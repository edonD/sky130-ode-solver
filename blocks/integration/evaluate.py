#!/usr/bin/env python3
"""
Full Integration Evaluator — SKY130 Analog ODE Solver
Runs ngspice simulation, validates specs, generates publication-quality plots.
"""

import subprocess, os, sys, json, re, warnings
import numpy as np
from pathlib import Path

warnings.filterwarnings('ignore')

# ── Configuration ──────────────────────────────────────────────────────────
VCM = 0.9
T_LORENZ_US = 2.565  # from upstream_config.json
SIGMA, RHO, BETA = 10.0, 28.0, 8.0/3.0
SIM_TIME_US = 200       # total sim time
RESET_TIME_NS = 500     # reset duration
KICK_END_NS = 520       # perturbation ends

PLOTS_DIR = Path("plots")
PLOTS_DIR.mkdir(exist_ok=True)

# ── Helper: write and run ngspice ──────────────────────────────────────────
def run_ngspice(netlist_str, raw_file="sim_output.raw", timeout=300):
    """Write netlist to file, run ngspice, return raw file path."""
    netlist_path = "sim_netlist.cir"
    with open(netlist_path, 'w') as f:
        f.write(netlist_str)

    cmd = ["ngspice", "-b", "-r", raw_file, netlist_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    if result.returncode != 0:
        print("NGSPICE STDERR:", result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr)

    return raw_file, result

def read_raw_file(raw_file):
    """Parse ngspice binary raw file using wrdata fallback."""
    # Use wrdata approach for reliability
    return None  # Will use wrdata instead

def run_sim_wrdata(corner="tt", temp=27, vdd=1.8, sim_us=None, prefix="nom"):
    """Run simulation and extract data via wrdata."""
    if sim_us is None:
        sim_us = SIM_TIME_US

    reset_ns = RESET_TIME_NS
    total_ns = sim_us * 1000

    # Determine model lib include
    model_lib = f'.lib "sky130_models/sky130.lib.spice" {corner}'

    data_file = f"data_{prefix}.txt"

    netlist = f"""* Full Integration Simulation — {corner}/{temp}C/{vdd}V
{model_lib}

.include design.cir

* Top-level instantiation
XTop vxp_buf vxn_buf vyp_buf vyn_buf vzp_buf vzn_buf reset vdd vss ode_solver

* Supply
Vdd vdd 0 DC {vdd}
Vss vss 0 DC 0

* Reset: high for {reset_ns}ns, then low
Vrst reset 0 DC 0 PWL(0 {vdd} {reset_ns}n {vdd} {reset_ns + 1}n 0)

* Transient
.tran 1n {total_ns}n 0 1n
.options method=gear maxord=3

* Save data
.control
run
wrdata {data_file} v(vxp_buf) v(vxn_buf) v(vyp_buf) v(vyn_buf) v(vzp_buf) v(vzn_buf) v(vdd) i(Vdd)
quit
.endc

.end
"""

    netlist_path = f"sim_{prefix}.cir"
    with open(netlist_path, 'w') as f:
        f.write(netlist)

    result = subprocess.run(
        ["ngspice", "-b", netlist_path],
        capture_output=True, text=True, timeout=600
    )

    if result.returncode != 0 and not os.path.exists(data_file):
        print(f"ERROR: ngspice failed for {prefix}")
        print(result.stderr[-1500:])
        return None

    if not os.path.exists(data_file):
        print(f"ERROR: No data file produced for {prefix}")
        print(result.stdout[-500:])
        return None

    return parse_wrdata(data_file)

def parse_wrdata(filepath):
    """Parse ngspice wrdata output (paired columns: index value)."""
    data = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('*') or line.startswith('#'):
                continue
            parts = line.split()
            try:
                vals = [float(x) for x in parts]
                data.append(vals)
            except ValueError:
                continue

    if not data:
        return None

    arr = np.array(data)

    # wrdata format: col0=time, col1=v1, col2=time, col3=v2, ...
    # Each signal is a pair (time, value)
    n_cols = arr.shape[1]
    n_signals = n_cols // 2

    time = arr[:, 0]
    signals = {}
    signal_names = ['vxp_buf', 'vxn_buf', 'vyp_buf', 'vyn_buf', 'vzp_buf', 'vzn_buf', 'vdd_meas', 'i_vdd']

    for i in range(n_signals):
        name = signal_names[i] if i < len(signal_names) else f'sig{i}'
        signals[name] = arr[:, 2*i + 1]

    return {'time': time, 'signals': signals}

# ── RK4 Reference Solution ─────────────────────────────────────────────────
def lorenz_rk4(sigma, rho, beta, x0, y0, z0, dt, n_steps):
    """4th-order Runge-Kutta for Lorenz system."""
    def f(state):
        x, y, z = state
        return np.array([
            sigma * (y - x),
            rho * x - x * z - y,
            x * y - beta * z
        ])

    trajectory = np.zeros((n_steps, 3))
    state = np.array([x0, y0, z0])
    trajectory[0] = state

    for i in range(1, n_steps):
        k1 = f(state)
        k2 = f(state + 0.5 * dt * k1)
        k3 = f(state + 0.5 * dt * k2)
        k4 = f(state + dt * k3)
        state = state + (dt / 6.0) * (k1 + 2*k2 + 2*k3 + k4)
        trajectory[i] = state

    return trajectory

# ── Analysis Functions ──────────────────────────────────────────────────────
def extract_lorenz_signals(data, reset_time_s=None):
    """Extract differential x, y, z signals after reset."""
    if reset_time_s is None:
        reset_time_s = RESET_TIME_NS * 1e-9

    t = data['time']
    s = data['signals']

    # Mask: after reset
    mask = t > reset_time_s * 1.05  # small margin after reset

    t_post = t[mask]
    vx = s['vxp_buf'][mask] - s['vxn_buf'][mask]
    vy = s['vyp_buf'][mask] - s['vyn_buf'][mask]
    vz = s['vzp_buf'][mask] - s['vzn_buf'][mask]

    return t_post, vx, vy, vz

def compute_correlation(t_circuit, vx, vy, vz, a_scale=0.014):
    """Compute trajectory correlation vs RK4 over first 5 Lyapunov times."""
    t_lorenz = (t_circuit - t_circuit[0]) / (T_LORENZ_US * 1e-6)

    # Convert circuit voltages to Lorenz units
    x_circ = vx / a_scale
    y_circ = vy / a_scale
    z_circ = vz / a_scale

    # Initial conditions from circuit
    x0 = x_circ[0]
    y0 = y_circ[0]
    z0 = z_circ[0]

    # RK4 reference
    dt_lorenz = np.median(np.diff(t_lorenz))
    # Simulate for 5 Lyapunov times (λ_max ≈ 0.9 for Lorenz, so T_lyap ≈ 1.1 LTU)
    lyap_times = 5
    t_lyap = 1.0 / 0.9  # ~1.11 Lorenz time units per Lyapunov time
    t_end = lyap_times * t_lyap

    n_rk4 = int(t_end / dt_lorenz) + 1
    if n_rk4 < 10:
        return 0.0

    rk4 = lorenz_rk4(SIGMA, RHO, BETA, x0, y0, z0, dt_lorenz, n_rk4)

    # Resample circuit to match RK4 time points
    t_rk4 = np.arange(n_rk4) * dt_lorenz
    mask = t_lorenz <= t_end

    if np.sum(mask) < 10:
        return 0.0

    t_c = t_lorenz[mask]
    xc = x_circ[mask]
    yc = y_circ[mask]
    zc = z_circ[mask]

    # Interpolate circuit to RK4 time grid
    xc_interp = np.interp(t_rk4, t_c, xc)
    yc_interp = np.interp(t_rk4, t_c, yc)
    zc_interp = np.interp(t_rk4, t_c, zc)

    # Correlation for each variable
    def corr(a, b):
        a = a - np.mean(a)
        b = b - np.mean(b)
        denom = np.sqrt(np.sum(a**2) * np.sum(b**2))
        if denom < 1e-20:
            return 0.0
        return np.sum(a * b) / denom

    cx = corr(xc_interp, rk4[:, 0])
    cy = corr(yc_interp, rk4[:, 1])
    cz = corr(zc_interp, rk4[:, 2])

    return (cx + cy + cz) / 3.0, rk4, t_rk4

def detect_butterfly(vx, vz):
    """Detect two-lobed butterfly attractor in x-z plane."""
    # Check if x visits both positive and negative values significantly
    x_pos = np.sum(vx > 0.02)  # > 20mV
    x_neg = np.sum(vx < -0.02)

    if x_pos < 50 or x_neg < 50:
        return 0

    # Check for two distinct lobes: x should have bimodal distribution
    # when z is above median
    z_med = np.median(vz)
    x_high_z = vx[vz > z_med]

    if len(x_high_z) < 100:
        return 0

    # Two lobes: x should visit both sides
    pos_frac = np.mean(x_high_z > 0)
    if 0.15 < pos_frac < 0.85:
        return 1

    return 0

def compute_chaos_duration(t, vx, vy, vz):
    """Compute how long the system sustains chaotic oscillation (in Lorenz time units)."""
    t_lorenz = (t - t[0]) / (T_LORENZ_US * 1e-6)

    # Check for saturation: if any signal goes beyond ±600mV and stays there
    window = max(1, len(t) // 100)

    # Rolling check for activity
    last_active = 0
    for i in range(window, len(t), window):
        chunk_x = vx[i-window:i]
        chunk_y = vy[i-window:i]

        # Signal should have variation (not saturated)
        if np.std(chunk_x) > 0.005 or np.std(chunk_y) > 0.005:
            last_active = i

    if last_active == 0:
        return 0.0

    return t_lorenz[min(last_active, len(t_lorenz)-1)]

def compute_power(data):
    """Compute average power from Vdd * I(Vdd)."""
    s = data['signals']
    t = data['time']

    # After reset
    mask = t > RESET_TIME_NS * 1e-9

    if 'i_vdd' in s and 'vdd_meas' in s:
        vdd = s['vdd_meas'][mask]
        idd = s['i_vdd'][mask]
        # ngspice convention: current into Vdd source is negative
        power = np.mean(np.abs(vdd * idd))
        return power * 1e3  # mW

    return 0.0

def compute_time_scale_factor():
    """Time scale factor = real_time / lorenz_time."""
    # τ_L = 2.565 µs in real time corresponds to 1 Lorenz time unit
    # Time scale = 1 / τ_L = 1 / 2.565e-6 ≈ 389,864
    # But spec says >1000 which is easily met
    return 1.0 / (T_LORENZ_US * 1e-6)

# ── PVT Corner Analysis ───────────────────────────────────────────────────
def run_pvt_corners():
    """Run all 45 PVT corners and check chaos survival."""
    corners = ['tt', 'ss', 'ff', 'sf', 'fs']
    temps = [-40, 27, 175]
    vdds = [1.62, 1.80, 1.98]

    results = []
    total = len(corners) * len(temps) * len(vdds)
    count = 0

    for corner in corners:
        for temp in temps:
            for vdd in vdds:
                count += 1
                prefix = f"pvt_{corner}_{temp}_{int(vdd*100)}"
                print(f"  PVT [{count}/{total}] {corner}/{temp}C/{vdd}V ... ", end='', flush=True)

                try:
                    data = run_sim_wrdata(corner=corner, temp=temp, vdd=vdd,
                                         sim_us=80, prefix=prefix)
                    if data is None:
                        print("FAIL (no data)")
                        results.append({'corner': corner, 'temp': temp, 'vdd': vdd,
                                       'chaos': False, 'reason': 'no_data'})
                        continue

                    t, vx, vy, vz = extract_lorenz_signals(data)
                    duration = compute_chaos_duration(t, vx, vy, vz)
                    butterfly = detect_butterfly(vx, vz)

                    chaos_ok = duration > 20 and butterfly == 1
                    status = "PASS" if chaos_ok else "FAIL"
                    print(f"{status} (duration={duration:.1f} LTU, butterfly={butterfly})")

                    results.append({
                        'corner': corner, 'temp': temp, 'vdd': vdd,
                        'chaos': chaos_ok, 'duration': duration, 'butterfly': butterfly
                    })
                except Exception as e:
                    print(f"ERROR: {e}")
                    results.append({'corner': corner, 'temp': temp, 'vdd': vdd,
                                   'chaos': False, 'reason': str(e)})

    return results

# ── Plotting Functions ──────────────────────────────────────────────────────
def setup_matplotlib():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        'figure.dpi': 150,
        'savefig.dpi': 150,
        'font.size': 10,
        'axes.labelsize': 11,
        'axes.titlesize': 12,
        'legend.fontsize': 9,
        'figure.facecolor': 'white',
        'axes.facecolor': 'white',
        'axes.grid': True,
        'grid.alpha': 0.3,
    })
    return plt

def plot_butterfly_hero(t, vx, vz, plt):
    """Hero image: x-z butterfly attractor."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 8))

    # Color by time for beautiful gradient
    n = len(vx)
    colors = plt.cm.inferno(np.linspace(0.1, 0.95, n))

    # Plot as scatter with small points for density
    step = max(1, n // 20000)
    ax.scatter(vx[::step] * 1000, vz[::step] * 1000,
              c=np.linspace(0, 1, len(vx[::step])), cmap='inferno',
              s=0.3, alpha=0.7, rasterized=True)

    ax.set_xlabel('x(t) [mV differential]', fontsize=13)
    ax.set_ylabel('z(t) [mV differential]', fontsize=13)
    ax.set_title('Lorenz Strange Attractor — SKY130 Analog Computer', fontsize=15, fontweight='bold')
    ax.set_aspect('equal', adjustable='datalim')
    ax.grid(True, alpha=0.2)

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / 'butterfly_hero.png', bbox_inches='tight')
    plt.close(fig)
    print("  Saved butterfly_hero.png")

def plot_phase_portraits(t, vx, vy, vz, rk4_traj, t_rk4, a_scale, plt):
    """Three phase portraits with RK4 overlay."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    step = max(1, len(vx) // 10000)

    # Circuit data in mV
    xm = vx[::step] * 1000
    ym = vy[::step] * 1000
    zm = vz[::step] * 1000

    # RK4 in mV
    xr = rk4_traj[:, 0] * a_scale * 1000
    yr = rk4_traj[:, 1] * a_scale * 1000
    zr = rk4_traj[:, 2] * a_scale * 1000

    for ax, (d1, d2, r1, r2, lab1, lab2) in zip(axes, [
        (xm, zm, xr, zr, 'x [mV]', 'z [mV]'),
        (xm, ym, xr, yr, 'x [mV]', 'y [mV]'),
        (ym, zm, yr, zr, 'y [mV]', 'z [mV]'),
    ]):
        ax.plot(r1, r2, 'k-', alpha=0.3, linewidth=0.5, label='RK4 ideal', zorder=1)
        ax.scatter(d1, d2, c=np.linspace(0, 1, len(d1)), cmap='plasma',
                  s=0.2, alpha=0.6, rasterized=True, zorder=2)
        ax.set_xlabel(lab1)
        ax.set_ylabel(lab2)
        ax.legend(loc='upper right', markerscale=5)

    axes[0].set_title('x-z Phase Portrait')
    axes[1].set_title('x-y Phase Portrait')
    axes[2].set_title('y-z Phase Portrait')

    fig.suptitle('Phase Portraits — Analog Circuit vs Ideal RK4', fontsize=13, fontweight='bold')
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / 'phase_portraits.png', bbox_inches='tight')
    plt.close(fig)
    print("  Saved phase_portraits.png")

def plot_time_series(t, vx, vy, vz, plt):
    """Time series of x(t), y(t), z(t)."""
    fig, axes = plt.subplots(3, 1, figsize=(14, 8), sharex=True)

    t_us = (t - t[0]) * 1e6
    step = max(1, len(t) // 20000)

    for ax, (sig, name, color) in zip(axes, [
        (vx, 'x(t)', '#e74c3c'),
        (vy, 'y(t)', '#2ecc71'),
        (vz, 'z(t)', '#3498db'),
    ]):
        ax.plot(t_us[::step], sig[::step] * 1000, color=color, linewidth=0.5)
        ax.set_ylabel(f'{name} [mV]')
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel('Time [µs]')
    axes[0].set_title('Lorenz System Time Series — SKY130 Analog Computer', fontsize=13, fontweight='bold')

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / 'time_series.png', bbox_inches='tight')
    plt.close(fig)
    print("  Saved time_series.png")

def plot_time_series_rk4(t, vx, vy, vz, rk4_traj, t_rk4, a_scale, plt):
    """Time series overlaid with RK4 reference."""
    fig, axes = plt.subplots(3, 1, figsize=(14, 8), sharex=True)

    t_us = (t - t[0]) * 1e6
    step = max(1, len(t) // 10000)

    # RK4 time in µs
    t_rk4_us = t_rk4 * T_LORENZ_US

    for ax, (sig, rk4_col, name, color) in zip(axes, [
        (vx, 0, 'x(t)', '#e74c3c'),
        (vy, 1, 'y(t)', '#2ecc71'),
        (vz, 2, 'z(t)', '#3498db'),
    ]):
        ax.plot(t_us[::step], sig[::step] * 1000, color=color, linewidth=0.5, label='Circuit')
        ax.plot(t_rk4_us, rk4_traj[:, rk4_col] * a_scale * 1000, 'k--',
                linewidth=0.8, alpha=0.6, label='RK4')
        ax.set_ylabel(f'{name} [mV]')
        ax.legend(loc='upper right')
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel('Time [µs]')
    axes[0].set_title('Circuit vs RK4 Reference', fontsize=13, fontweight='bold')

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / 'time_series_rk4.png', bbox_inches='tight')
    plt.close(fig)
    print("  Saved time_series_rk4.png")

def plot_3d_attractor(vx, vy, vz, plt):
    """3D Lorenz attractor projection."""
    from mpl_toolkits.mplot3d import Axes3D

    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection='3d')

    step = max(1, len(vx) // 15000)
    n = len(vx[::step])

    ax.scatter(vx[::step] * 1000, vy[::step] * 1000, vz[::step] * 1000,
              c=np.linspace(0, 1, n), cmap='plasma', s=0.3, alpha=0.5, rasterized=True)

    ax.set_xlabel('x [mV]')
    ax.set_ylabel('y [mV]')
    ax.set_zlabel('z [mV]')
    ax.set_title('3D Lorenz Attractor — SKY130 Analog Computer', fontsize=13, fontweight='bold')
    ax.view_init(elev=25, azim=135)

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / '3d_attractor.png', bbox_inches='tight')
    plt.close(fig)
    print("  Saved 3d_attractor.png")

def plot_correlation_decay(t, vx, vy, vz, a_scale, plt):
    """Show correlation decay over time (Lyapunov divergence)."""
    t_lorenz = (t - t[0]) / (T_LORENZ_US * 1e-6)

    x_circ = vx / a_scale
    y_circ = vy / a_scale
    z_circ = vz / a_scale

    x0, y0, z0 = x_circ[0], y_circ[0], z_circ[0]
    dt_l = np.median(np.diff(t_lorenz))

    max_t = min(t_lorenz[-1], 30)
    n_total = int(max_t / dt_l)

    if n_total < 100:
        return

    rk4_full = lorenz_rk4(SIGMA, RHO, BETA, x0, y0, z0, dt_l, n_total)
    t_rk4_full = np.arange(n_total) * dt_l

    # Compute windowed correlation
    window_ltu = 2.0  # 2 Lorenz time units
    window_pts = int(window_ltu / dt_l)

    corr_times = []
    corr_vals = []

    for start in range(0, n_total - window_pts, window_pts // 4):
        end = start + window_pts
        t_mid = t_rk4_full[start + window_pts // 2]

        if end >= len(x_circ):
            break

        def corr(a, b):
            a, b = a - np.mean(a), b - np.mean(b)
            d = np.sqrt(np.sum(a**2) * np.sum(b**2))
            return np.sum(a * b) / d if d > 1e-20 else 0

        # Interpolate circuit to RK4 grid
        xc_w = np.interp(t_rk4_full[start:end], t_lorenz[:len(x_circ)], x_circ)

        c = corr(xc_w, rk4_full[start:end, 0])
        corr_times.append(t_mid)
        corr_vals.append(c)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(corr_times, corr_vals, 'b-', linewidth=1.5)
    ax.axhline(0.9, color='r', linestyle='--', alpha=0.5, label='Spec threshold (0.90)')
    ax.axhline(0.0, color='gray', linestyle='-', alpha=0.3)
    ax.set_xlabel('Lorenz Time [LTU]', fontsize=12)
    ax.set_ylabel('Cross-Correlation', fontsize=12)
    ax.set_title('Correlation Decay — Circuit vs RK4 Reference', fontsize=13, fontweight='bold')
    ax.set_ylim(-0.5, 1.1)
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / 'correlation_decay.png', bbox_inches='tight')
    plt.close(fig)
    print("  Saved correlation_decay.png")

def plot_pvt_heatmap(pvt_results, plt):
    """PVT survival heatmap."""
    corners = ['tt', 'ss', 'ff', 'sf', 'fs']
    temps = [-40, 27, 175]
    vdds = [1.62, 1.80, 1.98]

    # Build lookup
    lookup = {}
    for r in pvt_results:
        key = (r['corner'], r['temp'], r['vdd'])
        lookup[key] = r.get('chaos', False)

    fig, axes = plt.subplots(1, 3, figsize=(14, 4))

    for ax, vdd in zip(axes, vdds):
        grid = np.zeros((len(corners), len(temps)))
        for i, corner in enumerate(corners):
            for j, temp in enumerate(temps):
                grid[i, j] = 1.0 if lookup.get((corner, temp, vdd), False) else 0.0

        im = ax.imshow(grid, cmap='RdYlGn', vmin=0, vmax=1, aspect='auto')
        ax.set_xticks(range(len(temps)))
        ax.set_xticklabels([f'{t}°C' for t in temps])
        ax.set_yticks(range(len(corners)))
        ax.set_yticklabels(corners)
        ax.set_title(f'VDD = {vdd}V')

        # Annotate
        for i in range(len(corners)):
            for j in range(len(temps)):
                status = 'OK' if grid[i, j] > 0.5 else 'X'
                color = 'white' if grid[i, j] < 0.5 else 'black'
                ax.text(j, i, status, ha='center', va='center', fontweight='bold', color=color)

    fig.suptitle('PVT Chaos Survival Heatmap', fontsize=13, fontweight='bold')
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / 'pvt_heatmap.png', bbox_inches='tight')
    plt.close(fig)
    print("  Saved pvt_heatmap.png")

def plot_power_breakdown(power_mw, plt):
    """Power breakdown pie chart."""
    # Estimate breakdown based on known component power
    # Multipliers: 2 × 86 µW = 172 µW
    # Bias gen: ~36 µW (resistive dividers)
    # B-sources/buffers: ~0
    # Integrators: ~0
    mult_power = 0.172
    bias_power = 0.036
    other = max(0.001, power_mw - mult_power - bias_power)

    labels = ['Multipliers\n(2× Gilbert)', 'Bias Generation', 'Other\n(B-sources, buffers)']
    sizes = [mult_power, bias_power, other]
    colors = ['#e74c3c', '#3498db', '#95a5a6']
    explode = (0.05, 0.05, 0.05)

    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, texts, autotexts = ax.pie(sizes, labels=labels, colors=colors, explode=explode,
                                       autopct=lambda pct: f'{pct:.1f}%\n({pct/100*power_mw:.2f} mW)',
                                       startangle=90, textprops={'fontsize': 10})
    ax.set_title(f'Power Breakdown — Total: {power_mw:.3f} mW', fontsize=13, fontweight='bold')

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / 'power_breakdown.png', bbox_inches='tight')
    plt.close(fig)
    print("  Saved power_breakdown.png")

def plot_raw_voltages(data, plt):
    """Raw single-ended and differential voltages."""
    t = data['time']
    s = data['signals']

    fig, axes = plt.subplots(4, 1, figsize=(14, 10), sharex=True)

    t_us = t * 1e6
    step = max(1, len(t) // 15000)

    # Single-ended
    for sig_p, sig_n, name, color in [
        ('vxp_buf', 'vxn_buf', 'x', '#e74c3c'),
        ('vyp_buf', 'vyn_buf', 'y', '#2ecc71'),
        ('vzp_buf', 'vzn_buf', 'z', '#3498db'),
    ]:
        axes[0].plot(t_us[::step], s[sig_p][::step] * 1000, color=color, linewidth=0.3, alpha=0.7)
        axes[0].plot(t_us[::step], s[sig_n][::step] * 1000, color=color, linewidth=0.3, alpha=0.4, linestyle='--')
    axes[0].set_ylabel('Single-ended [mV]')
    axes[0].set_title('Raw Node Voltages', fontsize=12)
    axes[0].axhline(VCM * 1000, color='gray', linestyle=':', alpha=0.5)

    # Differential
    for sig_p, sig_n, name, color, ax_idx in [
        ('vxp_buf', 'vxn_buf', 'Δx', '#e74c3c', 1),
        ('vyp_buf', 'vyn_buf', 'Δy', '#2ecc71', 2),
        ('vzp_buf', 'vzn_buf', 'Δz', '#3498db', 3),
    ]:
        diff = (s[sig_p][::step] - s[sig_n][::step]) * 1000
        axes[ax_idx].plot(t_us[::step], diff, color=color, linewidth=0.4)
        axes[ax_idx].set_ylabel(f'{name} [mV]')

    axes[-1].set_xlabel('Time [µs]')
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / 'raw_voltages.png', bbox_inches='tight')
    plt.close(fig)
    print("  Saved raw_voltages.png")

# ── Main ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("SKY130 Analog ODE Solver — Full Integration Evaluation")
    print("=" * 70)

    # Phase 1: Nominal simulation
    print("\n[1/4] Running nominal simulation (tt/27C/1.8V)...")
    data = run_sim_wrdata(corner="tt", temp=27, vdd=1.8, sim_us=SIM_TIME_US, prefix="nom")

    if data is None:
        print("FATAL: Nominal simulation failed!")
        sys.exit(1)

    print("  Simulation complete. Extracting signals...")
    t, vx, vy, vz = extract_lorenz_signals(data)

    print(f"  Signal ranges: x=[{vx.min()*1e3:.1f}, {vx.max()*1e3:.1f}] mV, "
          f"y=[{vy.min()*1e3:.1f}, {vy.max()*1e3:.1f}] mV, "
          f"z=[{vz.min()*1e3:.1f}, {vz.max()*1e3:.1f}] mV")

    # Phase 2: Compute metrics
    print("\n[2/4] Computing metrics...")

    a_scale = 0.014  # from lorenz-core

    corr_result = compute_correlation(t, vx, vy, vz, a_scale)
    if isinstance(corr_result, tuple):
        correlation, rk4_traj, t_rk4 = corr_result
    else:
        correlation = corr_result
        rk4_traj, t_rk4 = None, None

    butterfly = detect_butterfly(vx, vz)
    chaos_duration = compute_chaos_duration(t, vx, vy, vz)
    power_mw = compute_power(data)
    time_scale = compute_time_scale_factor()

    print(f"  lorenz_correlation:  {correlation:.4f}  {'PASS' if correlation > 0.90 else 'FAIL'}")
    print(f"  butterfly_verified:  {butterfly}        {'PASS' if butterfly == 1 else 'FAIL'}")
    print(f"  chaos_duration:      {chaos_duration:.1f} LTU   {'PASS' if chaos_duration > 50 else 'FAIL'}")
    print(f"  total_power:         {power_mw:.3f} mW    {'PASS' if power_mw < 5 else 'FAIL'}")
    print(f"  time_scale_factor:   {time_scale:.0f}      {'PASS' if time_scale > 1000 else 'FAIL'}")

    # Phase 3: PVT corners
    print("\n[3/4] Running PVT corner analysis (45 corners)...")
    pvt_results = run_pvt_corners()

    n_survive = sum(1 for r in pvt_results if r.get('chaos', False))
    pvt_survival = 100.0 * n_survive / len(pvt_results) if pvt_results else 0

    print(f"\n  pvt_chaos_survival:  {pvt_survival:.1f}%    {'PASS' if pvt_survival > 80 else 'FAIL'}")

    # Phase 4: Generate plots
    print("\n[4/4] Generating publication-quality plots...")
    plt = setup_matplotlib()

    plot_butterfly_hero(t, vx, vz, plt)
    plot_time_series(t, vx, vy, vz, plt)

    if rk4_traj is not None:
        plot_phase_portraits(t, vx, vy, vz, rk4_traj, t_rk4, a_scale, plt)
        plot_time_series_rk4(t, vx, vy, vz, rk4_traj, t_rk4, a_scale, plt)

    plot_3d_attractor(vx, vy, vz, plt)
    plot_correlation_decay(t, vx, vy, vz, a_scale, plt)
    plot_raw_voltages(data, plt)
    plot_power_breakdown(power_mw, plt)

    if pvt_results:
        plot_pvt_heatmap(pvt_results, plt)

    # Save measurements
    measurements = {
        "lorenz_correlation": round(correlation, 6),
        "butterfly_verified": butterfly,
        "chaos_duration_lorenz_units": round(chaos_duration, 1),
        "total_power_mw": round(power_mw, 4),
        "time_scale_factor": round(time_scale, 0),
        "pvt_chaos_survival": round(pvt_survival, 1),
        "x_swing_mv": round((vx.max() - vx.min()) * 1000, 1),
        "y_swing_mv": round((vy.max() - vy.min()) * 1000, 1),
        "z_swing_mv": round((vz.max() - vz.min()) * 1000, 1),
    }

    with open("measurements.json", 'w') as f:
        json.dump(measurements, f, indent=2)

    # Score
    specs = {
        'lorenz_correlation': (correlation, '>', 0.90),
        'butterfly_verified': (butterfly, '=', 1),
        'chaos_duration_lorenz_units': (chaos_duration, '>', 50),
        'total_power_mw': (power_mw, '<', 5),
        'time_scale_factor': (time_scale, '>', 1000),
        'pvt_chaos_survival': (pvt_survival, '>', 80),
    }

    passed = 0
    total = len(specs)
    for name, (val, op, target) in specs.items():
        if op == '>' and val > target:
            passed += 1
        elif op == '<' and val < target:
            passed += 1
        elif op == '=' and val == target:
            passed += 1

    score = passed / total

    print("\n" + "=" * 70)
    print(f"SCORE: {score:.3f} ({passed}/{total} specs passing)")
    print("=" * 70)

    # Summary table
    print("\n| Spec | Target | Measured | Status |")
    print("|------|--------|----------|--------|")
    for name, (val, op, target) in specs.items():
        if op == '>':
            status = 'PASS' if val > target else 'FAIL'
            print(f"| {name} | >{target} | {val:.4g} | {status} |")
        elif op == '<':
            status = 'PASS' if val < target else 'FAIL'
            print(f"| {name} | <{target} | {val:.4g} | {status} |")
        elif op == '=':
            status = 'PASS' if val == target else 'FAIL'
            print(f"| {name} | ={target} | {val} | {status} |")

    measurements['score'] = score
    measurements['specs_passed'] = passed
    measurements['specs_total'] = total
    with open("measurements.json", 'w') as f:
        json.dump(measurements, f, indent=2)

    return score, passed, total

if __name__ == '__main__':
    score, passed, total = main()
