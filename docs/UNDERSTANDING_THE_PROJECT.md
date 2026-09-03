# Understanding AVR-25D — A Plain-English Guide

> Written for Anuj, who is reading this project for the first time.
> No jargon assumed. Every term is explained before it is used.

---

## What is this project, in one sentence?

You are building software that takes the raw output of a **LiDAR sensor** (a
laser-based 3D scanner mounted on a vehicle) and turns it into a smart map that
tells the vehicle: *"this patch of ground is safe to drive on, that one has a
pothole, and a truck is crossing your path in 4 seconds."*

The full name is **AVR-25D** — Adaptive Variable-Resolution 2.5D LiDAR Mapping.

---

## Part 1 — The Problem Being Solved

### What is LiDAR?

A LiDAR sensor sits on top of a vehicle and spins 10 times a second. Each spin
fires ~120,000 laser pulses in every direction. Each pulse bounces off something
— the road, a wall, a pedestrian — and comes back. By timing the round-trip, the
sensor measures the exact 3D position of every reflection. The result is a cloud
of ~120,000 (x, y, z) points, called a **point cloud**, produced 10 times a
second.

### Why existing approaches fail

There are two obvious things you could do with that point cloud, and both are
wrong for an autonomous logistics vehicle:

**Option 1 — Keep all 120,000 points in 3D.**
Rich and accurate, but processing 1.2 million points per second requires a
powerful computer. Logistics vehicles (yard trucks, warehouse shuttles, convoy
support vehicles) carry small embedded computers. It does not fit.

**Option 2 — Flatten to a 2D grid.**
Cheap to process, but you throw away height information. A pothole and a bridge
above a clear road both become just "occupied cell" in a 2D grid. The vehicle
has no way to know one is dangerous and the other is fine. It cannot tell if it
fits under the bridge.

### The solution — a 2.5D foveated map

AVR-25D uses a middle path:

- **2.5D** means a top-down grid where each cell stores *height information* —
  not just "occupied/free" but "the ground here is at 0.12 m, the obstacle
  reaches 1.8 m, so clearance is 1.68 m."

- **Foveated** means the grid is fine-grained close to the vehicle (where
  decisions are made right now) and coarse far away (where the sensor itself
  doesn't have fine detail anyway). The word comes from the human eye — your
  retina is dense in the centre and sparse at the edges.

- **Variable resolution** means cell size grows with distance: 5 cm cells within
  10 m, growing up to 50 cm cells at 100 m. This saves **22.67× memory** versus
  a flat 5 cm grid covering the same area (705,771 cells vs 16,000,000 cells).

---

## Part 2 — The Big Picture (System Architecture)

Here is the full pipeline, from laser pulse to decision:

```
  LiDAR scan (~120,000 points)
         │
         ▼
  ┌─────────────────────┐
  │  1. PERCEPTION      │  "What is each point?"
  │                     │  Every point gets a label:
  │                     │  road / terrain / building / vehicle / unknown
  └──────────┬──────────┘
             │
             ▼
  ┌─────────────────────┐
  │  2. GRID PROJECTION │  "Where does each point go on the map?"
  │                     │  Each (x,y,z) point → one cell in the ring grid
  │                     │  Cell stores height, class, roughness, etc.
  └──────────┬──────────┘
             │
             ▼
  ┌─────────────────────┐
  │  3. HAZARD ANALYSIS │  "What is dangerous?"
  │                     │  Detects potholes, curbs, low bridges
  └──────────┬──────────┘
             │
             ▼
  ┌─────────────────────┐
  │  4. DECISION LAYER  │  "What should the vehicle do?"
  │                     │  Scores traversability, tracks moving objects,
  │                     │  plans a route with A*, explains the choice
  └──────────┬──────────┘
             │  (sent over WebSocket to the browser, 30 times/second)
             ▼
  ┌─────────────────────┐
  │  5. WEB DASHBOARD   │  "Show me everything."
  │                     │  Next.js app with a 3D viewer, live HUD,
  │                     │  side-by-side comparison, route display
  └─────────────────────┘
```

---

## Part 3 — Stage 1: Perception (labelling each point)

### The five classes

Every point in the cloud gets assigned one of exactly five categories:

| ID | Name | Colour | Meaning |
|---|---|---|---|
| 0 | VOID | grey | Unknown / unlabelled |
| 1 | DRIVABLE | green | Road surface — safe to drive on |
| 2 | NON_DRIVABLE_TERRAIN | amber | Grass, verge, sidewalk — not a road but not a wall |
| 3 | STATIC_OBSTACLE | red | Building, fence, pole — fixed objects to avoid |
| 4 | DYNAMIC_OBJECT | blue | Car, truck, person — moving objects to track |

The real dataset (SemanticKITTI) has 19 categories. The code collapses them to
these 5 because it's cleaner, faster, and maps directly to what the problem
statement asks for.

### Two ways to do perception

**Method A — Neural network (the good one)**

The point cloud is projected onto a 64×2048 image (like a panoramic photo, but
each pixel stores range and coordinates instead of colour). A CNN runs on that
image and outputs a class label for each pixel. Then the labels are mapped back
onto the original 3D points.

The model used is **SqueezeSegV2**, an MIT-licensed network from University of
Bonn. It runs on CPU only (no GPU required). On Sameer's machine it scores
**mIoU 0.845** (84.5% overlap between predicted and true labels). It runs at
5.3 ms median per frame in cached mode.

**Method B — Geometric fallback (always available, no model needed)**

1. RANSAC fits a ground plane to the nearby points
2. Points on the plane → DRIVABLE
3. Everything above the plane → Euclidean clustering (group nearby points together)
4. Each cluster's bounding box decides: vehicle-shaped → DYNAMIC_OBJECT, large
   flat slab → NON_DRIVABLE_TERRAIN, everything else → STATIC_OBSTACLE

This scores **mIoU 0.291** — much lower, mainly because it can't tell tarmac
from flat grass. But it works without downloading a model and was built on
Day 1 to de-risk the project.

**Key measured result:**
| Mode | mIoU | End-to-end latency |
|---|---|---|
| Geometric | 0.291 | 63.8 ms |
| Network (cached labels) | 0.845 | 5.3 ms |

The demo runs with cached (pre-computed) labels at 5.3 ms. Live inference adds
~86 ms but is still measured and shown on the HUD.

---

## Part 4 — Stage 2: The Grid (the core math)

### What is a ring-sector grid?

Instead of a square grid, AVR-25D uses a **polar grid** — rings of cells around
the vehicle, like a dartboard. Each ring is divided into angular sectors. Cells
are approximately square at every distance.

```
         [vehicle]
            |||
   5cm  ___|||___
   cells|  |||  |
        |       |   ← inner rings, fine resolution
        |_______|
   10cm  _______
        |       |
        |       |
        |_______|
   ...growing...
   50cm  _______
        |       |   ← outer rings, coarse resolution
        |_______|
         100 m out
```

### The math behind the cell count

- Inside 10 m: 200 rings × ~628 sectors = **125,037 cells**
- Outside 10 m: 462 rings × 1,257 sectors = **580,734 cells**
- **Total: 705,771 cells** (vs 16,000,000 for a uniform 5 cm grid — 22.67× fewer)

The angular bin count is constant at 1,257 in the far field. This isn't an
accident — it falls out of the math when cell size grows proportionally with
range (s(r) = 0.005 × r). Each cell is approximately square at every range.

### Finding which cell a point belongs to — O(1) lookup

Given a point at distance r from the vehicle:

```python
# Inside 10 m
ring_index = floor(r / 0.05)

# Beyond 10 m
ring_index = 200 + floor(ln(r / 10) / ln(1.005))

# Then the angular bin
angle_bin = floor(theta / (2*pi) * bins_in_this_ring)

# Flat cell id (one integer)
cell_id = prefix_sum[ring_index] + angle_bin
```

This is one arithmetic operation — no searching, no hashing. The 662-element
prefix sum table stays in CPU cache permanently. This is the "sophisticated data
structure" the problem statement asks for.

### What each cell stores

Every cell carries 25 bytes of data (stored as parallel arrays, not structs):

| Field | Type | Meaning |
|---|---|---|
| z_ground | float32 | Height of the traversable surface |
| z_obstacle | float32 | Height of the highest obstacle in the cell |
| z_min | float32 | Lowest return (pothole detection) |
| roughness | float32 | Variance of ground heights (bumpiness) |
| slope | float32 | Steepness of the ground |
| class_id | uint8 | Dominant class (0–4) |
| confidence | uint8 | 0–255, how sure we are |
| flags | uint8 | Bitfield: OVERHANG, POTHOLE, STEP, MOVING, etc. |
| count | uint16 | How many LiDAR points landed here |

---

## Part 5 — Stage 3: Hazard Detection

This is what makes 2.5D better than 2D. Three hazards that a flat grid would
completely miss:

### Pothole (NEGATIVE_OBSTACLE flag)
Compare a cell's ground height to its neighbours. If it's more than 10 cm lower
than average, flag it as a pothole. A 2D grid would show nothing — the pothole
just looks like an occupied cell.

### Curb / step (STEP flag)
If adjacent cells have ground heights differing by more than 8 cm, flag as a step.

### Low bridge / gantry (OVERHANG flag)
If a cell's ground is drivable but the obstacle height is less than the vehicle's
height (3.5 m), the vehicle fits on the surface but NOT under whatever is above.
This is literally impossible to detect with a 2D map.

### Verification with synthetic scenes

Five synthetic LiDAR scenes with exact ground truth are generated in-code:

| Scene | What it tests |
|---|---|
| S1_flat_road | Control — no hazards, should produce zero flags |
| S2_pothole | 1.4 m × 0.22 m depression at 12 m |
| S3_overhang | Gantry at 3.10 m clearance over a drivable road |
| S4_curb | A kerb / step discontinuity |
| S5_crossing_truck | A vehicle moving at 8 m/s crossing the path |

Because the geometry is exact, the ground truth is exact — you know the pothole
is exactly 0.22 m deep and can measure whether the system reports it within a
few centimetres.

---

## Part 6 — Stage 4: Decision Layer

Once the map is built and hazards are flagged, the vehicle needs to decide what to do.

### Step 1 — Traversability score (0 to 1 per cell)
Each cell gets a score. 1.0 = perfectly safe, 0.0 = completely blocked.

```
score = 1 - (
    0.30 × slope_penalty       (steepness)
  + 0.20 × roughness_penalty   (bumpiness)
  + 0.20 × step_penalty        (kerb detection)
  + 0.20 × class_penalty       (semantic class)
  + 0.10 × clearance_penalty   (low bridge)
)
```

Weights add to 1.0 and are in `config.yaml` with a one-line justification each.

### Step 2 — Track moving objects
`DYNAMIC_OBJECT` cells are clustered into discrete objects. Each object is
tracked frame-to-frame with a Kalman filter — the same math used in GPS and
aircraft navigation — predicting position and velocity.

### Step 3 — Plan a route (A* algorithm)
The polar map is resampled into a 40 m × 40 m Cartesian grid (160 × 160 cells at
25 cm resolution, centred on the vehicle's forward direction). A* finds the
lowest-cost path through it.

Cost per step: distance + slope + roughness + obstacle risk + clearance risk.

Two routes are found: a primary and a genuinely different alternative.

### Step 4 — Explain the decision
Every frame produces a human-readable reason string like:

> *"Rerouted: track #7 (DYNAMIC_OBJECT, 8.2 m/s) predicted to intersect primary
> route at t+4.0 s. Alternative adds 0.3 km at LOW terrain risk."*

The system is fully **deterministic** — same input always produces the same
route and the same reason string. No randomness anywhere.

---

## Part 7 — Stage 5: The Web Dashboard

The dashboard is a **Next.js** (React) web app running in the browser. It shows
four views of the same frame simultaneously:

| View | What you see |
|---|---|
| 1 | Raw point cloud — the raw LiDAR output |
| 2 | Uniform 5 cm 2.5D grid — what it would look like with no variable resolution |
| 3 | AVR-25D adaptive grid — the actual system output |
| 4 | Decision view — routes, tracked objects, risk shading |

### Key UI features

**A/B wipe** — drag a divider between View 2 and View 3 on the same scan. The
live cell counts (16,000,000 vs 705,771) update as you drag. This is the main
demo moment for the judges — it makes "22.67× fewer cells" something you can
*see*, not just a number.

**Ring overlay** — toggle lines showing the ring boundaries so the variable
resolution is directly visible.

**Live HUD** — shows FPS, latency per stage, memory usage, reduction factor,
and whether perception is running live or from cache.

### Technical choices (and why)

- The browser connects **directly** to the Python backend via WebSocket — not
  through the Next.js server. Routing 30 frames/second through an extra server
  hop would blow the latency budget.

- Per-frame cell data **never becomes React state**. The 3D viewer is a raw
  `<canvas>` driven by `requestAnimationFrame`. Putting 50,000 cells into React
  state would cause React to re-render 30 times per second for no reason.

- **Three.js** is used directly (imperatively), not through `react-three-fiber`.
  Same reasoning — avoiding React overhead in the hot rendering path.

---

## Part 8 — The Wire Protocol (how backend talks to frontend)

Every 33 ms the backend sends a **FrameMessage** over WebSocket. It is a binary
message: a JSON header (describing what follows) then raw typed arrays (the
actual cell data).

The browser reads cell data straight into `Float32Array` / `Uint8Array` with no
parsing per cell — it's like loading a binary file directly into GPU memory.

The message carries:
- Cell data: ring, bin, heights, class, flags for every occupied cell
- Tracks: position, velocity, predicted trajectory for each moving object
- Decision: selected route, alternative, risk level, ETA, reason string
- Stats: FPS, latency breakdown, memory usage, reduction factor

---

## Part 9 — The Benchmark

Reproducibility is a hard requirement. Judges must be able to re-run everything
and get the same numbers. `make bench` generates `results.json` and then renders
it as `docs/RESULTS.md`. No number goes into a slide unless it came from that
file.

**Current measured results (Sequence 04, 271 scans):**

| Metric | Value |
|---|---|
| Total cells (AVR-25D) | 705,771 |
| Total cells (uniform 5 cm) | 16,000,000 |
| Cell reduction | **22.67×** |
| Memory (AVR-25D dense) | 17.64 MB |
| Memory (uniform 5 cm) | 400.0 MB |
| End-to-end latency (median) | 5.3 ms (network) / 63.8 ms (geometric) |
| Network mIoU | 0.845 |
| Geometric mIoU | 0.291 |
| Object recall (network) | 0.914 |

The 60–100 m accuracy bin is blank — not because the system fails there, but
because SemanticKITTI simply doesn't annotate points beyond 60 m, so there's
nothing to be right or wrong about.

---

## Part 10 — What Exists vs What Doesn't Yet

### Done (Sameer's track — all in `model/avr25d/`)

| Module | What it does |
|---|---|
| `config.yaml` / `config.py` | All tunable parameters, centrally managed |
| `io/kitti.py` | Reads real LiDAR scan files and their labels |
| `perception/labelmap.py` | Maps 19 SemanticKITTI classes to 5 AVR classes |
| `perception/geometric_seg.py` | RANSAC + clustering fallback segmenter |
| `perception/range_proj.py` | Projects 3D points to/from the 64×2048 image |
| `perception/onnx_infer.py` | Runs the neural network on CPU |
| `perception/cache.py` | Pre-computed label cache (avoids re-running the model) |
| `synth/` | Synthetic scene generator (ray-caster + 5 hazard scenes) |
| `bench/baselines.py` | Memory models for comparison baselines |
| `bench/latency.py` | Per-stage timing measurement |
| `bench/distance_bins.py` | Accuracy broken down by distance range |
| `bench/report.py` | Renders `results.json` → `docs/RESULTS.md` |

### NOT Done yet (your track — `model/avr25d/core/` and `model/avr25d/server/`)

This is the work that is **blocked on you (Anuj)**. Sameer has been waiting
for these since Day 1:

| Module | What it does | Why it's critical |
|---|---|---|
| `server/protocol.py` | Defines the binary FrameMessage format | **Blocks all 4 other people** |
| `server/fixtures.py` | Emits fake-but-valid frames for frontend testing | Blocks Shubham and Navya |
| `core/grid.py` | The ring-sector grid math | Blocks the whole pipeline |
| `core/cell.py` | The per-cell data accumulation and hazard analysis | Blocks hazard detection |
| `core/refine.py` | Subdivides cells near moving objects | Blocks the differentiator feature |
| `server/app.py` | FastAPI server that runs the pipeline and streams frames | Blocks end-to-end |
| `decision/costmap.py` | Converts polar map to Cartesian for A* | Blocked by cell.py |
| `decision/planner.py` | A* route planning | Blocked by costmap |
| `decision/explain.py` | Generates the reason string | Blocked by planner |

### NOT Done (frontend — Shubham and Navya)

The frontend is still the default Next.js starter page. Nothing has been built
yet because `protocol.py` and `fixtures.py` don't exist.

### NOT Done (hardware — Khanak and Veda)

The companion drone LiDAR payload design (MATLAB/Simulink). Independent
workstream — doesn't affect the software.

---

## Part 11 — What You (Anuj) Need to Build

According to the plan, your first priority right now is:

### Priority 1: `server/protocol.py` and `server/fixtures.py`

These were supposed to land on Day 1. Everything frontend is blocked on them.
Once these exist, Shubham and Navya can build the entire dashboard independently
while you build the grid engine.

`protocol.py` defines the FrameMessage binary format (see §5.2 in
IMPLEMENTATION_PLAN.md for the exact schema).

`fixtures.py` generates synthetic-but-schema-valid frames that look like real
pipeline output, with no dependency on `core/` or `perception/`. The frontend
can render, animate and test against this while the real backend is being built.

### Priority 2: `core/grid.py`

The `RingGrid` class. Key things to implement:
- Build the 662-ring table at startup (one-time cost)
- `ring_of(r)` — closed-form, vectorised (no Python loop)
- `cell_of(x, y)` — returns cell_id and valid_mask
- `cell_centres(cell_id)` — inverse, for the renderer
- `cell_extents(cell_id)` — for correctly-sized render instances

Target: 662 rings, 705,771 total cells.

### Priority 3: `core/cell.py`

The `CellGrid` class. Key things:
- Allocate all SoA arrays once at startup, reuse every frame (no per-frame allocation)
- `accumulate(xyz, intensity, labels)` — scatter points into cells using `np.add.at`
- `analyse(cfg)` — compute slope, roughness, set OVERHANG/POTHOLE/STEP flags

Once this exists: Sameer can write `traversability.py` and `tracker.py`, and the
hazard benchmark can run.

---

## Part 12 — Key Numbers to Know

These are the headline numbers for the demo. You should be able to say them
from memory:

| What | Number |
|---|---|
| LiDAR points per scan | ~120,000 |
| Sensor rate | 10 Hz |
| Target latency | ≤ 33 ms (30 FPS) |
| Near-field cell size | 5 cm (within 10 m) |
| Far-field cell size | 50 cm (at 100 m) |
| Total rings | 662 |
| Total cells (AVR-25D) | 705,771 |
| Total cells (uniform 5 cm) | 16,000,000 |
| Cell reduction factor | **22.67×** |
| Memory (AVR-25D) | 17.64 MB |
| Memory (uniform) | 400.0 MB |
| Network accuracy (mIoU) | 0.845 |
| Network end-to-end latency | 5.3 ms (cached mode) |
| SIH internal deadline | **10 September 2026** |

---

## Part 13 — The Team

| Person | What they own |
|---|---|
| **Sameer** | Perception (neural net + geometric), benchmarking, synthetic scenes, integration lead |
| **Anuj (you)** | Grid engine (`core/`), FastAPI server, decision planner |
| **Shubham** | Three.js 3D viewer — everything inside the canvas |
| **Navya** | Next.js platform — auth (Firebase), database (MongoDB), HUD |
| **Khanak** | Drone LiDAR payload hardware design & modeling (MATLAB) |
| **Veda** | Drone LiDAR payload co-design & documentation, deck, video, submission |

---

## Part 14 — Glossary

| Term | Plain meaning |
|---|---|
| LiDAR | Laser-based 3D scanner. Fires pulses, times the reflections |
| Point cloud | The set of ~120,000 (x, y, z) points from one LiDAR scan |
| 2.5D | A top-down grid where each cell stores height, not just occupancy |
| mIoU | Mean Intersection over Union. Accuracy metric for segmentation. 1.0 = perfect, 0.0 = random |
| RANSAC | Algorithm that fits a shape (like a plane) to noisy data by finding the version most points agree with |
| Kalman filter | A standard algorithm for tracking moving objects and predicting where they'll be next |
| A* | A standard path-finding algorithm. Finds the lowest-cost route through a grid |
| SoA | Struct-of-Arrays. Storing all x-values together, all y-values together, etc. — faster for vectorised operations |
| ONNX | Open format for neural network models. Lets you run a PyTorch model without PyTorch installed |
| FastAPI | Python web framework used for the backend server |
| Next.js | React framework used for the web dashboard |
| WebSocket | A persistent two-way connection between browser and server — used to stream frames at 30 Hz |
| Three.js | JavaScript library for 3D rendering in the browser |
| SemanticKITTI | Real-world LiDAR dataset used for training and evaluation. Recorded in Germany |
| DRDO | Defence Research and Development Organisation — the organisation that set this problem |
| SIH | Smart India Hackathon |
