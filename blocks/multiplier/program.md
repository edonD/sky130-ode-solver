# Analog Multiplier — Autonomous Design

You are designing a four-quadrant analog multiplier for an analog ODE solver on SKY130 130nm.

## What This Cell Does

This multiplier computes the product of two analog voltages:

```
V_out_diff = K × V_x_diff × V_y_diff
```

where K is the multiplication gain constant (units: V⁻¹).

Two instances of this multiplier are used in the Lorenz system:
1. **x·y** (for dz/dt = x·y − β·z)
2. **x·z** (for dy/dt = ρ·x − x·z − y)

These cross-terms make the Lorenz system nonlinear and enable chaos. If the multiplication is inaccurate, the attractor deforms or collapses. Both inputs swing ±300mV differential around VCM=0.9V.

**You choose the topology and everything else.** Gilbert cell, log-antilog, squaring-based, translinear, weak-inversion — whatever you think works best. Research it. The only constraints are the specs and the interface.

## What to Measure

1. **Linearity error** (%): Max deviation from ideal V_out = K·Vx·Vy over the full ±300mV range on both inputs. Requires a 2D sweep. Target: <5%.
2. **K_mult** (V⁻¹): Multiplication gain constant. Target: >0.5 V⁻¹. Report precisely — downstream blocks need this number.
3. **Output offset** (mV): DC output when both inputs are zero. Target: <10 mV.
4. **Bandwidth** (MHz): -3dB frequency of multiplication response. Target: >5 MHz.
5. **THD** (%): With 100kHz sine on X at ±200mV, DC on Y at +200mV. Target: <2%.
6. **Power** (µW): Total power consumption. Target: <300 µW.

## Files

| File | Editable? | Purpose |
|------|-----------|---------|
| `design.cir` | YES | SPICE netlist — rewrite however you want |
| `parameters.csv` | YES | Define your own parameters |
| `evaluate.py` | YES | Build your own testbenches |
| `specs.json` | **NO** | Target specifications — the only hard constraint |

## Technology

- **PDK:** SkyWater SKY130 (130nm)
- **Devices:** `sky130_fd_pr__nfet_01v8`, `sky130_fd_pr__pfet_01v8`
- **Supply:** 1.8V
- **Models:** `.lib "sky130_models/sky130.lib.spice" tt`

## Interface Contract

Your final multiplier MUST have this subcircuit interface:
```spice
.subckt multiplier xp xn yp yn outp outn vbias_n vbias_p vcm vdd vss
* xp, xn: first differential input (X)
* yp, yn: second differential input (Y)
* outp, outn: differential output proportional to (xp-xn)×(yp-yn)
```

After optimisation, report in `measurements.json`:
- `k_mult`, `linearity_error_pct`, `output_offset_mv`
- `bw_mhz`, `thd_pct`, `power_uw`

## Critical Requirement: PVT + Monte Carlo Validation

Must meet ALL specs under:
- **PVT corners:** [-40, 24, 175]°C × [1.62V, 1.8V, 1.98V] × [tt, ss, ff, sf, fs]
- **Monte Carlo:** 200 samples with mismatch
- **Worst-case:** The WORST across all corners must still meet spec

---

---

---

# Autonomous Experiment Loop

**Remember the big picture:** This multiplier computes x·y and x·z — the nonlinear terms that make the Lorenz system chaotic. Every percent of linearity error distorts the strange attractor. The gain constant K directly scales the effective Lorenz parameters. If K is wrong, chaos dies.

## You Have Full Freedom — Use It

Search the web aggressively. Read papers, find SKY130 examples, read textbooks (Razavi, Gilbert's original paper), study analog computer implementations. pip install anything you need. The only constraint is `specs.json`.

## Setup (do this once)

1. Read `program.md`, `specs.json`, `../../interfaces.md`, current files.
2. Initialize `results.tsv`: `step	commit	score	specs_met	notes`
3. Run `bash setup.sh` if needed. Verify ngspice + PDK.

Begin the experiment loop. Do NOT ask for permission.

## The Experiment Loop

**LOOP FOREVER:**

1. **Think.** Which specs pass, which fail. Read the waveforms.
2. **Modify.** Change any file EXCEPT `specs.json`.
3. **Commit.** `git add -A && git commit -m '<what you changed>'`
4. **Run.** `python evaluate.py > run.log 2>&1`
5. **Read results.** `grep "score\|PASS\|FAIL\|worst" run.log | tail -20`
6. **Log.** Append to `results.tsv`.
7. **Decide.** Better → keep + update README. Worse → `git reset --hard HEAD~1`.
8. **Repeat.**

## Phase A: Meet All Specs
## Phase B: Deep Verification & Margin Improvement

After all specs pass: waveform analysis, system-level thinking, README updates, PVT corners, Monte Carlo. Produce verification plots in `plots/`.

**NEVER STOP.** Keep improving. Simplify. Find cleaner topologies.

## Logging, Crash Handling, Git Discipline

- Tab-separated `results.tsv`, don't commit it. DO commit improvements.
- Crashes: fix or revert, max 3 attempts per approach.
- Commit before running, keep or revert, push keepers.

## NEVER STOP

Do NOT ask the human anything. You are fully autonomous. If stuck, search the web, try different topologies, re-read waveforms and interfaces. The loop runs until the human manually stops you.
