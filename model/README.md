# `model/` — perception, synthetic scenes, benchmarks

The `avr25d` Python package: everything that turns points into labels, everything
that turns runs into numbers, and the synthetic scenes that carry exact hazard
ground truth. Owner: **Sameer** (`docs/WORK_DISTRIBUTION.md` §4.1).

The grid engine (`core/`), the wire protocol and the server (`server/`) are
Anuj's and live in `backend/`. Nothing here imports them.

## Setup

```bash
source ../backend/.venv/bin/activate      # shared virtualenv
pip install -e .
pytest -q
```

## Layout

| Path | What it is | Spec |
|---|---|---|
| `avr25d/config.yaml` | Every tunable, with units and a stated reason | NFR-7 |
| `avr25d/io/kitti.py` | SemanticKITTI `.bin` / `.label` readers and writers | — |
| `avr25d/perception/labelmap.py` | SemanticKITTI 19 → AVR-25D 5 class merge | PRD §6.1 |
| `avr25d/perception/geometric_seg.py` | RANSAC + clustering fallback segmenter | FR-5 |
| `avr25d/synth/` | Ray-cast scenes with exact ground truth | PRD §9.3 |
| `tests/` | `pytest -q` | IMPLEMENTATION_PLAN §9 |

## Synthetic scenes

```bash
python -m avr25d.synth                      # all five, to data/synthetic/
python -m avr25d.synth S2_pothole --out /tmp/scenes
```

Each scene writes a SemanticKITTI sequence directory — `velodyne/*.bin`,
`labels/*.label` — plus `ground_truth.json`. Real and synthetic data therefore
travel through one reader and one benchmark; there is no synthetic-only side
channel for bugs to hide in.

| Scene | Content | Measures |
|---|---|---|
| `S1_flat_road` | Flat road, nothing else | Ground-plane RMS; false-positive hazard rate |
| `S2_pothole` | 1.4 m × 0.22 m depression at 12 m | Negative-obstacle detection; depth error |
| `S3_overhang` | Overpass, 3.10 m clearance, drivable road beneath | Clearance error; that the ground stays `DRIVABLE` |
| `S4_curb` | 0.15 m kerb along the road edge | Step detection; height error |
| `S5_crossing_truck` | 40 frames, truck crossing at 8 m/s | Tracking; velocity error; reroute trigger |

Scenes are tables. One primitive per row in `avr25d/synth/scenes/*.csv`, so
authoring a hazard scene is editing a spreadsheet. **`x,y,z` is the centre of the
primitive and `sx,sy,sz` are full extents**, in the road frame (`z = 0` at the
road surface); points come out in the sensor frame, KITTI-style. See
`avr25d/synth/raycast.py` for the primitive types, including `pit` — the
open-top box that is the only way a depression can exist in a nearest-hit
ray-caster.

`data/` is gitignored. Nobody commits a point cloud.

## Progress

Daily notes go in [`../docs/progress/`](../docs/progress/) — one file per
contributor, newest entry at the top.
