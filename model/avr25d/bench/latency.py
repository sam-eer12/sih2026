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

**The warm-up frames are discarded, and counted.**  Measured on sequence 05 in
cached mode: median 5.9 ms, max 46.9 ms, against a 6.6 ms max on sequence 04
through the identical code path.  The spike is first-touch page faults on the
freshly-appended region of the label-cache mmap — an artefact of the first read
of a file, not of the pipeline, and it lands entirely in the opening frames.
Reporting it as the worst case would attribute 41 ms of page-fault to the
segmenter.  ``warmup_frames`` therefore drops the opening frames from the
statistics and ``results.json`` records how many were dropped, so the number is
disclosed rather than quietly removed.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Callable, Iterable, Iterator

import numpy as np

#: FR-32's floor.  Runs below this are reported as not meeting it.  Counted
#: *after* warm-up, so a 200-scan claim rests on 200 scored scans.
MIN_SCANS_FR32: int = 200

#: Frames ``bench/__main__.py`` discards before timing starts.  Enough to cover
#: the first touch of an mmapped cache and the allocator settling; small enough
#: that a 271-scan sequence still clears FR-32's 200 with room to spare.
#:
#: It is *not* the recorder's default.  The recorder is an instrument and an
#: instrument that silently throws away the first five observations is a trap
#: for its next caller; discarding warm-up is a benchmark policy, so the
#: benchmark passes it in.
BENCH_WARMUP_FRAMES: int = 5


def warmup_for(n_scans: int, requested: int = BENCH_WARMUP_FRAMES) -> int:
    """Warm-up window for a run of ``n_scans``, capped at a tenth of it.

    A 3-scan debug run with a 5-frame warm-up discards every observation and
    reports no latency at all, which is a worse failure than the page faults
    the warm-up exists to exclude: the run looks like it succeeded and the
    section is empty.  Capping the window at 10% keeps the guard on real runs
    (5 of 271) and turns it off on runs too short to warrant it.
    """
    return max(0, min(int(requested), int(n_scans) // 10))

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

    def __init__(
        self,
        clock: Callable[[], float] = time.perf_counter,
        warmup_frames: int = 0,
    ) -> None:
        self._clock = clock
        self._warmup = int(warmup_frames)
        self._seen = 0
        self._discarded = 0
        self._windows = 0
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
            self._seen += 1
            if self._seen > self._warmup:
                self._frames.append(elapsed_ms)
                self._unaccounted.append(elapsed_ms - self._frame_stage_total)
            else:
                self._discarded += 1
                if self._seen == 1:
                    self._windows += 1
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
            self._frame_stage_total += elapsed_ms
            # A warm-up frame's stages are discarded with the frame itself.
            # Keeping them would leave the stage medians measuring one thing
            # and end_to_end another, and the two are cross-checked in §11.2.
            if self._seen >= self._warmup:
                self._stages.setdefault(name, []).append(elapsed_ms)

    def restart_warmup(self, warmup_frames: int | None = None) -> None:
        """Discard another warm-up window from here, optionally resized.

        A multi-sequence run touches a new region of the label-cache mmap at
        every sequence boundary, so the page-fault spike this exists to exclude
        happens once per sequence, not once per process.  Without this the
        pooled worst case is the second sequence's first frame.
        """
        self._seen = 0
        if warmup_frames is not None:
            self._warmup = int(warmup_frames)

    @property
    def n_warmup_windows(self) -> int:
        return self._windows

    @property
    def n_frames(self) -> int:
        """Frames that were *scored* — warm-up is not included."""
        return len(self._frames)

    @property
    def n_warmup_discarded(self) -> int:
        """Total frames discarded, across every warm-up window."""
        return self._discarded

    def summary(self) -> dict:
        """The latency section of ``results.json``."""
        return {
            "n_frames": self.n_frames,
            "n_warmup_discarded": self.n_warmup_discarded,
            "n_warmup_windows": self.n_warmup_windows,
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
