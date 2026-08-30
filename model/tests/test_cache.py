"""Precomputed per-scan label store.  IMPLEMENTATION_PLAN §6.7.

The cache is what makes `perception.mode: cached` a real mode rather than a
euphemism: the network runs once, overnight, over the whole subset, and the
live pipeline reads labels out of a memory map instead of paying 86 ms a frame.
Its failure mode is silence — a cache built with the wrong segmenter, or half
built, still returns plausible labels — so the tests are mostly about detecting
that, not about the happy path.
"""

from __future__ import annotations

import numpy as np
import pytest

from avr25d.io.kitti import write_velodyne
from avr25d.perception.cache import LabelCache, build_cache


class StubSegmenter:
    """Labels every point with (point index % 5), so a wrong slice is visible."""

    mode = "stub"

    def __init__(self):
        self.model_path = "stub.onnx"
        self.calls = 0
        self.last_latency_ms = 0.1

    def __call__(self, xyz, intensity):
        self.calls += 1
        return (np.arange(xyz.shape[0], dtype=np.uint8) % 5).astype(np.uint8)


@pytest.fixture
def scans(tmp_path):
    """Three scans of different lengths, so offsets have to be right."""
    root = tmp_path / "sequences" / "07" / "velodyne"
    root.mkdir(parents=True)
    rng = np.random.default_rng(20260830)
    paths = []
    for i, n in enumerate((120, 45, 301)):
        xyz = rng.normal(0.0, 20.0, (n, 3)).astype(np.float32)
        p = root / f"{i:06d}.bin"
        write_velodyne(p, xyz, rng.random(n).astype(np.float32))
        paths.append(p)
    return paths


def _expected(path):
    from avr25d.io.kitti import read_velodyne

    xyz, _ = read_velodyne(path)
    return (np.arange(xyz.shape[0], dtype=np.uint8) % 5).astype(np.uint8)


# --------------------------------------------------------------------------


def test_a_built_cache_returns_the_labels_the_segmenter_produced(scans, tmp_path):
    out = tmp_path / "cache"
    build_cache(scans, StubSegmenter(), out, verbose=False)

    cache = LabelCache(out)
    assert len(cache) == 3
    for i, path in enumerate(scans):
        np.testing.assert_array_equal(cache[i], _expected(path))


def test_frames_are_addressable_by_id_as_well_as_position(scans, tmp_path):
    out = tmp_path / "cache"
    build_cache(scans, StubSegmenter(), out, verbose=False)
    cache = LabelCache(out)

    assert cache.frame_ids == ("07/000000", "07/000001", "07/000002")
    for i, fid in enumerate(cache.frame_ids):
        np.testing.assert_array_equal(cache[fid], cache[i])


def test_storage_is_exactly_one_byte_per_point(scans, tmp_path):
    out = tmp_path / "cache"
    build_cache(scans, StubSegmenter(), out, verbose=False)

    total = sum(len(_expected(p)) for p in scans)
    assert (out / "labels.bin").stat().st_size == total
    assert LabelCache(out).n_points == total


def test_an_unknown_frame_id_names_the_id_it_could_not_find(scans, tmp_path):
    out = tmp_path / "cache"
    build_cache(scans, StubSegmenter(), out, verbose=False)
    with pytest.raises(KeyError, match="99/000000"):
        LabelCache(out)["99/000000"]


def test_labels_come_back_read_only_so_a_caller_cannot_corrupt_the_store(
    scans, tmp_path
):
    out = tmp_path / "cache"
    build_cache(scans, StubSegmenter(), out, verbose=False)
    labels = LabelCache(out)[0]
    with pytest.raises(ValueError):
        labels[0] = 9


# -- provenance: the cache has to say what made it --------------------------


def test_the_cache_records_which_segmenter_and_model_built_it(scans, tmp_path):
    out = tmp_path / "cache"
    build_cache(scans, StubSegmenter(), out, verbose=False)
    meta = LabelCache(out).meta

    assert meta["mode"] == "stub"
    assert meta["model"] == "stub.onnx"
    assert meta["n_frames"] == 3
    assert "created" in meta


def test_a_cache_built_by_a_different_segmenter_is_not_silently_extended(
    scans, tmp_path
):
    out = tmp_path / "cache"
    build_cache(scans[:1], StubSegmenter(), out, verbose=False)

    other = StubSegmenter()
    other.mode = "geometric"
    with pytest.raises(ValueError, match="stub.*geometric|geometric.*stub"):
        build_cache(scans, other, out, verbose=False)


# -- an overnight job has to survive being interrupted ----------------------


def test_rebuilding_skips_scans_that_are_already_cached(scans, tmp_path):
    out = tmp_path / "cache"
    build_cache(scans[:2], StubSegmenter(), out, verbose=False)

    resumed = StubSegmenter()
    build_cache(scans, resumed, out, verbose=False)
    assert resumed.calls == 1, "only the missing scan should be segmented again"

    cache = LabelCache(out)
    assert len(cache) == 3
    for i, path in enumerate(scans):
        np.testing.assert_array_equal(cache[i], _expected(path))


def test_a_blob_that_does_not_match_its_index_is_refused(scans, tmp_path):
    out = tmp_path / "cache"
    build_cache(scans, StubSegmenter(), out, verbose=False)

    blob = out / "labels.bin"
    blob.write_bytes(blob.read_bytes()[:-10])
    with pytest.raises(ValueError, match="labels.bin"):
        LabelCache(out)


def test_opening_a_directory_with_no_cache_in_it_says_so(tmp_path):
    with pytest.raises(FileNotFoundError, match="index.json"):
        LabelCache(tmp_path)


def test_a_cache_of_no_scans_is_empty_but_valid(tmp_path):
    out = tmp_path / "cache"
    build_cache([], StubSegmenter(), out, verbose=False)
    cache = LabelCache(out)
    assert len(cache) == 0
    assert cache.n_points == 0


def test_build_reports_progress_when_asked(scans, tmp_path, capsys):
    build_cache(scans, StubSegmenter(), tmp_path / "cache", verbose=True)
    out = capsys.readouterr().out
    assert "3" in out
