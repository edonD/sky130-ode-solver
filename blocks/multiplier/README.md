# Multiplier — [STATUS: 6/6 specs passing, score 1.000]

## Spec Results

| Spec | Target | Measured | Margin | Pass/Fail |
|------|--------|----------|--------|-----------|
| Linearity Error | <5% | 3.22% | 1.78% margin | PASS |
| K_mult | >0.5 V⁻¹ | 1.018 V⁻¹ | +103% | PASS |
| Output Offset | <10 mV | 0.00 mV | 10 mV margin | PASS |
| Bandwidth | >5 MHz | 826 MHz | >>100x | PASS |
| THD | <2% | 0.42% | 1.58% margin | PASS |
| Power | <300 uW | 158 uW | 142 uW margin | PASS |

## Key Plots

### 2D Linearity Surface
![Linearity Surface](plots/linearity_surface.png)

### Error Heatmap
![Error Heatmap](plots/error_heatmap.png)

### Transfer Curves
![Transfer Curves](plots/transfer_curves.png)

### Spec Compliance Summary
![Spec Summary](plots/spec_summary.png)

## Design Rationale

### Topology: Resistive-Attenuated Gilbert Cell

The design uses a classic **NMOS Gilbert cell** with **resistive input attenuators** on both X and Y inputs to achieve wide-range linearity over the full +-300mV differential input range.

**Why this topology:**
- The Gilbert cell is the standard four-quadrant multiplier topology
- At +-300mV differential input (~12Vt), a bare Gilbert cell is deeply nonlinear (tanh saturation)
- Resistive attenuators reduce the signal swing at the transistor gates to stay within the linear operating region
- Source degeneration on the bottom (Y) pair provides additional linearization

**Key design choices:**
- **X attenuation:** 5:1 (4k/1k divider) — reduces +-300mV to +-60mV at top quad gates
- **Y attenuation:** 2:1 (1k/1k divider) — reduces +-300mV to +-150mV at bottom pair gates
- **Y degeneration:** 800 Ohm per side — linearizes the bottom pair transconductance
- **Load resistors:** 12k — converts output current to voltage
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
- **K_mult = 1.018 V^-1** (downstream blocks use this value)

## What Was Tried and Rejected

1. **Bare Gilbert cell (no attenuation):** K=0.58 but linearity=41%. At +-300mV (12Vt), the tanh function is fully saturated.

2. **Heavy source degeneration on all transistors:** Headroom issues with 1.8V supply. Stacking tail + degeneration + bottom pair + top degeneration + load leaves insufficient voltage for saturation.

3. **Top quad source degeneration:** Added individual source resistors. Improved linearity but still limited by headroom.

4. **Strong attenuation on both inputs (6:1 X, 4:1 Y):** Excellent linearity (0.27%) but K=0.184 — below the 0.5 target.

5. **Final balanced design (5:1 X, 2:1 Y + degeneration):** Best tradeoff with K=1.02 and linearity=3.2%.

## Known Limitations

- **Tail transistor in triode:** At the current bias point, the tail MOSFET operates near triode region. This reduces CMRR but doesn't affect differential multiplication.
- **Resistive attenuators load the inputs:** The 4k/1k and 1k/1k dividers present 5k and 2k loads to the driving stages.
- **Output common mode:** Output CM is ~1.27V (not at VCM=0.9V). Downstream stages must accommodate this.
- **PVT verification pending:** Current results are tt corner, 27C, 1.8V only.

## Design Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| tail_w/l | 80u/1u | Tail current source |
| bot_w/l | 20u/1u | Bottom pair (Y input) |
| top_w/l | 10u/0.5u | Top quad (X input) |
| rload | 12 kOhm | Load resistors |
| rdegen | 800 Ohm | Bottom pair degeneration |
| X attenuator | 4k/1k (5:1) | X input resistive divider |
| Y attenuator | 1k/1k (2:1) | Y input resistive divider |

## Experiment History

| Step | Score | Specs Met | Notes |
|------|-------|-----------|-------|
| 1 | 0.25 | 2/6 | Initial Gilbert cell, model issues (X prefix needed) |
| 2 | 0.50 | 4/6 | Fixed model instantiation, bare Gilbert cell |
| 3 | 0.70 | 5/6 | Added X attenuators (6:1), K low |
| 4 | 0.90 | 5/6 | Both attenuated (6:1 X, 4:1 Y), K=0.18 too low |
| 5 | 1.00 | 6/6 | Balanced (5:1 X, 2:1 Y + degen), all specs pass |
