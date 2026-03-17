# Multiplier — [STATUS: 6/6 specs passing, score 1.000]

## Spec Results (tt / 27C / 1.8V)

| Spec | Target | Measured | Margin | Pass/Fail |
|------|--------|----------|--------|-----------|
| Linearity Error | <5% | 2.28% | 2.72% margin | PASS |
| K_mult | >0.5 V^-1 | 1.103 V^-1 | +121% | PASS |
| Output Offset | <10 mV | 0.00 mV | 10 mV margin | PASS |
| Bandwidth | >5 MHz | 1405 MHz | >>200x | PASS |
| THD | <2% | 0.28% | 1.72% margin | PASS |
| Power | <300 uW | 86 uW | 214 uW margin | PASS |

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

### THD Waveform + Spectrum
![THD Waveform](plots/thd_waveform.png)

### Spec Compliance Summary
![Spec Summary](plots/spec_summary.png)

## PVT Corner Verification — 45/45 Passing

### Worst-Case PVT Results

| Spec | Target | Worst Case | Corner | Margin | Pass/Fail |
|------|--------|------------|--------|--------|-----------|
| Linearity Error | <5% | 3.00% | fs/-40C/1.98V | 2.00% | PASS |
| K_mult | >0.5 V^-1 | 0.629 | fs/175C/1.62V | +26% | PASS |
| Output Offset | <10 mV | 0.00 mV | All corners | 10 mV | PASS |
| Power | <300 uW | 222 uW | sf/175C/1.98V | 78 uW | PASS |

### PVT Sweep Plot
![PVT Sweep](plots/pvt_sweep.png)

### PVT Sensitivity Analysis
![PVT Sensitivity](plots/pvt_sensitivity.png)

### Key PVT Observations
- **45/45 corners fully passing** all specs
- **K_mult range:** 0.629 to 1.543 V^-1 (2.5x). Downstream calibration needed.
- **Linearity range:** 0.6% to 3.0%. Best at cold temperatures.
- **Power range:** 17 uW (fs/-40C/1.62V) to 222 uW (sf/175C/1.98V).
- **Offset: 0.00 mV** everywhere due to perfect symmetry.

## Design Rationale

### Topology: Resistive-Attenuated Gilbert Cell

A classic **NMOS Gilbert cell** with **resistive input attenuators** on both X and Y inputs. The attenuators keep the transistor signals in their linear operating region, achieving <3% linearity over the full +-300mV input range.

**Key design choices:**
- **X attenuation:** 5:1 (4k/1k divider) reduces +-300mV to +-60mV at top quad
- **Y attenuation:** 2.25:1 (1.25k/1k divider) reduces +-300mV to +-133mV at bottom pair
- **Y degeneration:** 600 Ohm per side linearizes bottom pair transconductance
- **Load resistors:** 14k converts output current to voltage
- **Tail transistor:** W/L = 60u/1.5u
- **Bias:** vbias_n = 0.64V (optimal for linearity-power tradeoff)

### How it works:
1. Y input (attenuated + degenerated) -> bottom diff pair -> diff current proportional to Vy
2. X input (attenuated) -> top quad steers current proportionally to Vx
3. Cross-coupling: V_out = K * Vx * Vy (four-quadrant multiplication)
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
| vbias_n | NMOS tail bias, 0.64V nominal |
| vbias_p | PMOS bias (unused) |
| vcm | Common-mode reference, 0.9V |
| vdd | Supply, 1.8V |
| vss | Ground |

**K_mult = 1.103 V^-1** (nominal, downstream blocks use this value)

## What Was Tried and Rejected

1. **Bare Gilbert cell:** linearity=41%. Tanh saturates at 12Vt.
2. **Heavy source degeneration on all transistors:** Headroom issues (1.8V).
3. **Strong attenuation (6:1 X, 4:1 Y):** linearity=0.27% but K=0.184 (too low).
4. **Top quad source degeneration:** Worsened linearity instead of improving it.
5. **vbias_n=0.62V:** Excellent linearity (1.6%) but fails at fs/-40C (K<0.5).
6. **vbias_n=0.65V:** More margin but higher power and worse linearity.

## Known Limitations

- **Tail in triode:** Reduces CMRR but doesn't affect differential multiplication.
- **Resistive loading:** 5k and 2k loads on inputs.
- **Output CM ~1.4V:** Not at VCM=0.9V. Downstream must accommodate.
- **K_mult PVT variation:** 2.5x range. System calibration needed.

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
| vbias_n | 0.64V | Tail bias |

## Experiment History

| Step | Score | Specs Met | Notes |
|------|-------|-----------|-------|
| 1-4 | 0.25-0.90 | 2-5/6 | Initial design iterations |
| 5 | 1.00 | 6/6 | First all-pass: balanced attenuation |
| 6-7 | 1.00 | 6/6 | PVT verified, Rload 12k->14k |
| 8 | 1.00 | 6/6 | tail_w 80u->60u: better power |
| 9 | 1.00 | 6/6 | tail_l 1u->1.5u: all margins improved |
| 10 | 1.00 | 6/6 | Y atten 2.25:1, rdeg 600: linearity 2.48% |
| 11 | 1.00 | 6/6 | vbias_n 0.65->0.64: lin 2.28%, THD 0.28%, pwr 86uW |
