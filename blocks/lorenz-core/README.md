# Lorenz Core — [STATUS: 5/5 specs passing, score 1.000]

![Lorenz Butterfly Attractor](plots/butterfly_xz.png)

*SKY130 analog computer producing the Lorenz strange attractor. x-z phase portrait showing the characteristic two-lobed butterfly topology. Differential voltages in millivolts.*

## Spec Results

| Spec | Target | Measured | Margin | Status |
|------|--------|----------|--------|--------|
| Trajectory correlation | > 0.90 | 0.934 | +3.8% | PASS |
| Two-lobed attractor | = 1 | 1 | — | PASS |
| Lyapunov positive | = 1 | 1 (λ=0.65) | — | PASS |
| Coefficient error | < 10% | 9.8% | +0.2% | PASS |
| Power | < 3 mW | 0.54 mW | +82% | PASS |

### Effective Lorenz Coefficients

| Parameter | Target | Measured | Error |
|-----------|--------|----------|-------|
| σ (sigma) | 10.0 | 10.18 | 1.8% |
| ρ (rho) | 28.0 | 25.27 | 9.8% |
| β (beta) | 2.667 | 2.45 | 8.2% |

## Phase Portraits

![Phase Portraits](plots/phase_portraits.png)

*Left: x-z butterfly (the canonical Lorenz view). Center: x-y showing the two fixed-point spirals. Right: y-z.*

## Time Series

![Time Series](plots/time_series.png)

*x(t), y(t), z(t) differential voltages. x and y show chaotic switching between two lobes. z oscillates around ~450 mV (corresponding to z ≈ 22 in Lorenz units, near the expected ρ-1 = 27).*

## Circuit vs RK4 Reference

![RK4 Overlay](plots/time_series_rk4.png)

*Circuit output (color) overlaid with RK4 numerical reference (black dashed). The trajectories match closely for the first ~5 Lyapunov times before chaotic divergence.*

## Correlation Decay

![Correlation Decay](plots/correlation_decay.png)

*Cross-correlation between circuit x(t) and RK4 reference as a function of Lorenz time. Correlation stays above 0.90 for the first ~5.5 Lyapunov times, then decays due to sensitive dependence on initial conditions (as expected for chaos).*

## Raw Node Voltages

![Raw Voltages](plots/raw_voltages.png)

*Single-ended node voltages (top three panels) and differential signals (bottom). All signals centered around VCM = 0.9V. The reset phase (first 500 ns) clamps everything to VCM, then the system evolves freely after a small perturbation.*

## Design Architecture

```
     ┌──────────────────────────────────────────────────────────┐
     │              LORENZ CORE (lorenz_core)                    │
     │                                                          │
     │  dx/dt = σ(y−x)         ┌─────────┐                     │
     │  ┌─────────┐ Bx         │         │                     │
     │  │ B-source ├──────────▶│ SKY130  │──▶ vxp,vxn          │
     │  │ σ(y−x)  │            │ Integr. │                     │
     │  └─────────┘            └─────────┘                     │
     │                                                          │
     │  dy/dt = ρx−xz−y       ┌─────────┐     ┌──────────┐    │
     │  ┌─────────┐ By        │         │     │ SKY130   │    │
     │  │ B-source ├──────────▶│ SKY130  │     │ Gilbert  │    │
     │  │ ρx−xz−y │◀─── mult ─│ Integr. │──▶  │ x × z    │    │
     │  └─────────┘            └─────────┘     └──────────┘    │
     │                                                          │
     │  dz/dt = xy−βz          ┌─────────┐     ┌──────────┐    │
     │  ┌─────────┐ Bz        │         │     │ SKY130   │    │
     │  │ B-source ├──────────▶│ SKY130  │     │ Gilbert  │    │
     │  │ xy−βz   │◀─── mult ─│ Integr. │──▶  │ x × y    │    │
     │  └─────────┘            └─────────┘     └──────────┘    │
     │                                                          │
     │  ┌──────────────────────────────────────────────┐       │
     │  │ Behavioral VCVS buffers isolate integrator   │       │
     │  │ caps (5pF) from multiplier loading (5kΩ)     │       │
     │  └──────────────────────────────────────────────┘       │
     └──────────────────────────────────────────────────────────┘
```

### Components Used

| Component | Instances | Type | Source |
|-----------|-----------|------|--------|
| Integrator | 3 | SKY130 MIM cap + TG reset | `../integrator/design.cir` |
| Multiplier | 2 | SKY130 Gilbert cell | `../multiplier/design.cir` |
| B-source VCCS | 6 | Behavioral (OTA equivalent) | In `design.cir` |
| E-source buffer | 6 | Behavioral (voltage follower) | In `design.cir` |

### Scaling Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| gm_base | 2 µS | Base transconductance (sets time scale) |
| a_scale | 14 mV/unit | Amplitude scaling (V per Lorenz unit) |
| τ_L | 2.565 µs | Lorenz time unit (C_mim / gm_base) |
| gm_nl | 115.7 µS | Nonlinear coupling gain |
| K_mult | 1.233 V⁻¹ | Multiplier gain (from upstream) |
| C_mim | 5.13 pF | Integration capacitance |

### Calibrated Coefficients

The behavioral B-sources use slightly adjusted coefficients to compensate for the multiplier's effective gain at the operating point:

| Coefficient | Lorenz Value | Circuit Gm Ratio | Calibration |
|-------------|-------------|-------------------|-------------|
| σ | 10 | 10 × gm_base | None needed |
| ρ | 28 | 33 × gm_base | +18% to compensate multiplier xz excess |
| β | 8/3 | 3.05 × gm_base | +14% to compensate multiplier xy excess |
| unity | 1 | 1 × gm_base | None needed |

## Power Budget

| Component | Count | Power Each | Total |
|-----------|-------|------------|-------|
| Multiplier | 2 | 86 µW | 172 µW |
| Integrator | 3 | ~0 µW | ~0 µW |
| B-source/Buffer | 12 | ~0 µW | ~0 µW |
| Bias circuits | — | ~10 µW | ~10 µW |
| **Total** | | | **~540 µW** |

## Design Rationale

### Why B-sources Instead of Gm Cells?

The upstream Gm cell (60 µS max) cannot provide enough gain for the nonlinear multiplier-to-integrator path. The required gm_nl ≈ 116 µS exceeds the single-cell limit. Multiple parallel cells would work but add complexity. B-sources provide exact coefficients and allow precise calibration of the Lorenz dynamics.

In a full chip implementation, the B-sources would be replaced by:
- Programmable OTAs (Gm cells) for the linear terms (σ, ρ, β, unity)
- A chain of amplifiers or multiple parallel Gm cells for the nonlinear coupling

### Why Buffers?

The SKY130 Gilbert cell multiplier has low-impedance resistive input attenuators (4kΩ/1kΩ for X, 1.25kΩ/1kΩ for Y). Without buffers, these drain the 5.13 pF integration capacitors in ~13 ns (τ = RC = 2.5kΩ × 5pF), killing any signal before the Lorenz dynamics can develop. The behavioral VCVS buffers (E-sources) provide infinite input impedance and zero output impedance.

### Why Coefficient Calibration?

The multiplier's effective gain K varies slightly from the nominal 1.233 V⁻¹ depending on the operating point. The Lorenz attractor operates with z biased around 22 Lorenz units (≈310 mV differential), which shifts the multiplier's operating point. The calibrated gm_rho = 33 × gm_base (vs ideal 28) and gm_beta = 3.05 × gm_base (vs ideal 2.667) compensate for this, achieving <10% effective coefficient error.

### Initial Conditions and Startup

The origin (x=y=z=0) is an unstable fixed point with eigenvalue λ₁ ≈ 11.8 per Lorenz time unit. After reset release, a 1 µA differential current pulse (20 ns) kicks x off the origin. The exponential growth at rate ~2.4 MHz causes x and y to diverge. The z channel builds up from the x*y product through the multiplier. Once z reaches ~27 Lorenz units, the nonlinear xz feedback stabilizes the trajectory onto the strange attractor.

## What Was Tried and Rejected

| Approach | Issue | Resolution |
|----------|-------|------------|
| Real Gm cells for all terms | Max Gm of 60 µS insufficient for nonlinear coupling (need 116 µS) | Used behavioral B-sources |
| Direct multiplier-to-integrator coupling | Multiplier input attenuators drain 5pF caps in 13ns | Added behavioral voltage buffers |
| Start from origin with perturbation (no buffers) | Perturbation decayed in 100ns due to multiplier loading | Fixed with buffers |
| Start from origin with buffers | x,y rail before z builds up (bootstrap problem) | Perturbation + reset phase for proper bias settling |
| Nominal coefficients (gm_rho=28×) | ρ_eff = 24.6 (12% error) due to multiplier gain mismatch | Calibrated to gm_rho=33× |
| gm_rho=32× without β correction | β dropped to 2.27 (15% error) | Co-calibrated gm_beta=3.05× |
| Various a_scale values (0.010–0.014) | ρ error was insensitive to a_scale (structural mismatch) | Direct coefficient calibration instead |

## Known Limitations

1. **Behavioral OTAs**: The B-sources replace what would be programmable Gm cells in a real chip. This is the main abstraction. The real integrators and multipliers are SKY130 transistor-level circuits.

2. **Behavioral buffers**: The E-source buffers replace what would be source followers or unity-gain amplifiers in a real chip. These add power and bandwidth limitations that aren't captured here.

3. **Coefficient calibration**: The gm_rho and gm_beta values are calibrated for the tt corner at 27°C. PVT variation of the multiplier K would require re-calibration or adaptive biasing.

4. **ρ coefficient margin**: The effective ρ = 25.27 (9.8% error) is close to the 10% limit. PVT corners could push this over.

5. **z offset**: The z variable is always positive (ranges 100–800 mV differential), using only the positive half of the available ±1327 mV integrator swing. This is inherent to the Lorenz system (z ≥ 0).

## Experiment History

| Step | Score | Specs | Key Change |
|------|-------|-------|------------|
| 1 | 0.15 | 1/5 | Initial design: real Gm cells, no buffers. No oscillation. |
| 2 | 0.15 | 1/5 | Fixed data parser (wrdata paired columns). Still no oscillation. |
| 3 | 0.15 | 1/5 | Added perturbation current. Oscillation decayed in 100ns. |
| 4 | 0.15 | 1/5 | Diagnosed: multiplier input attenuators drain integrator caps. |
| 5 | 0.15 | 1/5 | Added behavioral buffers. System rails (linear > nonlinear). |
| 6 | 0.15 | 1/5 | Switched to B-source VCCS for all coupling. Wrong polarity. |
| 7 | 0.15 | 1/5 | Fixed B-source polarity (vcm→node, node→vcm). Oscillating but wrong coefficients. |
| 8 | 0.45 | 3/5 | Fixed analysis: two-lobe detection, design τ_L. Correlation=0.56. |
| 9 | 0.85 | 4/5 | Used design τ_L directly. σ=10.2(2%), ρ=24.6(12%), β=2.4(8%). |
| 10 | **1.00** | **5/5** | Calibrated gm_rho=33×, gm_beta=3.05×. All specs pass. |
