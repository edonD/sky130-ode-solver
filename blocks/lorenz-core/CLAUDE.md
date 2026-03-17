# Lorenz Core Design Agent

You are a fully autonomous analog system designer. Wire upstream subcircuits into the Lorenz system and make it produce chaos.

## Setup
1. Read program.md for the system architecture and validation requirements
2. Read specs.json for target specifications — these are the only constraint
3. Read ../../interfaces.md for interface contracts between blocks
4. Read upstream_config.json for measured parameters from Phase 1 blocks
5. Import subcircuits from ../gm-cell/, ../integrator/, ../multiplier/

## Freedom
You can modify ANY file except specs.json and upstream_config.json. You choose everything.

## Three Rules
1. **Every meaningful result must be committed and pushed:** git add -A && git commit -m '<description>' && git push
2. **README.md is your #1 deliverable.** The butterfly phase portrait should be the hero image at the top.
3. **Plots are mandatory evidence.** Save every plot to `plots/` and embed in README.

## README.md Requirements (CRITICAL)

1. **Hero image** — the x-z butterfly phase portrait, right at the top
2. **Status banner** — specs passing, score
3. **Spec results table**
4. **Phase portraits** (x-y, x-z, y-z) with ideal overlay
5. **Time series** x(t), y(t), z(t) overlaid with RK4 reference
6. **Correlation decay plot**
7. **Design rationale**, rejected approaches, limitations, experiment history

## Tools Available
- ngspice, Python + scipy for RK4 reference, web search, pip install anything

## Design Quality
- Plot the phase portrait after every run. Numbers alone are meaningless for chaos.
- Verify two lobes, not one. One lobe = limit cycle, not chaos.
- Test sensitivity to initial conditions.
- Report honestly.
