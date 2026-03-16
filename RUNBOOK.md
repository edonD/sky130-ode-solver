# Analog ODE Solver — Runbook

Step-by-step instructions for the entire build, from launch to Lorenz attractor.

---

## Phase 1: Parallel Block Design (3 instances)

### Launch

```bash
cd sky130-ode-solver/infra
./deploy.sh phase1
```

Spins up 3x `c6a.4xlarge` (16 vCPU, 32GB RAM).

### Start agents

**Gm-Cell:**
```bash
ssh -i ~/.ssh/schemato-key.pem ubuntu@<GM_IP>
export ANTHROPIC_API_KEY="sk-ant-..."
tmux new -s gm-cell
./launch_agent.sh gm-cell
```

**Integrator:**
```bash
ssh -i ~/.ssh/schemato-key.pem ubuntu@<INT_IP>
export ANTHROPIC_API_KEY="sk-ant-..."
tmux new -s integrator
./launch_agent.sh integrator
```

**Multiplier:**
```bash
ssh -i ~/.ssh/schemato-key.pem ubuntu@<MULT_IP>
export ANTHROPIC_API_KEY="sk-ant-..."
tmux new -s multiplier
./launch_agent.sh multiplier
```

### When done

Each agent will meet all specs, generate plots, update README, commit and push.
Expected duration: **2–4 hours per block** (all 3 run simultaneously).

---

## Between Phase 1 and Phase 2

```bash
cd sky130-ode-solver
git pull
python orchestrate.py                    # Check: gm-cell=DONE, integrator=DONE, multiplier=DONE
python orchestrate.py --propagate        # Writes upstream_config.json into lorenz-core/
git add -A && git commit -m "Propagate Phase 1 measurements" && git push
```

---

## Phase 2: Lorenz Core (1 instance)

```bash
ssh -i ~/.ssh/schemato-key.pem ubuntu@<CORE_IP>
export ANTHROPIC_API_KEY="sk-ant-..."
bash full_setup.sh lorenz-core
tmux new -s lorenz-core
./launch_agent.sh lorenz-core
```

### What the lorenz-core agent does

1. Imports subcircuits from gm-cell, integrator, multiplier
2. Wires three coupled ODE channels per the Lorenz equations
3. Sets coefficient ratios: σ=10, ρ=28, β=8/3 via Gm programming
4. Runs transient simulation, compares x(t), y(t), z(t) against RK4 reference
5. Generates phase portraits (x-y, x-z, y-z), time series, correlation plots
6. Optimises initial conditions, time scaling, coefficient trimming

Expected duration: **3–5 hours**.

---

## Phase 3: Integration + Validation (1 instance)

```bash
ssh -i ~/.ssh/schemato-key.pem ubuntu@<INT_IP>
export ANTHROPIC_API_KEY="sk-ant-..."
bash full_setup.sh integration
tmux new -s integration
./launch_agent.sh integration
```

### What the integration agent does

1. Adds bias generation circuitry (bandgap + current mirrors)
2. Adds output buffers (source followers for off-chip measurement)
3. Runs long-duration transient (50+ Lorenz time units)
4. Validates butterfly attractor topology
5. Estimates Lyapunov exponent from analog trajectory
6. PVT corner analysis (does chaos survive process variation?)
7. Generates the final phase portraits and overlay plots

Expected duration: **2–4 hours**.

---

## Phase 4: Review

```bash
python orchestrate.py    # All 5 blocks should show [DONE]
```

### Verify the attractor

The integration block's README should contain:
- x-y phase portrait showing the classic butterfly
- Time series of x(t), y(t), z(t) showing chaotic switching
- Correlation plot vs RK4 reference (first 5 Lyapunov times)
- Power breakdown per block
- PVT corner survival analysis

---

## Dependency Graph

```
Phase 1 (parallel, 3 instances):

    ┌──────────┐   ┌──────────┐   ┌──────────┐
    │ Gm-Cell  │   │Integrator│   │Multiplier│
    │  (OTA)   │   │  (Gm-C)  │   │(Gilbert) │
    └────┬─────┘   └────┬─────┘   └────┬─────┘
         │              │              │
         │  propagate   │  propagate   │  propagate
         ▼              ▼              ▼
Phase 2 (1 instance):
    ┌─────────────────────────────────────────┐
    │           Lorenz Core                    │
    │  (3 coupled channels: dx, dy, dz)       │
    └────────────────┬────────────────────────┘
                     │
                     │  propagate
                     ▼
Phase 3 (1 instance):
    ┌─────────────────────────────────────────┐
    │           Integration                    │
    │  (bias gen + buffers + validation)       │
    └─────────────────────────────────────────┘
```

---

## Cost Summary

| Phase | Instances | Type | Hours | Cost/hr | Total |
|-------|-----------|------|-------|---------|-------|
| Phase 1 | 3 | c6a.4xlarge | 2–4 | $0.61 | $3.66–$7.32 |
| Phase 2 | 1 | c6a.4xlarge | 3–5 | $0.61 | $1.83–$3.05 |
| Phase 3 | 1 | c6a.4xlarge | 2–4 | $0.61 | $1.22–$2.44 |
| **Total** | | | **7–13** | | **$6.71–$12.81** |
