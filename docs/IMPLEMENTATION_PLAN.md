# Implementation Plan — AVR-25D

**SIH26053 · Adaptive Variable Resolution 2.5D LiDAR Mapping for Dynamic Environment Perception**

| | |
|---|---|
| Companion documents | [`PRD.md`](./PRD.md) · [`WORK_DISTRIBUTION.md`](./WORK_DISTRIBUTION.md) |
| Phase 1 deadline | **Thu 10 September 2026** — internal hackathon: PPT + video + prototype + live demo |
| Phase 2 deadline | Sun 20 September 2026 — SIH portal |
| Plan written | Fri 28 August 2026 |

This document is the build instruction. `PRD.md` says *what* and *why*; this says *how*,
*in what order*, and *who*. Requirement IDs (`FR-n`, `NFR-n`) refer to `PRD.md` §7 and §8.

---

## 1. How to use this plan

1. Read §2 and set up your environment **today**. An environment problem discovered on Day 4
   costs a day; discovered on Day 1 it costs an hour.
2. Read §3 if you touch the grid. It is the mathematical core and everything else assumes it.
3. Find your modules in §6. Each has a public interface that is a contract — other people are
   coding against it before you have written the body.
4. Read §5 — the wire protocol. It is frozen on Day 1. Everyone depends on it.
5. Work the schedule in §8 and hit the daily exit criteria. If you will miss one, say so at
   standup, not at midnight.

**The single most important rule in this plan:** nobody blocks on anybody. §5.3's fixture
generator exists so the two frontend developers can build the entire dashboard against
schema-valid synthetic frames before the backend produces a single real one. If you find
yourself waiting, you are doing it wrong — go read §5.

---

## 2. Environment

### 2.1 Dependencies

Pinned. Do not upgrade during the sprint.

```
python        >= 3.10, < 3.13
numpy         == 1.26.4
scipy         == 1.13.1        # KD-tree for k-NN label reprojection, RANSAC helpers
onnxruntime   == 1.18.0        # CPU execution provider only
fastapi       == 0.111.0
uvicorn       == 0.30.1
websockets    == 12.0
pyyaml        == 6.0.1
pytest        == 8.2.2
psutil        == 5.9.8         # RSS measurement for the memory benchmark
numba         == 0.59.1        # OPTIONAL, behind a flag (NFR-3)
```

Frontend uses Three.js `r165` vendored into `web/vendor/` — **not** loaded from a CDN. A
live demo must not depend on conference wifi.

### 2.2 Setup — identical on macOS and Windows

```bash
git clone <repo> && cd sih2026
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
pytest -q                      # must pass before you write anything
python -m avr25d.server.app --fixtures   # dashboard on http://localhost:8000
```

**NFR-4 is load-bearing.** No CUDA, no `spconv`, no `torchsparse`, no compiled extension, no
platform-specific build step. If a dependency needs a C++ toolchain, it does not go in
`requirements.txt`. Numba is optional and every Numba-accelerated function has a NumPy
sibling selected by `config.yaml: use_numba`.

### 2.3 Day-1 cross-platform smoke test

Both a Mac and the Windows box run `pytest -q` and `--fixtures` on Day 1 evening. Divergence
found on Day 1 is an hour; found on Day 11 it is the project (risk R-5).

---

## 3. The grid — mathematics and derivation

This is the technical core (FR-7…FR-12) and the part evaluators will interrogate. Everything
here is derived, not chosen by feel.

### 3.1 Requirement

PS-6 fixes two endpoints: 5 cm cells within a 10 m radius, 50 cm cells out to 100 m. The
interpolation between them is ours to choose.

### 3.2 Radial cell size

```
s(r) = 0.05                       for r ≤ 10 m
s(r) = min(0.005 · r, 0.50)       for r > 10 m
```

The exponent is 1 — cell size grows **linearly** with range — because that is what makes the
endpoints meet exactly: at `r = 100`, `0.005 × 100 = 0.50 m`, and at `r = 10`,
`0.005 × 10 = 0.05 m`. The function is continuous at `r = 10` and hits the PS's second
endpoint precisely at 100 m. No tuning constant is involved.

### 3.3 Ring boundaries

Rings are laid down by `r_{k+1} = r_k + s(r_k)`. Below 10 m this is 200 uniform 5 cm rings.
Above 10 m it becomes

```
r_{k+1} = r_k + 0.005·r_k = r_k · 1.005
```

— a **geometric progression with ratio 1.005**. The count of outer rings therefore has a
closed form:

```
K_outer = ln(100/10) / ln(1.005) = 2.302585 / 0.0049875 = 461.7  →  462 rings
K_total = 200 + 462 = 662 rings
```

Because the progression is geometric, the ring index inverts in closed form, which is what
makes FR-9's O(1) lookup possible:

```
k = floor(r / 0.05)                          for r ≤ 10 m
k = 200 + floor(ln(r / 10) / ln(1.005))      for r > 10 m
```

No search, no binary search over a boundary table, no iteration.

### 3.4 Angular bins — the isotropy condition

A polar grid with a fixed sector count produces slivers near the sensor and wedges far away.
We instead choose the sector count per ring so the tangential extent matches the radial:

```
N_k = round( 2π · r_k / s(r_k) )
```

Beyond 10 m, substitute `s(r) = 0.005·r`:

```
N_k = 2π·r / (0.005·r) = 2π / 0.005 = 1257,  independent of r
```

**The angular bin count is constant at 1257 for the entire far field.** Each far-field bin
subtends `360°/1257 = 0.286°` at every range. This is not a coincidence to be admired — it is
the direct consequence of choosing `s(r) ∝ r`, and it produces three properties worth stating
to an evaluator:

1. **Isotropic cells everywhere.** Verified numerically — at r = 5, 10, 20, 30, 50, 70 and
   100 m the radial and tangential extents agree to the centimetre (§3.6). Every cell is a
   square, at every range. Slope and roughness estimates are therefore unbiased with respect
   to orientation, which is not true of a fixed-sector polar grid.
2. **Resolution matched to the sensor.** A Velodyne HDL-64E at 10 Hz samples about 0.173°
   horizontally and 0.4° vertically. Our far-field bin of 0.286° sits between the two. The
   grid therefore never subdivides finer than the sensor actually measured. Far-field
   coarsening is not discarding measured detail — it is declining to fabricate detail that
   was never there. This is the answer to "doesn't your compression lose information?"
3. **Constant-width azimuth arrays.** The far field is a rectangular `462 × 1257` block, which
   vectorises and caches well.

### 3.5 Flat indexing

```
offset = cumsum([0, N_0, N_1, ..., N_660])      # 662 entries, built once at startup
cell_id = offset[k] + j,  where  j = floor(θ_normalised / (2π) · N_k)
```

One integer add on a contiguous 662-element table that lives permanently in L1 cache. This is
FR-9, and it is the concrete meaning of PS-4's "sophisticated data structure that can handle
variable resolution without causing alignment errors."

**Why alignment errors cannot occur here.** The classic failure mode PS-4 warns about arises
when you tile several uniform grids of different resolution: their boundaries do not coincide,
points near a seam are ambiguous, and reconciling them needs interpolation that invents or
destroys data. AVR-25D has no seams — there is a single analytic function from `(r, θ)` to a
cell id, defined over the whole envelope, total and single-valued. A point cannot fall between
two cells because the function is defined everywhere, and it cannot fall into two because the
function returns one value. FR-10's per-frame assertion `Σ count == n_points` turns that
argument into a measurement.

### 3.6 Reproducing the numbers

Ships as `tools/ring_table.py`. Anyone can re-derive every figure in the PRD:

```python
import math
S_MIN, S_MAX, R_KNEE, R_MAX = 0.05, 0.50, 10.0, 100.0

def cell_size(r):
    return S_MIN if r <= R_KNEE else min(S_MIN * (r / R_KNEE), S_MAX)

rings, r = [], 0.0
while r < R_MAX:
    s = cell_size(r); rings.append((r, s)); r += s

bins  = [max(1, round(2 * math.pi * r / s)) if r > 0 else 1 for r, s in rings]
total = sum(bins)

print(f"rings                    {len(rings)}")            # 662
print(f"bins at 10 m             {bins[199]}")             # 1257
print(f"bins in far field        {bins[-1]} (constant)")   # 1257
print(f"cells inside 10 m        {sum(bins[:200]):,}")     # 125,037
print(f"total cells              {total:,}")               # 705,771
print(f"uniform 5 cm equivalent  {int((2*R_MAX/S_MIN)**2):,}")  # 16,000,000
print(f"reduction                {(2*R_MAX/S_MIN)**2/total:.2f}x")  # 22.67x
print(f"bytes @25 B/cell         {total*25/1e6:.2f} MB")   # 17.64 MB
```

Verified output:

| Quantity | Value |
|---|---:|
| Rings to 100 m | 662 (200 inner + 462 outer) |
| Angular bins at 10 m | 1257 |
| Angular bins, far field | 1257, constant — 0.286°/bin |
| Cells inside 10 m | 125,037 |
| Cells beyond 10 m | 580,734 |
| **Total cells** | **705,771** |
| Uniform 5 cm Cartesian, same footprint | 16,000,000 |
| **Cell reduction** | **22.67×** |
| Dense ring table @ 25 B/cell | 17.64 MB |
| Dense uniform 2.5D @ 25 B/cell | 400.0 MB |
| Dense uniform 3D voxel @ 5 cm, 1 B | 3.20 GB |

Isotropy check — radial vs tangential extent:

| r | radial | tangential |
|---:|---:|---:|
| 5 m | 5.0 cm | 5.0 cm |
| 10 m | 5.0 cm | 5.0 cm |
| 20 m | 10.0 cm | 10.0 cm |
| 30 m | 15.0 cm | 15.0 cm |
| 50 m | 25.0 cm | 25.0 cm |
| 70 m | 35.0 cm | 35.0 cm |
| 100 m | 50.0 cm | 50.0 cm |

---

## 4. Repository layout

```
sih2026/
├── avr25d/
│   ├── config.yaml                 # every tunable, with units and provenance (NFR-7)
│   ├── core/
│   │   ├── grid.py                 # ring table, closed-form indexing, projection
│   │   ├── cell.py                 # SoA cell arrays, analysis, hazard flags
│   │   ├── refine.py               # bounded local refinement overlay
│   │   └── stats.py                # per-frame counters, memory accounting
│   ├── perception/
│   │   ├── range_proj.py           # cloud → 64×2048×6 range image and back
│   │   ├── onnx_infer.py           # ONNX Runtime CPU session wrapper
│   │   ├── geometric_seg.py        # RANSAC + clustering fallback segmenter
│   │   ├── labelmap.py             # SemanticKITTI 19 → AVR-25D 5 class merge
│   │   └── cache.py                # precomputed per-scan label store
│   ├── decision/
│   │   ├── traversability.py       # per-cell traversability score
│   │   ├── tracker.py              # clustering + constant-velocity Kalman
│   │   ├── costmap.py              # polar → ego-front Cartesian resample
│   │   ├── planner.py              # A*, primary + alternative route
│   │   └── explain.py              # deterministic reason strings
│   ├── bench/
│   │   ├── baselines.py            # B0–B4 memory models
│   │   ├── memory.py               # cell counts, bytes, peak RSS
│   │   ├── latency.py              # per-stage timing, mean/median/p95/max
│   │   ├── distance_bins.py        # binned mIoU and object recall
│   │   ├── hazard.py               # hazard preservation vs synthetic truth
│   │   └── report.py               # results.json → Markdown tables
│   ├── io/
│   │   ├── kitti.py                # .bin / .label readers
│   │   └── replay.py               # frame-log record and playback
│   └── server/
│       ├── app.py                  # FastAPI + WebSocket, pipeline driver
│       ├── protocol.py             # FrameMessage encode/decode — FROZEN DAY 1
│       └── fixtures.py             # synthetic schema-valid frames
├── web/
│   ├── index.html
│   ├── main.js                     # app shell, WebSocket client, view routing
│   ├── scene.js                    # Three.js scene, instanced cell rendering
│   ├── views.js                    # 4 views, A/B wipe, ring overlay
│   ├── hud.js                      # metrics panel
│   ├── palette.js                  # class colours — single source of truth
│   └── vendor/three.module.js      # vendored, no CDN
├── matlab/
│   ├── lidar_raycast.m             # spherical ray-cast against primitives
│   ├── scenegen.m                  # scene assembly from a spec table
│   ├── export_kitti.m              # write .bin + .label
│   ├── run_all_scenes.m
│   └── scenes/*.csv                # scene specifications
├── tools/
│   ├── ring_table.py               # §3.6 derivation
│   └── fetch_kitti.sh
├── tests/
├── data/                           # gitignored
│   ├── kitti/  synthetic/  cache/
└── docs/
    ├── PRD.md  IMPLEMENTATION_PLAN.md  WORK_DISTRIBUTION.md  RUNBOOK.md
```

`data/` is gitignored. Nobody commits a point cloud.

---

## 5. The wire protocol — frozen Day 1

### 5.1 Why this comes first

Four developers work in parallel for two weeks. The only way that is not chaos is to agree the
interface between them on the first afternoon and then never touch it. `protocol.py` is
written and merged on Day 1 before any feature work. After Day 1, changing it needs the
integration lead's sign-off and a message to everyone.

### 5.2 FrameMessage

Binary, little-endian: a JSON header followed by concatenated typed-array payloads, so the
browser reads cell data straight into `Float32Array` / `Uint8Array` with no per-cell parsing.

```jsonc
{
  "frame_id":  1284,
  "t_sec":     128.4,
  "mode":      "cached",          // "live" | "cached" | "geometric"  (FR-6)

  "cells": {                      // n = occupied cell count; typed arrays follow the header
    "n":           48213,
    "cell_id":     "uint32[n]",   // flat id — offset[k] + j
    "ring":        "uint16[n]",
    "bin":         "uint16[n]",
    "z_ground":    "float32[n]",
    "z_obstacle":  "float32[n]",
    "roughness":   "float32[n]",
    "slope":       "float32[n]",
    "class_id":    "uint8[n]",
    "confidence":  "uint8[n]",
    "flags":       "uint8[n]"
  },

  "refined": {                    // FR-17 overlay; same fields, sub-cell geometry
    "n": 812, "parent_id": "uint32[n]", "quadrant": "uint8[n]",
    "z_ground": "float32[n]", "z_obstacle": "float32[n]",
    "class_id": "uint8[n]", "flags": "uint8[n]"
  },

  "tracks": [
    { "id": 7, "x": 12.4, "y": -3.1, "vx": 8.2, "vy": 0.1,
      "class_id": 4, "age": 14, "speed": 8.2, "predicted": [[20.6,-3.0],[28.8,-2.9]] }
  ],

  "decision": {
    "route":       [[0,0],[2.1,0.3]],
    "alternative": [[0,0],[1.8,-1.4]],
    "selected":    "alternative",
    "risk":        "LOW",              // LOW | MEDIUM | HIGH
    "eta_s":       384.0,
    "reason":      "Rerouted: track #7 (DYNAMIC_OBJECT, 8.2 m/s) predicted to intersect primary route at t+4.0 s. Alternative adds 0.3 km at LOW terrain risk."
  },

  "stats": {
    "fps": 31.8,
    "t_perception_ms": 0.4, "t_projection_ms": 5.1, "t_analysis_ms": 6.2,
    "t_refine_ms": 1.8, "t_decision_ms": 4.4, "t_serialise_ms": 2.9,
    "t_total_ms": 20.8,
    "n_points": 121344, "n_points_conserved": 121344,   // FR-10 — must be equal
    "n_cells_occupied": 48213, "n_cells_total": 705771,
    "mem_bytes": 17644275, "baseline_mem_bytes": 400000000, "reduction": 22.67
  }
}
```

### 5.3 `fixtures.py` — the anti-blocking device

Emits fully schema-valid `FrameMessage`s from procedurally generated content: a synthetic
ground plane, a few static obstacles, one moving track on a crossing trajectory, a plausible
route and plausible stats. Runs with `--fixtures` and **imports nothing from `core/`,
`perception/` or `decision/`**.

Consequence: on Day 1 evening, `web/` can render adaptive cells, colour them by class, draw
routes and tracks, animate a moving object and populate the HUD — with the backend not yet
written. On Day 12, integration is changing one flag. This is the difference between a project
that integrates continuously and one that discovers on Day 12 that nothing fits together.

---

## 6. Module specifications

Each module below lists its owner, its public interface, what it depends on, and its tests.
The interface is a contract: write the signature and a stub that returns correctly shaped
zeros **first**, push it, then fill in the body.

### 6.1 `core/grid.py` — ring table and projection · Sameer

```python
class RingGrid:
    def __init__(self, s_min=0.05, s_max=0.50, r_knee=10.0, r_max=100.0): ...
    # Built once at startup, reused every frame (FR-12).
    #   self.n_rings   : int                  = 662
    #   self.r_edge    : float32[663]         ring inner radii
    #   self.s         : float32[662]         radial cell size per ring
    #   self.n_bins    : int32[662]           sector count per ring
    #   self.offset    : int32[663]           prefix sum; offset[-1] = 705_771
    #   self.n_cells   : int                  = 705_771

    def ring_of(self, r: np.ndarray) -> np.ndarray:
        """Closed-form ring index, fully vectorised. FR-9.
        r <= r_knee : floor(r / s_min)
        r >  r_knee : n_inner + floor(log(r / r_knee) / log(1 + s_min / r_knee))
        Returns -1 for r > r_max."""

    def cell_of(self, x, y) -> tuple[np.ndarray, np.ndarray]:
        """(x, y) -> (cell_id, valid_mask). One vectorised pass, no Python loop. FR-9, FR-11."""

    def cell_centres(self, cell_id) -> np.ndarray:
        """Inverse map -> (x, y) centres. Used by the renderer and the costmap."""

    def cell_extents(self, cell_id) -> np.ndarray:
        """(radial, tangential) extent per cell, for correctly sized render instances."""
```

**Implementation notes.** `ring_of` must use `np.where` over the two branches rather than
boolean-mask indexing with two passes — one pass over the array, not two. `cell_of` computes
`theta = np.arctan2(y, x) % (2*np.pi)` then `j = (theta / (2*np.pi) * n_bins[k]).astype(np.int32)`,
and must clamp `j` to `n_bins[k] - 1` to catch the floating-point edge case where `theta`
rounds to exactly `2π` — that single clamp is the difference between passing and failing the
conservation test, and it is the one line most likely to be forgotten.

**Tests:** T-G1, T-G2, T-G3, T-G4, T-G6.

### 6.2 `core/cell.py` — accumulation and analysis · Sameer

```python
class CellGrid:
    def __init__(self, grid: RingGrid): ...   # allocates all SoA arrays once (FR-12)

    def reset(self) -> None:
        """Zero the arrays in place. No reallocation, ever."""

    def accumulate(self, xyz, intensity, labels) -> AccumStats:
        """Scatter points into cells and populate every §6.2 field in one vectorised pass.
        Uses np.add.at / np.minimum.at / np.maximum.at for the scatter-reduce.
        Returns AccumStats(n_points_in, n_points_assigned) — FR-10 asserts these are equal."""

    def analyse(self, cfg) -> None:
        """Derive slope from ring-neighbour z_ground gradients, roughness from the z
        second moment, then set OVERHANG / NEGATIVE_OBSTACLE / STEP / VOID_UNOBSERVED /
        LOW_CONFIDENCE flags. FR-13, FR-14, FR-15."""
```

**`z_ground` estimation.** Not the minimum z in the cell — a single spurious low return would
sink the whole cell and manufacture a pothole. Use the 10th percentile of returns whose point
label is `DRIVABLE` or `NON_DRIVABLE_TERRAIN`; where a cell has no terrain-labelled returns,
fall back to the 10th percentile of all returns and set `LOW_CONFIDENCE`. Percentile via
scatter-sort is expensive; use a running min-of-k approximation with k = 3, which is within a
centimetre on real data and stays vectorised.

**Ring-neighbour topology.** Ring `k` and ring `k+1` have different bin counts below 10 m, so
the neighbour of bin `j` in ring `k` is bin `round(j * n_bins[k+1] / n_bins[k])` in ring
`k+1`. Above 10 m the bin counts are equal and the neighbour is simply `j`, which is why
almost all of the map has trivial neighbour lookup. Precompute the inner-ring neighbour table
once at startup.

**Tests:** T-G5, T-H1, T-H2, T-H3.

### 6.3 `core/refine.py` — bounded local refinement · Sameer

```python
def refine(cells: CellGrid, grid: RingGrid, cfg) -> RefinedOverlay:
    """Select far-field cells (r > r_knee) that are MOVING, or whose roughness or slope
    exceeds threshold. Rank by priority, take the top N_refine_max (default 4096, FR-18),
    subdivide each 2x2, re-accumulate the parent's points into the sub-cells.
    Returns a dict-of-arrays overlay keyed by parent cell_id. FR-17."""
```

The overlay is separate from the dense table so the dense table's fixed footprint (FR-12) is
untouched. Requires `accumulate` to retain per-cell point index lists for candidate cells
only — not for all 705,771, which would be a large per-frame allocation.

**Tests:** T-R1, T-R2.

### 6.4 `perception/range_proj.py` · Anuj

```python
def to_range_image(xyz, intensity, h=64, w=2048, fov_up=3.0, fov_down=-25.0):
    """-> image float32[6,h,w] (range,x,y,z,intensity,mask), plus px/py index arrays."""

def from_range_image(pred_hw, px, py, xyz, k=5):
    """Reproject per-pixel labels to per-point labels with k-NN range-aware voting.
    Points occluded in the projection still get a label. FR-4."""
```

The fov constants match the HDL-64E used by KITTI. k-NN post-processing is the RangeNet++
approach and it is not optional — without it, points that shared a pixel take the label of
whichever point won the depth test, which visibly shreds object boundaries.

**Tests:** T-P2, T-P4.

### 6.5 `perception/geometric_seg.py` — build this first · Anuj

```python
def segment(xyz, intensity, cfg) -> np.ndarray:
    """Deep-learning-free fallback producing the same 5 classes (FR-5).
      1. RANSAC ground plane over r < 30 m; inliers -> DRIVABLE
      2. Points within 0.3 m of the fitted plane beyond 30 m -> NON_DRIVABLE_TERRAIN
      3. Non-ground -> Euclidean clustering (scipy cKDTree, 0.5 m radius)
      4. Per cluster: bbox aspect + height + point count ->
         STATIC_OBSTACLE or DYNAMIC_OBJECT
      5. Unassigned -> VOID"""
```

**Why this is Day 1 and not a contingency.** It takes about three hours and it removes the
single biggest schedule risk in the project (R-2): from the end of Day 1, the grid engine,
the decision layer, the dashboard and the benchmark harness all have labelled input, whether
or not an ONNX checkpoint ever materialises. It also stays useful afterwards as the ablation
that shows what the network buys.

**Tests:** T-P5.

### 6.6 `perception/onnx_infer.py` · Anuj

```python
class OnnxSegmenter:
    def __init__(self, model_path, providers=("CPUExecutionProvider",)): ...
    def __call__(self, range_image) -> np.ndarray: ...   # -> int64[h,w] class ids
    @property
    def last_latency_ms(self) -> float: ...              # measured, reported honestly
```

Model: SalsaNext/CENet-family range-image network with pretrained SemanticKITTI weights,
exported to ONNX, dynamically quantised to int8 (`onnxruntime.quantization`) for CPU. Output
is 19-class; `labelmap.py` merges to 5 (PRD §6.1). Fine-tuning directly on the 5-class
taxonomy is Phase 2 — for Phase 1, merging a pretrained output is both faster and adequate.

**Tests:** T-P1, T-P3.

### 6.7 `perception/cache.py` · Anuj

```python
def build_cache(scan_paths, segmenter, out_dir) -> None:
    """Run the segmenter once over the whole subset, write uint8 labels per scan."""

class LabelCache:
    def __init__(self, cache_dir): ...     # memory-maps; no per-frame disk read
    def __getitem__(self, frame_id) -> np.ndarray: ...
```

Storage is `n_points × 1` byte per scan — about 120 KB, so 1000 scans is 120 MB. Built
overnight Day 6→7 while everyone sleeps, which is the only free compute the team has.

### 6.8 `decision/traversability.py` · Anuj

```python
def score(cells: CellGrid, cfg) -> np.ndarray:
    """Per-cell traversability in [0,1] (FR-19). Published weights in config.yaml:
         slope_penalty      w=0.30   normalised by max_slope_deg   (default 15°)
         roughness_penalty  w=0.20   normalised by max_roughness   (default 0.05 m²)
         step_penalty       w=0.20   STEP flag or |dz| > step_max  (default 0.12 m)
         class_penalty      w=0.20   DRIVABLE 0.0 / TERRAIN 0.5 / obstacle 1.0
         clearance_penalty  w=0.10   OVERHANG with clearance < H_vehicle -> 1.0
       score = clip(1 - Σ wᵢ·pᵢ, 0, 1); LOW_CONFIDENCE cells scale toward 0.5."""
```

Weights sum to 1.0 and live in config with a one-line justification each (NFR-7). Expect
"why 0.30?" from a judge; the answer must be in the file.

**Tests:** T-D1.

### 6.9 `decision/tracker.py` · Anuj

```python
class Tracker:
    def update(self, cells, grid, dt) -> list[Track]:
        """Cluster DYNAMIC_OBJECT cells (connected components in ring-bin space),
        associate to existing tracks by nearest neighbour with a gate of
        v_max·dt + 1.0 m, update a constant-velocity Kalman filter
        x = [x, y, vx, vy], F = [[1,0,dt,0],[0,1,0,dt],[0,0,1,0],[0,0,0,1]].
        Birth after 2 consecutive associations, death after 3 misses. FR-20."""
```

Connected components run in ring-bin index space rather than metric space — cheaper, and the
adjacency is already known from the neighbour table in §6.2.

**Tests:** T-D2.

### 6.10 `decision/costmap.py`, `planner.py`, `explain.py` · Sameer

```python
def build_costmap(cells, trav, tracks, grid, cfg) -> Costmap:
    """Resample the polar map to a 40 m x 40 m ego-front Cartesian grid at 0.25 m
    (160 x 160 = 25,600 cells). Each Cartesian cell samples the polar cell containing
    its centre — nearest-neighbour, no interpolation, because interpolating a
    traversability score across a curb edge invents a ramp that is not there. FR-21.
    Inflate obstacles by the vehicle half-width. Add predicted track occupancy at
    t + horizon (default 4 s) as a soft cost."""

def plan(costmap, goal, cfg) -> tuple[Route, Route]:
    """A* with octile heuristic. Cost per step:
         C = w1·dist + w2·slope + w3·roughness + w4·obstacle_risk + w5·clearance_risk
       Primary = min cost. Alternative = re-plan with the primary corridor penalised,
       giving a genuinely distinct route rather than a one-cell perturbation. FR-22."""

def explain(decision_ctx) -> str:
    """Deterministic template fill. No LLM (NG-5). Templates keyed by the dominant
    deciding factor, e.g.
      DYNAMIC_BLOCK  -> "Rerouted: track #{id} ({cls}, {v:.1f} m/s) predicted to intersect
                         primary route at t+{t:.1f} s. Alternative adds {d:.1f} km at
                         {risk} terrain risk."
      CLEARANCE      -> "Primary route blocked: overhead clearance {c:.2f} m below vehicle
                         height {h:.2f} m at {r:.0f} m ahead."
      NEGATIVE_OBS   -> "Primary route blocked: negative obstacle depth {d:.2f} m at
                         {r:.0f} m ahead."
      TERRAIN        -> "Primary route selected: mean traversability {t:.2f}, max slope
                         {s:.1f}°, no dynamic conflicts within {h:.0f} s."
    FR-23, FR-24."""
```

**Tests:** T-D3, T-D4, T-D5, T-D6.

### 6.11 `bench/` · Anuj

`baselines.py` implements B0–B4 from PRD §10.1 as pure functions of `(n_points, n_occ, ...)`,
so the memory comparison is auditable arithmetic rather than an opaque measurement.
`memory.py` adds real peak-RSS via `psutil`. `latency.py` collects per-stage timings and
reports mean/median/p95/max. `distance_bins.py` computes binned mIoU and object recall.
`hazard.py` scores synthetic scenes against exact ground truth. `report.py` renders
`results.json` into the Markdown tables of PRD §11.

```bash
make bench      # -> results.json + docs/RESULTS.md, one command, fully reproducible (NFR-5)
```

**Tests:** T-B1 … T-B5.

### 6.12 `server/app.py` · Sameer

```python
# python -m avr25d.server.app [--fixtures] [--infer live|cached|geometric]
#                             [--seq 04] [--replay LOG] [--record LOG]
```

Pipeline driver, WebSocket broadcaster, static file server for `web/`. Runs the pipeline in a
worker thread and pushes `FrameMessage`s on a fixed cadence, dropping frames rather than
queueing them if a consumer falls behind — a demo must degrade in frame rate, never in
latency.

### 6.13 `web/` · Shubham (scene) and Navya (HUD, transport)

**`scene.js` (Shubham).** Three.js scene, camera, lighting. Cells render as a single
`InstancedMesh` of unit boxes, per-instance matrix from `cell_centres` + `cell_extents` +
`z_ground`/`z_obstacle`, per-instance colour from `palette.js`. One draw call for ~50,000
cells. Frustum culling on; distance LOD drops cells beyond a radius when the instance count
exceeds budget. Fallback if instancing underperforms (R-4): render cell centroids as a
`Points` cloud with per-point size — visually near-identical at demo zoom and much cheaper.

**`views.js` (Shubham).** Four views (FR-25), ring-boundary overlay (FR-27), A/B wipe between
uniform and adaptive over the same frame (FR-29). The wipe is the single most persuasive
thing on the screen: same scan, same camera, a draggable divider, cell counts live on both
sides. Build it early.

**`hud.js` (Navya).** Metrics panel (FR-28): FPS, per-stage latency bars, total latency,
occupied cells, memory both sides, reduction factor, active perception mode, frame index.
Numbers come from `stats` and are never computed in the browser — one source of truth.

**`main.js` (Navya).** App shell, WebSocket client, binary frame decode into typed arrays,
view routing, keyboard shortcuts, route and track overlays, decision panel showing the
`reason` string.

**`palette.js`.** Class colours from PRD §6.1, in one file. Both developers import it; nobody
hard-codes a hex value anywhere else.

### 6.14 `matlab/` · Khanak

```matlab
% lidar_raycast.m — base-language MATLAB only. Runs unmodified in GNU Octave.
function [pts, labels] = lidar_raycast(scene, sensor)
%   64 beams x 1800 azimuths. For each ray, intersect against every primitive
%   (plane / axis-aligned box / cylinder), keep the nearest hit, emit the point and
%   the primitive's class label. Adds Gaussian range noise, sigma = 0.02 m, and drops
%   returns beyond r_max, so the synthetic clouds have realistic density falloff.

% scenegen.m     — assemble a scene struct from scenes/*.csv
% export_kitti.m — write float32 [x y z intensity] .bin + uint32 .label
% run_all_scenes.m — regenerate every scene into data/synthetic/
```

**No toolbox functions.** Not `pcread`, not `lidarScenario`, nothing from Automated Driving or
Lidar Toolbox. Base language only, which is what makes the files run in free Octave and takes
licensing off the critical path (risk R-8).

A scene CSV is one primitive per row, which is the deliberate design: authoring a new hazard
scene means editing a spreadsheet, not writing code.

```csv
type,   x,     y,     z,     sx,   sy,   sz,   class, note
plane,  0,     0,     0,     200,  200,  0,    1,     road surface
box,    12.0, -0.5,  -0.22,  1.4,  1.0,  0.22, 0,     pothole (negative)
box,    25.0,  0.0,   3.10,  6.0,  0.4,  0.5,  3,     gantry beam, 3.10 m clearance
cyl,    25.0, -3.0,   1.55,  0.3,  0.3,  3.10, 3,     gantry support post
```

**Tests:** T-H4.

---

## 7. Configuration

`avr25d/config.yaml` — every tunable, with units and a stated reason (NFR-7).

```yaml
grid:
  s_min: 0.05        # m   — PS-6: "5cm cells within a 10m radius"
  s_max: 0.50        # m   — PS-6: "50cm cells up to a 100m radius"
  r_knee: 10.0       # m   — PS-6
  r_max: 100.0       # m   — PS-6

vehicle:
  height: 3.50       # m   — medium logistics truck; drives OVERHANG (PRD A-2)
  width: 2.50        # m   — drives costmap obstacle inflation
  max_slope_deg: 15.0
  max_step: 0.12     # m   — typical kerb-climb limit for a wheeled logistics vehicle

hazards:
  tau_pothole: 0.10  # m   — depth below ring-neighbourhood median -> NEGATIVE_OBSTACLE
  tau_step: 0.08     # m   — z_ground jump to a 4-neighbour -> STEP
  tau_conf: 96       # 0-255 — below this -> LOW_CONFIDENCE

refine:
  enabled: true
  max_cells: 4096    # FR-18 — bounds worst-case latency and memory
  roughness_thresh: 0.03   # m²
  slope_thresh_deg: 10.0

decision:
  weights: {distance: 0.35, slope: 0.20, roughness: 0.15, obstacle: 0.20, clearance: 0.10}
  horizon_s: 4.0
  costmap: {extent_m: 40.0, res_m: 0.25}

perception:
  mode: cached       # live | cached | geometric
  model: models/salsanext_int8.onnx
  knn_k: 5

runtime:
  use_numba: false   # NFR-3 — NumPy path is always correct; Numba is opt-in
  target_fps: 30
```

---

## 8. Phase 1 schedule — Fri 28 Aug → Thu 10 Sep 2026

Fourteen calendar days to the internal hackathon submission. Each day has a **falsifiable exit
criterion**: something that either runs or does not. "Made progress on X" is not an exit
criterion.

Standup daily at **10:00**, 15 minutes, three questions: what landed, what is blocked, what
lands today. Integration checkpoint daily at **21:00** — `main` must be green.

**On the extended deadline.** This schedule originally ran to 3 September. The internal
deadline moved to 10 September, and the extra week is deliberately *not* spent working more
slowly. Days 1–8 carry the same task set at a sustainable pace instead of a punishing one, and
Days 9–11 pull forward four items that the six-day schedule had pushed into Phase 2 — bounded
*and* uncertainty-driven refinement, a perception improvement pass, multi-sequence evaluation,
and the full set of five synthetic scenes. The de-risking order is unchanged and still
matters: protocol frozen first, geometric segmenter before any model work, KITTI download on
the first morning. More time removes the excuse for skipping those, not the reason for them.

Days 2–3 and 9–10 fall on weekends and are scheduled as full working days. If that is not true
for your team, say so at the Day 1 standup — the plan can absorb it now, not on Day 9.

| Block | Days | Dates | Theme |
|---|---|---|---|
| **A** | 1–3 | Fri 28 – Sun 30 Aug | Foundations and de-risking |
| **B** | 4–6 | Mon 31 Aug – Wed 2 Sep | Perception and the memory evidence |
| **C** | 7–8 | Thu 3 – Fri 4 Sep | Decision layer |
| **D** | 9–11 | Sat 5 – Mon 7 Sep | Depth — pulled-forward work · **freeze Day 11** |
| **E** | 12–14 | Tue 8 – Thu 10 Sep | Evidence, rehearsal, submit |

---

### Block A — Foundations and de-risking

#### Day 1 — Fri 28 Aug · Unblock everyone

| Owner | Task |
|---|---|
| **Anuj** | **First action of the sprint:** start the SemanticKITTI subset download (seq 04, then 00, then 05). It is bandwidth-bound, so it runs unattended all day. Then begin `geometric_seg.py` (§6.5). |
| **Sameer** | Repo scaffold, `requirements.txt`, `config.yaml`, `tools/ring_table.py`. Write and **freeze `protocol.py`** (§5.2), then `fixtures.py` (§5.3) and push both by 14:00 — the frontend pair is blocked until this lands, so it is the highest-priority item on the board. Then start `core/grid.py`. |
| **Shubham** | Three.js scene skeleton, vendored `three.module.js`, orbit camera, ground reference, `palette.js`. From 14:00, render fixture cells as an `InstancedMesh`. |
| **Navya** | `index.html` shell, WebSocket client, binary frame decode, HUD panel laid out with live fixture numbers. |
| **Khanak** | Install MATLAB Online or Octave. Receive the `lidar_raycast.m` seed from Sameer, get it running, produce `S1_flat_road`. |
| **Veda** | Confirm deck template and submission mechanics (Q-2, Q-3). Deck outline. Start prior-art search. |

**Exit criteria.** `pytest -q` green on both a Mac and the Windows box. `--fixtures` serves a
dashboard rendering ~50,000 synthetic cells. KITTI seq 04 downloading. Nobody is blocked.

#### Day 2 — Sat 29 Aug · The grid exists

| Owner | Task |
|---|---|
| **Sameer** | Finish `core/grid.py`: ring table, `ring_of`, `cell_of`, `cell_centres`, `cell_extents`. Tests T-G1, T-G2, T-G3, T-G4. |
| **Anuj** | Finish `geometric_seg.py`. `io/kitti.py` readers. |
| **Shubham** | Class-coloured instanced cells, correct per-instance sizing from `cell_extents`, elevation-shading toggle. |
| **Navya** | HUD skeleton complete against fixtures. View switching, frame stepping, pause. |
| **Khanak** | `S2_pothole`. Verify the depression is visible in the point cloud, not just in the CSV. |
| **Veda** | Prior-art and novelty write-up. Draft slides 1–2. |

**Exit criterion.** `RingGrid` reports exactly **662 rings and 705,771 cells**, and the
conservation test T-G4 passes including its adversarial inputs.

#### Day 3 — Sun 30 Aug · First real scan end-to-end

| Owner | Task |
|---|---|
| **Sameer** | `core/cell.py`: SoA arrays, `accumulate` with `np.add.at` scatter-reduce, `z_ground` estimator, ring-neighbour table. Wire `server/app.py` to drive the real pipeline. |
| **Anuj** | `labelmap.py` (19→5 merge including the `moving-*` IDs). First labelled KITTI scan into the grid. |
| **Shubham** | View 1 (raw cloud) and View 3 (adaptive grid) on real streamed frames. |
| **Navya** | HUD wired to real `stats` rather than fixtures. |
| **Khanak** | `S3_overhang` with 3.10 m clearance. |
| **Veda** | Slides 3–4. Begin the judge Q&A bank. |

**Exit criterion.** A real KITTI scan, geometrically segmented, projected into the adaptive
grid, rendered class-coloured in the browser, with `n_points_conserved == n_points` on the HUD.

---

### Block B — Perception and the memory evidence

#### Day 4 — Mon 31 Aug · Hazards

| Owner | Task |
|---|---|
| **Sameer** | `cell.analyse()`: slope, roughness, OVERHANG, NEGATIVE_OBSTACLE, STEP, VOID_UNOBSERVED, LOW_CONFIDENCE. |
| **Anuj** | Acquire an ONNX SemanticKITTI checkpoint (Q-4). Export and int8-quantise. Begin `range_proj.py`. |
| **Shubham** | View 2 — the uniform 5 cm grid, needed for the comparison. |
| **Navya** | Memory comparison panel, reduction factor, per-stage latency bars. |
| **Khanak** | `S4_curb` at 0.15 m. |
| **Veda** | Slide 5. Full deck draft with `_measured_` placeholders intact. |

**Exit criterion.** Overhang and pothole flags fire correctly on `S3` and `S2`; `S1_flat_road`
produces **zero** hazard flags.

#### Day 5 — Tue 1 Sep · The money shot

| Owner | Task |
|---|---|
| **Shubham** | **The A/B wipe** (FR-29) and the ring overlay (FR-27). Highest-value visual in the submission — build it today, not in the final week. |
| **Sameer** | `bench/baselines.py`, `bench/memory.py`. |
| **Anuj** | `onnx_infer.py` and k-NN reprojection in `range_proj.py`. |
| **Navya** | Perception-mode badge (FR-6). Track list panel scaffold. |
| **Khanak** | Begin `S5_crossing_truck` (40 frames). |
| **Veda** | Video script, timed to 3:00, beats matched to the run-book. |

**Exit criterion.** The draggable divider shows uniform vs adaptive on the *same* scan with
live cell counts on both sides, reading **16,000,000 vs 705,771**.

#### Day 6 — Wed 2 Sep · Perception lands

| Owner | Task |
|---|---|
| **Anuj** | ONNX inference producing sane labels on real scans with measured CPU latency. **Kick off the label-cache build overnight.** |
| **Sameer** | `bench/latency.py`. Per-stage timing wired through the pipeline into `stats`. |
| **Shubham** | Wipe polish; performance pass on instance count. |
| **Navya** | Full HUD per FR-28 — every field populated from real frames. |
| **Khanak** | Finish `S5_crossing_truck`. |
| **Veda** | Q&A bank to 12 questions. Rehearse narration against the draft deck. |

**Exit criterion.** Network labels visibly better than geometric labels on the same scan, with
both modes selectable and the active mode shown on the HUD.

---

### Block C — Decision layer

Both `core/` and `perception/` have landed. Sameer and Anuj now converge on `decision/` — the
one module deliberately not pre-assigned to a single person.

#### Day 7 — Thu 3 Sep · Traversability and tracking

| Owner | Task |
|---|---|
| **Anuj** | `decision/traversability.py` and `decision/tracker.py`. Verify the overnight label cache. |
| **Sameer** | `decision/costmap.py` — polar → 160 × 160 ego-front Cartesian resample. |
| **Shubham** | View 4 scaffold: track markers and predicted trajectories. |
| **Navya** | Decision panel scaffold: route, risk, ETA, reason string. |
| **Khanak** | Regenerate S1–S5 with final parameters. Begin `GROUND_TRUTH.md`. |
| **Veda** | Deck to near-final. Q&A bank to 20 questions. |

**Exit criterion.** On `S5`, the tracker holds one stable ID across all 40 frames and estimates
speed within 0.5 m/s of the true 8.0 m/s.

#### Day 8 — Fri 4 Sep · Planning and explanation

| Owner | Task |
|---|---|
| **Sameer** | `decision/planner.py` (A*, primary + genuinely distinct alternative) and `decision/explain.py`. |
| **Anuj** | `bench/distance_bins.py` and `bench/hazard.py`. |
| **Shubham** | View 4 complete: routes, risk shading, legible from three metres. |
| **Navya** | Decision panel complete and readable at projector resolution. |
| **Khanak** | Deliver `GROUND_TRUTH.md` to Anuj. |
| **Veda** | Assemble the demo run-book with Sameer. |

**Exit criterion.** On `S5`, a tracked crossing truck triggers a reroute and the dashboard
shows the alternative route with a reason string naming the track, its speed and the predicted
intersection time.

---

### Block D — Depth · work the six-day schedule could not afford

#### Day 9 — Sat 5 Sep · Refinement, both kinds

| Owner | Task |
|---|---|
| **Sameer** | `core/refine.py` — bounded local refinement (FR-17, FR-18), **plus uncertainty-driven refinement** *[pulled forward]*: refine on low `confidence`, not only on motion and roughness. This completes the `R = f(distance, complexity, semantics, uncertainty)` claim that slide 2 makes. |
| **Anuj** | Perception improvement prep: assemble the 5-class fine-tuning split; resolve Q-1 definitively (is the Windows GPU usable?). |
| **Shubham** | LOD tuning; verify ≥30 FPS at 100k instances (FR-30). |
| **Navya** | Refinement visualisation — sub-cells visibly distinct from parents. |
| **Khanak** | Adversarial scene: pothole partially occluded by a parked vehicle. |
| **Veda** | Record a rough-cut video against the current build to find problems while they are still fixable. |

**Exit criterion.** A distant moving vehicle is visibly resolved at finer resolution than the
empty road beside it, and T-R2 confirms the refinement stays within `max_cells` on an
adversarial scene.

#### Day 10 — Sun 6 Sep · Perception improvement *[pulled forward, conditional]*

| Owner | Task |
|---|---|
| **Anuj** | **If Q-1 says the GPU is usable:** fine-tune the network directly on the 5-class taxonomy rather than remapping a 19-class output. **If not:** decoder-head-only fine-tune on CPU over a small subset — a few hundred iterations is affordable and still a real gain — plus temperature calibration of the confidence output, which feeds Day 9's uncertainty-driven refinement. Either way, run it overnight. |
| **Sameer** | `--replay` and `--record`. Record the demo sequence log early so the fallback exists well before it is needed. |
| **Shubham + Navya** | Visual polish. Verify on the actual demo machine at projector resolution. |
| **Khanak** | Second adversarial scene: low-clearance tunnel with a curb inside it. |
| **Veda** | Fix everything the rough-cut video exposed. |

**Exit criterion.** A measured before/after mIoU comparison exists, whichever branch was taken.
If neither improved anything, that is a finding — record it and move on. Do not spend Day 11
chasing it.

#### Day 11 — Mon 7 Sep · Expanded evaluation · **FEATURE FREEZE 21:00**

| Owner | Task |
|---|---|
| **Anuj** | `bench/report.py`. **First full `make bench`.** Multi-sequence evaluation *[pulled forward]* — report per-sequence variance rather than a single number, which is a materially stronger accuracy claim than one sequence. |
| **Sameer** | Final integration. Fix whatever the full bench run exposes. Then: nothing new. |
| **Shubham + Navya** | Final polish. Keyboard shortcuts for the entire demo sequence verified. |
| **Khanak** | Cross-check `GROUND_TRUTH.md` against the hazard benchmark output. |
| **Veda** | Deck final except for `_measured_` placeholders. |

**Exit criterion at 21:00.** The full pipeline runs end-to-end on KITTI and on all synthetic
scenes. `make bench` produces a complete `results.json`. **After this point, no new features.
Bugs, numbers, polish and rehearsal only.**

---

### Block E — Evidence, rehearsal, submit

#### Day 12 — Tue 8 Sep · Authoritative numbers

| Owner | Task |
|---|---|
| **Anuj** | Final benchmark runs: ≥200 scans for latency, full subset for accuracy, all scenes for hazards. Produce the authoritative `results.json` and hand it to Veda. No changes after handover. |
| **Sameer** | Bug fixes only. Re-record the demo replay log against the frozen build. |
| **Shubham + Navya** | Bug fixes only. |
| **Khanak** | Cross-check every number destined for the deck against `results.json`. |
| **Veda** | **Fill every `_measured_` placeholder from `results.json` only.** |

**Exit criterion.** Zero `_measured_` placeholders remain anywhere, and every filled number
traces to a line in `results.json`.

#### Day 13 — Wed 9 Sep · Video and rehearsal

| Owner | Task |
|---|---|
| **Veda** | Record and edit the final 3-minute video. Finalise the deck. |
| **Sameer** | Run the demo. Nothing else. |
| **All** | Three full timed demo rehearsals, including the two failure paths (replay fallback, LOD drop). |

**Exit criteria.** Video rendered and stored **locally** on the presenting laptop. Deck final.
Three clean rehearsals. Replay-log fallback verified on the demo machine.

#### Day 14 — Thu 10 Sep · Submit

Morning buffer for whatever broke overnight. Final rehearsal. **Submit.** Live demo.

Nothing is scheduled into this day on purpose. A fourteen-day plan with no slack is a
thirteen-day plan that fails.

---

## 9. Test plan

Test IDs are referenced from `PRD.md` §7. `pytest -q` runs the lot.

### Grid

| ID | Test |
|---|---|
| **T-G1** | Ring table matches §3.6 exactly: 662 rings, 705,771 cells, `s(r)` = 5 cm at r ≤ 10 and 50 cm at r = 100. |
| **T-G2** | Isotropy: for every ring, `|radial − tangential| / radial < 0.02`. |
| **T-G3** | `ring_of` is the exact inverse of `r_edge` for 10⁶ random radii; and `cell_of` agrees with a brute-force reference implementation on 10⁵ random points. |
| **T-G4** | **Conservation (FR-10):** for 10⁶ uniformly random points in the envelope, `Σ count == n_points`. Repeated with adversarial inputs: `θ` exactly 0 and 2π⁻ (the `arctan2` wrap), `r` exactly at each of the 662 ring boundaries, `r` exactly 10.0 and 100.0, and points at the origin. This is the test that proves PS-4, so it gets the hostile inputs. |
| **T-G5** | `accumulate` on a synthetic cloud with known per-cell content produces the expected `z_ground`, `z_obstacle`, `count`, `class_id`. |
| **T-G6** | Memory is stable: 1000 consecutive frames show no growth in `tracemalloc` peak (FR-12). |

### Perception

| ID | Test |
|---|---|
| **T-P1** | Segmenter returns one label per input point, all in [0,4]. |
| **T-P2** | Range projection then reprojection recovers ≥99% of points with an index round-trip. |
| **T-P3** | ONNX session builds and infers with `CPUExecutionProvider` only; asserted on both platforms in CI. |
| **T-P4** | k-NN reprojection labels 100% of points, including those occluded in the range image. |
| **T-P5** | Geometric segmenter on `S1_flat_road` classifies ≥95% of ground points as `DRIVABLE`. |
| **T-P6** | `live`, `cached` and `geometric` modes all produce a valid `FrameMessage`; `mode` in the message matches the flag passed. |

### Hazards

| ID | Test |
|---|---|
| **T-H1** | `S3_overhang`: cells beneath the gantry keep `class_id == DRIVABLE`, carry `OVERHANG`, and report clearance within 0.05 m of 3.10 m. The "ground stays drivable" half matters as much as the detection half — flagging the whole column as blocked would be the 2D failure we are claiming to fix. |
| **T-H2** | `S2_pothole`: `NEGATIVE_OBSTACLE` fires on ≥80% of pothole-covering cells; depth within 0.05 m of 0.22 m. |
| **T-H3** | `S4_curb`: `STEP` fires along the kerb; height within 0.03 m of 0.15 m. |
| **T-H4** | `S1_flat_road`: zero hazard flags. The false-positive test, and the one most likely to fail first when a threshold is tuned too aggressively. |

### Refinement

| ID | Test |
|---|---|
| **T-R1** | A far-field `MOVING` cell is subdivided; sub-cell point counts sum to the parent's. Conservation holds through refinement. |
| **T-R2** | An adversarial scene where every far-field cell qualifies still refines at most `max_cells` and stays within the latency budget (FR-18). |

### Decision

| ID | Test |
|---|---|
| **T-D1** | Traversability is 1.0 on flat labelled road and 0.0 on a wall; monotonically decreasing in slope. |
| **T-D2** | On `S5_crossing_truck`, the tracker holds a single stable ID across 40 frames and estimates speed within 0.5 m/s of the true 8.0 m/s. |
| **T-D3** | Costmap resample preserves obstacle positions within one 0.25 m cell. |
| **T-D4** | A* finds the known-optimal path on a hand-built costmap; the alternative route is genuinely distinct (Fréchet distance from primary above threshold), not a one-cell perturbation. |
| **T-D5** | Reason strings are non-empty, name the deciding factor, and contain no unformatted placeholders. |
| **T-D6** | **Determinism (FR-24):** the same recorded sequence run twice produces byte-identical decision records. |

### Visualisation

| ID | Test |
|---|---|
| **T-V1** | All four views render without console errors. |
| **T-V2** | Rendered instance colours match `palette.js` for each class. |
| **T-V3** | Ring overlay draws 662 boundaries in the right places. |
| **T-V4** | Every HUD field is populated from `stats` and none is `NaN` or `undefined`. |
| **T-V5** | The A/B wipe shows both representations of the same `frame_id`. |
| **T-V6** | 100,000 instances sustain ≥30 FPS on the demo machine (FR-30). |

### Benchmarks

| ID | Test |
|---|---|
| **T-B1** | Baseline memory models B0–B4 return the documented closed-form values for known inputs. |
| **T-B2** | Latency harness reports mean, median, p95 and max over ≥200 scans. |
| **T-B3** | Distance binning assigns every point to exactly one bin; bins sum to the total. |
| **T-B4** | Object recall matches a hand-computed value on a small fixture. |
| **T-B5** | `make bench` regenerates `results.json` and `docs/RESULTS.md` reproducibly; two runs on the same input give identical accuracy numbers. |

---

## 10. Demo run-book

Full version in `docs/RUNBOOK.md`. The 90-second sequence:

| Time | Beat | Key |
|---|---|---|
| 0–10 s | Raw KITTI point cloud. "120,000 points, 10 times a second. This is the bottleneck." | `1` |
| 10–22 s | Switch to adaptive grid, ring overlay on. Rings visibly coarsen with range. "5 cm here, 50 cm at 100 metres. 662 rings, one closed-form index, no seams." | `3`, `R` |
| 22–34 s | A/B wipe against the uniform 5 cm grid. Cell counts live on both sides. "Same scan. 16 million cells against 705,771. **22.67×**." | `W` |
| 34–48 s | Synthetic overhang scene. Ground stays green and drivable; the gantry is flagged with its measured clearance. "A 2D occupancy grid cannot express this. That is the whole argument for 2.5D." | `S3` |
| 48–58 s | Pothole scene. Negative obstacle flagged with measured depth. | `S2` |
| 58–70 s | Crossing truck. Track appears, velocity estimated, predicted trajectory drawn across the route. | `S5` |
| 70–82 s | Reroute fires. Alternative route drawn. Reason string on screen, naming the track and the predicted intersection time. | — |
| 82–90 s | HUD full screen: FPS, per-stage latency, memory both sides, reduction factor, conservation at 100%. | `H` |

**Failure paths, rehearsed:**

- Backend crashes → `--replay demo.log` and continue. The replay log is first recorded on
  Day 10 and re-recorded against the frozen build on Day 12.
- Rendering stutters → press `L` to drop to point-sprite LOD.
- Everything fails → play the recorded video. It is on the presenting laptop, not in the cloud.

**Pre-demo checklist:** laptop on mains power, display sleep off, notifications off, browser
zoom at 100%, `data/` populated, one full silent run-through completed, video file present
locally, replay log present locally.

---

## 11. Working agreements

- **Branching:** short-lived branches off `main`, merged same day. Nobody holds a branch
  overnight — a two-week project cannot afford a two-day merge.
- **`main` is always green.** `pytest -q` passes before every push. A red `main` blocks five
  people, so fixing it takes priority over whatever you were doing.
- **Interfaces first.** Push the signature and a correctly shaped stub before the body. Your
  consumers start immediately.
- **The protocol is frozen** after Day 1 (§5.1). Changes need the integration lead and a
  message to everyone.
- **No number without a measurement.** `_measured_` placeholders stay until `results.json`
  fills them. This applies to the deck, the video narration and anything said out loud to a
  judge.
- **Say you are blocked at standup**, not at midnight. Every module has a named backup owner
  in `WORK_DISTRIBUTION.md` §7.
- **Feature freeze is 21:00 on Day 11 (Mon 7 Sep)** and it is not negotiable.

---

## 12. Phase 2 — Fri 11 Sep → Sun 20 Sep 2026

Ten days for the SIH portal submission. Shorter than the original Phase 2 because four of its
items were pulled forward into Days 9–11 (§8, Block D). What remains is sequenced by
evaluation value.

| Days | Work | Owner |
|---|---|---|
| 11–13 Sep | Temporal accumulation across scans with ego-motion compensation from KITTI poses. Improves `z_ground` in sparse far-field cells and stabilises tracks. The largest remaining technical gain. | Sameer + Anuj |
| 11–13 Sep | Complete the perception fine-tune if Day 10 took the CPU-only branch, or if GPU access arrives late. | Anuj |
| 14–16 Sep | Dashboard: timeline scrubber, side-by-side scene comparison, exportable evidence screenshots for the deck and report. | Shubham + Navya |
| 14–16 Sep | Further adversarial scenes: multiple simultaneous hazards, sparse-return conditions, a negative obstacle on a slope. | Khanak |
| 14–17 Sep | Ablation studies: with and without refinement; network versus geometric segmenter; and the downstream planning cost on a uniform grid versus the adaptive one — which converts the 22.67× cell reduction into a measured compute saving rather than a memory claim. | Sameer + Anuj |
| 17–18 Sep | Full technical report, architecture diagrams, results write-up. | Veda + all |
| 19 Sep | Buffer, final rehearsal, numbers re-verified. | All |
| 20 Sep | **Submit to the SIH portal.** | Veda |

Contingent on hardware: if a CUDA GPU becomes available (Q-1), measure live inference latency
on it and replace the projected figure with a measured one. Until then it stays labelled
projected.

---

## 13. Definition of done — Phase 1

A checklist, not a feeling. Every line must be true on the evening of Wed 9 Sep.

- [ ] `pytest -q` green on macOS and Windows
- [ ] `make bench` regenerates `results.json` and `docs/RESULTS.md` from scratch
- [ ] Every `_measured_` placeholder in `PRD.md` §11 is filled from `results.json`
- [ ] Conservation (T-G4) passes at 100.000%, including the adversarial inputs
- [ ] Dashboard renders all four views, the ring overlay and the A/B wipe
- [ ] Hazard tests T-H1 through T-H4 pass against synthetic ground truth
- [ ] Determinism test T-D6 passes
- [ ] Live demo completes end to end, three times, unassisted
- [ ] Replay-log fallback verified on the demo machine
- [ ] 3-minute video rendered and stored locally on the presenting laptop
- [ ] Deck final; every number traced to `results.json`; no unmeasured claim anywhere
- [ ] `README.md` lets a stranger clone and run it in under ten minutes
- [ ] Every PS clause in `PRD.md` §15 maps to a passing test
