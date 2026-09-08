# Design Report — AVR-25D drone LiDAR sensing payload

PRD §16 companion workstream · HW-1 … HW-8 · Owner: Khanak · Evidence: Veda

**Scope and honesty statement.** This is a *simulated and analytical* sensor
design. Nothing here was built or measured. Every figure is regenerated from a
Scilab script in `hardware/scilab/`, every number traces to `hardware/results/`,
and every input traces to a labelled line in `params.sce`. Where a value is our
assumption rather than a requirement, it is tagged `[ASM]` and defended. The
eye-safety analysis is a design-stage calculation against published limits, not
a laboratory certification.

**Toolchain note.** PRD §16.4 names MATLAB/Simulink as primary and authorises a
pure-code fallback for the receiver chain. MATLAB was not available; the work is
implemented in **Scilab**, base language only, and the receiver chain uses
exactly the documented fallback (discrete-time convolution of the pulse with the
detector impulse response, plus shot and thermal noise, CFD and TDC applied
numerically). This satisfies §16.4 rather than departing from it.

---

## 1. Architecture

```
Trigger → laser driver → 905 nm pulsed laser → TX optics → target (ρ)
                                                             ↓
   Δt ← TDC ← CFD ← TIA ← APD ← RX optics (aperture + 905 nm bandpass)
    ↓
  range = c·Δt/2 → MEMS scanner gives (r, θ, φ) → MCU/FPGA → UDP, KITTI .bin
```

Matches PRD §16.1 block for block. HW-7 (output interface) is a software task on
the aggregator and is specified, not simulated, in §8 below.

## 2. The result that shaped the design

Two independent facts, discovered in that order, determined every other number.

**2.1 PS-6's cell law is a constant angle.** `config.yaml` asks for 5 cm cells at
10 m and 50 cm cells at 100 m. Both equal **5 mrad**. The software's
variable-resolution grid is not an arbitrary schedule — it is exactly what a
scanning LiDAR produces natively at constant angular pitch. The payload and the
grid engine agree by construction, with no resampling anywhere.

**2.2 Eye safety, not the link budget, sizes the emitter.** At 905 nm with a 5 ns
pulse, the Class 1 accessible-emission limit per pulse is ~1.07 nJ, falling to
~0.43 nJ once the repetitive-pulse rule is applied. A "textbook" 75 W emitter
behind a 10 mm aperture is roughly **2000× over the limit**. The design is
therefore built *backwards* from the eye-safety ceiling, not forwards from a
desired range.

The lever that recovers performance is the **exit aperture**. Class 1 is assessed
through a 7 mm stop at 100 mm; a wider exit aperture means a smaller fraction of
the beam enters that stop. Going from 10 mm to 50 mm raises the legal peak power
from ~0.19 W to **~4.4 W**, and that is what makes 100 m reachable.

## 3. Link budget (HW-1) — `link_budget.sce`

Range equation, diffuse target larger than the spot, normal incidence:

```
P_rx = P_tx · ρ · A_rx/(π R²) · η_opt · exp(−2 α R)
```

Term-by-term at 100 m, ρ = 0.1 — *insert the printed table from `link_budget.sce`.*

| ρ | R_max at SNR ≥ 6 | SNR at 100 m |
|---|---|---|
| 0.1 | **107.2 m** | 6.68 |
| 0.5 | 184.1 m | 16.05 |
| 0.9 | 218.3 m | 21.73 |

**Requirement met.** PS-6 needs 100 m; the worst case (ρ = 0.1) reaches 107.2 m,
a 7.2 m margin. Solar background is recomputed per reflectivity, because sunlight
reflects off the same target as the laser pulse — holding it fixed at ρ = 0.1
overstates bright-target range by up to 97 m. Figures: `fig_link_power.png`, `fig_link_snr.png`.

## 4. Eye safety (HW-2) — `eye_safety.sce`

Worked against IEC 60825-1 Ed. 3 (2014), Class 1.

| Item | Value | Provenance |
|---|---|---|
| C₄ = 10^(0.002(λ−700)) | 2.5704 | quoted formula, λ = 905 nm |
| AEL_single = 7×10⁻⁴·C₄·C₆·t^0.75 | 1.070 nJ | quoted formula, t = 5 ns, C₆ = 1 |
| Pulses a fixed eye sees in T₂ = 10 s | 272 | derived — the beam is **scanned**, so a fixed eye is hit N_ACC times per frame, not PRF times per second |
| C₅ = max(N^−0.25, 0.4) | 0.400 | quoted rule |
| AEL per pulse (Rule 3) | 0.428 nJ | derived |
| Emitted pulse energy (3.8 W × 5 ns) | 19.0 nJ | design |
| Fraction into the 7 mm stop at 100 mm | 0.0192 | derived from D_TX = 50 mm |
| **Accessible energy per pulse** | **0.3651 nJ** | derived |
| **Worst of the three rules** | **0.853 — PASS, 14.7% margin** | derived |

Three caveats to state out loud rather than hide:
1. C₅ is floored at 0.4, the simplified Ed. 3 treatment. A lab would evaluate the
   full pulse-group analysis.
2. The beam is treated as a uniform top-hat across the exit aperture. A real
   diode is not uniform, and a stop centred on a hot spot would collect more.
3. Margin is thin (~1%). **Recommended action: derate the emitter to 3.5 W peak**
   for a ~20% margin, costing about 10 m of range at ρ = 0.1. Re-run
   `eye_safety.sce` and `link_budget.sce` after changing `P_PEAK` in `params.sce`.

Figure: `fig_eye_safety.png` (Class 1 power ceiling vs exit aperture).

## 5. Receiver chain (HW-3) — `rx_chain.sce`

Pure-code equivalent of the Simulink model, per PRD §16.4.

Signal path and where noise enters — *see §2 of `RUNME.md` for the beginner-level
walkthrough; reproduce it here in the final report.*

Headline results — **measured from a run of `rx_chain.sce`**, 19 ranges ×
100 shots each, ρ = 0.1, 4-pulse accumulation. Detection rate 100% at every
range for both methods.

| Quantity | Threshold only | With CFD | Ratio |
|---|---|---|---|
| Time walk over 10–100 m | 0.771 m | **0.020 m** | 38× |
| Walk from ρ = 0.1 → 0.9 at fixed range | 0.312 m | **0.000 m** | — |
| Jitter at 100 m (1σ) | 5.93 cm | 4.80 cm | 1.2× |
| **Total RMS error at 100 m** | 34.8 cm | **4.91 cm** | **7.1×** |
| **Worst total RMS, 10–100 m** | 42.8 cm | **5.28 cm** | **8.1×** |

Time walk, not noise, is what limits a leading-edge threshold: its jitter is only
5 cm at 100 m but its systematic error is 32 cm. The CFD removes the systematic
term almost entirely and is very slightly *better* on jitter too.

**Three design details the simulation found, none of them assumed.**

1. **The CFD needs an arming comparator.** Without one, its zero-crossing
   detector fires on noise before the echo arrives. The leading-edge comparator
   is the arm.
2. **The CFD constants matter more than expected.** At fraction 0.4 with a 2 ns
   delay the zero crossing lands ~0.5 ns before the pulse peak, where the
   waveform is nearly flat, and jitter rose to 32 cm at 100 m. Sweeping the two
   constants moved the crossing onto the steep part of the edge: **fraction 0.7,
   delay 4 ns**, giving 4.9 cm. Same hardware, 7× better, two component values.
3. **Accumulation is not optional.** With a single pulse per direction the
   threshold (5σ) sits *above* the echo peak at 100 m, so nothing beyond ~80 m
   is detectable and any apparent return is a timed noise spike. The 4-pulse
   accumulation in `params.sce` is what makes the design work, and `rx_chain.sce`
   now prints a warning if this condition is ever violated again.

Figures: `fig_rx_waveforms.png`, `fig_rx_measured_vs_true.png`, `fig_rx_walk.png`,
`fig_rx_jitter.png`, `fig_rx_walk_vs_rho.png`.

## 6. Range accuracy (HW-4) — `range_accuracy.sce`

Governing relation: **σ_range = c·σ_t/2**. 1 ns ↔ 15 cm; 1 cm ↔ 66.7 ps.

| Error term | 1σ at 100 m | Source |
|---|---|---|
| TDC quantisation (50 ps LSB / √12) | 0.22 cm | PRD §16.1 |
| Noise jitter (t_rise / SNR) | ~3.5 cm analytic, 4.5–5.2 cm simulated | link budget / `rx_chain.sce` |
| Time walk, threshold only | 77 cm over 10–100 m | simulated |
| Time walk, with CFD | 2.0 cm over 10–100 m | simulated |

The analytic jitter estimate (`range_accuracy.sce`, t_rise/SNR) and the simulated
value (`rx_chain.sce`) agree to within about 30%, which is the expected level of
agreement given the analytic form ignores the signal-dependence of shot noise.
Two independent methods landing in the same place is worth stating.

The TDC is **not** the limiting term. Noise jitter dominates, which means the way
to improve accuracy is more received signal (aperture, accumulation), not a
faster TDC. Figure: `fig_range_accuracy.png`.

## 7. Scan coverage (HW-5) — `scan_coverage.sce`

| Parameter | Value |
|---|---|
| Field of view | 30° × 20° |
| Angular pitch | 5.0 mrad (= PS-6 requirement, §2.1) |
| Beam directions per frame | 105 × 70 = 7,350 |
| Accumulation | 4 pulses, spaced 5 µs (≥ Ti, so not thermally grouped) |
| Frame rate | 6.8 Hz |
| PRF | 200 kHz |
| Laser duty cycle | 0.10% |
| Average optical power | 4.5 mW |
| Points delivered | 50 kpts/s |

Spot pitch equals the PS-6 cell size at every range by construction. Figures:
`fig_scan_pitch.png`, `fig_scan_density.png`, `fig_scan_pts_per_cell.png`.

## 8. Output interface (HW-7)

Specified, not simulated. The aggregator packs each return as
`(x, y, z, intensity)` float32, identical to the KITTI `.bin` layout the software
pipeline already reads, and streams it over UDP. At 50 kpts/s × 16 bytes this is
**0.8 MB/s**, comfortably inside 100 Mbit Ethernet. The payload is therefore a
drop-in source: the software stack needs no change to consume it.

## 9. Power and mass budget (HW-6) — `power_budget.sce`

Stated limits (PRD HW-6 asks for "a stated drone payload limit"; we state and
defend these): **1.5 kg and 25 W**, taken from the team plan
(`WORK_DISTRIBUTION.md` §6.1, Day 11).

| | Used | Limit | Margin |
|---|---|---|---|
| Power | 6.85 W | 25 W | 18.15 W (73%) |
| Mass | 332 g | 1500 g | 1168 g (78%) |

The design sits far inside both limits, which is worth stating plainly rather
than presenting as a triumph: the payload is optics-dominated and the optics are
small. The margin is real headroom for a larger receiver aperture if the national
round wants more range.

Per-component breakdown in `BOM.md`. **All per-component figures are class-level
estimates pending datasheet verification** — see the warning at the top of
`BOM.md`. Figures: `fig_power_mass_bars.png`, `fig_budget_margins.png`.

## 10. Reproducibility (HW-8)

Every figure in this report is produced by a script in `hardware/scilab/`, and
every script reads its inputs from `params.sce`. To regenerate the entire report's
evidence base from scratch, run the seven scripts in the order given in
`RUNME.md`. Numerical outputs land in `hardware/results/*.csv`; figures in
`hardware/figures/*.png`.

## 11. Open items

| Item | Owner | Needed by |
|---|---|---|
| Datasheet verification of all 14 BOM rows | Khanak | before deck freeze |
| Re-run `range_accuracy.sce` and confirm it still agrees with `rx_chain.sce` after the CFD retune | Khanak | before report freeze |
| Confirm the 500 g / 15 W platform limits against a named drone | Khanak + Veda | before report freeze |
| Judge Q&A entries for the payload | Veda | Q&A bank |
