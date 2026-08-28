# Work Distribution — AVR-25D · 6-Person Team

**SIH26053 · Adaptive Variable Resolution 2.5D LiDAR Mapping for Dynamic Environment Perception**

| | |
|---|---|
| Companion documents | [`PRD.md`](./PRD.md) · [`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md) |
| Phase 1 | Fri 28 Aug → **Thu 10 Sep 2026** — internal hackathon (PPT + video + prototype + live demo) |
| Phase 2 | Fri 11 Sep → Sun 20 Sep 2026 — SIH portal |
| Team | Sameer · Anuj · Shubham · Navya · Khanak · Veda |

---

## 1. Team at a glance

| Person | Track | Role | Primary directories |
|---|---|---|---|
| **Sameer** | Backend / DL | Grid engine + integration lead | `avr25d/core/`, `avr25d/server/`, `avr25d/decision/{costmap,planner,explain}.py` |
| **Anuj** | Backend / DL | Perception + benchmarking | `avr25d/perception/`, `avr25d/bench/`, `avr25d/io/`, `avr25d/decision/{traversability,tracker}.py` |
| **Shubham** | Frontend / web | Dashboard — 3D scene and views | `web/scene.js`, `web/views.js`, `web/palette.js` |
| **Navya** | Frontend / web | Dashboard — HUD, transport, decision panel | `web/main.js`, `web/hud.js`, `web/index.html` |
| **Khanak** | Non-tech | Scenario generation and ground truth | `matlab/`, `data/synthetic/` |
| **Veda** | Non-tech | Evidence, communication, submission | `docs/`, deck, video, run-book, submission |

Six people, six non-overlapping directories. Two people never edit the same file on the same
day, which is what makes daily merges to `main` cheap.

---

## 2. Ownership map

Every module has exactly one owner and one named backup. The backup is who picks it up if the
owner is ill, stuck, or pulled onto something urgent — decided now, calmly, rather than at
02:00 on Day 11.

| Module | Owner | Backup | Critical path? |
|---|---|---|---|
| `server/protocol.py` — **frozen Day 1** | Sameer | Anuj | **Yes — blocks 4 people** |
| `server/fixtures.py` | Sameer | Anuj | **Yes — unblocks the frontend** |
| `core/grid.py` | Sameer | Anuj | **Yes** |
| `core/cell.py` | Sameer | Anuj | **Yes** |
| `core/refine.py` | Sameer | Anuj | No |
| `server/app.py` | Sameer | Navya | Yes |
| `perception/geometric_seg.py` | Anuj | Sameer | **Yes — de-risks everything** |
| `perception/onnx_infer.py`, `range_proj.py` | Anuj | Sameer | No — cached mode covers it |
| `perception/cache.py`, `labelmap.py` | Anuj | Sameer | Yes |
| `io/kitti.py` | Anuj | Sameer | **Yes** |
| `decision/traversability.py`, `tracker.py` | Anuj | Sameer | No |
| `decision/costmap.py`, `planner.py`, `explain.py` | Sameer | Anuj | No |
| `bench/*` | Anuj | Sameer | Yes — Day 12 depends on it |
| `web/scene.js`, `views.js` | Shubham | Navya | **Yes** |
| `web/main.js`, `hud.js` | Navya | Shubham | **Yes** |
| `matlab/*` | Khanak | Sameer (seed) | No — KITTI is an independent path |
| Deck, video, submission | Veda | Khanak | **Yes — it is the deliverable** |

**The decision layer is deliberately not one person's.** Sameer and Anuj converge on it on
Day 7, after `core/` and `perception/` have both landed. Neither of them opens a second front
while the hard core is still moving.

---

## 3. Who unblocks whom

```
  Day 1, 14:00 ─ Sameer freezes protocol.py + fixtures.py
                              │
        ┌─────────────────────┴─────────────────────┐
        ▼                                           ▼
   Shubham + Navya build the ENTIRE dashboard   Sameer builds core/
   against fixtures — zero backend dependency   Anuj builds perception/
        │                                           │
        └─────────────────────┬─────────────────────┘
                              ▼
                 Day 11–12 ─ integration is a FLAG CHANGE
                            (--fixtures  →  --infer cached)
```

**The one hard blocker in the project** is `protocol.py` + `fixtures.py` on Day 1 afternoon.
Two people cannot start until it lands, so it is the highest-priority item on the board and
nothing else Sameer does on Day 1 comes before it.

Everything else is soft:

| If this is late… | …this still proceeds |
|---|---|
| ONNX model | `geometric_seg.py` feeds the whole pipeline |
| KITTI download | Synthetic scenes are a complete independent data path |
| `core/cell.py` | Frontend continues on fixtures |
| Synthetic scenes | KITTI drives everything except the hazard metrics |
| Decision layer | Views 1–3 and every memory/latency claim are unaffected |

---

## 4. Backend track

### 4.1 Sameer — Grid engine and integration lead

**Owns:** the mathematical core (`core/`), the wire protocol, the server, the planner, and the
integration of everyone else's work.

**Also responsible for:** running the daily 10:00 standup and the 21:00 integration
checkpoint; keeping `main` green; making the call on what gets cut; running the live demo.

Roughly 60% of the time is the grid engine and 40% is integration and unblocking. Days 11–12
are almost entirely integration. Do not take on a second module before Day 7.

| Day | Tasks | Acceptance criterion |
|---|---|---|
| **1 · Fri 28 Aug** | Repo scaffold, `requirements.txt`, `config.yaml`, `tools/ring_table.py`. **`protocol.py` frozen and `fixtures.py` pushed by 14:00** — before anything else. Hand the `lidar_raycast.m` seed to Khanak. Then start `core/grid.py`. | `pytest -q` green on Mac and Windows. Frontend pair unblocked by 14:00. |
| **2 · Sat 29 Aug** | Finish `core/grid.py`: ring table, `ring_of`, `cell_of`, `cell_centres`, `cell_extents`. Tests T-G1, T-G2, T-G3, T-G4. | `RingGrid` reports **662 rings and 705,771 cells**; T-G4 passes including its adversarial inputs. |
| **3 · Sun 30 Aug** | `core/cell.py`: SoA arrays, `accumulate` with `np.add.at` scatter-reduce, `z_ground` estimator, ring-neighbour table. `server/app.py` driving the real pipeline. | A real KITTI scan streams to the browser with `n_points_conserved == n_points`. |
| **4 · Mon 31 Aug** | `cell.analyse()`: slope, roughness, OVERHANG, NEGATIVE_OBSTACLE, STEP, VOID_UNOBSERVED, LOW_CONFIDENCE. | `S2` and `S3` hazard flags fire; `S1_flat_road` produces **zero** flags. |
| **5 · Tue 1 Sep** | `bench/baselines.py` and `bench/memory.py`. | Memory panel shows both baselines and the live ratio. |
| **6 · Wed 2 Sep** | `bench/latency.py`. Per-stage timing wired through the pipeline into `stats`. | Every `stats` latency field populated from real measurement. |
| **7 · Thu 3 Sep** | `decision/costmap.py` — polar → 160 × 160 ego-front Cartesian resample. | T-D3 passes — obstacles preserved within one 0.25 m cell. |
| **8 · Fri 4 Sep** | `decision/planner.py` (A*, primary + genuinely distinct alternative) and `decision/explain.py`. | Reroute on `S5` with a fully formatted reason string. |
| **9 · Sat 5 Sep** | `core/refine.py` — bounded refinement (FR-17, FR-18) **plus uncertainty-driven refinement** *[pulled forward]*. | A distant moving vehicle is visibly finer than the empty road beside it; T-R2 passes. |
| **10 · Sun 6 Sep** | `--replay` and `--record`. Record the demo sequence log early, so the fallback exists well before it is needed. | `--replay demo.log` runs the full sequence end to end. |
| **11 · Mon 7 Sep** | Final integration. Fix whatever the full bench run exposes. **Feature freeze 21:00.** Then: nothing new. | Full pipeline runs on KITTI and all synthetic scenes. |
| **12 · Tue 8 Sep** | Bug fixes only. Re-record the demo replay log against the frozen build. | Replay fallback verified on the demo machine. |
| **13 · Wed 9 Sep** | Run the demo. Nothing else. | Three clean rehearsals including both failure paths. |
| **14 · Thu 10 Sep** | Final rehearsal. Run the live demo. | Submitted. |

**Depends on:** Anuj for `io/kitti.py` (Day 2) and labels (Day 2).
**Unblocks:** everyone, on Day 1 at 14:00.

### 4.2 Anuj — Perception and benchmarking

**Owns:** everything that turns points into labels, and everything that turns runs into
numbers.

**First action of the entire sprint:** start the SemanticKITTI download. It is bandwidth-bound
rather than effort-bound, so it runs unattended in the background all day while you write
code. Starting it on Day 2 instead of Day 1 is the easiest way to lose the project.

| Day | Tasks | Acceptance criterion |
|---|---|---|
| **1 · Fri 28 Aug** | **08:00 — start the KITTI subset download** (seq 04, then 00, then 05; ~1000 scans, ~12 GB). Then begin `perception/geometric_seg.py`. | Seq 04 downloading. RANSAC ground fit working on a synthetic plane. |
| **2 · Sat 29 Aug** | Finish `geometric_seg.py`: RANSAC ground plane, Euclidean clustering, bbox classification. `io/kitti.py` readers. | 5-class labels on a real KITTI scan. |
| **3 · Sun 30 Aug** | `labelmap.py` (19→5 merge including the `moving-*` IDs). First labelled KITTI scan into the grid. | End-to-end: KITTI scan → labels → grid → browser. |
| **4 · Mon 31 Aug** | Acquire an ONNX SemanticKITTI checkpoint (Q-4). Export and int8-quantise. Begin `range_proj.py`. | Checkpoint obtained and its licence confirmed usable. |
| **5 · Tue 1 Sep** | `onnx_infer.py`. k-NN range-aware reprojection in `range_proj.py`. | T-P4 passes — 100% of points labelled, including those occluded in the range image. |
| **6 · Wed 2 Sep** | Network labels on real scans with measured CPU latency. **Kick off the label-cache build overnight.** | Network labels visibly better than geometric on the same scan; both modes selectable. |
| **7 · Thu 3 Sep** | `decision/traversability.py` and `decision/tracker.py`. Verify the overnight label cache. | Stable track ID across all 40 `S5` frames; speed within 0.5 m/s of 8.0 m/s. |
| **8 · Fri 4 Sep** | `bench/distance_bins.py` and `bench/hazard.py`. | Binned mIoU computed; hazard scoring runs against `GROUND_TRUTH.md`. |
| **9 · Sat 5 Sep** | Assemble the 5-class fine-tuning split. **Resolve Q-1 definitively** — is the Windows GPU usable? | Q-1 answered and shared with the team. Fine-tuning split assembled. |
| **10 · Sun 6 Sep** | Perception improvement *[pulled forward]*: GPU fine-tune if Q-1 allows, otherwise CPU decoder-head-only fine-tune plus confidence calibration. Run overnight. | A measured before/after mIoU comparison exists, whichever branch was taken. |
| **11 · Mon 7 Sep** | `bench/report.py`. **First full `make bench`.** Multi-sequence evaluation *[pulled forward]* with per-sequence variance. | Complete `results.json` with every section populated. |
| **12 · Tue 8 Sep** | Authoritative benchmark runs: ≥200 scans for latency, full subset for accuracy, all scenes for hazards. Hand `results.json` to Veda. | Final `results.json` handed over. **No changes after handover.** |
| **13 · Wed 9 Sep** | Bug fixes only. Standby for rehearsal support. | — |
| **14 · Thu 10 Sep** | Demo support. | — |

**Depends on:** Sameer for `protocol.py` (Day 1), `CellGrid` (Day 3).
**Unblocks:** Sameer on Day 3 (readers and labels), Veda on Day 12 (all numbers).

**If the ONNX checkpoint does not materialise by Day 6 evening:** stop looking. The geometric
segmenter carries the demo, and the deck says "the pipeline is model-agnostic; we demonstrate
with a classical segmenter and a range-image CNN" — which is true, defensible, and a stronger
position than a broken model dependency in the final week.

---

## 5. Frontend track

Both frontend developers work entirely against `fixtures.py` from Day 1 afternoon. Neither
imports backend code, and neither waits for a backend feature. On Day 11–12, integration is
changing `--fixtures` to `--infer cached`.

**Shared rule:** `web/palette.js` is the single source of class colours. Nobody hard-codes a
hex value anywhere else, or the two views will disagree in front of a judge.

### 5.1 Shubham — 3D scene and views

**Owns:** everything the judge actually looks at.

| Day | Tasks | Acceptance criterion |
|---|---|---|
| **1 · Fri 28 Aug** | Three.js scene, vendored `three.module.js` (no CDN), orbit camera, ground reference, `palette.js`. From 14:00: render fixture cells as one `InstancedMesh`. | ~50,000 fixture cells render at interactive frame rate. |
| **2 · Sat 29 Aug** | Class colouring, elevation-shading toggle, correct per-instance sizing from `cell_extents`. | Cells correctly sized at every range — no slivers, no gaps. |
| **3 · Sun 30 Aug** | View 1 (raw cloud) and View 3 (adaptive grid) on real streamed frames. | Views 1 and 3 render real streamed frames, class-coloured. |
| **4 · Mon 31 Aug** | View 2 — the uniform 5 cm grid, needed for the comparison. | Uniform view renders the same scan as View 3. |
| **5 · Tue 1 Sep** | **The A/B wipe** (FR-29) and the ring overlay (FR-27). The highest-value visual in the submission. | Draggable divider shows **16,000,000 vs 705,771** live on the same scan. |
| **6 · Wed 2 Sep** | Wipe polish. Performance pass on instance count. | No frame drops while dragging the divider. |
| **7 · Thu 3 Sep** | View 4 scaffold: track markers and predicted trajectories. | Tracks visible and individually identifiable. |
| **8 · Fri 4 Sep** | View 4 complete: routes, risk shading. | Reroute legible from three metres away. |
| **9 · Sat 5 Sep** | LOD tuning. Verify ≥30 FPS at 100k instances (FR-30). | T-V6 passes on the demo machine. |
| **10 · Sun 6 Sep** | Visual polish. Verify on the actual demo machine at projector resolution. | Renders correctly at projector resolution. |
| **11 · Mon 7 Sep** | Final polish. Demo keystroke sequence verified end to end. | Every run-book keystroke works. |
| **12 · Tue 8 Sep** | Bug fixes only. | Zero console errors across all four views. |
| **13 · Wed 9 Sep** | Rehearsal support. | — |
| **14 · Thu 10 Sep** | Demo support. | — |

**The A/B wipe is the single most persuasive object in the whole submission.** Same scan, same
camera, a divider you drag, live cell counts on both sides. It converts "22.67× reduction"
from a claim into something the judge watches happen. Build it on Day 5, not in the final week.

**Design notes.** Judged on a projector, possibly in a bright room. High contrast, thick
lines, large HUD type. Verify the class palette is distinguishable in greyscale — if it
survives greyscale it survives a bad projector and it survives colour-blind judges.

### 5.2 Navya — HUD, transport, decision panel

**Owns:** the numbers on screen and the plumbing that gets them there.

| Day | Tasks | Acceptance criterion |
|---|---|---|
| **1 · Fri 28 Aug** | `index.html` shell, layout, WebSocket client, binary `FrameMessage` decode into typed arrays, HUD skeleton with live fixture numbers. | HUD updates continuously from fixture frames. |
| **2 · Sat 29 Aug** | View switching, frame stepping, pause. | All controls work against fixtures. |
| **3 · Sun 30 Aug** | HUD wired to real `stats` rather than fixtures. | Real numbers displayed; no `NaN`, no `undefined`. |
| **4 · Mon 31 Aug** | Memory comparison panel, reduction factor, per-stage latency bars. | Memory panel shows both sides and the live ratio. |
| **5 · Tue 1 Sep** | **Perception-mode badge** (FR-6). Track list panel scaffold. | Badge always shows whether perception is `live`, `cached` or `geometric`. |
| **6 · Wed 2 Sep** | Full HUD per FR-28 — every field populated from real frames. | Every FR-28 field populated from real frames. |
| **7 · Thu 3 Sep** | Decision panel scaffold: route, risk, ETA, reason string. | Panel renders from both fixtures and real frames. |
| **8 · Fri 4 Sep** | Decision panel complete and readable at projector resolution. | Reason string readable at projector resolution. |
| **9 · Sat 5 Sep** | Refinement visualisation — sub-cells visibly distinct from their parents. | Refined cells visually distinguishable from unrefined ones. |
| **10 · Sun 6 Sep** | Polish. Responsive layout at the demo machine's real resolution. | Layout correct at the demo machine's resolution. |
| **11 · Mon 7 Sep** | Keyboard shortcuts for the entire demo sequence (`1`–`4`, `R`, `W`, `H`, `L`). | Every run-book keystroke works. |
| **12 · Tue 8 Sep** | Bug fixes only. | T-V4 passes — no undefined fields. |
| **13 · Wed 9 Sep** | Rehearse the keystroke sequence with Sameer. | Three clean rehearsals. |
| **14 · Thu 10 Sep** | Demo support. | — |

**The perception-mode badge is a requirement, not decoration** (FR-6, PRD §7.1). It always
shows whether segmentation is `live`, `cached` or `geometric`. Showing it is what makes the
demo honest, and an evaluator who sees you display it will trust the rest of your numbers
more, not less.

**Never compute a displayed number in the browser.** Everything comes from `stats` in the
`FrameMessage`. One source of truth means the HUD and `results.json` can never disagree.

---

## 6. Non-technical track

Two workstreams that are genuinely load-bearing. Khanak produces the only data in the project
with exact ground truth — without it, hazard preservation is a demo rather than a measurement,
and hazard preservation is the core argument for 2.5D over 2D. Veda owns the artefacts that
are literally what gets submitted.

### 6.1 Khanak — Scenario generation and ground truth

**Owns:** `matlab/` and `data/synthetic/`.

**What this actually is.** A LiDAR sensor works by firing laser beams in known directions and
timing the reflection. You are going to simulate that in software: for each of 64 × 1800
directions, compute where that beam would hit a simple shape (a flat plane, a box, a cylinder),
and record the hit point. The result is a synthetic point cloud that looks like real LiDAR
data — and because you built the scene, **you know exactly where every object is, to the
millimetre.** Real datasets never give you that. It is why your scenes are the only way to
measure whether the system correctly reports a pothole as 0.22 m deep rather than merely
"noticing something".

**Toolchain — no licence problem.** Everything is written in the base MATLAB language, using
no toolboxes. That means the identical files run in **GNU Octave**, which is free and
open-source. Use whichever you can get:

1. **GNU Octave** (recommended, free) — download from `octave.org`, install, done. All scripts
   run unmodified.
2. **MATLAB Online** free tier — `matlab.mathworks.com`, sign in with a student account.

You do not need Automated Driving Toolbox or Lidar Toolbox. If anyone suggests adding a
toolbox function to these scripts, say no — it breaks Octave compatibility and puts licensing
back on the critical path.

**Day 1 onboarding, in order:**

1. Install Octave (or open MATLAB Online). Confirm `disp('hello')` runs.
2. Sameer gives you `lidar_raycast.m` — the ray-casting engine, already written. You do not
   need to write it or fully understand its internals. You need to run it and read its inputs.
3. Run `run_all_scenes.m`. It should produce `S1_flat_road`.
4. Open `scenes/S1_flat_road.csv`. This is the scene description — **one shape per row**:

   ```csv
   type,   x,     y,     z,     sx,   sy,   sz,   class, note
   plane,  0,     0,     0,     200,  200,  0,    1,     road surface
   box,    12.0, -0.5,  -0.22,  1.4,  1.0,  0.22, 0,     pothole (negative)
   box,    25.0,  0.0,   3.10,  6.0,  0.4,  0.5,  3,     gantry beam, 3.10 m clearance
   cyl,    25.0, -3.0,   1.55,  0.3,  0.3,  3.10, 3,     gantry support post
   ```

   `x, y, z` is the centre in metres (`x` forward, `y` left, `z` up, sensor at the origin
   1.7 m above the road). `sx, sy, sz` are the dimensions. `class` is the semantic label from
   `PRD.md` §6.1 — `1` drivable, `2` non-drivable terrain, `3` static obstacle, `4` dynamic
   object, `0` void.

5. **Building a scene means editing this spreadsheet.** Change a number, re-run, look at the
   output. That is the whole workflow.

**Your five scenes and their exact specifications:**

| Scene | Content | Exact ground truth to record |
|---|---|---|
| `S1_flat_road` | Flat 200 × 200 m road plane, no hazards | Nothing. This is the control — the system must find **zero** hazards here. |
| `S2_pothole` | Road plus a depression 12 m ahead, 1.4 m across, **0.22 m deep** | depth = 0.220 m, centre = (12.0, −0.5), extent = 1.4 × 1.0 m |
| `S3_overhang` | Road plus a gantry beam with **3.10 m clearance**, plus two support posts | clearance = 3.100 m, beam at x = 25.0 m, road beneath must stay drivable |
| `S4_curb` | Road plus a **0.15 m** kerb along the right edge | height = 0.150 m, edge at y = −4.0 m |
| `S5_crossing_truck` | 40 frames; a 7 × 2.5 × 3 m box crossing left to right at **8.0 m/s** | speed = 8.00 m/s, crossing x = 18.0 m, entry at t = 0.5 s |

The bolded numbers are the answer key. The system's job is to recover them from the point
cloud, and the error between its answer and yours is the hazard-preservation metric in
`PRD.md` §11.4. Record them in `matlab/GROUND_TRUTH.md` and hand that file to Anuj on Day 8.

| Day | Tasks | Acceptance criterion |
|---|---|---|
| **1 · Fri 28 Aug** | Install Octave or MATLAB Online. Get `lidar_raycast.m` running. Produce `S1_flat_road`. | `S1` `.bin` and `.label` files exist and Anuj's reader opens them. |
| **2 · Sat 29 Aug** | `S2_pothole`. Verify the depression is visible in the point cloud, not just in the CSV. | `S2` loads; the pothole is visible in the dashboard. |
| **3 · Sun 30 Aug** | `S3_overhang` with 3.10 m clearance. | `S3` loads; the gantry is at exactly 3.10 m. |
| **4 · Mon 31 Aug** | `S4_curb` at 0.15 m. | Kerb visible in the point cloud; height exactly 0.15 m. |
| **5 · Tue 1 Sep** | Begin `S5_crossing_truck` (40 frames, moving box). | The truck moves between frames. |
| **6 · Wed 2 Sep** | Finish `S5_crossing_truck`. | The 40-frame sequence plays end to end. |
| **7 · Thu 3 Sep** | Regenerate S1–S5 with final parameters. Begin `GROUND_TRUTH.md`. | All five scenes present in `data/synthetic/`. |
| **8 · Fri 4 Sep** | Deliver `GROUND_TRUTH.md` to Anuj. | Ground-truth table delivered and accepted by Anuj. |
| **9 · Sat 5 Sep** | Adversarial scene: pothole partially occluded by a parked vehicle. | Scene generates and loads in the pipeline. |
| **10 · Sun 6 Sep** | Adversarial scene: low-clearance tunnel with a curb inside it. | Scene generates and loads in the pipeline. |
| **11 · Mon 7 Sep** | Cross-check `GROUND_TRUTH.md` against the hazard benchmark output. | Every hazard number reconciled between the two sources. |
| **12 · Tue 8 Sep** | **Cross-check every number in Veda's deck against `results.json`.** | Zero unverified numbers in the deck. |
| **13 · Wed 9 Sep** | Finalise the demo run-book with Sameer. | Run-book complete, including both failure paths. |
| **14 · Thu 10 Sep** | Demo support. | — |

**If Octave will not install:** tell Sameer at standup, not later. There is a Python fallback
ray-caster that produces identical outputs; it costs Sameer two hours and it is a fine
outcome. What is not fine is losing two days to a silent install problem. Your scenes are on
the critical path for §11.4 of the PRD.

**Why S1 matters as much as the others.** It is easy to build a detector that flags hazards
everywhere. `S1` is the scene where the correct answer is "nothing here". If the system raises
a single hazard flag on flat road, a threshold is wrong, and it is far better to find that on
Day 4 than in front of a judge.

### 6.2 Veda — Evidence, communication, and submission

**Owns:** everything that is actually submitted. The code is the means; the deck, the video
and the submission are the deliverable.

**The rule that matters most:** *no number reaches a slide except from `results.json`.* Anuj
generates it, you consume it, Khanak cross-checks it. If a number is not in that file, it does
not go in the deck, the video narration, or anything said out loud to a judge. Placeholders
stay as `_measured_` until Day 12. A single unverifiable number is the fastest way to lose a
technically strong submission.

| Day | Tasks | Acceptance criterion |
|---|---|---|
| **1 · Fri 28 Aug** | Resolve Q-2 (deck template, slide count) and Q-3 (demo hardware) from `PRD.md` §14.2 — the team's plans depend on the answers. Deck outline. Begin prior-art search. | Q-2 and Q-3 answered and shared with the team. |
| **2 · Sat 29 Aug** | Prior-art and novelty write-up (§6.2.2). Draft slides 1–2. | Novelty statement written: what exists, what we do differently. |
| **3 · Sun 30 Aug** | Slides 3–4. Begin the judge Q&A bank. | Slides 3–4 drafted. |
| **4 · Mon 31 Aug** | Slide 5. Full deck draft with `_measured_` placeholders intact. | Complete deck; every number still a placeholder. |
| **5 · Tue 1 Sep** | Video script, timed to 3:00, beats matched to the run-book. | Script timed to 3:00 with 10 seconds spare. |
| **6 · Wed 2 Sep** | Q&A bank to 12 questions. Rehearse narration against the draft deck. | 12 questions, each with the location of its answer. |
| **7 · Thu 3 Sep** | Deck to near-final. Q&A bank to 20 questions. | 20 questions. Deck near-final. |
| **8 · Fri 4 Sep** | Assemble the demo run-book with Sameer. | Run-book drafted with Sameer. |
| **9 · Sat 5 Sep** | **Record a rough-cut video against the current build** — find problems while they are still fixable. | Rough cut exists; problem list produced and circulated. |
| **10 · Sun 6 Sep** | Fix everything the rough cut exposed. | Problem list closed. |
| **11 · Mon 7 Sep** | Deck final except for `_measured_` placeholders. | Deck final; placeholders intact and clearly marked. |
| **12 · Tue 8 Sep** | **Fill every placeholder from `results.json` only.** | Zero placeholders remain; every number traces to `results.json`. |
| **13 · Wed 9 Sep** | Record and edit the final 3-minute video. Finalise the deck. | Video rendered and stored **locally** on the presenting laptop. |
| **14 · Thu 10 Sep** | **Submit.** Deck, video, documentation. | Submission confirmed. |

#### 6.2.1 Deck structure — five slides, SIH format

| Slide | Content | Where it comes from |
|---|---|---|
| **1 · Idea / Solution** | The foveation analogy in one line. The 2D-vs-3D dilemma. What we built. The system diagram. | `PRD.md` §1, §5 |
| **2 · Technical Approach** | Pipeline. The ring-sector grid: 662 rings, 5 cm → 50 cm, isotropic cells, closed-form O(1) index. **Constant 0.286° far-field bins matched to sensor sampling.** Tech stack. | `IMPLEMENTATION_PLAN.md` §3 |
| **3 · Feasibility & Viability** | Working prototype, measured numbers, cross-platform CPU-only operation. Risks and how they were handled — a judge trusts a team that names its risks. | `PRD.md` §13, `results.json` |
| **4 · Impact & Benefits** | 22.67× cell reduction → memory and downstream compute. Hazards a 2D grid destroys, preserved and measured. Explainable routing for logistics. Defence and IDEX relevance. | `PRD.md` §10, §11 |
| **5 · Research & References** | SemanticKITTI, RangeNet++/SalsaNext, elevation-mapping and traversability literature, the PS itself. | §6.2.2 |

**Slide 2 is where the submission is won.** Every team will show a point cloud and a
dashboard. The specific, defensible claims are: the closed-form index that makes alignment
error impossible by construction, isotropic cells at every range, and far-field resolution
matched to the sensor's own angular sampling rather than chosen arbitrarily. Those three are
the differentiators and they belong in large type.

#### 6.2.2 Prior-art search — what to look for

Establish what exists so novelty can be stated precisely rather than vaguely. Search terms:
*multi-resolution occupancy grid*, *log-polar grid mapping*, *elevation map robot navigation*,
*2.5D traversability mapping*, *foveated LiDAR perception*, *variable resolution costmap*,
*range image semantic segmentation LiDAR*.

Known relevant work to position against: Wavemap and OctoMap (multi-resolution 3D, but
volumetric and not foveated by range); ETH Zurich's robot-centric elevation mapping (2.5D with
uncertainty, but uniform resolution); RangeNet++ and SalsaNext (range-image segmentation, which
we use rather than claim); classical polar occupancy grids in early ADAS (polar, but fixed
sector count and no semantics).

For each: one line on what it does and one on what we do differently. The honest novelty claim
is the **combination** — semantic labels, an isotropic range-adaptive polar 2.5D representation
with closed-form indexing, hazard preservation validated against exact ground truth, and a
deterministic explainable decision layer on top — not any single component. Claiming to have
invented range-image segmentation would be caught immediately and would cost credibility on
everything else.

#### 6.2.3 Video — 3 minutes

| Time | Content |
|---|---|
| 0:00–0:20 | Problem. Millions of points per second; 2D grids destroy height. |
| 0:20–0:40 | The foveation idea, with the human-vision analogy. |
| 0:40–1:30 | Live screen capture following the run-book (`IMPLEMENTATION_PLAN.md` §10). |
| 1:30–2:10 | Hazards: overhang and pothole, with measured numbers on screen. |
| 2:10–2:40 | Dynamic object, reroute, the explanation string. |
| 2:40–3:00 | Results summary. Every number from `results.json`. |

Record screen capture at the demo machine's native resolution. Narrate over it afterwards
rather than live — retakes are cheap, and a clean audio track is worth more than spontaneity.

#### 6.2.4 Judge Q&A bank — build to 20 questions

The ones that will certainly be asked, with the answer's location:

| Question | Answer lives in |
|---|---|
| "How is this different from just downsampling far-away points?" | `IMPLEMENTATION_PLAN.md` §3.4 — resolution is matched to the sensor's angular sampling, and the map retains full elevation and semantics per cell rather than discarding points. |
| "Doesn't the coarse far field lose critical information?" | `PRD.md` §11.3, distance-binned accuracy — measured, not asserted. |
| "How do you know no points are lost in the projection?" | The conservation assertion, every frame, plus test T-G4 with adversarial inputs. |
| "Why not a sparse voxel hash? Isn't that smaller?" | `PRD.md` §10.1 — stated honestly: on raw bytes for one scan it can be. We win on occupied-cell count, on deterministic O(1) access with no worst case, and on 22.67× less downstream compute. |
| "Is the segmentation running live?" | The HUD says so, always. Cached mode drives the demo; live CPU inference latency is measured and reported separately; embedded-GPU figures are labelled projected. |
| "What happens on a flyover or multi-level structure?" | `PRD.md` A-3 — a known limit of any 2.5D height field; `z_ground` plus clearance still captures what the planner needs. |
| "Why 5 cm and 50 cm?" | They are given by PS-6. The `s(r) ∝ r` interpolation between them is our choice, and §3.2 shows it is the one that makes both endpoints exact. |
| "Could this run on vehicle hardware?" | It runs CPU-only today at the measured rate; the design has fixed pre-allocated memory and no GC pressure in the hot path. |

Rehearse these with the team on Day 11. The best answer to a hard question is a slide number.

---

## 7. Working agreements

- **Standup 10:00, 15 minutes.** What landed, what is blocked, what lands today. Blocked is
  said out loud, at standup — not discovered at midnight.
- **Integration checkpoint 21:00.** `main` must be green. Whoever broke it fixes it before
  sleeping; a red `main` blocks five people.
- **Branches live less than a day.** No overnight branches. A two-week project cannot absorb a
  two-day merge.
- **Interfaces before bodies.** Push the signature and a correctly shaped stub, then fill it in.
- **`protocol.py` is frozen after Day 1.** Changes need Sameer and a message to everyone.
- **No number without a measurement.** Deck, video, and anything said to a judge.
- **Feature freeze 21:00 Day 11 (Mon 7 Sep).** Not negotiable. Cutting features is how
  fixed-deadline projects ship.
- **Every module has a named backup** (§2). If you are stuck for more than two hours, escalate
  to Sameer rather than grinding.

### Escalation

| Situation | Action |
|---|---|
| Stuck > 2 hours | Message Sameer. Do not grind silently. |
| `main` red | Whoever broke it fixes it now; everything else waits. |
| A Day-N exit criterion will be missed | Say so at that morning's standup, not that evening. |
| Two people need the same file | Sameer decides who edits and who waits. |
| Scope disagreement | Sameer decides. §12.1 of the PRD is the reference. |

---

## 8. Load balance

| Person | Days 1–3 · Foundations | Days 4–8 · Perception + decisions | Days 9–11 · Depth | Days 12–14 · Evidence |
|---|---|---|---|---|
| Sameer | **Heavy** — protocol, fixtures, grid, cells | Heavy — analysis, costmap, planner | **Heavy** — refinement, integration, freeze | Medium — demo only |
| Anuj | Heavy — download, segmenter, readers | **Heavy** — ONNX, tracker, benchmarks | Heavy — fine-tune, multi-sequence eval | **Heavy** — authoritative runs |
| Shubham | Medium — scene, instancing | **Heavy** — uniform view, wipe, View 4 | Medium — LOD, polish | Light — bug fixes |
| Navya | Medium — client, HUD | Medium — panels, badge, decision panel | Medium — refinement view, shortcuts | Light — rehearsal |
| Khanak | Medium — setup, S1, S2 | Medium — S3, S4, S5 | Medium — adversarial scenes, cross-check | **Heavy** — deck verification, run-book |
| Veda | Light — questions, outline | Medium — deck, script, Q&A bank | Medium — rough cut, fixes | **Heavy** — numbers, video, submission |

**Known concentration risk.** Sameer owns the protocol, the grid, the cells, the planner, the
integration and the demo. That is a lot on one person, and it is a deliberate trade — those
pieces are tightly coupled and splitting them would cost more in coordination than it saves in
load. The mitigation is that Anuj is the named backup on every one of them and reviews each as
it merges, so the bus factor is two and not one.

**If Navya finishes the HUD early on Day 5**, the highest-value place to help is Shubham on the
A/B wipe. It is the most persuasive artefact in the submission and the one most worth two
people.

---

## 9. Phase 2 — 4 to 20 September 2026

Ten days, calmer pace, same ownership.

| Person | Phase 2 focus |
|---|---|
| **Sameer** | Uncertainty-driven refinement; temporal accumulation with ego-motion compensation; ablation studies |
| **Anuj** | Fine-tune the network on the 5-class taxonomy; expand evaluation across sequences; per-sequence variance |
| **Shubham** | Timeline scrubber; side-by-side scene comparison; exportable evidence screenshots |
| **Navya** | Metrics history plots; recorded-run comparison view; UI for the expanded evaluation |
| **Khanak** | Adversarial scenes: multiple simultaneous hazards, occluded pothole, low-clearance tunnel, sparse-return conditions |
| **Veda** | Full technical report; final SIH deck; portal submission on 20 Sep |

---

## 10. Day 1 checklist

Print this. Tick it tonight.

- [ ] **Anuj** — KITTI download started (do this first, before anything else)
- [ ] **Sameer** — `protocol.py` frozen and `fixtures.py` pushed **by 14:00**
- [ ] **Sameer** — `lidar_raycast.m` seed handed to Khanak
- [ ] **Shubham + Navya** — dashboard rendering fixture cells by end of day
- [ ] **Khanak** — Octave or MATLAB Online installed and running
- [ ] **Veda** — Q-2 (deck template) and Q-3 (demo hardware) answered
- [ ] **Everyone** — repo cloned, `pytest -q` green on your own machine
- [ ] **Sameer** — cross-platform smoke test passed on both Mac and Windows
- [ ] `RingGrid` reports **662 rings, 705,771 cells** — the number that says the core is real
