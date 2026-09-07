# Khanak — drone LiDAR payload, models and analysis

Newest entry at the top. Format and rules: [`README.md`](./README.md).

## Day 7 · Thursday 03 Sep 2026

**Landed.** The whole payload analysis track, `hardware/scilab/`. Eight Scilab
scripts: `params.sce` (single source of truth, every constant tagged
PRD/CFG/DER/ASM/CND), `eye_safety.sce`, `scan_coverage.sce`, `link_budget.sce`,
`snr_sweep.sce`, `range_accuracy.sce`, `rx_chain.sce`, `power_budget.sce`. All
seven analysis scripts run clean in one pass and write **18 PNGs** to
`hardware/figures/` and **7 CSVs** to `hardware/results/`. Plus
`hardware/docs/DESIGN_REPORT.md` (skeleton, real numbers filled in) and
`hardware/docs/BOM.md`. All committed on branch `khanak_hardware`.

Headline results — all simulated, none measured:

| Metric | Result | Requirement |
|---|---|---|
| Max range (rho=0.1, SNR≥6) | **116 m** | 100 m (`config.yaml r_max`) |
| Range error at 100 m (CFD) | **4.58 cm** | — |
| Range error at 100 m (threshold-only) | 32.6 cm | — |
| Eye safety (905 nm, 4.4 W peak, 5 ns, 200 kHz) | **Class 1** | IEC 60825-1 HW-2 |
| Mass | **332 g** | 500 g budget |
| Power | **6.85 W** | 15 W budget |

**Acceptance.**

HW-1 through HW-8 all have a runnable script and a figure. HW-8 (every figure
reproducible from its script) is met: seven `exec` calls in order regenerate the
entire evidence base from `params.sce`.

**NOT met:** every per-component power/mass/cost figure in `BOM.md` is a
class-level estimate, not a datasheet value. They are flagged `[unverified]` in
the file. Do not quote them to a judge as datasheet numbers — see open items
below.

**Blocked / blocking.** Blocking nobody — PRD §16 is a companion workstream with
no runtime dependency on the software. Veda needs the slide text and Q&A table,
both at the bottom of `hardware/RUNME.md`.

**Decisions and surprises.**

1. **PS-6's cell law is a constant angle.** `config.yaml` asks for 5 cm cells at
   10 m and 50 cm at 100 m: `0.05/10 = 0.005 rad`; `0.50/100 = 0.005 rad`. Both
   are exactly 5 mrad. The variable-resolution grid is what a scanning LiDAR
   produces natively at constant angular pitch — the sensor and the grid engine
   agree by construction with no resampling. This set the entire scan geometry.

2. **Eye safety sizes the emitter, not the link budget.** Class 1 at 905 nm with
   a 5 ns pulse allows ~1.07 nJ/pulse, ~0.43 nJ after the repetitive-pulse
   reduction rule. A textbook 75 W emitter behind a 10 mm aperture is ~2000×
   over. The lever is the exit aperture: Class 1 is assessed through a 7 mm stop
   at 100 mm, so widening the exit from 10 mm to **50 mm** raises the legal peak
   power from 0.19 W to **4.4 W**. That is why the payload carries 50 mm optics
   costing 100 g. Everything else was designed backwards from that ceiling.

3. **The CFD constants are not a detail.** At fraction 0.4 / 2 ns delay the zero
   crossing lands ~0.5 ns before the pulse peak where the waveform is nearly
   flat, and noise there gave **32 cm error at 100 m**. Swept both constants;
   fraction **0.7 / 4 ns** puts the crossing on the steep edge and gives
   **4.58 cm** — same hardware, 7× better, two passive component values. Anyone
   rebuilding from the report would otherwise rediscover this the hard way.

4. **Accumulation is load-bearing.** First version of `rx_chain.sce` fired one
   pulse per measurement while the rest of the design assumed four. At 100 m
   that put the 5-sigma threshold (1.39 mV) **above** the echo peak (1.04 mV),
   so everything past ~80 m was the simulation timing a noise spike. Fixed —
   `rx_chain.sce` now prints a warning if the condition recurs.

5. **Divergence from `IMPLEMENTATION_PLAN.md §4` — raised at checkpoint.** The
   repo layout specifies `hardware/matlab/` and `hardware/simulink/`. MATLAB and
   Simulink are not available, so the work is in `hardware/scilab/`, base-language
   Scilab only. PRD §16.4 explicitly authorises a pure-code fallback for the
   receiver chain (discrete-time convolution of the pulse with the detector
   impulse response, plus shot and thermal noise, CFD and TDC applied
   numerically) — `rx_chain.sce` implements exactly that. This satisfies §16.4
   rather than departing from it, but the folder name in the plan is now wrong
   and should be updated.

**Open items.**

- Eye-safety margin is thin: worst-case ratio ~0.99 (~1% pass). Considering
  derating `P_PEAK` from 4.4 W → 3.5 W for ~20% margin at a cost of ~10 m range.
  Decision needed before the deck numbers are frozen (Day 12).
- Datasheet verification of all 14 BOM rows is outstanding.

<!-- No entries yet. Copy the template from README.md and add one above this line. -->
