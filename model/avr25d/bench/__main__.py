"""``make bench`` — the one command that produces every number in the deck.

    python -m avr25d.bench --seq 04 --mode geometric
    python -m avr25d.bench --seq 04 --mode network --limit 40
    python -m avr25d.bench --seq 04 --mode cached --cache data/cache/network

Writes ``results.json`` and renders ``docs/RESULTS.md`` from it (NFR-5, T-B5).
Nothing else in the project may print a number destined for a slide: PRD §11's
rule is that a figure traces to a row of ``results.json`` or it does not get
used.

**What this does not measure yet, and says so.** Grid occupancy, peak RSS,
hazard scoring and projection integrity all need ``core/grid.py`` and
``core/cell.py``, which do not exist. The corresponding sections are emitted as
absent rather than as zeroes, and ``RESULTS.md`` prints "_not measured_" where
they belong. That is deliberate: a partially-run benchmark that looks complete
is worse than one that is visibly partial.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import load_config
from ..io.kitti import KittiSequence
from ..perception.geometric_seg import GeometricSegmenter
from . import baselines, distance_bins, report
from .latency import LatencyRecorder


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def _build_segmenter(mode: str, cfg, cache_dir: Path | None):
    """Return ``(callable(xyz, intensity) -> labels, needs_frame_id)``.

    ``cached`` is dispatched here rather than inside ``perception/`` for the
    reason recorded on Day 6: a cached lookup needs a *frame id*, which a
    ``(xyz, intensity)`` segmenter does not have. The mode switch lives where
    frame ids exist.
    """
    if mode == "geometric":
        return GeometricSegmenter(cfg), False
    if mode == "network":
        from ..perception.onnx_infer import OnnxSegmenter
        return OnnxSegmenter(cfg=cfg), False
    if mode == "cached":
        from ..perception.cache import LabelCache
        if cache_dir is None:
            raise SystemExit("--mode cached requires --cache")
        return LabelCache(cache_dir), True
    raise SystemExit(f"unknown mode {mode!r}")


def run(
    *,
    root: Path,
    sequence: str,
    mode: str,
    limit: int | None,
    cache_dir: Path | None,
) -> dict:
    cfg = load_config()
    seq = KittiSequence(root, sequence, limit=limit)
    if len(seq) == 0:
        raise SystemExit(f"no scans found in {seq.dir}")
    if not seq.has_labels:
        raise SystemExit(f"{seq.dir} has no labels/ — accuracy cannot be scored")

    segmenter, by_frame_id = _build_segmenter(mode, cfg, cache_dir)

    rec = LatencyRecorder()
    acc = distance_bins.BinnedAccumulator()
    recall = distance_bins.RecallAccumulator()

    n_points_total = 0
    occ_uniform: list[int] = []
    occ_voxel: list[int] = []

    print(f"benchmarking {len(seq)} scans of sequence {sequence} in {mode} mode")
    for i in range(len(seq)):
        with rec.frame():
            with rec.stage("read"):
                scan = seq[i]
            with rec.stage("segment"):
                if by_frame_id:
                    # for_frame, not [frame_id]: an int index into a cache
                    # spanning several sequences is a position, and would
                    # silently return another sequence's labels.
                    pred = segmenter.for_frame(sequence, scan.frame_id)
                else:
                    pred = segmenter(scan.xyz, scan.intensity)
            with rec.stage("score"):
                acc.add(pred, scan.avr_label, scan.xyz)
                recall.add(pred, scan.avr_label, scan.instance, scan.xyz)

        n_points_total += scan.n_points
        # Occupancy is O(n log n) per scan; sampling keeps the benchmark from
        # being dominated by a statistic that barely moves scan to scan.
        if i % 10 == 0:
            occ_uniform.append(baselines.count_uniform_occupancy(scan.xyz))
            occ_voxel.append(baselines.count_voxel_occupancy(scan.xyz))

        if (i + 1) % 25 == 0 or i + 1 == len(seq):
            print(f"  {i + 1}/{len(seq)}", end="\r", flush=True)
    print()

    mean_pts = int(round(n_points_total / len(seq)))
    mean_occ_uniform = int(round(float(np.mean(occ_uniform))))
    mean_occ_voxel = int(round(float(np.mean(occ_voxel))))

    memory = baselines.compare(
        n_points=mean_pts,
        n_occ_uniform=mean_occ_uniform,
        n_vox_occ=mean_occ_voxel,
        # The ring table's cell count is a derived constant of the §3 grid
        # maths (662 rings, 705,771 cells).  core/grid.py will report it
        # directly; until then it is quoted from the PRD and flagged as such.
        n_cells_adaptive=705_771,
        # n_occ_adaptive needs core/grid.py's projection.  Recording the
        # uniform count here would be a fabrication, so it is left absent.
        n_occ_adaptive=0,
    )
    memory["n_occ_adaptive_measured"] = False
    memory["n_cells_adaptive_source"] = "PRD §10.1 (core/grid.py not yet available)"
    memory["models"] = [
        m for m in memory["models"] if m["name"] != "AVR-25D occupied"
    ]

    return {
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_commit": _git_commit(),
            "dataset": f"SemanticKITTI sequence {sequence}, {len(seq)} scans",
            "perception_mode": mode,
            "mean_points_per_scan": mean_pts,
        },
        "memory": memory,
        "latency": rec.summary(),
        "accuracy": acc.result(),
        "object_recall": recall.result(),
        # Absent, not zero — see the module docstring.
        "hazards": None,
        "projection": None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m avr25d.bench", description=__doc__)
    ap.add_argument("--root", default="data/kitti")
    ap.add_argument("--seq", default="04")
    ap.add_argument("--mode", default="geometric",
                    choices=("geometric", "network", "cached"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path("results.json"))
    ap.add_argument("--md", type=Path, default=Path("../docs/RESULTS.md"))
    args = ap.parse_args(argv)

    results = run(
        root=Path(args.root), sequence=args.seq, mode=args.mode,
        limit=args.limit, cache_dir=args.cache,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.md.write_text(report.render(results))

    lat = results["latency"]["end_to_end"]
    acc = results["accuracy"]["overall"]
    print(f"  wrote {args.out} and {args.md}")
    print(f"  mIoU {acc['miou']}  ·  median {lat['median_ms']:.1f} ms  "
          f"·  p95 {lat['p95_ms']:.1f} ms  ·  max {lat['max_ms']:.1f} ms")
    if not results["latency"]["meets_fr32"]:
        print("  NOTE: fewer than 200 scans — does not satisfy FR-32")
    return 0


if __name__ == "__main__":
    sys.exit(main())
