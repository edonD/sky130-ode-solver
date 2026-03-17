# Multiplier — [STATUS: 6/6 specs passing, score 1.000]

## Spec Results (tt / 27C / 1.8V)

| Spec | Target | Measured | Margin | Pass/Fail |
|------|--------|----------|--------|-----------|
| Linearity Error | <5% | 2.48% | 2.52% margin | PASS |
| K_mult | >0.5 V^-1 | 1.124 V^-1 | +125% | PASS |
| Output Offset | <10 mV | 0.00 mV | 10 mV margin | PASS |
| Bandwidth | >5 MHz | 1403 MHz | >>200x | PASS |
| THD | <2% | 0.32% | 1.68% margin | PASS |
| Power | <300 uW | 100 uW | 200 uW margin | PASS |

## Key Plots

### 2D Linearity Surface
![Linearity Surface](plots/linearity_surface.png)

### Error Heatmap
![Error Heatmap](plots/error_heatmap.png)

### Transfer Curves
![Transfer Curves](plots/transfer_curves.png)

### Frequency Response
![Bandwidth](plots/bandwidth.png)

### Four-Quadrant Verification
![Four Quadrant](plots/four_quadrant.png)

### THD Waveform (100 kHz sine on X, DC on Y)
![THD Waveform](plots/thd_waveform.png)

### Spec Compliance Summary
![Spec Summary](plots/spec_summary.png)

## PVT Corner Verification — 45/45 Passing

All 45 PVT corners (5 process x 3 temperatures x 3 supply voltages) pass all specs.

### Worst-Case PVT Results

| Spec | Target | Worst Case | Corner | Margin | Pass/Fail |
|------|--------|------------|--------|--------|-----------|
| Linearity Error | <5% | 2.49% | tt/27C/1.8V | 2.51% | PASS |
| K_mult | >0.5 V^-1 | 0.632 | fs/175C/1.62V | +26% | PASS |
| Output Offset | <10 mV | 0.00 mV | All corners | 10 mV | PASS |
| Power | <300 uW | 231 uW | sf/175C/1.98V | 69 uW | PASS |

### PVT Sweep Plot
![PVT Sweep](plots/pvt_sweep.png)

### PVT Sensitivity Analysis
![PVT Sensitivity](plots/pvt_sensitivity.png)

### Key PVT Observations
- **45/45 corners fully passing** all tested specs
- **K_mult range:** 0.632 to 1.604 V^-1 (2.5x). Downstream calibration needed.
- **Linearity range:** 0.7% to 2.49%. Best at cold temperatures.
- **Power range:** 22 uW (fs/-40C/1.62V) to 231 uW (sf/175C/1.98V).
- **Offset: 0.00 mV** everywhere due to perfect symmetry.

## Design Rationale

### Topology: Resistive-Attenuated Gilbert Cell

A classic **NMOS Gilbert cell** with **resistive input attenuators** on both X and Y inputs achieves wide-range linearity over the full +-300mV differential input range.

**Why this topology:**
- The Gilbert cell is the standard four-quadrant multiplier
- At +-300mV (~12Vt), a bare Gilbert cell is deeply nonlinear (tanh saturation)
- Resistive attenuators keep transistor gates in the linear operating region
- Source degeneration on the bottom pair provides additional Y-path linearization

**Key design choices:**
- **X attenuation:** 5:1 (4k/1k divider) reduces +-300mV to +-60mV at top quad
- **Y attenuation:** 2.25:1 (1.25k/1k divider) reduces +-300mV to +-133mV at bottom pair
- **Y degeneration:** 600 Ohm per side linearizes bottom pair transconductance
- **Load resistors:** 14k converts output current to voltage
- **Tail transistor:** W/L = 60u/1.5u (longer channel for reduced current, better output impedance)

### Circuit Structure
1. Y input (attenuated + degenerated) drives bottom differential pair -> creates diff current proportional to Vy
2. X input (attenuated) drives top quad, steers current proportionally to Vx
3. Cross-coupling ensures four-quadrant operation: V_out = K * Vx * Vy
4. Load resistors convert differential current to output voltage

## Circuit Interface

```spice
.subckt multiplier xp xn yp yn outp outn vbias_n vbias_p vcm vdd vss
```

| Port | Description |
|------|-------------|
| xp, xn | Differential input X, VCM+-300mV |
| yp, yn | Differential input Y, VCM+-300mV |
| outp, outn | Differential output = K * Vx_diff * Vy_diff |
| vbias_n | NMOS tail bias, 0.65V nominal |
| vbias_p | PMOS bias (unused in current design) |
| vcm | Common-mode reference, 0.9V |
| vdd | Supply, 1.8V |
| vss | Ground |

**K_mult = 1.124 V^-1** (nominal, downstream blocks use this value)

## What Was Tried and Rejected

1. **Bare Gilbert cell:** linearity=41%. Tanh saturates at 12Vt.
2. **Heavy source degeneration on all transistors:** Headroom issues (1.8V supply).
3. **Strong attenuation (6:1 X, 4:1 Y):** linearity=0.27% but K=0.184 (too low).
4. **tail_w=80u, tail_l=1u:** Worst power=295uW (5uW margin). Too tight.
5. **tail_w=60u, tail_l=1u:** Better at 265uW but still tight.
6. **Final: tail_w=60u, tail_l=1.5u:** Worst power=224uW (76uW margin). Best tradeoff.

## Known Limitations

- **Tail in triode:** Reduces CMRR but doesn't affect differential multiplication.
- **Resistive loading:** 5k and 2k loads on inputs. Upstream must be low impedance.
- **Output CM ~1.3V:** Not at VCM=0.9V. Downstream must accommodate.
- **K_mult PVT variation:** 2.5x range. System calibration needed for precise Lorenz parameters.

## Design Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| tail_w/l | 60u/1.5u | Tail current source |
| bot_w/l | 20u/1u | Bottom pair (Y input) |
| top_w/l | 10u/0.5u | Top quad (X input) |
| rload | 14 kOhm | Load resistors |
| rdegen | 600 Ohm | Bottom pair degeneration |
| X attenuator | 4k/1k (5:1) | X input resistive divider |
| Y attenuator | 1.25k/1k (2.25:1) | Y input resistive divider |
| vbias_n | 0.65V | Tail bias (set by testbench) |

## Experiment History

| Step | Score | Specs Met | Notes |
|------|-------|-----------|-------|
| 1 | 0.25 | 2/6 | Initial Gilbert cell, model issues |
| 2 | 0.50 | 4/6 | Fixed X-prefix for subcircuit instances |
| 3 | 0.70 | 5/6 | Added X attenuators, K low |
| 4 | 0.90 | 5/6 | Both attenuated, K=0.18 too low |
| 5 | 1.00 | 6/6 | Balanced attenuation, all specs pass |
| 6 | 1.00 | 6/6 | PVT verified (12k Rload) |
| 7 | 1.00 | 6/6 | Rload 12k->14k for K margin |
| 8 | 1.00 | 6/6 | tail_w 80u->60u: improved power margin |
| 9 | 1.00 | 6/6 | tail_l 1u->1.5u: worst power 265->224uW, all 45 PVT pass |
| 10 | 1.00 | 6/6 | Y atten 2:1->2.25:1, rdeg 800->600: linearity 2.83->2.48% |
