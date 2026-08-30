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

## Dataset

```bash
python ../tools/fetch_kitti.py --dry-run    # what it would fetch, and how big
python ../tools/fetch_kitti.py              # the subset, to model/data/kitti/
```

KITTI publishes the odometry point clouds as **one 84.8 GB zip** with no
per-sequence download. The archive is served with `Accept-Ranges: bytes`, so the
fetcher reads the zip's central directory over HTTP and issues one ranged
request per member it actually wants — about 2% of the archive. `zipfile` does
the ZIP64 parsing; the script just supplies a seekable file object over ranges.

Two things about that archive are worth knowing before changing the subset,
because both cost real time:

- **Members are not stored in frame order.** Within sequence 04, frame `000000`
  sits at a *higher* offset than `000007`. Extraction runs in `header_offset`
  order, not filename order; walking by name seeks backwards on nearly every
  file and made one benchmark transfer 912 MB to extract 114 MB.
- **"The first N frames" is an expensive request.** Those N frames are strewn
  across the whole sequence region. Hence `--sampling`:

  | mode | picks | cost | use for |
  |---|---|---|---|
  | `frames` | first N by frame number, temporally consecutive | ~4.5× payload | tracking, replay logs |
  | `contiguous` | N adjacent *in the archive*, spread across the drive | 1.0× payload | segmentation accuracy |

  Whole sequences are contiguous either way, so sequence 04 costs 1.0× regardless.

The default subset (PRD §9.1, with per-sequence sampling this repo adds):

| Sequence | Scans | Sampling | Transfer | For |
|---|---:|---|---:|---|
| 04 | all 271 | — | 0.55 GB | Smoke test, demo, first accuracy numbers |
| 00 | 400 | `contiguous` | 0.78 GB | Segmentation accuracy, sampled across the drive |
| 05 | 300 | `frames` | 2.66 GB | Moving traffic — the tracker needs temporal continuity |

**Licences.** SemanticKITTI is [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)
— attribution, share-alike, and **non-commercial**. That is fine for the
hackathon and it must be stated wherever the data is used; it also means no
claim in the deck may imply a commercial product trained on this data.

## Progress

Daily notes go in [`../docs/progress/`](../docs/progress/) — one file per
contributor, newest entry at the top.
