"""
evaluate.py — Full simulation and validation for the analog multiplier.
"""

import os
import sys
import json
import re
import argparse
import subprocess
from typing import Dict, Tuple, Optional

import numpy as np

NGSPICE = os.environ.get("NGSPICE", "ngspice")
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SPECS_FILE = os.path.join(PROJECT_DIR, "specs.json")
PLOTS_DIR = os.path.join(PROJECT_DIR, "plots")
RESULTS_FILE = os.path.join(PROJECT_DIR, "measurements.json")

VDD = 1.8
VCM = 0.9
INPUT_RANGE = 0.3


def run_ngspice(netlist: str, timeout: int = 300) -> str:
    tmpfile = os.path.join(PROJECT_DIR, "_tmp_sim.cir")
    with open(tmpfile, 'w') as f:
        f.write(netlist)
    try:
        result = subprocess.run(
            [NGSPICE, "-b", "_tmp_sim.cir"],
            capture_output=True, text=True, timeout=timeout,
            cwd=PROJECT_DIR
        )
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return "ERROR: ngspice timeout"
    finally:
        try:
            os.unlink(tmpfile)
        except:
            pass


def parse_wrdata(filename: str) -> Tuple[np.ndarray, ...]:
    """Parse wrdata output. Returns (col0, col1) or (col0, col1, col2) if 3 columns."""
    fullpath = os.path.join(PROJECT_DIR, filename)
    data = []
    with open(fullpath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('*') or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    row = [float(p) for p in parts]
                    data.append(row)
                except ValueError:
                    continue
    if not data:
        return np.array([]), np.array([])
    data = np.array(data)
    if data.shape[1] >= 3:
        return data[:, 0], data[:, 1], data[:, 2]
    return data[:, 0], data[:, 1]


def cleanup(*filenames):
    for f in filenames:
        try:
            os.unlink(os.path.join(PROJECT_DIR, f))
        except:
            pass


def measure_dc_linearity(corner="tt", temp=27, vdd=1.8) -> Dict:
    """2D DC sweep using individual op points written to CSV."""
    n = 21

    sweep_cmds = []
    sweep_cmds.append('shell rm -f linearity_results.csv')

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
            sweep_cmds.append(f'echo "{vx:.6f},{vy:.6f},$&v(outp),$&v(outn)" >> linearity_results.csv')

    control_block = '\n'.join(sweep_cmds)

    netlist = f"""Multiplier DC Linearity
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
{control_block}
.endc
.end
"""

    print(f"  Running {n}x{n} = {n*n} DC operating points...")
    output = run_ngspice(netlist, timeout=600)

    csvfile = os.path.join(PROJECT_DIR, "linearity_results.csv")
    try:
        with open(csvfile) as f:
            lines = f.readlines()
    except Exception as e:
        print(f"ERROR reading results: {e}")
        return {"k_mult": 0, "linearity_error_pct": 100, "output_offset_mv": 100}

    vx_arr, vy_arr, outp_arr, outn_arr = [], [], [], []
    for line in lines:
        parts = line.strip().split(',')
        if len(parts) >= 4:
            try:
                vx_arr.append(float(parts[0]))
                vy_arr.append(float(parts[1]))
                outp_arr.append(float(parts[2]))
                outn_arr.append(float(parts[3]))
            except ValueError:
                continue

    cleanup("linearity_results.csv")

    if len(outp_arr) == 0:
        print("ERROR: No data parsed")
        return {"k_mult": 0, "linearity_error_pct": 100, "output_offset_mv": 100}

    vx_arr = np.array(vx_arr)
    vy_arr = np.array(vy_arr)
    vout_diff = np.array(outp_arr) - np.array(outn_arr)

    # Offset at zero input
    center_mask = (np.abs(vx_arr) < 0.001) & (np.abs(vy_arr) < 0.001)
    if np.any(center_mask):
        offset_mv = abs(vout_diff[center_mask][0]) * 1000
    else:
        offset_mv = abs(np.mean(vout_diff)) * 1000

    # Fit K: vout = K * vx * vy + c
    product = vx_arr * vy_arr
    A = np.column_stack([product, np.ones(len(product))])
    result = np.linalg.lstsq(A, vout_diff, rcond=None)
    k_mult = result[0][0]
    fitted_offset = result[0][1]

    ideal = k_mult * product + fitted_offset
    error = np.abs(vout_diff - ideal)
    max_range = np.max(np.abs(k_mult * product))
    linearity_error_pct = 100.0 * np.max(error) / max_range if max_range > 0 else 100

    print(f"  K_mult = {k_mult:.4f} V^-1")
    print(f"  Linearity error = {linearity_error_pct:.2f}%")
    print(f"  Output offset = {offset_mv:.2f} mV")
    print(f"  Data points: {len(vout_diff)}")

    return {
        "k_mult": k_mult,
        "linearity_error_pct": linearity_error_pct,
        "output_offset_mv": offset_mv,
        "vx": vx_arr, "vy": vy_arr,
        "vout_diff": vout_diff, "ideal": ideal,
    }


def measure_bandwidth(corner="tt", temp=27, vdd=1.8) -> float:
    netlist = f"""Multiplier BW Test
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}
.include "design.cir"

Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {VCM}
Vbias_n vbias_n 0 0.65
Vbias_p vbias_p 0 {vdd - 0.5}

Vyp yp 0 dc {VCM + 0.1}
Vyn yn 0 dc {VCM - 0.1}

Vxp xp 0 dc {VCM} ac 0.5
Vxn xn 0 dc {VCM} ac -0.5

Xmult xp xn yp yn outp outn vbias_n vbias_p vcm vdd vss multiplier

.control
ac dec 50 1k 100g
wrdata bw_data.txt v(outp)-v(outn)
.endc
.end
"""
    output = run_ngspice(netlist, timeout=120)

    try:
        parsed = parse_wrdata("bw_data.txt")
        if len(parsed) == 3:
            freq, real, imag = parsed
            mag_abs = np.sqrt(real**2 + imag**2)
        else:
            freq, mag = parsed
            mag_abs = np.abs(mag)
    except:
        print("ERROR: No bandwidth data")
        return 0

    cleanup("bw_data.txt")

    if len(freq) < 2:
        return 0

    if mag_abs[0] == 0:
        return 0

    dc_gain = mag_abs[0]
    mag_db = 20 * np.log10(mag_abs / dc_gain + 1e-30)

    bw_hz = freq[-1]
    for i in range(1, len(freq)):
        if mag_db[i] < -3.0:
            if mag_db[i] != mag_db[i-1]:
                ratio = (-3.0 - mag_db[i-1]) / (mag_db[i] - mag_db[i-1])
                bw_hz = freq[i-1] + ratio * (freq[i] - freq[i-1])
            else:
                bw_hz = freq[i]
            break

    bw_mhz = bw_hz / 1e6
    dc_gain_db = 20 * np.log10(dc_gain + 1e-30)
    print(f"  Bandwidth = {bw_mhz:.2f} MHz (DC gain = {dc_gain_db:.1f} dB)")
    return bw_mhz


def measure_thd(corner="tt", temp=27, vdd=1.8) -> float:
    freq = 100e3
    periods = 20
    tstop = periods / freq
    tstep = 1.0 / (freq * 200)

    netlist = f"""Multiplier THD Test
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}
.include "design.cir"

Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {VCM}
Vbias_n vbias_n 0 0.65
Vbias_p vbias_p 0 {vdd - 0.5}

Vyp yp 0 dc {VCM + 0.1}
Vyn yn 0 dc {VCM - 0.1}

Vxp xp 0 sin({VCM} 0.1 {freq})
Vxn xn 0 sin({VCM} -0.1 {freq})

Xmult xp xn yp yn outp outn vbias_n vbias_p vcm vdd vss multiplier

.control
tran {tstep} {tstop} {tstop * 0.5} uic
let vout = v(outp) - v(outn)
wrdata thd_data.txt vout
.endc
.end
"""
    output = run_ngspice(netlist, timeout=180)

    try:
        time_arr, vout = parse_wrdata("thd_data.txt")
    except:
        print("ERROR: No THD data")
        return 100

    cleanup("thd_data.txt")

    if len(vout) < 100:
        return 100

    vout_ac = vout - np.mean(vout)
    fft_mag = np.abs(np.fft.rfft(vout_ac))

    fund_idx = np.argmax(fft_mag[1:]) + 1
    fund_mag = fft_mag[fund_idx]
    if fund_mag == 0:
        return 100

    harmonic_power = sum(fft_mag[h * fund_idx]**2
                         for h in range(2, 11)
                         if h * fund_idx < len(fft_mag))

    thd = 100.0 * np.sqrt(harmonic_power) / fund_mag
    print(f"  THD = {thd:.3f}%")
    return thd


def measure_power(corner="tt", temp=27, vdd=1.8) -> float:
    netlist = f"""Multiplier Power Test
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
    output = run_ngspice(netlist, timeout=60)

    for line in output.split('\n'):
        if 'pwr' in line.lower() and '=' in line:
            match = re.search(r'=\s*([-\d.eE+]+)', line)
            if match:
                try:
                    power_uw = abs(float(match.group(1))) * 1e6
                    print(f"  Power = {power_uw:.1f} uW")
                    return power_uw
                except:
                    pass

    print("ERROR: Could not parse power")
    return 0


def generate_plots(lin_data: Dict, measurements: Dict):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    os.makedirs(PLOTS_DIR, exist_ok=True)

    vx = lin_data.get("vx", np.array([]))
    vy = lin_data.get("vy", np.array([]))
    vout = lin_data.get("vout_diff", np.array([]))
    ideal = lin_data.get("ideal", np.array([]))
    k_mult = lin_data.get("k_mult", 0)

    if len(vx) == 0:
        return

    # Find grid dimensions
    n_unique_x = len(np.unique(np.round(vx, 6)))
    n_unique_y = len(np.unique(np.round(vy, 6)))
    expected = n_unique_x * n_unique_y
    if len(vx) < expected:
        n_unique_y = len(vx) // n_unique_x
        expected = n_unique_x * n_unique_y

    vx = vx[:expected]; vy = vy[:expected]
    vout = vout[:expected]; ideal = ideal[:expected]

    m = n_unique_x; n = n_unique_y
    VX = vx.reshape(m, n) * 1000
    VY = vy.reshape(m, n) * 1000
    VOUT = vout.reshape(m, n) * 1000
    IDEAL = ideal.reshape(m, n) * 1000

    # 3D surface
    fig = plt.figure(figsize=(14, 5))
    ax1 = fig.add_subplot(121, projection='3d')
    ax1.plot_surface(VX, VY, VOUT, cmap='viridis', alpha=0.8)
    ax1.set_xlabel('Vx (mV)'); ax1.set_ylabel('Vy (mV)'); ax1.set_zlabel('Vout (mV)')
    ax1.set_title('Measured')
    ax2 = fig.add_subplot(122, projection='3d')
    ax2.plot_surface(VX, VY, IDEAL, cmap='viridis', alpha=0.8)
    ax2.set_xlabel('Vx (mV)'); ax2.set_ylabel('Vy (mV)'); ax2.set_zlabel('Vout (mV)')
    ax2.set_title(f'Ideal (K={k_mult:.3f})')
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'linearity_surface.png'), dpi=150)
    plt.close()

    # Error heatmap
    error = VOUT - IDEAL
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(error, extent=[-300, 300, -300, 300], origin='lower', cmap='RdBu_r')
    plt.colorbar(im, label='Error (mV)')
    ax.set_xlabel('Vx (mV)'); ax.set_ylabel('Vy (mV)')
    ax.set_title(f'Error Heatmap (max={np.max(np.abs(error)):.2f} mV)')
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'error_heatmap.png'), dpi=150)
    plt.close()

    # Transfer curves
    fig, ax = plt.subplots(figsize=(8, 6))
    for ix in [0, m//4, m//2, 3*m//4, m-1]:
        ax.plot(VY[ix, :], VOUT[ix, :], '-o', ms=2, label=f'Vx={VX[ix,0]:.0f}mV')
    ax.set_xlabel('Vy (mV)'); ax.set_ylabel('Vout (mV)')
    ax.set_title('Transfer Curves'); ax.legend(); ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'transfer_curves.png'), dpi=150)
    plt.close()

    # BW frequency response plot
    try:
        bw_netlist = f"""BW Plot
.lib "sky130_models/sky130.lib.spice" tt
.temp 27
.include "design.cir"
Vdd vdd 0 1.8
Vss vss 0 0
Vcm vcm 0 {VCM}
Vbias_n vbias_n 0 0.65
Vbias_p vbias_p 0 1.3
Vyp yp 0 dc {VCM + 0.1}
Vyn yn 0 dc {VCM - 0.1}
Vxp xp 0 dc {VCM} ac 0.5
Vxn xn 0 dc {VCM} ac -0.5
Xmult xp xn yp yn outp outn vbias_n vbias_p vcm vdd vss multiplier
.control
ac dec 50 1k 100g
wrdata bw_plot.txt v(outp)-v(outn)
.endc
.end
"""
        run_ngspice(bw_netlist)
        parsed = parse_wrdata("bw_plot.txt")
        if len(parsed) == 3:
            bw_freq, bw_real, bw_imag = parsed
            bw_mag = np.sqrt(bw_real**2 + bw_imag**2)
        else:
            bw_freq, bw_mag_raw = parsed
            bw_mag = np.abs(bw_mag_raw)
        cleanup("bw_plot.txt")

        if len(bw_freq) > 0 and bw_mag[0] > 0:
            bw_db = 20 * np.log10(bw_mag / bw_mag[0] + 1e-30)
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.semilogx(bw_freq / 1e6, bw_db, 'b-', linewidth=2)
            ax.axhline(y=-3, color='r', linestyle='--', label='-3dB')
            ax.axvline(x=5, color='g', linestyle=':', label='Target: 5 MHz')
            ax.set_xlabel('Frequency (MHz)')
            ax.set_ylabel('Gain (dB, normalized)')
            ax.set_title(f'Frequency Response (DC gain = {20*np.log10(bw_mag[0]):.1f} dB)')
            ax.legend(); ax.grid(True, alpha=0.3)
            ax.set_ylim([-40, 5])
            plt.tight_layout()
            plt.savefig(os.path.join(PLOTS_DIR, 'bandwidth.png'), dpi=150)
            plt.close()
    except Exception as e:
        print(f"  BW plot error: {e}")

    # Spec summary
    fig, ax = plt.subplots(figsize=(10, 5))
    specs_dict = load_specs()["measurements"]
    names = list(specs_dict.keys())
    meas_vals, tgt_vals, colors = [], [], []
    for nm in names:
        sp = specs_dict[nm]; mv = measurements.get(nm, 0); meas_vals.append(mv)
        t = sp["target"]; tv = float(t[1:]); tgt_vals.append(tv)
        if t.startswith("<"):
            colors.append('green' if mv < tv else 'red')
        else:
            colors.append('green' if mv > tv else 'red')
    x = np.arange(len(names)); w = 0.35
    ax.bar(x - w/2, meas_vals, w, color=colors, alpha=0.7, label='Measured')
    ax.bar(x + w/2, tgt_vals, w, color='gray', alpha=0.5, label='Target')
    ax.set_xticks(x); ax.set_xticklabels(names, rotation=45, ha='right')
    ax.set_title('Spec Compliance'); ax.legend(); ax.grid(True, alpha=0.3, axis='y')
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'spec_summary.png'), dpi=150)
    plt.close()

    print("  Plots saved to plots/")


def load_specs() -> Dict:
    with open(SPECS_FILE) as f:
        return json.load(f)


def compute_score(measurements: Dict, specs: Dict) -> Tuple[float, Dict]:
    spec_defs = specs.get("measurements", {})
    total_weight = weighted_score = 0
    details = {}
    for name, spec in spec_defs.items():
        target = spec["target"]; weight = spec.get("weight", 1)
        total_weight += weight
        measured = measurements.get(name)
        if measured is None:
            details[name] = {"target": target, "measured": None, "pass": False}
            continue
        if target.startswith(">"):
            passed = measured > float(target[1:])
        elif target.startswith("<"):
            passed = measured < float(target[1:])
        else:
            passed = False
        details[name] = {"target": target, "measured": measured, "pass": passed}
        if passed:
            weighted_score += weight
    return (weighted_score / total_weight if total_weight else 0), details


def validate(quick=False):
    print("=" * 60)
    print("  Analog Multiplier Validation")
    print("=" * 60)

    specs = load_specs()

    print("\n--- DC Linearity & Gain ---")
    lin_data = measure_dc_linearity()

    print("\n--- Bandwidth ---")
    bw = measure_bandwidth()

    print("\n--- THD ---")
    thd = measure_thd()

    print("\n--- Power ---")
    power = measure_power()

    measurements = {
        "k_mult": lin_data["k_mult"],
        "linearity_error_pct": lin_data["linearity_error_pct"],
        "output_offset_mv": lin_data["output_offset_mv"],
        "bw_mhz": bw,
        "thd_pct": thd,
        "power_uw": power,
    }

    score, details = compute_score(measurements, specs)

    print(f"\n{'='*60}\n  RESULTS\n{'='*60}")
    n_pass = 0
    for name, d in details.items():
        st = "PASS" if d["pass"] else "FAIL"
        mv = f"{d['measured']:.4f}" if d['measured'] is not None else "N/A"
        unit = specs["measurements"][name].get("unit", "")
        print(f"  {name}: {mv} {unit} (target: {d['target']}) [{st}]")
        if d["pass"]: n_pass += 1

    print(f"\n  SPECS: {n_pass}/{len(details)} passing")
    print(f"  SCORE: {score:.3f}")

    measurements["score"] = score
    with open(RESULTS_FILE, "w") as f:
        json.dump(measurements, f, indent=2)

    if "vx" in lin_data and len(lin_data.get("vx", [])) > 0:
        print("\n--- Generating Plots ---")
        generate_plots(lin_data, measurements)

    return score, measurements, details


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    os.makedirs(PLOTS_DIR, exist_ok=True)
    validate(quick=args.quick)


if __name__ == "__main__":
    main()
