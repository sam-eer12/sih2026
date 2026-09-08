# Deck numbers — the authoritative hand-off

**From:** Sameer · **To:** Veda · **Issued:** Mon 7 Sep 2026
**Source:** `model/results.json` · **Commit:** `1ccc876` · **Run:** 2026-09-07T14:13:23Z
**Rendered long form:** [`docs/RESULTS.md`](./RESULTS.md)

> This replaces every `_measured_` placeholder in the deck. Each row names the
> `results.json` path it came from, so "where did that number come from" has a
> one-line answer in front of a judge.
>
> **If a figure is not on this sheet, it is not measured, and it does not go on
> a slide.** Ask me and I will either measure it or tell you why we can't.

---

## The five numbers that carry the pitch

| # | Figure | Value | `results.json` path |
|---|---|---:|---|
| 1 | Cell reduction vs dense uniform 2.5D | **22.67×** | `memory/cell_reduction_vs_b1` |
| 2 | Overall mIoU | **0.878** | `accuracy/overall/miou` |
| 3 | Median end-to-end latency | **9.2 ms** | `latency/end_to_end/median_ms` |
| 4 | Object recall | **0.930** | `object_recall/overall/recall` |
| 5 | Hazard false positives, control scenes | **0** | `hazards/false_positives` |

Say **"22.67× fewer cells"**, not "22.67× less memory" — they are different
claims and only the first is what we measured. See the memory caution below.

## Dataset and provenance — the "is this real" slide

| Field | Value | Path |
|---|---|---|
| Dataset | SemanticKITTI, sequences 00 / 04 / 05 | `meta/dataset` |
| Scans benchmarked | **971** | 400 + 271 + 300 |
| Scans timed | **956** (15 warm-up discarded, 3 boundaries) | `latency/n_frames` |
| Points scored | **118,217,289** of 120,421,559 | `accuracy/overall/n_points_scored` |
| Perception mode | cached | `meta/perception_mode` |
| Platform | macOS 26.6.2, arm64, Python 3.14.0 | — |

FR-32 asks for ≥200 scans. We ran 956 timed. `latency/meets_fr32` is `true`.

## Accuracy

| Metric | Value | Path |
|---|---:|---|
| mIoU (pooled) | 0.878 | `accuracy/overall/miou` |
| Point accuracy | 0.934 | `accuracy/overall/accuracy` |
| DRIVABLE IoU | 0.951 | `accuracy/overall/iou/DRIVABLE` |
| NON_DRIVABLE_TERRAIN IoU | 0.874 | `accuracy/overall/iou/NON_DRIVABLE_TERRAIN` |
| DYNAMIC_OBJECT IoU | 0.871 | `accuracy/overall/iou/DYNAMIC_OBJECT` |
| STATIC_OBSTACLE IoU | 0.816 | `accuracy/overall/iou/STATIC_OBSTACLE` |

**By range** — this is the slide that earns the "adaptive" claim:

| Range | mIoU | Point acc | Object recall |
|---|---:|---:|---:|
| 0–10 m | 0.913 | 0.955 | 0.999 |
| 10–30 m | 0.842 | 0.914 | 0.952 |
| 30–60 m | 0.669 | 0.807 | 0.861 |
| 60–100 m | *unscored* | *unscored* | — |

## Latency

| Stage | Mean | Median | p95 | Max |
|---|---:|---:|---:|---:|
| Read | 2.0 | 1.9 | 2.9 | 3.2 |
| Segment | 0.0 | 0.0 | 0.0 | 0.1 |
| Score | 7.5 | 7.2 | 11.6 | 19.5 |
| **End-to-end** | **9.6** | **9.2** | **13.7** | **22.4** |

All ms, n = 956. Path: `latency/end_to_end/*`.

Quote the **median (9.2 ms)** as the headline and have **p95 = 13.7 ms** ready
for "what about the tail". Both are comfortably inside a 10 Hz budget.

## Memory

| Model | Size | Cells |
|---|---:|---:|
| B1 dense uniform 2.5D @ 5 cm | 400.0 MB | 16,000,000 |
| B3 dense uniform 3D voxel | 3200.0 MB | 3.2 B |
| B4 sparse 3D voxel hash | 1.006 MB | 83,789 |
| **AVR-25D** dense ring table | 17.64 MB | **705,771** |
| **AVR-25D** occupied only | **1.4 MB** | 48,277 |
| Peak RSS, whole process | 220.9 MB | — |

## Hazard preservation — 7 scenes

| Scene | Hazard | True | Measured | Error |
|---|---|---:|---:|---:|
| S1_flat_road | false positives | 0.00 | 0.0000 | 0.0000 |
| S2_pothole | pothole depth | 0.22 m | 0.2092 | 0.0108 |
| S3_overhang | clearance | 3.10 m | 3.0976 | 0.0024 |
| S4_curb | step height | 0.15 m | 0.1526 | 0.0026 |
| S5_crossing_truck | track speed | 8.00 m/s | 7.5660 | 0.4340 |
| S6_occluded_pothole | pothole depth | 0.22 m | 0.2248 | 0.0048 |
| S7_tunnel_curb | clearance | 3.40 m | 3.3977 | 0.0023 |
| S7_tunnel_curb | step height | 0.15 m | 0.1508 | 0.0008 |

**Largest geometric error: 0.0108 m (about 1 cm).** The 0.434 figure in
`hazards/max_error_m` is S5's **speed** error in m/s, not a distance — do not
put it on a "we measure geometry to 43 cm" slide, because that is not what it
says.

The 2D counterfactual is the strongest hazard story: a 0.22 m pothole is
**byte-identical to flat road** in a 2D occupancy grid (0.000 of its cells
blocked), and the road under the overpass is marked **impassable** (1.000
blocked). Both are in `hazards/scenes/*/counterfactual_2d`.

---

## Five things not to say

1. **Do not quote synthetic-scene accuracy** (the ~99 % point accuracies on
   S1–S7). Noise-free geometry with analytic labels. The honest reading is
   "the segmenter is not broken", not "99 % accurate". Real accuracy is the
   SemanticKITTI table above.
2. **Do not say the 60–100 m bin scores zero.** It holds 721,394 points and
   *every one is unlabelled in the ground truth*. It is unscored. Saying 0.000
   claims a measured failure that we did not measure.
3. **Do not claim we beat B4 on bytes.** B4 (1.006 MB) is smaller than our
   dense ring table (17.64 MB) and we say so on the slide. The argument is cell
   count, deterministic `offset[k] + j` access, and the proportional cut in
   per-cell downstream work.
4. **Object recall is DYNAMIC_OBJECT only.** `STATIC_OBSTACLE` has
   `n_objects: 0` in this run — the instance ground truth does not enumerate
   them. Say "dynamic object recall", not "object recall", if pressed.
5. **Do not quote BOM figures as datasheet numbers.** All 14 rows are
   class-level estimates marked `[unverified]` pending Khanak (M2).

## If a number changes

Any post-freeze code exception invalidates this sheet. The chain is:
`make bench-authoritative` → new `results.json` → re-issued `DECK_NUMBERS.md` →
Veda re-checks every slide. There is no shortcut where a slide gets a number
from anywhere else.
