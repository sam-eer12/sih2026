# Project Flow & Timeline — AVR-25D

> Who does what, in what order, and why the order matters.
> Read this alongside `UNDERSTANDING_THE_PROJECT.md`.

---

## The Core Idea Behind the Timeline

Six people working in parallel for 14 days. The only way this works is if nobody
is ever waiting for someone else. The plan achieves this through two devices:

1. **`protocol.py` + `fixtures.py` on Day 1 afternoon.** These define the message
   format the backend sends to the frontend. Once they exist, the two frontend
   developers (Shubham, Navya) can build the entire dashboard against fake-but-
   valid data — with zero dependency on the real backend. Integration on Day 12
   becomes a one-line flag change, not a two-day fire drill.

2. **The geometric fallback segmenter on Day 1–2.** Even before any neural network,
   the pipeline has a working way to label every point. So the grid, the server,
   and the dashboard can all be tested on real data from Day 3 onward.

Everything else flows from these two decisions.

---

## The Dependency Graph

Read arrows as "is needed by":

```
  Day 1 ─ Anuj: protocol.py + fixtures.py
                │
        ┌───────┴───────┐
        │               │
        ▼               ▼
  Shubham: viewer   Navya: platform
  (from Day 1 pm)   (from Day 1 pm)
        │               │
        └───────┬───────┘
                │
                ▼
         Day 11: integration = flag change
                 (--fixtures → --infer cached)

  Day 1 ─ Sameer: geometric_seg.py
  Day 2 ─ Anuj:   core/grid.py
  Day 3 ─ Anuj:   core/cell.py   ─────────────────────────────┐
  Day 3 ─ Sameer: labelmap.py                                  │
                │                                              │
                ▼                                              │
  Day 3: First real scan → labels → grid → browser             │
                │                                              │
  Day 4 ─ Anuj: cell.analyse() (hazard flags) ◄───────────────┘
                │
  Day 7 ─ Sameer: traversability.py + tracker.py
  Day 7 ─ Anuj:  costmap.py
  Day 8 ─ Anuj:  planner.py + explain.py
                │
  Day 8: Full decision pipeline working (reroute on S5)
                │
  Day 11: make bench → complete results.json
  Day 12: Authoritative numbers → Veda fills placeholders
  Day 13: Video + rehearsals
  Day 14: SUBMIT
```

---

## The 14-Day Sprint in Detail

The sprint is divided into 5 blocks, each with a clear theme.

---

### Block A — Days 1–3 (Fri 28 Aug – Sun 30 Aug)
**Theme: Foundation and de-risking**

The goal of this block is to make sure nothing can go wrong later. By end of
Day 3, a real scan should be visible in the browser. Every other workstream
should be unblocked by end of Day 1.

---

#### Day 1 — Friday 28 Aug — UNBLOCK EVERYONE

This is the most important day of the sprint. Two things MUST happen by 14:00.

**Sameer**
- First action of the day (8:00 AM): start downloading SemanticKITTI sequence 04.
  It takes ~2 hours and runs unattended. Starting this on Day 2 instead is the
  easiest way to lose the whole project.
- Then: begin `geometric_seg.py` (the RANSAC ground-plane segmenter).
- Exit: RANSAC ground plane fitting works on a synthetic flat plane.

**Anuj** ← your most critical day
- Set up the repo (`requirements.txt`, `config.yaml`, `tools/ring_table.py`).
- Write `server/protocol.py` — the FrameMessage binary format definition. FREEZE
  IT. Push it. **This must land by 14:00.**
- Write `server/fixtures.py` — generates synthetic-but-schema-valid frames.
  **This must land by 14:00.**
- Then start `core/grid.py`.
- Exit: Shubham and Navya can both render from your fixtures by 14:00.

**Navya**
- First action: create the Firebase project and Atlas M0 cluster. These have
  lead time (account verification, etc.) so they go first.
- Then: `create-next-app` with TypeScript + Tailwind, `.env.local.example`,
  and `lib/protocol.ts` that decodes your fixture frames.
- Exit: Firebase and Atlas exist. `pnpm dev` serves a page.

**Shubham**
- Set up Three.js inside a `useRef` canvas: renderer, orbit camera, ground plane,
  `lib/palette.ts` (the colour table).
- From 14:00 (once Anuj's fixtures land): render ~50,000 fixture cells as one
  `InstancedMesh`.
- Exit: 50,000 cells render at interactive frame rate from fixtures.

**Khanak**
- Install MATLAB or Octave. Determine TODAY whether Simulink is available — tell
  the team either way at standup. Don't spend days later chasing a licence.
- Read PRD §16. Draft the payload architecture block diagram.

**Veda**
- Confirm deck template and submission format (Q-2, Q-3). Share answers with team.
- Deck outline. Start prior-art search.

---

#### Day 2 — Saturday 29 Aug — THE GRID EXISTS

**Anuj**
- Finish `core/grid.py`: ring table, `ring_of`, `cell_of`, `cell_centres`,
  `cell_extents`.
- Run tests T-G1 through T-G4.
- Exit: `RingGrid` reports exactly **662 rings and 705,771 cells**. T-G4 passes
  including adversarial inputs (points at exactly ring boundaries, theta = 0,
  theta = 2π, etc.).

**Sameer**
- Finish `geometric_seg.py`: full RANSAC + Euclidean clustering + bounding box
  classifier.
- Write `io/kitti.py`: readers for `.bin` and `.label` files.
- Exit: 5-class labels on a real KITTI scan.

**Navya**
- Firebase Auth: login page, email/password + Google sign-in, middleware that
  blocks unauthenticated access to `/dashboard` (FR-36).
- `lib/ws.ts` with exponential-backoff reconnect.
- Exit: T-W1 passes — unauthenticated users cannot reach `/dashboard`.

**Shubham**
- Class colouring per `palette.ts`, elevation-shading toggle, correct per-instance
  sizing from `cell_extents`.
- Exit: Cells correctly sized at every range — no slivers, no gaps.

**Khanak**
- Write `link_budget.m`: received optical power vs. range, for reflectivities
  0.1–0.9. First numbers out.

**Veda**
- Prior-art and novelty write-up. Draft slides 1–2.

---

#### Day 3 — Sunday 30 Aug — FIRST REAL SCAN END-TO-END

**Anuj**
- `core/cell.py`: SoA arrays, `accumulate` scatter-reduce using `np.add.at`,
  `z_ground` estimator, ring-neighbour table.
- `server/app.py`: FastAPI server driving the real pipeline (perception →
  grid → cell → FrameMessage → WebSocket).
- Exit: A real KITTI scan, geometrically segmented, projected into the adaptive
  grid, rendering class-coloured in the browser, with `n_points_conserved ==
  n_points` visible on the HUD.

**Sameer**
- `perception/labelmap.py`: maps 19 SemanticKITTI classes → 5 AVR classes,
  keeping `moving-*` labels separate.
- `avr25d/synth/` ray-caster + scenes S1, S2, S3. Anuj needs these tomorrow
  for hazard flag testing.
- Exit: Scenes S1–S3 load in the pipeline and produce correct synthetic scans.

**Shubham**
- View 1 (raw point cloud) and View 3 (adaptive grid) rendering real streamed
  frames from the server.
- Exit: Both views render real streamed frames, class-coloured.

**Navya**
- HUD wired to real `stats` from FrameMessage. View switching, frame stepping, pause.
- Exit: Real numbers on the HUD; no `NaN`, no `undefined`.

**Khanak**
- `range_accuracy.m`: timing jitter and walk error → range error budget.

**Veda**
- Slides 3–4. Begin the judge Q&A bank. Start the payload design report skeleton.

---

### Block B — Days 4–6 (Mon 31 Aug – Wed 2 Sep)
**Theme: Perception and the memory evidence**

By end of this block: the neural network is running, the A/B wipe is live, and
hazard flags are firing on synthetic scenes.

---

#### Day 4 — Monday 31 Aug — HAZARDS + NEURAL NET BEGINS

**Anuj**
- `core/cell.py` → `cell.analyse()`: slope, roughness, OVERHANG,
  NEGATIVE_OBSTACLE, STEP, VOID_UNOBSERVED, LOW_CONFIDENCE flags.
- Exit: `S2_pothole` fires `NEGATIVE_OBSTACLE`. `S3_overhang` fires `OVERHANG`.
  `S1_flat_road` produces ZERO flags (the false-positive test).

**Sameer**
- Acquire the ONNX SemanticKITTI model checkpoint (already done: SqueezeSegV2
  from lidar-bonnetal, MIT licence, direct HTTP download).
- Export to ONNX, apply int8 quantisation (already done and measured).
- Begin `perception/range_proj.py`.
- Exit: ONNX checkpoint obtained, licence confirmed, int8 export verified.

**Shubham**
- View 2: the uniform 5 cm grid (needed for the side-by-side comparison).
- Exit: Uniform view renders the same scan as View 3.

**Navya**
- `lib/mongo.ts` (module-scoped cached MongoClient — NEVER create per request)
  and `app/api/runs/route.ts` with `requireUser` token verification (FR-37).
- Exit: T-W2 passes — unverified tokens are rejected before any MongoDB call.

**Khanak**
- `snr_sweep.m`: sweep over aperture, reflectivity and sunlight background.

**Veda**
- Slide 5. Full deck draft with `_measured_` placeholders intact (no real numbers
  yet — they don't exist yet and must not be made up).

---

#### Day 5 — Tuesday 1 Sep — THE MONEY SHOT

**Shubham** ← most important task of your whole sprint
- Build the **A/B wipe** (FR-29) and the ring overlay (FR-27).
- The wipe is a draggable divider between the uniform grid and the adaptive grid
  on the SAME scan, with live cell counts on both sides: **16,000,000 vs 705,771**.
  This is the single most persuasive object in the submission. Build it today,
  not the week of the demo.
- Exit: Dragging the divider shows the counts live. No frame drops while dragging.

**Anuj**
- `bench/baselines.py` (memory models for B0–B4 baselines).
- `bench/memory.py` (actual cell counts and byte measurements).
- Exit: Memory panel shows both baselines and the live reduction ratio.

**Sameer**
- `onnx_infer.py`: OnnxSegmenter wrapper.
- k-NN range-aware reprojection in `range_proj.py`.
- Scenes S4 (curb) and S5 (crossing truck, 40 frames).
- Exit: T-P4 passes — 100% of points labelled including occluded ones. All 5 scenes exist.

**Navya**
- MongoDB collections + indexes created.
- `app/api/scenes/route.ts` — register scene ground truth (FR-40).
- Exit: T-W5 passes — every scene's ground truth matches its CSV exactly.

**Khanak**
- `scan_coverage.m`: MEMS scan pattern → angular sampling → point density vs. range.

**Veda**
- Video script timed to exactly 3:00, beats matched to the run-book.

---

#### Day 6 — Wednesday 2 Sep — PERCEPTION LANDS

**Sameer**
- Network labels on real scans, with measured CPU latency.
- Kick off the label-cache build overnight (runs unattended).
- Exit: Network labels visibly better than geometric on same scan (measured: 0.845
  vs 0.291 mIoU — already confirmed). Both modes selectable at runtime.

**Anuj**
- `bench/latency.py`: per-stage timing wired through the pipeline into `stats`.
- Exit: Every `stats` latency field populated from real measurement on the HUD.

**Shubham**
- A/B wipe polish. Performance pass on instance count.
- Exit: No frame drops while dragging the divider.

**Navya**
- Full HUD per FR-28, including the **perception-mode badge** showing `live /
  cached / geometric` at all times.
- Exit: Every FR-28 field populated from real streamed frames.

**Khanak**
- `power_budget.m`. Start the component selection table with part numbers.

**Veda**
- Q&A bank to 12 questions. Payload report: architecture + component sections.

---

### Block C — Days 7–8 (Thu 3 Sep – Fri 4 Sep)
**Theme: Decision layer**

`core/` and `perception/` are both done. Sameer and Anuj now converge on
`decision/` — the module that turns the map into an action.

---

#### Day 7 — Thursday 3 Sep — TRAVERSABILITY + TRACKING + COSTMAP

**Sameer**
- `decision/traversability.py`: per-cell score in [0,1] from slope, roughness,
  step, class, clearance, confidence.
- `decision/tracker.py`: cluster DYNAMIC_OBJECT cells, Kalman filter per track,
  nearest-neighbour association.
- Verify the overnight label cache is correct.
- Exit: On S5, the tracker holds one stable ID across all 40 frames, speed
  within 0.5 m/s of the true 8.0 m/s.

**Anuj**
- `decision/costmap.py`: resample the polar map into a 160×160 (40 m × 40 m)
  Cartesian grid at 0.25 m resolution.
- Exit: T-D3 passes — obstacles preserved within one 0.25 m cell.

**Shubham**
- View 4 scaffold: track markers and predicted trajectories.
- Exit: Tracks visible and individually identifiable.

**Navya**
- `app/api/decisions/route.ts` with batched writes (FR-39).
- **Verify the localhost-vs-Vercel mixed-content issue TODAY** (NFR-9). The demo
  runs from `http://localhost:3000`, NOT from the Vercel deployment. An HTTPS
  page on Vercel cannot open `ws://localhost:8000`. Discovering this on Day 13
  would be a project-ending mistake.
- Exit: NFR-9 confirmed: demo path is `http://localhost:3000`. T-W6 passes.

**Khanak**
- Simulink receiver chain (or the pure-MATLAB fallback if no Simulink licence).

**Veda**
- Deck to near-final (except measured numbers). Q&A bank to 20 questions.

---

#### Day 8 — Friday 4 Sep — PLANNING + EXPLANATION + VIEW 4 COMPLETE

**Anuj**
- `decision/planner.py`: A* algorithm. Primary route + genuinely distinct
  alternative (re-plan with primary corridor penalised — not just a one-cell
  perturbation).
- `decision/explain.py`: deterministic template-based reason strings. No LLM.
- Exit: On S5, a tracked crossing truck triggers a reroute. Dashboard shows the
  alternative route. Reason string names the track, its speed, and the predicted
  intersection time.

**Sameer**
- `bench/distance_bins.py`: binned mIoU and object recall by distance range.
- `bench/hazard.py`: score synthetic scenes against exact ground truth.
- Exit: Binned mIoU computed; hazard scoring runs against known ground truth.

**Shubham**
- View 4 complete: routes, risk shading.
- Exit: Reroute legible from 3 metres away (judges look at projectors).

**Navya**
- Decision panel: route, risk level, ETA, reason string.
- `/runs` history page (list of past pipeline runs from MongoDB).
- Exit: T-W4 passes — writes on change + heartbeat, not one write per frame.

**Khanak**
- Finish receiver-chain model. Produce measured-vs-true range plots.

**Veda**
- Assemble the demo run-book with Sameer. Payload BOM table with costs.

---

### Block D — Days 9–11 (Sat 5 Sep – Mon 7 Sep)
**Theme: Depth — things the 6-day plan couldn't fit**

This is the extra week the deadline extension gave. Use it for the features that
make the submission stand out, not for doing Days 1–8 more slowly.

---

#### Day 9 — Saturday 5 Sep — REFINEMENT

**Anuj**
- `core/refine.py`: bounded local refinement (FR-17, FR-18).
  - Far-field cells that are MOVING, or high roughness/slope, get subdivided 2×2.
  - Hard cap: at most 4096 cells refined per frame (no adversarial scene can blow
    the latency budget).
  - Also: uncertainty-driven refinement — resolution is a function of distance
    AND scene content, not just distance.
- Exit: A distant moving vehicle is visibly finer than the empty road beside it.
  T-R2 passes (cap enforced). T-W7 passes (under 10 React renders in 300 frames).

**Sameer**
- Fine-tuning split preparation. Definitively answer Q-1: is the Windows GPU
  usable for fine-tuning?
- Adversarial scene: an occluded pothole.

**Shubham**
- LOD tuning. Verify ≥30 FPS at 100k instances (FR-30) and the React render
  count test (T-W7 — must be under 10 renders in 300 frames).

**Navya**
- `/runs/[id]` detail page: shows config, results, and decision log for one run.

**Khanak**
- Eye-safety calculation (HW-2) per IEC 60825-1 Class 1 at 905 nm. This is not
  optional — a DRDO evaluator will ask. Work through it explicitly.

**Veda**
- Payload design report: first full draft.
- Record a rough-cut video against the current build. Produce a problem list.

---

#### Day 10 — Sunday 6 Sep — PERCEPTION IMPROVEMENT + POLISH

**Sameer**
- If Q-1 says GPU is available: fine-tune the network on the 5-class taxonomy.
- If not: decoder-head-only fine-tune on CPU over a small subset + confidence
  calibration. Run overnight.
- Adversarial scene: a low-clearance tunnel with a curb.
- Exit: A measured before/after mIoU comparison exists. Even if improvement is
  small, the attempt must be documented. If it didn't help, record that — it's
  still a finding.

**Anuj**
- Implement `--replay` and `--record` flags for the server.
- Record the demo sequence log early. This is the fallback if something breaks on
  demo day — `--replay demo.log` plays back a pre-recorded run.
- Exit: `--replay demo.log` runs the full sequence end to end.

**Shubham + Navya**
- Visual polish. Deploy to Vercel for the submission link (keeping localhost as
  the actual demo path).
- Exit: Vercel deployment live. Renders correctly at projector resolution.

**Khanak**
- Regenerate every payload figure from its script. Confirm reproducibility (HW-8):
  every number in the report comes from a script, not a calculator.

**Veda**
- Fix everything the rough-cut video exposed. Problem list closed.

---

#### Day 11 — Monday 7 Sep — FULL BENCHMARK + FEATURE FREEZE at 21:00

**Sameer**
- `bench/report.py`: renders `results.json` → `docs/RESULTS.md`.
- Run the first full `make bench`. All 971 scans (sequences 00, 04, 05), all
  5 synthetic scenes, all latency measurements.
- Multi-sequence evaluation with per-sequence variance.
- Exit: Complete `results.json` with every section populated.

**Anuj**
- Final integration. Fix whatever the full bench run exposes.
- Exit: Full pipeline runs on KITTI and all synthetic scenes without error.

**Shubham + Navya**
- Final polish. Demo keystroke sequence verified end to end.

**Khanak**
- Payload design report complete.

**Veda**
- Deck final except for `_measured_` placeholders. All placeholders clearly
  marked (not filled — the real numbers come on Day 12).
- Rehearse the Q&A bank with the team.

**At 21:00: FEATURE FREEZE.** After this point: bug fixes, numbers, polish,
rehearsal only. No new code. No new features. The feature that is not built by
21:00 today does not go in the submission.

---

### Block E — Days 12–14 (Tue 8 Sep – Thu 10 Sep)
**Theme: Evidence, rehearsal, submit**

---

#### Day 12 — Tuesday 8 Sep — AUTHORITATIVE NUMBERS

**Sameer**
- Final benchmark runs: ≥200 scans for latency, full subset for accuracy, all
  scenes for hazards.
- Produce the authoritative `results.json`. Persist it to MongoDB as a `runs`
  document. Hand the file to Veda.
- **No changes after handover.** The numbers are frozen from this point.

**Anuj**
- Bug fixes only.
- Re-record the demo replay log against the frozen build.
- Exit: Replay fallback verified on the demo machine.

**Shubham + Navya**
- Bug fixes only.
- Exit: Zero console errors across all four views.

**Khanak**
- Cross-check every number destined for the deck against `results.json` — both
  software numbers AND payload numbers.
- Exit: Zero unverified numbers in the deck.

**Veda**
- Fill every `_measured_` placeholder from `results.json` only. Not from memory,
  not from a Day 3 scratch script.
- Exit: Zero `_measured_` placeholders remain. Every filled number traces to a
  line in `results.json` or a payload script output.

---

#### Day 13 — Wednesday 9 Sep — VIDEO + REHEARSALS

**Veda**
- Finalise the deck including the payload slide. Record the narration.

**Navya** (picks up from Veda)
- Edit the 3-minute video. Store the final render **locally** on the presenting
  laptop (not only in the cloud).

**Sameer**
- Run the demo. Nothing else.
- Three full timed demo rehearsals, including BOTH failure paths:
  1. The normal path (cached labels, live pipeline).
  2. Failure path 1: perception mode switched to geometric.
  3. Failure path 2: `--replay demo.log` (replay the pre-recorded log).

**All**
- Know the run-book. Know what key does what. Know the two failure paths.

---

#### Day 14 — Thursday 10 Sep — SUBMIT

Nothing is scheduled into this day on purpose. It is a buffer.

Morning: fix anything that broke overnight. Final rehearsal. **Submit.** Live demo.

---

## Who Is Blocked on Whom (Right Now)

As of the integration checkpoint Sameer wrote on Day 6, the current state is:

| What is blocked | Waiting on | Since |
|---|---|---|
| Shubham: entire frontend | `protocol.py` + `fixtures.py` from Anuj | Day 1 |
| Navya: entire frontend | `protocol.py` + `fixtures.py` from Anuj | Day 1 |
| Sameer: `traversability.py`, `tracker.py` | `core/cell.py` (CellGrid) from Anuj | Day 3 |
| Sameer: `bench/hazard.py`, `bench/memory.py` | `core/grid.py` + `core/cell.py` from Anuj | Day 3 |
| Decision layer | `core/cell.py` from Anuj | Day 4 |
| Hazard flags | `core/cell.py` → `cell.analyse()` from Anuj | Day 4 |
| End-to-end pipeline | Server (`app.py`) from Anuj | Day 3 |

**Everything is blocked on Anuj.** This is expected — the grid engine is the
mathematical core that everything else builds on. But it is now past the point
where it was supposed to exist.

**The immediate priority order for Anuj:**

1. `server/protocol.py` + `server/fixtures.py` — unblocks Shubham and Navya NOW
2. `core/grid.py` — the ring-sector grid
3. `core/cell.py` — accumulation + hazard analysis
4. `server/app.py` — the FastAPI server
5. `decision/costmap.py` → `decision/planner.py` → `decision/explain.py`

---

## What Sameer Can Do Without Anuj

While waiting for `core/cell.py`, Sameer has written `traversability.py` and
`tracker.py` against **test doubles** (mock objects that implement the same
interface as `CellGrid`). When Anuj's real `CellGrid` lands, these modules drop
in without changes.

This is also available to Shubham and Navya with `fixtures.py` — they can build
the entire dashboard against fake frames and switch to real frames by changing one
flag (`--fixtures` → `--infer cached`).

---

## The Three Rules That Must Not Be Broken

**1. No number reaches a slide except from `results.json`.**
Sameer generates the numbers, Khanak generates the payload numbers, Veda fills
the deck. No exceptions. A single unverifiable number is the fastest way to fail
a technically strong submission in front of a DRDO evaluator.

**2. The demo runs from `http://localhost:3000`, not from Vercel.**
Vercel serves the submission link (HTTPS). The live demo runs locally (HTTP).
An HTTPS page cannot open a `ws://localhost` connection — browsers block mixed
content. This is NFR-9. Navya must verify this on Day 7, not Day 13.

**3. `protocol.py` is frozen after Day 1.**
If it changes, four people have to update their code simultaneously. Any change
after Day 1 requires the integration lead (Sameer) to sign off and a message to
the whole team.

---

## Key Numbers for the Demo (Memorise These)

| What | Number |
|---|---|
| Cell reduction | **22.67×** |
| AVR-25D cells | **705,771** |
| Uniform 5 cm cells | **16,000,000** |
| AVR-25D memory | **17.64 MB** |
| Uniform memory | **400.0 MB** |
| Network mIoU (seq 04) | **0.845** |
| Geometric mIoU (seq 04) | **0.291** |
| Network end-to-end | **5.3 ms median** |
| Geometric end-to-end | **63.8 ms median** |
| LiDAR scan rate | **10 Hz** |
| Total rings | **662** |

---

## Summary — One Line Per Person

| Person | Their job in one sentence |
|---|---|
| **Sameer** | Labels every point, benchmarks everything, is the integration lead |
| **Anuj** | Builds the grid math, the server, and the planner — everything blocks on this |
| **Shubham** | Makes the 3D viewer and the A/B wipe — the things judges actually look at |
| **Navya** | Builds the Next.js app, Firebase auth, MongoDB storage, and the HUD |
| **Khanak** | Designs and simulates the drone LiDAR sensor in MATLAB |
| **Veda** | Co-designs the drone LiDAR system, owns the deck, video, Q&A bank, and hits submit |
