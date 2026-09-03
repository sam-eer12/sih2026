# Sameer — perception, benchmarking, synthetic scenes, integration lead

Newest entry at the top. Format and rules: [`README.md`](./README.md).

---

## Days 7-11 · Thu 3 Sep 2026 — hazard scoring exists, and it found two bugs in `core/`

Board cleared through Day 11. Every section of `docs/RESULTS.md` is populated —
there is no `_not measured_` left in the file.

**Landed.**

| Module | What it does | Board day |
|---|---|---|
| `bench/hazard.py` + `tests/test_hazard.py` (26) | §11.4 — every hazard scored in metres against exact ground truth, with the 2D counterfactual | 8 |
| `synth/scenes/S6_occluded_pothole.csv` | S2 with 53% of the pit in a stopped car's shadow | 9 |
| `synth/scenes/S7_tunnel_curb.csv` | 3.40 m tunnel + a 0.15 m kerb inside it | 10 |
| `tools/finetune.py` | Q-1 probe, the 5-class split, the decoder-head fine-tune, before/after | 9-10 |
| `bench/__main__.py` | `--seq 00 04 05` pools into one result with per-sequence variance | 11 |
| `bench/latency.py` | warm-up discard, one window per sequence | 11 |
| `bench/report.py` | new §11.3.1 variance section; §11.4 rewritten | 11 |
| `decision/tracker.py` | rewritten — Anuj's stub said "Sameer replaces the body" | 7 |

Suite **347, all green**. `make bench-authoritative` runs 971 scans in 25 s.

---

### Day 7's acceptance was not met, and the reason was a real bug

The board asks for a *stable track id across all 40 S5 frames* and *speed within
0.5 m/s of 8.0*. What was there passed neither, and the test could not have
caught it: the speed assertion was written at ±5.0 m/s and wrapped in
`if speed_readings:`, so it also passed when nothing was tracked at all.

The defect was clustering DYNAMIC_OBJECT cells with 4-connectivity **in
(ring, bin) index space**. A vehicle at fixed x crossing in y occupies a
*diagonal* swath of the ring table — its visible face spans several metres of
range — so 4-connectivity shears it into one fragment per ring. Measured: **74
truck cells across 42 rings became 19 clusters**, and since `tracks[0]` was a
different fragment each frame the id changed four times in forty. The one frame
that clustered correctly was frame 20, the truck dead ahead, where its face is
at constant range and spans two rings.

Clustering by radius in metres has no preferred axis: **one cluster on all 40
frames, one id, born at frame 1.**

Speed now measures **7.566 m/s against a true 8.0**, error 0.434. Worth knowing
where that residual comes from, because it is not the filter: the tracker sees
the centroid of the *visible* cells, and over the crossing that centroid slides
from the truck's near face to its far one — +0.81 m at the start, −0.81 m at the
end. That is a fixed −0.415 m/s of parallax on a 3.9 s crossing and no tuning
removes it, because the information is not in the returns. The filter's own
contribution is 0.02 m/s. There is a test asserting exactly that, so if the
speed assertion ever fails we know immediately whether to look at the estimator
or the scene.

Also made track ids per-instance rather than a module global — the old counter
made a test's ids depend on how many tracks every *earlier* test had created,
which is why the original test could only assert that *some* id existed.

---

### Two defects in `core/cell.py`. **Anuj — one is fixed, one is yours.**

`bench/hazard.py` was written to score the flags. It found that two of the three
were nearly never firing, and the causes are both structural rather than
threshold tuning.

**1. NEGATIVE_OBSTACLE's reference was the pothole itself. Fixed.**

FR-14 and your own §6.3 docstring both say the reference is the median of a
cell's *ring neighbourhood*. The code used the median of the **single ring**,
and a pit is exactly the case where that fails. Ground returns land at discrete
ranges — successive beams strike the road `r²·δ/h` apart, 0.65 m at 12 m — so
the rings *between* two beam hits are empty. A pit's far inner wall sits a
little beyond the beam ring that lit it, which lands its returns in one of those
otherwise-empty rings.

Measured on S2: **ring 248 held 15 occupied cells out of 1257 bins and all 15
were inside the pothole.** Its median was the pit floor, the drop against it was
0.005 m, and a 0.22 m hole did not fire. The beam-lit ring beside it, 247, held
435 cells with median −1.7033 — the road, and the reference the requirement
means.

Replaced `_ring_median_z_ground` with `_ground_reference`: a windowed median
over the nearest rings that are populated enough to mean anything, gated by
`hazards.ref_ring_min_fill` (2% of a ring's bins) and `hazards.ref_rings` (9).
The two rings above sit at 1.2% and 34.6%, an order of magnitude apart, so the
gate is not balanced on a knife edge. Both constants are in `config.yaml` with
their reasoning.

Pothole detection **25.9% → 77.8%** of covering cells. The remaining 22.2% are
the pit's *rim*, which is at road level by construction and must not fire —
every cell genuinely below the local road now fires, and §11.4 reports both
denominators. S1 still raises **zero** false positives, which is the test I was
most worried about breaking.

**2. OVERHANG is measurable on almost no cells, and this one is yours.**

FR-13 defines `clearance = z_obstacle − z_ground` **per cell**, and the code
implements exactly that. The problem is the sensor, not the code: on S3 the deck
underside returns land in **15 rings**, the road beneath it in **6**, and
**exactly 1 ring has both** — because a beam that strikes an overhead surface
and a beam that strikes the road under it are different beams landing at
different ranges. So OVERHANG fires on **2 of 916** cells under the deck, and on
**0 of 191** on S7's tunnel.

I have not touched this. The fix wants the same neighbourhood idea — the lowest
overhead return *near* a ground cell rather than in it — and that is a change to
your frame loop with a 30 Hz budget attached, so it should be your call rather
than mine. Two things to note before you start:

- **The half of T-H1 that matters already passes.** 419 of 916 cells under the
  deck stay `DRIVABLE`, so the road under the bridge is not lost. That is the 2D
  failure we claim to fix and we do fix it. There is a test.
- **The clearance number itself is fine** — 3.0976 m against 3.10, and 3.3977
  against S7's 3.40. `bench/hazard.py` measures it as the structure's lowest
  return above the road reference and reports `clearance_cells_with_both`
  alongside, so §11.4 states the per-cell yield rather than quietly measuring it
  another way. Nothing in the deck is blocked on this.

---

### §11.4 — the table, and the counterfactual

| Scene | Hazard | True | Measured | Error |
|---|---|---:|---:|---:|
| S2_pothole | depth | 0.22 | 0.2092 | **0.0108** |
| S3_overhang | clearance | 3.10 | 3.0976 | **0.0024** |
| S4_curb | step height | 0.15 | 0.1526 | **0.0026** |
| S5_crossing_truck | track speed | 8.00 | 7.5660 | **0.4340** |
| S6_occluded_pothole | depth | 0.22 | 0.2248 | **0.0048** |
| S7_tunnel_curb | clearance | 3.40 | 3.3977 | **0.0023** |
| S7_tunnel_curb | step height | 0.15 | 0.1508 | **0.0008** |
| S1_flat_road | false positives | 0 | **0** | — |

Cells are associated to a hazard by **instance id**, not by a footprint test on
cell centres. Those sound equivalent and are not: at 12 m the cells are 5.7 cm
across, the pit's far-wall returns land in cells whose centres sit just outside
the CSV footprint, and a footprint test silently dropped them — including the
deepest return in the scene, which is the one the depth estimate depends on.
That cost an hour; the instance id cannot be wrong.

**The 2D counterfactual is now measured rather than asserted** (PRD §10.4). A
standard navigation grid — occupied where a return sits more than `max_step`
above the local road, not the strawman that blocks the road itself:

- **pothole: 0.000 of its cells blocked.** A depression holds no returns above
  the road, so a 0.22 m hole is byte-identical to flat road. Not "hard to see" —
  *not representable*.
- **overpass and tunnel: 1.000 blocked.** The structure's returns block the
  column and the drivable road beneath is marked impassable. That is the
  measured version of the slide.
- **kerb: 0.647 blocked, height not recoverable.** A 0.15 m kerb sets the same
  single bit as a 3 m wall.

---

### The adversarial scenes, and one that had to be rebuilt

**S6 — occluded pothole.** First draft put the pit at 16 m and measured a 0.14 m
depth error. That was **the range doing it, not the occlusion**: a pit is
measurable only where a beam reaches its floor and the grazing angle falls from
8.1° at 12 m to 6.1° at 16 m, so the two effects would have been reported as
one. Rebuilt at S2's 12.0 m with only occlusion changed. Sweeping the pit across
the car's shadow edge:

| lit fraction | 0% | 7% | 30% | 53% | 75% |
|---|---:|---:|---:|---:|---:|
| pit returns | 4 | 12 | 25 | 41 | 49 |
| depth error (m) | 0.158 | 0.095 | 0.003 | 0.005 | 0.004 |

Depth survives occlusion until almost nothing is left and then fails abruptly,
because it depends on whether *any* beam reaches the floor rather than on how
many do. 53% is the shipped operating point — hard enough that a detector
relying on cell population fails, not so hard that everything fails. A scene
whose answer is always "no" tests nothing.

**S7 — tunnel and kerb.** 3.40 m against a 3.50 m vehicle, so the whole decision
is 0.10 m, and we measure it to 0.0023 m — 43x margin. The kerb inside is the
adversarial half: at 30-60 m a 0.15 m face subtends 0.21° against a 0.4375° beam
pitch, so **detection density collapses (15 returns, against S4's 2,694) while
geometric accuracy does not (0.0008 m, better than S4's 0.0026)**. Range costs
us confidence the kerb is there, not knowledge of how high it is. Worth a slide.

---

### Q-1, answered — and the answer is that it stopped mattering

**A usable training GPU is already here.** `torch.backends.mps` reaches the M4's
GPU, forward *and backward* both run on it (verified, not assumed — `probe`
runs a real backward pass), and it is on the machine that already holds the
2.2 GB of KITTI, the checkpoint and the 971-scan cache. The fine-tune does not
wait on the Windows box, and moving the data to a second machine would have cost
most of a day.

What this repo cannot settle is which card is in the Windows box. **Someone at
that machine: run `make finetune`'s probe line and paste the output at
standup.** It is wanted only for the HUD's live-inference figure (PRD Q-1's
second sentence); no module, benchmark or demo path depends on it.

**The split (Day 9).** Train on 00+05 (700 scans), validate on 04 (271).
**Sequence-level, not a random frame split** — KITTI is a 10 Hz recording, frame
41 is very nearly frame 40, and a random split puts near-duplicates on both
sides and reports a memorisation score. It also means before and after are
measured on the sequence §11.3 already quotes. Manifest with class frequencies
and loss weights in `model/data/splits/finetune_5class.json`.

**The fine-tune (Day 10) — measured, and we are not shipping it.**

Backbone frozen (parameters *and* BatchNorm — `requires_grad=False` does nothing
to running statistics, so leaving BN in train mode drifts the pretrained
features while the loss looks healthy). Decoder + a new 5-output head, the head
initialised from the 20-class weights by averaging each AVR class's
constituents. 184,133 of 919,809 parameters train. 3 epochs, ~10 scan/s on MPS,
under 4 minutes. Scored on 271 held-out scans through the identical projection →
inference → k-NN reprojection path as production.

| | pretrained | inverse-freq | uniform |
|---|---:|---:|---:|
| mIoU | **0.8454** | 0.8303 | 0.8384 |
| point accuracy | **0.9409** | 0.9339 | 0.9286 |
| object recall | 0.9145 | **0.9427** | 0.8978 |
| STATIC_OBSTACLE IoU | 0.7310 | 0.7341 | **0.7490** |
| DYNAMIC_OBJECT IoU | 0.8006 | 0.7753 | **0.8262** |
| DRIVABLE IoU | **0.9569** | 0.9283 | 0.9026 |

**Neither weighting beats the pretrained network on mIoU, so `config.yaml` still
points at the ONNX and nothing changed in the pipeline.** Both variants improve
the two hard classes and lose more on DRIVABLE than they gain — coherent, since
DRIVABLE is 34% of the points and a frozen backbone with 3 epochs on 700 scans
moves the boundary toward the rare classes at its expense. The inverse-frequency
run did exactly what its weights asked (recall +2.8 points); mIoU was not what
it optimised. I ran the uniform variant specifically so "fine-tuning does not
help here" has two data points rather than one.

The honest framing for the deck: **the pretrained network is already at the
accuracy this dataset supports for a frozen-backbone budget**, and Day 10's
value is knowing that rather than guessing it.

---

### Day 11's runner work

**`--seq 00 04 05` is one run, not three added up afterwards.** The confusion
matrices pool into a single accumulator, so the headline is the real pooled
figure and not a mean of means over sequences of different lengths. Per-sequence
blocks and the spread land in §11.3.1:

| | mean | sd | spread |
|---|---:|---:|---:|
| mIoU | 0.866 | 0.022 | 2.6% |
| point accuracy | 0.934 | 0.010 | 1.0% |
| object recall | 0.924 | 0.010 | 1.1% |

Pooled headline mIoU **0.878** over 971 scans. This replaces the three-runs-
aggregated-by-hand table from Day 7, which was the remaining Day 11 piece.

**Warm-up is discarded and counted.** The seq-05 46.9 ms max against a 5.9 ms
median was first-touch page faults on the freshly-appended cache mmap. One
window *per sequence*, not per process — a new sequence touches a new region, so
without that the pooled worst case is sequence 2's first frame. 15 scans
discarded across 3 boundaries, stated in §11.2 rather than quietly dropped, and
FR-32 counts *scored* scans so 956 of 971 is what the claim rests on.

It is opt-in: `LatencyRecorder`'s default is 0. An instrument that silently
throws away its first five observations is a trap for its next caller, so
discarding warm-up is a benchmark policy and the benchmark passes it in. It is
also capped at a tenth of the run — a 3-scan debug run with a 5-frame warm-up
discarded everything and reported no latency at all, which is worse than the
page faults, because the run looks like it succeeded.

**Peak RSS is measured: 292.6 MB.** The last `_not measured_` in the file. It
comes from `getrusage`'s high-water mark rather than sampling RSS after the
loop, which only finds the peak if the peak happened to be at the end.
`ru_maxrss` is bytes on Darwin and kibibytes on Linux — a units bug that reports
a 1024x wrong number rather than failing, so the platform is checked. §11.1 says
the figure is the whole benchmark process and therefore an upper bound.

---

### Three things that were broken and are not any more

- **`make bench --mode network` had never run.** `_build_segmenter` called
  `OnnxSegmenter(cfg=cfg)`, and `model_path` is positional with no default, so
  it raised `TypeError` the moment anyone tried it. Nobody had.
- **`main` was red.** `psutil` and `uvicorn` are both in
  `backend/requirements.txt` and neither was installed in `backend/.venv`, so
  two tests failed on import and `server/app.py` could not be imported at all.
  Every pin now installs and imports. **If your venv predates today, re-run
  `pip install -r backend/requirements.txt`.**
- **`tests/test_synth.py::test_all_five_scenes_are_present`** now expects seven.

---

### For the standup

1. **Anuj** — OVERHANG, above. Yours, with the measurement already in place.
2. **Anuj** — `_ground_reference` in `core/cell.py` is my edit to your file, and
   `config.yaml` gained `hazards.ref_*` and `decision.tracker.*`. Both
   documented in place; shout if you would rather own the change.
3. **Everyone** — reinstall requirements.
4. **Shubham, Navya, Khanak, Veda** — `docs/progress/` still has four empty
   files on Day 7. The backend is four days ahead of the board and the other
   four tracks are unmeasured, which is the real risk item, not anything above.
5. Day 12's authoritative run is `make bench-authoritative`. It takes 25 s, so
   the Day 12 slot is handover and MongoDB persistence, not compute.

---

## Day 7 (early) · Mon 31 Aug 2026 — `make bench` exists and produces real numbers

Day 8's `bench/distance_bins.py` and Day 11's `bench/report.py` landed today,
three days early, along with the two `bench/` modules §8's contingency had tried
to give away. None of it needed anything from anyone else.

**Landed.**

| Module | What it does | Spec |
|---|---|---|
| `bench/baselines.py` | B0-B4 and both AVR models as pure closed forms | PRD §10.1, FR-31 |
| `bench/latency.py` | Per-stage + end-to-end, mean/median/p95/max | FR-32 |
| `bench/distance_bins.py` | Binned mIoU, object recall, streaming accumulators | FR-33, FR-34 |
| `bench/report.py` | `results.json` -> the PRD §11 tables | NFR-5 |
| `bench/__main__.py`, `Makefile` | `make bench` | §6.11 |
| `tests/test_{baselines,latency,distance_bins,report}.py` | 86 new tests | T-B1…T-B5 |

Suite is **207, all green**. T-B1 through T-B4 pass; T-B5's reproducibility half
passes, its `make bench` half now has a `make bench` to run.

**Acceptance.** Day 8's *"binned mIoU computed"* — met. Day 11's `bench/report.py`
and *"first full `make bench`"* — met, with the caveat below. Day 6's *"network
beats geometric"* is now **measured over all 271 scans of sequence 04 rather than
46**, and it holds:

| | geometric | network (cached) |
|---|---:|---:|
| mIoU (classes 1-4) | 0.291 | **0.845** |
| Point accuracy | 0.502 | **0.941** |
| Object recall | 0.444 | **0.914** |
| Median end-to-end | 63.8 ms | **5.3 ms** |

2.90x on mIoU, which is the 2.9x claimed on Day 6, now on 6x the scans. Per-bin:
0.290 -> 0.877 at 0-10 m, 0.289 -> 0.846 at 10-30 m, 0.213 -> 0.663 at 30-60 m.
`NON_DRIVABLE_TERRAIN` is 0.134 -> 0.893, still the whole argument for the network.

**Three things I got wrong before, corrected by the harness.**

1. **My Day 3 "0.000 mIoU at 60-100 m" was wrong, and the truth is better.**
   Sequence 04 has 20,943 points beyond 60 m and **every single one is
   ground-truth `VOID`**. There is nothing out there to be right or wrong about.
   0.000 was an artefact of scoring absent classes as zero; the honest statement
   is that *SemanticKITTI stops annotating past 60 m*, so far-field accuracy is
   unmeasurable on this data, not bad. `RESULTS.md` now prints that sentence
   under the table rather than a bare dash, because a judge who sees "—" will
   ask, and "the dataset does not label that range" is a much stronger answer
   than the question assumes. **This changes a slide.**

2. **Excluding VOID from the mean was not enough.** A point whose truth is
   *unlabeled* but which the model called DRIVABLE was still counting as a false
   positive against DRIVABLE. Ground-truth-VOID points are now dropped from the
   evaluation entirely, which is what "SemanticKITTI excludes unlabeled" actually
   means. Deliberately **not** symmetric: predicting VOID on a labelled point
   still counts against that class, because refusing to answer is an error and
   the geometric segmenter can do it. Both the row-drop and the asymmetry are
   mutation-tested. This moved seq 04 geometric from 0.289 to 0.291.

3. **`LabelCache[8]` means "the ninth cached scan", not "frame 000008".** I wrote
   the cache with sequence-qualified keys precisely so `000000` in three
   sequences would not collide, then indexed it with an int from my own
   benchmark runner and got sequence 00's labels while asking for 04's. It threw
   only because the point counts differed — **with matching counts it would have
   silently scored the wrong sequence.** That is the exact failure `index.json`'s
   provenance checks exist to prevent, reintroduced one layer up by an
   `int | str` overload. Added `LabelCache.for_frame(sequence, frame)`, which
   cannot mean the wrong thing. **Anuj: use `for_frame`, not `cache[frame_id]`,
   when the server dispatches `perception.mode: cached`** — the wire protocol
   carries a frame number and this is a live trap.

**Loose ends from the checkpoint, closed.**

- **Sequence 05 is complete** — 283 of 300 scans at the time of writing and still
  running; it was 87. One resumable command, as predicted.
- **`backend/requirements.txt` is fixed, and it was worse than "two stale pins".**
  It was a `pip freeze` of an unrelated global environment: 168 of its ~180 pins
  were not installed here and nothing in the project imports them — ultralytics,
  catboost, xgboost, kaggle, tree-sitter for twenty languages, and a package
  called **`nupy`, which is a typosquat of `numpy`** and should not be installed
  on anyone's machine. Replaced with the ~15 packages we actually use, every one
  verified to resolve on 3.14, including the server and bench deps Anuj will
  need. `IMPLEMENTATION_PLAN.md` §2.1 updated to match: the pins move to 3.14
  rather than the interpreter moving back to 3.12, because the suite and every
  perception measurement we have were taken on 3.14 and downgrading buys nothing.

**Decisions worth two minutes at standup.**

- **The memory table now reports that B4 beats us on a single scan, in bold.**
  Measured on seq 04: B4 sparse voxel is 0.96 MB against our 17.64 MB dense ring
  table. PRD §10.1 already promised we would say so; the renderer now says it
  automatically, so nobody has to remember. The argument stands on cell count
  (22.67x), deterministic `offset[k] + j` access, and the proportional cut in
  downstream per-cell work — and it is much stronger for being volunteered.
- **`bench/` is honest about what it cannot measure.** Occupied adaptive cells,
  peak RSS, hazard scoring and projection integrity all need `core/grid.py` and
  `core/cell.py`. Those sections are emitted **absent**, and `RESULTS.md` prints
  `_not measured_`, never a zero. A half-run benchmark that looks complete is
  worse than one that is visibly partial.
- **`n_cells_adaptive` is quoted from the PRD, not computed**, and `results.json`
  says so in `n_cells_adaptive_source`. It becomes a real measurement the day
  `core/grid.py` lands.
- **Cached mode is 5.3 ms median end-to-end** against a 33 ms budget, versus
  63.8 ms for live geometric. FR-6's decoupling is now a measured number rather
  than a design intention.

**Multi-sequence evaluation — Day 11's, landed the same day.** Sequence 05 finished
downloading, so I extended the label cache (971 scans, 120.4 MB, 0.5 min — it
skipped the 758 already there, as designed) and ran all three sequences in both
modes. 971 scans total:

| seq | scans | geometric mIoU | network mIoU | ratio | net accuracy | net recall |
|---|---:|---:|---:|---:|---:|---:|
| 00 | 400 | 0.374 | 0.890 | 2.38x | 0.938 | 0.934 |
| 04 | 271 | 0.291 | 0.845 | 2.90x | 0.941 | 0.914 |
| 05 | 300 | 0.297 | 0.864 | 2.91x | 0.923 | 0.924 |

**The network is not only better, it is more *consistent*, and that is the
stronger claim.** Across sequences: geometric **0.321 ± 0.046**, network
**0.866 ± 0.022**. Relative spread falls from 14.3% to 2.5%. The geometric
segmenter's accuracy depends on what kind of road it is looking at — seq 00 is
urban and scores 0.374, seq 04 is a road through fields and scores 0.291 —
whereas the network holds within two points across all three. A judge asking
"does this generalise?" gets a measured answer, not an assurance.

Per-class IoU spread, network: `DRIVABLE` sd 0.006, `NON_DRIVABLE_TERRAIN` 0.023,
`DYNAMIC_OBJECT` 0.043, `STATIC_OBSTACLE` **0.060** — the widest, and the class
to look at if there is time for a fine-tune (Day 10).

One latency oddity worth a note: seq 05 cached shows median 5.9 ms but a 46.9 ms
max, against 6.6 ms max on seq 04. Almost certainly first-touch page faults on
the newly appended region of the cache mmap rather than anything in the pipeline.
It is a warm-up artefact and the Day 12 authoritative run should discard a warm-up
pass, which the harness does not yet do.

**Still open on `bench/`:** multi-sequence is currently three runs of the CLI
aggregated by hand; folding `--seq 00 04 05` into the runner so `results.json`
carries per-sequence variance directly is the remaining Day 11 piece.
`hazard.py` and `memory.py` stay blocked on `core/`.

**Still blocked on Anuj, unchanged:** `core/cell.py` for `bench/hazard.py` and
`bench/memory.py`; `CellGrid` for `traversability.py` and `tracker.py`. I am
writing the Day 7 decision modules against the documented §6.2 cell schema with a
test double next, so they drop in the day `core/` lands rather than starting then.

---

## Integration checkpoint · Sun 30 Aug 2026 — nothing outside `model/` exists

Written as integration lead, not as a perception note. Days 1–6 of *my* board are
complete and merged. Days 1–6 of the *sprint* are not, and the gap is not mine
to close alone.

**State of the repository.** Every commit in it is mine.

| | State |
|---|---|
| `backend/` | `requirements.txt` and a virtualenv. **Zero `.py` files.** |
| `frontend/` | Untouched `create-next-app` — `app/page.tsx` still renders the Next.js logo |
| `server/protocol.py`, `server/fixtures.py` | Do not exist |
| `core/grid.py`, `core/cell.py`, `tools/ring_table.py` | Do not exist |
| `docs/progress/{anuj,shubham,navya,khanak,veda}.md` | 5-line stubs, unedited |

**Exit criteria, Days 1–6.** One clause of six days is met.

| Day | Criterion | Status |
|---|---|---|
| 1 | `pytest` green both platforms · `pnpm dev` renders 50k fixture cells · Firebase + Atlas exist · seq 04 downloading | Mine green on macOS arm64; seq 04 complete. Rest not started |
| 2 | `RingGrid` reports 662 rings / 705,771 cells · T-W1 auth gate | Not started |
| 3 | KITTI scan → labels → **grid → browser**, `n_points_conserved == n_points` on the HUD | My half done. Grid, server and viewer missing |
| 4 | Overhang and pothole flags fire on `S3`/`S2`, zero on `S1` · T-W2 | Needs `cell.analyse()`. My scenes carry exact ground truth and are ready |
| 5 | A/B wipe reading 16,000,000 vs 705,771 · T-W5 | Not started |
| 6 | Network beats geometric · both modes selectable, mode on the HUD | **First half met, 2.9×.** Second half needs the server and the HUD |

**Blocking the team.** `server/protocol.py`. `WORK_DISTRIBUTION.md` §3 marks it
*"frozen Day 1 — blocks 4 people"*, §4.2 puts it at 14:00 on Day 1 ahead of
everything else, and changes to it need my sign-off. It does not exist, so
neither does `fixtures.py`, so the whole point of `IMPLEMENTATION_PLAN.md` §5.3,
*"the anti-blocking device"* — that Shubham and Navya build the entire dashboard
against schema-valid synthetic frames with **zero** backend dependency — has not
been available to them for three days. This is the highest-leverage missing
item in the sprint and it is not close.

**Blocked, me, from Day 7.** Both of my next modules take Anuj's data structure:

```python
traversability.score(cells: CellGrid, cfg)    # §6.8
Tracker.update(cells, grid, dt)               # §6.9
```

`WORK_DISTRIBUTION.md` §4.1 says it outright — *"Depends on: Anuj for
`protocol.py` (Day 1), `CellGrid` (Day 3)."* Neither exists, so Day 7 cannot
start as specified. Two ways round it, both of which I can take without touching
Anuj's grid maths: write `protocol.py` and `fixtures.py` myself as the named
backup, and write `traversability.py` against the documented §6.2/§6.3 cell
fields with a test double so it drops in the day `core/cell.py` lands.

**Loose ends that are mine and are not blocked on anyone.**

- **Sequence 05 is 87/300 scans.** All 300 `.label` files are on disk; the point
  clouds stopped when the fetch process died. `tools/fetch_kitti.py` is resumable
  and skips what exists — this is one command, not a task.
- **`backend/requirements.txt` pins `numpy==2.2.6` and `scipy==1.16.2`**, neither
  of which builds on Python 3.14. Everything here runs on 2.5.2 / 1.18.1. Raised
  on Day 3 and still open: refresh the pins or pin the interpreter to 3.12.
  Whoever hits this next will lose an afternoon to it.

**Ownership contradiction to settle at standup.** `WORK_DISTRIBUTION.md` §3 and
§4.1 give me all of `bench/*`. `IMPLEMENTATION_PLAN.md` Days 5–6 assign
`bench/baselines.py`, `bench/memory.py` and `bench/latency.py` to Anuj. Two of
those three are §8's contingency — *"if Sameer is behind at the Day 5 standup,
the first thing to hand to Anuj is `bench/baselines.py` and `bench/memory.py`"* —
pre-applied to the schedule. I am ahead, not behind, so they come back to me
unless Anuj wants them. `bench/latency.py` is not covered by that contingency at
all and is simply assigned to two people.

**What I propose at the 10:00 standup.** In priority order:

1. **`protocol.py` and `fixtures.py` land today**, by Anuj if he can, by me if he
   cannot. Nothing else on anyone's board is worth more than unblocking two
   people who have been able to do nothing for three days.
2. **`core/grid.py` next**, because `core/cell.py`, my Day 7, the A/B wipe and
   the whole memory argument all sit behind it.
3. I take `traversability.py` against the documented cell fields with a test
   double in the meantime, so Day 7 is not lost waiting.

Days 4–6 landed early because the KITTI download ran unattended while I wrote
code — which is exactly what §4.1 said to do with it. That pattern is available
to everyone and costs nothing.

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

