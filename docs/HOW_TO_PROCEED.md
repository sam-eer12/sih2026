# How Anuj Should Proceed — Step-by-Step

> You are reading the codebase for the first time and need to build
> `protocol.py`, `fixtures.py`, `core/grid.py`, `core/cell.py`, and `server/app.py`
> without errors, in the right order.
>
> This document tells you exactly what to do, step by step, command by command.

---

## Before You Write a Single Line of Code

### Step 1 — Set up your Python environment

The project has a specific virtual environment. Run these commands from the
repo root:

```bash
cd /Users/anuj/Desktop/sih2026

# Create the virtual environment inside backend/
python3 -m venv backend/.venv

# Activate it
source backend/.venv/bin/activate

# Install all dependencies
pip install -r backend/requirements.txt

# Install the avr25d package in editable mode (so your imports work)
pip install -e model/
```

**How to verify it worked:**

```bash
cd model
python3 -m pytest -q
```

You should see something like `207 passed` with zero errors. If it says
"command not found: pytest", you forgot to activate the venv. Run
`source backend/.venv/bin/activate` again.

> Every time you open a new terminal to work on this project, run
> `source backend/.venv/bin/activate` first.

---

## Understanding Where Your Files Go

The repo currently has this structure inside `model/avr25d/`:

```
model/avr25d/
├── config.yaml          ← all tunable numbers (already exists)
├── config.py            ← loads config.yaml (already exists)
├── perception/          ← Sameer's work (all exists)
├── synth/               ← Sameer's work (all exists)
├── bench/               ← Sameer's work (all exists)
├── io/                  ← Sameer's work (kitti.py exists)
├── core/                ← YOUR work — THIS DIRECTORY DOES NOT EXIST YET
│   ├── __init__.py      ← you create this (can be empty)
│   ├── grid.py          ← you create this
│   └── cell.py          ← you create this
└── server/              ← YOUR work — THIS DIRECTORY DOES NOT EXIST YET
    ├── __init__.py      ← you create this (can be empty)
    ├── protocol.py      ← you create this FIRST
    ├── fixtures.py      ← you create this SECOND
    └── app.py           ← you create this LAST
```

---

## The Build Order (Do NOT skip steps)

```
1. protocol.py      ← defines the message format (no dependencies)
2. fixtures.py      ← generates fake frames using protocol.py
3. core/grid.py     ← the ring math (no dependencies)
4. core/cell.py     ← uses grid.py
5. server/app.py    ← uses everything above
```

---

## Module 1: `server/protocol.py`

**What it does:** Defines the binary message format the backend sends to the
frontend, 30 times per second. It is a frozen contract — once written, it
does not change without team sign-off.

**Your task:** Create the directory and the file.

```bash
mkdir -p model/avr25d/server
touch model/avr25d/server/__init__.py
```

Now create `model/avr25d/server/protocol.py`. The full message schema is
defined in `IMPLEMENTATION_PLAN.md §5.2`. Here is what it needs to contain:

```python
"""FrameMessage encode/decode — FROZEN after Day 1.

Binary format: a length-prefixed JSON header followed by concatenated
typed-array payloads.  The browser reads cell data straight into
Float32Array / Uint8Array with zero per-cell parsing.

Wire layout (little-endian):
  [4 bytes] header_len  — uint32, byte length of the JSON header
  [header_len bytes]    — UTF-8 JSON (the FrameMessage dict, with
                          typed-array fields replaced by placeholder strings)
  [payload bytes...]    — the typed arrays in the order listed in `cells`
                          and `refined`, then nothing for tracks/decision/stats
                          (those are fully in the JSON header)
"""
```

The JSON header carries ALL fields. The typed-array payloads carry ONLY the
dense cell arrays (because they are too large to put in JSON). Here is the
exact schema (copy from `IMPLEMENTATION_PLAN.md §5.2`):

```python
# The FrameMessage dict structure (what the JSON header looks like):
{
  "frame_id":  int,
  "t_sec":     float,
  "mode":      str,   # "live" | "cached" | "geometric"

  "cells": {
    "n":          int,
    "cell_id":    "uint32[n]",    # these strings are PLACEHOLDERS in the JSON
    "ring":       "uint16[n]",    # the real data is in the binary payload
    "bin":        "uint16[n]",
    "z_ground":   "float32[n]",
    "z_obstacle": "float32[n]",
    "roughness":  "float32[n]",
    "slope":      "float32[n]",
    "class_id":   "uint8[n]",
    "confidence": "uint8[n]",
    "flags":      "uint8[n]",
  },

  "refined": { "n": int, ... },   # same pattern

  "tracks": [...],                # fully in JSON
  "decision": {...},              # fully in JSON
  "stats": {...},                 # fully in JSON
}
```

**The minimum viable `protocol.py` that unblocks the frontend:**

At minimum it needs two things:
1. A `FrameMessage` dataclass (or TypedDict) that defines the structure
2. `encode(msg) -> bytes` and `decode(data: bytes) -> dict` functions

The frontend's `lib/protocol.ts` mirrors this file exactly.

---

## Module 2: `server/fixtures.py`

**What it does:** Emits fake-but-schema-valid `FrameMessage`s. Has ZERO
dependency on `core/` or `perception/`. This is the "anti-blocking device"
that lets Shubham and Navya build the entire dashboard independently.

**Key requirement:** When the server is started with `--fixtures`, this
module generates the frames. The frontend should be able to render them,
animate a moving track, and populate the HUD — all without the real pipeline.

**What to generate:**
- A flat synthetic ground plane (~50,000 cells with class DRIVABLE)
- A few static obstacle cells (class STATIC_OBSTACLE)
- One moving DYNAMIC_OBJECT track with a crossing trajectory
- Plausible route and decision
- Plausible stats (fps ~30, latency numbers in range)

**The cells should look like the real adaptive grid:** use the ring geometry.
The simplest approach is to iterate over a range of (ring, bin) pairs and
compute (x, y) centres from them, rather than running the real grid engine.

---

## Module 3: `core/grid.py`

**What it does:** The mathematical heart of the project. Implements the
variable-resolution ring-sector grid. Everything downstream depends on this.

**The math (from `IMPLEMENTATION_PLAN.md §3`):**

```
Cell size:
  s(r) = 0.05 m          for r <= 10 m    (200 rings of 5 cm each)
  s(r) = 0.005 * r       for r > 10 m     (grows proportionally → 50 cm at 100 m)

Ring boundaries:
  r[k+1] = r[k] + s(r[k])
  → inner rings: uniform, 5 cm spacing
  → outer rings: geometric progression, ratio 1.005

Ring count:
  K_inner = 200
  K_outer = floor(ln(100/10) / ln(1.005)) = 462
  K_total = 662

Bins per ring (angular sectors):
  N_k = round(2π * r_k / s(r_k))
  → This makes cells approximately SQUARE at every distance
  → For outer rings (r > 10 m): N_k = round(2π / 0.005) = 1257, CONSTANT

Total cells: 705,771

Closed-form ring lookup (no searching):
  r <= 10 m:  k = floor(r / 0.05)
  r > 10 m:   k = 200 + floor(ln(r / 10) / ln(1.005))

Flat cell id:
  offset = cumulative sum of [N_0, N_1, ..., N_661]  (precomputed once)
  j = floor(theta / (2*pi) * N_k)    where theta = arctan2(y, x) % (2*pi)
  cell_id = offset[k] + j
```

**The `RingGrid` class interface (from `IMPLEMENTATION_PLAN.md §6.1`):**

```python
class RingGrid:
    def __init__(self, s_min=0.05, s_max=0.50, r_knee=10.0, r_max=100.0):
        # Build the ring table ONCE at startup. Never rebuild per frame.
        # self.n_rings  : int        = 662
        # self.r_edge   : float32[663]    inner radii of each ring (plus the outer edge)
        # self.s        : float32[662]    radial cell size per ring
        # self.n_bins   : int32[662]      sector count per ring
        # self.offset   : int32[663]      prefix sum; offset[-1] = 705_771
        # self.n_cells  : int        = 705_771

    def ring_of(self, r: np.ndarray) -> np.ndarray:
        # Closed-form ring index, fully vectorised (FR-9).
        # MUST use np.where for the two branches — ONE pass, not two.
        # Returns -1 for r > r_max (out of range).

    def cell_of(self, x, y) -> tuple[np.ndarray, np.ndarray]:
        # (x, y) -> (cell_id, valid_mask)
        # One vectorised pass, no Python loop (FR-9, FR-11).
        # CRITICAL: clamp j to n_bins[k] - 1 to handle the floating-point
        #   edge case where theta rounds to exactly 2*pi. Missing this clamp
        #   is the #1 way the conservation test (T-G4) fails.

    def cell_centres(self, cell_id) -> np.ndarray:
        # Inverse map: cell_id -> (x, y) centre coordinates.
        # Used by the renderer and the costmap.

    def cell_extents(self, cell_id) -> np.ndarray:
        # (radial_extent, tangential_extent) per cell.
        # Used by the renderer to draw correctly-sized boxes.
```

**The one clamp you MUST NOT forget:**

```python
j = np.floor(theta / (2 * np.pi) * n_bins_k).astype(np.int32)
j = np.minimum(j, n_bins_k - 1)   # ← this single line is the difference between
                                    #   passing and failing T-G4
```

**How to verify it worked:**

```bash
cd model
python3 -c "
from avr25d.core.grid import RingGrid
g = RingGrid()
print('rings:', g.n_rings)    # must print 662
print('cells:', g.n_cells)    # must print 705771
"
```

---

## Module 4: `core/cell.py`

**What it does:** Takes the point cloud and accumulates each point into its
cell. Then analyses each cell to detect hazards. Sameer needs this to write
`traversability.py` and `tracker.py`.

**The `CellGrid` class interface (from `IMPLEMENTATION_PLAN.md §6.2`):**

```python
class CellGrid:
    def __init__(self, grid: RingGrid):
        # Allocate ALL SoA arrays ONCE here. NEVER allocate per frame (FR-12).
        # self.z_ground   = np.full(grid.n_cells, np.nan, dtype=np.float32)
        # self.z_obstacle = np.full(grid.n_cells, np.nan, dtype=np.float32)
        # self.z_min      = np.full(grid.n_cells, np.nan, dtype=np.float32)
        # self.roughness  = np.zeros(grid.n_cells, dtype=np.float32)
        # self.slope      = np.zeros(grid.n_cells, dtype=np.float32)
        # self.class_id   = np.zeros(grid.n_cells, dtype=np.uint8)
        # self.confidence = np.zeros(grid.n_cells, dtype=np.uint8)
        # self.flags      = np.zeros(grid.n_cells, dtype=np.uint8)
        # self.count      = np.zeros(grid.n_cells, dtype=np.uint16)

    def reset(self) -> None:
        # Zero / NaN the arrays IN PLACE. No reallocation, ever.

    def accumulate(self, xyz, intensity, labels) -> AccumStats:
        # Scatter points into cells. One vectorised pass (FR-11).
        # Use np.add.at / np.minimum.at / np.maximum.at for scatter-reduce.
        # Returns AccumStats(n_points_in, n_points_assigned).
        # n_points_in == n_points_assigned MUST always be true (FR-10).

    def analyse(self, cfg) -> None:
        # After accumulate(), derive:
        #   slope      — ring-neighbour z_ground gradient
        #   roughness  — variance of z among ground-labelled returns
        # Then set flags:
        #   OVERHANG          (FR-13)
        #   NEGATIVE_OBSTACLE (FR-14)
        #   STEP              (FR-15)
        #   VOID_UNOBSERVED
        #   LOW_CONFIDENCE
```

**The flag bits (from `PRD.md §6.3`):**

```python
FLAG_OCCUPIED           = 1 << 0   # count > 0
FLAG_VOID_UNOBSERVED    = 1 << 1   # count == 0 and inside FoV
FLAG_OVERHANG           = 1 << 2   # drivable + z_obstacle - z_ground < H_vehicle
FLAG_NEGATIVE_OBSTACLE  = 1 << 3   # pothole — z_ground drop vs neighbours
FLAG_STEP               = 1 << 4   # curb — z_ground jump to 4-neighbour
FLAG_MOVING             = 1 << 5   # has a moving-* label
FLAG_REFINED            = 1 << 6   # subdivided
FLAG_LOW_CONFIDENCE     = 1 << 7   # confidence < tau_conf
```

**z_ground estimation (critical detail from `IMPLEMENTATION_PLAN.md §6.2`):**

Do NOT use the minimum z in the cell — one bad return would manufacture a pothole.
Use the **10th percentile** of returns whose label is DRIVABLE or NON_DRIVABLE_TERRAIN.
Approximate this with a running min-of-3 (take the 3rd lowest z value in the cell)
— this is within a centimetre on real data and stays vectorised.

**Ring-neighbour topology (important):**

Rings above 10 m all have the same bin count (1257), so the neighbour of bin `j`
in ring `k` is just bin `j` in ring `k+1`. Easy.

Rings below 10 m have different bin counts, so the neighbour of bin `j` in ring `k`
is `round(j * n_bins[k+1] / n_bins[k])` in ring `k+1`. Precompute this table once.

---

## Module 5: `server/app.py`

**What it does:** FastAPI server that runs the pipeline and streams
`FrameMessage`s over WebSocket at 30 Hz. Also serves `--fixtures` mode.

**Usage:**
```bash
python -m avr25d.server.app --fixtures              # fake frames, frontend unblocked
python -m avr25d.server.app --infer geometric       # real pipeline, geometric labels
python -m avr25d.server.app --infer cached --seq 04 # real pipeline, cached labels
```

**Key design decisions (from the PRD):**

1. The pipeline runs in a **worker thread**. The WebSocket handler just picks up
   the latest frame from a queue — it never runs perception itself.

2. **Drop frames rather than queue them.** If a client falls behind, skip frames.
   A demo that runs at 15 FPS is fine. A demo that builds up a 5-second backlog
   and then plays it back out of sync is not.

3. The `mode` field in FrameMessage must match the actual mode being used
   (`live` / `cached` / `geometric`). Sameer's cache uses
   `cache.for_frame(sequence, frame_id)`, NOT `cache[frame_id]`.

---

## Module 6: `core/refine.py` (comes after cell.py)

**What it does:** Subdivides far-field cells that are MOVING or have high
roughness/slope, into 2×2 sub-cells. Bounded at 4096 cells per frame (FR-18).

This is Day 9 work — build it after the core pipeline is working end-to-end.

---

## The Tests You Need to Pass

Once you have `core/grid.py` done, you should be passing these:

| Test file | Tests |
|---|---|
| (doesn't exist yet) | You need to create `tests/test_grid.py` |

The plan specifies T-G1 through T-G6. The most important is **T-G4** —
the conservation test. Write this test yourself:

```python
def test_conservation():
    from avr25d.core.grid import RingGrid
    import numpy as np
    grid = RingGrid()
    rng = np.random.default_rng(42)
    # 1 million random points inside the 100 m envelope
    r = rng.uniform(0, 100, 1_000_000)
    theta = rng.uniform(0, 2*np.pi, 1_000_000)
    x = r * np.cos(theta)
    y = r * np.sin(theta)
    cell_ids, valid = grid.cell_of(x, y)
    # Every point inside the envelope must map to a valid cell
    assert valid.all(), f"{(~valid).sum()} points dropped"
    # Adversarial: points exactly at ring boundaries, at theta = 0 and 2*pi - eps
    r_boundaries = grid.r_edge[1:-1]  # all 661 internal ring boundaries
    for r_b in r_boundaries[:10]:     # test a sample
        x_b = np.array([r_b, r_b])
        y_b = np.array([0.0, 1e-10])
        ids, v = grid.cell_of(x_b, y_b)
        assert v.all()
```

---

## Build Checklist — Tick These Off In Order

```
[ ] 1. Virtual environment created and activated
[ ] 2. pip install -r backend/requirements.txt
[ ] 3. pip install -e model/
[ ] 4. python3 -m pytest -q  →  207 passed (Sameer's tests, verifies setup)

[ ] 5. mkdir model/avr25d/server && touch model/avr25d/server/__init__.py
[ ] 6. Write server/protocol.py
[ ] 7. Write server/fixtures.py
[ ] 8. Tell Shubham + Navya: "fixtures are live, start building"

[ ] 9. mkdir model/avr25d/core && touch model/avr25d/core/__init__.py
[ ] 10. Write core/grid.py
[ ] 11. Verify: RingGrid() → 662 rings, 705,771 cells
[ ] 12. Write test_grid.py and run it

[ ] 13. Write core/cell.py
[ ] 14. Verify hazard flags on synthetic scenes:
         python3 -c "
         from avr25d import load_config
         from avr25d.synth import load_scene, raycast, SensorSpec
         from avr25d.perception import labelmap
         from avr25d.core.grid import RingGrid
         from avr25d.core.cell import CellGrid

         cfg = load_config()
         sensor = SensorSpec()
         grid = RingGrid()
         cells = CellGrid(grid)

         for scene_name in ['S1_flat_road', 'S2_pothole', 'S3_overhang']:
             scene = load_scene(scene_name)
             xyzi, packed = raycast(scene, sensor)
             semantic, _ = labelmap.split_label(packed)
             avr_labels = labelmap.raw_to_avr(semantic)

             cells.reset()
             cells.accumulate(xyzi[:, :3], xyzi[:, 3], avr_labels)
             cells.analyse(cfg)

             n_overhang = int((cells.flags & 0x04).astype(bool).sum())
             n_pothole  = int((cells.flags & 0x08).astype(bool).sum())
             print(f'{scene_name}: OVERHANG={n_overhang}, POTHOLE={n_pothole}')
         # Expected:
         # S1_flat_road:  OVERHANG=0, POTHOLE=0  ← zero false positives
         # S2_pothole:    OVERHANG=0, POTHOLE>0  ← pothole detected
         # S3_overhang:   OVERHANG>0, POTHOLE=0  ← overhang detected
         "

[ ] 15. Write server/app.py
[ ] 16. Test end-to-end:
         python3 -m avr25d.server.app --fixtures
         # Open browser, verify cells render
```

---

## Common Mistakes to Avoid

**In `grid.py`:**
- Using `np.log` vs `np.log(1.005)` — must be the natural log (base e), not log base 10
- Forgetting the `j = np.minimum(j, n_bins[k] - 1)` clamp on the angular bin
- Using two separate array passes for r <= 10 and r > 10 — use `np.where` for one pass
- `arctan2(y, x)` can return negative values; use `% (2*np.pi)` to normalise to [0, 2π)

**In `cell.py`:**
- Allocating new arrays inside `reset()` — use in-place operations (`[:] = 0`, `np.fill`)
- Using `np.min` instead of `np.minimum.at` for the scatter-reduce (`.at` is scatter,
  plain `np.min` is a reduction over the whole array)
- `np.add.at` is slow on large arrays — this is expected and acceptable; it's the correct
  approach. The alternative is to sort by cell_id and use `np.reduceat`, but that's
  an optimisation for later.

**In `fixtures.py`:**
- Don't import anything from `core/` or `perception/` — the whole point is zero dependency
- Make sure the `n_points_conserved == n_points` field in stats is correct (both equal)
- The `mode` field must be one of `"live"`, `"cached"`, `"geometric"`

**In `app.py`:**
- Use `cache.for_frame(sequence, frame_id)` not `cache[frame_id]` (Sameer's bug note)
- Run the pipeline in a worker thread, not in the WebSocket handler
- Drop frames rather than queue them when the client is slow

---

## How to Know You Are Done

**`server/protocol.py` + `server/fixtures.py` done when:**
```bash
python3 -m avr25d.server.app --fixtures
# ws://localhost:8000/stream is sending frames
# Shubham/Navya can connect and see cells
```

**`core/grid.py` done when:**
```python
from avr25d.core.grid import RingGrid
g = RingGrid()
assert g.n_rings == 662
assert g.n_cells == 705_771
# And the conservation test passes (T-G4)
```

**`core/cell.py` done when:**
- S1_flat_road: zero OVERHANG, zero NEGATIVE_OBSTACLE, zero STEP flags
- S2_pothole: at least one NEGATIVE_OBSTACLE flag
- S3_overhang: at least one OVERHANG flag with clearance ~3.10 m

**`server/app.py` done when:**
```bash
python3 -m avr25d.server.app --infer geometric --seq 04
# Real KITTI scan → labels → grid → browser, n_points_conserved on the HUD
```

---

## What Sameer Is Waiting For

Once `core/cell.py` exists, Sameer can immediately drop in:
- `decision/traversability.py` — uses `cells.z_ground`, `cells.slope`,
  `cells.roughness`, `cells.flags`, `cells.confidence`
- `decision/tracker.py` — uses `cells.class_id`, `cells.flags` (MOVING bit)
- `bench/hazard.py` — uses the OVERHANG/NEGATIVE_OBSTACLE/STEP flags
- `bench/memory.py` — uses `grid.n_cells` and counts occupied cells

Tell Sameer when `core/cell.py` is pushed. He has these four modules already
written against a test double and they will drop in the same day.
