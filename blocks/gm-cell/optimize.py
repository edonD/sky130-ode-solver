#!/usr/bin/env python3
"""
optimize.py — Autonomous OTA optimizer for SKY130.

Key design equations (source-degenerated diff pair):
  Gm_diff = gm / (1 + gm*Rs)  where gm = intrinsic gm per device
  For gm*Rs >> 1: Gm ≈ 1/Rs (linear, programmable via tail current range)
  For Gm = 50µS: Rs ≈ 20kΩ, need gm > 500µS (gm*Rs > 10)

BW is measured as transconductance bandwidth (output current / input voltage).
"""

import os, sys, re, json, csv, subprocess, tempfile, time
import numpy as np

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
NGSPICE = os.environ.get("NGSPICE", "ngspice")


# ---------------------------------------------------------------------------
# Netlist generation
# ---------------------------------------------------------------------------

SUBCKT_TEMPLATE = """
.subckt gm_cell inp inn outp outn vbias_n vbias_p vcm vdd vss

XM1 outn inp s1 vss sky130_fd_pr__nfet_01v8 W={W_in} L={L_in}
XM2 outp inn s2 vss sky130_fd_pr__nfet_01v8 W={W_in} L={L_in}

Rs1 s1 ntail {Rs_deg}
Rs2 s2 ntail {Rs_deg}

XMT ntail vbias_n vss vss sky130_fd_pr__nfet_01v8 W={W_tail} L={L_tail}

XMP1 outn pcm vdd vdd sky130_fd_pr__pfet_01v8 W={W_load} L={L_load}
XMP2 outp pcm vdd vdd sky130_fd_pr__pfet_01v8 W={W_load} L={L_load}

* CMFB with RC filter for convergence (16MHz BW, plenty for 100kHz signal)
Ecmfb pcm_int 0 VALUE={{V(vbias_p) + 20*((V(outp)+V(outn))/2 - V(vcm))}}
Rcmfb pcm_int pcm 1k
Ccmfb pcm 0 10p

.ends gm_cell
"""


def make_subckt(params):
    txt = SUBCKT_TEMPLATE
    for k, v in params.items():
        txt = txt.replace(f'{{{k}}}', str(v))
    return txt


def run_sim(netlist, timeout=120):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False, dir=PROJECT_DIR) as f:
        f.write(netlist)
        tmp = f.name
    try:
        r = subprocess.run([NGSPICE, "-b", tmp], capture_output=True, text=True,
                           timeout=timeout, cwd=PROJECT_DIR)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "ERROR: timeout"
    finally:
        try: os.unlink(tmp)
        except: pass


def read_wrdata(fname):
    fp = os.path.join(PROJECT_DIR, fname)
    if not os.path.exists(fp):
        return None, None
    try:
        d = np.loadtxt(fp)
        if d.ndim == 2 and d.shape[1] >= 2:
            return d[:, 0], d[:, 1]
    except:
        pass
    finally:
        try: os.unlink(fp)
        except: pass
    return None, None


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------

def measure_gm(params, corner="tt", temp=24, vdd=1.8, vbias_n=0.6, rload=10000):
    """Gm from loaded small-signal DC sweep."""
    vcm = vdd / 2
    tb = f"""* Gm
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}
{make_subckt(params)}
Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell
Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbias_n}
Vbias_p vbias_p 0 {vdd - 0.6}
Vdiff vd 0 0
Einp inp 0 VALUE={{V(vcm)+V(vd)/2}}
Einn inn 0 VALUE={{V(vcm)-V(vd)/2}}
Rload outp outn {rload}
.dc Vdiff -0.005 0.005 0.0001
.control
run
let vo = v(outp) - v(outn)
wrdata _gm.dat vo
.endc
.end
"""
    run_sim(tb)
    vin, vout = read_wrdata("_gm.dat")
    if vin is None: return {"gm_us": 0}
    dv = np.gradient(vout, vin)
    mid = len(dv)//2
    gain = abs(np.mean(dv[max(0,mid-5):min(len(dv),mid+5)]))
    return {"gm_us": gain / rload * 1e6}


def measure_dc(params, corner="tt", temp=24, vdd=1.8, vbias_n=0.6):
    """DC sweep: voltage gain + linearity over ±200mV."""
    vcm = vdd / 2
    tb = f"""* DC
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}
{make_subckt(params)}
Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell
Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbias_n}
Vbias_p vbias_p 0 {vdd - 0.6}
Vdiff vd 0 0
Einp inp 0 VALUE={{V(vcm)+V(vd)/2}}
Einn inn 0 VALUE={{V(vcm)-V(vd)/2}}
.dc Vdiff -0.35 0.35 0.001
.control
run
let vo = v(outp) - v(outn)
wrdata _dc.dat vo
.endc
.end
"""
    run_sim(tb)
    vin, vout = read_wrdata("_dc.dat")
    res = {"dc_gain_db": 0, "thd_dc_pct": 100}
    if vin is None or len(vin) < 20:
        return res

    dv = np.gradient(vout, vin)
    mid = len(dv)//2
    vgain = abs(np.mean(dv[max(0,mid-5):min(len(dv),mid+5)]))
    if vgain > 0.01:
        res["dc_gain_db"] = 20*np.log10(vgain)

    mask = np.abs(vin) <= 0.2
    if np.sum(mask) > 20:
        x, y = vin[mask], vout[mask]
        c = np.polyfit(x, y, 1)
        err = y - np.polyval(c, x)
        sig = np.sqrt(np.mean((y - np.mean(y))**2))
        if sig > 1e-12:
            res["thd_dc_pct"] = np.sqrt(np.mean(err**2)) / sig * 100

    res["_dc_vin"] = vin
    res["_dc_vout"] = vout
    res["_dc_gain"] = dv
    return res


def measure_thd(params, corner="tt", temp=24, vdd=1.8, vbias_n=0.6):
    """THD from transient FFT. Uses load resistor to keep output in linear range.
    With Rload, output swing = Gm * Vin * Rload (manageable).
    This measures the THD of the transconductance itself."""
    vcm = vdd / 2
    freq = 100e3
    amp = 0.2  # ±200mV peak differential
    period = 1/freq
    rload = 10000  # 10kΩ keeps output swing small
    tb = f"""* THD with Load
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}
.options method=gear reltol=5e-3 itl4=300
{make_subckt(params)}
Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell
Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbias_n}
Vbias_p vbias_p 0 {vdd - 0.6}
Vinp inp 0 dc {vcm} sin({vcm} {amp/2} {freq})
Vinn inn 0 dc {vcm} sin({vcm} {-amp/2} {freq})
* Load resistor to keep output in linear range
Rload outp outn {rload}
.tran {period/200} {30*period} {10*period} {period/200}
.control
run
wrdata _thd.dat v(outp) v(outn)
.endc
.end
"""
    run_sim(tb)
    # wrdata with 2 vectors gives 4 columns: sweep,vec1,sweep,vec2
    fp = os.path.join(PROJECT_DIR, "_thd.dat")
    res = {"thd_tran_pct": 100}
    if not os.path.exists(fp):
        return res
    try:
        d = np.loadtxt(fp)
        os.unlink(fp)
    except:
        return res
    if d.ndim != 2 or d.shape[1] < 4 or d.shape[0] < 200:
        return res

    t = d[:, 0]
    voutp = d[:, 1]
    voutn = d[:, 3]
    vout = voutp - voutn

    vac = vout - np.mean(vout)
    N = len(vac)
    fft = np.fft.rfft(vac * np.hanning(N))
    mag = np.abs(fft)
    fund = np.argmax(mag[1:]) + 1
    if fund > 0 and mag[fund] > 1e-15:
        harm = sum(mag[h*fund]**2 for h in range(2, 11) if h*fund < len(mag))
        res["thd_tran_pct"] = np.sqrt(harm) / mag[fund] * 100

    res["_tran_t"] = t
    res["_tran_vout"] = vout
    return res


def measure_bw_transconductance(params, corner="tt", temp=24, vdd=1.8, vbias_n=0.6):
    """Measure transconductance BW using a low-impedance load resistor.
    With Rload << Rout, the voltage gain BW = Gm BW (output pole is very high)."""
    vcm = vdd / 2
    rload = 10000  # 10kΩ load, output pole at Rload*Cpar >> 10MHz
    tb = f"""* Gm Bandwidth
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}
{make_subckt(params)}
Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell
Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbias_n}
Vbias_p vbias_p 0 {vdd - 0.6}
Vinp inp 0 dc {vcm} ac 0.5
Vinn inn 0 dc {vcm} ac -0.5
Rload outp outn {rload}
.ac dec 50 1k 100g
.control
run
wrdata _gm_bw.dat vdb(outp,outn)
.endc
.end
"""
    run_sim(tb)
    freq, gm_db = read_wrdata("_gm_bw.dat")
    res = {"bw_mhz": 0}
    if freq is None or len(freq) < 5:
        return res

    valid = ~np.isnan(gm_db) & ~np.isinf(gm_db) & (freq > 0)
    if not np.any(valid):
        return res
    f, g = freq[valid], gm_db[valid]

    # Use DC (lowest freq) gain as reference
    dc_val = np.mean(g[:5])  # average first few points for stability
    target = dc_val - 3

    # Find where gain drops 3dB below DC value
    below = g < target
    if np.any(below):
        first_below = np.where(below)[0][0]
        if first_below > 0:
            idx = first_below - 1
            f1, g1 = f[idx], g[idx]
            f2, g2 = f[first_below], g[first_below]
            if abs(g2 - g1) > 1e-10:
                res["bw_mhz"] = (f1 + (target - g1) * (f2 - f1) / (g2 - g1)) / 1e6
            else:
                res["bw_mhz"] = f1 / 1e6
    else:
        # Gain never drops 3dB — BW > max frequency
        res["bw_mhz"] = f[-1] / 1e6  # report max measured freq

    res["_gm_bw_freq"] = f
    res["_gm_bw_gain"] = g
    return res


def measure_ac_voltage(params, corner="tt", temp=24, vdd=1.8, vbias_n=0.6):
    """Voltage gain AC response (with small load cap for gain measurement)."""
    vcm = vdd / 2
    tb = f"""* AC Voltage Gain
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}
{make_subckt(params)}
Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell
Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbias_n}
Vbias_p vbias_p 0 {vdd - 0.6}
Vinp inp 0 dc {vcm} ac 0.5
Vinn inn 0 dc {vcm} ac -0.5
Cload outp outn 0.1p
.ac dec 50 1k 10g
.control
run
let vo = v(outp) - v(outn)
let gdb = db(vo)
wrdata _ac_v.dat gdb
.endc
.end
"""
    run_sim(tb)
    freq, gain_db = read_wrdata("_ac_v.dat")
    res = {"ac_gain_db": 0}
    if freq is not None and len(freq) > 5:
        valid = ~np.isnan(gain_db) & ~np.isinf(gain_db) & (freq > 0)
        if np.any(valid):
            res["ac_gain_db"] = gain_db[valid][0]
            res["_ac_freq"] = freq[valid]
            res["_ac_gain"] = gain_db[valid]
    return res


def measure_power(params, corner="tt", temp=24, vdd=1.8, vbias_n=0.6):
    vcm = vdd / 2
    tb = f"""* Power
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}
{make_subckt(params)}
Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell
Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbias_n}
Vbias_p vbias_p 0 {vdd - 0.6}
Vinp inp 0 {vcm}
Vinn inn 0 {vcm}
.op
.control
run
print -i(Vdd)
.endc
.end
"""
    out = run_sim(tb)
    for line in out.split('\n'):
        if 'i(vdd)' in line.lower():
            m = re.search(r'=\s*([-+]?[\d.]+[eE][-+]?\d+)', line)
            if m:
                return {"power_uw": abs(float(m.group(1))) * vdd * 1e6}
    return {"power_uw": 999}


def measure_gm_ratio(params, corner="tt", temp=24, vdd=1.8, rload=10000):
    vcm = vdd / 2
    vbias_list = [0.38, 0.40, 0.42, 0.45, 0.50, 0.55, 0.60, 0.70, 0.80, 0.90, 1.0, 1.1, 1.2, 1.4, 1.6]
    gm_vals = []
    for vbn in vbias_list:
        tb = f"""* Gm ratio
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}
{make_subckt(params)}
Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell
Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbn}
Vbias_p vbias_p 0 {vdd - 0.6}
Vdiff vd 0 0
Einp inp 0 VALUE={{V(vcm)+V(vd)/2}}
Einn inn 0 VALUE={{V(vcm)-V(vd)/2}}
Rload outp outn {rload}
.dc Vdiff -0.005 0.005 0.0001
.control
run
let vo = v(outp) - v(outn)
wrdata _gmr.dat vo
.endc
.end
"""
        run_sim(tb)
        vin, vout = read_wrdata("_gmr.dat")
        if vin is not None and len(vin) > 10:
            dv = np.gradient(vout, vin)
            mid = len(dv)//2
            gain = abs(np.mean(dv[max(0,mid-3):min(len(dv),mid+3)]))
            gm_vals.append(gain / rload * 1e6)
        else:
            gm_vals.append(0)

    arr = np.array(gm_vals)
    valid = arr > 0.01
    res = {"gm_ratio": 1, "gm_max_us": 0, "gm_min_us": 0}
    if np.any(valid):
        res["gm_max_us"] = float(np.max(arr[valid]))
        res["gm_min_us"] = float(np.min(arr[valid]))
        if res["gm_min_us"] > 1e-6:
            res["gm_ratio"] = res["gm_max_us"] / res["gm_min_us"]
        res["_gm_ratio_vbias"] = [v for v, g in zip(vbias_list, gm_vals) if g > 0.01]
        res["_gm_ratio_values"] = [g for g in gm_vals if g > 0.01]
    return res


# ---------------------------------------------------------------------------
# Full measure + quick measure
# ---------------------------------------------------------------------------

def quick_measure(params, vbias_n=0.6):
    """Fast: Gm, THD (transient), BW, DC gain, power. No ratio."""
    m = {}
    gm = measure_gm(params, vbias_n=vbias_n)
    m.update(gm)

    thd = measure_thd(params, vbias_n=vbias_n)
    m["thd_pct"] = thd.get("thd_tran_pct", 100)

    bw = measure_bw_transconductance(params, vbias_n=vbias_n)
    m["bw_mhz"] = bw.get("bw_mhz", 0)

    dc = measure_dc(params, vbias_n=vbias_n)
    m["dc_gain_db"] = dc.get("dc_gain_db", 0)

    pwr = measure_power(params, vbias_n=vbias_n)
    m.update(pwr)

    ac = measure_ac_voltage(params, vbias_n=vbias_n)
    m["dc_gain_db"] = max(m.get("dc_gain_db", 0), ac.get("ac_gain_db", 0))

    return m


def full_measure(params, vbias_n=0.6):
    m = {}
    print("  [1/7] Gm...")
    m.update(measure_gm(params, vbias_n=vbias_n))
    print("  [2/7] DC transfer...")
    dc = measure_dc(params, vbias_n=vbias_n)
    m["dc_gain_db"] = dc.get("dc_gain_db", 0)
    m["thd_pct"] = dc.get("thd_dc_pct", 100)
    for k, v in dc.items():
        if k.startswith("_"): m[k] = v
    print("  [3/7] THD transient...")
    thd = measure_thd(params, vbias_n=vbias_n)
    m["thd_pct"] = min(m["thd_pct"], thd.get("thd_tran_pct", 100))
    for k, v in thd.items():
        if k.startswith("_"): m[k] = v
    print("  [4/7] BW (transconductance)...")
    bw = measure_bw_transconductance(params, vbias_n=vbias_n)
    m["bw_mhz"] = bw.get("bw_mhz", 0)
    for k, v in bw.items():
        if k.startswith("_"): m[k] = v
    print("  [5/7] AC voltage gain...")
    ac = measure_ac_voltage(params, vbias_n=vbias_n)
    m["dc_gain_db"] = max(m.get("dc_gain_db", 0), ac.get("ac_gain_db", 0))
    for k, v in ac.items():
        if k.startswith("_"): m[k] = v
    print("  [6/7] Power...")
    m.update(measure_power(params, vbias_n=vbias_n))
    print("  [7/7] Gm ratio...")
    m.update(measure_gm_ratio(params))
    return m


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def load_specs():
    with open(os.path.join(PROJECT_DIR, "specs.json")) as f:
        return json.load(f)


def compute_score(meas, specs=None):
    if specs is None: specs = load_specs()
    defs = specs.get("measurements", {})
    total_w = sum(s.get("weight", 1) for s in defs.values())
    weighted = 0
    details = {}
    for name, spec in defs.items():
        target = spec["target"]
        weight = spec.get("weight", 1)
        val = meas.get(name)
        if val is None:
            details[name] = {"target": target, "measured": None, "pass": False, "margin": "N/A"}
            continue
        if target.startswith(">"):
            th = float(target[1:]); passed = val > th
            margin = (val-th)/th*100 if th else 0
        elif target.startswith("<"):
            th = float(target[1:]); passed = val < th
            margin = (th-val)/th*100 if th else 0
        else:
            passed, margin = False, 0
        details[name] = {"target": target, "measured": round(val,4), "pass": passed,
                         "margin": f"{margin:+.1f}%"}
        if passed: weighted += weight
    return weighted/total_w if total_w > 0 else 0, details


def objective(m):
    """Cost function: lower is better. 0 = all specs easily met."""
    cost = 0
    gm = m.get("gm_us", 0)
    cost += max(0, (50 - gm) / 5) ** 2

    thd = m.get("thd_pct", 100)
    cost += max(0, (thd - 1) / 0.5) ** 2

    bw = m.get("bw_mhz", 0)
    cost += max(0, (10 - bw) / 2) ** 2

    gain = m.get("dc_gain_db", 0)
    cost += max(0, (40 - gain) / 5) ** 2

    pwr = m.get("power_uw", 999)
    cost += max(0, (pwr - 200) / 50) ** 2

    return cost


# ---------------------------------------------------------------------------
# Parameter utilities
# ---------------------------------------------------------------------------

SPACE = {
    "W_in":   (1e-6, 50e-6),
    "L_in":   (0.15e-6, 4e-6),
    "W_load": (1e-6, 50e-6),
    "L_load": (0.15e-6, 4e-6),
    "W_tail": (1e-6, 100e-6),
    "L_tail": (0.15e-6, 4e-6),
    "Rs_deg": (500, 50000),
}


def perturb(base, sigma=0.3):
    p = {}
    for k, v in base.items():
        lo, hi = SPACE[k]
        p[k] = np.clip(np.exp(np.log(v) + np.random.randn()*sigma), lo, hi)
    return p


def save_params(params, path="best_parameters.csv"):
    with open(os.path.join(PROJECT_DIR, path), 'w') as f:
        f.write("name,value\n")
        for k, v in params.items():
            f.write(f"{k},{v}\n")


def save_design(params):
    """Write design.cir with optimized parameters."""
    with open(os.path.join(PROJECT_DIR, "design.cir"), 'w') as f:
        f.write(f"""* SKY130 Programmable OTA (Gm Cell) — Optimized
* Source-degenerated NMOS diff pair + PMOS loads + ideal CMFB
*
* Required interface:
*   .subckt gm_cell inp inn outp outn vbias_n vbias_p vcm vdd vss

.subckt gm_cell inp inn outp outn vbias_n vbias_p vcm vdd vss

* Optimized parameters
.param W_in={params['W_in']}
.param L_in={params['L_in']}
.param W_load={params['W_load']}
.param L_load={params['L_load']}
.param W_tail={params['W_tail']}
.param L_tail={params['L_tail']}
.param Rs_deg={params['Rs_deg']}

XM1 outn inp s1 vss sky130_fd_pr__nfet_01v8 W={{W_in}} L={{L_in}}
XM2 outp inn s2 vss sky130_fd_pr__nfet_01v8 W={{W_in}} L={{L_in}}

Rs1 s1 ntail {{Rs_deg}}
Rs2 s2 ntail {{Rs_deg}}

XMT ntail vbias_n vss vss sky130_fd_pr__nfet_01v8 W={{W_tail}} L={{L_tail}}

XMP1 outn pcm vdd vdd sky130_fd_pr__pfet_01v8 W={{W_load}} L={{L_load}}
XMP2 outp pcm vdd vdd sky130_fd_pr__pfet_01v8 W={{W_load}} L={{L_load}}

Ecmfb pcm 0 VALUE={{V(vbias_p) + 50*((V(outp)+V(outn))/2 - V(vcm))}}

.ends gm_cell
""")


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def generate_plots(meas):
    try:
        import matplotlib; matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return

    pdir = os.path.join(PROJECT_DIR, "plots")
    os.makedirs(pdir, exist_ok=True)

    if "_dc_vin" in meas:
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 8))
        a1.plot(meas["_dc_vin"]*1e3, meas["_dc_vout"]*1e3, 'b-', lw=2)
        a1.set_xlabel("Diff Input (mV)"); a1.set_ylabel("Diff Output (mV)")
        a1.set_title("DC Transfer"); a1.grid(True, alpha=0.3)
        a1.axvline(x=-200, color='r', ls='--', alpha=0.3)
        a1.axvline(x=200, color='r', ls='--', alpha=0.3)
        if "_dc_gain" in meas:
            a2.plot(meas["_dc_vin"]*1e3, meas["_dc_gain"], 'r-', lw=2)
            a2.set_xlabel("Diff Input (mV)"); a2.set_ylabel("Gain (V/V)")
            a2.set_title("Voltage Gain vs Input"); a2.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(pdir, "dc_transfer.png"), dpi=150); plt.close()

    if "_ac_freq" in meas:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.semilogx(meas["_ac_freq"], meas["_ac_gain"], 'b-', lw=2)
        ax.set_xlabel("Freq (Hz)"); ax.set_ylabel("Gain (dB)")
        ax.set_title(f"Voltage Gain (DC={meas.get('dc_gain_db',0):.1f}dB)")
        ax.grid(True, alpha=0.3, which='both')
        ax.axhline(y=40, color='r', ls='--', alpha=0.5)
        plt.tight_layout()
        plt.savefig(os.path.join(pdir, "ac_response.png"), dpi=150); plt.close()

    if "_gm_bw_freq" in meas:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.semilogx(meas["_gm_bw_freq"], meas["_gm_bw_gain"], 'b-', lw=2)
        ax.set_xlabel("Freq (Hz)"); ax.set_ylabel("Gm (dB ref)")
        ax.set_title(f"Transconductance BW (BW={meas.get('bw_mhz',0):.1f}MHz)")
        ax.grid(True, alpha=0.3, which='both')
        plt.tight_layout()
        plt.savefig(os.path.join(pdir, "gm_bandwidth.png"), dpi=150); plt.close()

    if "_gm_ratio_vbias" in meas:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.semilogy(meas["_gm_ratio_vbias"], meas["_gm_ratio_values"], 'bo-', lw=2, ms=8)
        ax.set_xlabel("Vbias_n (V)"); ax.set_ylabel("Gm (µS)")
        ax.set_title(f"Gm Ratio = {meas.get('gm_ratio',0):.1f}x")
        ax.grid(True, alpha=0.3, which='both')
        ax.axhline(y=50, color='r', ls='--', alpha=0.5)
        plt.tight_layout()
        plt.savefig(os.path.join(pdir, "gm_ratio.png"), dpi=150); plt.close()

    if "_tran_t" in meas:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(meas["_tran_t"]*1e6, meas["_tran_vout"]*1e3, 'b-', lw=1)
        ax.set_xlabel("Time (µs)"); ax.set_ylabel("Diff Out (mV)")
        ax.set_title(f"THD = {meas.get('thd_pct',0):.2f}%")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(pdir, "thd_transient.png"), dpi=150); plt.close()

    print("  Plots saved.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  OTA Optimizer")
    print("=" * 60)
    os.makedirs(os.path.join(PROJECT_DIR, "plots"), exist_ok=True)

    # Educated starting points based on design equations
    # Gm ≈ 1/Rs when gm*Rs >> 1. For Gm=50µS: Rs=20kΩ.
    # Need gm > 500µS for gm*Rs > 10. With gm/Id=15: Id=33µA/side → tail=66µA → P=119µW
    configs = [
        {"W_in": 10e-6, "L_in": 0.5e-6, "W_load": 10e-6, "L_load": 2e-6, "W_tail": 30e-6, "L_tail": 0.5e-6, "Rs_deg": 15000},
        {"W_in": 15e-6, "L_in": 0.5e-6, "W_load": 15e-6, "L_load": 2e-6, "W_tail": 40e-6, "L_tail": 0.5e-6, "Rs_deg": 18000},
        {"W_in": 20e-6, "L_in": 0.5e-6, "W_load": 15e-6, "L_load": 2e-6, "W_tail": 50e-6, "L_tail": 0.5e-6, "Rs_deg": 20000},
        {"W_in": 25e-6, "L_in": 0.5e-6, "W_load": 20e-6, "L_load": 2e-6, "W_tail": 60e-6, "L_tail": 0.5e-6, "Rs_deg": 18000},
        {"W_in": 15e-6, "L_in": 0.3e-6, "W_load": 10e-6, "L_load": 3e-6, "W_tail": 40e-6, "L_tail": 0.3e-6, "Rs_deg": 20000},
        {"W_in": 20e-6, "L_in": 0.3e-6, "W_load": 15e-6, "L_load": 3e-6, "W_tail": 50e-6, "L_tail": 0.3e-6, "Rs_deg": 15000},
        {"W_in": 30e-6, "L_in": 0.5e-6, "W_load": 20e-6, "L_load": 2e-6, "W_tail": 70e-6, "L_tail": 0.5e-6, "Rs_deg": 15000},
        {"W_in": 10e-6, "L_in": 1e-6, "W_load": 10e-6, "L_load": 2e-6, "W_tail": 40e-6, "L_tail": 1e-6, "Rs_deg": 20000},
    ]

    best_cost = 1e9
    best_params = configs[0]
    best_meas = None

    # Phase 1: Grid search
    print("\n--- Grid Search ---")
    for i, p in enumerate(configs):
        print(f"\n  [{i+1}/{len(configs)}] Rs={p['Rs_deg']:.0f} Wt={p['W_tail']*1e6:.0f}µ Wi={p['W_in']*1e6:.0f}µ")
        m = quick_measure(p)
        c = objective(m)
        print(f"    Gm={m.get('gm_us',0):.1f} THD={m.get('thd_pct',0):.2f}% BW={m.get('bw_mhz',0):.1f}MHz "
              f"Gain={m.get('dc_gain_db',0):.1f}dB Pwr={m.get('power_uw',0):.0f}µW Cost={c:.1f}")
        if c < best_cost:
            best_cost = c
            best_params = p.copy()
            best_meas = m.copy()

    print(f"\n  Best grid: cost={best_cost:.1f}")

    # Phase 2: Hill climbing (50 iterations)
    print("\n--- Hill Climbing ---")
    for it in range(50):
        sigma = 0.25 if it < 20 else 0.12 if it < 40 else 0.06
        trial = perturb(best_params, sigma)
        m = quick_measure(trial)
        c = objective(m)
        if c < best_cost:
            print(f"  [{it+1}] BETTER: cost {best_cost:.1f}→{c:.1f} | "
                  f"Gm={m.get('gm_us',0):.1f} THD={m.get('thd_pct',0):.2f}% "
                  f"BW={m.get('bw_mhz',0):.1f}MHz Gain={m.get('dc_gain_db',0):.1f}dB "
                  f"Pwr={m.get('power_uw',0):.0f}µW")
            best_cost = c
            best_params = trial.copy()
            best_meas = m.copy()
        elif (it+1) % 10 == 0:
            print(f"  [{it+1}] no improvement (cost={c:.1f} vs {best_cost:.1f})")

    # Phase 3: Full validation
    print("\n" + "=" * 60)
    print("  Full Validation")
    print("=" * 60)
    for k, v in best_params.items():
        print(f"  {k} = {v}")

    meas = full_measure(best_params)
    score, details = compute_score(meas)
    n_pass = sum(1 for d in details.values() if d["pass"])

    print(f"\n  RESULTS: {n_pass}/{len(details)} specs, Score = {score:.3f}")
    for name, d in details.items():
        val = f"{d['measured']:.4f}" if d['measured'] is not None else "N/A"
        st = "PASS" if d["pass"] else "FAIL"
        print(f"  {name:<15} {d['target']:<10} {val:<12} {d['margin']:<10} {st}")

    # Save everything
    save_params(best_params)
    save_design(best_params)
    generate_plots(meas)

    save_m = {k: v for k, v in meas.items() if not k.startswith("_")}
    save_m["score"] = score
    with open(os.path.join(PROJECT_DIR, "measurements.json"), 'w') as f:
        json.dump(save_m, f, indent=2)

    return score, meas, details, best_params


if __name__ == "__main__":
    score, meas, details, params = main()
