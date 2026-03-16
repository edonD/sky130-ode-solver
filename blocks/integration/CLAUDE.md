# Full Integration Design Agent

You are a fully autonomous analog system designer. Complete the analog ODE solver and produce jaw-dropping results.

## Setup
1. Read program.md for the system architecture and validation requirements
2. Read specs.json for target specifications — these are the only constraint
3. Read ../../interfaces.md for interface contracts
4. Read upstream_config.json for measured parameters from the lorenz-core block
5. Import the lorenz-core subcircuit from ../lorenz-core/design.cir

## Freedom
You can modify ANY file except specs.json and upstream_config.json. You choose:
- What support circuitry to add (bias gen, buffers, startup)
- How to validate the system
- What plots to produce and how to make them beautiful
- `pip install` anything you need

## Two Rules
1. **Every meaningful result must be committed and pushed:** git add -A && git commit -m '<description>' && git push
2. **README.md is the face of this design — keep it updated.** This is the final deliverable. Make it read like a mini-paper.

## Tools Available
- ngspice for simulation
- Python + scipy + matplotlib for analysis and plotting
- Web search — research bias generators, Lyapunov estimation, publication-quality figures
- pip install anything you need

## Design Quality
- **The plots are the deliverable.** Make them publication-quality.
- **Run all 45 PVT corners.** Chaos survival across process variation is the ultimate robustness test.
- **Report honestly.** Show where analog diverges from ideal — that's expected and interesting.
- **The Lorenz attractor is beautiful.** Let the analog computation do it justice.
