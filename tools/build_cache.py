#!/usr/bin/env python3
"""Precompute per-point labels for the KITTI subset.  IMPLEMENTATION_PLAN §6.7.

Live network inference is ~86 ms a frame on a laptop CPU against a 33 ms
end-to-end budget (NFR-1).  This runs it once, unattended, so the demo can read
labels out of a memory map.  Resumable — rerun it after an interruption and it
picks up the scans it has not done.

    python tools/build_cache.py                     # network, whole subset
    python tools/build_cache.py --mode geometric    # the FR-5 fallback
    python tools/build_cache.py --sequences 04      # one sequence
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "model"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=REPO / "model/data/kitti")
    ap.add_argument("--mode", choices=("network", "geometric"), default="network")
    ap.add_argument("--model", type=Path, default=None,
                    help="ONNX model; defaults to perception.model in config.yaml")
    ap.add_argument("--out", type=Path, default=None,
                    help="cache directory; defaults to data/cache/<mode>")
    ap.add_argument("--sequences", nargs="*", default=None)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    from avr25d import load_config
    from avr25d.perception.cache import build_cache

    cfg = load_config()
    out = args.out or REPO / "model/data/cache" / args.mode

    seq_dir = args.root / "sequences"
    if not seq_dir.is_dir():
        ap.error(f"no sequences under {seq_dir}; run tools/fetch_kitti.py first")
    sequences = sorted(args.sequences or [p.name for p in seq_dir.iterdir()
                                          if p.is_dir()])
    scans = [p for s in sequences
             for p in sorted((seq_dir / s / "velodyne").glob("*.bin"))]
    if args.limit:
        scans = scans[: args.limit]
    if not scans:
        ap.error(f"no .bin scans found under {seq_dir} for sequences {sequences}")

    if args.mode == "network":
        from avr25d.perception.onnx_infer import OnnxSegmenter

        model = args.model or (REPO / "model" / cfg.perception.model)
        segmenter = OnnxSegmenter(model, cfg)
        print(f"network: {Path(model).name}  {segmenter.h}x{segmenter.w}  "
              f"{', '.join(segmenter.providers)}")
    else:
        from avr25d.perception.geometric_seg import GeometricSegmenter

        segmenter = GeometricSegmenter(cfg)

    print(f"{len(scans)} scans from sequences {', '.join(sequences)}")
    build_cache(scans, segmenter, out, verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
