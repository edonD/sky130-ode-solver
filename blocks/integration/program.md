# Full Integration — Autonomous Design

You are completing the analog ODE solver by adding support circuitry and running comprehensive end-to-end validation.

## What This Block Does

Takes the working Lorenz core and turns it into a complete, standalone analog computer:
1. **Bias generation** — VCM, current references, cascode biases. Whatever the core needs.
2. **Output buffers** — drive external loads without disturbing the core feedback loop.
3. **Startup/reset** — clean power-on sequence that sets initial conditions.
4. **End-to-end validation** — prove the system works with publication-quality results.

**You figure out what support circuitry is needed, design it, and validate the complete system.** The only constraints are the specs and the interface.

## What to Measure

1. **Lorenz correlation**: End-to-end trajectory correlation vs RK4 reference (first 5 Lyapunov times). Target: >0.90.
2. **Butterfly verified**: x-z phase portrait shows two distinct lobes. Target: 1 (boolean).
3. **Chaos duration** (Lorenz time units): System sustains chaotic oscillation without saturating. Target: >50 LTU.
4. **Total power** (mW): Everything included — core, bias, buffers. Target: <5 mW.
5. **Time scale factor**: Real time / Lorenz time. Target: >1000.
6. **PVT chaos survival** (%): Percentage of PVT corners where chaos is sustained. Target: >80%.

## Files

| File | Editable? | Purpose |
|------|-----------|---------|
| `design.cir` | YES | Full system netlist — design whatever you need |
| `evaluate.py` | YES | Simulation + validation + all plots |
| `specs.json` | **NO** | Target specifications |
| `upstream_config.json` | READ | Measured values from lorenz-core |

## Technology

- **PDK:** SkyWater SKY130 (130nm), **Supply:** 1.8V
- **Models:** `.lib "sky130_models/sky130.lib.spice" tt`

## Interface Contract

```spice
.subckt ode_solver vxp_buf vxn_buf vyp_buf vyn_buf vzp_buf vzn_buf reset vdd vss
* Buffered outputs for external measurement
* reset: active-high, resets all integrators
* vdd, vss: power supply
```

Report in `measurements.json`:
- `lorenz_correlation`, `butterfly_verified` (0 or 1)
- `chaos_duration_lorenz_units`, `total_power_mw`
- `time_scale_factor`, `pvt_chaos_survival`

## Critical Requirement: PVT Analysis

Run the Lorenz simulation at ALL 45 PVT corners. For each corner report whether chaos is sustained. The key metric is `pvt_chaos_survival`: what percentage of corners maintain chaotic oscillation without collapsing or saturating.

---

---

---

# Autonomous Experiment Loop

**Remember the big picture:** This is the final block. It produces the plots that people will see. The Lorenz attractor is one of the most visually stunning objects in mathematics — a strange attractor emerging from deterministic chaos, computed entirely in analog hardware on a 130nm CMOS process. Make the results jaw-dropping.

## You Have Full Freedom — Use It

Search the web for bias generator designs, output buffer topologies, Lyapunov exponent estimation, attractor topology analysis, publication-quality plotting techniques. pip install anything. The only constraint is `specs.json`.

## Setup (do this once)

1. Read `program.md`, `specs.json`, `../../interfaces.md`, `upstream_config.json`.
2. Import lorenz-core subcircuit from `../lorenz-core/design.cir`.
3. Initialize `results.tsv`: `step	commit	score	specs_met	notes`
4. Run `bash setup.sh` if needed. Verify ngspice + PDK.

Begin the experiment loop. Do NOT ask for permission.

## The Experiment Loop

**LOOP FOREVER:**

1. **Think.** Study the phase portraits. Which specs pass, which fail.
2. **Modify.** Change any file EXCEPT `specs.json` and `upstream_config.json`.
3. **Commit.** `git add -A && git commit -m '<what you changed>'`
4. **Run.** `python evaluate.py > run.log 2>&1`
5. **Read results.** `grep "score\|PASS\|FAIL\|correlation\|butterfly\|chaos\|power" run.log | tail -20`
6. **Log.** Append to `results.tsv`.
7. **Decide.** Better → keep + update README. Worse → `git reset --hard HEAD~1`.
8. **Repeat.**

## Phase A: End-to-End Working
Add bias gen, buffers, startup. Run long transient. Get the butterfly.

## Phase B: Publication-Quality Results
Produce all the plots: time series overlaid with RK4, phase portraits, 3D attractor, correlation decay, PVT survival heatmap, power breakdown. Make them beautiful. The README should read like a mini-paper with the butterfly hero image at the top.

**NEVER STOP.** Keep improving: better correlation, more PVT corners surviving, lower power, more beautiful plots, bifurcation diagrams, sensitivity analysis.

## Logging, Crash Handling, Git Discipline

- Tab-separated `results.tsv`, don't commit it. DO commit improvements.
- Long transients can crash ngspice — try reduced timestep, shorter sims first.
- Commit before running, keep or revert, push keepers.

## NEVER STOP

Do NOT ask the human anything. You are fully autonomous. The loop runs until the human manually stops you. If stuck, make the plots more beautiful, try more PVT corners, try different Lorenz parameters, add a bifurcation diagram.
