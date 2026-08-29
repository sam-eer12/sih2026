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
| **Sameer** | Backend / DL | Perception + benchmarking, integration lead | `avr25d/perception/`, `avr25d/bench/`, `avr25d/io/`, `avr25d/synth/`, `avr25d/decision/{traversability,tracker}.py` |
| **Anuj** | Backend / DL | Grid engine + server platform | `avr25d/core/`, `avr25d/server/`, `avr25d/decision/{costmap,planner,explain}.py` |
| **Shubham** | Frontend / web | Three.js viewer — all rendering | `webapp/components/viewer/`, `lib/palette.ts` |
| **Navya** | Frontend / web | Next.js platform — auth, persistence, HUD | `webapp/app/`, `lib/`, `components/hud/`, `components/decision/` |
| **Khanak** | Non-tech | Drone LiDAR payload — design and model | `hardware/matlab/`, `hardware/simulink/` |
| **Veda** | Non-tech | Payload documentation + evidence and submission | `hardware/docs/`, deck, script, Q&A, submission |

Six people, six non-overlapping directories. Two people never edit the same file on the same
day, which is what makes daily merges to `main` cheap.

**Two changes from the previous revision.** The MATLAB workstream was redirected from
synthetic scene generation to the drone LiDAR sensing payload (`PRD.md` §16) — a companion
hardware-design deliverable presented on its own slide, not woven into the software narrative.
The synthetic scenes did not go with it: they are the only source of exact hazard ground truth
and `PRD.md` §11.4 depends on them, so the ray-caster moved into Python as `avr25d/synth/`
under Sameer. Separately, the dashboard is now a Next.js application with Firebase Auth and
MongoDB Atlas, which splits the frontend along a cleaner boundary — Shubham owns everything
inside the canvas, Navya owns everything around it.

---

## 2. Ownership map

Every module has exactly one owner and one named backup. The backup is who picks it up if the
owner is ill, stuck, or pulled onto something urgent — decided now, calmly, rather than at
02:00 on Day 11.

| Module | Owner | Backup | Critical path? |
|---|---|---|---|
| `server/protocol.py` — **frozen Day 1** | Anuj | Sameer | **Yes — blocks 4 people** |
| `server/fixtures.py` | Anuj | Sameer | **Yes — unblocks the frontend** |
| `core/grid.py` | Anuj | Sameer | **Yes** |
| `core/cell.py` | Anuj | Sameer | **Yes** |
| `core/refine.py` | Anuj | Sameer | No |
| `server/app.py` | Anuj | Navya | Yes |
| `perception/geometric_seg.py` | Sameer | Anuj | **Yes — de-risks everything** |
| `perception/onnx_infer.py`, `range_proj.py` | Sameer | Anuj | No — cached mode covers it |
| `perception/cache.py`, `labelmap.py` | Sameer | Anuj | Yes |
| `io/kitti.py` | Sameer | Anuj | **Yes** |
| `decision/traversability.py`, `tracker.py` | Sameer | Anuj | No |
| `decision/costmap.py`, `planner.py`, `explain.py` | Anuj | Sameer | No |
| `bench/*` | Sameer | Anuj | Yes — Day 12 depends on it |
| `avr25d/synth/*` | Sameer | Anuj | **Yes — §11.4 depends on it** |
| `webapp/components/viewer/*` | Shubham | Navya | **Yes** |
| `webapp/app/*`, `lib/*`, `components/hud/*` | Navya | Shubham | **Yes** |
| Firebase project, Atlas cluster | Navya | Anuj | **Yes — external lead time** |
| `hardware/matlab/*`, `simulink/*` | Khanak | Veda | No — companion workstream |
| `hardware/docs/*` | Veda | Khanak | No — companion workstream |
| Deck, video, submission | Veda | Navya (video edit) | **Yes — it is the deliverable** |

**The decision layer is deliberately not one person's.** Sameer and Anuj converge on it on
Day 7, after `core/` and `perception/` have both landed. Neither of them opens a second front
while the hard core is still moving.

---

## 3. Who unblocks whom

```
  Day 1, 14:00 ─ Anuj freezes protocol.py + fixtures.py
                              │
        ┌─────────────────────┴─────────────────────┐
        ▼                                           ▼
   Shubham + Navya build the ENTIRE dashboard   Anuj builds core/
   against fixtures — zero backend dependency   Sameer builds perception/ + synth/
        │                                           │
        └─────────────────────┬─────────────────────┘
                              ▼
                 Day 11–12 ─ integration is a FLAG CHANGE
                            (--fixtures  →  --infer cached)

  Khanak + Veda ── hardware/ payload ──→ own slide + report
                   (no dependency in either direction)
```

The payload workstream is fully decoupled. Nothing in `avr25d/` or `webapp/` imports it, and
it needs nothing from them. If it slips, the software submission is unaffected; if the
software slips, the payload still lands.

**The one hard blocker in the project** is `protocol.py` + `fixtures.py` on Day 1 afternoon.
Two people cannot start until it lands, so it is the highest-priority item on the board and
nothing else Anuj does on Day 1 comes before it.

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

### 4.1 Sameer — Perception, benchmarking and integration lead

**Owns:** everything that turns points into labels, everything that turns runs into numbers,
and — new in this revision — `avr25d/synth/`, the synthetic scenes that carry exact hazard
ground truth. That last one arrived when MATLAB was redirected to the payload workstream. It
is roughly 150 lines and shares its spherical-projection maths with `range_proj.py`, which you
are writing anyway, so it is cheaper than it looks. It is still on the critical path for
`PRD.md` §11.4.

**Also responsible for:** running the daily 10:00 standup and the 21:00 integration
checkpoint; keeping `main` green; making the call on what gets cut; running the live demo.
Roughly 70% of the time is perception, the scenes and the benchmark harness; the rest is
integration and unblocking. Days 11–12 lean heavily towards integration.

**First action of the entire sprint:** start the SemanticKITTI download. It is bandwidth-bound
rather than effort-bound, so it runs unattended in the background all day while you write
code. Starting it on Day 2 instead of Day 1 is the easiest way to lose the project.

| Day | Tasks | Acceptance criterion |
|---|---|---|
| **1 · Fri 28 Aug** | **08:00 — start the KITTI subset download** (seq 04, then 00, then 05; ~1000 scans, ~12 GB). Then begin `perception/geometric_seg.py`. | Seq 04 downloading. RANSAC ground fit working on a synthetic plane. |
| **2 · Sat 29 Aug** | Finish `geometric_seg.py`: RANSAC ground plane, Euclidean clustering, bbox classification. `io/kitti.py` readers. | 5-class labels on a real KITTI scan. |
| **3 · Sun 30 Aug** | `labelmap.py` (19→5 merge including the `moving-*` IDs). **`avr25d/synth/` ray-caster plus scenes `S1`, `S2`, `S3`** — Anuj needs them on Day 4. | End-to-end: KITTI scan → labels → grid → browser. `S1`–`S3` load in the pipeline. |
| **4 · Mon 31 Aug** | Acquire an ONNX SemanticKITTI checkpoint (Q-4). Export and int8-quantise. Begin `range_proj.py`. | Checkpoint obtained and its licence confirmed usable. |
| **5 · Tue 1 Sep** | `onnx_infer.py`. k-NN range-aware reprojection in `range_proj.py`. Scenes `S4_curb` and `S5_crossing_truck`. | T-P4 passes — 100% of points labelled. All five scenes exist. |
| **6 · Wed 2 Sep** | Network labels on real scans with measured CPU latency. **Kick off the label-cache build overnight.** | Network labels visibly better than geometric on the same scan; both modes selectable. |
| **7 · Thu 3 Sep** | `decision/traversability.py` and `decision/tracker.py`. Verify the overnight label cache. | Stable track ID across all 40 `S5` frames; speed within 0.5 m/s of 8.0 m/s. |
| **8 · Fri 4 Sep** | `bench/distance_bins.py` and `bench/hazard.py`. | Binned mIoU computed; hazard scoring runs against `GROUND_TRUTH.md`. |
| **9 · Sat 5 Sep** | Assemble the 5-class fine-tuning split. **Resolve Q-1 definitively** — is the Windows GPU usable? Adversarial scene: occluded pothole. | Q-1 answered and shared. Split assembled. Scene loads. |
| **10 · Sun 6 Sep** | Perception improvement *[pulled forward]*: GPU fine-tune if Q-1 allows, otherwise CPU decoder-head-only fine-tune plus confidence calibration. Run overnight. Adversarial scene: low-clearance tunnel with a curb. | A measured before/after mIoU comparison exists, whichever branch was taken. |
| **11 · Mon 7 Sep** | `bench/report.py`. **First full `make bench`.** Multi-sequence evaluation *[pulled forward]* with per-sequence variance. **Call the feature freeze at 21:00.** | Complete `results.json` with every section populated. Freeze called. |
| **12 · Tue 8 Sep** | Authoritative benchmark runs: ≥200 scans for latency, full subset for accuracy, all scenes for hazards. Persist as a `runs` document and hand `results.json` to Veda. | Final `results.json` handed over and stored in MongoDB. **No changes after handover.** |
| **13 · Wed 9 Sep** | Bug fixes only. **Run the demo rehearsals** — three full timed runs including both failure paths. | Three clean rehearsals including both failure paths. |
| **14 · Thu 10 Sep** | Final rehearsal. Run the live demo. | Submitted. |

**Depends on:** Anuj for `protocol.py` (Day 1), `CellGrid` (Day 3).
**Unblocks:** Anuj's Day 4 hazard work — `S1`–`S3` must exist by the end of Day 3.
**Unblocks:** Anuj on Day 3 (readers and labels), Veda on Day 12 (all numbers).

**If the ONNX checkpoint does not materialise by Day 6 evening:** stop looking. The geometric
segmenter carries the demo, and the deck says "the pipeline is model-agnostic; we demonstrate
with a classical segmenter and a range-image CNN" — which is true, defensible, and a stronger
position than a broken model dependency in the final week.

### 4.2 Anuj — Grid engine and server platform

**Owns:** the mathematical core (`core/`), the wire protocol, the server, and the planner —
the pieces every other workstream builds against.

**Your first action on Day 1:** `protocol.py` frozen and `fixtures.py` pushed **by 14:00**.
Four people are blocked until it lands, so nothing else you do that day comes before it.

Roughly 80% of the time is the grid engine and the server; the rest is wiring other people's
modules into the pipeline as they land. The integration *lead* sits with Sameer, so surface
cross-module breakage at the 21:00 checkpoint rather than absorbing it quietly. Do not take on
a second module before Day 7.

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
| **13 · Wed 9 Sep** | Bug fixes only. Rehearsal support: the pipeline and the replay fallback. | Both failure paths exercised in rehearsal. |
| **14 · Thu 10 Sep** | Demo support — stand by on the stack while Sameer presents. | Submitted. |

**Depends on:** Sameer for `io/kitti.py` (Day 2) and labels (Day 2).
**Unblocks:** everyone, on Day 1 at 14:00.

---

## 5. Frontend track

The dashboard is a **Next.js 14 application** (App Router, TypeScript) with **Firebase Auth**
and **MongoDB Atlas**. Both cloud services are used directly — see risk R-11, where cloud-only
was chosen deliberately and the mitigations are listed.

The split follows a real boundary: **Shubham owns everything inside the canvas, Navya owns
everything around it.** That keeps the highest-risk performance work in one pair of hands and
the platform, auth and persistence work in the other, with almost no shared files.

Both work entirely against `fixtures.py` from Day 1 afternoon. Neither imports backend code.

**Two rules that are not style preferences.**

1. **The frame stream bypasses Next.js entirely** (FR-41). The browser opens a WebSocket
   straight to the FastAPI server. Proxying a 30 Hz binary stream through a route handler adds
   a serialisation hop and a process boundary to the one path with a 33 ms budget.
2. **Per-frame data never becomes React state** (FR-42). The viewer is a `useRef` canvas with
   a plain `requestAnimationFrame` loop; React renders the chrome around it and nothing inside
   it. `react-three-fiber` is deliberately not used. T-W7 enforces this with a render counter.

**Shared:** `lib/palette.ts` is the single source of class colours, and `lib/protocol.ts`
mirrors `avr25d/server/protocol.py`. Nobody hard-codes a hex value or a field offset anywhere
else, or the two halves will disagree in front of a judge.

### 5.1 Shubham — the Three.js viewer

**Owns:** `webapp/components/viewer/`, `lib/palette.ts`. Everything the judge actually looks at.

| Day | Tasks | Acceptance criterion |
|---|---|---|
| **1 · Fri 28 Aug** | Three.js scene inside a `useRef` canvas — renderer, orbit camera, ground reference, `lib/palette.ts`. From 14:00: render fixture cells as one `InstancedMesh`. | ~50,000 fixture cells render at interactive frame rate. |
| **2 · Sat 29 Aug** | Class colouring, elevation-shading toggle, correct per-instance sizing from `cell_extents`. | Cells correctly sized at every range — no slivers, no gaps. |
| **3 · Sun 30 Aug** | View 1 (raw cloud) and View 3 (adaptive grid) on real streamed frames. | Views 1 and 3 render real streamed frames, class-coloured. |
| **4 · Mon 31 Aug** | View 2 — the uniform 5 cm grid, needed for the comparison. | Uniform view renders the same scan as View 3. |
| **5 · Tue 1 Sep** | **The A/B wipe** (FR-29) and the ring overlay (FR-27). Two scissor-rect renders of one scene graph, not two canvases. | Divider shows **16,000,000 vs 705,771** live on the same scan. |
| **6 · Wed 2 Sep** | Wipe polish. Performance pass on instance count. | No frame drops while dragging the divider. |
| **7 · Thu 3 Sep** | View 4 scaffold: track markers and predicted trajectories. | Tracks visible and individually identifiable. |
| **8 · Fri 4 Sep** | View 4 complete: routes, risk shading. | Reroute legible from three metres away. |
| **9 · Sat 5 Sep** | LOD tuning. Verify ≥30 FPS at 100k instances (FR-30) **and the React render count** (T-W7). | T-V6 passes; T-W7 passes — under 10 React renders across 300 frames. |
| **10 · Sun 6 Sep** | Visual polish. Verify at projector resolution. Help Navya with the Vercel deploy. | Renders correctly at projector resolution. |
| **11 · Mon 7 Sep** | Final polish. Demo keystroke sequence verified end to end. | Every run-book keystroke works. |
| **12 · Tue 8 Sep** | Bug fixes only. | Zero console errors across all four views. |
| **13 · Wed 9 Sep** | Rehearsal support. | — |
| **14 · Thu 10 Sep** | Demo support. | — |

**The A/B wipe is the single most persuasive object in the whole submission.** Same scan, same
camera, a divider you drag, live cell counts on both sides. It converts "22.67× reduction"
from a claim into something the judge watches happen. Build it on Day 5, not in the final week.

**Design notes.** Judged on a projector, possibly in a bright room. High contrast, thick lines,
large HUD type. Verify the class palette is distinguishable in greyscale — if it survives
greyscale it survives a bad projector and it survives colour-blind judges.

**Performance fallback** (risk R-4): if instancing underperforms, render cell centroids as a
`THREE.Points` cloud with per-point size. Near-identical at demo zoom, far cheaper.

### 5.2 Navya — Next.js platform, auth, persistence, HUD

**Owns:** `webapp/app/`, `lib/` (except palette), `components/hud/`, `components/decision/`,
plus the Firebase project and the Atlas cluster.

| Day | Tasks | Acceptance criterion |
|---|---|---|
| **1 · Fri 28 Aug** | **Create the Firebase project and the Atlas M0 cluster** — external accounts first, they have lead time. Then `create-next-app` + TypeScript + Tailwind, `.env.local.example`, `lib/protocol.ts` decoding fixture frames. | Firebase project and Atlas cluster exist. `pnpm dev` serves a page. |
| **2 · Sat 29 Aug** | Firebase Auth: login page, email/password and Google providers, middleware gating `/dashboard` (FR-36). `lib/ws.ts` with exponential-backoff reconnect. | T-W1 passes — unauthenticated users cannot reach `/dashboard`. |
| **3 · Sun 30 Aug** | HUD wired to real `stats`. View switching, frame stepping, pause. | Real numbers displayed; no `NaN`, no `undefined`. |
| **4 · Mon 31 Aug** | `lib/mongo.ts` (module-scoped cached client) and `app/api/runs/route.ts` with `requireUser` token verification (FR-37). | T-W2 passes on the `runs` route — unverified tokens rejected before any Mongo call. |
| **5 · Tue 1 Sep** | Mongo collections and indexes created. `app/api/scenes/route.ts`; scene ground truth registered (FR-40). | T-W5 passes — every scene's ground truth matches its CSV exactly. |
| **6 · Wed 2 Sep** | Full HUD per FR-28, including the **perception-mode badge** (FR-6). | Every FR-28 field populated from real frames. |
| **7 · Thu 3 Sep** | `app/api/decisions/route.ts` with **batched writes** (FR-39). **Verify the localhost-vs-Vercel mixed-content path today** (NFR-9). | NFR-9 confirmed: the demo path is `http://localhost:3000`. T-W6 passes. |
| **8 · Fri 4 Sep** | Decision panel: route, risk, ETA, reason string. `/runs` history page. | T-W4 passes — reroutes plus heartbeats, not one write per frame. |
| **9 · Sat 5 Sep** | `/runs/[id]` detail page: config, results, decision log. | A completed run renders its config, results and decision log. |
| **10 · Sun 6 Sep** | Deploy to Vercel for the submission link, keeping localhost as the demo path. | Vercel deployment live; localhost still the demo path. |
| **11 · Mon 7 Sep** | Final polish. Responsive layout at the demo machine's resolution. | Layout correct at the demo machine's resolution. |
| **12 · Tue 8 Sep** | Bug fixes only. | T-V4 passes — no undefined fields. |
| **13 · Wed 9 Sep** | **Edit the 3-minute video** — picked up from Veda, whose load peaks here. | Video rendered and stored **locally** on the presenting laptop. |
| **14 · Thu 10 Sep** | Demo support. | — |

**Create the Firebase project and the Atlas cluster on Day 1 morning.** They are external
dependencies with account-verification lead time, and everything else you own is blocked
behind them. This is the same reasoning that puts Sameer's KITTI download first.

**Three things that will cost you a day each if missed:**

- **Mixed content** (NFR-9). An HTTPS page on Vercel cannot open `ws://localhost:8000`. The
  demo runs from `http://localhost:3000`; Vercel exists for the submission link. Verify this
  on **Day 7**, not Day 13.
- **Mongo client per request.** Next.js route handlers run per-request; creating a
  `MongoClient` in each one exhausts the Atlas connection pool within minutes. Cache it at
  module scope.
- **Decision write volume** (FR-39). At 30 FPS, one write per frame is 30 Atlas round-trips a
  second storing near-identical documents. Write on change plus a heartbeat, batch with
  `insertMany`, flush on a timer, and never await it inside the frame loop.

**Never compute a displayed number in the browser.** Everything comes from `stats` in the
`FrameMessage`. One source of truth means the HUD and `results.json` cannot disagree.

---

## 6. Non-technical track — drone LiDAR sensing payload

Khanak and Veda jointly own a **companion hardware-design deliverable**: a proprietary
time-of-flight LiDAR sensing module, light enough to fly on a drone, specified and simulated
end to end in MATLAB and Simulink. Full specification in `PRD.md` §16.

**It is presented separately** — one slide in the deck, one section of the report — and framed
as *"we also designed the sensor"*. It is not woven into the software narrative, nothing in
`avr25d/` or `webapp/` depends on it, and the PS coverage in `PRD.md` §15 does not reference
it. That decoupling is deliberate: if the payload slips, the software submission is unaffected.

**What this actually is.** A LiDAR measures distance by firing a very short laser pulse and
timing how long the reflection takes to come back — at the speed of light, 1 cm of range is
67 picoseconds of delay. Designing one means answering, with numbers: how much laser power is
needed to see a dark target at 100 m; whether that power is still safe for the human eye; how
fast the detector and amplifier must be to resolve a 5 ns pulse; how precisely the timing
circuit must measure that delay to get centimetre accuracy; and whether the whole thing fits
inside a drone's weight and power budget. Each of those is a calculation, and each calculation
is a MATLAB script that produces a figure for the report.

**Division of labour.** Khanak drives the models and the numbers; Veda drives the report, the
component justification and the BOM. Veda's half is documentation-shaped work, which is the
same skill as the deck — that is why the split falls there.

**Toolchain, and the licence escape hatch.** Every `.m` analysis script is written in base
MATLAB language only, so all of them run unmodified in free **GNU Octave**. The one
Simulink-dependent item is the receiver-chain model, and it has a documented pure-MATLAB
equivalent: discrete-time convolution of the laser pulse with the detector impulse response,
plus shot and thermal noise, with the discriminator and timing circuit applied numerically.
Same waveforms, same range-error figures, no Simulink. **Establish on Day 1 whether Simulink
is available and say so at standup.** If it is not, take the fallback immediately — do not
spend days chasing a licence (risk R-12).

### 6.1 Khanak — payload models and analysis

**Owns:** `hardware/matlab/`, `hardware/simulink/`.

| Day | Tasks | Acceptance criterion |
|---|---|---|
| **1 · Fri 28 Aug** | Install MATLAB or Octave. **Determine on day one whether Simulink is available** and tell the team either way (risk R-12). Read `PRD.md` §16. Draft the payload architecture block diagram. | Toolchain working; Simulink question answered; block diagram drafted. |
| **2 · Sat 29 Aug** | `link_budget.m` — received optical power against range, reflectivity 0.1–0.9. | Max range at the stated SNR threshold, plotted. |
| **3 · Sun 30 Aug** | `range_accuracy.m` — timing jitter and walk error into a range error budget. | `σ_range = c·σ_t / 2` error budget with numbers. |
| **4 · Mon 31 Aug** | `snr_sweep.m` — sweep aperture, reflectivity and sunlight background. | Sweep plots produced; design margins identified. |
| **5 · Tue 1 Sep** | `scan_coverage.m` — MEMS scan pattern → angular sampling → point density against range. | Point density against range, tabulated. |
| **6 · Wed 2 Sep** | `power_budget.m`. Begin the component selection table with part numbers. | Total power and mass against the drone payload limit. |
| **7 · Thu 3 Sep** | Simulink receiver chain — or the pure-MATLAB fallback if Day 1 found no licence. Do not spend days chasing a licence. | Model runs end to end, or the fallback script does. |
| **8 · Fri 4 Sep** | Finish the receiver-chain model; produce measured-against-true range plots. | Measured range tracks true range within the derived error budget. |
| **9 · Sat 5 Sep** | **Eye-safety calculation** (HW-2) worked through against IEC 60825-1 Class 1 at 905 nm. | Class 1 limit computed; the design is shown to comply, or the aperture is changed until it does. |
| **10 · Sun 6 Sep** | Regenerate every payload figure from its script and confirm reproducibility (HW-8). | Every figure regenerable from its script — no hand-drawn plots. |
| **11 · Mon 7 Sep** | Payload design report complete, with Veda. | Report complete: architecture, components with justification, all derived figures. |
| **12 · Tue 8 Sep** | **Cross-check every number destined for the deck against `results.json`** — software and payload both. | Zero unverified numbers in the deck. |
| **13 · Wed 9 Sep** | Finalise the demo run-book with Sameer. | Run-book complete, including both failure paths. |
| **14 · Thu 10 Sep** | Demo support. | — |

**Eye safety is not optional** (HW-2). The IEC 60825-1 Class 1 accessible-emission limit at
905 nm has to be worked through explicitly. If the design exceeds it, change the design —
widen the aperture, lower the peak power, reduce the repetition rate — and show the working.
A LiDAR design that does not address eye safety is not a credible design, and it is exactly
the question a DRDO evaluator will ask.

**Every figure must be regenerable from its script** (HW-8). No hand-drawn plots, no numbers
typed into the report that the code does not produce. This is the same rule the software side
follows with `results.json`, and for the same reason.

**If you get stuck for more than two hours**, say so at standup. Sameer and Anuj can both seed
a script skeleton in under an hour; grinding silently is what costs days.

### 6.2 Veda — payload documentation, evidence, and submission

**Owns:** `hardware/docs/`, the deck, the video script, the Q&A bank, and the submission.

**The rule that matters most:** *no number reaches a slide except from `results.json`, or from
a payload script that produced it.* Sameer generates the software numbers, Khanak generates the
payload numbers, you consume both, and Khanak cross-checks the deck on Day 12. Placeholders
stay as `_measured_` until then. A single unverifiable number is the fastest way to lose a
technically strong submission.

| Day | Tasks | Acceptance criterion |
|---|---|---|
| **1 · Fri 28 Aug** | Resolve Q-2 (deck template, slide count) and Q-3 (demo hardware). Deck outline. Begin prior-art search. | Q-2 and Q-3 answered and shared with the team. |
| **2 · Sat 29 Aug** | Prior-art and novelty write-up. Draft slides 1–2. | Novelty statement written: what exists, what we do differently. |
| **3 · Sun 30 Aug** | Slides 3–4. Begin the judge Q&A bank. Start the payload design report skeleton with Khanak. | Slides 3–4 drafted; report skeleton agreed with Khanak. |
| **4 · Mon 31 Aug** | Slide 5. Full deck draft with `_measured_` placeholders intact. | Complete deck; every number still a placeholder. |
| **5 · Tue 1 Sep** | Video script timed to 3:00, beats matched to the run-book. | Script timed to 3:00 with 10 seconds spare. |
| **6 · Wed 2 Sep** | Q&A bank to 12 questions. Payload report: architecture and component-justification sections. | 12 questions, each with the location of its answer. |
| **7 · Thu 3 Sep** | Deck to near-final. Q&A bank to 20 questions, including payload questions. | 20 questions. Deck near-final. |
| **8 · Fri 4 Sep** | Assemble the demo run-book with Sameer. Payload BOM table with costs. | Run-book drafted. BOM costed. |
| **9 · Sat 5 Sep** | Payload design report first full draft. **Record a rough-cut video** against the current build. | Rough cut exists; problem list produced and circulated. |
| **10 · Sun 6 Sep** | Fix everything the rough cut exposed. | Problem list closed. |
| **11 · Mon 7 Sep** | Deck final except for `_measured_` placeholders — now including the payload slide. Rehearse the Q&A bank with the team. | Deck final; placeholders intact and clearly marked. |
| **12 · Tue 8 Sep** | **Fill every placeholder from `results.json` only.** | Zero placeholders remain; every number traces to `results.json`. |
| **13 · Wed 9 Sep** | Finalise the deck. Record the narration; hand the edit to Navya. | Narration recorded; deck locked. |
| **14 · Thu 10 Sep** | **Submit.** Deck, video, documentation. | Submission confirmed. |

**Load note.** You are carrying the payload report *and* the deck *and* the submission. Two
items have been moved off you to keep Days 11–13 survivable: the **video edit** goes to Navya
on Day 13, and the **deck number cross-check** goes to Khanak on Day 12. If it still looks
overloaded at the Day 10 standup, hand the Q&A rehearsal to Sameer — it is the most
transferable item you own.

#### 6.2.1 Deck structure — SIH format, plus one payload slide

| Slide | Content | Where it comes from |
|---|---|---|
| **1 · Idea / Solution** | The foveation analogy in one line. The 2D-vs-3D dilemma. What we built. The system diagram. | `PRD.md` §1, §5 |
| **2 · Technical Approach** | Pipeline. The ring-sector grid: 662 rings, 5 cm → 50 cm, isotropic cells, closed-form O(1) index. **Constant 0.286° far-field bins matched to sensor sampling.** Tech stack including Next.js, Firebase, MongoDB. | `IMPLEMENTATION_PLAN.md` §3 |
| **3 · Feasibility & Viability** | Working prototype, measured numbers, cross-platform CPU-only operation. Risks and how they were handled — a judge trusts a team that names its risks. | `PRD.md` §13, `results.json` |
| **4 · Impact & Benefits** | 22.67× cell reduction → memory and downstream compute. Hazards a 2D grid destroys, preserved and measured. Explainable routing with a persisted audit trail. Defence and IDEX relevance. | `PRD.md` §10, §11 |
| **5 · Sensing Hardware** | The drone LiDAR payload: architecture, link budget, range accuracy, power and mass, eye safety. Framed as *"we also designed the sensor"*. | `hardware/docs/DESIGN_REPORT.md` |
| **6 · Research & References** | SemanticKITTI, RangeNet++/SalsaNext, elevation-mapping and traversability literature, IEC 60825-1, the PS itself. | §6.2.2 |

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
| 0:40–1:25 | Live screen capture following the run-book (`IMPLEMENTATION_PLAN.md` §10). |
| 1:25–2:00 | Hazards: overhang and pothole, with measured numbers on screen. |
| 2:00–2:25 | Dynamic object, reroute, the explanation string. |
| 2:25–2:40 | The drone payload, briefly — architecture diagram and headline figures. |
| 2:40–3:00 | Results summary. Every number from `results.json`. |

Record screen capture at the demo machine's native resolution. Narrate over it afterwards
rather than live — retakes are cheap, and a clean audio track is worth more than spontaneity.
Veda records the narration on Day 13; Navya cuts it.

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
| **"Did you build the sensor?"** | No — we designed and simulated it. Link budget, receiver chain, timing error budget, scan coverage, power and mass, and eye safety are all worked through in `hardware/docs/DESIGN_REPORT.md`. Say plainly that it is a design study, not a built prototype. Overclaiming here is the easiest way to lose the room. |
| **"Is the laser eye-safe?"** | HW-2 — IEC 60825-1 Class 1 computed at the exit aperture. Have the number ready. |

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
- **`protocol.py` is frozen after Day 1.** Changes need Sameer's sign-off and a message to
  everyone.
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
| Sameer | **Heavy** — download, segmenter, readers, synth | **Heavy** — ONNX, tracker, scenes, benchmarks | **Heavy** — fine-tune, multi-sequence eval, freeze | **Heavy** — authoritative runs, demo |
| Anuj | **Heavy** — protocol, fixtures, grid, cells | Heavy — analysis, costmap, planner | Heavy — refinement, integration | Medium — bug fixes, demo support |
| Shubham | Medium — canvas, instancing | **Heavy** — uniform view, wipe, View 4 | Medium — LOD, render-count verification | Light — bug fixes |
| Navya | **Heavy** — accounts, Next.js, auth | **Heavy** — Mongo, API routes, HUD, decision panel | Medium — run pages, Vercel deploy | Medium — video edit |
| Khanak | Medium — toolchain, link budget | Medium — sweeps, receiver chain | Medium — eye safety, reproducibility | **Heavy** — deck cross-check, run-book |
| Veda | Light — questions, outline | Medium — deck, script, Q&A, payload report | **Heavy** — report, rough cut | **Heavy** — numbers, narration, submission |

**Known concentration risks — two, both accepted deliberately.**

*Anuj* owns the protocol, the grid, the cells, the server and the planner. Those pieces are
tightly coupled and splitting them would cost more in coordination than it saves in load.
Sameer is the named backup on every one and reviews each as it merges, so the bus factor is
two, not one.

*Sameer* is the only Heavy in all four columns, and carries the integration lead and the demo
on top of perception, the benchmark harness and `avr25d/synth/` — which arrived when MATLAB
moved to the payload workstream. The mitigations are that `synth/` is small and shares maths
with `range_proj.py`, which is being written regardless, and that the scenes are front-loaded
to Days 3 and 5 while the fine-tuning work on Days 9–10 is explicitly droppable if it does not
pay off. **If Sameer is behind at the Day 5 standup, the first thing to hand to Anuj is
`bench/baselines.py` and `bench/memory.py`** — they are self-contained and Anuj has already
written the baseline arithmetic into `PRD.md` §10.1.

**If either frontend developer finds slack**, the highest-value place to help is the A/B wipe
on Day 5. It is the most persuasive artefact in the submission and the one most worth two
people.

---

## 9. Phase 2 — 11 to 20 September 2026

Ten days, calmer pace, same ownership.

| Person | Phase 2 focus |
|---|---|
| **Sameer** | Complete the perception fine-tune; expand evaluation across sequences; per-sequence variance |
| **Anuj** | Temporal accumulation with ego-motion compensation; ablation studies |
| **Shubham** | Timeline scrubber; side-by-side scene comparison; exportable evidence screenshots |
| **Navya** | Saved-run comparison view; shareable read-only run links; history charts from MongoDB |
| **Khanak** | Extend the receiver model with a full noise budget and a Monte-Carlo range-accuracy study |
| **Veda** | Full technical report including the payload section; final SIH deck; portal submission on 20 Sep |

---

## 10. Day 1 checklist

Print this. Tick it tonight.

- [ ] **Sameer** — KITTI download started (do this first, before anything else)
- [ ] **Navya** — Firebase project created and Atlas M0 cluster provisioned (external lead time)
- [ ] **Anuj** — `protocol.py` frozen and `fixtures.py` pushed **by 14:00**
- [ ] **Shubham + Navya** — `pnpm dev` serving a page that renders fixture cells
- [ ] **Khanak** — MATLAB or Octave installed; **Simulink availability answered** (risk R-12)
- [ ] **Veda** — Q-2 (deck template) and Q-3 (demo hardware) answered
- [ ] **Everyone** — repo cloned, `pytest -q` green on your own machine
- [ ] **Anuj** — cross-platform smoke test passed on both Mac and Windows
- [ ] `RingGrid` reports **662 rings, 705,771 cells** — the number that says the core is real
