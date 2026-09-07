# Bill of Materials — AVR-25D drone LiDAR sensing payload

**Status: candidate selection, specifications NOT yet datasheet-verified.**
PRD §16 HW-6. Owner: Khanak. Companion workstream — no software module depends on this.

> **Read this before quoting any number below.** Every part in this table is a
> *candidate from a component class that exists and is appropriate*. The
> quantitative columns are **engineering estimates**, not values read off a
> datasheet. They exist so `power_budget.sce` has something to total. Before the
> design report is final, open each manufacturer datasheet, replace the estimate,
> and re-run `power_budget.sce`. Mark the row `[VERIFIED]` when you have done so.
>
> Do not present an unverified number to a judge as a datasheet figure. If asked,
> the correct answer is "that is a class-level estimate; the verified figure is in
> the datasheet and we have flagged it."

## Selection criteria, per block

For each block the question is: **which single parameter decides whether the
design works?** That parameter is why the part is on the list.

| Block | Parameter that decides it | Why it decides it |
|---|---|---|
| Laser diode | peak optical power at 905 nm, pulse width | Sets received power via the range equation, and is directly capped by the Class 1 limit (`eye_safety.sce`) |
| Laser driver | current slew rate | A 5 ns optical pulse needs a driver that can dump tens of amps in nanoseconds; GaN FETs, not silicon |
| TX collimator | exit aperture diameter | Larger aperture spreads the same energy, so **more optical power is Class 1 legal**. This is the lever that made the design close |
| RX objective | clear aperture area | Collected power scales with area; the only free way to raise SNR |
| Optical filter | passband width at 905 nm | Narrower passband cuts solar background linearly |
| Detector | responsivity × gain, and excess noise factor F | Sets signal current and the shot-noise floor |
| TIA | bandwidth and input noise density | Bandwidth must resolve a 5 ns pulse; noise sets the thermal floor |
| Comparator / CFD | propagation-delay dispersion | Dispersion adds directly to timing jitter, hence to range error |
| TDC | LSB and single-shot precision | `σ_range = c·σ_t/2`; PRD §16.1 asks for ~50 ps |
| MEMS mirror | optical scan angle, resonant frequency | Sets field of view and frame rate |
| Aggregator | I/O throughput | Must sustain 50 kpts/s over UDP (HW-7) |

## Candidate components

| # | Block | Candidate part / family | Manufacturer | Key spec to verify | Est. power (W) | Est. mass (g) | Est. cost | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | Laser diode | SPL PL90_3 / SPL S1L90A_3 family | ams-OSRAM | Peak power at 905 nm; pulse width; max duty | 1.20 (with driver) | 8 | $ | ☐ verify |
| 2 | Laser driver | EPC GaN FET + gate driver (e.g. EPC2214 class) | EPC | Rise time, peak current | incl. above | incl. | $ | ☐ verify |
| 3 | TX collimator | 50 mm aspheric / lens assembly | Thorlabs / Edmund | Clear aperture, focal length, AR coating at 905 nm | 0 | 45 | $$ | ☐ verify |
| 4 | RX objective | 50 mm plano-convex + mount | Thorlabs / Edmund | Clear aperture, transmission at 905 nm | 0 | 55 (with filter) | $$ | ☐ verify |
| 5 | Bandpass filter | 905 nm, 20 nm FWHM interference filter | Edmund / Semrock | CWL, FWHM, peak transmission | 0 | incl. above | $$ | ☐ verify |
| 6 | Detector | Si APD, 905 nm-optimised (S8664 / S12023 class) | Hamamatsu | Responsivity, M, dark current, active area | 0.35 (with HV bias) | 6 | $$ | ☐ verify |
| 7 | TIA | LMH32401 / OPA858 class | Texas Instruments | Bandwidth, transimpedance, input noise density | 0.15 | 2 | $ | ☐ verify |
| 8 | Comparator | TLV3501 / ADCMP580 class | TI / Analog Devices | Propagation delay and its dispersion | 0.25 | 2 | $ | ☐ verify |
| 9 | TDC | TDC7200 / TDC7201 (TI) or AS6501 (ams) | TI / ams | **LSB and single-shot precision** — PRD asks ~50 ps | 0.40 | 2 | $$ | ☐ verify |
| 10 | MEMS mirror | 2-axis gimballed MEMS + driver | Mirrorcle / Hamamatsu | Optical scan angle, mirror diameter, resonant freq | 1.50 | 12 | $$$ | ☐ verify |
| 11 | Aggregator | STM32H7 MCU or small FPGA + Ethernet PHY | ST / Lattice | Sustained UDP throughput | 2.00 | 15 | $$ | ☐ verify |
| 12 | Power regulation | Multi-rail DC-DC + APD HV bias | — | Efficiency, ripple on the APD bias rail | 1.00 (losses) | 25 | $ | ☐ verify |
| 13 | PCB and wiring | 4-layer, controlled impedance on the analogue front end | — | — | 0 | 40 | $ | ☐ verify |
| 14 | Enclosure | Machined or printed optical bench + drone mount | — | Stiffness, thermal path | 0 | 120 | $$ | ☐ verify |
| | **TOTAL** | | | | **6.85 W** | **332 g** | | |
| | **STATED LIMIT** | | | | **15 W** | **500 g** | | |
| | **MARGIN** | | | | **8.15 W (54%)** | **168 g (34%)** | | |

## Notes on two choices a judge will probe

**Why an APD and not a SiPM?** PRD HW-3 allows either. An APD with M≈100 gives a
linear analogue output that a CFD can time directly, which is what the whole
receiver-chain model assumes. A SiPM would give better photon sensitivity but
needs photon-counting/histogramming rather than a CFD, which is a different
timing architecture and a different simulation. Choosing the APD keeps the
design consistent with the model we actually built.

**Why 50 mm optics on a drone, when they cost 100 g?** Because the exit aperture
is the eye-safety lever. A 10 mm exit aperture caps the emitter at ~0.19 W peak;
50 mm raises the cap to ~4.4 W, a 23× increase in legal optical power. There is
no cheaper way to buy that. `eye_safety.sce` figure 1 is the defence of this line
item.
