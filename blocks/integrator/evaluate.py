"""
evaluate.py — Simulation and validation for Gm-C Integrator on SKY130.

Measures: DC gain, unity-gain frequency, output swing, leakage drift,
          reset time, charge injection, power.
"""

import os
import json
import csv
import re
import argparse
import subprocess
import tempfile
import shutil
from typing import Dict, List, Tuple, Optional

import numpy as np

NGSPICE = os.environ.get("NGSPICE", "ngspice")
DESIGN_FILE = "design.cir"
PARAMS_FILE = "parameters.csv"
SPECS_FILE = "specs.json"
PLOTS_DIR = "plots"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(PROJECT_DIR, "sky130_models")

TEMPERATURES = [-40, 24, 175]
SUPPLY_VOLTAGES = [1.62, 1.8, 1.98]
PROCESS_CORNERS = ["tt", "ss", "ff", "sf", "fs"]


def load_specs(path: str = SPECS_FILE) -> Dict:
    filepath = os.path.join(PROJECT_DIR, path) if not os.path.isabs(path) else path
    with open(filepath) as f:
        return json.load(f)


def load_design(path: str = DESIGN_FILE) -> str:
    filepath = os.path.join(PROJECT_DIR, path) if not os.path.isabs(path) else path
    with open(filepath) as f:
        return f.read()


def run_ngspice(netlist: str, timeout: int = 120) -> str:
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False, dir=PROJECT_DIR) as f:
        f.write(netlist)
        f.flush()
        tmpfile = f.name
    try:
        result = subprocess.run(
            [NGSPICE, "-b", tmpfile],
            capture_output=True, text=True, timeout=timeout,
            cwd=PROJECT_DIR
        )
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return "ERROR: ngspice timeout"
    finally:
        try:
            os.unlink(tmpfile)
        except OSError:
            pass


def parse_measure(output: str, name: str) -> Optional[float]:
    """Parse a .measure result from ngspice output."""
    patterns = [
        rf'{name}\s*=\s*([+-]?[\d.eE+-]+)',
        rf'{name}\s*=\s*([+-]?[\d.]+)',
    ]
    for pat in patterns:
        m = re.search(pat, output, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


def write_rawfile_netlist(netlist: str) -> Tuple[str, str]:
    """Write netlist to temp file and return (netlist_path, rawfile_path)."""
    raw_path = tempfile.mktemp(suffix='.raw', dir=PROJECT_DIR)
    # Inject .raw file save
    netlist_with_raw = netlist
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False, dir=PROJECT_DIR) as f:
        f.write(netlist_with_raw)
        f.flush()
        return f.name, raw_path


def make_lib_include(corner: str = "tt") -> str:
    return f'.lib "{MODEL_DIR}/sky130.lib.spice" {corner}'


def make_design_include() -> str:
    design_path = os.path.join(PROJECT_DIR, DESIGN_FILE)
    return f'.include "{design_path}"'


# ============================================================
# Test 1: DC Gain and Unity-Gain Frequency (AC analysis)
# ============================================================
def measure_ac(corner="tt", temp=27, vdd=1.8) -> Dict:
    """
    Measure DC gain and unity-gain frequency of the integrator.
    Inject AC current into the integration node, measure V/I transfer function.
    DC gain = Rout (output impedance at DC) referenced to a nominal Gm.
    """
    netlist = f"""DC Gain and Unity-Gain Frequency Test
{make_lib_include(corner)}
{make_design_include()}

.param vdd_val={vdd}
.param vcm_val={{vdd_val/2}}

Vdd vdd 0 {{vdd_val}}
Vss vss 0 0
Vcm vcm 0 {{vcm_val}}
Vbias vbias_n 0 0.6
Vrst reset 0 0

* Instantiate integrator
XI inp inn outp outn reset vbias_n vcm vdd vss integrator

* Bias output nodes to VCM via large resistors (DC operating point)
Rbp outp vcm 100G
Rbn outn vcm 100G

* AC current source: inject differential current
* I into outp, -I out of outn
Iac_p inp vcm DC 0 AC 1
Iac_n vcm inn DC 0 AC 1

.control
set filetype=ascii
set wr_vecnames
option temp={temp}

* AC sweep from 0.1 Hz to 100 MHz
ac dec 100 0.1 100Meg

* Measure differential output voltage = V(outp) - V(outn)
let vdiff_mag = vm(outp,outn)
let vdiff_db = vdb(outp,outn)

* DC gain is the magnitude at lowest frequency
let dc_gain_mag = vdiff_mag[0]
let dc_gain_db = vdiff_db[0]

* Find unity gain frequency (where |H| = 1, i.e., 0 dB transimpedance)
* The transimpedance at UGF: |V/I| = 1/(2*pi*f*C), so f_ugf = 1/(2*pi*C)
* But we reference to Gm: voltage gain = Gm * |V/I|
* For Gm = 100uS, UGF = Gm/(2*pi*C)

print dc_gain_mag dc_gain_db

wrdata ac_results.txt vdiff_db vdiff_mag
.endc

.end
"""
    output = run_ngspice(netlist)

    results = {}
    # Parse DC gain
    dc_gain_mag = parse_measure(output, "dc_gain_mag")
    dc_gain_db = parse_measure(output, "dc_gain_db")

    # Try to read AC data file for more accurate UGF
    ac_file = os.path.join(PROJECT_DIR, "ac_results.txt")
    ugf = None
    if os.path.exists(ac_file):
        try:
            data = np.loadtxt(ac_file, skiprows=1)
            if data.ndim == 2 and data.shape[1] >= 3:
                freqs = data[:, 0]
                # Column order: freq, vdiff_db_real, vdiff_db_imag, vdiff_mag_real, vdiff_mag_imag
                mag_db = data[:, 1]  # real part of dB
                mag_lin = data[:, 3] if data.shape[1] >= 4 else 10**(mag_db/20)

                # DC gain from low-frequency data
                if dc_gain_db is None:
                    dc_gain_db = mag_db[0]
                if dc_gain_mag is None:
                    dc_gain_mag = mag_lin[0]

                # Transimpedance UGF: where |V/I| = 1 (0 dB)
                # This is the transimpedance. For integrator voltage gain with Gm:
                # A_v = Gm * Z_out, UGF_voltage = Gm / (2*pi*C)
                # We measure transimpedance directly.
                # Find where magnitude crosses 1.0 (0 dB)
                for i in range(len(mag_lin) - 1):
                    if mag_lin[i] >= 1.0 and mag_lin[i+1] < 1.0:
                        # Interpolate
                        f1, f2 = freqs[i], freqs[i+1]
                        m1, m2 = mag_lin[i], mag_lin[i+1]
                        ugf = f1 * (f2/f1) ** ((1.0 - m1) / (m2 - m1))
                        break
            os.unlink(ac_file)
        except Exception as e:
            print(f"  Warning: AC data parse error: {e}")
            if os.path.exists(ac_file):
                os.unlink(ac_file)

    # DC gain in dB: the transimpedance at DC in dB
    # For an integrator with Gm=100uS feeding it:
    # Voltage gain = Gm * Rout. DC_gain_dB = 20*log10(Gm * Rout)
    # Rout = dc_gain_mag (transimpedance magnitude at DC)
    # We'll use Gm_ref = 100uS as the system reference
    Gm_ref = 100e-6  # 100 µS reference transconductance

    if dc_gain_mag is not None and dc_gain_mag > 0:
        voltage_gain = Gm_ref * dc_gain_mag
        results["dc_gain_db"] = 20 * np.log10(voltage_gain) if voltage_gain > 0 else 0
    elif dc_gain_db is not None:
        # dc_gain_db is 20*log10(Rout), voltage gain = Gm*Rout
        results["dc_gain_db"] = dc_gain_db + 20 * np.log10(Gm_ref)
    else:
        results["dc_gain_db"] = 0

    # UGF: for voltage gain, UGF = Gm/(2*pi*C)
    # From transimpedance UGF (|Z|=1): f_z1 = 1/(2*pi*C)
    # Voltage UGF = Gm * f_z1_transimpedance ... no, let's think again.
    # H_v(f) = Gm/(j*2*pi*f*C) for ideal integrator
    # |H_v(f_ugf)| = 1 => f_ugf = Gm/(2*pi*C)
    # H_z(f) = 1/(j*2*pi*f*C)
    # |H_z(f_z1)| = 1 => f_z1 = 1/(2*pi*C)
    # So f_ugf = Gm * f_z1
    if ugf is not None:
        results["unity_gain_freq_mhz"] = ugf * Gm_ref / 1e6
    else:
        # Estimate from DC gain: f_ugf ~ DC_gain * f_lowcorner
        # Or from cap value: ~5pF, Gm=100uS => f_ugf = 100e-6/(2*pi*5e-12) = 3.18 MHz
        results["unity_gain_freq_mhz"] = 0

    results["_dc_gain_mag"] = dc_gain_mag
    results["_ugf_transimpedance"] = ugf
    return results


# ============================================================
# Test 2: Output Swing
# ============================================================
def measure_swing(corner="tt", temp=27, vdd=1.8) -> Dict:
    """
    Apply a constant current to charge the cap, measure max swing before clipping.
    """
    netlist = f"""Output Swing Test
{make_lib_include(corner)}
{make_design_include()}

.param vdd_val={vdd}
.param vcm_val={{vdd_val/2}}

Vdd vdd 0 {{vdd_val}}
Vss vss 0 0
Vcm vcm 0 {{vcm_val}}
Vbias vbias_n 0 0.6
Vrst reset 0 0

XI inp inn outp outn reset vbias_n vcm vdd vss integrator

* Apply constant current to charge cap (ramp output up)
* 10uA into outp, out of outn
Icharge_p vcm inp DC 10u
Icharge_n inn vcm DC 10u

.control
set filetype=ascii
option temp={temp}

* Run transient for enough time to ramp output
tran 1n 5u

* Measure peak output voltage
meas tran voutp_max MAX V(outp)
meas tran voutn_min MIN V(outn)
meas tran voutp_init FIND V(outp) AT=10n
meas tran voutn_init FIND V(outn) AT=10n

print voutp_max voutn_min voutp_init voutn_init

wrdata swing_results.txt V(outp) V(outn)
.endc

.end
"""
    output = run_ngspice(netlist)

    results = {}
    voutp_max = parse_measure(output, "voutp_max")
    voutn_min = parse_measure(output, "voutn_min")
    voutp_init = parse_measure(output, "voutp_init")
    voutn_init = parse_measure(output, "voutn_init")

    vcm = vdd / 2
    swing = 0
    if voutp_max is not None and voutp_init is not None:
        swing_p = (voutp_max - vcm) * 1000  # mV above VCM
        swing_n = (vcm - voutn_min) * 1000 if voutn_min is not None else swing_p
        swing = min(abs(swing_p), abs(swing_n))

    results["output_swing_mv"] = swing
    results["_voutp_max"] = voutp_max
    results["_voutn_min"] = voutn_min

    # Clean up
    for f in ["swing_results.txt"]:
        fp = os.path.join(PROJECT_DIR, f)
        if os.path.exists(fp):
            os.unlink(fp)

    return results


# ============================================================
# Test 3: Leakage Drift
# ============================================================
def measure_leakage(corner="tt", temp=27, vdd=1.8) -> Dict:
    """
    Reset integrator, release reset, measure output drift with zero input.
    """
    netlist = f"""Leakage Drift Test
{make_lib_include(corner)}
{make_design_include()}

.param vdd_val={vdd}
.param vcm_val={{vdd_val/2}}

Vdd vdd 0 {{vdd_val}}
Vss vss 0 0
Vcm vcm 0 {{vcm_val}}
Vbias vbias_n 0 0.6

* Reset: high for first 100ns, then low
Vrst reset 0 PWL(0 {{vdd_val}} 95n {{vdd_val}} 100n 0)

XI inp inn outp outn reset vbias_n vcm vdd vss integrator

* No input current (open circuit on inp/inn)
* Small resistors to ground to avoid floating node issues
Rp inp vcm 100G
Rn inn vcm 100G

.control
set filetype=ascii
option temp={temp}

tran 1n 60u

* Measure voltage at two time points after reset release
meas tran v1 FIND V(outp) AT=1u
meas tran v2 FIND V(outp) AT=51u
meas tran vn1 FIND V(outn) AT=1u
meas tran vn2 FIND V(outn) AT=51u

print v1 v2 vn1 vn2

wrdata leakage_results.txt V(outp) V(outn)
.endc

.end
"""
    output = run_ngspice(netlist)

    results = {}
    v1 = parse_measure(output, "v1")
    v2 = parse_measure(output, "v2")
    vn1 = parse_measure(output, "vn1")
    vn2 = parse_measure(output, "vn2")

    if v1 is not None and v2 is not None:
        dt = 50e-6  # 50 µs
        drift_p = abs(v2 - v1) / dt * 1e-3  # mV/µs
        drift_n = abs(vn2 - vn1) / dt * 1e-3 if vn1 is not None and vn2 is not None else drift_p
        results["leakage_mv_per_us"] = max(drift_p, drift_n)
    else:
        results["leakage_mv_per_us"] = 100  # fail

    results["_v1"] = v1
    results["_v2"] = v2

    for f in ["leakage_results.txt"]:
        fp = os.path.join(PROJECT_DIR, f)
        if os.path.exists(fp):
            os.unlink(fp)

    return results


# ============================================================
# Test 4: Reset Time and Charge Injection
# ============================================================
def measure_reset(corner="tt", temp=27, vdd=1.8) -> Dict:
    """
    Pre-charge cap to VCM+200mV, assert reset, measure settle time.
    Then release reset and measure charge injection.
    """
    vcm = vdd / 2
    v_init = vcm + 0.2  # Start 200mV above VCM

    netlist = f"""Reset Time and Charge Injection Test
{make_lib_include(corner)}
{make_design_include()}

.param vdd_val={vdd}
.param vcm_val={{vdd_val/2}}

Vdd vdd 0 {{vdd_val}}
Vss vss 0 0
Vcm vcm 0 {{vcm_val}}
Vbias vbias_n 0 0.6

* Reset sequence:
* 0-10ns: reset off, cap holds initial voltage
* 10ns: reset on (cap discharges to VCM)
* 200ns: reset off (charge injection)
Vrst reset 0 PWL(0 0 9n 0 10n {{vdd_val}} 199n {{vdd_val}} 200n 0)

XI inp inn outp outn reset vbias_n vcm vdd vss integrator

* Pre-charge outp to VCM+200mV, outn to VCM-200mV using IC
.ic V(outp)={v_init} V(outn)={vcm - 0.2}

* No input current
Rp inp vcm 100G
Rn inn vcm 100G

.control
set filetype=ascii
option temp={temp}

tran 0.1n 500n UIC

* Reset time: time from reset assertion (10ns) to within 1% of VCM
* VCM = vcm_val, 1% of 200mV = 2mV, so target = vcm_val +/- 2mV
meas tran t_settle WHEN V(outp)={vcm+0.002} RISE=1 TD=10n
meas tran t_reset_start FIND V(outp) AT=10n

* Charge injection: voltage just after reset release vs VCM
* Measure at 201ns (just after reset release) and at 250ns (settled)
meas tran v_before_release FIND V(outp) AT=199n
meas tran v_after_release FIND V(outp) AT=210n
meas tran v_settled FIND V(outp) AT=400n
meas tran vn_before_release FIND V(outn) AT=199n
meas tran vn_after_release FIND V(outn) AT=210n
meas tran vn_settled FIND V(outn) AT=400n

print t_settle v_before_release v_after_release v_settled
print vn_before_release vn_after_release vn_settled

wrdata reset_results.txt V(outp) V(outn) V(reset)
.endc

.end
"""
    output = run_ngspice(netlist)

    results = {}

    t_settle = parse_measure(output, "t_settle")
    v_before = parse_measure(output, "v_before_release")
    v_after = parse_measure(output, "v_after_release")
    v_settled = parse_measure(output, "v_settled")
    vn_before = parse_measure(output, "vn_before_release")
    vn_after = parse_measure(output, "vn_after_release")
    vn_settled = parse_measure(output, "vn_settled")

    # Reset time
    if t_settle is not None:
        results["reset_time_ns"] = (t_settle - 10e-9) * 1e9
    else:
        # Try to estimate from waveform file
        results["reset_time_ns"] = 100  # fail value

    # Charge injection: differential
    if v_settled is not None and vn_settled is not None:
        # Charge injection = how much the differential output moves from VCM after reset release
        v_diff_after = (v_settled - vn_settled)  # should be 0 for ideal
        charge_inject_mv = abs(v_diff_after) * 1000 / 2  # per side
        results["charge_inject_mv"] = charge_inject_mv

        # Also measure single-ended charge injection
        vcm_val = vdd / 2
        ci_p = abs(v_settled - vcm_val) * 1000
        ci_n = abs(vn_settled - vcm_val) * 1000
        results["_ci_single_p_mv"] = ci_p
        results["_ci_single_n_mv"] = ci_n
        results["charge_inject_mv"] = max(ci_p, ci_n)
    elif v_after is not None:
        vcm_val = vdd / 2
        results["charge_inject_mv"] = abs(v_after - vcm_val) * 1000
    else:
        results["charge_inject_mv"] = 100

    results["_v_before"] = v_before
    results["_v_after"] = v_after
    results["_v_settled"] = v_settled

    for f in ["reset_results.txt"]:
        fp = os.path.join(PROJECT_DIR, f)
        if os.path.exists(fp):
            os.unlink(fp)

    return results


# ============================================================
# Test 5: Power
# ============================================================
def measure_power(corner="tt", temp=27, vdd=1.8) -> Dict:
    """
    Measure quiescent power consumption with reset de-asserted.
    """
    netlist = f"""Power Consumption Test
{make_lib_include(corner)}
{make_design_include()}

.param vdd_val={vdd}
.param vcm_val={{vdd_val/2}}

Vdd vdd 0 {{vdd_val}}
Vss vss 0 0
Vcm vcm 0 {{vcm_val}}
Vbias vbias_n 0 0.6
Vrst reset 0 0

XI inp inn outp outn reset vbias_n vcm vdd vss integrator

Rp inp vcm 100G
Rn inn vcm 100G

.control
set filetype=ascii
option temp={temp}

* DC operating point
op

* Measure supply current
let ivdd = @Vdd[i]
let ivss = @Vss[i]
let ivcm = @Vcm[i]
let power_vdd = abs(ivdd) * {vdd}
let power_total = power_vdd

print ivdd ivss ivcm power_vdd power_total
.endc

.end
"""
    output = run_ngspice(netlist)

    results = {}
    power_total = parse_measure(output, "power_total")
    power_vdd = parse_measure(output, "power_vdd")
    ivdd = parse_measure(output, "ivdd")

    if power_total is not None:
        results["power_uw"] = abs(power_total) * 1e6
    elif ivdd is not None:
        results["power_uw"] = abs(ivdd) * vdd * 1e6
    else:
        results["power_uw"] = 0

    return results


# ============================================================
# Test 6: Integration linearity check
# ============================================================
def measure_integration(corner="tt", temp=27, vdd=1.8) -> Dict:
    """
    Apply constant current, verify output ramps linearly.
    """
    netlist = f"""Integration Linearity Test
{make_lib_include(corner)}
{make_design_include()}

.param vdd_val={vdd}
.param vcm_val={{vdd_val/2}}

Vdd vdd 0 {{vdd_val}}
Vss vss 0 0
Vcm vcm 0 {{vcm_val}}
Vbias vbias_n 0 0.6

* Reset for 100ns, then release
Vrst reset 0 PWL(0 {{vdd_val}} 95n {{vdd_val}} 100n 0)

XI inp inn outp outn reset vbias_n vcm vdd vss integrator

* Apply 10uA constant current after reset release
Icharge_p vcm inp DC 10u
Icharge_n inn vcm DC 10u

.control
set filetype=ascii
option temp={temp}

tran 1n 3u

* Measure ramp rate
meas tran v_t1 FIND V(outp) AT=0.5u
meas tran v_t2 FIND V(outp) AT=2.5u

print v_t1 v_t2

wrdata integration_results.txt V(outp) V(outn)
.endc

.end
"""
    output = run_ngspice(netlist)

    results = {}
    v_t1 = parse_measure(output, "v_t1")
    v_t2 = parse_measure(output, "v_t2")

    if v_t1 is not None and v_t2 is not None:
        dt = 2e-6  # 2 µs
        ramp_rate = (v_t2 - v_t1) / dt  # V/s
        # Expected: I/C = 10uA / 5pF = 2 V/µs = 2e6 V/s
        results["_ramp_rate_v_per_us"] = ramp_rate * 1e-6
        # Estimate capacitance: C = I / (dV/dt)
        if abs(ramp_rate) > 0:
            c_est = 10e-6 / abs(ramp_rate)
            results["c_int_pf"] = c_est * 1e12
    else:
        results["_ramp_rate_v_per_us"] = 0
        results["c_int_pf"] = 0

    for f in ["integration_results.txt"]:
        fp = os.path.join(PROJECT_DIR, f)
        if os.path.exists(fp):
            os.unlink(fp)

    return results


# ============================================================
# Plotting
# ============================================================
def generate_plots(corner="tt", temp=27, vdd=1.8):
    """Generate all verification plots."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print("  matplotlib not available, skipping plots")
        return

    os.makedirs(os.path.join(PROJECT_DIR, PLOTS_DIR), exist_ok=True)

    # Plot 1: Integration ramp
    _plot_integration_ramp(plt, corner, temp, vdd)

    # Plot 2: Reset + charge injection
    _plot_reset_waveform(plt, corner, temp, vdd)

    # Plot 3: Leakage drift
    _plot_leakage(plt, corner, temp, vdd)

    # Plot 4: AC response
    _plot_ac_response(plt, corner, temp, vdd)


def _run_and_read_data(netlist: str, datafile: str) -> Optional[np.ndarray]:
    """Run netlist and read the wrdata output file."""
    run_ngspice(netlist)
    fp = os.path.join(PROJECT_DIR, datafile)
    if os.path.exists(fp):
        try:
            data = np.loadtxt(fp, skiprows=1)
            os.unlink(fp)
            return data
        except Exception:
            os.unlink(fp)
    return None


def _plot_integration_ramp(plt, corner, temp, vdd):
    netlist = f"""Integration Ramp Plot
{make_lib_include(corner)}
{make_design_include()}

.param vdd_val={vdd}
.param vcm_val={{vdd_val/2}}
Vdd vdd 0 {{vdd_val}}
Vss vss 0 0
Vcm vcm 0 {{vcm_val}}
Vbias vbias_n 0 0.6
Vrst reset 0 PWL(0 {{vdd_val}} 95n {{vdd_val}} 100n 0)
XI inp inn outp outn reset vbias_n vcm vdd vss integrator
Icharge_p vcm inp DC 10u
Icharge_n inn vcm DC 10u
.control
set filetype=ascii
option temp={temp}
tran 1n 3u
wrdata plot_integration.txt V(outp) V(outn)
.endc
.end
"""
    data = _run_and_read_data(netlist, "plot_integration.txt")
    if data is not None and data.ndim == 2:
        t = data[:, 0] * 1e6  # µs
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(t, data[:, 1], 'b-', label='V(outp)', linewidth=1.5)
        if data.shape[1] >= 4:
            ax.plot(t, data[:, 3], 'r-', label='V(outn)', linewidth=1.5)
        ax.axhline(y=vdd/2, color='gray', linestyle='--', alpha=0.5, label='VCM')
        ax.set_xlabel('Time (µs)')
        ax.set_ylabel('Voltage (V)')
        ax.set_title(f'Integration Ramp (10µA input, {corner} corner, {temp}°C)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PROJECT_DIR, PLOTS_DIR, 'integration_ramp.png'), dpi=150)
        plt.close()
        print("  Saved plots/integration_ramp.png")


def _plot_reset_waveform(plt, corner, temp, vdd):
    vcm = vdd / 2
    netlist = f"""Reset Waveform Plot
{make_lib_include(corner)}
{make_design_include()}

.param vdd_val={vdd}
.param vcm_val={{vdd_val/2}}
Vdd vdd 0 {{vdd_val}}
Vss vss 0 0
Vcm vcm 0 {{vcm_val}}
Vbias vbias_n 0 0.6
Vrst reset 0 PWL(0 0 9n 0 10n {{vdd_val}} 199n {{vdd_val}} 200n 0)
XI inp inn outp outn reset vbias_n vcm vdd vss integrator
.ic V(outp)={vcm+0.2} V(outn)={vcm-0.2}
Rp inp vcm 100G
Rn inn vcm 100G
.control
set filetype=ascii
option temp={temp}
tran 0.1n 500n UIC
wrdata plot_reset.txt V(outp) V(outn) V(reset)
.endc
.end
"""
    data = _run_and_read_data(netlist, "plot_reset.txt")
    if data is not None and data.ndim == 2:
        t = data[:, 0] * 1e9  # ns
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 8), sharex=True)
        ax1.plot(t, data[:, 1], 'b-', label='V(outp)', linewidth=1.5)
        if data.shape[1] >= 4:
            ax1.plot(t, data[:, 3], 'r-', label='V(outn)', linewidth=1.5)
        ax1.axhline(y=vdd/2, color='gray', linestyle='--', alpha=0.5, label='VCM')
        ax1.set_ylabel('Voltage (V)')
        ax1.set_title(f'Reset & Charge Injection ({corner}, {temp}°C)')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        if data.shape[1] >= 6:
            ax2.plot(t, data[:, 5], 'g-', label='Reset', linewidth=1.5)
        ax2.set_xlabel('Time (ns)')
        ax2.set_ylabel('Reset (V)')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PROJECT_DIR, PLOTS_DIR, 'reset_waveform.png'), dpi=150)
        plt.close()
        print("  Saved plots/reset_waveform.png")


def _plot_leakage(plt, corner, temp, vdd):
    netlist = f"""Leakage Plot
{make_lib_include(corner)}
{make_design_include()}

.param vdd_val={vdd}
.param vcm_val={{vdd_val/2}}
Vdd vdd 0 {{vdd_val}}
Vss vss 0 0
Vcm vcm 0 {{vcm_val}}
Vbias vbias_n 0 0.6
Vrst reset 0 PWL(0 {{vdd_val}} 95n {{vdd_val}} 100n 0)
XI inp inn outp outn reset vbias_n vcm vdd vss integrator
Rp inp vcm 100G
Rn inn vcm 100G
.control
set filetype=ascii
option temp={temp}
tran 10n 60u
wrdata plot_leakage.txt V(outp) V(outn)
.endc
.end
"""
    data = _run_and_read_data(netlist, "plot_leakage.txt")
    if data is not None and data.ndim == 2:
        t = data[:, 0] * 1e6  # µs
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(t, data[:, 1] * 1000, 'b-', label='V(outp) (mV)', linewidth=1.5)
        if data.shape[1] >= 4:
            ax.plot(t, data[:, 3] * 1000, 'r-', label='V(outn) (mV)', linewidth=1.5)
        ax.axhline(y=vdd/2*1000, color='gray', linestyle='--', alpha=0.5, label='VCM')
        ax.set_xlabel('Time (µs)')
        ax.set_ylabel('Voltage (mV)')
        ax.set_title(f'Leakage Drift ({corner}, {temp}°C)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PROJECT_DIR, PLOTS_DIR, 'leakage_drift.png'), dpi=150)
        plt.close()
        print("  Saved plots/leakage_drift.png")


def _plot_ac_response(plt, corner, temp, vdd):
    netlist = f"""AC Response Plot
{make_lib_include(corner)}
{make_design_include()}

.param vdd_val={vdd}
.param vcm_val={{vdd_val/2}}
Vdd vdd 0 {{vdd_val}}
Vss vss 0 0
Vcm vcm 0 {{vcm_val}}
Vbias vbias_n 0 0.6
Vrst reset 0 0
XI inp inn outp outn reset vbias_n vcm vdd vss integrator
Rbp outp vcm 100G
Rbn outn vcm 100G
Iac_p inp vcm DC 0 AC 1
Iac_n vcm inn DC 0 AC 1
.control
set filetype=ascii
option temp={temp}
ac dec 100 0.1 100Meg
wrdata plot_ac.txt vdb(outp,outn) vm(outp,outn)
.endc
.end
"""
    data = _run_and_read_data(netlist, "plot_ac.txt")
    if data is not None and data.ndim == 2:
        freqs = data[:, 0]
        mag_db = data[:, 1]
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.semilogx(freqs, mag_db, 'b-', linewidth=1.5)
        ax.axhline(y=0, color='r', linestyle='--', alpha=0.5, label='0 dB')
        ax.set_xlabel('Frequency (Hz)')
        ax.set_ylabel('Transimpedance (dB)')
        ax.set_title(f'AC Response - Transimpedance ({corner}, {temp}°C)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PROJECT_DIR, PLOTS_DIR, 'ac_response.png'), dpi=150)
        plt.close()
        print("  Saved plots/ac_response.png")


# ============================================================
# Scoring
# ============================================================
def compute_score(measurements: Dict, specs: Dict) -> Tuple[float, Dict]:
    spec_defs = specs.get("measurements", {})
    total_weight = 0
    weighted_score = 0
    details = {}

    for name, spec in spec_defs.items():
        target = spec["target"]
        weight = spec.get("weight", 1)
        total_weight += weight
        measured = measurements.get(name, None)

        if measured is None:
            details[name] = {"target": target, "measured": None, "pass": False}
            continue

        passed = False
        if target.startswith(">"):
            passed = measured > float(target[1:])
        elif target.startswith("<"):
            passed = measured < float(target[1:])
        elif target.startswith("="):
            passed = abs(measured - float(target[1:])) < 0.01

        details[name] = {"target": target, "measured": measured, "pass": passed}
        if passed:
            weighted_score += weight

    score = weighted_score / total_weight if total_weight > 0 else 0
    return score, details


# ============================================================
# Main validation
# ============================================================
def validate(quick: bool = False):
    print("=" * 60)
    print("  Gm-C Integrator Validation")
    print("=" * 60)

    specs = load_specs()
    measurements = {}

    # Run all tests
    print("\n--- Test 1: AC (DC gain + UGF) ---")
    ac_results = measure_ac()
    measurements.update(ac_results)
    print(f"  DC gain: {ac_results.get('dc_gain_db', 'N/A'):.1f} dB")
    print(f"  UGF: {ac_results.get('unity_gain_freq_mhz', 'N/A'):.3f} MHz")

    print("\n--- Test 2: Output Swing ---")
    swing_results = measure_swing()
    measurements.update(swing_results)
    print(f"  Swing: {swing_results.get('output_swing_mv', 'N/A'):.1f} mV")

    print("\n--- Test 3: Leakage ---")
    leak_results = measure_leakage()
    measurements.update(leak_results)
    print(f"  Leakage: {leak_results.get('leakage_mv_per_us', 'N/A'):.4f} mV/µs")

    print("\n--- Test 4: Reset + Charge Injection ---")
    reset_results = measure_reset()
    measurements.update(reset_results)
    print(f"  Reset time: {reset_results.get('reset_time_ns', 'N/A'):.2f} ns")
    print(f"  Charge injection: {reset_results.get('charge_inject_mv', 'N/A'):.2f} mV")

    print("\n--- Test 5: Power ---")
    power_results = measure_power()
    measurements.update(power_results)
    print(f"  Power: {power_results.get('power_uw', 'N/A'):.3f} µW")

    print("\n--- Test 6: Integration Linearity ---")
    int_results = measure_integration()
    measurements.update(int_results)
    print(f"  Cap estimate: {int_results.get('c_int_pf', 'N/A'):.2f} pF")
    print(f"  Ramp rate: {int_results.get('_ramp_rate_v_per_us', 'N/A'):.4f} V/µs")

    # Generate plots
    if not quick:
        print("\n--- Generating Plots ---")
        generate_plots()

    # Score
    # Filter out internal measurements (prefixed with _)
    public_meas = {k: v for k, v in measurements.items() if not k.startswith('_') and v is not None}

    score, details = compute_score(public_meas, specs)
    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    specs_passed = 0
    specs_total = 0
    for name, d in details.items():
        status = "PASS" if d["pass"] else "FAIL"
        measured = f"{d['measured']:.4f}" if d['measured'] is not None else "N/A"
        print(f"  {name}: {measured} (target: {d['target']}) [{status}]")
        specs_total += 1
        if d["pass"]:
            specs_passed += 1
    print(f"\n  SCORE: {score:.3f} ({specs_passed}/{specs_total} specs passing)")

    # Save measurements
    public_meas["score"] = score
    public_meas["specs_passed"] = specs_passed
    public_meas["specs_total"] = specs_total
    with open(os.path.join(PROJECT_DIR, "measurements.json"), "w") as f:
        json.dump(public_meas, f, indent=2)
    print(f"\nSaved measurements.json")

    return score, details, public_meas


def main():
    parser = argparse.ArgumentParser(description="Gm-C Integrator Evaluator")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    os.makedirs(os.path.join(PROJECT_DIR, PLOTS_DIR), exist_ok=True)
    validate(quick=args.quick)


if __name__ == "__main__":
    main()
