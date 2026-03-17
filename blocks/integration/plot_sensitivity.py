#!/usr/bin/env python3
"""
Sensitivity analysis plots for the Lorenz ODE solver.
Generates: rho bifurcation diagram, coefficient sensitivity, PVT detail.
"""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path

PLOTS_DIR = Path("plots")
SIGMA, RHO, BETA = 10.0, 28.0, 8.0/3.0

def lorenz_rk4(sigma, rho, beta, x0, y0, z0, dt, n):
    def f(s):
        return np.array([sigma*(s[1]-s[0]), rho*s[0]-s[0]*s[2]-s[1], s[0]*s[1]-beta*s[2]])
    traj = np.zeros((n, 3))
    s = np.array([x0, y0, z0])
    traj[0] = s
    for i in range(1, n):
        k1=f(s); k2=f(s+.5*dt*k1); k3=f(s+.5*dt*k2); k4=f(s+dt*k3)
        s = s + (dt/6)*(k1+2*k2+2*k3+k4)
        traj[i] = s
    return traj

def plot_rho_bifurcation():
    """Show how z_max varies with rho — highlights chaos boundary."""
    rho_values = np.linspace(20, 32, 120)
    dt = 0.005
    n_trans = 5000   # transient to discard
    n_sample = 10000  # sample period

    fig, ax = plt.subplots(figsize=(12, 6))

    for rho in rho_values:
        traj = lorenz_rk4(SIGMA, rho, BETA, 1.0, 1.0, 1.0, dt, n_trans + n_sample)
        z = traj[n_trans:, 2]

        # Find local maxima of z
        maxima = []
        for i in range(1, len(z)-1):
            if z[i] > z[i-1] and z[i] > z[i+1] and z[i] > 15:
                maxima.append(z[i])

        if maxima:
            ax.scatter([rho]*len(maxima), maxima, s=0.1, c='#3498db', alpha=0.3, rasterized=True)

    # Mark our operating point
    ax.axvline(25.32, color='#e74c3c', linewidth=2, linestyle='--', alpha=0.8, label='Circuit ρ_eff = 25.32')
    ax.axvline(28.0, color='#2ecc71', linewidth=1.5, linestyle=':', alpha=0.8, label='Ideal ρ = 28.0')
    ax.axvline(24.74, color='#f39c12', linewidth=1.5, linestyle='-.', alpha=0.8, label='Chaos onset ρ_c ≈ 24.74')

    ax.set_xlabel('ρ (rho)', fontsize=13)
    ax.set_ylabel('z maxima', fontsize=13)
    ax.set_title('Bifurcation Diagram — Lorenz System z-maxima vs ρ', fontsize=14, fontweight='bold')
    ax.legend(fontsize=10, loc='upper left')
    ax.grid(True, alpha=0.3)

    # Shade the chaos region
    ax.axvspan(24.74, 32, alpha=0.05, color='blue')
    ax.text(24.0, ax.get_ylim()[1]*0.95, 'Stable\nfixed point', fontsize=9, ha='center',
           color='#e67e22', fontstyle='italic')
    ax.text(28.5, ax.get_ylim()[1]*0.95, 'Chaotic\nregion', fontsize=9, ha='center',
           color='#3498db', fontstyle='italic')

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / 'bifurcation_rho.png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    print("  Saved bifurcation_rho.png")

def plot_coefficient_sensitivity():
    """Show how correlation varies with coefficient errors."""
    # Sweep each coefficient and compute correlation with ideal
    dt = 0.001
    n = int(5.52 / dt)  # 5 Lyapunov times

    def corr_with_ideal(sigma, rho, beta):
        ref = lorenz_rk4(SIGMA, RHO, BETA, 1.0, 1.0, 25.0, dt, n)
        test = lorenz_rk4(sigma, rho, beta, 1.0, 1.0, 25.0, dt, n)
        x_ref = (ref[:, 0] - np.mean(ref[:, 0])) / (np.std(ref[:, 0]) + 1e-12)
        x_test = (test[:, 0] - np.mean(test[:, 0])) / (np.std(test[:, 0]) + 1e-12)
        return max(0, np.corrcoef(x_ref, x_test)[0, 1])

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # Sigma sweep
    sigmas = np.linspace(8, 12, 40)
    corrs = [corr_with_ideal(s, RHO, BETA) for s in sigmas]
    axes[0].plot(sigmas, corrs, 'b-', linewidth=2)
    axes[0].axvline(10.14, color='r', linestyle='--', label='Circuit σ=10.14')
    axes[0].axhline(0.90, color='gray', linestyle=':', alpha=0.5)
    axes[0].set_xlabel('σ (sigma)')
    axes[0].set_ylabel('Correlation with ideal')
    axes[0].set_title('σ Sensitivity')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # Rho sweep
    rhos = np.linspace(24, 32, 40)
    corrs = [corr_with_ideal(SIGMA, r, BETA) for r in rhos]
    axes[1].plot(rhos, corrs, 'b-', linewidth=2)
    axes[1].axvline(25.32, color='r', linestyle='--', label='Circuit ρ=25.32')
    axes[1].axhline(0.90, color='gray', linestyle=':', alpha=0.5)
    axes[1].set_xlabel('ρ (rho)')
    axes[1].set_title('ρ Sensitivity (most critical)')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    # Beta sweep
    betas = np.linspace(1.5, 4.0, 40)
    corrs = [corr_with_ideal(SIGMA, RHO, b) for b in betas]
    axes[2].plot(betas, corrs, 'b-', linewidth=2)
    axes[2].axvline(2.53, color='r', linestyle='--', label='Circuit β=2.53')
    axes[2].axhline(0.90, color='gray', linestyle=':', alpha=0.5)
    axes[2].set_xlabel('β (beta)')
    axes[2].set_title('β Sensitivity')
    axes[2].legend()
    axes[2].grid(True, alpha=0.3)

    fig.suptitle('Coefficient Sensitivity Analysis — Correlation vs Parameter Error',
                fontsize=14, fontweight='bold')
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / 'coefficient_sensitivity.png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    print("  Saved coefficient_sensitivity.png")

if __name__ == '__main__':
    print("Generating sensitivity analysis plots...")
    plot_rho_bifurcation()
    plot_coefficient_sensitivity()
    print("Done!")
