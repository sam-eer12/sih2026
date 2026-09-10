# NEXA — Adaptive Variable-Resolution 2.5D LiDAR Mapping

**Live demo:** https://nexa-drdo.duckdns.org

---

## 1. Project Information

| Field | Value |
|---|---|
| **Project Title** | NEXA — Adaptive Variable-Resolution 2.5D LiDAR Mapping for Dynamic Environment Perception |
| **PS ID** | 26053 |
| **PS Title** | Adaptive Variable Resolution 2.5D Lidar Mapping for Dynamic Environment Perception |
| **Category** | Software |
| **Theme** | Smart Vehicles |
| **Organisation** | DRDO — Department of Defence Production / iDEX |
| **Team Name** | KANVSS |

## 2. Problem Statement

A 64-beam LiDAR produces ~120,000 points per revolution at 10 Hz — about 1.2 million
points per second. The two standard ways of consuming that stream both fail on vehicle
compute:

- **Keeping the full 3D point cloud or voxel grid** is rich but does not close the loop
  in real time on embedded hardware.
- **Flattening to a 2D occupancy grid** is cheap but discards height. A curb, a pothole
  and a low gantry all collapse into the same "occupied" bit, so the map cannot tell a
  vehicle that the ground is drivable but the bridge above it is 3.1 m.

A uniform high-resolution grid also over-samples the far field, where LiDAR beam
divergence means the detail was never measured in the first place.

## 3. Proposed Solution

NEXA allocates spatial resolution the way the human eye does — finely where a braking
decision is made, coarsening with range to the point where the sensor's own angular
sampling runs out.

Raw scans become a semantic **2.5D map** (elevation *and* class per cell) over a
ring-sector polar grid running **5 cm cells inside 10 m and 50 cm cells at 100 m**. Because
each cell keeps ground height and obstacle height separately, the map represents the three
hazards a 2D grid destroys: **curbs, potholes and overhanging structures**. A deterministic
decision layer turns the map into a route, a risk level, an ETA and a stated reason.

## 4. Key Features

- **Biomimetic foveated polar grid** — 662 rings, **705,771 cells**, isotropic at every
  range; **22.67× fewer cells** than a uniform 5 cm grid over the same 360° × 100 m footprint
- **Closed-form O(1) projection** — `offset[k] + j`, no search, no hashing; **100.000% point
  conservation** asserted every frame
- **Multi-hazard 2.5D detection** — curbs (step), potholes (negative obstacle) and overhangs
  (clearance), validated against synthetic scenes with exact ground truth
- **CPU-only perception** — range-image CNN via ONNX Runtime, with a geometric RANSAC
  fallback; no CUDA, no `spconv`, no compiled extension
- **Deterministic decision layer** — Kalman tracking, traversability costmap, A* routing and
  template-filled reason strings; no LLM anywhere in the decision path
- **Direct binary WebSocket streaming** — FastAPI to a Three.js `InstancedMesh` canvas, with
  per-frame data never entering React state
- **Reproducible benchmarks** — every published figure regenerates from `make bench` into
  `results.json` and `docs/RESULTS.md`

## 5. Technology Stack

| Layer | Technology |
|---|---|
| **Perception** | Python, NumPy, SciPy, ONNX Runtime (CPU) |
| **Mapping / Decision** | Python, NumPy (vectorised, pre-allocated) |
| **Backend** | FastAPI, Uvicorn, binary WebSocket |
| **Frontend** | Next.js 16 (App Router), React 19, TypeScript, Three.js, Tailwind |
| **Auth** | Firebase Authentication |
| **Database** | MongoDB Atlas |
| **Deployment** | Docker, Docker Compose, Caddy (auto-TLS), AWS EC2 (Graviton ARM64) |
| **Companion hardware** | Scilab — drone LiDAR payload modelling |

## 6. Architecture

See [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) and
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

```
LiDAR scan (~120k points)
  |
  v
1. PERCEPTION            range-image CNN (ONNX, CPU) + geometric fallback
  |                      19 SemanticKITTI classes -> 5 PS classes
  v
2. RING-SECTOR           (x,y) -> (r,theta) -> (ring k, bin j) -> flat id
   PROJECTION            5 cm @ <=10 m  ->  50 cm @ 100 m, closed-form O(1)
  |
  v
3. CELL ANALYSIS         z_ground / z_obstacle / slope / roughness / clearance
   + HAZARD FLAGS        OVERHANG - NEGATIVE_OBSTACLE - STEP
  |
  v
4. DECISION LAYER        traversability -> Kalman tracker -> costmap -> A*
   (deterministic)       -> route, risk, ETA, reason string
  |
  |  FrameMessage (binary WebSocket)
  v
5. WEB APP               Firebase auth gate - Three.js viewer - live HUD
  |
  v
6. MongoDB Atlas         run history - decision audit log - scene ground truth
```

**Deployed architecture**

```
Internet -> Caddy :443 (TLS)
              |-- /          -> Next.js  :3000
              |-- /health    -> FastAPI  :8000
              +-- /stream    -> FastAPI  :8000   (WebSocket, direct)
```

The browser reaches the WebSocket without a Next.js hop, so frame data is never proxied,
buffered or re-serialised.

## 7. Repository Structure

```
sih2026/
├── README.md
├── Makefile                  # make test | bench | scenes | finetune
├── model/                    # the engine
│   ├── avr25d/
│   │   ├── core/             # grid.py, cell.py, refine.py
│   │   ├── perception/       # range_proj, onnx_infer, geometric_seg, cache
│   │   ├── decision/         # traversability, tracker, costmap, planner, explain
│   │   ├── bench/            # memory, latency, distance_bins, hazard, report
│   │   ├── synth/            # ray-cast scenes with exact ground truth
│   │   └── server/           # FastAPI app, wire protocol, fixtures
│   └── tests/                # 382 tests
├── frontend/                 # Next.js app
│   ├── app/                  # routes: /, /login, /dashboard, /runs, /api/*
│   ├── components/           # viewer (Three.js), hud, decision
│   └── lib/                  # protocol, ws, firebase, mongo
├── backend/requirements.txt  # pinned Python dependencies
├── deploy/                   # Dockerfiles, compose, Caddyfile, push.sh
├── docs/                     # PRD, implementation plan, RESULTS.md, DEPLOYMENT.md
├── hardware/                 # companion drone LiDAR payload (Scilab)
├── tools/                    # dataset fetch, ONNX export, cache build, finetune
├── submission/               # presentation + demo links
└── assets/screenshots/       # dashboard and prototype images
```

| Item | Location |
|---|---|
| Source code | `model/`, `frontend/`, `backend/` |
| Architecture / technical documentation | `docs/` |
| Screenshots / hardware figures | `assets/screenshots/`, `hardware/figures/` |
| Final PPT | `submission/PRESENTATION.md` |
| Demo video link | `submission/DEMO.md` |
| Project overview | `README.md` |

## 8. Final Presentation

See [`submission/PRESENTATION.md`](submission/PRESENTATION.md).

## 9. Demo Video

See [`submission/DEMO.md`](submission/DEMO.md).

## 10. Screenshots / Prototype Photos

See [`assets/screenshots/`](assets/screenshots/). Payload figures generated by the Scilab
scripts are in [`hardware/figures/`](hardware/figures/).

## 11. Installation

Requires **Python 3.13+** and **Node 22+**. CPU only — no GPU, no CUDA.

```bash
git clone https://github.com/sam-eer12/sih2026.git
cd sih2026

# backend
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
backend/.venv/bin/pip install -e model/

# frontend
cd frontend && npm install && cd ..
```

The frontend needs a `frontend/.env.local`; copy `frontend/.env.local.example` and fill it
in. The app runs without it — authentication and persistence simply stay switched off.

## 12. Run

```bash
# Terminal 1 — pipeline server (no dataset needed)
cd model && ../backend/.venv/bin/python -m avr25d.server.app --fixtures

# Terminal 2 — web app
cd frontend && npm run dev
```

Open http://localhost:3000. Other modes:

```bash
# real scans, geometric segmenter
cd model && ../backend/.venv/bin/python -m avr25d.server.app \
    --infer geometric --seq 04 --data data/kitti

# replay a recorded log — deterministic, no dataset required
cd model && ../backend/.venv/bin/python -m avr25d.server.app \
    --replay data/logs/demo.log
```

**Tests and benchmarks**

```bash
make test          # 382 tests
make bench         # regenerates results.json and docs/RESULTS.md
make scenes        # regenerates the synthetic hazard scenes
```

**Deploy** (see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md))

```bash
./deploy/push.sh all
```

## 13. Results

Measured numbers live in [`docs/RESULTS.md`](docs/RESULTS.md), regenerated by `make bench`.
Structural properties, verified by the test suite:

| Property | Value |
|---|---|
| Rings to 100 m | 662 |
| Total cells, 360° × 100 m | 705,771 |
| Uniform 5 cm equivalent | 16,000,000 |
| Cell reduction | **22.67×** |
| Point conservation | **100.000%** |
| Pothole depth error (S2, true 0.22 m) | 0.0108 m |
| Gantry clearance error (S3, true 3.10 m) | 0.0024 m |
| Curb height error (S4, true 0.15 m) | 0.0026 m |
| False positives on flat control scene | 0 |

Latency and mIoU depend on the perception mode and the sequences evaluated; both are
stated with their configuration in `docs/RESULTS.md` rather than quoted bare.

## 14. Future Scope

- **Temporal accumulation** across scans with ego-motion compensation, improving `z_ground`
  in sparse far-field cells and stabilising tracks
- **Uncertainty-driven refinement** — resolution as a function of confidence, completing the
  `R = f(distance, complexity, semantics, uncertainty)` claim
- **Embedded-GPU latency measurement** on Jetson-class hardware
- **Ablation studies** — with and without refinement, network versus geometric segmenter,
  and planning cost on a uniform grid versus the adaptive one
- **Payload**: extend the receiver-chain model with a full noise budget and a Monte-Carlo
  range-accuracy study

---

## Important

No passwords, API keys, access tokens or `.env` files containing secrets are committed to
this repository. `deploy/.env` and `frontend/.env.local` are gitignored; the tracked
`*.example` files carry empty placeholders only.
