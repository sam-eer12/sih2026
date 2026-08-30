# Sameer — perception, benchmarking, synthetic scenes, integration lead

Newest entry at the top. Format and rules: [`README.md`](./README.md).

---

## Days 1–3 · Fri 28 – Sun 30 Aug 2026

Landed as one branch, `sameer/perception-synth`, rather than three daily commits.

**Landed.** The `avr25d` package now exists under `model/`, installed editable
into the shared `backend/.venv`.

| Module | What it does | Spec |
|---|---|---|
| `avr25d/config.yaml` | Every tunable, with units and a one-line reason each | NFR-7 |
| `avr25d/config.py` | Attribute-addressable loader; a missing key raises rather than returning `None` | — |
| `avr25d/io/kitti.py` | `.bin` / `.label` readers and writers, `Scan`, `KittiSequence` | — |
| `avr25d/perception/labelmap.py` | Raw-id → 5-class and learning-id → 5-class tables, `moving-*` kept separately | PRD §6.1 |
| `avr25d/perception/geometric_seg.py` | RANSAC ground plane + k-NN-graph clustering + bbox gate | FR-5 |
| `avr25d/synth/` | Ray-caster, CSV scene loader, KITTI exporter, scenes `S1`–`S5` | PRD §9.3 |
| `tests/` | 77 tests, `pytest -q` green | §9 |

**Acceptance.**

- Day 1 — *"RANSAC ground fit working on a synthetic plane."* Met.
- Day 2 — *"5-class labels on a real KITTI scan."* **Not met — see blockers.**
  Met on synthetic scans instead, which exercise the identical code path.
- Day 3 — *"`S1`–`S3` load in the pipeline."* Met, and `S4`/`S5` landed early.
  *"End-to-end: scan → labels → grid → browser"* is blocked on `core/`.

Measured, macOS arm64, single core, 5 runs, median:

| Scene | points | median ms | point acc | `DRIVABLE` recall |
|---|---:|---:|---:|---:|
| `S1_flat_road` | 99,000 | 16.8 | 1.0000 | 1.0000 |
| `S2_pothole` | 99,000 | 16.8 | 0.9995 | 1.0000 |
| `S3_overhang` | 99,776 | 17.6 | 0.9998 | 1.0000 |
| `S4_curb` | 99,000 | 20.8 | 0.9737 | 0.9917 |
| `S5_crossing_truck` | 99,548 | 18.0 | 0.9997 | 1.0000 |

T-P1 and T-P5 pass. **These are synthetic numbers and must not go in the deck**
— they are noise-free geometry with analytic labels, and the honest reading is
"the segmenter is not broken", not "the segmenter is 99% accurate". Real
accuracy waits on KITTI.

**Blocked / blocking.**

- **Blocked: the SemanticKITTI download has not started.** This was Day 1, hour
  1, and it is the longest-lead item on the critical path. Everything above ran
  on synthetic data instead, which was enough to build against but is not enough
  to measure against. *Starting this is the first action of Day 4.*
- **Blocked on Anuj:** `core/grid.py` and `core/cell.py`. `decision/traversability.py`
  needs `CellGrid`; `bench/hazard.py` needs both. Deferred, not started.
- **Blocking Anuj:** `S1`–`S5` were due end of Day 3 for his Day-4 hazard work.
  All five exist and regenerate with `python -m avr25d.synth`. Unblocked.
- **Not started:** `range_proj.py`, `onnx_infer.py`, `cache.py` (Days 4–6 as
  planned).

**Decisions and surprises.** Four things contradicted the written plan. All four
are worth two minutes at the checkpoint.

1. **The gantry in `S3` was outside the sensor's field of view.** The HDL-64E
   stops at +3°, so at 25 m it cannot see above 3.01 m in the road frame — a
   thin beam at 3.10 m returns *nothing at all*. And where only a vertical face
   is visible, the lowest beam that lands on it is quantised by the beam pitch:
   0.31 m at 40 m, six times the 0.05 m T-H1 asks for. **T-H1 as specified was
   not achievable with a thin gantry at any range.**
   Fixed by giving the structure depth along `x` — an overpass deck spanning
   26–50 m. Beams at +3.000, +2.556, +2.111 and +1.667° cross the 3.10 m plane
   at 26.7, 31.4, 38.0 and 48.1 m, so four rings strike the *underside*, and an
   underside hit measures clearance directly. **Measured error: 0.0027 m.**
   The general lesson applies to the payload workstream too: a +3° up-FOV
   barely sees overhead structure, which is a real argument for a
   purpose-designed sensor (PRD §16).

2. **`z_obstacle` cannot serve as clearance.** PRD §6.2 defines `z_obstacle` as
   the *maximum* height of non-ground returns; PRD §6.3 bit 2 then uses
   `z_obstacle − z_ground` as clearance. Those agree only for a thin obstacle.
   Under the deck the maximum return is the deck's *top* at 4.60 m, so
   `clearance` computes as 4.60, `OVERHANG` does not fire, and the scene the
   flag exists for is the scene it fails on. The cell schema needs a separate
   *minimum* height of non-ground returns above the ground surface. **Anuj's
   call — `core/cell.py` — but it should be decided before Day 4's
   `cell.analyse()`.**

3. **The scene CSV in IMPLEMENTATION_PLAN §6.15 mixes two conventions.** Its
   pothole and gantry rows are base-referenced (`z` = bottom of the primitive)
   while its cylinder row is centre-referenced. Settled on **centre-referenced
   throughout, full extents**, documented in every scene file. So a 0.22 m
   pothole flush with the road is `z=-0.11, sz=0.22`, and a 0.5 m beam with
   3.10 m clearance is `z=3.35, sz=0.5`. Worth a one-line fix in the plan.

4. **A pothole cannot exist in a nearest-hit ray-caster.** A solid box under the
   road plane is simply hidden by the plane. Added a `pit` primitive: an
   open-top box that carves its volume out of everything above it, so rays reach
   the inner floor and walls. Roughly 20 lines, in `raycast.py`.

Two coverage findings that affect Anuj's tests, both physics rather than bugs:

- **T-H2's ≥80% is not reachable as literally written.** A 1.4 m × 1.0 m
  pothole at 12 m gets **49 returns** — the beam pitch puts only two rings
  across it. Those 49 sit in roughly 370 grid cells, so at most ~13% of
  *covered* cells can be flagged. Read as *≥80% of **occupied** covering cells*
  it is fine. The depth measurement is unaffected and good: deepest return
  0.2101 m against a true 0.220 m, **error 0.0099 m**, inside T-H2's 0.05 m.
  Also note no ray reaches the pit floor at 12 m — 8.06° incidence needs a
  1.55 m run and the pit is 1.40 m long, so every return is on the far wall.
  That is correct sensor behaviour and the reason the error is not zero.
- **The geometric segmenter does not resolve negative obstacles semantically,**
  by design. 48 of the 49 pothole returns are within `ground_tol` of the plane
  and read as `DRIVABLE`. Calling a hole a `STATIC_OBSTACLE` would be worse —
  there is nothing there to hit. Sub-plane points are classified
  `NON_DRIVABLE_TERRAIN` and the negative obstacle is detected *geometrically*
  by the grid, from the `z_ground` drop (FR-14). Same for `S4`: the kerb top is
  0.15 m and `ground_tol` is 0.12 m, so noise straddles it and 1,687 of 2,694
  kerb returns read as ground. The footway behind it classifies correctly as
  terrain. Neither weakens the demo; both should be stated rather than
  discovered by a judge.

Smaller decisions:

- **`ground_tol` set to 0.12 m = `vehicle.max_step`.** Ground is, by definition,
  what the vehicle can drive over, so the segmenter's notion of flat and the
  planner's notion of mountable are now the same number with the same
  justification. Answers "why 0.12?" without a shrug.
- **Clustering uses a k-NN graph (k=16) filtered by radius, not all radius
  pairs.** Textbook Euclidean clustering has an unbounded edge count; a dense
  urban scan can produce tens of millions of pairs and turn a 20 ms stage into a
  2 s one. The k-NN graph caps edges at 16n. Same components for anything denser
  than 16 points, which is every object we care about.
- **The cluster gate asks four questions in a fixed order** — floating? raised
  ground? traffic? — and the order is load-bearing. Two real defects were caught
  only by per-object tests, invisible in aggregate accuracy: a 1.2 m wide,
  3.1 m tall bridge pier passing the vehicle gate and being tracked as a lorry
  (fixed by requiring a vehicle to be at least as long as it is tall), and the
  overpass deck passing the raised-ground gate and being called a footway at
  3.1 m (fixed by testing "floating" first).
- **Synthetic scenes write real SemanticKITTI raw ids**, not AVR class ids, so
  they read through the same `KittiSequence` as sequence 04. Moving primitives
  emit `moving-truck` (258), which exercises the `MOVING` bit end to end.
- **`other-structure` (52) and `other-object` (99) map to `STATIC_OBSTACLE`**,
  per PRD §6.1 — the stock `semantic-kitti.yaml` sends both to *unlabeled*. Ours
  is right for us: they are solid things a vehicle would hit. Divergence is
  documented in `labelmap.py` and asserted in a test.
- **Python 3.14.** `requirements.txt` pins `numpy==2.2.6` and `scipy==1.16.2`,
  neither of which builds on 3.14. Running `numpy 2.5.2` / `scipy 1.18.1`.
  The pins need refreshing or the interpreter needs pinning to 3.12 — decide
  before anyone else fights it.

