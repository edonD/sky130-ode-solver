# Analog ODE Solver — Interface Contracts

Every block must respect these interfaces exactly. If you're an agent designing one block, read this file to understand what your inputs and outputs must look like.

## Signal Naming Convention

All signals use differential pairs centered at VCM = 0.9V:

| Signal | Description | Range |
|--------|-------------|-------|
| `vdd` | Power supply | 1.8V |
| `vss` | Ground | 0V |
| `vcm` | Common-mode reference | 0.9V |
| `vbias_n` | NMOS tail current bias | Set by bias generator |
| `vbias_p` | PMOS cascode/load bias | Set by bias generator |
| `inp`, `inn` | Differential input pair | VCM ± 300mV |
| `outp`, `outn` | Differential output pair | VCM ± 300mV |

## Differential Signal Convention

State variables x, y, z are represented as:
- `v_x = vxp - vxn` (differential voltage, ±300mV)
- Physical voltages: `vxp = VCM + x_scaled/2`, `vxn = VCM - x_scaled/2`
- Scaling: Lorenz variables (x ∈ [-20, 20]) mapped to ±300mV → scale factor = 15mV per unit

## Block-to-Block Interfaces

### 1. Gm-Cell (Programmable OTA)

The OTA converts a differential input voltage to a differential output current.

| Parameter | Symbol | Expected Range | Measured By |
|-----------|--------|----------------|-------------|
| Transconductance | `Gm` | 10–500 µS, programmable | Gm-cell agent |
| Input common-mode range | `ICMR` | VCM ± 400mV minimum | Gm-cell agent |
| Output swing | `V_out_swing` | ± 300mV from VCM | Gm-cell agent |
| Linearity (THD) | `THD` | < 1% for ±200mV input | Gm-cell agent |
| Bandwidth | `BW` | > 10 MHz | Gm-cell agent |
| Output resistance | `Rout` | > 100 kΩ (high for current output) | Gm-cell agent |
| DC gain | `A_v` | > 40 dB | Gm-cell agent |
| Power per cell | `P_cell` | < 200 µW | Gm-cell agent |
| Gm programming ratio | `Gm_max/Gm_min` | > 30 (to cover σ=10, ρ=28, β=2.67, unity=1) | Gm-cell agent |

**Subcircuit interface:**
```spice
.subckt gm_cell inp inn outp outn vbias_n vbias_p vcm vdd vss
* Parameters: gm_target (sets the transconductance via tail current)
.ends
```

**What downstream blocks need:** A differential-in, differential-out OTA whose Gm can be set by adjusting the tail current bias. Must be linear over the full ±300mV differential input swing.

### 2. Integrator (Gm-C)

The integrator implements: `V_out(t) = (1/C) ∫ I_in dt`

Combined with the Gm cell feeding it: `V_out(t) = (Gm/C) ∫ V_in dt`

| Parameter | Symbol | Expected Range | Measured By |
|-----------|--------|----------------|-------------|
| Integration capacitance | `C_int` | 1–20 pF | Integrator agent |
| Unity-gain frequency | `f_unity` | Gm/(2π·C), tunable | Integrator agent |
| DC gain | `A_DC` | > 60 dB (integrator should be high-gain) | Integrator agent |
| Output swing | `V_out_swing` | ± 300mV from VCM | Integrator agent |
| Reset time | `T_reset` | < 10 ns | Integrator agent |
| Charge injection (reset) | `ΔV_inject` | < 5 mV | Integrator agent |
| Integrator time constant | `τ = C/Gm` | 0.1–10 µs (sets Lorenz time scale) | Integrator agent |
| Leakage drift | `dV/dt_leak` | < 1 mV/µs | Integrator agent |
| Power | `P_int` | < 100 µW | Integrator agent |

**Subcircuit interface:**
```spice
.subckt integrator inp inn outp outn reset vbias_n vcm vdd vss
* C_int is internal (MIM capacitor)
* reset: active-high, shorts output to VCM for initial conditions
.ends
```

**What downstream blocks need:** An integrator that accepts differential current input (from an OTA) and produces a differential voltage output. The reset switch allows setting initial conditions. Time constant τ = C/Gm determines the Lorenz time scale.

### 3. Multiplier (Gilbert Cell)

The multiplier implements: `V_out ∝ V_x · V_y` (four-quadrant)

| Parameter | Symbol | Expected Range | Measured By |
|-----------|--------|----------------|-------------|
| Multiplication gain | `K_mult` | Report value (V_out = K · Vx · Vy) | Multiplier agent |
| Input range (both ports) | `V_in_range` | ± 300mV differential | Multiplier agent |
| Linearity error | `ε_lin` | < 5% over full input range | Multiplier agent |
| Bandwidth | `BW_mult` | > 5 MHz | Multiplier agent |
| Output swing | `V_out_swing` | ± 300mV from VCM | Multiplier agent |
| Output offset | `V_os` | < 10 mV | Multiplier agent |
| Power | `P_mult` | < 300 µW | Multiplier agent |
| THD (single-tone) | `THD` | < 2% at ±200mV input | Multiplier agent |

**Subcircuit interface:**
```spice
.subckt multiplier xp xn yp yn outp outn vbias_n vbias_p vcm vdd vss
* Four-quadrant: out ∝ (xp-xn) × (yp-yn)
.ends
```

**What downstream blocks need:** A four-quadrant multiplier that takes two differential voltage inputs and produces a differential voltage output proportional to their product. Used for the x·y and x·z cross-terms in the Lorenz equations.

### 4. Lorenz Core → Integration

The lorenz-core produces three differential output pairs representing x(t), y(t), z(t):

| Parameter | Symbol | Expected Range | Measured By |
|-----------|--------|----------------|-------------|
| x(t) output | `vxp, vxn` | VCM ± 300mV | Lorenz-core agent |
| y(t) output | `vyp, vyn` | VCM ± 300mV | Lorenz-core agent |
| z(t) output | `vzp, vzn` | VCM ± 300mV | Lorenz-core agent |
| Lorenz time unit | `T_lorenz` | 0.1–10 µs | Lorenz-core agent |
| Trajectory correlation | `ρ_corr` | > 0.90 vs RK4 (first 5 Lyapunov times) | Lorenz-core agent |
| Attractor topology | | Two-lobed butterfly | Lorenz-core agent |
| Power | `P_core` | < 3 mW | Lorenz-core agent |

## Timing

There is no clock in this system — it is a continuous-time analog computer. The circuit runs freely after the reset switches release.

```
     ┌────────────────────────────────────────────────────────────┐
     │                    OPERATING SEQUENCE                       │
     ├─────────┬──────────────────────────────────────────────────┤
     │  RESET  │              FREE-RUNNING COMPUTATION             │
     │         │                                                   │
rst: ─────┐   │                                                   │
          └───┘                                                   │
              │                                                    │
x(t):   VCM + x0 ────── chaotic trajectory ──────────────────    │
y(t):   VCM + y0 ────── chaotic trajectory ──────────────────    │
z(t):   VCM + z0 ────── chaotic trajectory ──────────────────    │
     └────────────────────────────────────────────────────────────┘
```

**Sequence:**
1. Assert `reset` high — all integrator outputs clamped to initial conditions
2. Release `reset` — system evolves freely under the Lorenz dynamics
3. Monitor x(t), y(t), z(t) outputs — should show chaotic oscillation
4. After sufficient time (~50 Lorenz time units), check for butterfly attractor

## Lorenz Equation Implementation

Each equation maps to circuit blocks:

### dx/dt = σ(y − x)
```
(vyp,vyn) ──┐
             ├── [subtract] ──▶ [Gm × σ] ──▶ [∫dt] ──▶ (vxp,vxn)
(vxp,vxn) ──┘                                              │
     ▲                                                      │
     └──────────────────────────────────────────────────────┘ feedback
```

### dy/dt = x·(ρ − z) − y = ρ·x − x·z − y
```
(vxp,vxn) ──▶ [Gm × ρ] ──────────┐
                                    ├── [sum] ──▶ [∫dt] ──▶ (vyp,vyn)
(vxp,vxn) ──┐                      │                          │
             ├── [MULT] ──▶ [-1] ──┘                          │
(vzp,vzn) ──┘                      │                          │
                                    │                          │
(vyp,vyn) ──▶ [Gm × -1] ─────────┘                          │
     ▲                                                         │
     └─────────────────────────────────────────────────────────┘
```

### dz/dt = x·y − β·z
```
(vxp,vxn) ──┐
             ├── [MULT] ──────────┐
(vyp,vyn) ──┘                     ├── [sum] ──▶ [∫dt] ──▶ (vzp,vzn)
                                   │                          │
(vzp,vzn) ──▶ [Gm × -β] ────────┘                          │
     ▲                                                        │
     └────────────────────────────────────────────────────────┘
```

## Physical Constants (SKY130)

| Parameter | Value | Notes |
|-----------|-------|-------|
| VDD | 1.8V | Standard 1.8V devices |
| VCM | 0.9V | Mid-supply common mode |
| nfet_01v8 Vth (tt) | ~0.4V | Typical threshold |
| pfet_01v8 Vth (tt) | ~-0.4V | Typical threshold |
| MIM cap density | ~2 fF/µm² | For integration capacitors |
| Min L | 0.15 µm | |
| Min W (nfet) | 0.42 µm | |
| Min W (pfet) | 0.55 µm | |

## File Exchange Between Blocks

When a block agent finishes, it produces:
1. `best_parameters.csv` — optimised parameter values
2. `measurements.json` — all measured interface values
3. `design.cir` — final netlist (usable as subcircuit by downstream blocks)

The `orchestrate.py` script reads `measurements.json` from upstream blocks and writes `upstream_config.json` in downstream blocks with concrete values.
