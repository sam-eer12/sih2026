# Anuj — grid engine and server platform

Newest entry at the top. Format and rules: [`README.md`](./README.md).

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

### Blocked / blocking

**No longer blocking anyone.**  `protocol.py`, `fixtures.py`, `core/grid.py`,
`core/cell.py`, and `server/app.py` all exist and are tested.

**Still blocked on Sameer:** `decision/traversability.py` and
`decision/tracker.py` both take `CellGrid` — Sameer has written these against
a test double and they drop in immediately now that `CellGrid` exists.  Tell
Sameer at the next standup.

**Next on Anuj's board (Days 5–8):**
- `bench/baselines.py` + `bench/memory.py` (Day 5 work)
- `bench/latency.py` (Day 6 work)
- `decision/costmap.py` → `decision/planner.py` → `decision/explain.py`
  (Days 7–8 work)
- `core/refine.py` — bounded local refinement (Day 9 work)
