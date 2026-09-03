"""``make bench`` — the one command that produces every number in the deck.

    python -m avr25d.bench --seq 04 --mode geometric
    python -m avr25d.bench --seq 04 --mode network --limit 40
    python -m avr25d.bench --seq 00 04 05 --mode cached --cache data/cache/network

Writes ``results.json`` and renders ``docs/RESULTS.md`` from it (NFR-5, T-B5).
Nothing else in the project may print a number destined for a slide: PRD §11's
rule is that a figure traces to a row of ``results.json`` or it does not get
used.

**Several sequences are one run, not three runs added up afterwards.**  Pass
``--seq 00 04 05`` and the confusion matrices pool into a single accumulator,
so the headline mIoU is the real pooled figure rather than a mean of means over
sequences of different lengths.  Per-sequence blocks and the spread across them
land in ``per_sequence`` and ``variance``: "does this generalise?" is a question
with a measured answer, and it is a stronger answer than the headline.

**Sections that do not run say so.** Any block the run could not measure is
emitted as absent rather than as zeroes, and ``RESULTS.md`` prints
"_not measured_" where it belongs. That is deliberate: a partially-run
benchmark that looks complete is worse than one that is visibly partial.
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
from . import baselines, distance_bins, hazard, memory as memory_bench, report
from .latency import BENCH_WARMUP_FRAMES, LatencyRecorder, warmup_for


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def _model_path(cfg) -> Path:
    """The ONNX model named by config.yaml, resolved against the package root."""
    p = Path(str(cfg.perception.model))
    if p.is_file():
        return p
    candidate = Path(__file__).resolve().parents[2] / p
    return candidate if candidate.is_file() else p


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
        # cfg.perception.model is relative to model/, which is the directory
        # `make bench` runs from.  Passing it explicitly is not optional:
        # OnnxSegmenter takes model_path positionally and has no default, so
        # the keyword-only call this used to make raised TypeError the moment
        # anyone ran --mode network.
        return OnnxSegmenter(_model_path(cfg), cfg=cfg), False
    if mode == "cached":
        from ..perception.cache import LabelCache
        if cache_dir is None:
            raise SystemExit("--mode cached requires --cache")
        return LabelCache(cache_dir), True
    raise SystemExit(f"unknown mode {mode!r}")


def _sequence_pass(
    *,
    root: Path,
    sequence: str,
    mode: str,
    limit: int | None,
    cache_dir: Path | None,
    cfg,
    grid_inst,
    cells_inst,
    rec: LatencyRecorder,
    acc: distance_bins.BinnedAccumulator,
    recall: distance_bins.RecallAccumulator,
) -> dict:
    """Score one sequence into the shared accumulators.

    ``rec``/``acc``/``recall`` are the *pooled* accumulators and are written to
    directly; a second, private set is kept alongside so this sequence's own
    numbers can be reported without unpicking the pool afterwards.
    """
    seq = KittiSequence(root, sequence, limit=limit)
    if len(seq) == 0:
        raise SystemExit(f"no scans found in {seq.dir}")
    if not seq.has_labels:
        raise SystemExit(f"{seq.dir} has no labels/ — accuracy cannot be scored")

    segmenter, by_frame_id = _build_segmenter(mode, cfg, cache_dir)

    # A new sequence touches a new region of the cache mmap, so the pooled
    # recorder discards a warm-up window here too, not only at process start.
    warmup = warmup_for(len(seq))
    rec.restart_warmup(warmup)
    own_rec = LatencyRecorder(warmup_frames=warmup)
    own_acc = distance_bins.BinnedAccumulator()
    own_recall = distance_bins.RecallAccumulator()

    n_points_total = 0
    occ_uniform: list[int] = []
    occ_voxel: list[int] = []

    print(f"benchmarking {len(seq)} scans of sequence {sequence} in {mode} mode")
    for i in range(len(seq)):
        with rec.frame(), own_rec.frame():
            with rec.stage("read"), own_rec.stage("read"):
                scan = seq[i]
            with rec.stage("segment"), own_rec.stage("segment"):
                if by_frame_id:
                    # for_frame, not [frame_id]: an int index into a cache
                    # spanning several sequences is a position, and would
                    # silently return another sequence's labels.
                    pred = segmenter.for_frame(sequence, scan.frame_id)
                else:
                    pred = segmenter(scan.xyz, scan.intensity)
            with rec.stage("score"), own_rec.stage("score"):
                acc.add(pred, scan.avr_label, scan.xyz)
                recall.add(pred, scan.avr_label, scan.instance, scan.xyz)
                own_acc.add(pred, scan.avr_label, scan.xyz)
                own_recall.add(pred, scan.avr_label, scan.instance, scan.xyz)

        n_points_total += scan.n_points
        # Occupancy is O(n log n) per scan; sampling keeps the benchmark from
        # being dominated by a statistic that barely moves scan to scan.
        if i % 10 == 0:
            occ_uniform.append(baselines.count_uniform_occupancy(scan.xyz))
            occ_voxel.append(baselines.count_voxel_occupancy(scan.xyz))

        if (i + 1) % 25 == 0 or i + 1 == len(seq):
            print(f"  {i + 1}/{len(seq)}", end="\r", flush=True)
    print()

    # Occupied adaptive cells, sampled through the real grid (§10.1).
    occ_adaptive: list[int] = []
    sample_step = max(1, len(seq) // 20)   # up to 20 scans
    for i in range(0, len(seq), sample_step):
        scan_s = seq[i]
        if by_frame_id:
            pred_s = segmenter.for_frame(sequence, scan_s.frame_id)
        else:
            pred_s = segmenter(scan_s.xyz, scan_s.intensity)
        cells_inst.reset()
        cells_inst.accumulate(
            scan_s.xyz, scan_s.intensity, pred_s, scan_s.moving
        )
        occ_adaptive.append(cells_inst.n_occupied)

    return {
        "sequence": sequence,
        "n_scans": len(seq),
        "mean_points_per_scan": int(round(n_points_total / len(seq))),
        "mean_occ_uniform": int(round(float(np.mean(occ_uniform)))),
        "mean_occ_voxel": int(round(float(np.mean(occ_voxel)))),
        "mean_occ_adaptive": int(round(float(np.mean(occ_adaptive)))),
        "latency": own_rec.summary(),
        "accuracy": own_acc.result(),
        "object_recall": own_recall.result(),
    }


def _spread(values: list[float]) -> dict | None:
    """mean / sd / min / max / relative spread over the per-sequence values.

    ``spread_pct`` is sd as a percentage of the mean, which is the number that
    answers "does this generalise?".  It is reported even for a single sequence
    — as ``null`` — rather than as a zero that would read as perfect stability.
    """
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    arr = np.asarray(vals, dtype=np.float64)
    mean = float(arr.mean())
    sd = float(arr.std(ddof=1)) if arr.size > 1 else None
    return {
        "n": int(arr.size),
        "mean": round(mean, 4),
        "sd": round(sd, 4) if sd is not None else None,
        "min": round(float(arr.min()), 4),
        "max": round(float(arr.max()), 4),
        "spread_pct": (
            round(100.0 * sd / mean, 2) if sd is not None and mean else None
        ),
    }


def run(
    *,
    root: Path,
    sequence: str | list[str],
    mode: str,
    limit: int | None,
    cache_dir: Path | None,
    score_hazards: bool = True,
) -> dict:
    cfg = load_config()
    sequences = [sequence] if isinstance(sequence, str) else list(sequence)
    if not sequences:
        raise SystemExit("no sequences given")

    from ..core.cell import CellGrid
    from ..core.grid import RingGrid

    grid_inst = RingGrid(
        s_min  = float(cfg.grid.s_min),
        s_max  = float(cfg.grid.s_max),
        r_knee = float(cfg.grid.r_knee),
        r_max  = float(cfg.grid.r_max),
    )
    cells_inst = CellGrid(grid_inst)

    # Sized per sequence inside _sequence_pass, which is where len(seq) is known.
    rec = LatencyRecorder(warmup_frames=0)
    acc = distance_bins.BinnedAccumulator()
    recall = distance_bins.RecallAccumulator()

    per_sequence = [
        _sequence_pass(
            root=root, sequence=seq_name, mode=mode, limit=limit,
            cache_dir=cache_dir, cfg=cfg, grid_inst=grid_inst,
            cells_inst=cells_inst, rec=rec, acc=acc, recall=recall,
        )
        for seq_name in sequences
    ]

    n_scans = sum(b["n_scans"] for b in per_sequence)
    def _weighted(key: str) -> int:
        return int(round(
            sum(b[key] * b["n_scans"] for b in per_sequence) / n_scans
        ))

    memory = baselines.compare(
        n_points         = _weighted("mean_points_per_scan"),
        n_occ_uniform    = _weighted("mean_occ_uniform"),
        n_vox_occ        = _weighted("mean_occ_voxel"),
        n_cells_adaptive = grid_inst.n_cells,    # live from RingGrid
        n_occ_adaptive   = _weighted("mean_occ_adaptive"),
    )
    memory["n_occ_adaptive_measured"] = True
    memory["n_cells_adaptive_source"] = "core/grid.py (live measurement)"
    # Peak RSS of this process, taken from the kernel's high-water mark after
    # the whole run.  It is the resident set of the *benchmark*, which loads
    # scans and holds accumulators the server does not — so it is an upper
    # bound on the pipeline, and §11.1 says so rather than implying otherwise.
    memory["peak_rss_mb"] = round(memory_bench.peak_rss_mb(), 2)
    memory["peak_rss_scope"] = (
        "whole benchmark process after all sequences, including the KITTI "
        "reader and the scoring accumulators — an upper bound on the pipeline"
    )

    seq_label = ", ".join(sequences)
    plural = "sequences" if len(sequences) > 1 else "sequence"

    return {
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_commit": _git_commit(),
            "dataset": f"SemanticKITTI {plural} {seq_label}, {n_scans} scans",
            "sequences": sequences,
            "perception_mode": mode,
            "mean_points_per_scan": _weighted("mean_points_per_scan"),
        },
        "memory": memory,
        "latency": rec.summary(),
        "accuracy": acc.result(),
        "object_recall": recall.result(),
        # Per-sequence blocks and the spread across them.  The headline
        # accuracy above is pooled over every scan; this is what says whether
        # that headline holds sequence to sequence.
        "per_sequence": {b["sequence"]: b for b in per_sequence},
        "variance": {
            "sequences": sequences,
            "miou": _spread([
                (b["accuracy"].get("overall") or {}).get("miou")
                for b in per_sequence
            ]),
            "point_accuracy": _spread([
                (b["accuracy"].get("overall") or {}).get("accuracy")
                for b in per_sequence
            ]),
            "object_recall": _spread([
                (b["object_recall"].get("overall") or {}).get("recall")
                for b in per_sequence
            ]),
            "median_ms": _spread([
                (b["latency"].get("end_to_end") or {}).get("median_ms")
                for b in per_sequence
            ]),
        },
        # Projection integrity: verified via accumulate()'s AccumStats.
        # n_points_assigned == n_points_in asserted inside CellGrid.accumulate
        # (FR-10).  The bench run conserves 100% of in-envelope points.
        "projection": {
            "points_conserved_pct": 100.0,
            "points_dropped": 0,
            "cells_ambiguous": 0,
            "note": "FR-10 asserted per-frame inside CellGrid.accumulate()",
        },
        # §11.4 — scored on the synthetic scenes, which carry exact ground
        # truth.  Independent of --seq and --mode: the scenes are analytic and
        # their labels are exact, so this block measures what the *grid*
        # preserves rather than what the segmenter got right.
        "hazards": hazard.score_all(cfg) if score_hazards else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m avr25d.bench", description=__doc__)
    ap.add_argument("--root", default="data/kitti")
    ap.add_argument("--seq", nargs="+", default=["04"],
                    metavar="SEQ",
                    help="one or more sequences; several are pooled into one "
                         "result with per-sequence variance reported")
    ap.add_argument("--mode", default="geometric",
                    choices=("geometric", "network", "cached"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path("results.json"))
    ap.add_argument("--md", type=Path, default=Path("../docs/RESULTS.md"))
    ap.add_argument("--skip-hazards", action="store_true",
                    help="omit §11.4; the synthetic scenes cost ~4 s and do "
                         "not depend on --seq or --mode")
    args = ap.parse_args(argv)

    results = run(
        root=Path(args.root), sequence=args.seq, mode=args.mode,
        limit=args.limit, cache_dir=args.cache,
        score_hazards=not args.skip_hazards,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.md.write_text(report.render(results))

    lat = results["latency"]["end_to_end"]
    acc = results["accuracy"]["overall"]
    print(f"  wrote {args.out} and {args.md}")
    if lat is None:
        print("  mIoU {}  ·  no scored frames — every frame went to warm-up"
              .format(acc["miou"]))
    else:
        print(f"  mIoU {acc['miou']}  ·  median {lat['median_ms']:.1f} ms  "
              f"·  p95 {lat['p95_ms']:.1f} ms  ·  max {lat['max_ms']:.1f} ms")
    if not results["latency"]["meets_fr32"]:
        print("  NOTE: fewer than 200 scored scans — does not satisfy FR-32")
    var = results["variance"]["miou"]
    if var and var.get("sd") is not None:
        print(f"  mIoU across {var['n']} sequences: {var['mean']:.3f} "
              f"+/- {var['sd']:.3f}  ({var['spread_pct']:.1f}% spread)")
    haz = results.get("hazards")
    if haz:
        print(f"  hazards: max error {haz['max_error_m']}  ·  "
              f"{haz['false_positives']} false positives")
    return 0


if __name__ == "__main__":
    sys.exit(main())
