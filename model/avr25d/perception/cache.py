"""Precomputed per-scan label store.  IMPLEMENTATION_PLAN §6.7.

Live network inference costs about 86 ms a frame on a laptop CPU, against a
33 ms end-to-end budget (NFR-1).  Those two numbers do not fit, and pretending
otherwise is the kind of thing a judge asks about.  So the network runs once,
over the whole subset, while nobody is watching, and the live pipeline reads
its answers out of a memory map.  Live inference stays available behind
``--infer network`` and is timed and reported as its own number (PRD §11.2).

Layout::

    cache/
      index.json    frame ids, byte offsets, point counts, and provenance
      labels.bin    one uint8 AVR class per point, all scans end to end

One blob and one ``np.memmap``, not one file per scan.  ``__getitem__`` is then
a slice of an already-mapped array: no ``open``, no read, no allocation on the
frame path, which is the whole point of caching.

The dangerous failure here is a quiet one.  A cache built with the geometric
fallback, or left half-built by an interrupted overnight run, still returns
plausible labels for every frame — and a demo that shows geometric labels while
the HUD says "network" is worse than one that crashes.  Hence ``index.json``
records what built it and refuses to extend a cache with a different segmenter,
and ``LabelCache`` checks the blob length against the index before trusting it.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import numpy as np

INDEX_NAME = "index.json"
BLOB_NAME = "labels.bin"
FORMAT_VERSION = 1


def frame_id_for(path: Path) -> str:
    """``.../sequences/04/velodyne/000123.bin`` -> ``"04/000123"``.

    Sequence-qualified, because frame ``000000`` exists in every sequence and a
    cache spanning several of them needs keys that do not collide.
    """
    path = Path(path)
    seq = path.parent.parent.name
    return f"{seq}/{path.stem}"


def _read_index(cache_dir: Path) -> dict:
    index_path = cache_dir / INDEX_NAME
    if not index_path.is_file():
        raise FileNotFoundError(f"no {INDEX_NAME} in {cache_dir}")
    return json.loads(index_path.read_text(encoding="utf-8"))


def build_cache(
    scan_paths: Sequence[Path] | Iterable[Path],
    segmenter,
    out_dir: Path | str,
    verbose: bool = True,
) -> dict:
    """Segment every scan once and write ``uint8`` labels per point.

    Resumable: scans already present in the index are skipped, so an overnight
    run that dies at 3 a.m. costs the frames it had left, not the ones it did.
    Returns the index it wrote.
    """
    from ..io.kitti import read_velodyne

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scan_paths = [Path(p) for p in scan_paths]

    mode = getattr(segmenter, "mode", "unknown")
    model = str(getattr(segmenter, "model_path", "") or "")

    frames: list[dict] = []
    offset = 0
    if (out_dir / INDEX_NAME).is_file():
        index = _read_index(out_dir)
        if index.get("mode") != mode:
            raise ValueError(
                f"{out_dir} holds a cache built by the {index.get('mode')!r} "
                f"segmenter; refusing to extend it with {mode!r}.  Delete the "
                "directory to rebuild."
            )
        frames = index["frames"]
        offset = sum(f["n_points"] for f in frames)

    done = {f["id"] for f in frames}
    todo = [p for p in scan_paths if frame_id_for(p) not in done]

    if verbose:
        print(
            f"{len(todo)} of {len(scan_paths)} scans to segment "
            f"({len(done)} already cached) -> {out_dir}"
        )

    t_start = time.perf_counter()
    with (out_dir / BLOB_NAME).open("ab") as blob:
        for i, path in enumerate(todo, 1):
            xyz, intensity = read_velodyne(path)
            labels = np.ascontiguousarray(segmenter(xyz, intensity), dtype=np.uint8)
            if labels.shape != (xyz.shape[0],):
                raise ValueError(
                    f"{path}: segmenter returned {labels.shape} for "
                    f"{xyz.shape[0]} points"
                )
            blob.write(labels.tobytes())
            frames.append(
                {
                    "id": frame_id_for(path),
                    "offset": offset,
                    "n_points": int(labels.shape[0]),
                    "path": str(path),
                }
            )
            offset += int(labels.shape[0])

            if verbose and (i % 25 == 0 or i == len(todo)):
                elapsed = time.perf_counter() - t_start
                rate = i / elapsed
                eta = (len(todo) - i) / rate if rate else 0.0
                print(
                    f"  {i}/{len(todo)}  {rate:.2f} scan/s  "
                    f"eta {eta/60:.1f} min",
                    flush=True,
                )
            # Rewrite the index as we go: an interrupted run stays resumable.
            if i % 25 == 0:
                _write_index(out_dir, mode, model, frames)

    index = _write_index(out_dir, mode, model, frames)
    if verbose:
        print(
            f"cached {len(frames)} scans, {offset:,} points, "
            f"{offset/1e6:.1f} MB in {(time.perf_counter()-t_start)/60:.1f} min"
        )
    return index


def _write_index(out_dir: Path, mode: str, model: str, frames: list[dict]) -> dict:
    index = {
        "version": FORMAT_VERSION,
        "mode": mode,
        "model": model,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_frames": len(frames),
        "n_points": sum(f["n_points"] for f in frames),
        "frames": frames,
    }
    (out_dir / INDEX_NAME).write_text(json.dumps(index, indent=1), encoding="utf-8")
    return index


class LabelCache:
    """Read-only view over a built cache.  Memory-mapped; no per-frame read."""

    def __init__(self, cache_dir: Path | str):
        self.dir = Path(cache_dir)
        index = _read_index(self.dir)
        self.meta = {k: v for k, v in index.items() if k != "frames"}
        self._frames = index["frames"]
        self.frame_ids: tuple[str, ...] = tuple(f["id"] for f in self._frames)
        self._by_id = {f["id"]: i for i, f in enumerate(self._frames)}
        self.n_points = int(index["n_points"])

        blob = self.dir / BLOB_NAME
        size = blob.stat().st_size if blob.is_file() else 0
        if size != self.n_points:
            raise ValueError(
                f"{blob} holds {size:,} bytes but {INDEX_NAME} accounts for "
                f"{self.n_points:,}; the cache is truncated or stale"
            )
        self._blob = (
            np.memmap(blob, dtype=np.uint8, mode="r")
            if self.n_points
            else np.zeros(0, np.uint8)
        )

    def __len__(self) -> int:
        return len(self._frames)

    def __getitem__(self, frame_id: int | str | np.integer) -> np.ndarray:
        if isinstance(frame_id, str):
            try:
                i = self._by_id[frame_id]
            except KeyError:
                raise KeyError(
                    f"{frame_id!r} is not in this cache "
                    f"({len(self._frames)} frames, {self.meta.get('mode')} mode)"
                ) from None
        else:
            i = int(frame_id)
            if not -len(self._frames) <= i < len(self._frames):
                raise IndexError(
                    f"frame {i} out of range for {len(self._frames)} cached scans"
                )
        entry = self._frames[i]
        # A slice of the mode="r" map: read-only by construction, so a caller
        # cannot scribble on the cache through the array it was handed.
        return self._blob[entry["offset"] : entry["offset"] + entry["n_points"]]

    def __iter__(self) -> Iterator[np.ndarray]:
        for i in range(len(self._frames)):
            yield self[i]

    def __contains__(self, frame_id: str) -> bool:
        return frame_id in self._by_id

    def path_for(self, frame_id: int | str) -> Path:
        i = self._by_id[frame_id] if isinstance(frame_id, str) else int(frame_id)
        return Path(self._frames[i]["path"])

    def __repr__(self) -> str:
        return (
            f"LabelCache({self.dir}, {len(self._frames)} frames, "
            f"{self.n_points:,} points, mode={self.meta.get('mode')!r})"
        )
