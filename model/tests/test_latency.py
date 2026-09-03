"""Per-stage and end-to-end latency harness (§6.11, FR-32).  T-B2.

FR-32 is specific: mean, median, p95 *and worst case* — "not just the mean".
A benchmark that reports only a mean hides exactly the tail a 10 Hz loop cares
about, so these tests pin all four and the >=200-scan requirement with them.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from avr25d.bench import latency as lat


class FakeClock:
    """A scripted ``perf_counter``.  Timing tests that sleep are slow and
    flaky; timing tests that inject their clock are neither."""

    def __init__(self, ticks_s):
        self._ticks = list(ticks_s)
        self._i = 0

    def __call__(self) -> float:
        t = self._ticks[self._i]
        self._i += 1
        return t


# --- the statistics --------------------------------------------------------

def test_summarise_reports_all_four_fr32_statistics():
    samples = [10.0, 20.0, 30.0, 40.0, 100.0]
    s = lat.summarise(samples)
    assert s.n == 5
    assert s.mean_ms == pytest.approx(40.0)
    assert s.median_ms == pytest.approx(30.0)
    assert s.max_ms == pytest.approx(100.0)
    assert s.min_ms == pytest.approx(10.0)


def test_p95_matches_the_documented_linear_interpolation():
    """The p95 definition is stated, not left to whichever library is handy."""
    samples = list(range(1, 101))          # 1..100 ms
    s = lat.summarise(samples)
    assert s.p95_ms == pytest.approx(float(np.percentile(samples, 95)))
    assert lat.PERCENTILE_METHOD == "linear"


def test_summarise_refuses_an_empty_sample():
    """Statistics of nothing are a lie, not a zero."""
    with pytest.raises(ValueError):
        lat.summarise([])


def test_max_is_the_true_worst_case_not_a_high_percentile():
    samples = [1.0] * 999 + [500.0]
    s = lat.summarise(samples)
    assert s.max_ms == pytest.approx(500.0)
    assert s.p95_ms < s.max_ms


# --- the recorder ----------------------------------------------------------

def test_recorder_times_stages_and_the_frame_that_contains_them():
    clock = FakeClock([0.000, 0.001, 0.005, 0.006])
    rec = lat.LatencyRecorder(clock=clock)
    with rec.frame():
        with rec.stage("segment"):
            pass
    out = rec.summary()
    assert out["stages"]["segment"]["mean_ms"] == pytest.approx(4.0)
    assert out["end_to_end"]["mean_ms"] == pytest.approx(6.0)


def test_end_to_end_is_measured_not_summed_from_stages():
    """Summing stages silently drops the glue between them.  The frame is
    timed on its own clock and the difference is reported, not hidden."""
    clock = FakeClock([0.000, 0.001, 0.005, 0.006])
    rec = lat.LatencyRecorder(clock=clock)
    with rec.frame():
        with rec.stage("segment"):
            pass
    out = rec.summary()
    assert out["unaccounted_ms"]["mean_ms"] == pytest.approx(2.0)


def test_multiple_stages_accumulate_independently():
    #        frame0 in, a in,  a out, b in,  b out, frame0 out
    clock = FakeClock([0.000, 0.000, 0.010, 0.010, 0.030, 0.030,
                       0.000, 0.000, 0.020, 0.020, 0.060, 0.060])
    rec = lat.LatencyRecorder(clock=clock)
    for _ in range(2):
        with rec.frame():
            with rec.stage("project"):
                pass
            with rec.stage("infer"):
                pass
    out = rec.summary()
    assert out["stages"]["project"]["n"] == 2
    assert out["stages"]["project"]["mean_ms"] == pytest.approx(15.0)
    assert out["stages"]["infer"]["mean_ms"] == pytest.approx(30.0)


def test_stage_order_is_preserved_for_reporting():
    """The report reads as a pipeline, so stages keep insertion order rather
    than being alphabetised into nonsense."""
    clock = FakeClock([0.0, 0.0, 0.001, 0.001, 0.002, 0.002])
    rec = lat.LatencyRecorder(clock=clock)
    with rec.frame():
        with rec.stage("read"):
            pass
        with rec.stage("segment"):
            pass
    assert list(rec.summary()["stages"]) == ["read", "segment"]


def test_a_stage_outside_a_frame_is_a_programming_error():
    rec = lat.LatencyRecorder(clock=FakeClock([0.0, 0.0]))
    with pytest.raises(RuntimeError):
        with rec.stage("orphan"):
            pass


def test_an_exception_inside_a_stage_does_not_corrupt_the_recorder():
    clock = FakeClock([0.000, 0.000, 0.010, 0.010])
    rec = lat.LatencyRecorder(clock=clock)
    with pytest.raises(ZeroDivisionError):
        with rec.frame():
            with rec.stage("boom"):
                raise ZeroDivisionError
    assert rec.summary()["stages"]["boom"]["n"] == 1


# --- FR-32's >=200 scans ---------------------------------------------------

def test_fewer_than_200_scans_is_reported_as_not_meeting_fr32():
    rec = lat.LatencyRecorder(clock=FakeClock([0.0, 0.001] * 10))
    for _ in range(10):
        with rec.frame():
            pass
    out = rec.summary()
    assert lat.MIN_SCANS_FR32 == 200
    assert out["n_frames"] == 10
    assert out["meets_fr32"] is False


def test_two_hundred_scans_meets_fr32():
    rec = lat.LatencyRecorder(clock=FakeClock([0.0, 0.001] * 200))
    for _ in range(200):
        with rec.frame():
            pass
    assert rec.summary()["meets_fr32"] is True


# --- the report ------------------------------------------------------------

def test_summary_is_json_serialisable():
    rec = lat.LatencyRecorder(clock=FakeClock([0.0, 0.0, 0.001, 0.002]))
    with rec.frame():
        with rec.stage("segment"):
            pass
    json.dumps(rec.summary())          # lands in results.json


def test_summary_of_a_recorder_that_saw_nothing_is_explicit():
    """An empty run reports that it is empty rather than inventing zeros."""
    rec = lat.LatencyRecorder(clock=FakeClock([]))
    out = rec.summary()
    assert out["n_frames"] == 0
    assert out["end_to_end"] is None
    assert out["meets_fr32"] is False


def test_default_clock_measures_real_elapsed_time():
    """The injected clock must not be the only thing that works."""
    rec = lat.LatencyRecorder()
    with rec.frame():
        with rec.stage("work"):
            sum(range(200_000))
    out = rec.summary()
    assert out["stages"]["work"]["mean_ms"] > 0.0
    assert out["end_to_end"]["mean_ms"] >= out["stages"]["work"]["mean_ms"]


# ---------------------------------------------------------------------------
# Warm-up discard (Day 11 — the seq-05 46.9 ms page-fault artefact)
# ---------------------------------------------------------------------------

class TestWarmup:
    """The recorder must not discard anything unless it is asked to.

    An instrument that silently drops its first five observations is a trap for
    whoever picks it up next, so the default is zero and the benchmark opts in.
    """

    @staticmethod
    def _clock_over(durations_s):
        """A clock that makes frame i take durations_s[i]."""
        t = [0.0]
        seq = iter(durations_s)

        def clock():
            # Called twice per frame: entry, then exit.
            clock.calls += 1
            if clock.calls % 2 == 0:
                t[0] += next(seq)
            return t[0]
        clock.calls = 0
        return clock

    def test_default_discards_nothing(self):
        rec = lat.LatencyRecorder(clock=self._clock_over([0.010]))
        with rec.frame():
            pass
        out = rec.summary()
        assert out["n_frames"] == 1
        assert out["n_warmup_discarded"] == 0

    def test_warmup_frames_are_excluded_from_the_statistics(self):
        # One 100 ms cold frame, then four 10 ms ones.
        rec = lat.LatencyRecorder(
            clock=self._clock_over([0.100, 0.010, 0.010, 0.010, 0.010]),
            warmup_frames=1,
        )
        for _ in range(5):
            with rec.frame():
                pass
        out = rec.summary()
        assert out["n_frames"] == 4
        assert out["n_warmup_discarded"] == 1
        assert out["end_to_end"]["max_ms"] == pytest.approx(10.0, abs=1e-6), (
            "the cold frame is still in the worst case"
        )

    def test_warmup_frames_stages_are_excluded_too(self):
        """Otherwise the stage medians and end_to_end measure different sets."""
        rec = lat.LatencyRecorder(warmup_frames=2)
        for _ in range(5):
            with rec.frame():
                with rec.stage("work"):
                    pass
        out = rec.summary()
        assert out["stages"]["work"]["n"] == out["end_to_end"]["n"] == 3

    def test_restart_warmup_opens_another_window(self):
        """A multi-sequence run pays the page-fault cost once per sequence."""
        rec = lat.LatencyRecorder(warmup_frames=2)
        for _ in range(2):          # "sequence" one
            for _ in range(5):
                with rec.frame():
                    pass
            rec.restart_warmup()
        out = rec.summary()
        assert out["n_warmup_windows"] == 2
        assert out["n_warmup_discarded"] == 4
        assert out["n_frames"] == 6

    def test_fr32_counts_scored_scans_not_raw_ones(self):
        """200 scans of which 5 are warm-up is 195 scored scans, not 200."""
        rec = lat.LatencyRecorder(warmup_frames=5)
        for _ in range(lat.MIN_SCANS_FR32):
            with rec.frame():
                pass
        out = rec.summary()
        assert out["n_frames"] == lat.MIN_SCANS_FR32 - 5
        assert out["meets_fr32"] is False

    def test_warmup_is_capped_at_a_tenth_of_the_run(self):
        """A 3-scan debug run must not discard all three.

        Discarding everything leaves an empty latency section on a run that
        otherwise looks successful, which is a worse failure than the page
        faults the warm-up exists to exclude.
        """
        assert lat.warmup_for(3) == 0
        assert lat.warmup_for(40) == 4
        assert lat.warmup_for(271) == lat.BENCH_WARMUP_FRAMES
        assert lat.warmup_for(0) == 0

    def test_restart_warmup_can_resize_the_window(self):
        rec = lat.LatencyRecorder(warmup_frames=0)
        with rec.frame():
            pass
        rec.restart_warmup(2)
        for _ in range(4):
            with rec.frame():
                pass
        out = rec.summary()
        assert out["n_frames"] == 3          # 1 before + 2 after the 2 discarded
        assert out["n_warmup_discarded"] == 2
