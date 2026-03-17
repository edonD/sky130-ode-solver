"""
evaluate.py — Comprehensive simulation and validation for Programmable OTA (Gm Cell).

Measures: Gm, Gm_ratio, THD, bandwidth, DC gain, power
Uses ngspice with SKY130 PDK.
"""

import os
import sys
import re
import json
import csv
import time
import argparse
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NGSPICE = os.environ.get("NGSPICE", "ngspice")
DESIGN_FILE = "design.cir"
PARAMS_FILE = "parameters.csv"
SPECS_FILE = "specs.json"
PLOTS_DIR = "plots"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

NOMINAL_CORNER = "tt"
NOMINAL_TEMP = 24
NOMINAL_SUPPLY = 1.8

# ---------------------------------------------------------------------------
# Parameter / spec loading
# ---------------------------------------------------------------------------

def load_parameters(path: str = PARAMS_FILE) -> List[Dict]:
    filepath = os.path.join(PROJECT_DIR, path) if not os.path.isabs(path) else path
    params = []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            params.append({
                "name": row["name"].strip(),
                "min": float(row["min"]),
                "max": float(row["max"]),
                "scale": row.get("scale", "lin").strip(),
            })
    return params


def load_best_parameters(path: str = "best_parameters.csv") -> Dict[str, float]:
    filepath = os.path.join(PROJECT_DIR, path) if not os.path.isabs(path) else path
    params = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            params[row["name"].strip()] = float(row["value"])
    return params


def load_specs(path: str = SPECS_FILE) -> Dict:
    filepath = os.path.join(PROJECT_DIR, path) if not os.path.isabs(path) else path
    with open(filepath) as f:
        return json.load(f)


def load_design(path: str = DESIGN_FILE) -> str:
    filepath = os.path.join(PROJECT_DIR, path) if not os.path.isabs(path) else path
    with open(filepath) as f:
        return f.read()


# ---------------------------------------------------------------------------
# SPICE simulation
# ---------------------------------------------------------------------------

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
        except:
            pass


def parse_wrdata(filepath: str) -> Optional[np.ndarray]:
    """Parse ngspice wrdata output file."""
    full = os.path.join(PROJECT_DIR, filepath)
    if not os.path.exists(full):
        return None
    try:
        data = np.loadtxt(full)
        return data
    except Exception as e:
        print(f"  Warning: parse error {filepath}: {e}")
        return None
    finally:
        try:
            os.unlink(full)
        except:
            pass


# ---------------------------------------------------------------------------
# Testbench builders
# ---------------------------------------------------------------------------

def build_gm_testbench(params: Dict[str, float], corner="tt", temp=24, vdd=1.8,
                        vbias_n=0.6, sweep_range=0.35, step=0.001) -> str:
    """DC sweep for Gm and linearity measurement."""
    design = load_design()
    param_lines = "\n".join(f".param {k}={v}" for k, v in params.items())
    vcm = vdd / 2

    return f"""* OTA Gm Measurement - DC Sweep
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}

{param_lines}

{design}

Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell

Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbias_n}
Vbias_p vbias_p 0 {vdd - 0.6}

* Differential input sweep: both move symmetrically around VCM
Vinp inp 0 {vcm}
Vinn inn 0 {vcm}

* Sweep Vinp, with Vinn fixed at VCM
* Differential input = V(inp) - V(inn) = Vinp - VCM
.dc Vinp {vcm - sweep_range} {vcm + sweep_range} {step}

.control
run
wrdata gm_dc_sweep.dat v(outp) v(outn) i(Vdd)
.endc
.end
"""


def build_thd_testbench(params: Dict[str, float], corner="tt", temp=24, vdd=1.8,
                         vbias_n=0.6, amp_mv=200, freq=100e3) -> str:
    """Transient simulation for THD measurement."""
    design = load_design()
    param_lines = "\n".join(f".param {k}={v}" for k, v in params.items())
    vcm = vdd / 2
    amp = amp_mv / 1000.0
    period = 1.0 / freq
    # Run for 20 periods, sample last 10
    tstop = 20 * period
    tstep = period / 200  # 200 points per period

    return f"""* OTA THD Measurement - Transient
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}

{param_lines}

{design}

Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell

Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbias_n}
Vbias_p vbias_p 0 {vdd - 0.6}

* Differential sinusoidal input: ±{amp_mv}mV
Vinp inp 0 dc {vcm} sin({vcm} {amp/2} {freq})
Vinn inn 0 dc {vcm} sin({vcm} {-amp/2} {freq})

* Load capacitor (integrator-like)
Cload outp outn 2p

.tran {tstep} {tstop} {tstop/2} {tstep}

.control
run
wrdata thd_tran.dat v(outp) v(outn)
.endc
.end
"""


def build_ac_testbench(params: Dict[str, float], corner="tt", temp=24, vdd=1.8,
                        vbias_n=0.6) -> str:
    """AC analysis for bandwidth and DC gain."""
    design = load_design()
    param_lines = "\n".join(f".param {k}={v}" for k, v in params.items())
    vcm = vdd / 2

    return f"""* OTA AC Analysis
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}

{param_lines}

{design}

Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell

Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbias_n}
Vbias_p vbias_p 0 {vdd - 0.6}

* Small-signal AC input (differential)
Vinp inp 0 dc {vcm} ac 0.5
Vinn inn 0 dc {vcm} ac -0.5

* Load capacitor
Cload outp outn 2p

.ac dec 50 1k 10g

.control
run
let vout_diff = v(outp) - v(outn)
let gain_db = db(vout_diff)
let phase = ph(vout_diff) * 180 / 3.14159265
wrdata ac_response.dat gain_db phase
.endc
.end
"""


def build_power_testbench(params: Dict[str, float], corner="tt", temp=24, vdd=1.8,
                           vbias_n=0.6) -> str:
    """DC operating point for power measurement."""
    design = load_design()
    param_lines = "\n".join(f".param {k}={v}" for k, v in params.items())
    vcm = vdd / 2

    return f"""* OTA Power Measurement
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}

{param_lines}

{design}

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
print v(outp) v(outn)
.endc
.end
"""


# ---------------------------------------------------------------------------
# Measurement functions
# ---------------------------------------------------------------------------

def measure_gm_and_linearity(params: Dict[str, float], corner="tt", temp=24,
                              vdd=1.8, vbias_n=0.6) -> Dict:
    """Measure Gm and THD from DC sweep + transient."""
    results = {"gm_us": 0, "thd_pct": 100}
    vcm = vdd / 2

    # --- Gm from DC sweep ---
    tb = build_gm_testbench(params, corner, temp, vdd, vbias_n)
    output = run_ngspice(tb)

    data = parse_wrdata("gm_dc_sweep.dat")
    if data is not None and data.ndim == 2 and data.shape[1] >= 3:
        vin = data[:, 0]  # Vinp sweep value
        voutp = data[:, 1]
        voutn = data[:, 2]
        vout_diff = voutp - voutn
        vdiff_in = vin - vcm  # differential input

        # Compute Gm = d(Vout_diff)/d(Vdiff_in) — this is voltage gain, not Gm
        # For OTA: Gm = Iout_diff / Vdiff_in, but we measure voltage gain here
        # Since output has high impedance + PMOS load, the voltage gain = Gm * Rout
        # We'll extract Gm separately. For now, compute the voltage gain slope
        dv = np.gradient(vout_diff, vdiff_in)

        # Gm at center (operating point)
        mid = len(dv) // 2
        region = slice(max(0, mid-10), min(len(dv), mid+10))
        gain_center = np.mean(dv[region])

        # For linearity: fit line in ±200mV region, compute deviation
        mask200 = (np.abs(vdiff_in) <= 0.2)
        if np.sum(mask200) > 10:
            vin_lin = vdiff_in[mask200]
            vout_lin = vout_diff[mask200]
            coeffs = np.polyfit(vin_lin, vout_lin, 1)
            ideal = np.polyval(coeffs, vin_lin)
            error = vout_lin - ideal
            rms_error = np.sqrt(np.mean(error**2))
            signal_rms = np.sqrt(np.mean(vout_lin**2))
            if signal_rms > 1e-12:
                thd_approx = rms_error / signal_rms * 100
                results["thd_pct"] = thd_approx

        # Store waveform data for plotting
        results["_dc_vin"] = vdiff_in
        results["_dc_vout"] = vout_diff
        results["_dc_gain"] = dv
        results["_voltage_gain"] = abs(gain_center)
    else:
        if "ERROR" in output or "error" in output.lower():
            print(f"  DC sweep error: {output[-200:]}")

    # --- THD from transient simulation ---
    tb = build_thd_testbench(params, corner, temp, vdd, vbias_n)
    output = run_ngspice(tb)

    data = parse_wrdata("thd_tran.dat")
    if data is not None and data.ndim == 2 and data.shape[1] >= 2:
        t = data[:, 0]
        # Handle ngspice wrdata format: might have extra columns
        if data.shape[1] >= 3:
            voutp = data[:, 1]
            voutn = data[:, 2]
            vout_diff = voutp - voutn
        else:
            vout_diff = data[:, 1]

        # Compute THD using FFT on last portion of signal
        N = len(vout_diff)
        if N > 100:
            # Remove DC
            vout_ac = vout_diff - np.mean(vout_diff)
            # Window
            window = np.hanning(N)
            vout_w = vout_ac * window

            fft = np.fft.rfft(vout_w)
            mag = np.abs(fft)

            # Find fundamental
            fund_idx = np.argmax(mag[1:]) + 1
            if fund_idx > 0:
                fund_mag = mag[fund_idx]
                # Sum harmonics (2nd through 10th)
                harmonic_power = 0
                for h in range(2, 11):
                    hidx = h * fund_idx
                    if hidx < len(mag):
                        harmonic_power += mag[hidx]**2
                if fund_mag > 1e-15:
                    thd = np.sqrt(harmonic_power) / fund_mag * 100
                    results["thd_pct"] = min(results["thd_pct"], thd)

        results["_tran_t"] = t
        results["_tran_vout"] = vout_diff

    return results


def measure_ac(params: Dict[str, float], corner="tt", temp=24,
               vdd=1.8, vbias_n=0.6) -> Dict:
    """Measure bandwidth and DC gain from AC analysis."""
    results = {"bw_mhz": 0, "dc_gain_db": 0}

    tb = build_ac_testbench(params, corner, temp, vdd, vbias_n)
    output = run_ngspice(tb)

    data = parse_wrdata("ac_response.dat")
    if data is not None and data.ndim == 2 and data.shape[1] >= 2:
        freq = data[:, 0]
        gain_db = data[:, 1]

        if len(freq) > 5 and not np.all(np.isnan(gain_db)):
            # DC gain: gain at lowest frequency
            valid = ~np.isnan(gain_db) & ~np.isinf(gain_db)
            if np.any(valid):
                gain_valid = gain_db[valid]
                freq_valid = freq[valid]
                dc_gain = gain_valid[0]
                results["dc_gain_db"] = dc_gain

                # -3dB bandwidth
                target = dc_gain - 3
                above = gain_valid >= target
                if not np.all(above) and np.any(above):
                    # Find crossing
                    crossings = np.where(np.diff(above.astype(int)) == -1)[0]
                    if len(crossings) > 0:
                        idx = crossings[0]
                        # Linear interpolation
                        if idx + 1 < len(freq_valid):
                            f1, f2 = freq_valid[idx], freq_valid[idx+1]
                            g1, g2 = gain_valid[idx], gain_valid[idx+1]
                            if abs(g2 - g1) > 1e-10:
                                f3db = f1 + (target - g1) * (f2 - f1) / (g2 - g1)
                            else:
                                f3db = f1
                            results["bw_mhz"] = f3db / 1e6

                results["_ac_freq"] = freq_valid
                results["_ac_gain"] = gain_valid
    else:
        if "ERROR" in output or "error" in output.lower():
            print(f"  AC error: {output[-200:]}")

    return results


def measure_power(params: Dict[str, float], corner="tt", temp=24,
                  vdd=1.8, vbias_n=0.6) -> Dict:
    """Measure DC power consumption."""
    results = {"power_uw": 999}

    tb = build_power_testbench(params, corner, temp, vdd, vbias_n)
    output = run_ngspice(tb)

    # Parse printed current from ngspice output
    for line in output.split('\n'):
        if 'i(vdd)' in line.lower() or 'i(v' in line.lower():
            # Look for numeric value
            match = re.search(r'[-+]?[0-9]*\.?[0-9]+[eE][-+]?[0-9]+', line)
            if match:
                current = abs(float(match.group()))
                power_w = current * vdd
                results["power_uw"] = power_w * 1e6
                break

    return results


def measure_gm_ratio(params: Dict[str, float], corner="tt", temp=24, vdd=1.8) -> Dict:
    """Measure Gm at different bias points to get programmability ratio."""
    results = {"gm_ratio": 1, "gm_us": 0, "gm_max_us": 0, "gm_min_us": 0}

    # Sweep vbias_n to find Gm range
    # vbias_n controls tail current: higher = more current = higher Gm
    vbias_values = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80, 0.90, 1.0]
    gm_values = []

    vcm = vdd / 2

    for vbn in vbias_values:
        tb = build_gm_testbench(params, corner, temp, vdd, vbn, sweep_range=0.01, step=0.0002)
        output = run_ngspice(tb)

        data = parse_wrdata("gm_dc_sweep.dat")
        if data is not None and data.ndim == 2 and data.shape[1] >= 3:
            vin = data[:, 0]
            voutp = data[:, 1]
            voutn = data[:, 2]
            vout_diff = voutp - voutn
            vdiff_in = vin - vcm

            # Compute voltage gain at center
            dv = np.gradient(vout_diff, vdiff_in)
            mid = len(dv) // 2
            region = slice(max(0, mid-3), min(len(dv), mid+3))
            gain = abs(np.mean(dv[region]))
            gm_values.append(gain)
        else:
            gm_values.append(0)

    gm_arr = np.array(gm_values)
    valid = gm_arr > 0.01  # filter out failed measurements

    if np.any(valid):
        gm_max = np.max(gm_arr[valid])
        gm_min = np.min(gm_arr[valid])
        # Nominal is at vbias_n=0.6 (index 3)
        gm_nom = gm_arr[3] if gm_arr[3] > 0 else gm_max

        if gm_min > 1e-6:
            results["gm_ratio"] = gm_max / gm_min
        results["gm_max_us"] = gm_max  # Note: this is voltage gain, need conversion
        results["gm_min_us"] = gm_min
        results["_gm_vs_vbias"] = (vbias_values, gm_arr.tolist())

    return results


# ---------------------------------------------------------------------------
# Full measurement suite
# ---------------------------------------------------------------------------

def measure_all(params: Dict[str, float], corner="tt", temp=24, vdd=1.8,
                vbias_n=0.6, measure_ratio=True) -> Dict:
    """Run all measurements and return combined results."""
    print(f"  Corner: {corner}, T={temp}C, VDD={vdd}V, Vbias_n={vbias_n}V")

    # Gm + linearity
    gm_res = measure_gm_and_linearity(params, corner, temp, vdd, vbias_n)

    # AC response
    ac_res = measure_ac(params, corner, temp, vdd, vbias_n)

    # Power
    pwr_res = measure_power(params, corner, temp, vdd, vbias_n)

    # Combine
    meas = {}
    meas.update(gm_res)
    meas.update(ac_res)
    meas.update(pwr_res)

    # Gm ratio (only at nominal)
    if measure_ratio and corner == "tt" and temp == 24:
        ratio_res = measure_gm_ratio(params, corner, temp, vdd)
        meas.update(ratio_res)

    # The DC sweep gives us voltage gain. We need actual Gm.
    # Gm = Iout / Vin. With high-impedance output, V_gain = Gm * Rout
    # We'll report the voltage gain as a proxy and also try to extract Gm
    # from the output current directly if available.
    # For now, the "gm_us" spec is about Gm in µS.
    # We need to measure actual transconductance: Iout/Vin

    return meas


def measure_gm_current(params: Dict[str, float], corner="tt", temp=24,
                        vdd=1.8, vbias_n=0.6) -> Dict:
    """Measure actual Gm (transconductance) by measuring output current."""
    design = load_design()
    param_lines = "\n".join(f".param {k}={v}" for k, v in params.items())
    vcm = vdd / 2

    # Use a voltage source at output to measure current (force Vout = VCM)
    tb = f"""* OTA Gm Measurement - Current Output
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}

{param_lines}

{design}

Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell

Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbias_n}
Vbias_p vbias_p 0 {vdd - 0.6}

* Force output to VCM to measure short-circuit current
Voutp outp 0 {vcm}
Voutn outn 0 {vcm}

Vinp inp 0 {vcm}
Vinn inn 0 {vcm}

.dc Vinp {vcm - 0.35} {vcm + 0.35} 0.001

.control
run
wrdata gm_current.dat i(Voutp) i(Voutn)
.endc
.end
"""
    output = run_ngspice(tb)
    results = {"gm_us": 0}

    data = parse_wrdata("gm_current.dat")
    if data is not None and data.ndim == 2 and data.shape[1] >= 3:
        vin = data[:, 0]
        ioutp = data[:, 1]
        ioutn = data[:, 2]
        iout_diff = ioutp - ioutn
        vdiff_in = vin - vcm

        # Gm = d(Iout_diff) / d(Vin_diff)
        gm = np.gradient(iout_diff, vdiff_in)
        mid = len(gm) // 2
        region = slice(max(0, mid-10), min(len(gm), mid+10))
        gm_center = abs(np.mean(gm[region]))
        results["gm_us"] = gm_center * 1e6

        results["_gm_vin"] = vdiff_in
        results["_gm_iout"] = iout_diff
        results["_gm_curve"] = gm * 1e6  # in µS

    return results


def measure_gm_ratio_current(params: Dict[str, float], corner="tt", temp=24, vdd=1.8) -> Dict:
    """Measure Gm ratio using actual current measurements."""
    design = load_design()
    vcm = vdd / 2
    param_lines = "\n".join(f".param {k}={v}" for k, v in params.items())

    vbias_values = [0.42, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80, 0.90, 1.0, 1.1, 1.2]
    gm_values = []

    for vbn in vbias_values:
        tb = f"""* OTA Gm Ratio - Vbias_n={vbn}V
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}

{param_lines}

{design}

Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell

Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 {vbn}
Vbias_p vbias_p 0 {vdd - 0.6}

Voutp outp 0 {vcm}
Voutn outn 0 {vcm}
Vinp inp 0 {vcm}
Vinn inn 0 {vcm}

.dc Vinp {vcm - 0.01} {vcm + 0.01} 0.0005

.control
run
wrdata gm_ratio_sweep.dat i(Voutp) i(Voutn)
.endc
.end
"""
        output = run_ngspice(tb)
        data = parse_wrdata("gm_ratio_sweep.dat")
        if data is not None and data.ndim == 2 and data.shape[1] >= 3:
            vin = data[:, 0]
            ioutp = data[:, 1]
            ioutn = data[:, 2]
            iout_diff = ioutp - ioutn
            vdiff_in = vin - vcm
            gm = np.gradient(iout_diff, vdiff_in)
            mid = len(gm) // 2
            gm_center = abs(np.mean(gm[max(0,mid-3):min(len(gm),mid+3)]))
            gm_values.append(gm_center * 1e6)  # µS
        else:
            gm_values.append(0)

    results = {"gm_ratio": 1, "gm_max_us": 0, "gm_min_us": 0}
    gm_arr = np.array(gm_values)
    valid = gm_arr > 0.1

    if np.any(valid):
        gm_max = np.max(gm_arr[valid])
        gm_min = np.min(gm_arr[valid])
        if gm_min > 0.001:
            results["gm_ratio"] = gm_max / gm_min
        results["gm_max_us"] = gm_max
        results["gm_min_us"] = gm_min
        results["_gm_ratio_vbias"] = vbias_values
        results["_gm_ratio_values"] = gm_arr.tolist()

    return results


# ---------------------------------------------------------------------------
# Complete measurement suite
# ---------------------------------------------------------------------------

def full_measure(params: Dict[str, float], corner="tt", temp=24, vdd=1.8,
                 vbias_n=0.6) -> Dict:
    """Complete measurement of all specs."""
    meas = {}

    # 1. Gm (transconductance in µS) from current measurement
    print("  Measuring Gm (current)...")
    gm_res = measure_gm_current(params, corner, temp, vdd, vbias_n)
    meas.update(gm_res)

    # 2. THD from transient + DC linearity
    print("  Measuring linearity/THD...")
    lin_res = measure_gm_and_linearity(params, corner, temp, vdd, vbias_n)
    meas["thd_pct"] = lin_res.get("thd_pct", 100)
    # Copy waveform data
    for k in lin_res:
        if k.startswith("_"):
            meas[k] = lin_res[k]

    # 3. AC response (BW, DC gain)
    print("  Measuring AC response...")
    ac_res = measure_ac(params, corner, temp, vdd, vbias_n)
    meas.update(ac_res)

    # 4. Power
    print("  Measuring power...")
    pwr_res = measure_power(params, corner, temp, vdd, vbias_n)
    meas.update(pwr_res)

    # 5. Gm ratio (only at nominal corner)
    if corner == "tt" and temp == 24 and abs(vdd - 1.8) < 0.01:
        print("  Measuring Gm ratio...")
        ratio_res = measure_gm_ratio_current(params, corner, temp, vdd)
        meas.update(ratio_res)

    return meas


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def compute_score(measurements: Dict, specs: Dict = None) -> Tuple[float, Dict]:
    if specs is None:
        specs = load_specs()
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
            details[name] = {"target": target, "measured": None, "pass": False, "margin": "N/A"}
            continue

        passed = False
        margin = 0
        if target.startswith(">"):
            threshold = float(target[1:])
            passed = measured > threshold
            margin = (measured - threshold) / threshold * 100 if threshold != 0 else 0
        elif target.startswith("<"):
            threshold = float(target[1:])
            passed = measured < threshold
            margin = (threshold - measured) / threshold * 100 if threshold != 0 else 0

        details[name] = {
            "target": target,
            "measured": round(measured, 4),
            "pass": passed,
            "margin": f"{margin:+.1f}%"
        }
        if passed:
            weighted_score += weight

    score = weighted_score / total_weight if total_weight > 0 else 0
    return score, details


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def generate_plots(meas: Dict, params: Dict[str, float]):
    """Generate all diagnostic plots."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print("  matplotlib not available, skipping plots")
        return

    os.makedirs(os.path.join(PROJECT_DIR, PLOTS_DIR), exist_ok=True)

    # 1. Gm vs Vin (DC transfer)
    if "_dc_vin" in meas and "_dc_vout" in meas:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

        ax1.plot(meas["_dc_vin"] * 1000, meas["_dc_vout"] * 1000, 'b-', linewidth=2)
        ax1.set_xlabel("Differential Input (mV)")
        ax1.set_ylabel("Differential Output (mV)")
        ax1.set_title("OTA DC Transfer Characteristic")
        ax1.grid(True, alpha=0.3)
        ax1.axhline(y=0, color='k', linewidth=0.5)
        ax1.axvline(x=0, color='k', linewidth=0.5)

        if "_dc_gain" in meas:
            ax2.plot(meas["_dc_vin"] * 1000, meas["_dc_gain"], 'r-', linewidth=2)
            ax2.set_xlabel("Differential Input (mV)")
            ax2.set_ylabel("Voltage Gain (V/V)")
            ax2.set_title("Small-Signal Voltage Gain vs Input")
            ax2.grid(True, alpha=0.3)
            ax2.axhline(y=0, color='k', linewidth=0.5)

        plt.tight_layout()
        plt.savefig(os.path.join(PROJECT_DIR, PLOTS_DIR, "dc_transfer.png"), dpi=150)
        plt.close()
        print("  Saved plots/dc_transfer.png")

    # 2. Gm (transconductance) vs Vin
    if "_gm_vin" in meas and "_gm_curve" in meas:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

        ax1.plot(meas["_gm_vin"] * 1000, meas["_gm_iout"] * 1e6, 'b-', linewidth=2)
        ax1.set_xlabel("Differential Input (mV)")
        ax1.set_ylabel("Differential Output Current (µA)")
        ax1.set_title("OTA Transconductance: Iout vs Vin")
        ax1.grid(True, alpha=0.3)
        ax1.axhline(y=0, color='k', linewidth=0.5)

        ax2.plot(meas["_gm_vin"] * 1000, meas["_gm_curve"], 'r-', linewidth=2)
        ax2.set_xlabel("Differential Input (mV)")
        ax2.set_ylabel("Gm (µS)")
        ax2.set_title(f"Transconductance vs Input (Gm_nom = {meas.get('gm_us', 0):.1f} µS)")
        ax2.grid(True, alpha=0.3)
        ax2.axhline(y=meas.get("gm_us", 0), color='g', linestyle='--', alpha=0.5, label=f'Gm={meas.get("gm_us",0):.1f} µS')
        ax2.legend()

        plt.tight_layout()
        plt.savefig(os.path.join(PROJECT_DIR, PLOTS_DIR, "gm_vs_vin.png"), dpi=150)
        plt.close()
        print("  Saved plots/gm_vs_vin.png")

    # 3. AC response
    if "_ac_freq" in meas and "_ac_gain" in meas:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.semilogx(meas["_ac_freq"], meas["_ac_gain"], 'b-', linewidth=2)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Gain (dB)")
        ax.set_title(f"OTA AC Response (DC Gain={meas.get('dc_gain_db',0):.1f} dB, BW={meas.get('bw_mhz',0):.1f} MHz)")
        ax.grid(True, alpha=0.3, which='both')
        if meas.get("dc_gain_db", 0) > 0:
            ax.axhline(y=meas["dc_gain_db"] - 3, color='r', linestyle='--', alpha=0.5, label='-3dB')
        if meas.get("bw_mhz", 0) > 0:
            ax.axvline(x=meas["bw_mhz"] * 1e6, color='g', linestyle='--', alpha=0.5, label=f'BW={meas["bw_mhz"]:.1f} MHz')
        ax.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(PROJECT_DIR, PLOTS_DIR, "ac_response.png"), dpi=150)
        plt.close()
        print("  Saved plots/ac_response.png")

    # 4. Gm ratio vs bias
    if "_gm_ratio_vbias" in meas and "_gm_ratio_values" in meas:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(meas["_gm_ratio_vbias"], meas["_gm_ratio_values"], 'bo-', linewidth=2, markersize=8)
        ax.set_xlabel("Vbias_n (V)")
        ax.set_ylabel("Gm (µS)")
        ax.set_title(f"Gm Programmability (Ratio = {meas.get('gm_ratio',0):.1f}x)")
        ax.grid(True, alpha=0.3)
        ax.set_yscale('log')
        plt.tight_layout()
        plt.savefig(os.path.join(PROJECT_DIR, PLOTS_DIR, "gm_ratio.png"), dpi=150)
        plt.close()
        print("  Saved plots/gm_ratio.png")

    # 5. THD transient waveform
    if "_tran_t" in meas and "_tran_vout" in meas:
        fig, ax = plt.subplots(figsize=(10, 5))
        t = meas["_tran_t"]
        v = meas["_tran_vout"]
        ax.plot(t * 1e6, v * 1000, 'b-', linewidth=1)
        ax.set_xlabel("Time (µs)")
        ax.set_ylabel("Differential Output (mV)")
        ax.set_title(f"OTA Transient Response (THD = {meas.get('thd_pct',0):.2f}%)")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PROJECT_DIR, PLOTS_DIR, "thd_transient.png"), dpi=150)
        plt.close()
        print("  Saved plots/thd_transient.png")


# ---------------------------------------------------------------------------
# Main validation entry point
# ---------------------------------------------------------------------------

def validate(quick: bool = False):
    """Run full validation of current best parameters."""
    print("=" * 60)
    print("  OTA (Gm Cell) Full Validation")
    print("=" * 60)

    specs = load_specs()

    try:
        params = load_best_parameters()
        print(f"\nLoaded parameters from best_parameters.csv")
        for k, v in params.items():
            print(f"  {k} = {v}")
    except FileNotFoundError:
        print("\nNo best_parameters.csv found. Using defaults.")
        params = {}

    print(f"\n--- Nominal Corner (tt, 24C, 1.8V) ---")
    meas = full_measure(params, corner="tt", temp=24, vdd=1.8, vbias_n=0.6)

    # Print results
    score, details = compute_score(meas, specs)
    n_pass = sum(1 for d in details.values() if d["pass"])
    n_total = len(details)

    print(f"\n{'='*60}")
    print(f"  RESULTS: {n_pass}/{n_total} specs passing, Score = {score:.3f}")
    print(f"{'='*60}")
    print(f"  {'Spec':<15} {'Target':<10} {'Measured':<12} {'Margin':<10} {'Status'}")
    print(f"  {'-'*55}")
    for name, d in details.items():
        status = "PASS" if d["pass"] else "FAIL"
        measured = f"{d['measured']:.4f}" if d['measured'] is not None else "N/A"
        print(f"  {name:<15} {d['target']:<10} {measured:<12} {d['margin']:<10} {status}")

    # Generate plots
    print("\n--- Generating Plots ---")
    generate_plots(meas, params)

    # Save measurements
    save_meas = {k: v for k, v in meas.items() if not k.startswith("_")}
    save_meas["score"] = score
    with open(os.path.join(PROJECT_DIR, "measurements.json"), "w") as f:
        json.dump(save_meas, f, indent=2)
    print(f"\nSaved measurements.json")

    return score, meas, details


def main():
    parser = argparse.ArgumentParser(description="OTA Gm Cell Evaluator")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    os.makedirs(os.path.join(PROJECT_DIR, PLOTS_DIR), exist_ok=True)
    validate(quick=args.quick)


if __name__ == "__main__":
    main()
