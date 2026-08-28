# AVR-25D

**Adaptive Variable-Resolution 2.5D LiDAR Mapping for Dynamic Environment Perception**

Smart India Hackathon 2026 · Problem Statement **SIH26053**
DRDO — Department of Defence Production / IDEX · Theme: Transportation & Logistics

---

A LiDAR mapping engine that allocates spatial resolution the way the human eye does: fine
detail close to the vehicle where braking decisions are made, coarsening with range to the
point where the sensor's own angular sampling runs out. Raw point clouds become a semantic
2.5D map — elevation plus class per cell — over a ring-sector polar grid that runs **5 cm
cells inside 10 m and 50 cm cells at 100 m**, using **22.67× fewer cells** than a uniform
5 cm grid over the same footprint, with a closed-form O(1) index that makes projection
alignment error impossible by construction.

Because the map keeps ground height and obstacle height separately, it represents the three
hazards a 2D occupancy grid destroys: **curbs, potholes, and overhanging structures**. A
deterministic decision layer turns the map into a route, a risk level, an ETA, and a stated
reason.

| Property | Value |
|---|---|
| Rings to 100 m | 662 (200 inner + 462 outer) |
| Total cells, 360° × 100 m | 705,771 |
| Uniform 5 cm equivalent | 16,000,000 |
| Cell reduction | **22.67×** |
| Far-field angular bin | 0.286°, constant |
| Cell size at every range | isotropic — radial ≈ tangential |

## Documents

| Document | What it covers |
|---|---|
| **[Product Requirements](docs/PRD.md)** | Problem framing, PS-clause traceability, 35 functional and 8 non-functional requirements, the data contract, metric definitions and measurement protocol, results tables, scope and cut line, risk register |
| **[Implementation Plan](docs/IMPLEMENTATION_PLAN.md)** | Grid mathematics and derivation, repository layout, the frozen wire protocol, module-by-module specifications, configuration reference, the day-by-day schedule, the 35-test plan, and the demo run-book |
| **[Work Distribution](docs/WORK_DISTRIBUTION.md)** | Six owners, ownership and backup map, dependency graph, per-person day-by-day tasks with acceptance criteria, the MATLAB scenario-generation guide, and the evidence and submission workstream |

## Status

Documentation complete; implementation begins Fri 28 Aug 2026.

| Milestone | Date |
|---|---|
| Internal hackathon — PPT, video, prototype, live demo | **Thu 10 September 2026** |
| SIH portal submission | Sun 20 September 2026 |

## Design commitments

- **CPU-only, cross-platform.** Runs on macOS and Windows from one source tree. No CUDA, no
  `spconv`, no compiled extension, no platform-specific build step.
- **Deterministic decisions.** No LLM in the decision path. The same input sequence always
  produces byte-identical routes and reason strings.
- **No unmeasured numbers.** Every figure in the deck comes from `results.json`, regenerated
  by one command. Results tables ship empty until they are measured.
