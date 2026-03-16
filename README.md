# SKY130 Analog ODE Solver — Lorenz Attractor on Silicon

**An analog computer that solves the Lorenz equations in continuous time, producing chaotic attractors directly in hardware.**

```
dx/dt = σ(y − x)           σ = 10
dy/dt = x(ρ − z) − y       ρ = 28
dz/dt = xy − βz            β = 8/3
```

## Why This Exists

This project demonstrates that autonomous AI agents can design a complete analog computer — not just amplifiers or data converters, but a system that *computes* in the continuous-time domain. The Lorenz attractor is the iconic benchmark: if you can build it in analog, you can build anything.

Every circuit block in this project was designed by an autonomous agent on the SKY130 130nm open-source PDK.

## Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │            LORENZ ANALOG COMPUTER            │
                    │                                             │
  ┌──────────┐     │  ┌─────┐    ┌─────┐    ┌──────────┐        │
  │  BIAS    │────▶│  │ Gm  │───▶│ ∫dt │───▶│ x(t) out │        │
  │  GEN     │     │  │σ(y-x)│   │     │    └──────────┘        │
  └──────────┘     │  └─────┘    └─────┘         │               │
                    │       ▲         │            │               │
                    │       │         ▼            ▼               │
                    │  ┌─────┐    ┌─────┐    ┌────────┐          │
                    │  │ Gm  │───▶│ ∫dt │───▶│ y(t)   │          │
                    │  │x·ρ-y│   │     │    └────────┘          │
                    │  │-x·z │    └─────┘         │               │
                    │  └─────┘                     │               │
                    │       ▲                      ▼               │
                    │       │         ┌─────┐ ┌────────┐          │
                    │  ┌─────┐    ┌──▶│ ∫dt │▶│ z(t)   │          │
                    │  │MULT │    │   └─────┘ └────────┘          │
                    │  │x·y  │────┘        ▲                      │
                    │  │x·z  │─────────────┘                      │
                    │  └─────┘    ┌─────┐                         │
                    │             │ Gm  │◀── z feedback           │
                    │             │-β·z │                          │
                    │             └─────┘                         │
                    └─────────────────────────────────────────────┘
```

## Blocks

| Block | Description | Phase | Status |
|-------|-------------|-------|--------|
| **gm-cell** | Programmable OTA — implements σ, ρ, β, unity gain coefficients | 1 (parallel) | Pending |
| **integrator** | Gm-C integrator with reset switch — the d/dt operator | 1 (parallel) | Pending |
| **multiplier** | Gilbert cell for x·y and x·z nonlinear cross-terms | 1 (parallel) | Pending |
| **lorenz-core** | Three coupled ODE channels wired as Lorenz system | 2 | Pending |
| **integration** | Full system: bias gen + output buffers + Lorenz validation | 3 | Pending |

## Key Design Decisions

- **Differential signaling** throughout — state variables x, y, z are differential voltages centered at VCM = 0.9V with ±300mV swing
- **Gm-C topology** — integrators use transconductance × capacitor (no resistors), giving clean continuous-time integration
- **Gilbert cell multipliers** — four-quadrant multiplication for the x·y and x·z nonlinear terms
- **Coefficient programming** — Lorenz parameters (σ=10, ρ=28, β=8/3) implemented as gm ratios between OTA stages
- **Time scaling** — analog runs at >1000× real-time (µs per Lorenz time unit)

## Technology

- **Process:** SkyWater SKY130 130nm CMOS
- **Supply:** 1.8V
- **Simulation:** ngspice 44
- **PDK models:** sky130_fd_pr__nfet_01v8, sky130_fd_pr__pfet_01v8

## Signal Ranges

| Signal | Representation | Range |
|--------|---------------|-------|
| x(t) | V_x+ − V_x- | ±300 mV around VCM |
| y(t) | V_y+ − V_y- | ±300 mV around VCM |
| z(t) | V_z+ − V_z- | ±300 mV around VCM |
| VCM | Common mode | 0.9V |
| VDD | Supply | 1.8V |

## Running

```bash
# Check block status
python orchestrate.py

# Propagate measurements between phases
python orchestrate.py --propagate

# Launch agents (see RUNBOOK.md)
```

## Project Structure

```
sky130-ode-solver/
├── master_spec.json          ← Top-level system specs
├── orchestrate.py            ← Build orchestrator
├── interfaces.md             ← Signal contracts between blocks
├── RUNBOOK.md                ← Step-by-step deployment guide
├── blocks/
│   ├── gm-cell/              ← Programmable OTA (Phase 1)
│   ├── integrator/           ← Gm-C integrator (Phase 1)
│   ├── multiplier/           ← Gilbert cell (Phase 1)
│   ├── lorenz-core/          ← Three coupled channels (Phase 2)
│   └── integration/          ← Full system + validation (Phase 3)
└── demo/                     ← Browser-based visualization
```
