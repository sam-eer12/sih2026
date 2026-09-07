# START HERE — payload workstream catch-up pack

Owner: Khanak. Covers PRD §16 HW-1 … HW-8. Nothing here needs MATLAB or Simulink.

## What you have

```
hardware/
├── RUNME.md                  ← this file
├── scilab/
│   ├── params.sce            ← EVERY number lives here. Read this first.
│   ├── eye_safety.sce        HW-2   run 1st — it caps the laser power
│   ├── scan_coverage.sce     HW-5   run 2nd — it sets the PRF
│   ├── link_budget.sce       HW-1   run 3rd
│   ├── snr_sweep.sce         HW-1   run 4th
│   ├── range_accuracy.sce    HW-4   run 5th
│   ├── rx_chain.sce          HW-3   run 6th (slow, ~1 min)
│   └── power_budget.sce      HW-6   run 7th
├── docs/
│   ├── DESIGN_REPORT.md      HW-8 — skeleton with real numbers filled in
│   └── BOM.md                candidate parts, all flagged unverified
├── figures/                  (created on first run)
└── results/                  (created on first run)
```

**The dependency chain, in one sentence:** eye safety caps the laser power → the
laser power plus the receiver aperture set the range → the PS-6 cell law sets the
angular pitch → the pitch plus the field of view set the PRF → everything else
follows. That is why the run order is what it is.

## How to run everything (10 minutes)

1. Open Scilab (the GUI, not `scilab-cli` — you want the figure windows).
2. In the Scilab console:

```
cd("C:/path/to/hardware/scilab");
exec("eye_safety.sce", -1);
exec("scan_coverage.sce", -1);
exec("link_budget.sce", -1);
exec("snr_sweep.sce", -1);
exec("range_accuracy.sce", -1);
exec("rx_chain.sce", -1);
exec("power_budget.sce", -1);
```

3. Check that `figures/` has 18 PNGs and `results/` has 7 CSVs.

That is HW-8 satisfied: every figure regenerated from its script in one pass.

## The receiver chain, explained from zero

Light travels **30 cm per nanosecond**. Out and back, so **1 ns of measured time
= 15 cm of range**. Everything else is engineering around that one fact.

| Block | What it does | In | Out |
|---|---|---|---|
| Laser | fires a 5 ns flash of 905 nm light | trigger | optical power (W) |
| Target + air | scatters a little back, air absorbs some | W out | nanowatts back |
| APD | converts light to current and multiplies it ~100× | watts | amps |
| TIA | converts that current to a voltage | amps | volts |
| Threshold / CFD | decides *the instant* the echo arrived | voltage | one time stamp |
| TDC | a stopwatch that reports the number digitally | start/stop | a number in 50 ps steps |

**True range** = where the target actually is. **Measured range** = what the
electronics reports. The gap between them is the entire subject.

**Noise comes from two places.** *Shot noise*: photons and electrons are
countable, so counts wobble; it gets **bigger** on top of a strong echo.
*Thermal noise*: charge jiggling in a warm amplifier; constant, present in the
dark.

**Why two timing methods.** A **fixed threshold** fires when the voltage crosses
a level. A tall nearby echo crosses it early on its rising edge; a weak far echo
crosses the same level late. Same distance, different reported time — that is
**time walk**, and it is systematic, so averaging cannot remove it. A **CFD**
fires at a fixed fraction of the echo's *own* height (multiply by 0.4, subtract a
copy delayed 2 ns, find the zero crossing), so the firing point does not move
with amplitude and the walk disappears.

## Sanity checks — physics, not simulation output

| Check | Correct answer |
|---|---|
| 10 m round trip | 66.71 ns |
| 50 m round trip | 333.56 ns |
| 100 m round trip | 667.13 ns |
| 1 cm of range | 66.7 ps |
| 1 ns of timing | 15.0 cm |
| 50 ps TDC LSB | 7.5 mm |

`rx_chain.sce` prints all six. If the simulation disagrees with them, the
simulation is wrong.

Three things must also be true after a run:
1. `fig_rx_measured_vs_true.png` — both curves sit on the dashed ideal line.
2. `fig_rx_walk_vs_rho.png` — the CFD curve is flat at zero, the threshold curve
   slopes. That is the walk demonstration.
3. Detection rate 100% at every range in the console output.

## One-slide payload summary (give this to Veda)

> **We also designed the sensor.**
> A 905 nm direct time-of-flight LiDAR payload: 4.4 W peak, 5 ns pulses, 200 kHz,
> APD + 200 MHz TIA + constant-fraction discriminator + 50 ps TDC, MEMS-scanned
> 30°×20° at 5 mrad, 6.8 Hz, 50 kpts/s over UDP in KITTI format.
> **116 m** at 10% reflectivity. **±8 cm** range error at 100 m. **Class 1
> eye-safe.** **332 g, 6.9 W** — inside a 500 g / 15 W drone budget.
> Two findings: PS-6's variable-resolution cell law *is* a constant 5 mrad
> angular pitch, so the sensor and the grid agree by construction; and eye
> safety, not the link budget, is what sizes the emitter.
> Simulated and analytical. Seven Scilab scripts, every figure reproducible.

## Likely judge questions

| Question | Short answer |
|---|---|
| "Did you build this?" | No. It is a simulated and analytical design. Every figure regenerates from a script; nothing is measured. We say so on the slide. |
| "Is it eye-safe?" | Class 1 by calculation against IEC 60825-1 Ed. 3, worked through in the report. Not a lab certification. The exit aperture is what makes it close, and margin is currently thin — we flag that. |
| "Why 905 nm and not 1550 nm?" | 1550 nm allows far more power under Class 1, but needs InGaAs detectors, which are much more expensive and heavier. 905 nm with silicon is the right point for a student drone payload. |
| "Why an APD and not a SiPM?" | An APD gives a linear analogue pulse a CFD can time directly. A SiPM needs photon counting, a different timing architecture. We chose the one our model actually represents. |
| "Why is the CFD worth the complexity?" | It removes ~68 cm of systematic walk over 10–100 m. It costs about 2× in jitter. Net gain ~3.4× in total error. |
| "What limits your accuracy?" | Noise jitter, not the TDC. The 50 ps TDC contributes 2 mm; jitter contributes ~3.5 cm at 100 m. So more aperture or more accumulation, not a faster TDC. |
| "How does this connect to your software?" | It doesn't have to — PRD §16 makes it a companion workstream with no runtime dependency. But it outputs the same KITTI `.bin` layout the pipeline already reads, so it is a drop-in source. |
| "Are your component numbers real?" | The parts are real families. The power/mass/cost figures are class-level estimates, flagged as unverified in `BOM.md`. We did not want to present estimates as datasheet values. |

## Your remaining work, in priority order

| Priority | Task | Why it is this priority |
|---|---|---|
| 1 | Run all seven scripts, confirm they execute | Nothing else is real until they do |
| 2 | Write today's `khanak.md` log entry | Team rule; the log is worthless reconstructed later |
| 3 | Decide the P_PEAK derating (4.4 → 3.5 W) | Eye-safety margin is ~1%; a judge will find it |
| 4 | Verify the 14 BOM rows against datasheets | The only fabrication risk in the pack |
| 5 | Fill the *insert here* gaps in `DESIGN_REPORT.md` | HW-8 |
| 6 | Hand the slide text and Q&A table to Veda | She owns the deck |
