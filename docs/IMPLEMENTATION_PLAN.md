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

Pinned. Do not upgrade during the sprint. The authoritative copy is
[`backend/requirements.txt`](../backend/requirements.txt); this table is a summary.

```
python        == 3.14          # revised Day 7 — see below
numpy         == 2.5.2
scipy         == 1.18.1        # cKDTree for k-NN label reprojection, RANSAC helpers
onnx          == 1.22.0
onnxruntime   == 1.29.0        # CPU execution provider only
fastapi       == 0.141.1
uvicorn       == 0.52.4
websockets    == 17.1
pymongo       == 4.17.0        # official driver, no ODM
pyyaml        == 6.0.3
pytest        == 9.1.1
psutil        == 7.2.2         # RSS measurement for the memory benchmark
certifi       == 2026.7.22     # tools/fetch_kitti.py needs a CA bundle that exists
torch         == 2.13.0        # tools/export_onnx.py ONLY — install on demand
numba                          # OPTIONAL, behind a flag (NFR-3); not currently used
```

**Revised from `python >= 3.10, < 3.13` / `numpy == 1.26.4` / `scipy == 1.13.1`.**
Those three do not hold together: neither pinned version builds on 3.14, which is
the interpreter the work has been done on since Day 1. Raised at the Day 3
checkpoint and settled in favour of refreshing the pins rather than pinning the
interpreter back to 3.12 — the suite is green on 3.14 with the versions above,
and every perception measurement in `docs/progress/sameer.md` was taken on them.
Downgrading would mean re-verifying the ONNX export, the k-NN reprojection and
the 758-scan label cache to buy nothing.

Frontend (`webapp/`, Next.js):

```
node                    >= 20.11 LTS
next                    == 14.2.5      # App Router
react / react-dom       == 18.3.1
typescript              == 5.4.5
three                   == 0.165.0     # npm dependency, imperative use — NOT react-three-fiber
firebase                == 10.12.2     # client SDK, auth only
firebase-admin          == 12.1.1      # server-side ID token verification
mongodb                 == 6.7.0       # official driver; no ODM
tailwindcss             == 3.4.4
```

**`three` is used imperatively and `react-three-fiber` is deliberately excluded** (FR-42).
Rendering 50,000 instanced cells at 30 FPS through React reconciliation is the fastest way to
lose the frame-rate claim; the viewer is a `useRef` canvas driven by a plain
`requestAnimationFrame` loop.

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

# backend — pipeline + WebSocket frame stream
python -m avr25d.server.app --fixtures         # ws://localhost:8000/stream

# frontend — Next.js app, in a second terminal
cd webapp && pnpm install && pnpm dev          # http://localhost:3000
```

### 2.3 Cloud services

Both are cloud-only by decision (`PRD.md` R-11). Two accounts, set up on Day 1:

- **Firebase** — one project, Authentication enabled with Email/Password and Google providers.
  Client config goes in `webapp/.env.local`; the Admin service-account JSON goes in
  `FIREBASE_SERVICE_ACCOUNT` as a single-line env var and is **never committed**.
- **MongoDB Atlas** — free M0 cluster, one database `avr25d`, one user. Connection string in
  `MONGODB_URI`.

`webapp/.env.local.example` lists every variable with a comment. `.env.local` is gitignored.
Anyone who commits a service account key rotates it immediately and tells the team.

### 2.4 Serve the demo from localhost, not from Vercel

**NFR-9, and it will bite you if you forget it.** A page served over HTTPS from Vercel cannot
open a `ws://localhost:8000` connection — browsers block mixed content, and the frame stream
silently never connects. The Vercel deployment exists so the submission has a live link; the
**live demo runs `pnpm dev` on the demo machine at `http://localhost:3000`**, talking to the
local FastAPI server. Verify this on Day 7, not Day 13.

**NFR-4 is load-bearing.** No CUDA, no `spconv`, no `torchsparse`, no compiled extension, no
platform-specific build step. If a dependency needs a C++ toolchain, it does not go in
`requirements.txt`. Numba is optional and every Numba-accelerated function has a NumPy
sibling selected by `config.yaml: use_numba`.

### 2.5 Day-1 cross-platform smoke test

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
│   ├── synth/                      # synthetic scenes with exact ground truth (PRD §9.3)
│   │   ├── raycast.py              # spherical ray-cast vs plane / AABB / cylinder
│   │   ├── scenegen.py             # scene assembly from a spec CSV
│   │   ├── export.py               # write KITTI-format .bin + .label
│   │   └── scenes/*.csv            # one primitive per row
│   └── server/
│       ├── app.py                  # FastAPI + WebSocket, pipeline driver
│       ├── protocol.py             # FrameMessage encode/decode — FROZEN DAY 1
│       └── fixtures.py             # synthetic schema-valid frames
├── webapp/                         # Next.js 14, App Router, TypeScript
│   ├── app/
│   │   ├── layout.tsx  page.tsx
│   │   ├── (auth)/login/page.tsx   # Firebase Auth gate
│   │   ├── dashboard/page.tsx      # the live viewer
│   │   ├── runs/page.tsx           # run history from MongoDB
│   │   ├── runs/[id]/page.tsx      # one run: config, results, decision log
│   │   └── api/
│   │       ├── runs/route.ts       # POST/GET runs      (token-verified)
│   │       ├── decisions/route.ts  # POST batched decision records
│   │       └── scenes/route.ts     # scene registry + ground truth
│   ├── components/
│   │   ├── viewer/                 # Shubham — imperative Three.js, no React state
│   │   │   ├── Viewer.tsx  useThreeScene.ts  instancedCells.ts
│   │   │   ├── ringOverlay.ts  wipe.ts  views.ts
│   │   ├── hud/                    # Navya
│   │   │   ├── Hud.tsx  LatencyBars.tsx  MemoryPanel.tsx  ModeBadge.tsx
│   │   └── decision/DecisionPanel.tsx  TrackList.tsx
│   ├── lib/
│   │   ├── firebase/client.ts  admin.ts
│   │   ├── mongo.ts                # cached client, collections, indexes
│   │   ├── protocol.ts             # FrameMessage decode — mirrors protocol.py
│   │   ├── palette.ts              # class colours — single source of truth
│   │   └── ws.ts                   # WebSocket client, reconnect, backpressure
│   ├── .env.local.example
│   └── package.json
├── hardware/                       # companion workstream — PRD §16
│   ├── docs/DESIGN_REPORT.md  LINK_BUDGET.md  BOM.md
│   ├── matlab/link_budget.m  range_accuracy.m  snr_sweep.m
│   │           scan_coverage.m  power_budget.m
│   ├── simulink/tof_receiver_chain.slx
│   └── figures/
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

### 6.1 `core/grid.py` — ring table and projection · Anuj

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

### 6.2 `core/cell.py` — accumulation and analysis · Anuj

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

### 6.3 `core/refine.py` — bounded local refinement · Anuj

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

### 6.4 `perception/range_proj.py` · Sameer

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

### 6.5 `perception/geometric_seg.py` — build this first · Sameer

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

### 6.6 `perception/onnx_infer.py` · Sameer

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

### 6.7 `perception/cache.py` · Sameer

```python
def build_cache(scan_paths, segmenter, out_dir) -> None:
    """Run the segmenter once over the whole subset, write uint8 labels per scan."""

class LabelCache:
    def __init__(self, cache_dir): ...     # memory-maps; no per-frame disk read
    def __getitem__(self, frame_id) -> np.ndarray: ...
```

Storage is `n_points × 1` byte per scan — about 120 KB, so 1000 scans is 120 MB. Built
overnight Day 6→7 while everyone sleeps, which is the only free compute the team has.

### 6.8 `decision/traversability.py` · Sameer

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

### 6.9 `decision/tracker.py` · Sameer

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

### 6.10 `decision/costmap.py`, `planner.py`, `explain.py` · Anuj

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

### 6.11 `bench/` · Sameer

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

### 6.12 `server/app.py` · Anuj

```python
# python -m avr25d.server.app [--fixtures] [--infer live|cached|geometric]
#                             [--seq 04] [--replay LOG] [--record LOG]
```

Pipeline driver, WebSocket broadcaster, static file server for `web/`. Runs the pipeline in a
worker thread and pushes `FrameMessage`s on a fixed cadence, dropping frames rather than
queueing them if a consumer falls behind — a demo must degrade in frame rate, never in
latency.

**Tests:** T-P6. The mode on the wire is the mode that ran: both fallbacks here — a missing
ONNX file and a missing label cache — rewrite `mode` to `geometric`, because FR-6 puts the
active mode on the HUD at all times and a badge reading "network" over geometric labels is
worse than a crash.

### 6.13 `webapp/components/viewer/` — the Three.js viewer · Shubham

Owns the entire rendering path. **No React state touches per-frame data** (FR-42).

```ts
// useThreeScene.ts
export function useThreeScene(canvasRef: RefObject<HTMLCanvasElement>) {
  // Creates renderer/scene/camera ONCE in an effect keyed on [].
  // Returns an imperative handle. Frames arrive via handle.pushFrame(msg) from the
  // WebSocket callback and are written straight into GPU buffers. React never re-renders.
}

// instancedCells.ts
export function updateCells(mesh: THREE.InstancedMesh, cells: CellArrays): void
// Writes per-instance matrix from (centre, extent, z_ground, z_obstacle) and per-instance
// colour from palette.ts. One draw call for ~50,000 cells. Reallocates the InstancedMesh
// only when n exceeds the current capacity, growing in powers of two.
```

**Why `useRef` and not `useState`.** A `FrameMessage` arrives 30 times a second carrying
typed arrays for tens of thousands of cells. Putting that in React state would run
reconciliation 30 times a second over data only a WebGL buffer ever reads. The canvas is a
ref, the render loop is a plain `requestAnimationFrame`, and React renders only the chrome
around the canvas. This is FR-42 and risk R-13.

**Views** (`views.ts`, FR-25): raw cloud, uniform 5 cm grid, adaptive grid, decision layer.
Plus `ringOverlay.ts` (FR-27) and `wipe.ts` (FR-29).

**The A/B wipe is the single most persuasive object in the submission.** Same scan, same
camera, a draggable divider, live cell counts on both sides reading 16,000,000 against
705,771. Implemented as two scissor-rect renders of the same scene graph with different cell
sets — not two canvases, which would double the WebGL context cost.

**Performance fallback** (risk R-4): if instancing underperforms, render cell centroids as a
`THREE.Points` cloud with per-point size. Visually near-identical at demo zoom, far cheaper.

**Tests:** T-V1, T-V2, T-V3, T-V5, T-V6, T-W7.

### 6.14 `webapp/app/`, `lib/`, `components/hud/` — platform, auth, persistence · Navya

Owns the Next.js application, the auth gate, the MongoDB layer, the HUD and the decision panel.

```ts
// lib/ws.ts — the realtime path. Bypasses Next.js entirely (FR-41).
export function connectFrames(url: string, onFrame: (m: FrameMessage) => void): () => void
// Direct browser -> ws://localhost:8000/stream. Exponential-backoff reconnect.
// Drops frames rather than queueing when the consumer falls behind — degrade in frame
// rate, never in latency.

// lib/protocol.ts — mirrors avr25d/server/protocol.py. Decodes the JSON header, then maps
// each payload onto a typed-array view over the received ArrayBuffer. Zero copies.

// lib/firebase/admin.ts
export async function requireUser(req: Request): Promise<DecodedIdToken>
// Verifies the Bearer ID token with the Admin SDK. Every route handler that writes calls
// this FIRST (FR-37). No handler ever trusts a client-supplied uid.

// lib/mongo.ts — module-scoped cached MongoClient (Next.js route handlers are per-request;
// creating a client per request exhausts the Atlas connection pool within minutes).
```

**MongoDB schema.** Four collections, indexed on Day 5.

| Collection | Document | Indexes |
|---|---|---|
| `runs` | `{_id, uid, startedAt, finishedAt, gitCommit, platform, config, results, mode}` — one per pipeline or benchmark run, carrying the full `config.yaml` snapshot and `results.json` payload (FR-38) | `{uid:1, startedAt:-1}` |
| `decisions` | `{_id, runId, frameId, tSec, selected, risk, etaS, reason, trackIds, changed}` — the routing audit trail (FR-39) | `{runId:1, frameId:1}` |
| `scenes` | `{_id, name, primitives, groundTruth:{potholeDepth, clearance, curbHeight, truckSpeed}}` (FR-40) | `{name:1}` unique |
| `users` | `{_id: firebaseUid, email, displayName, createdAt}` | `_id` |

**Decision writes are batched** (FR-39, NFR-10). A record is queued when the selected route,
risk level or reason string changes, and otherwise at most once every 60 frames. The queue
flushes on a 2-second timer via `insertMany`, off the render path and never awaited inside
the frame loop. At 30 FPS the naive alternative is 30 Atlas round-trips per second, which
would both dominate the latency budget and store thirty near-identical documents per second.

**Why `runs` matters beyond the demo.** Every number in the deck traces to a `results.json`,
and every `results.json` now lives in a `runs` document with the exact config and git commit
that produced it. When a judge asks "where did that 22.67× come from?", the answer is a run
id, not a memory.

**HUD** (`components/hud/`, FR-28): FPS, per-stage latency bars, total latency, occupied
cells, memory both sides, reduction factor, **perception-mode badge** (FR-6), frame index.
Every value comes from `stats` in the `FrameMessage` — never computed in the browser, so the
HUD and `results.json` cannot disagree.

**Tests:** T-V4, T-W1 … T-W6.

### 6.15 `avr25d/synth/` — synthetic scenes with exact ground truth · Sameer

Moved here from MATLAB (PRD §9.3). About 150 lines, and it shares its spherical projection
maths with `perception/range_proj.py`, which Sameer is writing anyway.

```python
def raycast(scene: Scene, sensor: SensorSpec) -> tuple[np.ndarray, np.ndarray]:
    """64 beams x 1800 azimuths. For each ray, intersect against every primitive
    (plane / axis-aligned box / cylinder), keep the nearest hit, emit the point and the
    primitive's class label. Adds Gaussian range noise (sigma = 0.02 m) and drops returns
    beyond r_max, so synthetic clouds have realistic density falloff.
    Returns (xyzi float32[n,4], labels uint32[n])."""

def load_scene(csv_path) -> Scene:   # one primitive per row
def export_kitti(pts, labels, out_dir, frame_id) -> None
```

Scene CSV — one primitive per row, so authoring a hazard scene is editing a table:

```csv
type,   x,     y,     z,     sx,   sy,   sz,   class, note
plane,  0,     0,     0,     200,  200,  0,    1,     road surface
box,    12.0, -0.5,  -0.22,  1.4,  1.0,  0.22, 0,     pothole (negative)
box,    25.0,  0.0,   3.10,  6.0,  0.4,  0.5,  3,     gantry beam, 3.10 m clearance
cyl,    25.0, -3.0,   1.55,  0.3,  0.3,  3.10, 3,     gantry support post
```

`x` forward, `y` left, `z` up, sensor at the origin 1.7 m above the road. `class` is the
taxonomy from `PRD.md` §6.1.

**Because the scene is analytic, ground truth is exact and free** — the pothole is 0.220 m
deep and the gantry clearance is 3.100 m to machine precision. That is what turns hazard
preservation from a demo into a measurement with an error in metres (PRD §11.4). Ground-truth
values are written to the `scenes` collection (FR-40) so the benchmark and the dashboard read
truth from one place.

Five scenes: `S1_flat_road`, `S2_pothole`, `S3_overhang`, `S4_curb`, `S5_crossing_truck`
(40 frames), plus two adversarial scenes on Days 9–10.

**Tests:** T-H4.

### 6.16 `hardware/` — drone LiDAR sensing payload · Khanak and Veda

Companion workstream, specified in `PRD.md` §16. **No software module depends on it** and it
introduces no runtime dependency; it is developed and presented in parallel.

| File | Produces |
|---|---|
| `matlab/link_budget.m` | Received optical power and SNR against range, for reflectivity 0.1–0.9 (HW-1) |
| `matlab/range_accuracy.m` | `σ_range = c·σ_t / 2` error budget; walk error with and without CFD (HW-4) |
| `matlab/snr_sweep.m` | Sweeps over aperture, reflectivity and sunlight background (HW-1) |
| `matlab/scan_coverage.m` | MEMS scan pattern → angular sampling → point density against range (HW-5) |
| `matlab/power_budget.m` | Per-component power and mass, totalled against the drone payload limit (HW-6) |
| `simulink/tof_receiver_chain.slx` | Pulse → APD → TIA → CFD → TDC with noise; measured against true range (HW-3) |
| `docs/DESIGN_REPORT.md` | The design, with every figure reproducible from the scripts above (HW-8) |
| `docs/BOM.md` | Costed component list with justification |

**Every `.m` file is base-language only** and runs unmodified in free GNU Octave. The only
Simulink-dependent item is the receiver-chain model, and it has a documented pure-MATLAB
equivalent: discrete-time convolution of the laser pulse with the detector impulse response,
plus shot and thermal noise, with the CFD and TDC applied numerically. Same waveforms, same
range-error figures, no Simulink. Take that path immediately if a licence is not available
(risk R-12) rather than spending days chasing one.

**Eye safety is not optional** (HW-2). The IEC 60825-1 Class 1 accessible-emission limit at
905 nm must be worked through explicitly in the report. A LiDAR design that does not address
it is not a credible design, and it is exactly the question a DRDO evaluator asks.

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
| **Sameer** | **First action of the sprint:** start the SemanticKITTI subset download (seq 04, then 00, then 05). It is bandwidth-bound, so it runs unattended all day. Then begin `geometric_seg.py` (§6.5). |
| **Anuj** | Repo scaffold, `requirements.txt`, `config.yaml`, `tools/ring_table.py`. Write and **freeze `protocol.py`** (§5.2), then `fixtures.py` (§5.3) and push both by 14:00 — the frontend pair is blocked until this lands. Then start `core/grid.py`. |
| **Navya** | **Create the Firebase project and the Atlas M0 cluster** (§2.3) — external accounts are lead-time items, so they go first. Then `create-next-app`, Tailwind, `.env.local.example`, and `lib/protocol.ts` decoding fixture frames. |
| **Shubham** | Three.js scene inside a `useRef` canvas — renderer, orbit camera, ground reference, `lib/palette.ts`. From 14:00, render fixture cells as one `InstancedMesh`. |
| **Khanak** | Install MATLAB/Octave; confirm whether Simulink is available (risk R-12) and tell the team either way. Read `PRD.md` §16. Draft the payload architecture block diagram. |
| **Veda** | Confirm deck template and submission mechanics (Q-2, Q-3). Deck outline. Start prior-art search. |

**Exit criteria.** `pytest -q` green on both a Mac and the Windows box. `pnpm dev` serves a
page rendering ~50,000 fixture cells. Firebase project and Atlas cluster exist. KITTI seq 04
downloading. Nobody is blocked.

#### Day 2 — Sat 29 Aug · The grid exists

| Owner | Task |
|---|---|
| **Anuj** | Finish `core/grid.py`: ring table, `ring_of`, `cell_of`, `cell_centres`, `cell_extents`. Tests T-G1 – T-G4. |
| **Sameer** | Finish `geometric_seg.py`. `io/kitti.py` readers. |
| **Navya** | Firebase Auth: login page, both providers, middleware gating `/dashboard` (FR-36). `lib/ws.ts` with reconnect. |
| **Shubham** | Class colouring, per-instance sizing from `cell_extents`, elevation-shading toggle. |
| **Khanak** | `link_budget.m` — received power against range. First numbers out. |
| **Veda** | Prior-art and novelty write-up. Draft slides 1–2. |

**Exit criteria.** `RingGrid` reports **662 rings and 705,771 cells**; T-G4 passes including
its adversarial inputs. T-W1 passes — unauthenticated users cannot reach `/dashboard`.

#### Day 3 — Sun 30 Aug · First real scan end-to-end

| Owner | Task |
|---|---|
| **Anuj** | `core/cell.py`: SoA arrays, `accumulate` scatter-reduce, `z_ground` estimator, ring-neighbour table. `server/app.py` driving the real pipeline. |
| **Sameer** | `labelmap.py` (19→5 including `moving-*`). **`avr25d/synth/` ray-caster** (§6.15) plus scenes `S1`, `S2`, `S3` — needed by Day 4. |
| **Shubham** | View 1 (raw cloud) and View 3 (adaptive grid) on real streamed frames. |
| **Navya** | HUD wired to real `stats`. View switching, frame stepping, pause. |
| **Khanak** | `range_accuracy.m` — jitter and walk error into a range error budget. |
| **Veda** | Slides 3–4. Begin the judge Q&A bank. Start the payload design report skeleton with Khanak. |

**Exit criterion.** A real KITTI scan, geometrically segmented, projected into the adaptive
grid, rendered class-coloured in the browser, with `n_points_conserved == n_points` on the HUD.

---

### Block B — Perception and the memory evidence

#### Day 4 — Mon 31 Aug · Hazards

| Owner | Task |
|---|---|
| **Anuj** | `cell.analyse()`: slope, roughness, OVERHANG, NEGATIVE_OBSTACLE, STEP, VOID_UNOBSERVED, LOW_CONFIDENCE. |
| **Sameer** | Acquire an ONNX SemanticKITTI checkpoint (Q-4). Export and int8-quantise. Begin `range_proj.py`. |
| **Shubham** | View 2 — the uniform 5 cm grid, needed for the comparison. |
| **Navya** | `lib/mongo.ts` and `app/api/runs/route.ts` with `requireUser` token verification (FR-37). |
| **Khanak** | `snr_sweep.m` — reflectivity, aperture and sunlight background sweeps. |
| **Veda** | Slide 5. Full deck draft with `_measured_` placeholders intact. |

**Exit criteria.** Overhang and pothole flags fire on `S3` and `S2`; `S1_flat_road` produces
**zero** flags. T-W2 passes on the `runs` route.

#### Day 5 — Tue 1 Sep · The money shot

| Owner | Task |
|---|---|
| **Shubham** | **The A/B wipe** (FR-29) and the ring overlay (FR-27). Highest-value visual in the submission — build it today, not in the final week. |
| **Anuj** | `bench/baselines.py`, `bench/memory.py`. |
| **Sameer** | `onnx_infer.py`; k-NN reprojection in `range_proj.py`. Scenes `S4`, `S5`. |
| **Navya** | Mongo collections and indexes created. `app/api/scenes/route.ts`; scene ground truth registered (FR-40). |
| **Khanak** | `scan_coverage.m` — MEMS scan pattern to angular sampling and point density. |
| **Veda** | Video script timed to 3:00, beats matched to the run-book. |

**Exit criteria.** The draggable divider shows uniform against adaptive on the *same* scan
with live cell counts reading **16,000,000 vs 705,771**. T-W5 passes.

#### Day 6 — Wed 2 Sep · Perception lands

| Owner | Task |
|---|---|
| **Sameer** | ONNX inference producing sane labels with measured CPU latency. **Kick off the label-cache build overnight.** |
| **Anuj** | `bench/latency.py`; per-stage timing wired into `stats`. |
| **Shubham** | Wipe polish; performance pass on instance count. |
| **Navya** | Full HUD per FR-28, including the **perception-mode badge** (FR-6). |
| **Khanak** | `power_budget.m`; begin the component selection table. |
| **Veda** | Q&A bank to 12 questions. Payload design report: architecture and component-justification sections. |

**Exit criterion.** Network labels visibly better than geometric labels on the same scan, with
both modes selectable and the active mode shown on the HUD.

---

### Block C — Decision layer

Both `core/` and `perception/` have landed. Sameer and Anuj now converge on `decision/` — the
one module deliberately not pre-assigned to a single person.

#### Day 7 — Thu 3 Sep · Traversability and tracking

| Owner | Task |
|---|---|
| **Sameer** | `decision/traversability.py` and `decision/tracker.py`. Verify the overnight label cache. |
| **Anuj** | `decision/costmap.py` — polar → 160 × 160 ego-front Cartesian resample. |
| **Shubham** | View 4 scaffold: track markers and predicted trajectories. |
| **Navya** | `app/api/decisions/route.ts` with **batched writes** (FR-39). **Verify the localhost-vs-Vercel mixed-content path today** (NFR-9) — not on Day 13. |
| **Khanak** | Simulink receiver chain, or the pure-MATLAB fallback if Day 1 found no licence. |
| **Veda** | Deck to near-final. Q&A bank to 20 questions. |

**Exit criteria.** On `S5` the tracker holds one stable ID across all 40 frames with speed
within 0.5 m/s of 8.0 m/s. NFR-9 confirmed: the demo path is `http://localhost:3000`.

#### Day 8 — Fri 4 Sep · Planning and explanation

| Owner | Task |
|---|---|
| **Anuj** | `decision/planner.py` (A*, primary plus a genuinely distinct alternative) and `decision/explain.py`. |
| **Sameer** | `bench/distance_bins.py` and `bench/hazard.py`. |
| **Shubham** | View 4 complete: routes, risk shading, legible from three metres. |
| **Navya** | Decision panel: route, risk, ETA, reason string. `/runs` history page. |
| **Khanak** | Finish the receiver-chain model; produce measured-against-true range plots. |
| **Veda** | Assemble the demo run-book with Sameer. Payload BOM table. |

**Exit criteria.** On `S5`, a tracked crossing truck triggers a reroute and the dashboard
shows the alternative route with a reason string naming the track, its speed and the predicted
intersection time. T-W4 passes — reroutes plus heartbeats, not one write per frame.

---

### Block D — Depth · work the six-day schedule could not afford

#### Day 9 — Sat 5 Sep · Refinement, both kinds

| Owner | Task |
|---|---|
| **Anuj** | `core/refine.py` — bounded refinement (FR-17, FR-18) **plus uncertainty-driven refinement** *[pulled forward]*, completing the `R = f(distance, complexity, semantics, uncertainty)` claim slide 2 makes. |
| **Sameer** | Fine-tuning split prep. **Resolve Q-1 definitively.** Adversarial scene: occluded pothole. |
| **Shubham** | LOD tuning; verify ≥30 FPS at 100k instances (FR-30) and the React render count (T-W7). |
| **Navya** | `/runs/[id]` detail page: config, results, decision log. |
| **Khanak** | Eye-safety calculation (HW-2) worked through against IEC 60825-1. |
| **Veda** | Payload design report first full draft. Record a rough-cut video against the current build. |

**Exit criteria.** A distant moving vehicle is visibly resolved finer than the empty road
beside it; T-R2 and T-W7 pass.

#### Day 10 — Sun 6 Sep · Perception improvement *[pulled forward, conditional]*

| Owner | Task |
|---|---|
| **Sameer** | **If Q-1 says the GPU is usable:** fine-tune on the 5-class taxonomy. **If not:** decoder-head-only fine-tune on CPU over a small subset plus temperature calibration of confidence, which feeds Day 9's uncertainty-driven refinement. Either way, run it overnight. Adversarial scene: low-clearance tunnel with a curb. |
| **Anuj** | `--replay` and `--record`. Record the demo sequence log early. |
| **Shubham + Navya** | Polish. Deploy to Vercel for the submission link, keeping localhost as the demo path. |
| **Khanak** | Regenerate every payload figure from its script; confirm reproducibility (HW-8). |
| **Veda** | Fix everything the rough cut exposed. |

**Exit criterion.** A measured before/after mIoU comparison exists, whichever branch was
taken. If neither improved anything, that is a finding — record it and move on. Do not spend
Day 11 chasing it.

#### Day 11 — Mon 7 Sep · Expanded evaluation · **FEATURE FREEZE 21:00**

| Owner | Task |
|---|---|
| **Sameer** | `bench/report.py`. **First full `make bench`.** Multi-sequence evaluation *[pulled forward]* with per-sequence variance. |
| **Anuj** | Final integration. Fix whatever the full bench exposes. Then: nothing new. |
| **Shubham + Navya** | Final polish. Demo keystroke sequence verified end to end. |
| **Khanak** | Payload design report complete. |
| **Veda** | Deck final except for `_measured_` placeholders. Rehearse the Q&A bank with the team. |

**Exit criterion at 21:00.** Full pipeline runs end to end on KITTI and every synthetic scene;
`make bench` produces a complete `results.json`; the payload report is done. **After this
point, no new features. Bugs, numbers, polish and rehearsal only.**

---

### Block E — Evidence, rehearsal, submit

#### Day 12 — Tue 8 Sep · Authoritative numbers

| Owner | Task |
|---|---|
| **Sameer** | Final benchmark runs: ≥200 scans for latency, full subset for accuracy, all scenes for hazards. Produce the authoritative `results.json`, persist it as a `runs` document, hand it to Veda. No changes after handover. |
| **Anuj** | Bug fixes only. Re-record the demo replay log against the frozen build. |
| **Shubham + Navya** | Bug fixes only. |
| **Khanak** | **Cross-check every number destined for the deck against `results.json`** — software and payload both. |
| **Veda** | **Fill every `_measured_` placeholder from `results.json` only.** |

**Exit criterion.** Zero `_measured_` placeholders remain anywhere, and every filled number
traces to a line in `results.json` or to a payload script.

#### Day 13 — Wed 9 Sep · Video and rehearsal

| Owner | Task |
|---|---|
| **Veda** | Finalise the deck, including the payload slide. Record the narration. |
| **Navya** | **Edit the 3-minute video** — picked up from Veda, whose load peaks here (§8 note). |
| **Sameer** | Run the demo. Nothing else. |
| **All** | Three full timed demo rehearsals, including both failure paths (replay fallback, LOD drop). |

**Exit criteria.** Video rendered and stored **locally** on the presenting laptop. Deck final.
Three clean rehearsals. Replay-log fallback verified on the demo machine.

#### Day 14 — Thu 10 Sep · Submit

Morning buffer for whatever broke overnight. Final rehearsal. **Submit.** Live demo.

Nothing is scheduled into this day on purpose. A fourteen-day plan with no slack is a
thirteen-day plan that fails.

**Load note.** Moving both non-tech members onto the payload leaves the evidence workstream
thinner than it was. Veda still owns the deck, the script, the Q&A bank and the submission,
but the video *edit* moves to Navya on Day 13 and the deck number cross-check moves to Khanak
on Day 12. If Veda's Days 11–13 look overloaded at the Day 10 standup, move the Q&A rehearsal
to Sameer — it is the most transferable item.

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

### Web platform

| ID | Test |
|---|---|
| **T-W1** | An unauthenticated request to `/dashboard` redirects to `/login`. A signed-in user reaches it. Both Firebase providers (email/password, Google) complete a sign-in. |
| **T-W2** | Every `app/api/*` write handler rejects a request with a missing, malformed or expired Firebase ID token with `401`, **before** touching MongoDB. Asserted per route, not once globally — a single unprotected handler is the whole vulnerability. |
| **T-W3** | Completing a benchmark run inserts one `runs` document whose `config` and `results` round-trip byte-identically against the local `results.json`. |
| **T-W4** | Over a 600-frame replay containing exactly 2 reroutes, the `decisions` collection receives 2 change-triggered records plus 10 heartbeats — not 600. Proves FR-39's batching rather than assuming it. |
| **T-W5** | Each of the five scenes has a `scenes` document, and its `groundTruth` values equal the CSV specification exactly. |
| **T-W6** | The frame stream connects browser→FastAPI directly: no Next.js route handler appears in the network trace for `/stream`, and killing the Next.js dev server mid-stream does not interrupt rendering. |
| **T-W7** | Instrument a React render counter on the dashboard route: over 300 streamed frames it increments **fewer than 10 times**. Per-frame data must not be entering React state (FR-42). |

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
- Login or Atlas unreachable → the pipeline, viewer and HUD are entirely local and keep
  running; only run history and the audit log are affected. Say so plainly if asked and
  continue — do not attempt to debug cloud connectivity in front of judges.
- Everything fails → play the recorded video. It is on the presenting laptop, not in the cloud.

**Pre-demo checklist**, in order:

1. Laptop on mains power; display sleep off; notifications off; browser zoom 100%.
2. `data/` populated — KITTI subset and all synthetic scenes present.
3. Backend up: `python -m avr25d.server.app --infer cached`.
4. Frontend up **on localhost**: `cd webapp && pnpm dev`, then open
   `http://localhost:3000`. **Not the Vercel URL** — an HTTPS origin cannot open
   `ws://localhost` and the frame stream will silently never connect (NFR-9).
5. **Sign in to Firebase now, before the audience arrives**, and leave the tab open. The ID
   token refreshes for an hour, so an authenticated session survives a network drop that a
   fresh login would not (risk R-11).
6. Phone hotspot on and paired, as the second network.
7. Confirm the Atlas connection once — load `/runs` and see history render.
8. One full silent run-through completed.
9. Video file and replay log both present **locally** on this laptop.

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
| 11–13 Sep | Complete the perception fine-tune if Day 10 took the CPU-only branch, or if GPU access arrives late. | Sameer |
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
- [ ] Auth gate works; every write route rejects an unverified token (T-W1, T-W2)
- [ ] A completed run appears in `runs`, and `/runs/[id]` renders its config and results
- [ ] Decision batching verified — reroutes plus heartbeats, not one write per frame (T-W4)
- [ ] React render count under 10 across 300 streamed frames (T-W7)
- [ ] Demo verified from `http://localhost:3000`, not the deployed origin (NFR-9)
- [ ] Vercel deployment live for the submission link
- [ ] **Payload (companion):** design report complete; link budget, range accuracy, scan
      coverage and power/mass figures all reproducible from their scripts; eye-safety
      calculation present; payload slide in the deck
