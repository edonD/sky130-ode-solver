#!/usr/bin/env python3
"""
orchestrate.py — Analog ODE Solver Build Orchestrator

Checks the status of each block, enforces dependency order,
and propagates measured interface values between blocks.

Usage:
    python orchestrate.py              # Show status of all blocks
    python orchestrate.py --propagate  # Push upstream measurements into downstream specs
    python orchestrate.py --launch     # Print which blocks are ready to launch
"""

import json
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
BLOCKS_DIR = PROJECT_ROOT / "blocks"

# Block definitions with dependencies
BLOCKS = {
    "gm-cell": {
        "path": BLOCKS_DIR / "gm-cell",
        "depends_on": [],
        "parallel_group": 1,
        "description": "Programmable OTA (sigma, rho, beta coefficients)",
    },
    "integrator": {
        "path": BLOCKS_DIR / "integrator",
        "depends_on": [],
        "parallel_group": 1,
        "description": "Gm-C integrator with reset",
    },
    "multiplier": {
        "path": BLOCKS_DIR / "multiplier",
        "depends_on": [],
        "parallel_group": 1,
        "description": "Gilbert cell four-quadrant multiplier",
    },
    "lorenz-core": {
        "path": BLOCKS_DIR / "lorenz-core",
        "depends_on": ["gm-cell", "integrator", "multiplier"],
        "parallel_group": 2,
        "description": "Three coupled ODE channels (Lorenz system)",
    },
    "integration": {
        "path": BLOCKS_DIR / "integration",
        "depends_on": ["lorenz-core"],
        "parallel_group": 3,
        "description": "Full system + bias gen + Lorenz validation",
    },
}


def get_block_status(block_name: str) -> dict:
    """Check the status of a block."""
    block = BLOCKS[block_name]
    path = block["path"]

    status = {
        "name": block_name,
        "description": block["description"],
        "parallel_group": block["parallel_group"],
        "depends_on": block["depends_on"],
        "has_specs": (path / "specs.json").exists(),
        "has_program": (path / "program.md").exists(),
        "has_design": (path / "design.cir").exists(),
        "has_evaluate": (path / "evaluate.py").exists(),
        "has_parameters": (path / "parameters.csv").exists(),
        "has_best_params": (path / "best_parameters.csv").exists(),
        "has_measurements": (path / "measurements.json").exists(),
        "has_readme": (path / "README.md").exists(),
        "measurements": None,
        "score": None,
    }

    if status["has_measurements"]:
        try:
            with open(path / "measurements.json") as f:
                meas = json.load(f)
            status["measurements"] = meas
            status["score"] = meas.get("score", None)
        except (json.JSONDecodeError, IOError):
            pass

    if status["has_measurements"] and status["has_best_params"]:
        status["state"] = "COMPLETE"
    elif status["has_design"] and status["has_evaluate"]:
        status["state"] = "READY"
    elif status["has_specs"] and status["has_program"]:
        status["state"] = "SETUP"
    else:
        status["state"] = "EMPTY"

    return status


def check_dependencies_met(block_name: str, statuses: dict) -> bool:
    """Check if all dependencies of a block are complete."""
    block = BLOCKS[block_name]
    for dep in block["depends_on"]:
        if statuses[dep]["state"] != "COMPLETE":
            return False
    return True


def print_status():
    """Print the status of all blocks."""
    statuses = {name: get_block_status(name) for name in BLOCKS}

    print()
    print("=" * 70)
    print("  ANALOG ODE SOLVER — BLOCK STATUS")
    print("=" * 70)

    for group in sorted(set(b["parallel_group"] for b in BLOCKS.values())):
        group_blocks = [n for n, b in BLOCKS.items() if b["parallel_group"] == group]
        parallel_label = "parallel" if len(group_blocks) > 1 else "sequential"
        print(f"\n  Phase {group} ({parallel_label}):")

        for name in group_blocks:
            s = statuses[name]
            deps_met = check_dependencies_met(name, statuses)

            if s["state"] == "COMPLETE":
                indicator = "[DONE]"
                score_str = f" score={s['score']:.2f}" if s['score'] is not None else ""
            elif s["state"] == "READY":
                if deps_met:
                    indicator = "[READY TO RUN]"
                else:
                    waiting = [d for d in s["depends_on"] if statuses[d]["state"] != "COMPLETE"]
                    indicator = f"[WAITING: {', '.join(waiting)}]"
                score_str = ""
            elif s["state"] == "SETUP":
                indicator = "[SETUP ONLY]"
                score_str = ""
            else:
                indicator = "[EMPTY]"
                score_str = ""

            deps_str = f" (needs: {', '.join(s['depends_on'])})" if s['depends_on'] else ""
            print(f"    {name:<15} {indicator:<20} {s['description']}{deps_str}{score_str}")

    complete = sum(1 for s in statuses.values() if s["state"] == "COMPLETE")
    total = len(BLOCKS)
    print(f"\n  Progress: {complete}/{total} blocks complete")

    print(f"\n  Next actions:")
    for name in BLOCKS:
        s = statuses[name]
        deps_met = check_dependencies_met(name, statuses)
        if s["state"] != "COMPLETE" and deps_met:
            if s["state"] in ("READY", "SETUP"):
                print(f"    -> Launch agent for: {name}")
            else:
                print(f"    -> Set up files for: {name}")

    blocked = [n for n in BLOCKS if not check_dependencies_met(n, statuses)
               and statuses[n]["state"] != "COMPLETE"]
    if blocked:
        print(f"\n  Blocked (waiting on dependencies): {', '.join(blocked)}")

    print(f"\n{'=' * 70}\n")
    return statuses


def propagate_measurements():
    """Push upstream measurements into downstream block specs/configs."""
    statuses = {name: get_block_status(name) for name in BLOCKS}

    print("\n--- Propagating interface values ---\n")

    # Gm-cell -> Lorenz-core: push Gm range, linearity, bandwidth
    if statuses["gm-cell"]["state"] == "COMPLETE":
        meas = statuses["gm-cell"]["measurements"]
        if meas:
            config_path = BLOCKS["lorenz-core"]["path"] / "upstream_config.json"
            upstream = {"gm_cell": {
                "gm_us": meas.get("gm_us"),
                "gm_max_us": meas.get("gm_max_us"),
                "gm_min_us": meas.get("gm_min_us"),
                "thd_pct": meas.get("thd_pct"),
                "bw_mhz": meas.get("bw_mhz"),
                "rout_kohm": meas.get("rout_kohm"),
                "power_uw": meas.get("power_uw"),
                "source": str(BLOCKS["gm-cell"]["path"] / "measurements.json"),
            }}
            if config_path.exists():
                with open(config_path) as f:
                    existing = json.load(f)
                existing.update(upstream)
                upstream = existing
            with open(config_path, "w") as f:
                json.dump(upstream, f, indent=2)
            print(f"  gm-cell -> lorenz-core: wrote {config_path}")

    # Integrator -> Lorenz-core: push time constant, leakage, reset time
    if statuses["integrator"]["state"] == "COMPLETE":
        meas = statuses["integrator"]["measurements"]
        if meas:
            config_path = BLOCKS["lorenz-core"]["path"] / "upstream_config.json"
            upstream_int = {"integrator": {
                "c_int_pf": meas.get("c_int_pf"),
                "tau_us": meas.get("tau_us"),
                "dc_gain_db": meas.get("dc_gain_db"),
                "leakage_mv_per_us": meas.get("leakage_mv_per_us"),
                "reset_time_ns": meas.get("reset_time_ns"),
                "charge_inject_mv": meas.get("charge_inject_mv"),
                "power_uw": meas.get("power_uw"),
                "source": str(BLOCKS["integrator"]["path"] / "measurements.json"),
            }}
            if config_path.exists():
                with open(config_path) as f:
                    existing = json.load(f)
                existing.update(upstream_int)
                upstream_int = existing
            with open(config_path, "w") as f:
                json.dump(upstream_int, f, indent=2)
            print(f"  integrator -> lorenz-core: wrote {config_path}")

    # Multiplier -> Lorenz-core: push gain constant, linearity, bandwidth
    if statuses["multiplier"]["state"] == "COMPLETE":
        meas = statuses["multiplier"]["measurements"]
        if meas:
            config_path = BLOCKS["lorenz-core"]["path"] / "upstream_config.json"
            upstream_mult = {"multiplier": {
                "k_mult": meas.get("k_mult"),
                "linearity_error_pct": meas.get("linearity_error_pct"),
                "bw_mhz": meas.get("bw_mhz"),
                "output_offset_mv": meas.get("output_offset_mv"),
                "power_uw": meas.get("power_uw"),
                "source": str(BLOCKS["multiplier"]["path"] / "measurements.json"),
            }}
            if config_path.exists():
                with open(config_path) as f:
                    existing = json.load(f)
                existing.update(upstream_mult)
                upstream_mult = existing
            with open(config_path, "w") as f:
                json.dump(upstream_mult, f, indent=2)
            print(f"  multiplier -> lorenz-core: wrote {config_path}")

    # Lorenz-core -> Integration: push trajectory characteristics
    if statuses["lorenz-core"]["state"] == "COMPLETE":
        meas = statuses["lorenz-core"]["measurements"]
        if meas:
            config_path = BLOCKS["integration"]["path"] / "upstream_config.json"
            upstream_core = {"lorenz_core": {
                "t_lorenz_us": meas.get("t_lorenz_us"),
                "trajectory_correlation": meas.get("trajectory_correlation"),
                "power_mw": meas.get("power_mw"),
                "x_swing_mv": meas.get("x_swing_mv"),
                "y_swing_mv": meas.get("y_swing_mv"),
                "z_swing_mv": meas.get("z_swing_mv"),
                "source": str(BLOCKS["lorenz-core"]["path"] / "measurements.json"),
            }}
            if config_path.exists():
                with open(config_path) as f:
                    existing = json.load(f)
                existing.update(upstream_core)
                upstream_core = existing
            with open(config_path, "w") as f:
                json.dump(upstream_core, f, indent=2)
            print(f"  lorenz-core -> integration: wrote {config_path}")

    print("\n--- Propagation complete ---\n")


def print_launch_info():
    """Print which blocks can be launched right now."""
    statuses = {name: get_block_status(name) for name in BLOCKS}

    launchable = []
    for name in BLOCKS:
        s = statuses[name]
        if s["state"] != "COMPLETE" and check_dependencies_met(name, statuses):
            if s["state"] in ("READY", "SETUP"):
                launchable.append(name)

    if not launchable:
        complete = sum(1 for s in statuses.values() if s["state"] == "COMPLETE")
        if complete == len(BLOCKS):
            print("\nAll blocks complete! The analog ODE solver is ready.")
        else:
            blocked = [n for n in BLOCKS if statuses[n]["state"] != "COMPLETE"]
            print(f"\nNo blocks ready to launch. Blocked: {', '.join(blocked)}")
            for b in blocked:
                waiting = [d for d in BLOCKS[b]["depends_on"]
                           if statuses[d]["state"] != "COMPLETE"]
                if waiting:
                    print(f"  {b} waiting on: {', '.join(waiting)}")
    else:
        print(f"\nBlocks ready to launch ({len(launchable)}):")
        for name in launchable:
            block_path = BLOCKS[name]["path"]
            print(f"\n  {name}:")
            print(f"    cd {block_path}")
            print(f"    # Launch your AI agent here pointing at this directory")


def main():
    parser = argparse.ArgumentParser(description="Analog ODE Solver Build Orchestrator")
    parser.add_argument("--propagate", action="store_true",
                        help="Propagate upstream measurements to downstream blocks")
    parser.add_argument("--launch", action="store_true",
                        help="Show which blocks are ready to launch")
    args = parser.parse_args()

    if args.propagate:
        propagate_measurements()
    elif args.launch:
        print_launch_info()

    print_status()


if __name__ == "__main__":
    main()
