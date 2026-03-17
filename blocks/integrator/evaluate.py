"""
evaluate.py — Simulation and validation for Gm-C Integrator on SKY130.
"""

import os
import json
import re
import argparse
import subprocess
import tempfile
from typing import Dict, Tuple, Optional

import numpy as np

NGSPICE = os.environ.get("NGSPICE", "ngspice")
DESIGN_FILE = "design.cir"
SPECS_FILE = "specs.json"
PLOTS_DIR = "plots"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(PROJECT_DIR, "sky130_models")
GM_REF = 100e-6  # Reference Gm for voltage gain


def load_specs():
    with open(os.path.join(PROJECT_DIR, SPECS_FILE)) as f:
        return json.load(f)


def run_ngspice(netlist, timeout=180):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False, dir=PROJECT_DIR) as f:
        f.write(netlist)
        tmpfile = f.name
    try:
        r = subprocess.run([NGSPICE, "-b", tmpfile], capture_output=True, text=True,
                           timeout=timeout, cwd=PROJECT_DIR)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "ERROR: timeout"
    finally:
        try:
            os.unlink(tmpfile)
        except OSError:
            pass


def parse_meas(output, name):
    m = re.search(rf'{name}\s*=\s*([+-]?[\d.eE+-]+)', output, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def read_wrdata(filename):
    fp = os.path.join(PROJECT_DIR, filename)
    if not os.path.exists(fp):
        return None
    try:
        data = np.loadtxt(fp, skiprows=1)
        os.unlink(fp)
        return data
    except Exception:
        if os.path.exists(fp):
            os.unlink(fp)
        return None


def hdr(corner="tt", vdd=1.8, temp=27):
    return f""".lib "{MODEL_DIR}/sky130.lib.spice" {corner}
.include "{os.path.join(PROJECT_DIR, DESIGN_FILE)}"
.param vdd_val={vdd}
.param vcm_val={{vdd_val/2}}
Vdd vdd 0 {{vdd_val}}
Vss vss 0 0
Vcm vcm 0 {{vcm_val}}
Vbias vbias_n 0 0.6
"""


def measure_integration(corner="tt", temp=27, vdd=1.8):
    """Ramp test: extract C_int and UGF."""
    i_test = 5e-6
    netlist = f"""Integration Test
{hdr(corner, vdd, temp)}
Vrst reset 0 PWL(0 {{vdd_val}} 195n {{vdd_val}} 200n 0)
XI inp inn outp outn reset vbias_n vcm vdd vss integrator
Icp vcm inp DC {i_test}
Icn inn vcm DC {i_test}
.control
set filetype=ascii
option temp={temp}
tran 0.5n 2u UIC
meas tran vp1 FIND V(outp) AT=0.4u
meas tran vp2 FIND V(outp) AT=1.4u
meas tran vn1 FIND V(outn) AT=0.4u
meas tran vn2 FIND V(outn) AT=1.4u
print vp1 vp2 vn1 vn2
wrdata integ_data.txt V(outp) V(outn)
.endc
.end
"""
    out = run_ngspice(netlist)
    vp1, vp2 = parse_meas(out, "vp1"), parse_meas(out, "vp2")
    vn1, vn2 = parse_meas(out, "vn1"), parse_meas(out, "vn2")
    res = {}
    if vp1 is not None and vp2 is not None:
        ramp = (vp2 - vp1) / 1e-6
        if abs(ramp) > 0:
            c = abs(i_test / ramp)
            res["c_int_pf"] = c * 1e12
            res["unity_gain_freq_mhz"] = GM_REF / (2 * np.pi * c) / 1e6
        else:
            res["c_int_pf"] = 0
            res["unity_gain_freq_mhz"] = 0
        res["_ramp"] = ramp * 1e-6
    return res


def measure_leakage(corner="tt", temp=27, vdd=1.8, c_pf=5.0):
    """Leakage drift + DC gain from output impedance."""
    netlist = f"""Leakage Test
{hdr(corner, vdd, temp)}
Vrst reset 0 PWL(0 {{vdd_val}} 195n {{vdd_val}} 200n 0)
XI inp inn outp outn reset vbias_n vcm vdd vss integrator
Rp inp vcm 1T
Rn inn vcm 1T
.control
set filetype=ascii
option temp={temp}
tran 10n 55u UIC
meas tran vp1 FIND V(outp) AT=5u
meas tran vp2 FIND V(outp) AT=55u
meas tran vn1 FIND V(outn) AT=5u
meas tran vn2 FIND V(outn) AT=55u
print vp1 vp2 vn1 vn2
wrdata leak_data.txt V(outp) V(outn)
.endc
.end
"""
    out = run_ngspice(netlist)
    vp1, vp2 = parse_meas(out, "vp1"), parse_meas(out, "vp2")
    vn1, vn2 = parse_meas(out, "vn1"), parse_meas(out, "vn2")
    res = {}
    if vp1 is not None and vp2 is not None:
        dt = 50e-6
        drift_p = abs(vp2 - vp1) / dt
        drift_n = abs(vn2 - vn1) / dt if vn1 and vn2 else drift_p
        max_drift = max(drift_p, drift_n)
        res["leakage_mv_per_us"] = max_drift * 1e3 * 1e-6
        c = c_pf * 1e-12
        if max_drift > 1e-3:
            rout = vdd / 2 / (c * max_drift)
        else:
            rout = vdd / 2 / (c * 2.0)  # resolution limit
        res["dc_gain_db"] = 20 * np.log10(GM_REF * rout) if rout > 0 else 0
    else:
        res["leakage_mv_per_us"] = 100
        res["dc_gain_db"] = 0
    return res


def measure_swing(corner="tt", temp=27, vdd=1.8):
    """Output swing measurement."""
    netlist = f"""Swing Test
{hdr(corner, vdd, temp)}
Vrst reset 0 PWL(0 {{vdd_val}} 195n {{vdd_val}} 200n 0)
XI inp inn outp outn reset vbias_n vcm vdd vss integrator
Icp vcm inp DC 50u
Icn inn vcm DC 50u
.control
set filetype=ascii
option temp={temp}
tran 1n 10u UIC
meas tran vmax MAX V(outp)
meas tran vmin MIN V(outn)
print vmax vmin
.endc
.end
"""
    out = run_ngspice(netlist)
    vmax = parse_meas(out, "vmax")
    vmin = parse_meas(out, "vmin")
    vcm = vdd / 2
    sp = (vmax - vcm) * 1000 if vmax else 0
    sn = (vcm - vmin) * 1000 if vmin else sp
    return {"output_swing_mv": min(abs(sp), abs(sn))}


def measure_reset_time(corner="tt", temp=27, vdd=1.8):
    """Reset time: start cap at VCM+200mV, assert reset, measure settle."""
    vcm = vdd / 2
    # Use current injection to pre-charge, then reset
    netlist = f"""Reset Time Test
{hdr(corner, vdd, temp)}
* Phase 1: reset ON (0-200ns) charges to VCM
* Phase 2: reset OFF (200-600ns) charge to VCM+200mV via current
* Phase 3: reset ON (600ns+) measure settle time
Vrst reset 0 PWL(0 {{vdd_val}} 195n {{vdd_val}} 200n 0 599n 0 600n {{vdd_val}})
XI inp inn outp outn reset vbias_n vcm vdd vss integrator
* Charge during phase 2 only
Icp vcm inp PULSE(0 5u 200n 1n 1n 350n 100u)
Icn inn vcm PULSE(0 5u 200n 1n 1n 350n 100u)
.control
set filetype=ascii
option temp={temp}
tran 0.05n 700n UIC
meas tran vpre FIND V(outp) AT=595n
meas tran t_settle WHEN V(outp)={vcm+0.002} FALL=1 TD=600n
print vpre t_settle
wrdata reset_data.txt V(outp) V(outn) V(reset)
.endc
.end
"""
    out = run_ngspice(netlist)
    t = parse_meas(out, "t_settle")
    vpre = parse_meas(out, "vpre")
    res = {}
    if t is not None:
        res["reset_time_ns"] = max(0, (t - 600e-9) * 1e9)
    else:
        # Try from waveform
        data = read_wrdata("reset_data.txt")
        if data is not None and data.ndim == 2:
            times = data[:, 0]
            voutp = data[:, 1]
            mask = times >= 600e-9
            if mask.any():
                t_sub = times[mask]
                v_sub = voutp[mask]
                idx = np.where(v_sub <= vcm + 0.002)[0]
                if len(idx) > 0:
                    res["reset_time_ns"] = (t_sub[idx[0]] - 600e-9) * 1e9
                else:
                    res["reset_time_ns"] = 100
            else:
                res["reset_time_ns"] = 100
        else:
            res["reset_time_ns"] = 100
    res["_vpre"] = vpre
    return res


def measure_charge_injection(corner="tt", temp=27, vdd=1.8):
    """Charge injection: reset to VCM, release, measure kick."""
    vcm = vdd / 2
    netlist = f"""Charge Injection Test
{hdr(corner, vdd, temp)}
Vrst reset 0 PWL(0 {{vdd_val}} 199n {{vdd_val}} 200n 0)
XI inp inn outp outn reset vbias_n vcm vdd vss integrator
Rp inp vcm 1T
Rn inn vcm 1T
.control
set filetype=ascii
option temp={temp}
tran 0.02n 500n UIC
meas tran vp_before FIND V(outp) AT=198n
meas tran vn_before FIND V(outn) AT=198n
meas tran vp_after FIND V(outp) AT=350n
meas tran vn_after FIND V(outn) AT=350n
print vp_before vn_before vp_after vn_after
wrdata ci_data.txt V(outp) V(outn) V(reset)
.endc
.end
"""
    out = run_ngspice(netlist)
    vpa = parse_meas(out, "vp_after")
    vna = parse_meas(out, "vn_after")
    ci_p = abs(vpa - vcm) * 1000 if vpa else 100
    ci_n = abs(vna - vcm) * 1000 if vna else 100
    return {"charge_inject_mv": max(ci_p, ci_n),
            "_vp_after": vpa, "_vn_after": vna}


def measure_power(corner="tt", temp=27, vdd=1.8):
    """Quiescent power with reset off."""
    netlist = f"""Power Test
{hdr(corner, vdd, temp)}
Vrst reset 0 PWL(0 {{vdd_val}} 95n {{vdd_val}} 100n 0)
XI inp inn outp outn reset vbias_n vcm vdd vss integrator
Rp inp vcm 1T
Rn inn vcm 1T
.control
set filetype=ascii
option temp={temp}
tran 1n 1u UIC
meas tran ivdd AVG I(Vdd) FROM=200n TO=1u
print ivdd
.endc
.end
"""
    out = run_ngspice(netlist)
    ivdd = parse_meas(out, "ivdd")
    return {"power_uw": abs(ivdd) * vdd * 1e6 if ivdd else 0}


def compute_score(meas, specs):
    sd = specs.get("measurements", {})
    tw, ws = 0, 0
    details = {}
    for name, spec in sd.items():
        tgt = spec["target"]
        w = spec.get("weight", 1)
        tw += w
        v = meas.get(name)
        if v is None:
            details[name] = {"target": tgt, "measured": None, "pass": False}
            continue
        p = False
        if tgt.startswith(">"):
            p = v > float(tgt[1:])
        elif tgt.startswith("<"):
            p = v < float(tgt[1:])
        details[name] = {"target": tgt, "measured": v, "pass": p}
        if p:
            ws += w
    return ws / tw if tw else 0, details


def generate_plots(corner="tt", temp=27, vdd=1.8):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print("  No matplotlib")
        return
    os.makedirs(os.path.join(PROJECT_DIR, PLOTS_DIR), exist_ok=True)
    vcm = vdd / 2

    # 1. Integration ramp
    netlist = f"""Integration Plot
{hdr(corner, vdd, temp)}
Vrst reset 0 PWL(0 {{vdd_val}} 195n {{vdd_val}} 200n 0)
XI inp inn outp outn reset vbias_n vcm vdd vss integrator
Icp vcm inp DC 5u
Icn inn vcm DC 5u
.control
set filetype=ascii
option temp={temp}
tran 1n 2u UIC
wrdata plot_integ.txt V(outp) V(outn)
.endc
.end
"""
    run_ngspice(netlist)
    d = read_wrdata("plot_integ.txt")
    if d is not None and d.ndim == 2:
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(d[:, 0]*1e6, d[:, 1], 'b-', label='V(outp)', lw=1.5)
        if d.shape[1] >= 4:
            ax.plot(d[:, 0]*1e6, d[:, 3], 'r-', label='V(outn)', lw=1.5)
        ax.axhline(vcm, color='gray', ls='--', alpha=0.5, label='VCM')
        ax.set_xlabel('Time (us)'); ax.set_ylabel('V')
        ax.set_title(f'Integration Ramp (5uA, {corner}, {temp}C)')
        ax.legend(); ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PROJECT_DIR, PLOTS_DIR, 'integration_ramp.png'), dpi=150)
        plt.close()
        print("  Saved plots/integration_ramp.png")

    # 2. Reset + CI
    netlist = f"""Reset Plot
{hdr(corner, vdd, temp)}
Vrst reset 0 PWL(0 {{vdd_val}} 199n {{vdd_val}} 200n 0)
XI inp inn outp outn reset vbias_n vcm vdd vss integrator
Rp inp vcm 1T
Rn inn vcm 1T
.control
set filetype=ascii
option temp={temp}
tran 0.02n 500n UIC
wrdata plot_reset.txt V(outp) V(outn) V(reset)
.endc
.end
"""
    run_ngspice(netlist)
    d = read_wrdata("plot_reset.txt")
    if d is not None and d.ndim == 2:
        t = d[:, 0]*1e9
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 8), sharex=True,
                                         gridspec_kw={'height_ratios': [3, 1]})
        ax1.plot(t, (d[:, 1]-vcm)*1000, 'b-', label='V(outp)-VCM', lw=1.5)
        if d.shape[1] >= 4:
            ax1.plot(t, (d[:, 3]-vcm)*1000, 'r-', label='V(outn)-VCM', lw=1.5)
        ax1.axhline(0, color='gray', ls='--', alpha=0.5)
        ax1.set_ylabel('mV from VCM'); ax1.set_title(f'Reset & Charge Injection ({corner})')
        ax1.legend(); ax1.grid(True, alpha=0.3)
        if d.shape[1] >= 6:
            ax2.plot(t, d[:, 5], 'g-', lw=1.5)
        ax2.set_xlabel('Time (ns)'); ax2.set_ylabel('Reset (V)')
        ax2.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PROJECT_DIR, PLOTS_DIR, 'reset_waveform.png'), dpi=150)
        plt.close()
        print("  Saved plots/reset_waveform.png")

    # 3. Leakage
    netlist = f"""Leakage Plot
{hdr(corner, vdd, temp)}
Vrst reset 0 PWL(0 {{vdd_val}} 195n {{vdd_val}} 200n 0)
XI inp inn outp outn reset vbias_n vcm vdd vss integrator
Rp inp vcm 1T
Rn inn vcm 1T
.control
set filetype=ascii
option temp={temp}
tran 10n 55u UIC
wrdata plot_leak.txt V(outp) V(outn)
.endc
.end
"""
    run_ngspice(netlist)
    d = read_wrdata("plot_leak.txt")
    if d is not None and d.ndim == 2:
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(d[:, 0]*1e6, (d[:, 1]-vcm)*1000, 'b-', label='outp drift', lw=1.5)
        if d.shape[1] >= 4:
            ax.plot(d[:, 0]*1e6, (d[:, 3]-vcm)*1000, 'r-', label='outn drift', lw=1.5)
        ax.axhline(0, color='gray', ls='--', alpha=0.5)
        ax.set_xlabel('Time (us)'); ax.set_ylabel('Drift from VCM (mV)')
        ax.set_title(f'Leakage Drift ({corner}, {temp}C)')
        ax.legend(); ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PROJECT_DIR, PLOTS_DIR, 'leakage_drift.png'), dpi=150)
        plt.close()
        print("  Saved plots/leakage_drift.png")

    # 4. AC response
    netlist = f"""AC Plot
{hdr(corner, vdd, temp)}
Vrst reset 0 0
XI inp inn outp outn reset vbias_n vcm vdd vss integrator
.nodeset V(outp)={vcm} V(outn)={vcm} V(inp)={vcm} V(inn)={vcm}
Rbp outp vcm 1T
Rbn outn vcm 1T
Iac_p inp vcm DC 0 AC 1
Iac_n vcm inn DC 0 AC 1
.control
set filetype=ascii
option temp={temp}
ac dec 50 0.01 1G
wrdata plot_ac.txt vdb(outp,outn) vm(outp,outn)
.endc
.end
"""
    run_ngspice(netlist)
    d = read_wrdata("plot_ac.txt")
    if d is not None and d.ndim == 2 and d.shape[1] >= 4:
        freqs = d[:, 0]
        mag_db = d[:, 1]
        vg_db = mag_db + 20*np.log10(GM_REF) - 20*np.log10(2)
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 8))
        ax1.semilogx(freqs, mag_db, 'b-', lw=1.5)
        ax1.axhline(0, color='r', ls='--', alpha=0.5)
        ax1.set_ylabel('Transimpedance (dB)')
        ax1.set_title(f'AC Response ({corner})')
        ax1.grid(True, alpha=0.3)
        ax2.semilogx(freqs, vg_db, 'b-', lw=1.5)
        ax2.axhline(0, color='r', ls='--', alpha=0.5, label='UGF')
        ax2.axhline(60, color='g', ls='--', alpha=0.5, label='60dB target')
        ax2.set_xlabel('Frequency (Hz)'); ax2.set_ylabel('Voltage Gain (dB)')
        ax2.legend(); ax2.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PROJECT_DIR, PLOTS_DIR, 'ac_response.png'), dpi=150)
        plt.close()
        print("  Saved plots/ac_response.png")


def validate(quick=False):
    print("=" * 60)
    print("  Gm-C Integrator Validation")
    print("=" * 60)
    specs = load_specs()
    meas = {}

    print("\n--- Integration (C_int + UGF) ---")
    r = measure_integration()
    meas.update({k: v for k, v in r.items() if not k.startswith('_')})
    print(f"  C_int: {r.get('c_int_pf', 0):.2f} pF, UGF: {r.get('unity_gain_freq_mhz', 0):.3f} MHz")

    print("\n--- Leakage + DC Gain ---")
    r = measure_leakage(c_pf=meas.get("c_int_pf", 5))
    meas.update({k: v for k, v in r.items() if not k.startswith('_')})
    print(f"  Leakage: {r.get('leakage_mv_per_us', 0):.4f} mV/us, DC gain: {r.get('dc_gain_db', 0):.1f} dB")

    print("\n--- Output Swing ---")
    r = measure_swing()
    meas.update(r)
    print(f"  Swing: {r.get('output_swing_mv', 0):.1f} mV")

    print("\n--- Reset Time ---")
    r = measure_reset_time()
    meas.update({k: v for k, v in r.items() if not k.startswith('_')})
    print(f"  Reset time: {r.get('reset_time_ns', 100):.2f} ns")

    print("\n--- Charge Injection ---")
    r = measure_charge_injection()
    meas.update({k: v for k, v in r.items() if not k.startswith('_')})
    print(f"  Charge injection: {r.get('charge_inject_mv', 100):.2f} mV")

    print("\n--- Power ---")
    r = measure_power()
    meas.update(r)
    print(f"  Power: {r.get('power_uw', 0):.3f} uW")

    if not quick:
        print("\n--- Plots ---")
        generate_plots()

    score, details = compute_score(meas, specs)
    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    np_pass = 0
    for name, d in details.items():
        st = "PASS" if d["pass"] else "FAIL"
        v = f"{d['measured']:.4f}" if d['measured'] is not None else "N/A"
        print(f"  {name}: {v} (target: {d['target']}) [{st}]")
        if d["pass"]:
            np_pass += 1
    nt = len(details)
    print(f"\n  SCORE: {score:.3f} ({np_pass}/{nt} specs passing)")

    meas["score"] = score
    meas["specs_passed"] = np_pass
    meas["specs_total"] = nt
    with open(os.path.join(PROJECT_DIR, "measurements.json"), "w") as f:
        json.dump(meas, f, indent=2)
    print(f"  Saved measurements.json")
    return score, details, meas


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    os.makedirs(os.path.join(PROJECT_DIR, PLOTS_DIR), exist_ok=True)
    validate(quick=args.quick)
