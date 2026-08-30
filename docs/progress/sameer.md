# Sameer — perception, benchmarking, synthetic scenes, integration lead

Newest entry at the top. Format and rules: [`README.md`](./README.md).

---

## Days 4–6 (early) · Sun 30 Aug 2026 — the perception network

**Landed.** The network path, end to end, on real KITTI.

- `tools/export_onnx.py` — checkpoint → ONNX → int8, with verification.
- `avr25d/perception/onnx_infer.py` — `OnnxSegmenter`, CPU-only ONNX Runtime.
- `avr25d/perception/cache.py` — `build_cache` / `LabelCache`, memory-mapped.
- `tools/build_cache.py` — the overnight job, resumable.
- `tests/test_range_proj.py`, `test_onnx_infer.py`, `test_cache.py` — 44 tests,
  covering T-P1 through T-P4. Suite is 121, all green.

**Q-4 answered.** **lidar-bonnetal SqueezeSegV2** — MIT, University of Bonn,
plain HTTP, no account. SalsaNext is also MIT but only reachable through a
Google Drive interstitial that cannot be scripted, and 0.93 M parameters against
DarkNet21's 21 M is the difference between a frame budget and an apology.

**Acceptance.** Day 6's exit criterion — *"network labels visibly better than
geometric labels on the same scan"* — **met, by a factor of 2.9.** Same scans,
same ground truth, mIoU over classes 1–4:

| | seq 04, 46 scans | seq 00, 40 scans |
|---|---:|---:|
| Network | **0.823** | **0.868** |
| Geometric | 0.287 | 0.371 |
| Network point accuracy | 92.03% | 92.31% |

Day 4's *"acquire, export, int8-quantise"* — met, and the quantisation is the
interesting part (below). Day 5's `onnx_infer.py` and the k-NN reprojection —
met. Day 6's label cache — built, not merely kicked off: **758 scans, 93.7 MB,
2.0 minutes.**

**Blocked / blocking.** Nothing blocking me. Two things for Anuj:

1. **`perception.mode` cannot be dispatched inside `perception/`.** Its three
   values are `live | cached | geometric`, and `cached` needs a *frame id* —
   which a `(xyz, intensity)` segmenter does not have. The mode switch has to
   live where frame ids exist, i.e. the server. `LabelCache[frame_id]` is the
   API; `OnnxSegmenter` and `GeometricSegmenter` are interchangeable callables
   with a `.mode` string for the FR-6 HUD badge. I deliberately did not invent a
   factory that would have forced a lie into one of the three.
2. Still open from Day 3: **`z_obstacle` cannot serve as clearance.** PRD §6.2
   defines it as the *maximum* non-ground return; §6.3 bit 2 computes clearance
   as `z_obstacle − z_ground`. Under the S3 overpass deck that reads 4.60 m and
   `OVERHANG` never fires. A separate minimum-overhead field is needed.

**Decisions and surprises.**

- **The architecture is reimplemented, not vendored, and it is verified rather
  than trusted.** `export_onnx.py` rebuilds SqueezeSegV2 from the published
  source (MIT, credited in the file header) so the repo holds no third-party
  Python, then loads the released weights with `strict=True`. One wrong layer
  name, channel count or ordering and the load fails instead of silently
  producing a network that runs and is wrong. The exported graph then has to
  reproduce PyTorch's argmax: measured **100.000% of pixels** on `00/000008`.
- **int8 is exported and deliberately not used — against §6.6.** Measured:
  3.71 → 1.11 MB, **86.0 → 86.2 ms**, and agreement with the PyTorch reference
  falling **100.000% → 95.058%**. Dynamic quantisation scales activations at
  runtime, so a Conv-only graph pays the quantise/dequantise cost without ever
  reaching an int8 kernel. It buys 2.6 MB of disk we are not short of and spends
  5% of pixels on it. `config.yaml` points at fp32 with that measurement written
  next to the key. Static quantisation with a calibration set from the 758
  cached scans is the version worth trying, and now cheap to try.
- **`NON_DRIVABLE_TERRAIN` is the entire argument for the network**, and it is
  now measured: IoU **0.132 geometric → 0.872 network** on sequence 04, where
  that class is 50% of all points. Flat grass beside a road is the same plane as
  the road, so RANSAC calls both DRIVABLE; tarmac against verge is a semantic
  distinction and geometry has no access to it. Good slide.
- **The softmax is dropped from the exported graph.** Argmax is invariant under
  it, and 20 × 64 × 2048 exponentials per frame is real CPU time spent on a
  value nothing reads. A caller wanting probabilities can soft-max the logits.
- **Labels merge 20 → 5 *before* the k-NN vote, not after.** Voting in 5-class
  space is what the taxonomy cares about, it stops three vehicle classes
  splitting the vehicle vote against one road neighbour, and it keeps the vote
  array at n×5 rather than n×20.
- **The checkpoint validated `range_proj.py` after the fact.** Its
  `arch_cfg.yaml` carries the same `img_means`/`img_stds` already hard-coded in
  `KITTI_MEAN`/`KITTI_STD`, and the same k-NN post-processing parameters
  (`knn 5, search 5, sigma 1.0, cutoff 1.0`) already defaulted in
  `from_range_image`. Those are now in `config.yaml` sourced to the checkpoint,
  not to us — they are not ours to retune.
- **`range_proj.py` shipped on Day 3 with no tests; that is now fixed, and the
  tests were checked by mutation.** Six deliberate defects injected into the
  source — nearest-first scatter, no FOV clamp, cutoff removed, orphan fallback
  removed, unflipped vertical axis, empty pixels allowed to vote. Five were
  caught immediately; the sixth, the `range < 0` guard, was not, which is how a
  genuinely untested line was found. It has a test now, and one line of dead
  belt-and-braces was deleted once the mmap's own `mode="r"` was shown to carry
  the read-only guarantee. Same treatment on `cache.py` and `onnx_infer.py`:
  nine mutations, nine caught.
- **The cache refuses to lie about itself.** `index.json` records the segmenter
  mode and model path, and `build_cache` will not extend a geometric cache with
  network labels or vice versa; `LabelCache` checks the blob length against the
  index before trusting it. A demo showing geometric labels while the HUD reads
  "network" is worse than one that crashes.
- **`reproject` is 46 ms of the 147 ms**, a third of the network path, and it is
  pure NumPy over 125k points. If live inference ever has to fit a budget, that
  is the cheapest place to look after quantisation.
- The network never predicts `VOID`. Ground-truth *unlabeled* is ~2% of points,
  so whole-taxonomy mIoU reads 0.658/0.695 while classes 1–4 read 0.823/0.868.
  SemanticKITTI excludes *unlabeled* from mIoU; the tables here do the same and
  say so.

---

## Day 3 (later) · Sun 30 Aug 2026 — dataset

**Landed.** `tools/fetch_kitti.py`, and real KITTI on disk.

KITTI publishes the odometry point clouds as **one 84.8 GB zip** with no
per-sequence download — the plan's "~12 GB for 1000 scans" assumed an access
mode that does not exist. The archive is served with `Accept-Ranges: bytes` and
a zip keeps its central directory at the end, so the fetcher reads the directory
over HTTP and issues one ranged request per member it actually wants.
**1.8 GB of payload out of an 84.8 GB archive — 2.3%.** `zipfile` does the ZIP64
parsing; the script only has to supply a seekable file object over ranges.

Written as `.py`, not the `fetch_kitti.sh` the plan names: the range-into-zip
trick is not expressible in shell, and NFR-4 requires one source tree that runs
on macOS and Windows. Stdlib only, so it runs before `pip install -e model/`.

**Acceptance.** Day 2's *"5-class labels on a real KITTI scan"* — **met.**
Sequence 04 complete: 271 scans, 271 labels, 519.9 MB. Sequences 00 and 05 in
progress.

First real numbers, geometric segmenter over all 271 scans of sequence 04,
125,718 points/scan, macOS arm64 single core:

| | |
|---|---:|
| mIoU (4 classes, VOID excluded) | **0.289** |
| Point accuracy | 0.500 |
| Latency, median / p95 / max | 58.1 / 70.1 / 135.1 ms |

| Class | IoU | Share of truth |
|---|---:|---:|
| `DRIVABLE` | 0.627 | 33.9% |
| `NON_DRIVABLE_TERRAIN` | **0.133** | **50.1%** |
| `STATIC_OBSTACLE` | 0.268 | 12.6% |
| `DYNAMIC_OBJECT` | 0.127 | 1.3% |

Distance-binned (FR-33): 0.290 at 0–10 m, 0.291 at 10–30 m, 0.196 at 30–60 m,
0.000 at 60–100 m (1,152 pts/scan in that bin).

These are one-off measurements from a scratch script. `bench/` proper is Day 8
and nothing here should reach a slide until it comes from `results.json`.

**Blocked / blocking.** Nothing new. The KITTI download is no longer a blocker.

**Decisions and surprises.**

1. **The geometric segmenter's real weakness is now measured, and it is not the
   one I expected.** `NON_DRIVABLE_TERRAIN` is 50% of sequence 04's points and
   scores IoU 0.133. Sequence 04 is a road through fields; the segmenter calls
   flat verge `DRIVABLE` and bushy verge `STATIC_OBSTACLE`. **Tarmac versus flat
   grass is a semantic distinction, not a geometric one**, and no threshold
   fixes it — which is a concrete, measured argument for the network rather than
   an assumed one. Roughness could recover part of it (vegetation returns are
   far rougher than tarmac) but that is Day 6 work, not a Day 3 tweak.
2. **Live perception is 58 ms median, 135 ms worst case** — above the 33 ms a
   30 FPS budget allows. Exactly why FR-6 decouples perception and runs the demo
   from a label cache. The number is real and goes on the HUD as its own figure.
3. **The plan's subset costs 3.5× its size to transfer, and it need not.**
   KITTI's zip does not store members in frame order — within sequence 04, frame
   `000000` sits at a *higher* offset than `000007`. Two consequences:
   - Extraction now runs in `header_offset` order. Walking by filename seeks
     backwards on nearly every file and threw away the read-ahead window each
     time: one benchmark transferred **912 MB to extract 114 MB**.
   - "The first N frames" is an expensive request, because those N frames are
     strewn across the sequence's whole region. Measured, 8 MB blocks:

     | Selection | Scans | Payload | Transfer |
     |---|---:|---:|---:|
     | Plan as written | 971 | 1.92 GB | 6.74 GB (3.5×) |
     | 04 all | 271 | 0.55 GB | 0.55 GB (1.0×) |
     | 00 first 400 | 400 | 0.77 GB | 3.53 GB (4.6×) |
     | 00 **400 archive-contiguous** | 400 | 0.78 GB | **0.78 GB (1.0×)** |

     So `--sampling contiguous` was added. Sequence 00 now takes 400 frames
     adjacent in the archive, which land spread across frame ids 8–4524 — for a
     *segmentation accuracy* set that is better sampling than 400 consecutive
     frames of one stretch of road, and 4.6× cheaper. Sequence 05 keeps
     `frames`, because temporal continuity is the entire point of that sequence.
     The chosen frame ids are recorded in `data/kitti/manifest.json` so the
     evaluation set is reproducible.
4. **Throughput needed three fixes to be usable at all.** The first version ran
   at 0.10 MB/s — five hours for the subset — against a link that measures
   1.0 MB/s single-stream. Block-aligned caching, one kept-alive connection per
   worker, and parallel prefetch (S3 shapes each connection separately, so one
   stream cannot exceed ~1 MB/s no matter the local link) took it to **2.7 MB/s**.
5. **`urllib` had no CA bundle** on this python.org build, so it failed
   `CERTIFICATE_VERIFY_FAILED` on a machine where `curl` worked. The fetcher
   resolves a bundle via `certifi`, then the system store, and says what to do if
   neither is there. Anyone on a fresh macOS box would have hit this.

**Q-4 resolved** — *which pretrained SemanticKITTI range-image checkpoint is
available under a licence permitting hackathon use?* Two, both MIT, both
verified reachable today:

| Source | Licence | Models | Notes |
|---|---|---|---|
| [SalsaNext](https://github.com/TiagoCortinhal/SalsaNext) | MIT | SalsaNext, SemanticKITTI | ~6.7 M params, built for efficiency. The architecture the plan names. Weights are on Google Drive, so not scriptable. |
| [lidar-bonnetal](https://github.com/PRBonn/lidar-bonnetal) (RangeNet++) | MIT | `squeezeseg` 3.4 MB, `squeezesegV2` 3.5 MB, `darknet21` 92 MB, `darknet53` 187 MB, `darknet53-512` 187 MB | Direct HTTP, all five returned 200 today. Same group whose k-NN reprojection `range_proj.py` implements. |

**Recommendation:** SalsaNext first — it is the named architecture and the best
accuracy-per-FLOP of the two. `squeezesegV2` from lidar-bonnetal as the fallback:
3.5 MB, direct download, no Google Drive friction, and small enough that int8 CPU
inference is plausible rather than hopeful.

**Licence note that belongs in the deck.** SemanticKITTI is CC BY-NC-SA 4.0 —
attribution, share-alike, **non-commercial**. Fine for the hackathon, but it must
be stated wherever the data is used, and no claim may imply a commercial product
trained on this data. This is exactly the kind of thing a DRDO evaluator asks
about, and the answer should be on a slide rather than improvised.

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

