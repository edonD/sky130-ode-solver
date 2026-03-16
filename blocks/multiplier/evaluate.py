"""
evaluate.py — Simulation and validation utilities for Gilbert Cell Multiplier.

Provides:
- NGSpice simulation runner
- Linearity, gain constant, offset, bandwidth, THD measurements
- PVT corner sweep
- Monte Carlo analysis
- Cost function, scoring, and plotting

Usage standalone:
    python evaluate.py                   # full validation
    python evaluate.py --quick           # quick validation
"""

import os
import json
import csv
import argparse
import subprocess
import tempfile
from typing import Dict, List, Tuple

import numpy as np

NGSPICE = os.environ.get("NGSPICE", "ngspice")
DESIGN_FILE = "design.cir"
PARAMS_FILE = "parameters.csv"
SPECS_FILE = "specs.json"
PLOTS_DIR = "plots"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

TEMPERATURES = [-40, 24, 175]
SUPPLY_VOLTAGES = [1.62, 1.8, 1.98]
PROCESS_CORNERS = ["tt", "ss", "ff", "sf", "fs"]


def load_parameters(path: str = PARAMS_FILE) -> List[Dict]:
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
        os.unlink(tmpfile)


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


def validate(quick: bool = False):
    print("=" * 60)
    print("  Gilbert Cell Multiplier Validation")
    print("=" * 60)

    specs = load_specs()

    try:
        params = load_best_parameters()
        print(f"\nLoaded parameters from best_parameters.csv")
    except FileNotFoundError:
        print("\nNo best_parameters.csv found. Using defaults.")
        params = {}

    # Placeholder measurements — agent will implement real simulation
    meas = {
        "linearity_error_pct": 100,
        "k_mult": 0,
        "output_offset_mv": 100,
        "bw_mhz": 0,
        "thd_pct": 100,
        "power_uw": 0,
    }

    score, details = compute_score(meas, specs)
    print(f"\n--- Scoring ---")
    for name, d in details.items():
        status = "PASS" if d["pass"] else "FAIL"
        measured = f"{d['measured']:.4f}" if d['measured'] is not None else "N/A"
        print(f"  {name}: {measured} (target: {d['target']}) [{status}]")
    print(f"\n  SCORE: {score:.3f}")

    meas["score"] = score
    with open(os.path.join(PROJECT_DIR, "measurements.json"), "w") as f:
        json.dump(meas, f, indent=2)
    print(f"\nSaved measurements.json")

    return score


def main():
    parser = argparse.ArgumentParser(description="Gilbert Cell Multiplier Evaluator")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    os.makedirs(os.path.join(PROJECT_DIR, PLOTS_DIR), exist_ok=True)
    validate(quick=args.quick)


if __name__ == "__main__":
    main()
