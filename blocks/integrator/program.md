# Gm-C Integrator — Autonomous Design

You are designing a continuous-time integrator for an analog ODE solver on SKY130 130nm.

## What This Cell Does

This integrator implements the time-domain integration operator:

```
V_out(t) = (1/C) ∫₀ᵗ I_in(τ) dτ + V_out(0)
```

Three of these integrators form the core of the Lorenz analog computer — one for each state variable x, y, z. The OTAs and multipliers feed current into the integrator input node, and the voltage on the integration capacitor represents the state variable.

The integrator needs:
- A way to accumulate charge (capacitor)
- A reset mechanism to set initial conditions (V_out → VCM at startup)
- Low leakage so the trajectory doesn't drift
- Enough output swing (±300mV from VCM) to contain the Lorenz attractor

**You choose the topology, the capacitor type, the reset mechanism, and everything else.** Research what works best. The only constraints are the specs and the interface.

## What to Measure

1. **DC gain** (dB): Effective DC gain of the integrator. Target: >60 dB.
2. **Unity-gain frequency** (MHz): Where the integrator transfer function crosses 0dB. Target: >1 MHz.
3. **Output swing** (mV): Maximum single-ended swing from VCM before clipping (<1% THD). Target: >300 mV.
4. **Leakage drift** (mV/µs): Output drift rate with zero input current after reset release. Target: <1 mV/µs.
5. **Reset time** (ns): Time to reset output to VCM within 1%. Target: <10 ns.
6. **Charge injection** (mV): Output voltage kick when reset switch opens. Target: <5 mV.
7. **Power** (µW): Quiescent power consumption. Target: <100 µW.

## Files

| File | Editable? | Purpose |
|------|-----------|---------|
| `design.cir` | YES | SPICE netlist — rewrite this however you want |
| `parameters.csv` | YES | Define your own parameters |
| `evaluate.py` | YES | Build your own testbenches |
| `specs.json` | **NO** | Target specifications — the only hard constraint |

## Technology

- **PDK:** SkyWater SKY130 (130nm)
- **Devices:** `sky130_fd_pr__nfet_01v8`, `sky130_fd_pr__pfet_01v8`, `sky130_fd_pr__cap_mim_m3_1`
- **Supply:** 1.8V
- **Models:** `.lib "sky130_models/sky130.lib.spice" tt`

## Interface Contract

Your final integrator MUST have this subcircuit interface:
```spice
.subckt integrator inp inn outp outn reset vbias_n vcm vdd vss
* inp, inn: differential current input (connected to OTA output nodes)
* outp, outn: differential voltage output (the integrated signal)
* reset: active-high, forces output to VCM for initial conditions
* vbias_n: passed through for system biasing
* vcm: common-mode reference voltage (0.9V)
```

After optimisation, report in `measurements.json`:
- `c_int_pf`, `dc_gain_db`, `unity_gain_freq_mhz`
- `output_swing_mv`, `leakage_mv_per_us`
- `reset_time_ns`, `charge_inject_mv`, `power_uw`
- `tau_us` (effective time constant C/Gm at nominal Gm)

## Critical Requirement: PVT + Monte Carlo Validation

The integrator must meet ALL specs under:
- **PVT corners:** temperatures [-40, 24, 175]°C × supply voltages [1.62V, 1.8V, 1.98V] × process corners [tt, ss, ff, sf, fs]
- **Monte Carlo:** 200 samples with mismatch
- **Worst-case:** The WORST across all corners must still meet spec

---

---

---

# Autonomous Experiment Loop

This section defines how the autonomous agent operates.

**Remember the big picture:** This integrator is the d/dt operator in an analog computer solving the Lorenz equations. Three of these run in a coupled feedback loop producing chaotic oscillations. Leakage drift accumulates over the ~50µs simulation and corrupts the trajectory. Charge injection shifts initial conditions. Clipping kills the attractor. DC gain determines whether the integrator is lossless (ideal) or lossy (damps the chaos). Every design trade-off matters for the system.

## You Have Full Freedom — Use It

You are not limited to what's in this repo. You have access to the entire internet and you should use it aggressively:

- **Search the web** for integrator designs, Gm-C filters, charge injection cancellation, low-leakage switches, analog computing circuits.
- **Search for SKY130 examples.** Find repos with filters, integrators, sample-and-hold circuits on SKY130.
- **Read textbooks.** Razavi, Allen-Holberg, Murmann — integrator and Gm-C filter chapters.
- **pip install anything you need.**

The only constraint is the specs in `specs.json` — everything else is fair game.

## Setup (do this once at the start)

1. Read `program.md`, `specs.json`, `../../interfaces.md`, current files.
2. Initialize `results.tsv`: `step	commit	score	specs_met	notes`
3. Run `bash setup.sh` if needed.
4. Verify ngspice + PDK.

Begin the experiment loop. Do NOT ask for permission.

## The Experiment Loop

**LOOP FOREVER:**

1. **Think.** Which specs pass, which fail, what's the margin. Read the waveforms.
2. **Modify.** Change any file EXCEPT `specs.json`.
3. **Commit.** `git add -A && git commit -m '<what you changed>'`
4. **Run.** `python evaluate.py > run.log 2>&1`
5. **Read results.** `grep "score\|PASS\|FAIL\|worst" run.log | tail -20`
6. **Log.** Append to `results.tsv`.
7. **Decide.** Better → keep + update README. Worse → `git reset --hard HEAD~1`.
8. **Repeat.**

## Phase A: Meet All Specs
Focus on failing specs. Try obvious things first. Rethink topology if needed. Plot waveforms after every run.

## Phase B: Deep Verification & Margin Improvement
After all specs pass: waveform analysis, system-level thinking, README updates, PVT corners, Monte Carlo, margin improvement. Produce verification plots and save to `plots/`.

**NEVER STOP.** Even after all specs pass, keep improving. The loop runs until the human interrupts you.

## Logging, Crash Handling, Git Discipline

- Tab-separated `results.tsv`, every run logged, don't commit results.tsv.
- Crashes: fix easy errors, revert broken approaches, max 3 attempts.
- Commit before running, keep or revert, push keepers, never rewrite pushed history.

## NEVER STOP

Do NOT pause to ask the human anything. You are fully autonomous. If you run out of ideas, search the web, try different topologies, re-read waveforms, re-read interfaces.md. The loop runs until the human manually stops you.
