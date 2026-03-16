# Lorenz Core — Autonomous Design

You are wiring three coupled ODE channels into the Lorenz system using subcircuits designed by other agents.

## What This Block Does

This is the heart of the analog computer. It connects OTA, integrator, and multiplier subcircuits into a feedback network that implements:

```
dx/dt = σ(y − x)           σ = 10
dy/dt = ρ·x − x·z − y     ρ = 28
dz/dt = x·y − β·z          β = 8/3 ≈ 2.667
```

The state variables x, y, z are differential voltages (±300mV around VCM=0.9V). The Lorenz parameters are implemented through Gm ratios and multiplier gain scaling.

**You figure out how to wire it, how to set the coefficients, how to scale time, and how to set initial conditions.** Read the upstream subcircuit designs, understand their measured characteristics, and build the system. The only constraints are the specs and the interface.

## What to Measure

1. **Trajectory correlation**: Cross-correlation between analog x(t) and RK4 numerical reference over the first 5 Lyapunov times (~3.4 Lorenz time units). Target: >0.90.
2. **Attractor topology**: The x-z phase portrait must show two distinct lobes (the butterfly). Target: 1 (boolean).
3. **Lyapunov exponent sign**: The largest Lyapunov exponent must be positive, confirming chaotic (not periodic or convergent) dynamics. Target: 1 (boolean).
4. **Coefficient error** (%): Max error in effective σ, ρ, β vs targets, measured by fitting the trajectory. Target: <10%.
5. **Power** (mW): Total power of the three-channel core. Target: <3 mW.

## Upstream Subcircuits

Import these from Phase 1 blocks — read their `measurements.json` and `upstream_config.json` for measured characteristics:
- `../gm-cell/design.cir` — programmable OTA
- `../integrator/design.cir` — integrator with reset
- `../multiplier/design.cir` — four-quadrant multiplier

## Validation Approach

1. Generate an RK4 numerical reference of the Lorenz system (use scipy)
2. Run ngspice transient simulation of the analog circuit
3. Extract x(t), y(t), z(t) from differential node voltages
4. Scale and time-align the analog output to the numerical reference
5. Compute cross-correlation
6. Plot phase portraits (x-z is the butterfly)
7. Estimate Lyapunov exponent from trajectory divergence

## Files

| File | Editable? | Purpose |
|------|-----------|---------|
| `design.cir` | YES | Top-level netlist — wire the subcircuits however you want |
| `evaluate.py` | YES | Simulation + validation + plotting — build it |
| `specs.json` | **NO** | Target specifications |
| `upstream_config.json` | READ | Measured values from Phase 1 blocks |

## Technology

- **PDK:** SkyWater SKY130 (130nm), **Supply:** 1.8V
- **Models:** `.lib "sky130_models/sky130.lib.spice" tt`

## Interface Contract

```spice
.subckt lorenz_core vxp vxn vyp vyn vzp vzn reset vbias_n vbias_p vcm vdd vss
```

Report in `measurements.json`:
- `trajectory_correlation`, `attractor_two_lobed` (0 or 1), `lyapunov_positive` (0 or 1)
- `coefficient_error_pct`, `power_mw`
- `t_lorenz_us`, `x_swing_mv`, `y_swing_mv`, `z_swing_mv`

---

---

---

# Autonomous Experiment Loop

**Remember the big picture:** You are building the Lorenz attractor in analog hardware. The circuit must produce the characteristic butterfly-shaped strange attractor with sensitive dependence on initial conditions. If the coefficients are wrong, chaos dies. If the integrators clip, the trajectory rails out. If the multipliers are inaccurate, the nonlinearity distorts. Every component must work together.

## You Have Full Freedom — Use It

Search the web aggressively. Read papers on analog Lorenz implementations, Chua circuits, chaotic oscillators, analog computing. Find SKY130 examples. Read Sprott's "Elegant Chaos," Strogatz's "Nonlinear Dynamics and Chaos." pip install anything you need.

## Setup (do this once)

1. Read `program.md`, `specs.json`, `../../interfaces.md`, `upstream_config.json`.
2. Import and study the upstream subcircuits.
3. Initialize `results.tsv`: `step	commit	score	specs_met	notes`
4. Run `bash setup.sh` if needed. Verify ngspice + PDK.

Begin the experiment loop. Do NOT ask for permission.

## The Experiment Loop

**LOOP FOREVER:**

1. **Think.** Study the phase portrait. Which specs pass, which fail.
2. **Modify.** Change any file EXCEPT `specs.json` and `upstream_config.json`.
3. **Commit.** `git add -A && git commit -m '<what you changed>'`
4. **Run.** `python evaluate.py > run.log 2>&1`
5. **Read results.** `grep "score\|PASS\|FAIL\|correlation\|butterfly" run.log | tail -20`
6. **Log.** Append to `results.tsv`.
7. **Decide.** Better → keep + update README. Worse → `git reset --hard HEAD~1`.
8. **Repeat.**

## Phase A: Get the Butterfly
Wire the channels, set coefficients, run transient, check phase portrait. If periodic → coefficients wrong. If saturated → reduce scaling. If no oscillation → check feedback.

## Phase B: Match the Ideal
Optimize correlation, trim coefficients, verify Lyapunov, produce all plots. README should have the butterfly prominently at the top.

**NEVER STOP.** Keep improving correlation, reducing power, trying different coefficient trimming. If stuck, try different time scales, initial conditions, or add small noise to break symmetry.

## Logging, Crash Handling, Git Discipline

- Tab-separated `results.tsv`, don't commit it. DO commit improvements.
- Lorenz transients can crash ngspice — try `.option method=gear reltol=1e-4`, shorter sims first.
- Commit before running, keep or revert, push keepers.

## NEVER STOP

Do NOT ask the human anything. You are fully autonomous. The loop runs until the human manually stops you.
