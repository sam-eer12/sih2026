# Payload number audit — every deck claim traced to a file

For WORK_DISTRIBUTION §6.1 Day 12 (Tue 8 Sep): *"Verify that every hardware
metric matches payload simulation outputs. Zero unverified claims allowed."*

**How to use this on Day 12.** For each row, open the CSV named in column 3 and
confirm the number in column 2 appears in it. Tick the box. If a number appears
on a slide and is not in this table, either add it here with its source or
remove it from the slide.

Regenerate every source file with:

```
cd("<your path>/hardware/scilab");
exec("eye_safety.sce", -1);   exec("scan_coverage.sce", -1);
exec("link_budget.sce", -1);  exec("snr_sweep.sce", -1);
exec("range_accuracy.sce", -1); exec("rx_chain.sce", -1);
exec("power_budget.sce", -1);
```

| # | Claim on the slide | Value | Source file | Script | ☐ |
|---|---|---|---|---|---|
| 1 | Max range at ρ = 0.1, SNR ≥ 6 | 115 m | `results/link_budget.csv` | `link_budget.sce` | ☐ |
| 2 | Max range at ρ = 0.9 | 236 m | `results/link_budget.csv` | `link_budget.sce` | ☐ |
| 3 | SNR at 100 m, ρ = 0.1 | 7.4 | `results/link_budget.csv` | `link_budget.sce` | ☐ |
| 4 | Range error at 100 m, with CFD | 4.58 cm | `results/rx_chain.csv` | `rx_chain.sce` | ☐ |
| 5 | Range error at 100 m, threshold only | 32.6 cm | `results/rx_chain.csv` | `rx_chain.sce` | ☐ |
| 6 | Time walk 10–100 m, threshold | 74.2 cm | `results/rx_chain.csv` | `rx_chain.sce` | ☐ |
| 7 | Time walk 10–100 m, CFD | 1.6 cm | `results/rx_chain.csv` | `rx_chain.sce` | ☐ |
| 8 | Walk from ρ 0.1→0.9 | 30.6 cm / 0.0 cm | `results/rx_chain_walk.csv` | `rx_chain.sce` | ☐ |
| 9 | Detection rate across the sweep | 100% | console output | `rx_chain.sce` | ☐ |
| 10 | TDC quantisation contribution | 0.22 cm | `results/range_accuracy.csv` | `range_accuracy.sce` | ☐ |
| 11 | Class 1 worst-case ratio | 0.988 | `results/eye_safety.csv` | `eye_safety.sce` | ☐ |
| 12 | AEL single pulse at 905 nm | 1.070 nJ | `results/eye_safety.csv` | `eye_safety.sce` | ☐ |
| 13 | C₄ wavelength correction | 2.5704 | `results/eye_safety.csv` | `eye_safety.sce` | ☐ |
| 14 | Required angular pitch | 5.0 mrad | `results/scan_coverage.csv` | `scan_coverage.sce` | ☐ |
| 15 | Beam directions per frame | 7,350 | console output | `scan_coverage.sce` | ☐ |
| 16 | Frame rate | 6.8 Hz | console output | `scan_coverage.sce` | ☐ |
| 17 | PRF | 200 kHz | console output | `scan_coverage.sce` | ☐ |
| 18 | Points delivered | 50 kpts/s | console output | `scan_coverage.sce` | ☐ |
| 19 | Total mass | 332 g | `results/power_budget.csv` | `power_budget.sce` | ☐ |
| 20 | Total power | 6.85 W | `results/power_budget.csv` | `power_budget.sce` | ☐ |
| 21 | Mass margin vs 1.5 kg limit | 78% | `results/power_budget.csv` | `power_budget.sce` | ☐ |
| 22 | Power margin vs 25 W limit | 73% | `results/power_budget.csv` | `power_budget.sce` | ☐ |

## Claims that must NOT appear on any slide

These are estimates, not measurements. Saying them out loud as facts is the one
way this workstream loses credibility with a DRDO evaluator.

| Claim | Why not |
|---|---|
| Any per-component power, mass or cost figure | Class-level estimates, not datasheet values. See the warning at the top of `BOM.md`. Only the **totals** are safe, and only as "estimated". |
| Any specific part number as "selected" | They are *candidates*. Say "candidate" out loud. |
| Anything phrased as measured, tested, or built | Nothing was built. Every figure is simulated or analytical. |
| Eye safety as "certified" or "compliant" | It is a design-stage calculation against published limits. Certification requires an accredited lab. Say "Class 1 by calculation". |

## Known open items to disclose if asked

1. **Eye-safety margin is 1.2%** at the current 4.4 W. Derating to 3.8 W gives
   ~15% margin at a cost of ~8 m range. Deferred to the national round by
   decision, not oversight.
2. **BOM figures unverified** — 14 rows pending datasheet check.
3. **Implemented in Scilab, not MATLAB/Simulink** per PRD §16.4's authorised
   pure-code fallback. Folder is `hardware/scilab/`, not `hardware/matlab/`.
