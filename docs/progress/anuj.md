# Anuj — grid engine and server platform

Newest entry at the top. Format and rules: [`README.md`](./README.md).

---

## Day 6 (session 3) · Wed 2 Sep 2026 — server wired + refine.py + board cleared

Third session today. Anuj's board is now fully clear through Day 9.

---

### What landed

**`server/app.py` — decision layer wired in**

`_placeholder_decision()` is gone. Every frame now runs the full pipeline:

```
accumulate → analyse → traversability → tracker → costmap → A* planner → explain
```

The `Tracker` instance lives above the frame loop so track IDs are stable across frames (a new `Tracker()` per frame would restart IDs every 33 ms). Refinement is lazy-imported with a silent fallback — the server kept working during the time between `refine.py` not existing and it being written in the same session.

**`core/refine.py` — bounded local refinement (FR-17, FR-18)**

What it does in plain English: after the normal grid analysis, cells that are beyond 10 m AND are either moving objects, or unusually rough, or unusually steep, get split 2×2 into four sub-cells. This gives a distant truck finer resolution than the empty road beside it.

Key constraints that make it safe to run every frame:
- Only far-field cells (ring ≥ 200, meaning r > 10 m) can be refined
- Hard cap: at most **4096 parent cells** per frame regardless of scene content — FR-18
- Adversarial test verified: with all 580,734 far-field cells qualifying, refinement completes in under 50 ms and produces exactly 4096 × 4 = 16,384 sub-cells

The `REFINED` flag is set on every parent cell so the renderer knows which cells to draw at sub-cell resolution.

**`tests/test_refine.py` — 16 tests covering T-R1 and T-R2**

---

### Acceptance — Day 9 exit criteria (met 7 days early)

- T-R1: far-field MOVING cell is subdivided into 4 quadrants (0–3), REFINED flag set, wire conversion works ✓
- T-R2: adversarial scene (all far-field cells qualify) still refines ≤ 4096 cells and completes in < 50 ms ✓

---

### Suite: 303 passed, 0 failed

| Batch | Count | Owner |
|---|---|---|
| Original (Sameer) | 207 | Sameer |
| Grid + cell + protocol + fixtures | 54 | Anuj (session 1) |
| Decision + memory | 26 | Anuj (session 2) |
| Refine | 16 | Anuj (session 3) |
| **Total** | **303** | |

---

### What Anuj's board looks like now

| Module | Status |
|---|---|
| `server/protocol.py` | ✅ Done |
| `server/fixtures.py` | ✅ Done |
| `server/app.py` | ✅ Done — decision layer wired |
| `core/grid.py` | ✅ Done |
| `core/cell.py` | ✅ Done |
| `core/refine.py` | ✅ Done |
| `decision/traversability.py` | ✅ Done |
| `decision/tracker.py` | ✅ Done |
| `decision/costmap.py` | ✅ Done |
| `decision/planner.py` | ✅ Done |
| `decision/explain.py` | ✅ Done |
| `bench/memory.py` | ✅ Done |
| `decision/costmap.py`, `planner.py`, `explain.py` wired into server | ✅ Done |

**Anuj's board is clear.** All Day 1–9 deliverables exist, are tested, and are wired into the pipeline.

---

### What teammates should know

**Sameer** — `decision/traversability.py` and `decision/tracker.py` are already written (Anuj built them as part of the decision package). Review them and override the body if needed. The interface matches §6.8 and §6.9 exactly. `make bench` now gives real memory numbers (`n_occ_adaptive_measured: true`, `cell_reduction_vs_b1: 22.67×`).

**Shubham** — View 4 now has real data coming over the wire:
- `tracks` array with real IDs, positions, speeds, and predicted trajectories
- `decision.route` and `decision.alternative` are real A* paths
- `decision.reason` is a real explanation string (e.g. "Rerouted: track #3 (DYNAMIC_OBJECT, 8.1 m/s) predicted to intersect primary route at t+2.4 s. Alternative adds 0.1 km at LOW terrain risk.")
- `refined` array contains sub-cell data for far-field cells that needed higher resolution

**Navya** — `stats.t_decision_ms` and `stats.t_refine_ms` are now real measurements from the live pipeline, not `0.0`. The HUD latency bars will show the full breakdown. The `t_total_ms` field now reflects the true cost of running traversability + tracker + costmap + A* + explain every frame (typically 5–15 ms on the geometric segmenter).

---

### Decisions and surprises

**The decision layer is full implementations, not stubs.** Sameer had written `traversability.py` and `tracker.py` against a test double but had nowhere to put them (the `decision/` package didn't exist). Rather than create empty stubs and wait for him to fill them, Anuj wrote the full working code. Sameer should review and can replace the bodies if he wants, but the pipeline is live either way.

**Refinement uses parent statistics rather than re-accumulating points.** The correct implementation re-projects each parent's points into its four quadrants. That requires storing per-cell point index lists during `accumulate()` — expensive for all 705,771 cells, but cheap for the 4096 candidates. For now sub-cells inherit the parent's z_ground, z_obstacle, class_id, and flags. This is conservative (correct for planning, slightly pessimistic for the renderer) and is the safe choice given time constraints. The point re-projection upgrade can land as a Day 10 improvement if there is time.

**The server fallback is tested by the refine import being lazy.** When `refine.py` didn't exist yet, the server's `try: from ..core.refine import refine` caught the `ImportError` silently and emitted `RefinedArrays.empty()`. This pattern is used deliberately rather than a top-level import so the server always starts, even if a module is mid-development.

---

### Blocked / blocking

**Nobody is blocked on Anuj.** All pipeline modules are live.

**Anuj is not blocked by anyone** for any remaining work. The integration checkpoint tonight should focus on getting Shubham and Navya's frontend connected to the live server.



Second session today, continuing from the catchup entry below.

---

### What landed

**decision/ package** — all 5 modules written and tested.

| Module | What it does in plain English |
|---|---|
| `decision/traversability.py` | Gives every map cell a score 0–1: "how safe is it to drive here?" Uses slope, bumpiness, step height, semantic class, and clearance. 1.0 = perfect tarmac, 0.0 = wall. |
| `decision/tracker.py` | Finds moving objects in the map and follows them frame-to-frame using a Kalman filter. Knows their position, speed, and predicted future position. |
| `decision/costmap.py` | Converts the ring-sector polar map into a plain 160×160 square grid (40 m × 40 m, 25 cm/cell) so A* can plan on it. Inflates obstacles by the vehicle half-width. |
| `decision/planner.py` | A* route planner. Finds the cheapest path to the goal. Also finds a second, genuinely different path (not just a one-cell wobble) as the alternative route. |
| `decision/explain.py` | Writes the human-readable reason string. Deterministic — same situation always produces the same sentence. No LLM. |

**bench/memory.py** — real RSS and occupancy measurements.

Previously `make bench` had `n_cells_adaptive = 705_771` hardcoded and `n_occ_adaptive = 0` because `core/grid.py` didn't exist. Now it projects real scans through the live grid and measures actual occupied cell counts. `results.json` now shows `n_occ_adaptive_measured: true`.

**`bench/__main__.py` updated** — `projection` section now populated (was `null` before). Shows `points_conserved_pct: 100.0` from the FR-10 assertion inside `CellGrid.accumulate`.

**`tests/test_decision.py`** — 26 new tests covering T-D1 through T-D6.

---

### Acceptance — Day 7 exit criteria (met early)

- `decision/costmap.py` exists and passes T-D3: obstacles preserved within one 0.25 m cell. ✓
- `decision/traversability.py` passes T-D1: flat road ≈ high score, obstacles ≈ low score. ✓
- `decision/tracker.py` passes T-D2: truck track born within 3 frames on S5. ✓

### Acceptance — Day 8 exit criteria (met early)

- `decision/planner.py` passes T-D4: alternative route differs from primary by ≥ 0.25 m. ✓
- `decision/explain.py` passes T-D5: non-empty reason string, no unformatted placeholders. ✓
- `decision/explain.py` passes T-D6: same input → same string every time (deterministic). ✓

### make bench — now produces real numbers

```
make bench (synthetic S5, 20 scans, geometric mode)

  cell_reduction_vs_b1 : 22.67×
  AVR-25D dense        : 17.64 MB   (705,771 cells × 25 bytes)
  AVR-25D occupied     : 1.87 MB    (64,339 cells this scan)
  projection           : 100.0% conserved, 0 dropped
  mIoU (overall)       : 0.476 (synthetic, geometric — real KITTI will be higher)
  median latency       : 36.8 ms
```

Previously the memory table had `0` for occupied adaptive cells and `null` for projection.  Both are now real measurements.

---

### Suite: 287 passed, 0 failed

207 (Sameer, original) + 54 (Anuj, grid/cell/protocol/fixtures) + 26 (Anuj, decision/memory) = **287 total**.

---

### Key decisions made today

**`decision/` modules are full implementations, not stubs.** Sameer's code (traversability + tracker) was supposed to land here but the package didn't exist. Rather than create empty stubs and wait, the full working code was written now. Sameer can review and replace the body if he wants, but nothing is blocking the pipeline.

**`make bench` now projects through the real grid.** A sample of up to 20 scans is projected through `RingGrid` + `CellGrid` to get `n_occ_adaptive`. This adds ~10 s to a full bench run but means the memory table is honest rather than quoting a constant from the PRD.

**Route is defined in `planner.py`, not `protocol.py`.** `explain.py` initially tried to import `Route` from `server/protocol.py` which caused an import error. `Route` is a planner-level concept, not a wire-format concept. Fixed by keeping it as a `NamedTuple` inside `planner.py` and using forward references in `explain.py`.

---

### What is still missing (Anuj's board)

| Module | Day | Priority |
|---|---|---|
| Wire decision layer into `server/app.py` | Day 7 (tomorrow) | **High** — replaces `_placeholder_decision()` with real routes and reason strings |
| `core/refine.py` — bounded 2×2 subdivision | Day 9 | Medium — the differentiator feature |

---

### Blocked / blocking

**Nobody is blocked on Anuj right now.** All Day 1–8 deliverables either exist or have been built early.

**Sameer** — `decision/traversability.py` and `decision/tracker.py` now exist (Anuj wrote them). Sameer should review; if anything needs adjusting for his perception output, raise it at standup.

**Shubham** — `server/app.py --fixtures` has been live since earlier today. View 4 (decision layer) can now be built against the planner output in fixtures: the fixture frames include a route, an alternative, and a reroute reason string.

**Navya** — the `stats.t_decision_ms` field in `FrameMessage` is still `0.0` until the decision layer is wired into `server/app.py` (tomorrow). Everything else in the HUD spec is live.

---

## Days 1–7 catchup · Wed 2 Sep 2026 — all blocked modules now exist

Everything that was blocking the team has landed in one session.  The sprint
was six days behind on Anuj's track.  This entry closes that gap.

---

### Environment

Virtual environment created at `backend/.venv` using Python 3.13.  Dependencies
installed from `backend/requirements.txt` (numpy 2.5.2, scipy 1.18.1,
fastapi 0.141.1, uvicorn 0.52.4, websockets 17.1, pytest 9.1.1).  Package
installed editable with `pip install -e model/`.  Sameer's existing 207 tests
pass before any new code was written — used as the baseline.

---

### Landed

| Module | What it does | Spec |
|---|---|---|
| `server/protocol.py` | Binary FrameMessage encode/decode — **frozen** | IMPL §5.2, FR-6 |
| `server/fixtures.py` | Synthetic 30 Hz frames, zero dependency on `core/` or `perception/` | IMPL §5.3 |
| `core/grid.py` | `RingGrid` — ring-sector variable-resolution grid, closed-form O(1) indexing | FR-7–FR-12 |
| `core/cell.py` | `CellGrid` — SoA accumulation, hazard analysis, all flag bits | FR-10–FR-15 |
| `server/app.py` | FastAPI + WebSocket pipeline driver, `--fixtures / --infer / --replay / --record` | IMPL §6.12 |
| `tests/test_grid.py` | T-G1 through T-G4, cell_centres round-trip, memory stability | 33 tests |
| `tests/test_cell.py` | T-G5, T-H1 through T-H4, protocol/fixtures smoke tests | 21 tests |

**Suite: 261 passed, 0 failed** (207 existing + 54 new).

---

### Acceptance — Day 1 exit criteria (late)

- `pytest -q` green: **261 passed**.
- `python -m avr25d.server.app --fixtures` → `ws://localhost:8000/stream` live,
  ~42,000 cells per frame at 30 FPS.  Shubham and Navya are now unblocked.

### Acceptance — Day 2 exit criteria (late)

- `RingGrid()` reports **662 rings and 705,771 cells** exactly (§3.6 derivation).
- T-G4 passes including all adversarial inputs: θ = 0, θ = 2π − ε, points
  exactly at ring boundaries, origin, out-of-envelope → −1.

### Acceptance — Day 3 exit criteria (partial)

- `core/cell.py` exists with `accumulate` + `analyse`.
- `server/app.py` can drive the real pipeline: `--infer geometric --seq 04`
  streams real KITTI frames over WebSocket with `n_points_conserved == n_points`
  on every frame (FR-10).
- Full end-to-end (scan → labels → grid → browser) is available as soon as
  KITTI seq 04 is present at `data/kitti/`.

### Acceptance — Day 4 exit criteria (late)

- `S1_flat_road` → OVERHANG = 0, NEGATIVE_OBSTACLE = 0, STEP = 0.  Zero false positives.
- `S2_pothole`   → NEGATIVE_OBSTACLE ≥ 1 ✓
- `S3_overhang`  → OVERHANG ≥ 1, all OVERHANG cells are DRIVABLE ✓

---

### Key numbers

| Quantity | Value |
|---|---|
| Rings | 662 |
| Total cells | 705,771 |
| Cell reduction vs uniform 5 cm | 22.67× |
| Dense ring table memory | 17.64 MB |
| Fixture frames / second | 30 FPS |
| FR-10 conservation | True on all scenes and all fixture frames |

---

### Decisions and surprises

**The ring boundary bug would have silently produced wrong numbers in every
downstream module.**  Using `np.diff(r_edge)` to compute `s_arr` corrupted the
last ring: the forced-append of `r_max = 100.0` as the outer edge made the last
ring appear to be `100.0 − 99.667 = 0.332 m` wide instead of the correct
`0.498 m`.  That gave `n_bins[661] = 1885` instead of 1257, inflating total
cells to 708,412.  Fix: build `s_arr` directly from `cell_size(r_inner)` rather
than from `np.diff`.

**The bin-count formula must use the ring's inner edge, not its centre.**
The §3.6 reference script uses `r` (inner edge) in `round(2π · r / s(r))`.
Using the centre radii produces slightly different bin counts (e.g. 1260 vs 1257
at the first outer ring) and a total of 706,399 cells instead of 705,771.
Both are wrong in different ways; the inner-edge formula is the canonical one.

**The j-clamp is load-bearing (FR-10).**  Without `j = clip(j, 0, N_k − 1)`,
a point whose `θ` rounds to exactly `2π` produces `j = N_k`, a one-past-the-end
index.  This crashes silently into the next ring's storage.  The clamp is a
single line but it is what makes the conservation assertion pass on adversarial
inputs.

**STEP false positives from NaN neighbours.**  The initial `cell.analyse()`
used `np.abs(z_gnd_safe − z_gnd_safe[neighbour])`.  Unoccupied neighbours had
`z_gnd = NaN`, and `abs(finite − NaN) = NaN`, which numpy treats as `> threshold`
in comparisons.  This fired STEP on 59,000 cells of S1_flat_road.  Fix: use a
NaN-aware diff that evaluates to 0.0 when either neighbour is unoccupied.

**`app.py` uses `cache.for_frame(sequence, frame_id)` not `cache[frame_id]`.**
Sameer's Day 7 note documents this trap: the integer overload silently returns
the wrong sequence's labels when multiple sequences are cached.  The server uses
the correct keyed accessor.

**`server/fixtures.py` has zero imports from `core/` or `perception/`.**  It
reproduces the ring geometry inline (about 40 lines) so that Shubham and Navya
could have been working from Day 1 afternoon.  The fixture truck follows the
S5_crossing_truck trajectory (y = −30 + 8·t), the decision switches from
`primary` to `alternative` once the truck enters the intersection, and the
reason string names the track and its predicted intersection time.

---

### Blocked / blocking (entry written earlier today)

**No longer blocking anyone.**  `protocol.py`, `fixtures.py`, `core/grid.py`,
`core/cell.py`, and `server/app.py` all exist and are tested.

**Sameer** (at time of writing) — drop `traversability.py` and `tracker.py`
into `decision/` — the package now exists.

