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
| `avr25d/perception/range_proj.py` | Cloud → 64×2048×6 range image, and back by k-NN | FR-2, FR-4 |
| `avr25d/perception/onnx_infer.py` | ONNX Runtime CPU session wrapper | FR-1, FR-3 |
| `avr25d/perception/cache.py` | Precomputed per-scan label store, memory-mapped | §6.7 |
| `avr25d/synth/` | Ray-cast scenes with exact ground truth | PRD §9.3 |
| `tests/` | `pytest -q` | IMPLEMENTATION_PLAN §9 |

Operational scripts live in [`../tools/`](../tools/): `fetch_kitti.py` (dataset),
`export_onnx.py` (checkpoint → ONNX), `build_cache.py` (overnight label cache).

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

## Perception model

**Q-4 — which pretrained checkpoint carries a usable licence?** Answered:
**[lidar-bonnetal](https://github.com/PRBonn/lidar-bonnetal)** SqueezeSegV2, from
the Photogrammetry and Robotics Lab at the University of Bonn. MIT licensed,
served over plain HTTP with no account or click-through, and the checkpoint the
RangeNet++ paper published. SalsaNext is also MIT but sits behind a Google Drive
interstitial that cannot be scripted, which matters when the model has to
rebuild on a fresh machine.

Of the five architectures published there, SqueezeSegV2 is the one a CPU budget
can afford: **0.93 M parameters, 3.6 MB of weights** against DarkNet21's 92 MB.

**The exported models are committed** — `data/models/squeezesegV2_{fp32,int8}.onnx`,
4.6 MB for both. A fresh clone can run the network path immediately, with no
checkpoint download and no PyTorch. Provenance, the upstream MIT licence and the
citation are in [`data/models/NOTICE.md`](data/models/NOTICE.md); it is the only
thing under `data/` that is committed.

To rebuild them from the published checkpoint instead:

```bash
curl -O http://www.ipb.uni-bonn.de/html/projects/bonnetal/lidar/semantic/models/squeezesegV2.tar.gz
tar xzf squeezesegV2.tar.gz -C data/checkpoints/
pip install -e '.[export]'              # torch, for the export only
python ../tools/export_onnx.py          # -> data/models/squeezesegV2_{fp32,int8}.onnx
```

The label cache needs the KITTI subset and is not committed (96 MB, and it is two
minutes to rebuild):

```bash
python ../tools/build_cache.py          # -> data/cache/network/
```

`export_onnx.py` reimplements the architecture rather than vendoring it, so the
repository holds no third-party Python. It is verified rather than trusted: the
published weights load with `strict=True`, so one wrong layer name or channel
count fails the load instead of quietly producing a network that runs and is
wrong. The exported graph then has to agree with the PyTorch reference —
measured at **100.000% of pixels** on a real KITTI scan.

### int8 is exported, and not used

IMPLEMENTATION_PLAN §6.6 calls for dynamic int8 quantisation. Measured, on
`00/000008`:

| | Size | Latency | Argmax agreement with PyTorch |
|---|---:|---:|---:|
| fp32 | 3.71 MB | 86.0 ms | 100.000% |
| int8 | 1.11 MB | 86.2 ms | 95.058% |

Dynamic quantisation scales activations at runtime, so a Conv-only graph pays
the quantise/dequantise cost without ever reaching an int8 kernel. It buys
2.6 MB of disk we are not short of and spends 5% of pixels on it. `config.yaml`
points at fp32 and says why. Both models are exported and both are tested;
static quantisation with a calibration set from the 758 cached scans is the
route worth trying if the network ever has to run live in the budget.

### Measured accuracy — network against the FR-5 geometric fallback

Same scans, same ground truth, five-class taxonomy. mIoU is over classes 1–4;
SemanticKITTI excludes *unlabeled* from mIoU and so do we.

| | seq 04, 46 scans (rural) | seq 00, 40 scans (urban) |
|---|---:|---:|
| **Network mIoU** | **0.823** | **0.868** |
| Geometric mIoU | 0.287 | 0.371 |
| Network point accuracy | 92.03% | 92.31% |
| Geometric point accuracy | 49.98% | 50.71% |

Per class, sequence 04:

| Class | Support | Network IoU | Geometric IoU |
|---|---:|---:|---:|
| DRIVABLE | 1,971,649 | 0.952 | 0.627 |
| NON_DRIVABLE_TERRAIN | 2,891,652 | **0.872** | **0.132** |
| STATIC_OBSTACLE | 725,490 | 0.694 | 0.267 |
| DYNAMIC_OBJECT | 73,842 | 0.772 | 0.124 |

The `NON_DRIVABLE_TERRAIN` row is the whole argument for the network. It is 50%
of sequence 04 by point count, and geometry cannot see it: flat grass beside a
road is the same plane as the road, so RANSAC calls both DRIVABLE. Tarmac
against verge is a *semantic* distinction, not a geometric one. That single row
is why FR-2 specifies a network and not a threshold.

### Measured latency

Per scan, ~125,000 points, macOS arm64, `CPUExecutionProvider`, median of 46:

| Stage | ms |
|---|---:|
| Range projection | 9.5 |
| ONNX inference | 91.4 |
| k-NN reprojection | 46.4 |
| **Total, network** | **146.7** |
| Total, geometric | 58.8 |

NFR-1's 33 ms budget explicitly excludes live network inference, which is why
`perception.mode` defaults to `cached`: `tools/build_cache.py` runs the network
once over the subset — 758 scans in 2.0 minutes at 6.4 scan/s — and writes
93.7 MB of `uint8` labels that `LabelCache` memory-maps in one call. Live
inference stays available and is reported as its own number, per PRD §11.2.

## Progress

Daily notes go in [`../docs/progress/`](../docs/progress/) — one file per
contributor, newest entry at the top.
