"""Per-stage and end-to-end latency.  IMPLEMENTATION_PLAN §6.11, FR-32, NFR-1.

FR-32 asks for mean, median, p95 **and worst case**, over at least 200 scans,
and is explicit that a mean alone will not do.  That is the right instinct: a
10 Hz loop is killed by its tail, not its average, and the Day 3 geometric
numbers are exactly this shape — 58.1 ms median against a 135.1 ms worst case.
Reporting only the median would have hidden a 2.3x spike.

Two deliberate choices:

**End-to-end is measured, not summed.**  Adding the stages up drops whatever
happens between them — allocation, copies, the loop itself — and produces a
total that is quietly smaller than the wall clock.  The frame is timed on its
own, and the residual is reported as ``unaccounted_ms`` rather than buried.
If that number is large, that is a finding about the pipeline, not a rounding
error to be hidden.

**Fewer than 200 frames is reported, not rejected.**  During development the
harness has to be runnable over 20 scans; what it must not do is let a 20-scan
run reach a slide claiming to satisfy FR-32.  So ``meets_fr32`` travels with
the numbers into ``results.json``.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Callable, Iterable, Iterator

import numpy as np

#: FR-32's floor.  Runs below this are reported as not meeting it.
MIN_SCANS_FR32: int = 200

#: numpy's default percentile interpolation.  Named here because "p95" is
#: ambiguous across libraries and the deck should mean one specific thing.
PERCENTILE_METHOD: str = "linear"


@dataclass(frozen=True)
class Stats:
    """The four FR-32 statistics, plus the count and floor that give context."""

    n: int
    mean_ms: float
    median_ms: float
    p95_ms: float
    max_ms: float
    min_ms: float

    def as_dict(self) -> dict:
        return {k: (v if k == "n" else round(v, 4)) for k, v in asdict(self).items()}


def summarise(samples_ms: Iterable[float]) -> Stats:
    """Reduce a sample of durations to the FR-32 statistics.

    Raises on an empty sample: a mean of no observations is not zero, it is
    undefined, and emitting 0.0 ms would be the most flattering possible lie.
    """
    arr = np.asarray(list(samples_ms), dtype=np.float64)
    if arr.size == 0:
        raise ValueError("cannot summarise an empty latency sample")
    return Stats(
        n=int(arr.size),
        mean_ms=float(arr.mean()),
        median_ms=float(np.median(arr)),
        p95_ms=float(np.percentile(arr, 95, method=PERCENTILE_METHOD)),
        max_ms=float(arr.max()),
        min_ms=float(arr.min()),
    )


class LatencyRecorder:
    """Accumulates per-stage and per-frame durations across a benchmark run.

    Usage mirrors the pipeline it measures::

        rec = LatencyRecorder()
        for scan in sequence:
            with rec.frame():
                with rec.stage("read"):     xyzi = scan.points()
                with rec.stage("segment"):  labels = seg(xyzi)
        results["latency"] = rec.summary()
    """

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._stages: dict[str, list[float]] = {}      # insertion-ordered
        self._frames: list[float] = []
        self._unaccounted: list[float] = []
        self._in_frame = False
        self._frame_stage_total = 0.0

    @contextmanager
    def frame(self) -> Iterator[None]:
        """Time one whole frame, end to end."""
        self._in_frame = True
        self._frame_stage_total = 0.0
        t0 = self._clock()
        try:
            yield
        finally:
            elapsed_ms = (self._clock() - t0) * 1e3
            self._frames.append(elapsed_ms)
            self._unaccounted.append(elapsed_ms - self._frame_stage_total)
            self._in_frame = False

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Time one stage within the current frame.

        A stage outside a frame is a programming error rather than a
        recoverable condition: its duration has no end-to-end total to belong
        to, so ``unaccounted_ms`` would silently stop meaning anything.
        """
        if not self._in_frame:
            raise RuntimeError(
                f"stage({name!r}) used outside a frame() — per-stage timings "
                "must belong to a frame for unaccounted_ms to be meaningful"
            )
        t0 = self._clock()
        try:
            yield
        finally:
            elapsed_ms = (self._clock() - t0) * 1e3
            self._stages.setdefault(name, []).append(elapsed_ms)
            self._frame_stage_total += elapsed_ms

    @property
    def n_frames(self) -> int:
        return len(self._frames)

    def summary(self) -> dict:
        """The latency section of ``results.json``."""
        return {
            "n_frames": self.n_frames,
            "meets_fr32": self.n_frames >= MIN_SCANS_FR32,
            "min_scans_fr32": MIN_SCANS_FR32,
            "percentile_method": PERCENTILE_METHOD,
            "stages": {
                name: summarise(samples).as_dict()
                for name, samples in self._stages.items()
            },
            "end_to_end": summarise(self._frames).as_dict() if self._frames else None,
            "unaccounted_ms": (
                summarise(self._unaccounted).as_dict() if self._unaccounted else None
            ),
        }
