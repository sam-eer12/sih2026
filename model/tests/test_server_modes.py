"""T-P6 — every perception mode emits a valid FrameMessage, and ``mode`` is honest.

    T-P6: `live`, `cached` and `geometric` modes all produce a valid
          `FrameMessage`; `mode` in the message matches the flag passed.

The plan lists T-P6 under *Perception* and the behaviour lives in
``server/app.py``, whose §6.12 section is the only module section with no
**Tests:** line — so it was the one id in the plan with no test anywhere.  It is
worth more than a checkbox, because ``app.py`` has two fallbacks that rewrite
the mode: a missing ONNX file and a missing label cache both drop to the
geometric segmenter.  FR-6 puts the active mode on the HUD *at all times*, so
the failure this test exists to prevent is a demo that shows geometric labels
under a badge reading "network" — the same quiet failure ``perception/cache.py``
was built to make impossible.

Two things are deliberate here.

*The data is synthetic.*  The sequence is ray-cast from ``S1_flat_road`` into a
KITTI directory in ``tmp_path``, so the suite still runs in a fresh clone with
no 2.2 GB download — the same reason ``test_onnx_infer.py`` builds its own ONNX
graphs instead of leaning on the checkpoint.

*The cached test asserts on the labels, not just on the mode string.*  A cache
built by a stub segmenter that answers ``STATIC_OBSTACLE`` for every point makes
"the labels came from the cache" checkable: if the cache is silently missed and
the geometric segmenter runs instead, a flat road does not come back as an
obstacle.  Asserting only ``mode == "cached"`` would pass on the fallback path
too, which is exactly how the bug this test was written against survived.
"""

from __future__ import annotations

import queue
from pathlib import Path

import numpy as np
import pytest

from avr25d.config import Config
from avr25d.perception import labelmap
from avr25d.perception.cache import build_cache
from avr25d.server.app import DEFAULT_CACHE_DIR, PipelineWorker
from avr25d.server.protocol import decode
from avr25d.synth import SensorSpec, load_scene, raycast
from avr25d.synth.export import export_kitti

SEQ = "04"
N_FRAMES = 2

#: Small enough to keep the fixture under a second, dense enough that the road
#: fills thousands of cells.  T-P6 is about the wiring, not about sensor
#: fidelity — the geometry tests in test_synth.py use the real 64 x 1800.
TEST_SENSOR = SensorSpec(n_beams=32, n_azimuth=360)

#: What the stub segmenter answers, and therefore what a genuine cache hit
#: looks like on a flat road.  Chosen because it is what geometric segmentation
#: of a flat road never returns.
CACHE_SENTINEL_CLASS = labelmap.STATIC_OBSTACLE


class _StubSegmenter:
    """Answers one class for every point.  ``build_cache`` reads ``mode``."""

    mode = "stub"
    model_path = ""

    def __call__(self, xyz, intensity):
        return np.full(len(xyz), CACHE_SENTINEL_CLASS, dtype=np.uint8)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def kitti_root(tmp_path_factory) -> Path:
    """A KITTI sequence directory ray-cast from S1_flat_road."""
    root = tmp_path_factory.mktemp("kitti")
    scene = load_scene("S1_flat_road")
    xyzi, labels = raycast(scene, TEST_SENSOR)
    for frame in range(N_FRAMES):
        export_kitti(xyzi, labels, root / "sequences" / SEQ, frame)
    return root


@pytest.fixture(scope="module")
def cache_dir(tmp_path_factory, kitti_root) -> Path:
    """A label cache over that sequence, built by the stub segmenter."""
    out = tmp_path_factory.mktemp("cache") / "stub"
    scans = sorted((kitti_root / "sequences" / SEQ / "velodyne").glob("*.bin"))
    build_cache(scans, _StubSegmenter(), out, verbose=False)
    return out


def _cfg_with_model(cfg, model_path) -> Config:
    """``cfg`` with ``perception.model`` repointed.  Config is read-only."""
    data = cfg.to_dict()
    data["perception"]["model"] = str(model_path)
    return Config(data)


def _first_frame(cfg, mode, kitti_root, **kwargs) -> dict:
    """Drive one frame out of the worker's generator and decode it."""
    worker = PipelineWorker(
        cfg, mode, queue.Queue(maxsize=2),
        seq=SEQ, data_root=kitti_root, **kwargs,
    )
    frames = worker._iter_frames()
    try:
        wire = next(frames)
    finally:
        frames.close()
    return decode(wire)


def _assert_valid_frame(header: dict) -> None:
    """The half of T-P6 that says *valid* rather than *matching*."""
    assert header["mode"] in {"live", "cached", "geometric", "fixtures"}
    assert isinstance(header["frame_id"], int)
    assert header["t_sec"] >= 0.0

    n = header["cells"]["n"]
    assert n > 0, "a flat road should occupy cells"
    arrays = header["_arrays"]["cells"]
    for name, arr in arrays.items():
        assert len(arr) == n, name
        # z_obstacle is NaN by design where a cell saw no non-ground return
        # (core/cell.py: "NaN where none seen"); every other field is a number.
        if name != "z_obstacle":
            assert np.isfinite(np.asarray(arr, dtype=np.float64)).all(), name

    z_ground = np.asarray(arrays["z_ground"], dtype=np.float64)
    z_obstacle = np.asarray(arrays["z_obstacle"], dtype=np.float64)
    seen = np.isfinite(z_obstacle)
    assert (z_obstacle[seen] >= z_ground[seen]).all(), \
        "an obstacle below its own ground — cell.py clamps this case"

    stats = header["stats"]
    for key, value in stats.items():
        assert value == value, f"stats.{key} is NaN"          # NaN != NaN
        assert value is not None, f"stats.{key} is null"
    assert stats["n_points"] > 0
    assert stats["n_points_conserved"] == stats["n_points"], "FR-10 on the wire"
    assert stats["n_cells_occupied"] == n
    assert stats["reduction"] > 1.0

    decision = header["decision"]
    assert decision["reason"], "FR-23: a decision always states a reason"
    assert decision["risk"]
    assert decision["route"]
    assert "{" not in decision["reason"], "unformatted placeholder in the reason"


# ---------------------------------------------------------------------------
# T-P6 — the mode on the wire is the mode that ran
# ---------------------------------------------------------------------------

def test_TP6_geometric_mode(cfg, kitti_root):
    header = _first_frame(cfg, "geometric", kitti_root)
    assert header["mode"] == "geometric"
    _assert_valid_frame(header)


def test_TP6_cached_mode_reads_the_cache(cfg, kitti_root, cache_dir):
    header = _first_frame(cfg, "cached", kitti_root, cache_dir=cache_dir)
    assert header["mode"] == "cached"
    _assert_valid_frame(header)

    classes = set(np.unique(header["_arrays"]["cells"]["class_id"]))
    assert classes == {CACHE_SENTINEL_CLASS}, (
        "cells carry classes the cache does not hold — the cache was missed and "
        "a segmenter ran instead"
    )


def test_TP6_live_mode(cfg, kitti_root):
    model = Path(cfg.perception.model)
    if not model.is_absolute():
        model = Path(__file__).resolve().parents[1] / model
    if not model.is_file():
        pytest.skip(f"no ONNX model at {model} — run tools/export_onnx.py")

    header = _first_frame(_cfg_with_model(cfg, model), "live", kitti_root)
    assert header["mode"] == "live"
    _assert_valid_frame(header)


# ---------------------------------------------------------------------------
# The fallbacks rewrite the mode, so the HUD cannot lie (FR-6)
# ---------------------------------------------------------------------------

def test_TP6_a_missing_cache_falls_back_and_says_geometric(cfg, kitti_root, tmp_path):
    header = _first_frame(cfg, "cached", kitti_root, cache_dir=tmp_path / "nothing")
    assert header["mode"] == "geometric", (
        "the cache was missing, geometric ran, and the wire still said 'cached'"
    )
    _assert_valid_frame(header)


def test_TP6_a_missing_model_falls_back_and_says_geometric(cfg, kitti_root, tmp_path):
    cfg_missing = _cfg_with_model(cfg, tmp_path / "no-such-model.onnx")
    header = _first_frame(cfg_missing, "live", kitti_root)
    assert header["mode"] == "geometric"
    _assert_valid_frame(header)


def test_the_default_cache_directory_is_where_build_cache_writes():
    """`data/cache/<seq>` never exists; caches are keyed by builder, not sequence.

    The regression this pins: `--infer cached` looked for `data/cache/04`, found
    nothing, and ran the geometric segmenter on every demo run.
    """
    assert DEFAULT_CACHE_DIR == Path("data/cache/network")
    assert not DEFAULT_CACHE_DIR.name.isdigit()


# ---------------------------------------------------------------------------
# Fixtures mode, and the threaded path the server actually uses
# ---------------------------------------------------------------------------

def test_TP6_fixtures_mode_is_a_valid_frame(cfg, kitti_root):
    header = _first_frame(cfg, "fixtures", kitti_root)
    _assert_valid_frame(header)


def test_frames_reach_the_queue_through_the_worker_thread(cfg, kitti_root):
    q: queue.Queue = queue.Queue(maxsize=2)
    worker = PipelineWorker(cfg, "geometric", q, seq=SEQ, data_root=kitti_root)
    worker.start()
    try:
        header = decode(q.get(timeout=30.0))
    finally:
        worker.stop()
    assert header["mode"] == "geometric"
    _assert_valid_frame(header)
