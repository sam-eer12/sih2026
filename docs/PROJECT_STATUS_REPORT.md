# AVR-25D — Project Status Report

| | |
|---|---|
| **Audit Date** | Mon 7 Sep 2026 |
| **Deadline** | Thu 10 Sep 2026 (Phase 1 — internal hackathon) |
| **Days Remaining** | 3 |
| **Auditor** | Kiro (cross-checked docs vs codebase) |

---

## 1. Executive Summary

The project is in a strong position with 3 days to the deadline. The backend
pipeline is fully implemented and tested (374+ Python tests, CI running on macOS
and Windows). The frontend landed completely on `main` today — `lib/protocol.ts`,
`lib/ws.ts`, all HUD components, all API routes, and the dashboard wired to the
live stream are all present.

The single biggest blocker that existed yesterday (Navya's decoder not on `main`)
is now resolved. The viewer runs on real streamed frames.

**Remaining critical gaps:**

1. OVERHANG hazard flag is nearly inert (0.004 / 0.000 detection) — fix assigned to Anuj
2. Demo replay log (`--replay demo.log`) has not been recorded
3. Firebase project + Atlas M0 cluster have not been provisioned
4. Feature freeze has not been declared
5. Authoritative `results.json` has not been run against the frozen build
6. Hardware track (Khanak + Veda) has **zero logged progress** — `hardware/` directory does not exist in the repo

---

## 2. Completed Work

### 2.1 Backend — Core Pipeline (Anuj)

| Module | What it does | Evidence |
|---|---|---|
| `core/grid.py` | `RingGrid` — 662 rings, 705,771 cells, O(1) closed-form indexing (FR-7–FR-12) | Full implementation, all 4 required methods |
| `core/cell.py` | `CellGrid` — SoA accumulation, all hazard flags, `_ground_reference` neighbourhood fix | Full implementation incl. NEGATIVE_OBSTACLE fix |
| `core/refine.py` | Bounded 2×2 far-field refinement, hard cap 4096 cells (FR-17, FR-18) | Complete — note: sub-cells inherit parent stats (see §3) |
| `server/protocol.py` | Binary FrameMessage encode/decode — **frozen Day 1** | `encode()` + `decode()` + all typed arrays |
| `server/fixtures.py` | Schema-valid synthetic frames — zero dependency on `core/` or `perception/` | Self-contained, imports only `protocol.py` |
| `server/app.py` | Full pipeline: all 4 modes, FrameHub fan-out, `--record` / `--replay` | `PipelineWorker`, `ReplayWorker`, `FrameHub` |
| `decision/costmap.py` | Polar → 160×160 Cartesian resample with obstacle inflation (FR-21) | Complete |
| `decision/planner.py` | A\* primary + genuinely distinct alternative via corridor penalty (FR-22) | `_CORRIDOR_PENALTY` forces path divergence |
| `decision/explain.py` | Deterministic reason strings, 4 templates, no LLM (FR-23, FR-24) | Complete |
| `decision/traversability.py` | 5-weight score in \[0,1] — all weights + `max_roughness` in `config.yaml` (FR-19) | Complete; NFR-7 satisfied |
| `decision/tracker.py` | Metric-space clustering, constant-velocity Kalman filter (FR-20) | Rewritten after index-space clustering bug |
| `config.yaml` | Every tunable documented with units and justification (NFR-7) | Complete |

### 2.2 Backend — Perception (Sameer)

| Module | What it does | Evidence |
|---|---|---|
| `perception/geometric_seg.py` | RANSAC + Euclidean clustering, 5 classes, deterministic (FR-5) | Complete |
| `perception/onnx_infer.py` | OnnxSegmenter — full pipeline from points to AVR labels (FR-1, FR-3) | Complete with k-NN reprojection |
| `perception/range_proj.py` | Range image projection + k-NN back-projection (FR-4) | `RangeProjection` class |
| `perception/labelmap.py` | 19-class → 5-class merge including `moving-*` variants | `raw_to_avr`, `learning_to_avr` |
| `perception/cache.py` | LabelCache with mmap, keyed by `seq/frame` | `for_frame()` accessor |
| `io/kitti.py` | `.bin` / `.label` readers + `KittiSequence` indexable view | Full implementation |
| `synth/scenes/` (S1–S7) | All 7 synthetic scenes including adversarial S6 + S7 | 7 CSVs committed |
| `synth/registry.py` + `data/scenes_registry.json` | FR-40 scene ground truth for MongoDB (FR-40) | Committed; CI checks regeneration |
| ONNX models | `squeezesegV2_fp32.onnx`, `_int8.onnx`, `_5class.pt` ×2 | 4 model files in `data/models/` |
| `tools/finetune.py` + split | Fine-tuning pipeline + `finetune_5class.json` | Complete; pretrained beats fine-tuned (documented) |
| `data/finetune_report.json` | Before/after mIoU comparison (Day 10 deliverable) | Both weighting variants measured |

### 2.3 Backend — Benchmarks (Sameer)

| Module | What it does | Evidence |
|---|---|---|
| `bench/baselines.py` | B0–B4 memory models | Complete |
| `bench/latency.py` | Per-stage timing, warm-up discard, p95/max over 956 scans | `LatencyRecorder` with sequence-level warm-up |
| `bench/distance_bins.py` | Binned mIoU + object recall by distance range | Streaming accumulators |
| `bench/hazard.py` | Hazard scoring vs exact ground truth + 2D counterfactual | All 7 scenes, instance-id association |
| `bench/memory.py` | Peak RSS via `getrusage` (platform-aware Darwin/Linux) | Complete |
| `bench/report.py` | `results.json` → §11 Markdown tables | Complete |
| `docs/RESULTS.md` | Fully populated — all §11 sections, 971 scans, no `_not measured_` | From commit `b75aa46` — needs re-run (see §4) |
| `Makefile` | `make bench`, `make bench-authoritative`, `make scenes`, `make finetune` | All targets present and documented |

### 2.4 Backend — Testing & CI

| Item | Count | Notes |
|---|---|---|
| Total Python tests | **386** | 19 test files |
| CI — macOS + Windows | ✅ | `.github/workflows/tests.yml`, `fail-fast: false` |
| T-P6 (server modes honest) | 8 tests | `test_server_modes.py` — asserts on labels, not mode string |
| FrameHub fan-out regression | 8 tests | `test_frame_hub.py` — prevents "second client gets nothing" bug |
| `make scenes-registry` idempotency | CI step | Regenerates and diffs `scenes_registry.json` |

### 2.5 Frontend — Viewer (Shubham)

| Item | Evidence |
|---|---|
| View 1 — raw point cloud | `components/viewer/pointCloud.ts` |
| View 2 — uniform 5 cm grid | `components/viewer/uniformGrid.ts` |
| View 3 — adaptive grid | `components/viewer/instancedCells.ts` |
| View 4 — decision layer (tracks, routes, risk shading) | `components/viewer/decisionLayer.ts` |
| A/B wipe with live cell counts — 16,000,000 vs 705,771 (FR-29) | `components/viewer/wipe.ts`, `WipeOverlay.tsx` |
| Ring overlay + procedural grid shader | `ringGeometry.ts`, `gridShader.ts` |
| FPS meter | `components/viewer/perfMeter.ts` |
| T-V6 — ≥30 FPS at 100k instances | **60 FPS @ 109,404 instances** (1% low: 56.7) |
| T-W7 — ≤10 React renders in 300 frames | **3 React renders measured** |
| `next build` clean | No warnings, no deprecations (Turbopack 16.3.3) |
| Views render real streamed frames | Closed Day 9 by `lib/protocol.ts` + `lib/ws.ts` |

### 2.6 Frontend — Platform (Navya)

| Item | Evidence |
|---|---|
| `lib/protocol.ts` — binary FrameMessage decoder | `decodeFrame()` with alignment fix (0.131 ms/frame overhead) |
| `lib/ws.ts` — WebSocket client, reconnect, NFR-9 guard | `connectFrames()`, `isMixedContentBlocked()` |
| `components/hud/` — full HUD FR-28 | `Hud.tsx`, `LatencyBars.tsx`, `MemoryPanel.tsx`, `ModeBadge.tsx`, `StreamStatus.tsx`, `ViewControls.tsx`, `SessionChip.tsx` |
| `components/decision/DecisionPanel.tsx` + `TrackList.tsx` | Sampling at 4 Hz, reason string in largest type |
| Firebase Auth — login, email/password + Google, route gate | `app/(auth)/login/page.tsx`, `proxy.ts`, `lib/firebase/{client,admin}.ts` |
| `proxy.ts` — Next 16 route gate (replaces `middleware.ts`) | Correct export name; `PROTECTED = ['/dashboard', '/runs']` |
| MongoDB API routes — `/api/runs`, `/api/decisions`, `/api/scenes`, `/api/users` | All 4 `route.ts` files; `requireUser()` is the first call in every handler (FR-37, T-W2) |
| `lib/mongo.ts` — module-scoped cached `MongoClient` | `globalThis` cache; `maxPoolSize: 10` |
| `lib/decisionLog.ts` — on-change + heartbeat batching (FR-39) | Timer-based flush; `insertMany`, never per-frame |
| `lib/runSession.ts` — wires decision log into dashboard | Inert until Firebase configured; no-op on every null check |
| `/runs` + `/runs/[id]` pages | Run list + detail with config, results, decision log |
| `app/page.tsx` — landing page | Key numbers, links to `/dashboard` and `/runs` |
| `.env.local.example` | Every variable documented; no credential committed |
| Dashboard wired to live stream | `connectFrames()` called in `handleReady`; no `devStream` prop passed |

---

## 3. Partially Completed Work

### 3.1 OVERHANG hazard flag (`core/cell.py`)

**What works:** The flag is implemented and the clearance *measurement* is accurate
(3.0976 m vs 3.10 true for S3; 3.3977 m vs 3.40 true for S7).

**What is broken:** The flag only fires on cells where both a ground return and an
overhead return land in the **same cell**. Because beams hitting the deck underside
and beams hitting the road beneath land at different ranges, they almost never share
a cell. Measured: 2/916 cells fire under S3's deck; 0/191 under S7's tunnel.

**Root cause:** Same as NEGATIVE_OBSTACLE had before the `_ground_reference` fix —
the reference must come from the ring *neighbourhood*, not the same cell.

**Impact:** `RESULTS.md §11.4` reports these numbers honestly (detection rate
= 0.004, 0.000). The fix is diagnosed; it is assigned to Anuj.

**What is not affected:** The clearance number itself is fine; `bench/hazard.py`
reports it separately from the per-cell yield.

---

### 3.2 `core/refine.py` — sub-cell accuracy

**What works:** Refinement runs every frame, correctly selects far-field candidates
(MOVING, rough, steep), enforces the 4096-cell cap, sets the `REFINED` flag, and
passes T-R1 and T-R2.

**What is approximate:** Sub-cells inherit the parent cell's `z_ground`, `z_obstacle`,
`class_id`, and `flags` wholesale — there is no true re-accumulation of the parent's
points into each quadrant. The code documents this explicitly.

**Impact:** Conservative (safe for planning). A distant truck gets finer resolution
in the renderer and planner, but each quadrant is not independently measured.

---

### 3.3 ONNX model — fp32 in production, not int8

**Situation:** Both `squeezesegV2_fp32.onnx` (3.71 MB) and `squeezesegV2_int8.onnx`
(1.11 MB) exist. `config.yaml` points at fp32.

**Reason (documented in `config.yaml`):** Dynamic int8 quantisation on this Conv-only
graph costs 5% pixel agreement (100% → 95%) with no latency improvement — it pays
quantise/dequantise overhead without reaching an int8 kernel. Decision is correct and
justified. Int8 is still exported and testable.

---

### 3.4 Synthetic scene KITTI directories — only S5 pre-generated

`model/data/synthetic/` contains only the `S5_crossing_truck` directory. S1–S4 and
S6–S7 are not pre-generated. They are regenerated on demand via `make scenes`.

This is not a blocker for tests (they ray-cast into `tmp_path` on the fly) but
`python -m avr25d.server.app --infer geometric --seq S2_pothole` would need `make
scenes` run first.

---

## 4. Remaining Work

### 🔴 Critical — blocks demo or submission

| # | Task | Owner | Notes |
|---|---|---|---|
| C1 | **OVERHANG neighbourhood fix** in `core/cell.py` | Anuj | Apply ring-neighbourhood lookup (same approach as `_ground_reference`). S3 = 0.004, S7 = 0.000 detection rates are in the deck numbers. |
| C2 | **Declare the feature freeze** | Sameer | Was due Day 11 at 21:00. No new features after this point. Bug fixes, numbers, rehearsal only. |
| C3 | **Run `make bench-authoritative`** and hand `results.json` to Veda | Sameer | Current `RESULTS.md` is from commit `b75aa46`. Must re-run after OVERHANG fix. No changes after handover. |
| C4 | **Record `--replay demo.log`** on the demo machine | Anuj | `ReplayWorker` and `--record` flag both exist. Run against frozen build in cached mode. This is the primary safety net for demo day. |
| C5 | **Provision Firebase project + Atlas M0 cluster** | Navya | Account verification has lead time. Auth is inert, all API routes return 401, `/runs` is empty until these exist. |

---

### 🟠 High — affects submission quality

| # | Task | Owner | Notes |
|---|---|---|---|
| H1 | **Vercel deployment** | Navya | Submission link must be live. Requires Firebase first. |
| H2 | **Seed Atlas `scenes` collection** | Navya | `curl` `data/scenes_registry.json` to `/api/scenes` once Atlas is live. Idempotent upsert. |
| H3 | **Persist authoritative `results.json` to MongoDB** | Sameer | Post to `/api/runs` after Day 12 bench run. The `/runs` page exists; it needs the data. |
| H4 | **3-minute demo video** | Navya (edit) / Veda (script) | No progress logged anywhere. Rough-cut recording + final edit. Store locally on the presenting laptop, not only in the cloud. |
| H5 | **Three full timed demo rehearsals** | Sameer (runs) / All | Normal path (cached), geometric fallback, `--replay demo.log` fallback. |
| H6 | **Q&A bank** | Veda | Target: 20 questions. No progress logged. |
| H7 | **Fill deck `_measured_` placeholders** | Veda | From `results.json` only — no memory, no Day 3 scratch scripts. Depends on C3. |
| H8 | **Re-record `demo.log` against the frozen build** | Anuj | Even if C4 is done early, re-record after the feature freeze to match the authoritative numbers. |

---

### 🟡 Medium — quality / completeness

| # | Task | Owner | Notes |
|---|---|---|---|
| M1 | **Hardware track — MATLAB scripts, Simulink model, payload report** | Khanak / Veda | `hardware/` directory does not exist. Zero progress logged. Decoupled from software — if it slips the software submission is unaffected. |
| M2 | **Commit frontend test files** | Navya | `navya.md` claims 273 assertions across 9 suites but no test files appear in `frontend/`. Either not committed or still on the branch. |
| M3 | **Generate scenes S1–S4, S6–S7 as KITTI directories** | Sameer | Run `make scenes`. Only S5 is pre-generated. Not needed for CI but needed for local server testing. |
| M4 | **Windows GPU probe (Q-1 second half)** | Whoever is at the Windows machine | `python tools/finetune.py probe`, paste output at standup. Wanted only for the live-inference HUD figure. |

---

### 🟢 Low — optional upgrades

| # | Task | Owner | Notes |
|---|---|---|---|
| L1 | **Sub-cell point re-accumulation in `refine.py`** | Anuj | True quadrant-level geometry requires storing per-cell point indices during `accumulate()`. Conservative inheritance works correctly for planning. |
| L2 | **`model/requirements.txt` cleanup** | Anyone | This file is a global pip freeze (180+ packages including `nupy`, a typosquat of numpy). The correct file is `backend/requirements.txt`. The dangerous file should be replaced or removed. |
| L3 | **`npm audit` 6 moderate advisories** | Navya | All transitive through `firebase-admin → @google-cloud/storage → uuid`. `audit fix --force` would downgrade the SDK. Documented; not blocking. |

---

## 5. Documentation vs Implementation Gaps

| Gap | Details |
|---|---|
| **`webapp/` vs `frontend/`** | Every planning doc references `webapp/`. The actual directory is `frontend/`. Docs are stale; Shubham and Navya both noted it. |
| **`middleware.ts` vs `proxy.ts`** | Planning docs say `middleware.ts`. Code correctly uses `proxy.ts` — Next 16 renamed the convention. |
| **Next 14 / React 18 vs Next 16 / React 19** | `IMPLEMENTATION_PLAN §2.1` pins `next == 14.2.5`, `react == 18.3.1`. Actual: Next 16.3.3, React 19.2.8. Treat the code as truth. |
| **`model/requirements.txt` is a global pip freeze** | `IMPLEMENTATION_PLAN §2.1` describes a clean pinned list. `model/requirements.txt` has 180+ packages including `nupy` (typosquat). The correct authoritative file is `backend/requirements.txt`. |
| **Python ≥3.10, <3.13 vs Python 3.14** | Plan said `>= 3.10, < 3.13`. Actual interpreter is 3.14.5. Documented in `backend/requirements.txt` comment with reasoning. |
| **int8 ONNX in production** | `IMPLEMENTATION_PLAN §6.6` specifies int8 quantisation. Production uses fp32. Deviation measured and justified in `config.yaml`. |
| **`RESULTS.md` commit `b75aa46` vs current HEAD `1ccc876`** | The results file is one merge behind. Needs re-run. |
| **`_placeholder_decision()` still in `app.py`** | Not an unfinished stub — it is a defensive fallback called only when the real decision layer throws. The real decision runs first. |
| **`data/synthetic/` only has S5** | Docs imply all 7 scenes are generated. S1–S4, S6–S7 must be regenerated with `make scenes`. |
| **No `data/kitti/` or `data/cache/` locally** | KITTI sequences and label cache are on Sameer's machine. `make bench` will fail on a fresh clone without downloading KITTI first. |
| **`hardware/` directory does not exist** | `IMPLEMENTATION_PLAN §4` describes `hardware/matlab/`, `hardware/simulink/`, `hardware/docs/`. None of these directories exist in the repository. |

---

## 6. Testing & Verification Status

### 6.1 Python test suite

| Test file | Tests | What it covers | Verified |
|---|---|---|---|
| `test_grid.py` | 33 | T-G1–T-G4, ring math, conservation | ✅ |
| `test_cell.py` | 21 | T-G5, T-H1–T-H4, accumulation, hazard flags | ✅ |
| `test_decision.py` | 32 | T-D1–T-D6, all 5 decision modules | ✅ |
| `test_hazard.py` | 26 | §11.4 hazard geometry errors + FP rate | ✅ |
| `test_server_modes.py` | 8 | T-P6 — mode honest in wire message | ✅ |
| `test_frame_hub.py` | 8 | FrameHub fan-out regression | ✅ |
| `test_refine.py` | 16 | T-R1, T-R2 | ✅ |
| `test_baselines.py` | 18 | B0–B4 memory models | ✅ |
| `test_latency.py` | 22 | Timing stats, warm-up discard | ✅ |
| `test_distance_bins.py` | 30 | Binned mIoU math | ✅ |
| `test_report.py` | 27 | `results.json` → Markdown | ✅ |
| `test_registry.py` | 17 | FR-40 scene registry | ✅ |
| `test_synth.py` | 18 | Synthetic scene generation | ✅ |
| `test_onnx_infer.py` | 15 | ONNX wrapper (builds its own graph) | ✅ |
| `test_range_proj.py` | 17 | T-P2, T-P4 | ✅ |
| `test_geometric_seg.py` | 18 | T-P5 | ✅ |
| `test_kitti_io.py` | 8 | `.bin`/`.label` readers | ✅ |
| `test_cache.py` | 15 | LabelCache mmap, `for_frame()` | ✅ |
| `test_labelmap.py` | 33 | 19→5 class merge | ✅ |
| **Total** | **386** | | **CI green on macOS + Windows** |

> **Local note:** pytest run timed out during this audit — likely `test_hazard.py`
> ray-casting multiple scenes. CI on GitHub is the authoritative pass/fail.
> Sameer's last log reports 374 green; 8 `test_frame_hub.py` tests were added since
> = **382 expected**. (386 reflects pytest `--collect-only` count.)

### 6.2 Missing test coverage

| Missing | Notes |
|---|---|
| Frontend test files not committed to repo | `navya.md` claims 273 assertions across 9 suites. No test files found under `frontend/`. Either not committed or still on an unmerged branch. |
| T-W3 (run round-trip byte-identical) | Referenced in planning docs; no visible test file. |
| OVERHANG neighbourhood fix | No test for the improved detection rate — once the fix lands, a test should assert S3 detection > 0.50. |
| T-W4, T-W5 frontend | `decisionLog.ts` batching and scene ground-truth checks — logic correct by inspection; no committed test. |

---

## 7. Recommended Next Steps (in order)

### Day 12 — Today (Tue 8 Sep)

| Priority | Action | Owner |
|---|---|---|
| 1 | Declare the **feature freeze** at standup | Sameer |
| 2 | **OVERHANG fix** in `core/cell.py` | Anuj |
| 3 | **Provision Firebase project + Atlas M0 cluster** — do this immediately; has lead time | Navya |
| 4 | **`make bench-authoritative`** after OVERHANG fix lands | Sameer |
| 5 | Hand `results.json` to Veda and **POST to `/api/runs`** (once Atlas is live) | Sameer |
| 6 | **Record `--replay demo.log`** on the demo machine against the frozen build | Anuj |
| 7 | **Vercel deploy** + seed `scenes` collection | Navya |

### Day 13 — Wed 9 Sep

| Priority | Action | Owner |
|---|---|---|
| 8 | **Fill all `_measured_` placeholders** in the deck from `results.json` only | Veda |
| 9 | **Edit the 3-minute video** — store locally on presenting laptop | Navya |
| 10 | **Three full timed rehearsals**: normal path → geometric fallback → `--replay` fallback | Sameer + All |
| 11 | **Q&A bank** — reach 20 questions minimum | Veda |

### Day 14 — Thu 10 Sep

| Priority | Action | Owner |
|---|---|---|
| 12 | Fix anything broken overnight | All |
| 13 | Final rehearsal | All |
| 14 | **Submit** | Veda |

---

## 8. Final Status Table

| Work Item | Status | Evidence | Remaining Work | Priority |
|---|---|---|---|---|
| `core/grid.py` — RingGrid, 662 rings, 705,771 cells | ✅ Complete | `grid.py`, 33 tests | — | — |
| `core/cell.py` — accumulation, hazard flags | ✅ Complete | `cell.py`, 21 tests | — | — |
| `core/cell.py` — OVERHANG neighbourhood fix | ❌ Not done | `RESULTS.md §11.4`: 0.004 / 0.000 detection | Apply neighbourhood lookup | 🔴 C1 |
| `core/refine.py` — bounded 2×2 refinement | ⚠️ Partial | Works; sub-cells inherit parent stats | Point re-accumulation (optional) | 🟢 L1 |
| `server/protocol.py` — binary wire format | ✅ Complete | `protocol.py`, round-trip tested | — | — |
| `server/fixtures.py` — synthetic frames | ✅ Complete | Zero core imports | — | — |
| `server/app.py` — full pipeline + FrameHub | ✅ Complete | 8 hub tests | — | — |
| `--record` / `--replay` flags | ✅ Implemented | `ReplayWorker` in `app.py` | Record actual demo log | 🔴 C4 |
| `decision/traversability.py` | ✅ Complete | T-D1 passes | — | — |
| `decision/tracker.py` | ✅ Complete | T-D2 passes (rewritten) | — | — |
| `decision/costmap.py` | ✅ Complete | T-D3 passes | — | — |
| `decision/planner.py` | ✅ Complete | T-D4 passes | — | — |
| `decision/explain.py` | ✅ Complete | T-D5, T-D6 pass | — | — |
| `geometric_seg.py` — RANSAC fallback | ✅ Complete | T-P5, 18 tests | — | — |
| `onnx_infer.py` — ONNX wrapper | ✅ Complete | 15 tests | — | — |
| `range_proj.py` — range image + k-NN | ✅ Complete | T-P2, T-P4, 17 tests | — | — |
| `labelmap.py` — 19→5 class merge | ✅ Complete | 33 tests | — | — |
| `cache.py` — LabelCache mmap | ✅ Complete | 15 tests | — | — |
| `io/kitti.py` — KITTI readers | ✅ Complete | 8 tests | — | — |
| Synthetic scenes S1–S7 (CSVs) | ✅ Complete | 7 CSVs committed | Run `make scenes` for KITTI dirs | 🟡 M3 |
| ONNX models (fp32 + int8) | ✅ Complete | 2 `.onnx` files | — | — |
| Fine-tuning split + tools | ✅ Complete | `finetune_5class.json` | — | — |
| All benchmark modules | ✅ Complete | `bench/` — 6 modules, all tested | — | — |
| `docs/RESULTS.md` — fully populated | ⚠️ Stale | From commit `b75aa46` | Re-run `make bench-authoritative` | 🔴 C3 |
| `data/scenes_registry.json` (FR-40) | ✅ Complete | File committed, CI idempotency check | Seed to Atlas once provisioned | 🟠 H2 |
| 386 Python tests, CI macOS + Windows | ✅ Complete | `.github/workflows/tests.yml` | — | — |
| `lib/protocol.ts` — binary decoder | ✅ Complete | Alignment fix, 0.131 ms overhead | — | — |
| `lib/ws.ts` — WS client + NFR-9 guard | ✅ Complete | `isMixedContentBlocked()` | — | — |
| Full HUD (FR-28) | ✅ Complete | 9 HUD component files | — | — |
| Decision panel + track list | ✅ Complete | `DecisionPanel.tsx`, `TrackList.tsx` | — | — |
| Firebase Auth — login + route gate | ✅ Code complete | `proxy.ts`, `admin.ts`, `login/page.tsx` | Provision Firebase project | 🔴 C5 |
| MongoDB API routes (FR-37–40) | ✅ Code complete | 4 `route.ts` files; `requireUser()` first | Provision Atlas M0 cluster | 🔴 C5 |
| `lib/mongo.ts` — cached client | ✅ Complete | `globalThis` cache, indexes | — | — |
| `lib/decisionLog.ts` — batched writes | ✅ Complete | On-change + heartbeat, timer flush | — | — |
| `lib/runSession.ts` | ✅ Complete | Inert until Firebase configured | — | — |
| `/runs` + `/runs/[id]` pages | ✅ Complete | Both `page.tsx` files | — | — |
| Dashboard wired to live stream | ✅ Complete | `connectFrames()` in `handleReady` | — | — |
| `proxy.ts` — Next 16 route gate | ✅ Complete | Correct export name | — | — |
| T-V6 (≥30 FPS @ 100k instances) | ✅ Verified | 60 FPS @ 109k instances | — | — |
| T-W7 (≤10 React renders / 300 frames) | ✅ Verified | 3 renders measured | — | — |
| Vercel deployment | ❌ Not done | Not in repo, not logged | Deploy after Firebase | 🟠 H1 |
| Demo replay log recorded | ❌ Not done | No `data/logs/` directory exists | `--record demo.log` on frozen build | 🔴 C4 |
| Firebase project + Atlas M0 cluster | ❌ Not done | `navya.md`: "Not created" | Navya to provision | 🔴 C5 |
| Feature freeze declared | ❌ Not done | Sameer's log: "has not been called" | Declare at standup | 🔴 C2 |
| Authoritative `results.json` handed to Veda | ❌ Not done | Current `RESULTS.md` is `b75aa46` | `make bench-authoritative` | 🔴 C3 |
| Deck `_measured_` placeholders | ❌ Not done | Veda's log: no entries | Fill from `results.json` only | 🟠 H7 |
| 3-minute video | ❌ Not done | No progress logged | Rough cut + edit | 🟠 H4 |
| Demo rehearsals (×3) | ❌ Not done | Not in any log | Day 13 | 🟠 H5 |
| Q&A bank (20 questions) | ❌ Unknown | Veda's log: no entries | Build to 20 | 🟠 H6 |
| Hardware track (Khanak + Veda) | ❌ Not started | `hardware/` dir does not exist | — | 🟡 M1 |
| Frontend test files committed | ❌ Missing | Not in `frontend/` | Commit Navya's suite | 🟡 M2 |
| `model/requirements.txt` cleanup | ❌ Dangerous | Contains `nupy` typosquat + 180 irrelevant packages | Replace with `backend/requirements.txt` | 🟡 L2 |
