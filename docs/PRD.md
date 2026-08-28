# Product Requirements Document — AVR-25D

**Adaptive Variable-Resolution 2.5D LiDAR Mapping for Dynamic Environment Perception**

| Field | Value |
|---|---|
| Problem Statement | SIH26053 |
| Organisation | DRDO — Department of Defence Production / IDEX |
| Theme | Transportation & Logistics |
| Category | Software |
| SIH portal deadline | 20 September 2026 |
| Internal hackathon submission | **10 September 2026** (PPT + video + prototype + live demo) |
| Document date | 28 August 2026 |
| Status | Approved for build |
| Revision | 28 Aug 2026 — internal deadline moved 3 Sept → **10 Sept**; schedule rebuilt as 14 days, four Phase 2 items pulled forward (§12.1) |
| Working name | `AVR-25D` — placeholder, rename with one find/replace |

---

## 1. Context

Autonomous and semi-autonomous logistics vehicles perceive the world through 3D LiDAR. A
64-beam sensor produces roughly 120,000 points per revolution at 10 Hz — about 1.2 million
points per second. Two established ways of consuming that stream both fail:

- **Keep the full 3D point cloud / voxel grid.** Rich, but processing millions of points per
  second is a computational and memory-bandwidth bottleneck. On the embedded compute a
  logistics vehicle actually carries, it does not close the loop in real time.
- **Flatten to a 2D occupancy grid.** Cheap, but height is discarded. A curb, a pothole and
  a low gantry all collapse into the same "occupied" or "free" cell. A 2D map cannot tell a
  vehicle that the ground is drivable but the bridge above it is 3.1 m and the vehicle is
  3.4 m.

The PS proposes the resolution: a **foveated** map, in the sense of human vision. The retina
spends its photoreceptor budget where the eye is looking and coarsens rapidly toward the
periphery, and that is why a human can read text and still notice motion at the edge of
vision on a fixed neural budget. Applied to LiDAR: render the immediate vicinity in high
detail because that is where a braking decision is made in the next 300 ms, and simplify
distant regions, where the sensor's own angular sampling means detail was never measured in
the first place.

AVR-25D implements that idea as a **2.5D map** — a plan-view grid where each cell carries
elevation and semantic layers rather than a single occupancy bit — over a **non-uniform,
distance-dependent grid** whose cell size grows with range.

### 1.1 Why this is a Transportation & Logistics submission

The map is not the product; the decision is. A logistics vehicle — a yard truck, a
warehouse-to-dock shuttle, a convoy support vehicle on unimproved road — needs to answer
three questions continuously: *can I drive over this surface*, *will something moving get in
my way*, and *what route should I take*. AVR-25D produces a representation shaped for
exactly those three questions and then answers them with a deterministic decision layer that
emits a route, a risk level, an ETA, and a human-readable reason.

---

## 2. Problem statement traceability

Every requirement in this document traces to a clause of the PS. The clauses, quoted:

| ID | PS clause (verbatim) |
|---|---|
| **PS-1** | "Distinguish between drivable surfaces and non-drivable terrain." |
| **PS-2** | "Identify and classify static obstacles (walls, poles) and dynamic objects (pedestrians, other vehicles)." |
| **PS-3** | "Implement a non-uniform grid where the cell size increases as the distance from the sensor increases." |
| **PS-4** | "This requires a sophisticated data structure that can handle variable resolution without causing alignment errors or data loss during the projection from 3D to 2.5D." |
| **PS-5** | "A network (e.g., PointNet++ or a Sparse Convolutional Neural Network) capable of semantic segmentation of point clouds into terrain, static obstacles, and moving objects." |
| **PS-6** | "An algorithm that projects classified 3D points into a 2.5D grid where the resolution is high (e.g., 5cm cells) within a 10m radius and decreases (e.g., 50cm cells) up to a 100m radius." |
| **PS-7** | "A dashboard showing the 2.5D map with distinct color-coding for terrain and objects" |
| **PS-8** | "demonstrating a significant reduction in memory usage compared to a uniform high-resolution 3D map." |
| **PS-9** | "Evidence of low latency (high FPS) and high accuracy in object classification across varying distances." |
| **PS-10** | Background: "detecting curbs, potholes, or overhanging obstacles" — the failure modes of 2D grids that motivate 2.5D. |

Section 7 maps every functional requirement back to these IDs. Section 15 checks the reverse
direction: every PS ID is covered by at least one requirement.

---

## 3. Goals and non-goals

### 3.1 Goals

- **G1** — Transform a raw LiDAR scan into a semantically labelled, variable-resolution 2.5D
  map in real time on commodity CPU hardware.
- **G2** — Make the projection provably lossless in the point-assignment sense: every input
  point lands in exactly one cell, verified per frame.
- **G3** — Preserve the three hazard classes a 2D grid destroys: curbs (step), potholes
  (negative obstacle), overhangs (clearance).
- **G4** — Demonstrate, with measured numbers, a large reduction in cell count and memory
  versus uniform high-resolution baselines, and show that far-field accuracy does not
  collapse as a result.
- **G5** — Convert the map into an explainable transportation decision: route, risk, ETA and
  a stated reason.
- **G6** — Ship a live, running demo by 10 September 2026.

### 3.2 Non-goals

Recorded here so they are not re-litigated mid-sprint.

- **NG1** — Not a SLAM system. Single-scan, ego-centric mapping. No loop closure, no global
  map, no pose graph. Multi-scan temporal accumulation is Phase 2 and optional.
- **NG2** — Not a new segmentation architecture. We use an established range-image network.
  The contribution is the representation and what is done with it.
- **NG3** — Not a vehicle controller. The decision layer outputs advisory routes, not
  actuation commands. No control loop, no safety certification claim.
- **NG4** — No ROS, no C++ rewrite, no MATLAB/Simulink in the runtime path. MATLAB appears
  only as an offline scenario-generation tool (§9.3).
- **NG5** — No LLM anywhere in the decision path. The decision layer is deterministic and
  reproducible; the same input frame always produces the same route and the same reason
  string. This is a requirement, not a limitation — a DRDO evaluator can re-run it.
- **NG6** — Not multi-vehicle. Single ego vehicle. Fleet-level logistics optimisation is out.

---

## 4. Users and operating context

| Persona | Need | What AVR-25D gives them |
|---|---|---|
| **Autonomy stack integrator** | A perception layer that fits in a fixed compute and memory budget on vehicle hardware | A map with a bounded, known, pre-allocated memory footprint and O(1) cell access |
| **Fleet / yard operations supervisor** | To know why a vehicle stopped or rerouted | An explanation string and a risk score per decision, logged per frame |
| **Safety engineer** | Evidence that hazards are not silently dropped by compression | Distance-binned accuracy tables and hazard-preservation tests against exact synthetic ground truth |
| **SIH / DRDO evaluator** | Evidence that each PS clause is met | Clause-to-requirement-to-test traceability (§2, §7, §15) and a live dashboard showing measured numbers |

**Operating envelope.** Ground vehicle, ego-centric, 360° × 100 m, 10 Hz sensor, flat to
moderately sloped terrain (highway, yard, unimproved road). Not designed for aerial, marine
or steep off-road terrain where a 2.5D height-field assumption breaks (§13, A-4).

---

## 5. System overview

```
  LiDAR scan (~120k points)              [ KITTI subset | MATLAB synthetic scenes ]
            │
            ▼
  ┌───────────────────────────┐
  │ 1. PERCEPTION             │   range-image 2D CNN (ONNX, CPU)
  │    per-point class label  │   + geometric fallback segmenter
  └───────────┬───────────────┘   19 SemanticKITTI classes → 5 PS classes
              │
              ▼
  ┌───────────────────────────┐
  │ 2. RING-SECTOR PROJECTION │   (x,y,z) → (r,θ) → (ring k, bin j) → flat id
  │    variable-resolution    │   5 cm @ ≤10 m  →  50 cm @ 100 m
  │    2.5D cell accumulation │   closed-form O(1) index, no resampling
  └───────────┬───────────────┘
              │
              ▼
  ┌───────────────────────────┐
  │ 3. CELL ANALYSIS          │   z_ground / z_obstacle / z_min / slope /
  │    + hazard flagging      │   roughness / clearance
  │    + local refinement     │   OVERHANG · NEGATIVE_OBSTACLE · STEP · VOID
  └───────────┬───────────────┘
              │
              ▼
  ┌───────────────────────────┐
  │ 4. DECISION LAYER         │   traversability · Kalman tracker ·
  │    deterministic          │   Cartesian costmap · A* · explanation
  └───────────┬───────────────┘
              │  FrameMessage (WebSocket, binary)
              ▼
  ┌───────────────────────────┐
  │ 5. DASHBOARD (Three.js)   │   4 views · ring overlay · live HUD
  └───────────────────────────┘

  ┌───────────────────────────┐
  │ 6. BENCHMARK HARNESS      │   memory · latency · distance-binned mIoU ·
  │    (offline, reproducible)│   hazard preservation · baseline comparison
  └───────────────────────────┘
```

---

## 6. Data contract

Frozen on Day 1. Changing anything in this section after Day 1 requires the integration
lead's sign-off, because four people code against it in parallel.

### 6.1 Semantic class taxonomy

The PS asks for three distinctions: drivable vs non-drivable terrain, static obstacles,
dynamic objects. We use exactly five classes — the three plus a terrain split and a void
class. Collapsing SemanticKITTI's 19 classes to 5 raises per-class accuracy, shrinks the
model, and maps 1:1 onto the PS.

| ID | Class | Colour (dashboard) | Merged from SemanticKITTI learning IDs | PS trace |
|---:|---|---|---|---|
| 0 | `VOID` | `#3a3a42` grey | unlabeled, outlier | PS-4 |
| 1 | `DRIVABLE` | `#2e7d32` green | road, parking, lane-marking | PS-1 |
| 2 | `NON_DRIVABLE_TERRAIN` | `#f9a825` amber | sidewalk, other-ground, terrain, vegetation | PS-1 |
| 3 | `STATIC_OBSTACLE` | `#c62828` red | building, fence, pole, traffic-sign, trunk, other-structure, other-object | PS-2 |
| 4 | `DYNAMIC_OBJECT` | `#1565c0` blue | car, bicycle, motorcycle, truck, other-vehicle, person, bicyclist, motorcyclist, and all `moving-*` IDs | PS-2 |

SemanticKITTI separates `moving-car` (252), `moving-person` (254), `moving-truck` (257) and
similar from their static counterparts. We exploit this: a parked car and a moving car both
land in `DYNAMIC_OBJECT` for classification, but the `moving-*` origin sets a
`MOVING` bit on the cell, which the tracker uses to seed candidates. This is free supervision
we would otherwise have to infer.

Colour choices are checked for deuteranopia/protanopia separation; the red/green pair is
disambiguated by luminance and by the elevation shading in the 3D view, not by hue alone.

### 6.2 Cell schema

Struct-of-arrays, one parallel NumPy array per field. Struct-of-arrays rather than
array-of-structs because every downstream operation is a vectorised sweep over one or two
fields, and SoA keeps those sweeps contiguous.

| Field | dtype | Bytes | Meaning |
|---|---|---:|---|
| `z_ground` | `float32` | 4 | Estimated traversable surface height. Robust low quantile of the cell's ground-classified returns. |
| `z_obstacle` | `float32` | 4 | Maximum height of non-ground returns in the cell. |
| `z_min` | `float32` | 4 | Minimum return height. Drives negative-obstacle detection. |
| `roughness` | `float32` | 4 | Variance of z among ground-classified returns, σ²_z. |
| `slope` | `float32` | 4 | Local gradient magnitude of `z_ground`, computed across ring neighbours. |
| `class_id` | `uint8` | 1 | Argmax of the cell's class histogram (§6.1). |
| `confidence` | `uint8` | 1 | 0–255. Fused from point count, mean per-point softmax margin, and temporal agreement. |
| `flags` | `uint8` | 1 | Bitfield (§6.3). |
| `count` | `uint16` | 2 | Number of points that landed in the cell, saturating at 65535. |
| **Total** | | **25** | per cell, SoA, no padding |

Dynamic cells additionally carry `vx, vy` as `float16` in a **sparse side table** keyed by
cell id, not in the dense arrays — motion applies to a small fraction of cells, and paying
4 bytes × 705,771 for it would be a 2.8 MB tax on a field that is almost always zero.

### 6.3 Flag bitfield

| Bit | Name | Set when |
|---:|---|---|
| 0 | `OCCUPIED` | `count > 0` |
| 1 | `VOID_UNOBSERVED` | `count == 0` and the cell is inside the sensor's field of view — i.e. genuinely unobserved, not merely out of range |
| 2 | `OVERHANG` | `class_id == DRIVABLE` and `0 < (z_obstacle − z_ground) < H_vehicle` |
| 3 | `NEGATIVE_OBSTACLE` | `z_ground − median(z_ground over ring neighbourhood) < −τ_pothole` |
| 4 | `STEP` | `max |Δz_ground|` to a 4-neighbour exceeds `τ_step` — curb detection |
| 5 | `MOVING` | Any contributing point carried a SemanticKITTI `moving-*` label, or the tracker associated the cell with a track whose speed exceeds `v_min` |
| 6 | `REFINED` | Cell has been subdivided by the local-refinement pass (§7.4) |
| 7 | `LOW_CONFIDENCE` | `confidence < τ_conf` |

`OVERHANG` and `NEGATIVE_OBSTACLE` are the two flags that exist purely because the map is
2.5D. A 2D occupancy grid cannot represent either. They are the headline demo (§10.4).

---

## 7. Functional requirements

Each requirement carries the PS clause it satisfies and the acceptance test that proves it.
Test IDs are defined in `IMPLEMENTATION_PLAN.md` §9.

### 7.1 Perception

| ID | Requirement | PS | Test |
|---|---|---|---|
| **FR-1** | The system shall assign one of the five §6.1 classes to every point in an input scan. | PS-5 | T-P1 |
| **FR-2** | Segmentation shall be performed by a deep neural network operating on a spherical range-image projection of the point cloud (64 × 2048 × 6 channels: range, x, y, z, intensity, validity mask). | PS-5 | T-P2 |
| **FR-3** | The network shall run to completion on CPU only, on both macOS (arm64) and Windows (x86-64), with no CUDA dependency and no compiled sparse-convolution extension. | NFR-4 | T-P3 |
| **FR-4** | Labels shall be reprojected from the range image back to the full 3D point set using k-NN range-aware post-processing, so that points occluded in the projection still receive a label. | PS-4 | T-P4 |
| **FR-5** | The system shall provide a geometric fallback segmenter (RANSAC ground-plane fit, Euclidean clustering, bounding-box aspect classification) selectable at runtime, producing the same five classes. | Risk R-2 | T-P5 |
| **FR-6** | Perception shall be selectable between `live` (network inference this frame) and `cached` (precomputed per-scan label file). The active mode shall be displayed on the dashboard HUD at all times. | PS-9 | T-P6 |

**On FR-6.** The team has no reliable CUDA GPU. Running a segmentation network live on CPU
will not sustain 30 FPS, and pretending otherwise in front of DRDO evaluators would be both
dishonest and trivially caught. Instead: perception is an explicitly decoupled stage. The
demo runs the mapping engine, decision layer and dashboard live at full rate against a label
cache, while live single-frame inference latency is measured, reported as its own number,
and shown on the HUD. The claim we make is precise — *the mapping and decision pipeline runs
at N FPS on CPU; segmentation adds M ms per frame on this CPU and would add far less on the
target embedded GPU* — and every part of it is measured. No projected number ever appears
without the word "projected" next to it.

### 7.2 Variable-resolution grid engine

| ID | Requirement | PS | Test |
|---|---|---|---|
| **FR-7** | The grid shall be a ring-sector polar structure over 360° × 100 m, with radial cell size `s(r) = 0.05 m` for `r ≤ 10 m` and `s(r) = min(0.005·r, 0.50 m)` for `r > 10 m`. | PS-3, PS-6 | T-G1 |
| **FR-8** | Angular bins per ring shall be `N_k = round(2π·r_k / s(r_k))`, making each cell approximately square (isotropic) at every range. | PS-3 | T-G2 |
| **FR-9** | Mapping a point to its cell shall be closed-form and O(1): `k = floor(r/0.05)` for `r ≤ 10 m`, `k = 200 + floor(ln(r/10)/ln(1.005))` for `r > 10 m`; `j = floor(θ/(2π)·N_k)`; flat id `= offset[k] + j` with `offset` a precomputed 662-entry prefix sum. No search, no hashing, no iteration. | PS-4 | T-G3 |
| **FR-10** | Every point within the 100 m envelope shall map to exactly one cell. The invariant `Σ cell.count == n_points_in_envelope` shall be asserted every frame, and a violation shall fail loudly rather than degrade silently. | PS-4 | T-G4 |
| **FR-11** | The engine shall populate all §6.2 cell fields in a single vectorised pass over the point array, with no Python-level per-point loop. | NFR-1 | T-G5 |
| **FR-12** | The ring table shall be allocated once at startup and reused for every frame, giving a fixed, known memory footprint with no per-frame allocation or garbage-collection pressure. | NFR-2 | T-G6 |

### 7.3 Hazard preservation

| ID | Requirement | PS | Test |
|---|---|---|---|
| **FR-13** | The system shall compute `clearance = z_obstacle − z_ground` per cell and set `OVERHANG` where a drivable cell has clearance below the configured vehicle height, keeping the ground traversable while flagging the overhead constraint separately. | PS-10 | T-H1 |
| **FR-14** | The system shall detect negative obstacles (potholes) by comparing a cell's `z_ground` against the median of its ring neighbourhood and setting `NEGATIVE_OBSTACLE` below threshold. | PS-10 | T-H2 |
| **FR-15** | The system shall detect step discontinuities (curbs) from the maximum `z_ground` difference to 4-neighbours and set `STEP`. | PS-10 | T-H3 |
| **FR-16** | Hazard detection shall be validated against synthetic scenes with exact ground truth (§9.3), reporting detection rate and geometric error in metres — not merely "the hazard is visible in the render". | PS-10 | T-H4 |

### 7.4 Local refinement

| ID | Requirement | PS | Test |
|---|---|---|---|
| **FR-17** | Beyond 10 m, cells flagged `MOVING`, or whose roughness or slope exceeds threshold, shall be subdivided 2×2 into sub-cells held in an overlay hash map alongside the dense ring table. | — | T-R1 |
| **FR-18** | Refinement shall be bounded: at most `N_refine_max` cells per frame (default 4096), so worst-case memory and latency stay bounded regardless of scene content. | NFR-1 | T-R2 |

**Rationale.** Distance-only foveation is what the PS asks for and FR-7 delivers it. FR-17 is
the differentiator: resolution becomes a function of distance *and* scene content, so a
distant truck is resolved finely while the distant empty road beside it stays coarse. The
bound in FR-18 is what keeps this from being a latency hazard — an adversarial scene cannot
make the refinement pass unbounded.

### 7.5 Decision layer

| ID | Requirement | PS | Test |
|---|---|---|---|
| **FR-19** | A traversability score in [0,1] shall be computed per cell from slope, roughness, step height, semantic class, clearance and confidence, with published weights. | PS-1 | T-D1 |
| **FR-20** | Dynamic objects shall be clustered from `DYNAMIC_OBJECT` cells and tracked frame-to-frame with a constant-velocity Kalman filter (state `[x, y, vx, vy]`), with nearest-neighbour gating for association. | PS-2 | T-D2 |
| **FR-21** | The polar map shall be resampled into a 40 m × 40 m ego-front Cartesian costmap at 0.25 m (160 × 160) for planning. | — | T-D3 |
| **FR-22** | An A* planner shall produce a primary and one alternative route over the costmap, minimising `C = w₁·distance + w₂·slope + w₃·roughness + w₄·obstacle_risk + w₅·clearance_risk` with published weights. | — | T-D4 |
| **FR-23** | The system shall emit a decision record per frame: selected route, alternative, risk level, ETA, and a deterministic template-filled reason string naming the specific factor that drove the choice. | — | T-D5 |
| **FR-24** | The decision layer shall contain no stochastic component. Re-running the pipeline on the same recorded scan sequence shall produce byte-identical decision records. | NG-5 | T-D6 |

### 7.6 Dashboard

| ID | Requirement | PS | Test |
|---|---|---|---|
| **FR-25** | The dashboard shall render four views over the same frame: (1) raw point cloud, (2) uniform 5 cm 2.5D grid, (3) AVR-25D adaptive 2.5D grid, (4) decision layer with routes, tracks and risk. | PS-7 | T-V1 |
| **FR-26** | Cells shall be colour-coded by semantic class per §6.1, with a toggle to shade by elevation instead. | PS-7 | T-V2 |
| **FR-27** | A ring overlay toggle shall draw the ring boundaries so the variable resolution is directly visible, not merely asserted. | PS-3 | T-V3 |
| **FR-28** | A live HUD shall display: FPS, per-stage latency (perception / projection / analysis / decision / serialise), total latency, occupied cell count, AVR-25D memory, baseline memory, reduction factor, active perception mode, and frame index. | PS-8, PS-9 | T-V4 |
| **FR-29** | Views 2 and 3 shall be presentable side-by-side and as an A/B wipe over the same scan, so the memory and cell-count difference is visually attributable to the representation and not to a different frame. | PS-8 | T-V5 |
| **FR-30** | The dashboard shall sustain interactive frame rates with up to 100,000 rendered cells, using instanced rendering. | NFR-1 | T-V6 |

### 7.7 Benchmarking

| ID | Requirement | PS | Test |
|---|---|---|---|
| **FR-31** | The harness shall measure memory for AVR-25D and for four baselines (§8.2) on identical scans, reporting both cell counts and bytes. | PS-8 | T-B1 |
| **FR-32** | The harness shall measure per-stage and end-to-end latency over ≥200 scans, reporting mean, median, p95 and worst case — not just the mean. | PS-9 | T-B2 |
| **FR-33** | The harness shall report mIoU and per-class IoU overall **and binned by range**: 0–10 m, 10–30 m, 30–60 m, 60–100 m. | PS-9 | T-B3 |
| **FR-34** | The harness shall report object recall by range bin and by object class. | PS-9 | T-B4 |
| **FR-35** | All benchmark output shall be written to a machine-readable `results.json` plus a rendered Markdown table, regenerable by one command, so no number reaches a slide by hand-copy. | — | T-B5 |

---

## 8. Non-functional requirements

| ID | Requirement | Rationale |
|---|---|---|
| **NFR-1** | End-to-end mapping + decision + serialisation latency ≤ 33 ms per frame (≥30 FPS) on a 2020-or-later laptop CPU, excluding live network inference. | PS-9. The 10 Hz sensor rate is the real bar; 30 FPS gives 3× headroom. |
| **NFR-2** | Steady-state memory bounded and pre-allocated. No per-frame heap allocation in the mapping hot path. | An autonomy stack cannot tolerate GC pauses at 10 Hz. |
| **NFR-3** | Pure Python + NumPy core. Optional Numba acceleration behind a feature flag, with a NumPy path that always works if Numba is absent. | Numba compile failures on one team member's machine must not block the team. |
| **NFR-4** | Runs on macOS (arm64) and Windows (x86-64) from the same source tree, CPU-only. No CUDA, no `spconv`, no `torchsparse`, no platform-specific build step. | The team has a Mac and a Windows box with an uncertain GPU. Cross-platform build failure is the single most likely way to lose two days. |
| **NFR-5** | Reproducible: fixed seeds, pinned dependency versions, a single `make bench` that regenerates every number in the deck. | An evaluator who cannot re-run it will not believe it. |
| **NFR-6** | Cold start to first rendered frame ≤ 15 s, so a live demo does not stall in front of judges. | |
| **NFR-7** | Every configurable threshold (`τ_pothole`, `τ_step`, `H_vehicle`, cost weights, refinement bounds) lives in one `config.yaml` with documented defaults and units. No magic numbers in code. | Judges ask "where did 0.15 come from?" |
| **NFR-8** | The dashboard shall run against `fixtures.py` with the backend entirely absent. | Unblocks two frontend developers from Day 1. |

---

## 9. Data

### 9.1 SemanticKITTI subset

Real-world evaluation data. Full dataset is ~80 GB; we take a subset.

- **Sequence 04** (271 scans) — small, quick to download, good for the pipeline smoke test.
- **Sequence 00** first 400 scans — urban, dense, many static obstacles and parked vehicles.
- **Sequence 05** first 300 scans — contains moving traffic, needed for tracker evaluation.

Target ~1000 scans, roughly 12 GB with labels. Download begins Day 1, hour 1, because it is
the longest-lead item on the critical path and it is bandwidth-bound, not effort-bound.

Used for: segmentation accuracy including distance-binned mIoU, memory baselines on realistic
point distributions, latency measurement on realistic point counts, object recall.

### 9.2 What KITTI cannot give us

SemanticKITTI has no pothole class, no annotated overhanging structures with known clearance,
and no ground-truth geometry for curbs. It cannot support a quantitative claim about hazard
preservation — only a qualitative "look, it appears in the render". Since hazard preservation
is the core justification for 2.5D over 2D (PS-10), a qualitative claim is not enough.

### 9.3 Synthetic scenes with exact ground truth

Generated in base-language MATLAB (§ `WORK_DISTRIBUTION.md`, Khanak). A scripted spherical
ray-caster intersects 64 beams × 1800 azimuths against analytic primitives — planes, boxes,
cylinders — and writes KITTI-format `.bin` (float32 x, y, z, intensity) and `.label` files.

Because the scene is analytic, ground truth is **exact and free**: we know the pothole is
0.22 m deep and 1.4 m across, and the gantry clearance is 3.10 m, to machine precision. That
converts hazard preservation from a demo into a measurement with an error in metres.

| Scene | Content | Measures |
|---|---|---|
| `S1_flat_road` | Flat road, no hazards | Control. Ground-plane RMS error; false-positive hazard rate |
| `S2_pothole` | 1.4 m × 0.22 m depression at 12 m | Negative-obstacle detection rate; depth error |
| `S3_overhang` | Gantry, 3.10 m clearance, drivable road beneath | Clearance error; that the ground beneath stays `DRIVABLE` |
| `S4_curb` | 0.15 m kerb along the road edge | Step detection rate; height error |
| `S5_crossing_truck` | 40-frame sequence, truck crossing at 8 m/s | Tracking, velocity error, reroute trigger |

**Toolchain.** All `.m` files are written in base MATLAB language only — no Automated Driving
Toolbox, no Lidar Toolbox, no toolbox functions at all. This means the identical files run
unmodified in **GNU Octave**, which is free and installs in minutes. MATLAB Online's free
tier is the primary environment; Octave is the zero-cost fallback and the CI environment.
This choice is deliberate: it removes licensing from the critical path entirely while keeping
the MATLAB-based validation story that a DRDO evaluator will recognise.

---

## 10. Metrics and measurement protocol

Definitions are given precisely because "we reduced memory by 20×" means nothing without
saying against what and counted how.

### 10.1 Memory

Let `n_occ` be occupied cells in a frame and `B = 25` bytes per cell (§6.2).

| Baseline | Definition | Bytes |
|---|---|---|
| **B0 — raw scan** | Input point cloud, float32 x/y/z/intensity + uint8 label | `n_pts × 17` |
| **B1 — dense uniform 2.5D @ 5 cm** | Cartesian grid over the 200 m × 200 m footprint that circumscribes the 100 m envelope | `16,000,000 × 25 = 400.0 MB` |
| **B2 — sparse uniform 2.5D @ 5 cm** | Hash map, occupied cells only, 4-byte key | `n_occ_uniform × (25 + 4)` |
| **B3 — dense uniform 3D voxel @ 5 cm** | 200 × 200 × 10 m at 1 byte/voxel | `3.2 × 10⁹ B = 3.20 GB` |
| **B4 — sparse 3D voxel hash @ 5 cm** | Occupied voxels only, 8-byte key + 4-byte payload | `n_vox_occ × 12` |
| **AVR-25D dense** | Pre-allocated ring table, all 705,771 cells | `705,771 × 25 = 17.64 MB` |
| **AVR-25D occupied** | Occupied cells only | `n_occ_adaptive × 29` |

**Where we win, and where we do not — stated up front.** Against dense baselines the win is
decisive and structural: **22.67× fewer cells** than B1 for identical coverage, and the
comparison against B3 is larger still. Against a well-implemented *sparse* baseline (B2, B4),
raw byte count is closer, and on a single sparse scan B4 can be smaller than our dense ring
table. We say so, and the argument stands anyway on three grounds:

1. **Occupied-cell count.** Far-field points that occupy many distinct 5 cm cells merge into
   one adaptive cell. `n_occ_adaptive < n_occ_uniform` is a measured, reportable fact.
2. **Access cost.** Our lookup is `offset[k] + j` — a prefix-sum add on a contiguous array.
   A hash map costs a hash, a probe, and a cache miss, with no worst-case bound. For a 10 Hz
   real-time loop, deterministic O(1) beats amortised O(1).
3. **Downstream compute.** Planning, traversability, rendering and any downstream convolution
   all iterate over cells. A 22.67× cell reduction is a 22.67× reduction in downstream work,
   which sparsity alone does not give you.

This is exactly the objection a DRDO evaluator will raise, and having the answer prepared is
worth more than a bigger unqualified number.

### 10.2 Latency and throughput

Per-stage wall-clock, `time.perf_counter`, over ≥200 consecutive scans, discarding the first
10 as warm-up. Report **mean, median, p95, max** — a real-time claim rests on the tail, not
the mean. Stages: `t_perception`, `t_projection`, `t_analysis`, `t_refine`, `t_decision`,
`t_serialise`. FPS is `1000 / t_total_median_ms`.

### 10.3 Accuracy

Per-point mIoU over the five classes against SemanticKITTI ground truth, `IoU_c = TP_c /
(TP_c + FP_c + FN_c)`, mIoU the unweighted mean over classes present in the bin.

**Distance-binned** into 0–10, 10–30, 30–60, 60–100 m by point range. This is the metric that
directly tests the central trade-off — whether far-field coarsening costs useful perception —
and PS-9 asks for it explicitly ("across varying distances"). We report alongside it the mean
point count per bin, because a low far-field mIoU caused by 40 points in a bin is a different
finding from one caused by the representation.

We also report **cell-level** accuracy: the fraction of occupied cells whose `class_id` matches
the majority ground-truth class of the points inside it. This is the number that matters for
the map, as distinct from FR-1's per-point number.

### 10.4 Hazard preservation

Against §9.3 synthetic ground truth:

- **Detection rate** — fraction of frames in which the hazard cell set overlaps ground truth.
- **Geometric error** — |measured − true| in metres for pothole depth, gantry clearance, curb height.
- **False-positive rate** — hazard flags raised on `S1_flat_road`, which has none.
- **2D-grid counterfactual** — the same scenes through a plain 2D occupancy grid, showing what
  is lost. This is the direct evidence for PS-10 and it belongs in the deck.

### 10.5 Projection integrity

`Σ cell.count == n_points_in_envelope`, asserted every frame. Reported as a percentage over
the whole benchmark run. The target is 100.000% and anything else is a defect, not a metric
(FR-10).

---

## 11. Results tables

**These ship empty. Measured columns are filled only from `results.json`, produced by
`make bench`. A number that has not been measured does not go in a table, a slide, or a
sentence.**

### 11.1 Representation and memory

| Metric | Target | B1 dense uniform 2.5D | B4 sparse 3D voxel | AVR-25D | Ratio |
|---|---|---|---|---|---|
| Total cells (full envelope) | — | 16,000,000 | — | 705,771 | **22.67×** |
| Occupied cells / frame | — | _measured_ | _measured_ | _measured_ | _measured_ |
| Bytes / frame | — | 400.0 MB | _measured_ | 17.64 MB dense | _measured_ |
| Peak RSS | — | _measured_ | _measured_ | _measured_ | _measured_ |

### 11.2 Latency

| Stage | Target | Mean | Median | p95 | Max |
|---|---|---|---|---|---|
| Perception (live, CPU) | — | _measured_ | _measured_ | _measured_ | _measured_ |
| Perception (cached) | — | _measured_ | _measured_ | _measured_ | _measured_ |
| Projection | ≤ 8 ms | _measured_ | _measured_ | _measured_ | _measured_ |
| Cell analysis | ≤ 8 ms | _measured_ | _measured_ | _measured_ | _measured_ |
| Refinement | ≤ 3 ms | _measured_ | _measured_ | _measured_ | _measured_ |
| Decision | ≤ 8 ms | _measured_ | _measured_ | _measured_ | _measured_ |
| Serialise | ≤ 4 ms | _measured_ | _measured_ | _measured_ | _measured_ |
| **Total (excl. live inference)** | **≤ 33 ms** | _measured_ | _measured_ | _measured_ | _measured_ |

### 11.3 Distance-binned accuracy

| Range | mIoU | DRIVABLE IoU | STATIC IoU | DYNAMIC IoU | Object recall | Mean pts/scan |
|---|---|---|---|---|---|---|
| 0–10 m | _measured_ | _measured_ | _measured_ | _measured_ | _measured_ | _measured_ |
| 10–30 m | _measured_ | _measured_ | _measured_ | _measured_ | _measured_ | _measured_ |
| 30–60 m | _measured_ | _measured_ | _measured_ | _measured_ | _measured_ | _measured_ |
| 60–100 m | _measured_ | _measured_ | _measured_ | _measured_ | _measured_ | _measured_ |
| **Overall** | _measured_ | _measured_ | _measured_ | _measured_ | _measured_ | _measured_ |

### 11.4 Hazard preservation

| Scene | Hazard | True value | Measured | Error | Detection rate | 2D-grid result |
|---|---|---|---|---|---|---|
| S2 | Pothole depth | 0.22 m | _measured_ | _measured_ | _measured_ | not representable |
| S3 | Gantry clearance | 3.10 m | _measured_ | _measured_ | _measured_ | not representable |
| S4 | Curb height | 0.15 m | _measured_ | _measured_ | _measured_ | not representable |
| S1 | False positives | 0 | _measured_ | — | — | — |

### 11.5 Projection integrity

| Metric | Target | Measured |
|---|---|---|
| Points conserved | 100.000 % | _measured_ |
| Points dropped at ring boundaries | 0 | _measured_ |
| Cells with ambiguous assignment | 0 | _measured_ |

---

## 12. Scope

### 12.1 Phase 1 — must exist and run by 10 September 2026

Fourteen days. The cut is still deliberate — anything not on this list is Phase 2 — but the
extended deadline makes room for four items that a six-day schedule had pushed out, marked
**[pulled forward]** below.

- Ring-sector grid engine with closed-form indexing and per-frame conservation assertion (FR-7…FR-12)
- Geometric fallback segmenter (FR-5) — **first**, because it de-risks everything downstream
- ONNX range-image segmentation, cached + live modes (FR-1…FR-4, FR-6)
- Full cell schema with hazard flags (FR-13…FR-16)
- Bounded local refinement (FR-17, FR-18)
- Traversability, Kalman tracker, Cartesian costmap, A*, explanation (FR-19…FR-24)
- Four-view dashboard, ring overlay, A/B wipe, live HUD (FR-25…FR-30)
- Benchmark harness: memory, latency, distance-binned accuracy, hazard preservation (FR-31…FR-35)
- Synthetic scenes S1–S5, all five (S4 curb is no longer at risk of being dropped)
- 5-slide SIH-format deck, 3-minute video, README, demo run-book
- **[pulled forward]** Uncertainty-driven refinement — resolution as a function of confidence,
  not only of motion and roughness. Completes the `R = f(distance, complexity, semantics,
  uncertainty)` claim rather than leaving it half-supported.
- **[pulled forward]** A perception improvement pass: fine-tune on the 5-class taxonomy if the
  GPU question (Q-1) resolves favourably, otherwise a CPU decoder-head-only fine-tune plus
  confidence calibration, which also feeds the uncertainty-driven refinement above.
- **[pulled forward]** Multi-sequence evaluation reporting per-sequence variance rather than a
  single number — a materially stronger accuracy claim.
- **[pulled forward]** Two adversarial synthetic scenes: an occluded pothole and a
  low-clearance tunnel containing a curb.

### 12.2 Phase 2 — 11 to 20 September 2026

Ten days. Shorter than originally planned because four items moved into Phase 1 when the
deadline shifted (§12.1).

- Temporal accumulation across scans with ego-motion compensation — the largest remaining
  technical gain, improving `z_ground` in sparse far-field cells and stabilising tracks
- Complete the perception fine-tune if Phase 1 took the CPU-only branch, or if GPU access
  arrives late
- Ablation studies: with and without refinement; network versus geometric segmenter; and
  downstream planning cost on a uniform grid versus the adaptive one, which converts the
  22.67× cell reduction into a measured compute saving rather than a memory claim
- Dashboard: timeline scrubber, side-by-side scene comparison, exportable evidence screenshots
- Further adversarial scenes: multiple simultaneous hazards, sparse-return conditions, a
  negative obstacle on a slope
- Jetson / embedded-GPU latency measurement if hardware becomes available
- Route ETA calibration against measured vehicle dynamics
- Full technical report

### 12.3 Explicitly cut

| Cut | Reason |
|---|---|
| Cylinder3D / SPVCNN / any sparse-conv model | `spconv` and `torchsparse` need CUDA, which this team does not have on any machine. Even with the extended deadline the hardware fact is unchanged, and the accuracy is not needed at 5 classes. |
| ROS / ROS 2 | Integration overhead with no PS coverage. |
| C++ core | NumPy vectorised is fast enough for the latency target. Rewriting is optimisation before measurement. |
| MATLAB/Simulink in the runtime path | MATLAB earns its place as an offline ground-truth generator (§9.3), not as a runtime dependency. |
| LLM-based agents | Non-deterministic, unexplainable, slower, and adds an API dependency to a live demo. See NG-5. |
| Multi-vehicle fleet optimisation | No PS coverage; large implementation cost. |
| SLAM / global mapping | NG-1. |

---

## 13. Risk register

| ID | Risk | L | I | Mitigation | Owner |
|---|---|---|---|---|---|
| **R-1** | No usable GPU; live network inference too slow for the demo | High | High | Cached-label mode (FR-6) with the mode shown on the HUD; live inference latency measured and reported separately; pipeline architecture makes perception a swappable stage | Anuj |
| **R-2** | Pretrained ONNX weights unavailable, incompatible, or wrongly licensed | Med | High | Geometric fallback segmenter ships Day 1 before any model work (FR-5); the pipeline is never blocked on a model | Anuj |
| **R-3** | SemanticKITTI download does not finish in time | Med | High | Start Day 1 hour 1; sequence 04 (271 scans) alone unblocks the smoke test; synthetic scenes are a complete independent data path | Anuj |
| **R-4** | Three.js cannot sustain frame rate at ~100k instanced cells | Med | Med | `InstancedMesh` + frustum culling + distance LOD; fallback to point-sprite rendering of cell centroids, which is visually nearly identical at demo zoom | Shubham |
| **R-5** | Mac/Windows divergence burns days on environment issues | Med | High | NFR-3, NFR-4: pure NumPy core, no compiled deps, Numba behind a flag; both platforms smoke-tested Day 1 evening | Sameer |
| **R-6** | Frontend blocked waiting on backend | High | High | `fixtures.py` on Day 1 emits schema-valid frames; protocol frozen Day 1; frontend never imports backend code (NFR-8) | Sameer |
| **R-7** | Live demo fails in front of judges | Med | High | `--replay` mode from a saved frame log; pre-recorded video as backup; demo run-book with a rehearsed recovery path; NFR-6 cold-start bound | Sameer |
| **R-8** | MATLAB licence unavailable to the non-tech pair | Med | Med | All `.m` files are base-language only and run unmodified in free GNU Octave (§9.3) | Khanak |
| **R-9** | The team over-commits and misses the deadline | Med | High | §12.1 cut line is explicit and dated; features are cut, never quality; Day 11 (Mon 7 Sep) is a hard feature freeze with three clear days after it | Sameer |
| **R-10** | Unmeasured numbers leak into the deck | Med | High | Results tables ship empty; only `results.json` may populate them (FR-35); Veda cross-checks every slide number against the file before submission | Veda |

---

## 14. Assumptions and open questions

### 14.1 Assumptions

- **A-1** — Sensor is a 64-beam mechanical LiDAR at 10 Hz, ego-mounted, roughly 1.7 m above
  ground, matching the KITTI HDL-64E setup. The grid parameters in FR-7 are tuned to it.
- **A-2** — Vehicle height `H_vehicle` = 3.5 m and width 2.5 m by default, representing a
  medium logistics truck. Configurable per NFR-7.
- **A-3** — Ground is single-valued in plan view within a cell — that is, a 2.5D height field
  is a valid representation. This holds for road, yard and unimproved terrain, and breaks for
  multi-level structures such as flyovers stacked over roads. Where it breaks, `z_ground` and
  `z_obstacle` together still capture the drivable surface plus the clearance above it, which
  is what the decision layer needs (§7.3).
- **A-4** — Scenes are ground-vehicle scenes. Aerial and steep off-road are out of envelope.
- **A-5** — 5 cm at 10 m and 50 cm at 100 m are taken from PS-6 as given requirements, not
  derived. The `s(r) ∝ r` interpolation between them is our design choice, justified in
  `IMPLEMENTATION_PLAN.md` §3.

### 14.2 Open questions

| ID | Question | Needed by | Owner |
|---|---|---|---|
| **Q-1** | Exact GPU in the Windows box — does it support CUDA and with how much VRAM? Changes nothing structurally, but if it is usable, live inference goes on the HUD as a real number rather than a projected one. | Day 2 | Anuj |
| **Q-2** | Does the internal hackathon require a specific deck template or slide count? | Day 2 | Veda |
| **Q-3** | Is the live demo on our hardware or a provided machine? Determines whether NFR-4 cross-platform work is essential or merely prudent. | Day 3 | Veda |
| **Q-4** | Which pretrained SemanticKITTI range-image checkpoint is available under a licence permitting hackathon use? | Day 2 | Anuj |

---

## 15. Coverage check — reverse traceability

Every PS clause is covered by at least one requirement.

| PS | Covered by |
|---|---|
| PS-1 Drivable vs non-drivable terrain | FR-1, FR-19; classes 1 and 2 in §6.1 |
| PS-2 Static and dynamic object classification | FR-1, FR-20; classes 3 and 4 in §6.1 |
| PS-3 Non-uniform grid, cell size grows with distance | FR-7, FR-8, FR-27 |
| PS-4 No alignment errors or data loss in 3D→2.5D projection | FR-4, FR-9, FR-10 |
| PS-5 Deep-learning semantic segmentation network | FR-1, FR-2, FR-3 |
| PS-6 5 cm within 10 m, 50 cm to 100 m | FR-7 |
| PS-7 Dashboard with colour-coded terrain and objects | FR-25, FR-26 |
| PS-8 Significant memory reduction vs uniform high-resolution 3D | FR-28, FR-29, FR-31; §10.1 |
| PS-9 Low latency, high FPS, accuracy across distances | FR-6, FR-28, FR-32, FR-33, FR-34 |
| PS-10 Curbs, potholes, overhanging obstacles | FR-13, FR-14, FR-15, FR-16 |

---

## 16. Glossary

| Term | Meaning |
|---|---|
| **2.5D map** | Plan-view grid in which each cell carries height and semantic layers, rather than a single occupancy value. Not a full 3D volume — one surface per cell, plus what is above it. |
| **Foveation** | Allocating resolution non-uniformly, concentrating it where it matters, by analogy with the human retina. |
| **Ring-sector grid** | Polar grid indexed by radial ring and angular sector, with per-ring cell size and per-ring sector count. |
| **Isotropic cell** | A cell whose radial and tangential extents are approximately equal — a square, not a sliver. FR-8 enforces this at every range. |
| **Negative obstacle** | A hazard below the ground plane — pothole, ditch, culvert. Invisible to a 2D occupancy grid because it returns no "occupied" cell. |
| **Clearance** | `z_obstacle − z_ground`. The vertical gap between the drivable surface and the structure above it. |
| **Conservation test** | The per-frame assertion that the number of points assigned to cells equals the number of input points in the envelope. The formal statement of "no data loss" (PS-4). |
| **Range image** | Spherical (azimuth × elevation) projection of a point cloud into a dense 2D image, letting a standard 2D CNN process LiDAR. |
| **mIoU** | Mean intersection-over-union across classes; the standard semantic segmentation metric. |
