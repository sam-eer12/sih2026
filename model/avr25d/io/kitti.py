"""SemanticKITTI ``.bin`` / ``.label`` readers.

On-disk layout, unchanged from the dataset release::

    <root>/sequences/<seq>/velodyne/<frame:06d>.bin     float32[n, 4]  x y z intensity
    <root>/sequences/<seq>/labels/<frame:06d>.label     uint32[n]      instance<<16 | semantic
    <root>/sequences/<seq>/calib.txt                    (optional)
    <root>/sequences/<seq>/poses.txt                    (optional)

The synthetic scenes in ``avr25d/synth/`` write this exact layout, so the whole
pipeline — readers, label merge, benchmarks — runs over real and synthetic data
through one code path.  That is deliberate: a synthetic-only side channel is a
place for bugs to hide until the day the real data arrives.

Test sequences ship without ``labels/``.  ``Scan.has_labels`` is False there
rather than the reader raising, because latency benchmarking does not need
ground truth and should not be blocked by its absence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from avr25d.perception import labelmap

_FRAME_RE = re.compile(r"^(\d{6})\.bin$")


@dataclass(frozen=True)
class Scan:
    """One LiDAR scan, with labels already merged to the AVR-25D taxonomy."""

    frame_id: int
    xyz: np.ndarray          # float32[n, 3] — sensor frame, x forward, y left, z up
    intensity: np.ndarray    # float32[n]    — 0…1 as stored by KITTI
    avr_label: np.ndarray    # uint8[n]      — PRD §6.1 class, all-VOID if unlabelled
    moving: np.ndarray       # bool[n]       — raw id was a ``moving-*`` variant
    instance: np.ndarray     # uint16[n]     — KITTI instance id, 0 where none
    raw_label: np.ndarray    # uint16[n]     — untouched SemanticKITTI semantic id
    has_labels: bool

    @property
    def n_points(self) -> int:
        return int(self.xyz.shape[0])

    @property
    def range(self) -> np.ndarray:
        """Euclidean range per point, float32[n].  Used for distance binning."""
        return np.linalg.norm(self.xyz, axis=1).astype(np.float32)


def read_velodyne(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Read a ``.bin`` scan.  -> (xyz float32[n,3], intensity float32[n])."""
    raw = np.fromfile(Path(path), dtype=np.float32)
    if raw.size % 4 != 0:
        raise ValueError(
            f"{path}: {raw.size} float32 values is not a multiple of 4; "
            "the file is truncated or is not a KITTI velodyne scan"
        )
    pts = raw.reshape(-1, 4)
    return np.ascontiguousarray(pts[:, :3]), np.ascontiguousarray(pts[:, 3])


def read_labels(path: str | Path, n_points: int | None = None) -> np.ndarray:
    """Read a ``.label`` file.  -> uint32[n] packed words."""
    packed = np.fromfile(Path(path), dtype=np.uint32)
    if n_points is not None and packed.size != n_points:
        raise ValueError(
            f"{path}: {packed.size} labels for {n_points} points — "
            "scan and label file disagree"
        )
    return packed


def write_velodyne(path: str | Path, xyz: np.ndarray, intensity: np.ndarray) -> None:
    """Write a ``.bin`` scan in KITTI's interleaved float32 x/y/z/i layout."""
    xyz = np.asarray(xyz, dtype=np.float32).reshape(-1, 3)
    intensity = np.asarray(intensity, dtype=np.float32).reshape(-1)
    if intensity.shape[0] != xyz.shape[0]:
        raise ValueError(
            f"{xyz.shape[0]} points but {intensity.shape[0]} intensities"
        )
    out = np.empty((xyz.shape[0], 4), dtype=np.float32)
    out[:, :3] = xyz
    out[:, 3] = intensity
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.tofile(path)


def write_labels(path: str | Path, packed: np.ndarray) -> None:
    """Write a ``.label`` file from packed ``instance<<16 | semantic`` words."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.asarray(packed, dtype=np.uint32).tofile(path)


def pack_labels(semantic: np.ndarray, instance: np.ndarray | None = None) -> np.ndarray:
    """Pack (semantic, instance) into KITTI ``.label`` words.  -> uint32[n]."""
    semantic = np.asarray(semantic, dtype=np.uint32)
    if instance is None:
        return semantic
    instance = np.asarray(instance, dtype=np.uint32)
    return (instance << np.uint32(16)) | semantic


def read_scan(
    bin_path: str | Path,
    label_path: str | Path | None = None,
    frame_id: int | None = None,
) -> Scan:
    """Read one frame, merging labels to the AVR-25D taxonomy if present."""
    bin_path = Path(bin_path)
    xyz, intensity = read_velodyne(bin_path)
    n = xyz.shape[0]

    if frame_id is None:
        m = _FRAME_RE.match(bin_path.name)
        frame_id = int(m.group(1)) if m else 0

    if label_path is not None and Path(label_path).exists():
        packed = read_labels(label_path, n_points=n)
        semantic, instance = labelmap.split_label(packed)
        avr = labelmap.raw_to_avr(semantic)
        moving = labelmap.raw_is_moving(semantic)
        has_labels = True
    else:
        semantic = np.zeros(n, dtype=np.uint16)
        instance = np.zeros(n, dtype=np.uint16)
        avr = np.zeros(n, dtype=np.uint8)
        moving = np.zeros(n, dtype=bool)
        has_labels = False

    return Scan(
        frame_id=frame_id,
        xyz=xyz,
        intensity=intensity,
        avr_label=avr,
        moving=moving,
        instance=instance,
        raw_label=semantic,
        has_labels=has_labels,
    )


class KittiSequence:
    """Indexable view over one SemanticKITTI sequence directory.

    Accepts either a dataset root plus a sequence id::

        KittiSequence("data/kitti", "04")

    or a directory that already contains ``velodyne/``::

        KittiSequence("data/synthetic/S2_pothole")

    which is what the synthetic exporter produces.
    """

    def __init__(
        self,
        root: str | Path,
        sequence: str | None = None,
        limit: int | None = None,
    ):
        root = Path(root)
        if sequence is not None:
            seq_dir = root / "sequences" / sequence
            if not seq_dir.exists():          # tolerate a root already at sequences/
                seq_dir = root / sequence
        else:
            seq_dir = root

        self.dir = seq_dir
        self.sequence = sequence if sequence is not None else seq_dir.name
        self.velodyne_dir = seq_dir / "velodyne"
        self.label_dir = seq_dir / "labels"

        if not self.velodyne_dir.is_dir():
            raise FileNotFoundError(
                f"{self.velodyne_dir} does not exist — expected a SemanticKITTI "
                "sequence directory containing velodyne/"
            )

        self.scan_paths: list[Path] = sorted(
            p for p in self.velodyne_dir.iterdir() if _FRAME_RE.match(p.name)
        )
        if limit is not None:
            self.scan_paths = self.scan_paths[:limit]

        self.has_labels = self.label_dir.is_dir()

    def __len__(self) -> int:
        return len(self.scan_paths)

    def __getitem__(self, index: int) -> Scan:
        bin_path = self.scan_paths[index]
        label_path = (
            self.label_dir / f"{bin_path.stem}.label" if self.has_labels else None
        )
        return read_scan(bin_path, label_path, frame_id=int(bin_path.stem))

    def __iter__(self):
        for i in range(len(self)):
            yield self[i]

    def __repr__(self) -> str:
        return (
            f"KittiSequence({self.sequence!r}, {len(self)} scans, "
            f"labels={'yes' if self.has_labels else 'no'})"
        )
