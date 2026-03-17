"""
pvt_sweep.py — PVT corner sweep for multiplier verification.
Sweeps temperature, supply voltage, and process corners.
"""

import os
import json
import numpy as np
from evaluate import (
    measure_dc_linearity, measure_bandwidth, measure_thd, measure_power,
    load_specs, compute_score, PLOTS_DIR, PROJECT_DIR
)

TEMPERATURES = [-40, 27, 175]
SUPPLY_VOLTAGES = [1.62, 1.8, 1.98]
PROCESS_CORNERS = ["tt", "ss", "ff", "sf", "fs"]


def run_pvt_sweep():
    specs = load_specs()
    results = []
    worst = {
        "linearity_error_pct": 0, "k_mult": 1e6,
        "output_offset_mv": 0, "bw_mhz": 1e6,
        "thd_pct": 0, "power_uw": 0,
    }

    # Reduced sweep for speed: 3 corners x 3 temps x 3 supplies = 27 points
    # Full sweep would be 5 x 3 x 3 = 45
    corners_to_test = PROCESS_CORNERS
    total = len(corners_to_test) * len(TEMPERATURES) * len(SUPPLY_VOLTAGES)
    idx = 0

    for corner in corners_to_test:
        for temp in TEMPERATURES:
            for vdd in SUPPLY_VOLTAGES:
                idx += 1
                print(f"\n{'='*50}")
                print(f"  PVT [{idx}/{total}]: {corner} / {temp}C / {vdd}V")
                print(f"{'='*50}")

                try:
                    lin = measure_dc_linearity(corner=corner, temp=temp, vdd=vdd)
                    bw = measure_bandwidth(corner=corner, temp=temp, vdd=vdd)
                    thd = measure_thd(corner=corner, temp=temp, vdd=vdd)
                    pwr = measure_power(corner=corner, temp=temp, vdd=vdd)

                    meas = {
                        "corner": corner, "temp": temp, "vdd": vdd,
                        "k_mult": lin["k_mult"],
                        "linearity_error_pct": lin["linearity_error_pct"],
                        "output_offset_mv": lin["output_offset_mv"],
                        "bw_mhz": bw, "thd_pct": thd, "power_uw": pwr,
                    }

                    score, details = compute_score(meas, specs)
                    meas["score"] = score
                    n_pass = sum(1 for d in details.values() if d["pass"])
                    meas["specs_passing"] = f"{n_pass}/{len(details)}"

                    # Track worst case
                    worst["linearity_error_pct"] = max(worst["linearity_error_pct"], lin["linearity_error_pct"])
                    worst["k_mult"] = min(worst["k_mult"], lin["k_mult"])
                    worst["output_offset_mv"] = max(worst["output_offset_mv"], lin["output_offset_mv"])
                    worst["bw_mhz"] = min(worst["bw_mhz"], bw)
                    worst["thd_pct"] = max(worst["thd_pct"], thd)
                    worst["power_uw"] = max(worst["power_uw"], pwr)

                    results.append(meas)
                    print(f"  Score: {score:.3f} ({meas['specs_passing']})")

                except Exception as e:
                    print(f"  ERROR: {e}")
                    results.append({
                        "corner": corner, "temp": temp, "vdd": vdd,
                        "error": str(e), "score": 0,
                    })

    # Compute worst-case score
    worst_score, worst_details = compute_score(worst, specs)

    print(f"\n{'='*60}")
    print(f"  PVT SWEEP SUMMARY")
    print(f"{'='*60}")
    print(f"\n  Worst-case results:")
    for name, d in worst_details.items():
        st = "PASS" if d["pass"] else "FAIL"
        print(f"    {name}: {d['measured']:.4f} (target: {d['target']}) [{st}]")

    n_worst_pass = sum(1 for d in worst_details.values() if d["pass"])
    print(f"\n  Worst-case: {n_worst_pass}/{len(worst_details)} passing, score={worst_score:.3f}")

    # Save results
    pvt_results = {
        "worst_case": worst,
        "worst_case_score": worst_score,
        "all_corners": results,
    }
    with open(os.path.join(PROJECT_DIR, "pvt_results.json"), "w") as f:
        json.dump(pvt_results, f, indent=2)

    # Generate PVT plot
    generate_pvt_plots(results, worst, worst_details)

    return worst_score, worst, results


def generate_pvt_plots(results, worst, worst_details):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    os.makedirs(PLOTS_DIR, exist_ok=True)

    # Extract data for plotting
    valid = [r for r in results if "error" not in r]
    if not valid:
        return

    specs = ["linearity_error_pct", "k_mult", "thd_pct", "power_uw"]
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    for ax, spec in zip(axes.flat, specs):
        vals = [r[spec] for r in valid]
        labels = [f"{r['corner']}\n{r['temp']}C\n{r['vdd']}V" for r in valid]
        colors = []
        from evaluate import load_specs
        spec_info = load_specs()["measurements"][spec]
        target = spec_info["target"]
        tv = float(target[1:])

        for v in vals:
            if target.startswith("<"):
                colors.append('green' if v < tv else 'red')
            else:
                colors.append('green' if v > tv else 'red')

        ax.bar(range(len(vals)), vals, color=colors, alpha=0.7)
        ax.axhline(y=tv, color='black', linestyle='--', label=f'Target: {target}')
        ax.set_title(f'{spec} ({spec_info["unit"]})')
        ax.set_xticks(range(len(vals)))
        ax.set_xticklabels(labels, fontsize=5, rotation=90)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    plt.suptitle('PVT Corner Sweep Results', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'pvt_sweep.png'), dpi=150)
    plt.close()
    print("  PVT plot saved to plots/pvt_sweep.png")


if __name__ == "__main__":
    run_pvt_sweep()
