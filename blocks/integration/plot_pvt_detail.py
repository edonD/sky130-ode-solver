#!/usr/bin/env python3
"""
PVT Detail Plots — Show attractor shape at selected corners.
"""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
from evaluate import run_sim_wrdata, extract_lorenz_signals

PLOTS_DIR = Path("plots")

def plot_pvt_attractors():
    """Show x-z attractor at selected PVT corners."""
    corners = [
        ('tt', 27, 1.80, 'Nominal (tt/27C/1.8V)'),
        ('ss', -40, 1.62, 'Worst-pass (ss/-40C/1.62V)'),
        ('ff', 175, 1.98, 'Fast/hot (ff/175C/1.98V)'),
        ('fs', 27, 1.62, 'FAIL (fs/27C/1.62V)'),
        ('sf', -40, 1.62, 'Slow-P (sf/-40C/1.62V)'),
        ('tt', 175, 1.98, 'Hot/high-V (tt/175C/1.98V)'),
    ]

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    axes = axes.flatten()

    for i, (corner, temp, vdd, title) in enumerate(corners):
        prefix = f"pvt_detail_{corner}_{temp}_{int(vdd*100)}"
        print(f"  Running {title}...", end='', flush=True)

        try:
            data = run_sim_wrdata(corner=corner, temp=temp, vdd=vdd,
                                 sim_us=100, prefix=prefix)
            if data is None:
                axes[i].text(0.5, 0.5, 'No data', transform=axes[i].transAxes,
                           ha='center', fontsize=14)
                print(" no data")
                continue

            t, vx, vy, vz = extract_lorenz_signals(data)

            step = max(1, len(vx) // 5000)
            xm = vx[::step] * 1000
            zm = vz[::step] * 1000

            # Color by time
            if np.std(xm) > 1:  # oscillating
                axes[i].scatter(xm, zm, c=np.linspace(0, 1, len(xm)),
                              cmap='plasma', s=0.3, alpha=0.5, rasterized=True)
                color = '#2ecc71'
                status = 'CHAOS'
            else:
                axes[i].scatter(xm, zm, c='red', s=1, alpha=0.5, rasterized=True)
                color = '#e74c3c'
                status = 'STABLE'

            axes[i].set_title(f'{title}\n[{status}]', fontsize=10, color=color, fontweight='bold')
            axes[i].set_xlabel('x [mV]', fontsize=9)
            axes[i].set_ylabel('z [mV]', fontsize=9)
            axes[i].grid(True, alpha=0.2)
            print(f" {status}")

        except Exception as e:
            axes[i].text(0.5, 0.5, f'Error: {e}', transform=axes[i].transAxes,
                       ha='center', fontsize=10, wrap=True)
            print(f" error: {e}")

    fig.suptitle('Lorenz Attractor at Selected PVT Corners', fontsize=15, fontweight='bold')
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / 'pvt_attractors.png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    print("  Saved pvt_attractors.png")

if __name__ == '__main__':
    print("Generating PVT detail plots...")
    plot_pvt_attractors()
    print("Done!")
