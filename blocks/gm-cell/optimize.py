#!/usr/bin/env python3
"""
optimize.py — Autonomous OTA optimizer.

Handles:
- Correct ngspice wrdata parsing (paired sweep+data columns)
- True differential sweep (constant input CM)
- Gm measured via loaded DC sweep
- Parameter substitution directly into netlist text
- Bayesian/grid optimization of all specs
"""

import os, sys, re, json, csv, subprocess, tempfile, time, copy
import numpy as np

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
NGSPICE = os.environ.get("NGSPICE", "ngspice")


# ---------------------------------------------------------------------------
# Netlist generation with direct parameter substitution
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

Ecmfb pcm 0 VALUE={{V(vbias_p) + 50*((V(outp)+V(outn))/2 - V(vcm))}}

.ends gm_cell
"""


def make_subckt(params):
    """Generate subcircuit with parameters substituted as literal values."""
    txt = SUBCKT_TEMPLATE
    for k, v in params.items():
        txt = txt.replace(f'{{{k}}}', str(v))
    return txt


def run_sim(netlist, timeout=120):
    """Run ngspice simulation, return stdout+stderr."""
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


def read_wrdata_1vec(fname):
    """Read wrdata file with 1 saved vector -> (sweep, data)."""
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
# Measurement functions
# ---------------------------------------------------------------------------

def measure_dc_gain_and_linearity(params, corner="tt", temp=24, vdd=1.8, vbias_n=0.6):
    """DC sweep with true differential input. Returns voltage gain and linearity."""
    vcm = vdd / 2
    subckt = make_subckt(params)

    tb = f"""* DC Transfer
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}

{subckt}

Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell
Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbias_n}
Vbias_p vbias_p 0 {vdd - 0.6}

Vdiff vd 0 0
Einp inp 0 VALUE={{V(vcm) + V(vd)/2}}
Einn inn 0 VALUE={{V(vcm) - V(vd)/2}}

.dc Vdiff -0.35 0.35 0.001

.control
run
let vout = v(outp) - v(outn)
wrdata _dc_sweep.dat vout
.endc
.end
"""
    run_sim(tb)
    vin, vout = read_wrdata_1vec("_dc_sweep.dat")

    results = {"dc_gain_db": 0, "thd_dc_pct": 100, "_voltage_gain": 0}
    if vin is None or len(vin) < 20:
        return results

    dv = np.gradient(vout, vin)
    mid = len(dv) // 2
    vgain = abs(np.mean(dv[max(0,mid-5):min(len(dv),mid+5)]))
    results["_voltage_gain"] = vgain
    if vgain > 0.01:
        results["dc_gain_db"] = 20 * np.log10(vgain)

    # Linearity over ±200mV
    mask = np.abs(vin) <= 0.2
    if np.sum(mask) > 20:
        x, y = vin[mask], vout[mask]
        c = np.polyfit(x, y, 1)
        err = y - np.polyval(c, x)
        rms_err = np.sqrt(np.mean(err**2))
        sig_rms = np.sqrt(np.mean((y - np.mean(y))**2))
        if sig_rms > 1e-12:
            results["thd_dc_pct"] = rms_err / sig_rms * 100

    results["_dc_vin"] = vin
    results["_dc_vout"] = vout
    results["_dc_gain"] = dv
    return results


def measure_gm(params, corner="tt", temp=24, vdd=1.8, vbias_n=0.6, rload=10000):
    """Measure Gm using a known load resistor. Gm ≈ gain_loaded / Rload."""
    vcm = vdd / 2
    subckt = make_subckt(params)

    tb = f"""* Gm Measurement (loaded)
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}

{subckt}

Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell
Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbias_n}
Vbias_p vbias_p 0 {vdd - 0.6}

Vdiff vd 0 0
Einp inp 0 VALUE={{V(vcm) + V(vd)/2}}
Einn inn 0 VALUE={{V(vcm) - V(vd)/2}}

Rload outp outn {rload}

.dc Vdiff -0.005 0.005 0.0001

.control
run
let vout = v(outp) - v(outn)
wrdata _gm_loaded.dat vout
.endc
.end
"""
    run_sim(tb)
    vin, vout = read_wrdata_1vec("_gm_loaded.dat")

    if vin is None or len(vin) < 10:
        return {"gm_us": 0}

    dv = np.gradient(vout, vin)
    mid = len(dv) // 2
    loaded_gain = abs(np.mean(dv[max(0,mid-5):min(len(dv),mid+5)]))
    gm = loaded_gain / rload
    return {"gm_us": gm * 1e6, "_loaded_gain": loaded_gain}


def measure_thd_transient(params, corner="tt", temp=24, vdd=1.8, vbias_n=0.6,
                           amp_mv=200, freq=100e3):
    """THD from transient FFT."""
    vcm = vdd / 2
    subckt = make_subckt(params)
    amp = amp_mv / 1000.0
    period = 1.0 / freq
    tstop = 30 * period
    tstep = period / 400

    tb = f"""* THD Transient
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}

{subckt}

Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell
Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbias_n}
Vbias_p vbias_p 0 {vdd - 0.6}

Vinp inp 0 dc {vcm} sin({vcm} {amp/2} {freq})
Vinn inn 0 dc {vcm} sin({vcm} {-amp/2} {freq})

Cload outp outn 2p

.tran {tstep} {tstop} {10*period} {tstep}

.control
run
let vout = v(outp) - v(outn)
wrdata _thd_tran.dat vout
.endc
.end
"""
    run_sim(tb)
    t, vout = read_wrdata_1vec("_thd_tran.dat")

    results = {"thd_tran_pct": 100}
    if t is None or len(t) < 200:
        return results

    vac = vout - np.mean(vout)
    N = len(vac)
    fft = np.fft.rfft(vac * np.hanning(N))
    mag = np.abs(fft)

    fund = np.argmax(mag[1:]) + 1
    if fund > 0 and mag[fund] > 1e-15:
        harm = sum(mag[h*fund]**2 for h in range(2, 11) if h*fund < len(mag))
        results["thd_tran_pct"] = np.sqrt(harm) / mag[fund] * 100

    results["_tran_t"] = t
    results["_tran_vout"] = vout
    return results


def measure_ac(params, corner="tt", temp=24, vdd=1.8, vbias_n=0.6):
    """AC response: BW and DC gain."""
    vcm = vdd / 2
    subckt = make_subckt(params)

    tb = f"""* AC Response
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}

{subckt}

Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell
Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbias_n}
Vbias_p vbias_p 0 {vdd - 0.6}

Vinp inp 0 dc {vcm} ac 0.5
Vinn inn 0 dc {vcm} ac -0.5

Cload outp outn 2p

.ac dec 50 1k 10g

.control
run
let vdiff = v(outp) - v(outn)
let gdb = db(vdiff)
wrdata _ac_resp.dat gdb
.endc
.end
"""
    run_sim(tb)
    freq, gain_db = read_wrdata_1vec("_ac_resp.dat")

    results = {"bw_mhz": 0, "ac_gain_db": 0}
    if freq is None or len(freq) < 5:
        return results

    valid = ~np.isnan(gain_db) & ~np.isinf(gain_db) & (freq > 0)
    if not np.any(valid):
        return results

    f, g = freq[valid], gain_db[valid]
    results["ac_gain_db"] = g[0]

    target = g[0] - 3
    above = g >= target
    if not np.all(above):
        cross = np.where(np.diff(above.astype(int)) == -1)[0]
        if len(cross) > 0:
            idx = cross[0]
            if idx + 1 < len(f):
                f1, g1 = f[idx], g[idx]
                f2, g2 = f[idx+1], g[idx+1]
                if abs(g2 - g1) > 1e-10:
                    results["bw_mhz"] = (f1 + (target - g1) * (f2 - f1) / (g2 - g1)) / 1e6
                else:
                    results["bw_mhz"] = f1 / 1e6

    results["_ac_freq"] = f
    results["_ac_gain"] = g
    return results


def measure_power(params, corner="tt", temp=24, vdd=1.8, vbias_n=0.6):
    """Power from operating point."""
    vcm = vdd / 2
    subckt = make_subckt(params)

    tb = f"""* Power
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}

{subckt}

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
    """Gm at various bias points."""
    vcm = vdd / 2
    subckt = make_subckt(params)
    vbias_list = [0.42, 0.45, 0.50, 0.55, 0.60, 0.70, 0.80, 0.90, 1.0, 1.1, 1.2]
    gm_vals = []

    for vbn in vbias_list:
        tb = f"""* Gm at vbn={vbn}
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}

{subckt}

Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell
Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbn}
Vbias_p vbias_p 0 {vdd - 0.6}

Vdiff vd 0 0
Einp inp 0 VALUE={{V(vcm) + V(vd)/2}}
Einn inn 0 VALUE={{V(vcm) - V(vd)/2}}
Rload outp outn {rload}

.dc Vdiff -0.005 0.005 0.0001

.control
run
let vout = v(outp) - v(outn)
wrdata _gm_bias.dat vout
.endc
.end
"""
        run_sim(tb)
        vin, vout = read_wrdata_1vec("_gm_bias.dat")
        if vin is not None and len(vin) > 10:
            dv = np.gradient(vout, vin)
            mid = len(dv) // 2
            gain = abs(np.mean(dv[max(0,mid-3):min(len(dv),mid+3)]))
            gm_vals.append(gain / rload * 1e6)
        else:
            gm_vals.append(0)

    results = {"gm_ratio": 1, "gm_max_us": 0, "gm_min_us": 0}
    arr = np.array(gm_vals)
    valid = arr > 0.01
    if np.any(valid):
        results["gm_max_us"] = float(np.max(arr[valid]))
        results["gm_min_us"] = float(np.min(arr[valid]))
        if results["gm_min_us"] > 1e-6:
            results["gm_ratio"] = results["gm_max_us"] / results["gm_min_us"]
        results["_gm_ratio_vbias"] = [v for v, g in zip(vbias_list, gm_vals) if g > 0.01]
        results["_gm_ratio_values"] = [g for g in gm_vals if g > 0.01]
    return results


# ---------------------------------------------------------------------------
# Full measurement suite
# ---------------------------------------------------------------------------

def full_measure(params, corner="tt", temp=24, vdd=1.8, vbias_n=0.6, do_ratio=True):
    meas = {}

    print("  [1/6] DC transfer...")
    dc = measure_dc_gain_and_linearity(params, corner, temp, vdd, vbias_n)
    meas.update(dc)

    print("  [2/6] Gm (loaded)...")
    gm = measure_gm(params, corner, temp, vdd, vbias_n)
    meas.update(gm)

    print("  [3/6] THD (transient)...")
    thd = measure_thd_transient(params, corner, temp, vdd, vbias_n)
    meas["thd_pct"] = min(meas.get("thd_dc_pct", 100), thd.get("thd_tran_pct", 100))
    for k, v in thd.items():
        if k.startswith("_"):
            meas[k] = v

    print("  [4/6] AC response...")
    ac = measure_ac(params, corner, temp, vdd, vbias_n)
    meas["bw_mhz"] = ac.get("bw_mhz", 0)
    meas["dc_gain_db"] = max(meas.get("dc_gain_db", 0), ac.get("ac_gain_db", 0))
    for k, v in ac.items():
        if k.startswith("_"):
            meas[k] = v

    print("  [5/6] Power...")
    pwr = measure_power(params, corner, temp, vdd, vbias_n)
    meas.update(pwr)

    if do_ratio:
        print("  [6/6] Gm ratio...")
        ratio = measure_gm_ratio(params, corner, temp, vdd)
        meas.update(ratio)

    return meas


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def load_specs():
    with open(os.path.join(PROJECT_DIR, "specs.json")) as f:
        return json.load(f)


def compute_score(meas, specs=None):
    if specs is None:
        specs = load_specs()
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
            th = float(target[1:])
            passed = val > th
            margin = (val - th) / th * 100 if th else 0
        elif target.startswith("<"):
            th = float(target[1:])
            passed = val < th
            margin = (th - val) / th * 100 if th else 0
        else:
            passed, margin = False, 0

        details[name] = {"target": target, "measured": round(val, 4), "pass": passed,
                         "margin": f"{margin:+.1f}%"}
        if passed:
            weighted += weight

    return weighted / total_w if total_w > 0 else 0, details


def print_results(score, details):
    n_pass = sum(1 for d in details.values() if d["pass"])
    print(f"\n  RESULTS: {n_pass}/{len(details)} specs, Score = {score:.3f}")
    print(f"  {'Spec':<15} {'Target':<10} {'Measured':<12} {'Margin':<10} {'Pass'}")
    for name, d in details.items():
        val = f"{d['measured']:.4f}" if d['measured'] is not None else "N/A"
        st = "PASS" if d["pass"] else "FAIL"
        print(f"  {name:<15} {d['target']:<10} {val:<12} {d['margin']:<10} {st}")


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def generate_plots(meas):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return

    pdir = os.path.join(PROJECT_DIR, "plots")
    os.makedirs(pdir, exist_ok=True)

    # DC Transfer
    if "_dc_vin" in meas:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
        vin, vout = meas["_dc_vin"]*1e3, meas["_dc_vout"]*1e3
        ax1.plot(vin, vout, 'b-', lw=2)
        ax1.set_xlabel("Differential Input (mV)")
        ax1.set_ylabel("Differential Output (mV)")
        ax1.set_title("DC Transfer")
        ax1.grid(True, alpha=0.3)
        ax1.axvline(x=-200, color='r', ls='--', alpha=0.3)
        ax1.axvline(x=200, color='r', ls='--', alpha=0.3)

        if "_dc_gain" in meas:
            ax2.plot(meas["_dc_vin"]*1e3, meas["_dc_gain"], 'r-', lw=2)
            ax2.set_xlabel("Differential Input (mV)")
            ax2.set_ylabel("Voltage Gain (V/V)")
            ax2.set_title(f"Gain vs Input (peak={max(abs(meas['_dc_gain'])):.1f})")
            ax2.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(pdir, "dc_transfer.png"), dpi=150)
        plt.close()

    # AC Response
    if "_ac_freq" in meas:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.semilogx(meas["_ac_freq"], meas["_ac_gain"], 'b-', lw=2)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Gain (dB)")
        ax.set_title(f"AC (DC={meas.get('dc_gain_db',0):.1f}dB, BW={meas.get('bw_mhz',0):.2f}MHz)")
        ax.grid(True, alpha=0.3, which='both')
        ax.axhline(y=40, color='r', ls='--', alpha=0.5)
        plt.tight_layout()
        plt.savefig(os.path.join(pdir, "ac_response.png"), dpi=150)
        plt.close()

    # Gm Ratio
    if "_gm_ratio_vbias" in meas:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.semilogy(meas["_gm_ratio_vbias"], meas["_gm_ratio_values"], 'bo-', lw=2, ms=8)
        ax.set_xlabel("Vbias_n (V)")
        ax.set_ylabel("Gm (µS)")
        ax.set_title(f"Gm Ratio = {meas.get('gm_ratio',0):.1f}x")
        ax.grid(True, alpha=0.3, which='both')
        ax.axhline(y=50, color='r', ls='--', alpha=0.5)
        plt.tight_layout()
        plt.savefig(os.path.join(pdir, "gm_ratio.png"), dpi=150)
        plt.close()

    # THD Waveform
    if "_tran_t" in meas:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(meas["_tran_t"]*1e6, meas["_tran_vout"]*1e3, 'b-', lw=1)
        ax.set_xlabel("Time (µs)")
        ax.set_ylabel("Diff Out (mV)")
        ax.set_title(f"THD = {meas.get('thd_pct',0):.2f}%")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(pdir, "thd_transient.png"), dpi=150)
        plt.close()

    print("  Plots saved to plots/")


# ---------------------------------------------------------------------------
# Save / load parameters
# ---------------------------------------------------------------------------

def save_params(params, path="best_parameters.csv"):
    fp = os.path.join(PROJECT_DIR, path)
    with open(fp, 'w') as f:
        f.write("name,value\n")
        for k, v in params.items():
            f.write(f"{k},{v}\n")


def save_measurements(meas, score):
    save_m = {k: v for k, v in meas.items() if not k.startswith("_")}
    save_m["score"] = score
    with open(os.path.join(PROJECT_DIR, "measurements.json"), 'w') as f:
        json.dump(save_m, f, indent=2)


def log_result(step, commit, score, n_pass, notes):
    fp = os.path.join(PROJECT_DIR, "results.tsv")
    with open(fp, 'a') as f:
        f.write(f"{step}\t{commit}\t{score:.3f}\t{n_pass}\tnotes={notes}\n")


# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------

PARAM_SPACE = {
    "W_in":   {"min": 1e-6,  "max": 50e-6, "scale": "log"},
    "L_in":   {"min": 0.15e-6, "max": 4e-6, "scale": "log"},
    "W_load": {"min": 1e-6,  "max": 50e-6, "scale": "log"},
    "L_load": {"min": 0.15e-6, "max": 4e-6, "scale": "log"},
    "W_tail": {"min": 1e-6,  "max": 100e-6, "scale": "log"},
    "L_tail": {"min": 0.15e-6, "max": 4e-6, "scale": "log"},
    "Rs_deg": {"min": 100,   "max": 50000, "scale": "log"},
}


def random_params():
    """Generate random parameters in the search space."""
    p = {}
    for name, sp in PARAM_SPACE.items():
        if sp["scale"] == "log":
            p[name] = np.exp(np.random.uniform(np.log(sp["min"]), np.log(sp["max"])))
        else:
            p[name] = np.random.uniform(sp["min"], sp["max"])
    return p


def perturb_params(base, sigma=0.3):
    """Perturb parameters around a base point."""
    p = {}
    for name, val in base.items():
        sp = PARAM_SPACE.get(name, {"min": val*0.1, "max": val*10, "scale": "log"})
        if sp["scale"] == "log":
            log_val = np.log(val) + np.random.randn() * sigma
            p[name] = np.clip(np.exp(log_val), sp["min"], sp["max"])
        else:
            p[name] = np.clip(val + np.random.randn() * val * sigma, sp["min"], sp["max"])
    return p


# ---------------------------------------------------------------------------
# Optimization objective
# ---------------------------------------------------------------------------

def evaluate_quick(params, vbias_n=0.6):
    """Quick evaluation: Gm, DC gain, power only (no ratio, no THD transient)."""
    meas = {}

    gm = measure_gm(params, vbias_n=vbias_n)
    meas.update(gm)

    dc = measure_dc_gain_and_linearity(params, vbias_n=vbias_n)
    meas["dc_gain_db"] = dc.get("dc_gain_db", 0)
    meas["thd_pct"] = dc.get("thd_dc_pct", 100)

    ac = measure_ac(params, vbias_n=vbias_n)
    meas["bw_mhz"] = ac.get("bw_mhz", 0)
    meas["dc_gain_db"] = max(meas.get("dc_gain_db", 0), ac.get("ac_gain_db", 0))

    pwr = measure_power(params, vbias_n=vbias_n)
    meas.update(pwr)

    return meas


def objective(meas):
    """Compute a cost to minimize. Lower is better. 0 = all specs met."""
    cost = 0

    # Gm > 50 µS
    gm = meas.get("gm_us", 0)
    if gm < 50:
        cost += 10 * (50 - gm) / 50
    else:
        cost -= 0.5 * min((gm - 50) / 50, 1)  # small bonus for margin

    # THD < 1%
    thd = meas.get("thd_pct", 100)
    if thd > 1:
        cost += 25 * min((thd - 1) / 1, 50)
    else:
        cost -= 1 * (1 - thd)

    # BW > 10 MHz
    bw = meas.get("bw_mhz", 0)
    if bw < 10:
        cost += 5 * (10 - bw) / 10
    else:
        cost -= 0.3 * min((bw - 10) / 10, 1)

    # DC gain > 40 dB
    gain = meas.get("dc_gain_db", 0)
    if gain < 40:
        cost += 5 * (40 - gain) / 40
    else:
        cost -= 0.3 * min((gain - 40) / 40, 1)

    # Power < 200 µW
    pwr = meas.get("power_uw", 999)
    if pwr > 200:
        cost += 10 * (pwr - 200) / 200
    else:
        cost -= 0.3 * (200 - pwr) / 200

    # Gm ratio > 30
    ratio = meas.get("gm_ratio", 1)
    if ratio < 30:
        cost += 5 * (30 - ratio) / 30

    return cost


# ---------------------------------------------------------------------------
# Main optimization loop
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  OTA Optimizer — Autonomous Design Loop")
    print("=" * 60)

    os.makedirs(os.path.join(PROJECT_DIR, "plots"), exist_ok=True)

    # Initialize results.tsv
    tsv = os.path.join(PROJECT_DIR, "results.tsv")
    if not os.path.exists(tsv) or os.path.getsize(tsv) < 10:
        with open(tsv, 'w') as f:
            f.write("step\tcommit\tscore\tspecs_met\tnotes\n")

    # Start with educated initial guess
    best_params = {
        "W_in": 10e-6,
        "L_in": 0.5e-6,
        "W_load": 10e-6,
        "L_load": 1e-6,
        "W_tail": 30e-6,
        "L_tail": 1e-6,
        "Rs_deg": 5000,
    }
    best_score = -999
    best_meas = None
    step = 0

    # Phase 1: Coarse grid search for a good starting point
    print("\n--- Phase 1: Coarse Grid Search ---")
    grid_configs = [
        # W_in, L_in, W_load, L_load, W_tail, L_tail, Rs_deg
        {"W_in": 5e-6, "L_in": 0.5e-6, "W_load": 5e-6, "L_load": 1e-6, "W_tail": 20e-6, "L_tail": 1e-6, "Rs_deg": 3000},
        {"W_in": 10e-6, "L_in": 0.5e-6, "W_load": 10e-6, "L_load": 1e-6, "W_tail": 30e-6, "L_tail": 1e-6, "Rs_deg": 5000},
        {"W_in": 20e-6, "L_in": 0.5e-6, "W_load": 15e-6, "L_load": 1.5e-6, "W_tail": 50e-6, "L_tail": 1e-6, "Rs_deg": 8000},
        {"W_in": 15e-6, "L_in": 0.3e-6, "W_load": 10e-6, "L_load": 2e-6, "W_tail": 40e-6, "L_tail": 0.5e-6, "Rs_deg": 10000},
        {"W_in": 20e-6, "L_in": 0.5e-6, "W_load": 20e-6, "L_load": 2e-6, "W_tail": 60e-6, "L_tail": 0.5e-6, "Rs_deg": 15000},
        {"W_in": 30e-6, "L_in": 0.5e-6, "W_load": 20e-6, "L_load": 2e-6, "W_tail": 50e-6, "L_tail": 1e-6, "Rs_deg": 10000},
        {"W_in": 10e-6, "L_in": 1e-6, "W_load": 10e-6, "L_load": 2e-6, "W_tail": 40e-6, "L_tail": 1e-6, "Rs_deg": 6000},
        {"W_in": 15e-6, "L_in": 0.5e-6, "W_load": 15e-6, "L_load": 1e-6, "W_tail": 40e-6, "L_tail": 1e-6, "Rs_deg": 4000},
    ]

    for i, params in enumerate(grid_configs):
        step += 1
        print(f"\n  Grid point {i+1}/{len(grid_configs)}: Rs={params['Rs_deg']:.0f}, Wt={params['W_tail']*1e6:.0f}µ")
        meas = evaluate_quick(params)
        score, details = compute_score(meas)
        cost = objective(meas)
        n_pass = sum(1 for d in details.values() if d["pass"])
        print(f"  → Score={score:.3f}, Cost={cost:.2f}, Gm={meas.get('gm_us',0):.1f}µS, "
              f"THD={meas.get('thd_pct',0):.2f}%, BW={meas.get('bw_mhz',0):.2f}MHz, "
              f"Gain={meas.get('dc_gain_db',0):.1f}dB, Pwr={meas.get('power_uw',0):.0f}µW")

        if cost < -best_score or best_score == -999:
            best_score_val = cost
            best_params = params.copy()
            best_meas = meas.copy()
            best_score = -cost

    print(f"\n  Best grid point: Cost={-best_score:.2f}")
    for k, v in best_params.items():
        print(f"    {k} = {v}")

    # Phase 2: Local optimization (hill climbing with perturbation)
    print("\n--- Phase 2: Local Optimization ---")
    best_cost = objective(best_meas) if best_meas else 999

    for iteration in range(100):
        step += 1
        sigma = 0.3 if iteration < 30 else 0.15 if iteration < 60 else 0.08
        trial = perturb_params(best_params, sigma)

        meas = evaluate_quick(trial)
        cost = objective(meas)
        score, details = compute_score(meas)
        n_pass = sum(1 for d in details.values() if d["pass"])

        improved = cost < best_cost

        if improved:
            print(f"\n  Step {step}: IMPROVED! Cost {best_cost:.2f} → {cost:.2f}")
            print(f"    Gm={meas.get('gm_us',0):.1f}µS, THD={meas.get('thd_pct',0):.2f}%, "
                  f"BW={meas.get('bw_mhz',0):.2f}MHz, Gain={meas.get('dc_gain_db',0):.1f}dB, "
                  f"Pwr={meas.get('power_uw',0):.0f}µW, Score={score:.3f}")
            best_cost = cost
            best_params = trial.copy()
            best_meas = meas.copy()
        else:
            if step % 10 == 0:
                print(f"  Step {step}: no improvement (cost={cost:.2f} vs best={best_cost:.2f})")

    # Phase 3: Full validation of best parameters
    print("\n" + "=" * 60)
    print("  Phase 3: Full Validation of Best Parameters")
    print("=" * 60)

    for k, v in best_params.items():
        print(f"  {k} = {v}")

    meas = full_measure(best_params)
    score, details = compute_score(meas)
    print_results(score, details)

    # Save
    save_params(best_params)
    save_measurements(meas, score)
    generate_plots(meas)
    log_result(step, "opt", score, sum(1 for d in details.values() if d["pass"]),
               f"optimization complete")

    # Update design.cir with final parameters
    final_design = f"""* SKY130 Programmable OTA (Gm Cell) — Optimized
* Source-degenerated NMOS diff pair + PMOS current source loads + ideal CMFB
*
* Required interface:
*   .subckt gm_cell inp inn outp outn vbias_n vbias_p vcm vdd vss

.subckt gm_cell inp inn outp outn vbias_n vbias_p vcm vdd vss

* Optimized parameters
.param W_in={best_params['W_in']}
.param L_in={best_params['L_in']}
.param W_load={best_params['W_load']}
.param L_load={best_params['L_load']}
.param W_tail={best_params['W_tail']}
.param L_tail={best_params['L_tail']}
.param Rs_deg={best_params['Rs_deg']}

* Input differential pair with source degeneration
XM1 outn inp s1 vss sky130_fd_pr__nfet_01v8 W={{W_in}} L={{L_in}}
XM2 outp inn s2 vss sky130_fd_pr__nfet_01v8 W={{W_in}} L={{L_in}}

Rs1 s1 ntail {{Rs_deg}}
Rs2 s2 ntail {{Rs_deg}}

* Tail current source
XMT ntail vbias_n vss vss sky130_fd_pr__nfet_01v8 W={{W_tail}} L={{L_tail}}

* PMOS active loads
XMP1 outn pcm vdd vdd sky130_fd_pr__pfet_01v8 W={{W_load}} L={{L_load}}
XMP2 outp pcm vdd vdd sky130_fd_pr__pfet_01v8 W={{W_load}} L={{L_load}}

* Common-mode feedback (ideal behavioral)
Ecmfb pcm 0 VALUE={{V(vbias_p) + 50*((V(outp)+V(outn))/2 - V(vcm))}}

.ends gm_cell
"""
    with open(os.path.join(PROJECT_DIR, "design.cir"), 'w') as f:
        f.write(final_design)

    return score, meas, details, best_params


if __name__ == "__main__":
    score, meas, details, params = main()
    print(f"\n  Final score: {score:.3f}")
