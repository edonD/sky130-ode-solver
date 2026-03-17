# Multiplier — [STATUS: 6/6 specs passing, score 1.000]

## Spec Results (tt / 27C / 1.8V)

| Spec | Target | Measured | Margin | Pass/Fail |
|------|--------|----------|--------|-----------|
| Linearity Error | <5% | 3.30% | 1.70% margin | PASS |
| K_mult | >0.5 V^-1 | 1.165 V^-1 | +133% | PASS |
| Output Offset | <10 mV | 0.00 mV | 10 mV margin | PASS |
| Bandwidth | >5 MHz | 1393 MHz | >>200x | PASS |
| THD | <2% | 0.44% | 1.56% margin | PASS |
| Power | <300 uW | 158 uW | 142 uW margin | PASS |

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

## PVT Corner Verification

All 45 PVT corners (5 process x 3 temperatures x 3 supply voltages) pass all specs.

### Worst-Case PVT Results

| Spec | Target | Worst Case | Corner | Pass/Fail |
|------|--------|------------|--------|-----------|
| Linearity Error | <5% | 3.82% | ff/-40C/1.98V | PASS |
| K_mult | >0.5 V^-1 | 0.657 | ss/175C/1.62V | PASS |
| Output Offset | <10 mV | 0.00 mV | All corners | PASS |
| Power | <300 uW | 240 uW | sf/175C/1.62V | PASS |

### Key PVT Observations
- **K_mult variation:** 0.657 to 1.69 V^-1 (2.6x range). Downstream blocks should calibrate.
- **Linearity improves at high temperature** (larger thermal voltage = more linear tanh region).
- **Power varies** from 43 uW (ss/-40C/1.62V) to 240 uW (sf/175C/1.62V).
- **Offset stays at 0 mV** across all corners due to perfectly symmetric design.

## Design Rationale

### Topology: Resistive-Attenuated Gilbert Cell

The design uses a classic **NMOS Gilbert cell** with **resistive input attenuators** on both X and Y inputs to achieve wide-range linearity over the full +-300mV differential input range.

**Why this topology:**
- The Gilbert cell is the standard four-quadrant multiplier topology
- At +-300mV differential input (~12Vt), a bare Gilbert cell is deeply nonlinear (tanh saturation)
- Resistive attenuators reduce the signal swing at the transistor gates to stay within the linear operating region
- Source degeneration on the bottom (Y) pair provides additional linearization

**Key design choices:**
- **X attenuation:** 5:1 (4k/1k divider) reduces +-300mV to +-60mV at top quad gates
- **Y attenuation:** 2:1 (1k/1k divider) reduces +-300mV to +-150mV at bottom pair gates
- **Y degeneration:** 800 Ohm per side linearizes the bottom pair transconductance
- **Load resistors:** 14k converts output current to voltage
- **Tail current:** ~44 uA per branch (vbias_n = 0.65V)

### How it works:
1. Y input (attenuated + degenerated) drives the bottom differential pair, creating differential current proportional to Vy
2. X input (attenuated) drives the top quad, which steers current proportionally to Vx
3. Cross-coupling ensures four-quadrant operation: V_out proportional to Vx * Vy
4. Load resistors convert differential current to output voltage

## Circuit Interface

```spice
.subckt multiplier xp xn yp yn outp outn vbias_n vbias_p vcm vdd vss
```

- **xp, xn:** First differential input (X), VCM+-300mV
- **yp, yn:** Second differential input (Y), VCM+-300mV
- **outp, outn:** Differential output = K * Vx_diff * Vy_diff
- **K_mult = 1.165 V^-1** (nominal, downstream blocks use this value)

## What Was Tried and Rejected

1. **Bare Gilbert cell (no attenuation):** K=0.58 but linearity=41%. At +-300mV (12Vt), the tanh function is fully saturated.

2. **Heavy source degeneration on all transistors:** Headroom issues with 1.8V supply. Stacking tail + degeneration + bottom pair + top degeneration + load leaves insufficient voltage for saturation.

3. **Strong attenuation on both inputs (6:1 X, 4:1 Y):** Excellent linearity (0.27%) but K=0.184 — below the 0.5 target.

4. **rload=12k:** K_mult=0.575 at worst PVT — too close to 0.5 target. Increased to 14k for 31% margin.

## Known Limitations

- **Tail transistor in triode:** At the current bias point, the tail MOSFET operates near triode region. This reduces CMRR but doesn't affect differential multiplication accuracy.
- **Resistive attenuators load the inputs:** The 4k/1k and 1k/1k dividers present 5k and 2k loads to the driving stages. The upstream OTA must have low output impedance.
- **Output common mode:** Output CM is ~1.24V (not at VCM=0.9V). Downstream stages must accommodate this.
- **K_mult variation:** 2.6x range across PVT. System-level calibration may be needed.

## Design Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| tail_w/l | 80u/1u | Tail current source |
| bot_w/l | 20u/1u | Bottom pair (Y input) |
| top_w/l | 10u/0.5u | Top quad (X input) |
| rload | 14 kOhm | Load resistors |
| rdegen | 800 Ohm | Bottom pair degeneration |
| X attenuator | 4k/1k (5:1) | X input resistive divider |
| Y attenuator | 1k/1k (2:1) | Y input resistive divider |
| vbias_n | 0.65V | Tail bias (set by testbench) |

## Experiment History

| Step | Score | Specs Met | Notes |
|------|-------|-----------|-------|
| 1 | 0.25 | 2/6 | Initial Gilbert cell, model issues (X prefix needed) |
| 2 | 0.50 | 4/6 | Fixed model instantiation, bare Gilbert cell |
| 3 | 0.70 | 5/6 | Added X attenuators (6:1), K low |
| 4 | 0.90 | 5/6 | Both attenuated (6:1 X, 4:1 Y), K=0.18 too low |
| 5 | 1.00 | 6/6 | Balanced (5:1 X, 2:1 Y + degen), all specs pass |
| 6 | 1.00 | 6/6 | PVT verified, all 45 corners pass |
| 7 | 1.00 | 6/6 | Rload 12k->14k for better worst-case K margin |
