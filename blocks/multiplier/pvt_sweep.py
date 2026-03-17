"""
pvt_sweep.py — PVT corner sweep for multiplier verification.
Uses unique temp file names to avoid conflicts.
"""

import os
import json
import uuid
import numpy as np
import subprocess
import re
from typing import Dict, Tuple

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
PLOTS_DIR = os.path.join(PROJECT_DIR, "plots")
SPECS_FILE = os.path.join(PROJECT_DIR, "specs.json")
VCM = 0.9
INPUT_RANGE = 0.3

TEMPERATURES = [-40, 27, 175]
SUPPLY_VOLTAGES = [1.62, 1.8, 1.98]
PROCESS_CORNERS = ["tt", "ss", "ff", "sf", "fs"]


def run_sim(netlist, timeout=300):
    uid = uuid.uuid4().hex[:8]
    tmpfile = os.path.join(PROJECT_DIR, f"_pvt_{uid}.cir")
    with open(tmpfile, 'w') as f:
        f.write(netlist)
    try:
        result = subprocess.run(
            ["ngspice", "-b", f"_pvt_{uid}.cir"],
            capture_output=True, text=True, timeout=timeout,
            cwd=PROJECT_DIR
        )
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return "ERROR: timeout"
    finally:
        try:
            os.unlink(tmpfile)
        except:
            pass


def measure_corner(corner, temp, vdd):
    """Quick measurement of key specs at a PVT corner."""
    uid = uuid.uuid4().hex[:8]
    csvfile = f"_pvt_lin_{uid}.csv"

    # Build linearity sweep
    n = 11  # Fewer points for speed
    sweep_cmds = [f'shell rm -f {csvfile}']
    vx_vals = np.linspace(-INPUT_RANGE, INPUT_RANGE, n)
    vy_vals = np.linspace(-INPUT_RANGE, INPUT_RANGE, n)
    for vx in vx_vals:
        vxp = VCM + vx/2
        vxn = VCM - vx/2
        for vy in vy_vals:
            vyp = VCM + vy/2
            vyn = VCM - vy/2
            sweep_cmds.append(f'alter Vxp = {vxp:.6f}')
            sweep_cmds.append(f'alter Vxn = {vxn:.6f}')
            sweep_cmds.append(f'alter Vyp = {vyp:.6f}')
            sweep_cmds.append(f'alter Vyn = {vyn:.6f}')
            sweep_cmds.append('op')
            sweep_cmds.append(f'echo "{vx:.6f},{vy:.6f},$&v(outp),$&v(outn)" >> {csvfile}')

    control = '\n'.join(sweep_cmds)

    netlist = f"""PVT Corner {corner} {temp}C {vdd}V
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}
.include "design.cir"
Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {VCM}
Vbias_n vbias_n 0 0.65
Vbias_p vbias_p 0 {vdd - 0.5}
Vxp xp 0 dc {VCM}
Vxn xn 0 dc {VCM}
Vyp yp 0 dc {VCM}
Vyn yn 0 dc {VCM}
Xmult xp xn yp yn outp outn vbias_n vbias_p vcm vdd vss multiplier
.control
{control}
.endc
.end
"""

    run_sim(netlist, timeout=300)

    # Parse
    try:
        fullpath = os.path.join(PROJECT_DIR, csvfile)
        vx_arr, vy_arr, outp_arr, outn_arr = [], [], [], []
        with open(fullpath) as f:
            for line in f:
                parts = line.strip().split(',')
                if len(parts) >= 4:
                    try:
                        vx_arr.append(float(parts[0]))
                        vy_arr.append(float(parts[1]))
                        outp_arr.append(float(parts[2]))
                        outn_arr.append(float(parts[3]))
                    except ValueError:
                        continue
        os.unlink(fullpath)
    except:
        return None

    if not outp_arr:
        return None

    vx_arr = np.array(vx_arr)
    vy_arr = np.array(vy_arr)
    vout_diff = np.array(outp_arr) - np.array(outn_arr)

    product = vx_arr * vy_arr
    A = np.column_stack([product, np.ones(len(product))])
    result = np.linalg.lstsq(A, vout_diff, rcond=None)
    k_mult = result[0][0]
    fitted_offset = result[0][1]
    ideal = k_mult * product + fitted_offset
    error = np.abs(vout_diff - ideal)
    max_range = np.max(np.abs(k_mult * product))
    lin_err = 100.0 * np.max(error) / max_range if max_range > 0 else 100

    center = (np.abs(vx_arr) < 0.001) & (np.abs(vy_arr) < 0.001)
    offset_mv = abs(vout_diff[center][0]) * 1000 if np.any(center) else 0

    # Power
    pwr_netlist = f"""PVT Power {corner} {temp}C {vdd}V
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}
.include "design.cir"
Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {VCM}
Vbias_n vbias_n 0 0.65
Vbias_p vbias_p 0 {vdd - 0.5}
Vxp xp 0 dc {VCM}
Vxn xn 0 dc {VCM}
Vyp yp 0 dc {VCM}
Vyn yn 0 dc {VCM}
Xmult xp xn yp yn outp outn vbias_n vbias_p vcm vdd vss multiplier
.control
op
let pwr = -v(vdd) * i(Vdd)
print pwr
.endc
.end
"""
    pwr_out = run_sim(pwr_netlist, timeout=30)
    power_uw = 0
    for line in pwr_out.split('\n'):
        if 'pwr' in line.lower() and '=' in line:
            match = re.search(r'=\s*([-\d.eE+]+)', line)
            if match:
                try:
                    power_uw = abs(float(match.group(1))) * 1e6
                except:
                    pass

    return {
        "k_mult": k_mult,
        "linearity_error_pct": lin_err,
        "output_offset_mv": offset_mv,
        "power_uw": power_uw,
    }


def load_specs():
    with open(SPECS_FILE) as f:
        return json.load(f)


def run_pvt_sweep():
    specs = load_specs()
    results = []
    worst = {
        "linearity_error_pct": 0, "k_mult": 1e6,
        "output_offset_mv": 0, "power_uw": 0,
    }

    total = len(PROCESS_CORNERS) * len(TEMPERATURES) * len(SUPPLY_VOLTAGES)
    idx = 0

    for corner in PROCESS_CORNERS:
        for temp in TEMPERATURES:
            for vdd in SUPPLY_VOLTAGES:
                idx += 1
                print(f"[{idx}/{total}] {corner}/{temp}C/{vdd}V ...", end=" ", flush=True)

                meas = measure_corner(corner, temp, vdd)
                if meas is None:
                    print("ERROR")
                    results.append({"corner": corner, "temp": temp, "vdd": vdd, "error": True})
                    continue

                # Check specs
                k_pass = meas["k_mult"] > 0.5
                lin_pass = meas["linearity_error_pct"] < 5
                off_pass = meas["output_offset_mv"] < 10
                pwr_pass = meas["power_uw"] < 300
                n_pass = sum([k_pass, lin_pass, off_pass, pwr_pass])

                worst["linearity_error_pct"] = max(worst["linearity_error_pct"], meas["linearity_error_pct"])
                worst["k_mult"] = min(worst["k_mult"], meas["k_mult"])
                worst["output_offset_mv"] = max(worst["output_offset_mv"], meas["output_offset_mv"])
                worst["power_uw"] = max(worst["power_uw"], meas["power_uw"])

                status = "PASS" if n_pass == 4 else f"FAIL({4-n_pass})"
                print(f"K={meas['k_mult']:.3f} Lin={meas['linearity_error_pct']:.1f}% Pwr={meas['power_uw']:.0f}uW [{status}]")

                meas.update({"corner": corner, "temp": temp, "vdd": vdd, "status": status})
                results.append(meas)

    print(f"\n{'='*60}")
    print(f"  PVT SUMMARY (worst-case across {total} corners)")
    print(f"{'='*60}")
    print(f"  K_mult:     {worst['k_mult']:.3f} (target >0.5)  {'PASS' if worst['k_mult'] > 0.5 else 'FAIL'}")
    print(f"  Linearity:  {worst['linearity_error_pct']:.2f}% (target <5%)  {'PASS' if worst['linearity_error_pct'] < 5 else 'FAIL'}")
    print(f"  Offset:     {worst['output_offset_mv']:.2f} mV (target <10)  {'PASS' if worst['output_offset_mv'] < 10 else 'FAIL'}")
    print(f"  Power:      {worst['power_uw']:.1f} uW (target <300)  {'PASS' if worst['power_uw'] < 300 else 'FAIL'}")

    n_total_pass = sum(1 for r in results if r.get("status") == "PASS")
    print(f"\n  {n_total_pass}/{total} corners fully passing")

    with open(os.path.join(PROJECT_DIR, "pvt_results.json"), "w") as f:
        json.dump({"worst": worst, "corners": results}, f, indent=2)

    # Generate PVT plot
    generate_pvt_plot(results)

    return worst, results


def generate_pvt_plot(results):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    os.makedirs(PLOTS_DIR, exist_ok=True)
    valid = [r for r in results if "error" not in r]
    if not valid:
        return

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))

    specs_info = [
        ("k_mult", ">0.5", "K_mult (V^-1)"),
        ("linearity_error_pct", "<5", "Linearity Error (%)"),
        ("output_offset_mv", "<10", "Output Offset (mV)"),
        ("power_uw", "<300", "Power (uW)"),
    ]

    for ax, (key, target, title) in zip(axes.flat, specs_info):
        vals = [r.get(key, 0) for r in valid]
        labels = [f"{r['corner']}\n{r['temp']}C\n{r['vdd']}V" for r in valid]
        tv = float(target[1:])

        if target.startswith("<"):
            colors = ['green' if v < tv else 'red' for v in vals]
        else:
            colors = ['green' if v > tv else 'red' for v in vals]

        ax.bar(range(len(vals)), vals, color=colors, alpha=0.7, width=0.8)
        ax.axhline(y=tv, color='black', linestyle='--', linewidth=2, label=f'Target: {target}')
        ax.set_title(title, fontsize=12)
        ax.set_xticks(range(len(vals)))
        ax.set_xticklabels(labels, fontsize=4, rotation=90)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3, axis='y')

    plt.suptitle('PVT Corner Sweep (45 corners)', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'pvt_sweep.png'), dpi=150)
    plt.close()
    print("  PVT plot saved")


if __name__ == "__main__":
    run_pvt_sweep()
