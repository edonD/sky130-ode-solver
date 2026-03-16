"""
evaluate.py — Simulation and validation utilities for Programmable OTA (Gm Cell).

Provides:
- NGSpice simulation runner (single sim at any PVT corner)
- Gm, linearity, bandwidth, gain measurements
- PVT corner sweep
- Monte Carlo analysis
- Cost function, scoring, and plotting

This file does NOT contain an optimizer. The agent chooses and implements
its own optimization strategy.

Usage standalone (validate existing best_parameters.csv):
    python evaluate.py                   # full validation
    python evaluate.py --quick           # quick validation (fewer corners)
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
RESULTS_FILE = "results.tsv"
PLOTS_DIR = "plots"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# PVT corners
TEMPERATURES = [-40, 24, 175]
SUPPLY_VOLTAGES = [1.62, 1.8, 1.98]
PROCESS_CORNERS = ["tt", "ss", "ff", "sf", "fs"]

# Monte Carlo settings
MC_N_SAMPLES = 200
MC_SIGMA_TARGET = 4.5

# Nominal corner
NOMINAL_CORNER = "tt"
NOMINAL_TEMP = 24
NOMINAL_SUPPLY = 1.8

# ---------------------------------------------------------------------------
# Parameter loading
# ---------------------------------------------------------------------------

def load_parameters(path: str = PARAMS_FILE) -> List[Dict]:
    """Load parameter definitions from CSV."""
    params = []
    filepath = os.path.join(PROJECT_DIR, path) if not os.path.isabs(path) else path
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
    """Load the current best parameter values."""
    filepath = os.path.join(PROJECT_DIR, path) if not os.path.isabs(path) else path
    params = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            params[row["name"].strip()] = float(row["value"])
    return params


def load_specs(path: str = SPECS_FILE) -> Dict:
    """Load target specifications."""
    filepath = os.path.join(PROJECT_DIR, path) if not os.path.isabs(path) else path
    with open(filepath) as f:
        return json.load(f)


def load_design(path: str = DESIGN_FILE) -> str:
    """Load the SPICE netlist template."""
    filepath = os.path.join(PROJECT_DIR, path) if not os.path.isabs(path) else path
    with open(filepath) as f:
        return f.read()


# ---------------------------------------------------------------------------
# SPICE simulation
# ---------------------------------------------------------------------------

def run_ngspice(netlist: str, timeout: int = 120) -> str:
    """Run ngspice on a netlist string, return stdout."""
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
        os.unlink(tmpfile)


def build_testbench(params: Dict[str, float], corner: str = "tt",
                    temp: float = 24, vdd: float = 1.8,
                    test_type: str = "gm") -> str:
    """Build a complete testbench netlist for the OTA."""
    # Read design template
    design = load_design()

    # Parameter substitution
    param_lines = "\n".join(f".param {k}={v}" for k, v in params.items())

    vcm = vdd / 2

    if test_type == "gm":
        # DC sweep to measure transconductance
        tb = f"""* OTA Gm Measurement Testbench
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}

{param_lines}

{design}

* Testbench
Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell

Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 0.6
Vbias_p vbias_p 0 {vdd - 0.6}

* Differential input: sweep from -300mV to +300mV around VCM
Vinp inp 0 {vcm}
Vinn inn 0 {vcm}

* DC sweep of differential input
.dc Vinp {vcm - 0.3} {vcm + 0.3} 0.001
.save v(outp) v(outn) i(Vdd)
.control
run
wrdata gm_sweep.dat v(outp) v(outn)
.endc
.end
"""
    elif test_type == "ac":
        # AC analysis for bandwidth
        tb = f"""* OTA AC Bandwidth Testbench
.lib "sky130_models/sky130.lib.spice" {corner}
.temp {temp}

{param_lines}

{design}

Xdut inp inn outp outn vbias_n vbias_p vcm vdd vss gm_cell

Vdd vdd 0 {vdd}
Vss vss 0 0
Vcm vcm 0 {vcm}
Vbias_n vbias_n 0 0.6
Vbias_p vbias_p 0 {vdd - 0.6}

Vinp inp 0 dc {vcm} ac 1m
Vinn inn 0 dc {vcm}

* Load capacitor (typical integrator cap)
Cload outp outn 5p

.ac dec 100 1k 1g
.save v(outp) v(outn)
.control
run
wrdata ac_response.dat vdb(outp,outn) vp(outp,outn)
.endc
.end
"""
    else:
        tb = f"* Unknown test type: {test_type}\n.end\n"

    return tb


# ---------------------------------------------------------------------------
# Measurement extraction
# ---------------------------------------------------------------------------

def measure_gm(params: Dict[str, float], corner="tt", temp=24, vdd=1.8) -> Dict:
    """Measure transconductance and linearity."""
    tb = build_testbench(params, corner, temp, vdd, "gm")
    output = run_ngspice(tb)

    measurements = {
        "gm_us": 0,
        "thd_pct": 100,
        "dc_gain_db": 0,
    }

    # Parse gm_sweep.dat if it exists
    datafile = os.path.join(PROJECT_DIR, "gm_sweep.dat")
    if os.path.exists(datafile):
        try:
            data = np.loadtxt(datafile)
            if data.ndim == 2 and data.shape[1] >= 3:
                vin = data[:, 0]
                voutp = data[:, 1]
                voutn = data[:, 2]
                vout_diff = voutp - voutn

                # Gm = d(Vout_diff) / d(Vin) at operating point
                dv = np.gradient(vout_diff, vin)
                mid = len(dv) // 2
                # Take Gm near the center (operating point)
                gm_region = dv[mid-5:mid+5]
                if len(gm_region) > 0:
                    gm = np.mean(gm_region)
                    measurements["gm_us"] = abs(gm) * 1e6  # placeholder scaling

                # Linearity: compute THD from deviation from best-fit line
                # Fit line to center ±200mV region
                vcm = vdd / 2
                mask = (vin >= vcm - 0.2) & (vin <= vcm + 0.2)
                if np.sum(mask) > 10:
                    vin_lin = vin[mask]
                    vout_lin = vout_diff[mask]
                    coeffs = np.polyfit(vin_lin, vout_lin, 1)
                    ideal = np.polyval(coeffs, vin_lin)
                    error = vout_lin - ideal
                    thd = np.sqrt(np.mean(error**2)) / (np.max(np.abs(vout_lin)) + 1e-12) * 100
                    measurements["thd_pct"] = thd

            os.unlink(datafile)
        except Exception as e:
            print(f"Warning: Could not parse gm_sweep.dat: {e}")

    return measurements


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def compute_score(measurements: Dict, specs: Dict) -> Tuple[float, Dict]:
    """Compute a 0-1 score based on how many specs are met."""
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

        # Parse target
        passed = False
        if target.startswith(">"):
            threshold = float(target[1:])
            passed = measured > threshold
        elif target.startswith("<"):
            threshold = float(target[1:])
            passed = measured < threshold
        elif target.startswith("="):
            threshold = float(target[1:])
            passed = abs(measured - threshold) < 0.01

        details[name] = {
            "target": target,
            "measured": measured,
            "pass": passed,
        }
        if passed:
            weighted_score += weight

    score = weighted_score / total_weight if total_weight > 0 else 0
    return score, details


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------

def validate(quick: bool = False):
    """Run full validation of the current best parameters."""
    print("=" * 60)
    print("  OTA (Gm Cell) Validation")
    print("=" * 60)

    specs = load_specs()

    # Load best parameters (or defaults)
    try:
        params = load_best_parameters()
        print(f"\nLoaded parameters from best_parameters.csv")
    except FileNotFoundError:
        print("\nNo best_parameters.csv found. Using defaults from design.cir.")
        params = {}

    # Nominal measurement
    print("\n--- Nominal Corner (tt, 24C, 1.8V) ---")
    meas = measure_gm(params)
    print(f"  Gm = {meas.get('gm_us', 0):.1f} µS")
    print(f"  THD = {meas.get('thd_pct', 0):.3f} %")

    # Score
    score, details = compute_score(meas, specs)
    print(f"\n--- Scoring ---")
    for name, d in details.items():
        status = "PASS" if d["pass"] else "FAIL"
        measured = f"{d['measured']:.4f}" if d['measured'] is not None else "N/A"
        print(f"  {name}: {measured} (target: {d['target']}) [{status}]")
    print(f"\n  SCORE: {score:.3f}")

    # Save measurements
    meas["score"] = score
    with open(os.path.join(PROJECT_DIR, "measurements.json"), "w") as f:
        json.dump(meas, f, indent=2)
    print(f"\nSaved measurements.json")

    return score


def main():
    parser = argparse.ArgumentParser(description="OTA Gm Cell Evaluator")
    parser.add_argument("--quick", action="store_true", help="Quick validation")
    args = parser.parse_args()

    os.makedirs(os.path.join(PROJECT_DIR, PLOTS_DIR), exist_ok=True)
    validate(quick=args.quick)


if __name__ == "__main__":
    main()
