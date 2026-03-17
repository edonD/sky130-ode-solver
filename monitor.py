#!/usr/bin/env python3
"""
monitor.py — Watch agent progress across all blocks.

Usage:
    python monitor.py              # Pull + show summary of all blocks
    python monitor.py --full       # Pull + show full READMEs
    python monitor.py --block gm-cell  # Show one block in detail
    python monitor.py --plots      # List all generated plots
    python monitor.py --no-pull    # Skip git pull
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
BLOCKS_DIR = PROJECT_ROOT / "blocks"

BLOCKS = ["gm-cell", "integrator", "multiplier", "lorenz-core", "integration"]


def git_pull():
    """Pull latest from all agents."""
    try:
        result = subprocess.run(
            ["git", "pull", "--rebase"],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=30
        )
        if "Already up to date" not in result.stdout:
            print(f"  git pull: {result.stdout.strip()}")
        else:
            print("  git pull: up to date")
    except Exception as e:
        print(f"  git pull failed: {e}")


def get_recent_commits(block_name, n=5):
    """Get recent commits touching this block."""
    try:
        result = subprocess.run(
            ["git", "log", f"--oneline", f"-{n}", "--", f"blocks/{block_name}/"],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=10
        )
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    except Exception:
        return []


def get_block_summary(block_name):
    """Extract key info from a block's README and measurements."""
    path = BLOCKS_DIR / block_name
    summary = {
        "name": block_name,
        "has_readme": (path / "README.md").exists(),
        "has_measurements": (path / "measurements.json").exists(),
        "has_design": (path / "design.cir").exists(),
        "plots": [],
        "score": None,
        "specs": {},
        "readme_lines": 0,
        "readme_preview": "",
    }

    # Count plots
    plots_dir = path / "plots"
    if plots_dir.exists():
        summary["plots"] = sorted([f.name for f in plots_dir.iterdir()
                                     if f.suffix in (".png", ".svg", ".jpg", ".pdf")])

    # Read measurements
    if summary["has_measurements"]:
        try:
            with open(path / "measurements.json") as f:
                meas = json.load(f)
            summary["score"] = meas.get("score")
            summary["specs"] = {k: v for k, v in meas.items() if k != "score"}
        except Exception:
            pass

    # Read README preview
    if summary["has_readme"]:
        try:
            text = (path / "README.md").read_text(encoding="utf-8", errors="replace")
            lines = text.strip().split("\n")
            summary["readme_lines"] = len(lines)
            # Get first 10 non-empty lines as preview
            preview_lines = [l for l in lines if l.strip()][:10]
            summary["readme_preview"] = "\n".join(preview_lines)
        except Exception:
            pass

    return summary


def print_summary():
    """Print a compact summary of all blocks."""
    print()
    print("=" * 70)
    print("  ANALOG ODE SOLVER — AGENT PROGRESS MONITOR")
    print("=" * 70)

    for block_name in BLOCKS:
        s = get_block_summary(block_name)
        commits = get_recent_commits(block_name, 3)

        # Status indicator
        if s["score"] is not None and s["score"] >= 1.0:
            status = "DONE"
            color = "32"  # green
        elif s["score"] is not None and s["score"] > 0:
            status = f"SCORE {s['score']:.2f}"
            color = "33"  # yellow
        elif s["has_readme"] and s["readme_lines"] > 20:
            status = "WORKING"
            color = "36"  # cyan
        else:
            status = "PENDING"
            color = "37"  # white

        print(f"\n  \033[1m{block_name}\033[0m  [\033[{color}m{status}\033[0m]")
        print(f"  {'─' * 50}")

        # Score and specs
        if s["score"] is not None:
            print(f"  Score: {s['score']:.3f}")
            for spec_name, value in s["specs"].items():
                if isinstance(value, (int, float)):
                    print(f"    {spec_name}: {value}")

        # Plots
        if s["plots"]:
            print(f"  Plots ({len(s['plots'])}):")
            for p in s["plots"][:8]:
                print(f"    - {p}")
            if len(s["plots"]) > 8:
                print(f"    ... and {len(s['plots']) - 8} more")
        else:
            print(f"  Plots: none yet")

        # README
        if s["has_readme"]:
            print(f"  README: {s['readme_lines']} lines")
        else:
            print(f"  README: not created yet")

        # Recent commits
        if commits:
            print(f"  Recent commits:")
            for c in commits:
                print(f"    {c}")

    print(f"\n{'=' * 70}\n")


def print_full_readme(block_name):
    """Print the full README for a block."""
    path = BLOCKS_DIR / block_name / "README.md"
    if not path.exists():
        print(f"No README.md for {block_name}")
        return

    print(f"\n{'=' * 70}")
    print(f"  {block_name} — README.md")
    print(f"{'=' * 70}\n")
    print(path.read_text(encoding="utf-8", errors="replace"))
    print(f"\n{'=' * 70}\n")


def print_all_plots():
    """List all plots across all blocks."""
    print(f"\n{'=' * 70}")
    print(f"  ALL GENERATED PLOTS")
    print(f"{'=' * 70}\n")

    total = 0
    for block_name in BLOCKS:
        plots_dir = BLOCKS_DIR / block_name / "plots"
        if plots_dir.exists():
            plots = sorted([f for f in plots_dir.iterdir()
                           if f.suffix in (".png", ".svg", ".jpg", ".pdf")])
            if plots:
                print(f"  {block_name}/plots/ ({len(plots)} files):")
                for p in plots:
                    size_kb = p.stat().st_size / 1024
                    print(f"    {p.name:40s} {size_kb:6.1f} KB")
                total += len(plots)
                print()

    if total == 0:
        print("  No plots generated yet.\n")
    else:
        print(f"  Total: {total} plots\n")


def main():
    parser = argparse.ArgumentParser(description="Monitor agent progress")
    parser.add_argument("--full", action="store_true", help="Show full READMEs")
    parser.add_argument("--block", type=str, help="Show one block in detail")
    parser.add_argument("--plots", action="store_true", help="List all plots")
    parser.add_argument("--no-pull", action="store_true", help="Skip git pull")
    args = parser.parse_args()

    if not args.no_pull:
        print("\n  Pulling latest...")
        git_pull()

    if args.block:
        print_full_readme(args.block)
        s = get_block_summary(args.block)
        if s["plots"]:
            print(f"  Plots: {', '.join(s['plots'])}")
        commits = get_recent_commits(args.block, 10)
        if commits:
            print(f"\n  Commit history:")
            for c in commits:
                print(f"    {c}")
    elif args.plots:
        print_all_plots()
    elif args.full:
        for block_name in BLOCKS:
            print_full_readme(block_name)
    else:
        print_summary()


if __name__ == "__main__":
    main()
