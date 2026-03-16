# Programmable OTA (Gm Cell) — Autonomous Design

You are designing a programmable transconductance amplifier (OTA) for an analog ODE solver on SKY130 130nm.

## What This Cell Does

This OTA converts a differential input voltage to a proportional differential output current:

```
I_out = Gm × (Vinp - Vinn)
```

The transconductance Gm must be programmable via a bias current. Multiple instances of this cell will implement the Lorenz equation coefficients (σ=10, ρ=28, β=2.667, and unity=1), so the Gm ratio between max and min settings must be at least 30×.

In the Lorenz analog computer, OTA output currents sum at the integrator input node (Kirchhoff's current law). The OTA must be linear over the full ±300mV differential input swing — this is the hard part.

**You choose the topology, the sizing strategy, the linearization technique, and everything else.** Research what works best. The only constraints are the specs and the interface.

## What to Measure

1. **Gm** (µS): Transconductance at nominal bias. Target: >50 µS.
2. **Gm ratio**: Gm_max / Gm_min across the programmable range. Target: >30.
3. **THD** (%): Total harmonic distortion for ±200mV differential sinusoidal input at 100kHz. Target: <1%.
4. **Bandwidth** (MHz): -3dB frequency of the transconductance. Target: >10 MHz.
5. **DC gain** (dB): Open-loop voltage gain. Target: >40 dB.
6. **Power** (µW): Per OTA cell at nominal bias. Target: <200 µW.

## Files

| File | Editable? | Purpose |
|------|-----------|---------|
| `design.cir` | YES | SPICE netlist — rewrite this however you want |
| `parameters.csv` | YES | Parameter names, min, max, scale — define your own |
| `evaluate.py` | YES | Simulation runner, measurement, scoring — build your own testbenches |
| `specs.json` | **NO** | Target specifications — the only hard constraint |

## Technology

- **PDK:** SkyWater SKY130 (130nm)
- **Devices:** `sky130_fd_pr__nfet_01v8`, `sky130_fd_pr__pfet_01v8`
- **Supply:** 1.8V
- **Models:** `.lib "sky130_models/sky130.lib.spice" tt`

## Interface Contract

Your final OTA MUST have this subcircuit interface:
```spice
.subckt gm_cell inp inn outp outn vbias_n vbias_p vcm vdd vss
```

After optimisation, report in `measurements.json`:
- `gm_us`, `gm_max_us`, `gm_min_us`, `gm_ratio`
- `thd_pct`, `bw_mhz`, `dc_gain_db`, `rout_kohm`, `power_uw`

## Critical Requirement: PVT + Monte Carlo Validation

The OTA must meet ALL specs under:
- **PVT corners:** temperatures [-40, 24, 175]°C × supply voltages [1.62V, 1.8V, 1.98V] × process corners [tt, ss, ff, sf, fs]
- **Monte Carlo:** 200 samples with mismatch — specs must hold at mean ± 4.5 sigma
- **Worst-case:** The WORST measurement across all corners AND MC bounds must still meet spec

---

---

---

# Autonomous Experiment Loop

This section defines how the autonomous agent operates. It applies to every block in the analog ODE solver project.

**Remember the big picture:** This block is part of an analog computer that solves the Lorenz equations in continuous time, producing chaotic attractors directly in hardware. Every design decision should be evaluated through that lens. Ask yourself: "Will this OTA work when four of them are summing currents into a single integrator?" and "Can it reproduce the Lorenz coefficients accurately enough to maintain chaos?" The block in isolation means nothing — it must work in the system.

## You Have Full Freedom — Use It

You are not limited to what's in this repo. You have access to the entire internet and you should use it aggressively:

- **Search the web** for state-of-the-art designs. Look up ISSCC papers, JSSC publications, IEEE Xplore, ResearchGate, university thesis PDFs. Find what the best analog designers in the world have done for this exact type of circuit.
- **Search for SKY130 examples.** Other people have designed similar circuits on the SKY130 PDK — find their repos on GitHub, read their netlists, learn from their parameter choices.
- **Look up design techniques.** If you're stuck on linearity, search for linearization techniques. If gain is too low, search for high-output-impedance topologies. Think creatively.
- **Read textbooks and course notes online.** Razavi, Allen-Holberg, Murmann lecture slides — many are freely available and contain exact design equations.
- **Study analog computer papers.** Search for "analog Lorenz attractor CMOS," "Chua circuit implementation," "continuous-time analog computing." Understand what works.
- **pip install anything you need.** If a better optimizer exists (optuna, cma, bayesian-optimization), install it. You have full access.

Do whatever you think is necessary to produce the best possible design. There are no restrictions on your research methods. The only constraint is the specs in `specs.json` — everything else is fair game.

## Setup (do this once at the start)

1. Read `program.md` for the full design brief and architecture.
2. Read `specs.json` for the pass/fail targets. These are the only hard constraints.
3. Read `../../interfaces.md` for signal contracts with other blocks.
4. Read `design.cir`, `parameters.csv`, `evaluate.py` for current state.
5. Initialize `results.tsv` with the header row:
   ```
   step	commit	score	specs_met	notes
   ```
6. Run `bash setup.sh` if SKY130 models are not already set up.
7. Confirm everything works: run a quick simulation to verify ngspice + PDK.

Once setup is confirmed, begin the experiment loop. Do NOT ask for permission.

## The Experiment Loop

**LOOP FOREVER:**

1. **Think.** Look at the current state: which specs pass, which fail, what's the margin. Read the waveforms. Decide what to try next.

2. **Modify.** Change `design.cir`, `parameters.csv`, `evaluate.py`, or write an optimization script. You can modify any file EXCEPT `specs.json`.

3. **Commit.** `git add -A && git commit -m '<what you changed>'`

4. **Run.** Execute the simulation or optimization. Redirect output:
   ```bash
   python evaluate.py > run.log 2>&1
   ```
   Or run your own optimizer script.

5. **Read results.** Extract the key metrics:
   ```bash
   grep "score\|PASS\|FAIL\|worst" run.log | tail -20
   ```
   If grep is empty, the run crashed. Read `tail -50 run.log` for the error. Fix and re-run. If you can't fix after 3 attempts, log it as a crash and move on.

6. **Log.** Append to `results.tsv`:
   ```
   <step>	<commit>	<score>	<specs_met>	<description of what you tried>
   ```

7. **Decide.**
   - If the result is **better** (higher score, more specs met, or better margins): **keep it**. This is now your new baseline. Update README.md with the latest numbers and plots.
   - If the result is **equal or worse**: **revert**. `git reset --hard HEAD~1`. Try something else.

8. **Repeat.** Go back to step 1.

## Two Phases

### Phase A: Meet All Specs

Your first priority is getting ALL specs to pass. This means score = 1.0 with every measurement meeting its target. During this phase:

- Focus on the specs that are failing. Ignore margin optimization.
- Try the obvious things first: sensible default parameters, textbook designs.
- If a spec is way off, rethink the topology or approach — don't just tweak parameters.
- When you get stuck, read the waveforms. The circuit is telling you what's wrong.
- Even during Phase A, plot waveforms after every successful run. You need to see what the circuit is doing — numbers alone are not enough.

### Phase B: Deep Verification & Margin Improvement (after all specs pass)

Once all specs pass, this is where the real engineering begins. You are no longer just hitting targets — you are proving this circuit is ready to be part of an analog Lorenz computer.

#### B.1 — Waveform Analysis (MANDATORY after every keeper)

After every run that you keep, you MUST:

1. **Plot the key waveforms** and save them to `plots/`. Every plot must have:
   - Clear axis labels (time in ns, voltage in V, current in µA)
   - A descriptive title that states what the plot shows
   - Annotation of key events

2. **Study every waveform critically.** Does this look like what the textbook says it should? Any glitches? Any unexpected behavior?

3. **If something looks wrong, investigate before moving on.** A waveform anomaly is more important than a passing spec number.

#### B.2 — System-Level Thinking

Remember that this block will be integrated into the Lorenz analog computer. After each improvement, think about how your block connects to the others. Will it work in the system? Are there interface issues you haven't considered?

#### B.3 — README.md as the Progress Dashboard

**README.md is how the human monitors your progress.** They will read ONLY the README to understand what you've done. Write it for a designer who has never seen this block before.

README.md MUST contain (update after every keeper):
1. **Status banner** — which specs pass, which fail, current score.
2. **Spec table** — measured values, targets, margin, pass/fail.
3. **Waveform plots** — embedded as `![description](plots/filename.png)`.
4. **Design parameters** — current values in a table.
5. **Design rationale** — why you chose this topology, why these sizes.
6. **What was tried and rejected** — approaches that didn't work and why.
7. **Known limitations** — honest assessment.
8. **Experiment history** — summary table of all runs.

#### B.4 — Margin Improvement

After verification plots are done, continue improving:
- Run PVT corner sweeps. Worst-case numbers matter.
- Run Monte Carlo. Statistical yield matters.
- Reduce power, reduce area, increase linearity.
- A design with 40% margin everywhere beats one that barely passes.
- Try simplifying: fewer transistors, smaller sizes, less complexity.

**NEVER STOP.** Even after all specs pass, all plots are generated, and margins are good, keep looking for improvements. Simplify the circuit. Find a cleaner topology. The loop runs until the human interrupts you.

## Logging Rules

- `results.tsv` is tab-separated (NOT comma-separated).
- Every run gets logged, even crashes.
- Do NOT commit `results.tsv` — leave it untracked so it doesn't create merge conflicts.
- DO commit and push `best_parameters.csv`, `measurements.json`, plots, and README.md after every improvement.

## Crash Handling

- If a simulation crashes (ngspice error, convergence failure, Python error):
  - Read the error. If it's a typo or easy fix, fix and re-run.
  - If the approach is fundamentally broken, revert and try something different.
  - Log "crash" in results.tsv and move on.
  - Never spend more than 3 attempts on a single failing approach.

## Git Discipline

- Every experiment gets its own commit BEFORE running (so you can revert cleanly).
- Keep commits: stay on the current commit.
- Discard experiments: `git reset --hard HEAD~1` to go back.
- Push after every keeper: `git push` so progress is saved remotely.
- Never rewrite history that's already pushed. Only reset un-pushed commits.

## NEVER STOP

Once the experiment loop begins, do NOT pause to ask the human anything. Do NOT ask "should I continue?" or "is this good enough?". The human may be away for hours. You are fully autonomous.

If you run out of ideas:
- Re-read the waveforms. Look at every node. The circuit is telling you something.
- Search the web for alternative topologies or techniques you haven't tried.
- Try combining two previous near-miss approaches.
- Try a completely different topology or optimization algorithm.
- Read the program.md again for hints you may have missed.
- Try shrinking the design (fewer transistors, smaller sizes, less power).
- Re-read `../../interfaces.md` — think about how your block connects to the others.

The loop runs until the human manually stops you.
