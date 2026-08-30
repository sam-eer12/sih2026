"""Write ray-cast output as a SemanticKITTI sequence directory.

    <out_dir>/velodyne/<frame:06d>.bin      float32[n, 4]  x y z intensity
    <out_dir>/labels/<frame:06d>.label      uint32[n]      instance<<16 | semantic

Identical on disk to the real dataset, so ``KittiSequence`` reads a synthetic
scene and a real sequence with the same call and the benchmark harness cannot
tell them apart.  That is the point — a synthetic-only side channel is where
bugs hide until the day the real data shows up.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from avr25d.io import kitti


def export_kitti(
    xyzi: np.ndarray,
    labels: np.ndarray,
    out_dir: str | Path,
    frame_id: int,
) -> tuple[Path, Path]:
    """Write one frame.  -> (bin_path, label_path)."""
    xyzi = np.asarray(xyzi, dtype=np.float32).reshape(-1, 4)
    labels = np.asarray(labels, dtype=np.uint32).reshape(-1)
    if labels.shape[0] != xyzi.shape[0]:
        raise ValueError(f"{xyzi.shape[0]} points but {labels.shape[0]} labels")

    out_dir = Path(out_dir)
    bin_path = out_dir / "velodyne" / f"{frame_id:06d}.bin"
    label_path = out_dir / "labels" / f"{frame_id:06d}.label"

    kitti.write_velodyne(bin_path, xyzi[:, :3], xyzi[:, 3])
    kitti.write_labels(label_path, labels)
    return bin_path, label_path
