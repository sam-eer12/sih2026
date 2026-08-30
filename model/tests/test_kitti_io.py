"""SemanticKITTI readers and writers."""

from __future__ import annotations

import numpy as np
import pytest

from avr25d.io import kitti
from avr25d.perception import labelmap
from avr25d.synth import raycast
from avr25d.synth.export import export_kitti


def test_velodyne_round_trip(tmp_path):
    rng = np.random.default_rng(0)
    xyz = rng.normal(0, 10, size=(500, 3)).astype(np.float32)
    intensity = rng.random(500).astype(np.float32)

    path = tmp_path / "velodyne" / "000000.bin"
    kitti.write_velodyne(path, xyz, intensity)
    got_xyz, got_i = kitti.read_velodyne(path)

    assert np.array_equal(got_xyz, xyz)
    assert np.array_equal(got_i, intensity)
    assert got_xyz.dtype == np.float32 and got_xyz.flags["C_CONTIGUOUS"]


def test_label_round_trip(tmp_path):
    semantic = np.array([40, 252, 50, 0], dtype=np.uint32)
    instance = np.array([0, 3, 1, 0], dtype=np.uint32)
    packed = kitti.pack_labels(semantic, instance)

    path = tmp_path / "labels" / "000000.label"
    kitti.write_labels(path, packed)
    got = kitti.read_labels(path, n_points=4)

    assert np.array_equal(got, packed)
    sem, inst = labelmap.split_label(got)
    assert np.array_equal(sem, semantic)
    assert np.array_equal(inst, instance)


def test_truncated_scan_is_rejected(tmp_path):
    path = tmp_path / "000000.bin"
    np.arange(7, dtype=np.float32).tofile(path)   # not a multiple of 4
    with pytest.raises(ValueError, match="not a multiple of 4"):
        kitti.read_velodyne(path)


def test_label_count_mismatch_is_rejected(tmp_path):
    path = tmp_path / "000000.label"
    np.zeros(3, dtype=np.uint32).tofile(path)
    with pytest.raises(ValueError, match="disagree"):
        kitti.read_labels(path, n_points=4)


def test_read_scan_merges_labels(tmp_path, scenes, sensor):
    xyzi, packed = raycast(scenes["S5_crossing_truck"], sensor)
    export_kitti(xyzi, packed, tmp_path, 0)

    scan = kitti.read_scan(
        tmp_path / "velodyne" / "000000.bin",
        tmp_path / "labels" / "000000.label",
    )
    assert scan.has_labels
    assert scan.frame_id == 0
    assert scan.n_points == xyzi.shape[0]
    assert np.array_equal(scan.xyz, xyzi[:, :3])
    assert scan.avr_label.dtype == np.uint8
    assert set(np.unique(scan.avr_label).tolist()) <= set(range(5))
    assert scan.moving.any(), "the moving truck should carry the moving-* annotation"
    assert scan.range.shape == (scan.n_points,)


def test_read_scan_without_labels_does_not_raise(tmp_path):
    kitti.write_velodyne(
        tmp_path / "velodyne" / "000012.bin",
        np.zeros((4, 3), np.float32),
        np.zeros(4, np.float32),
    )
    scan = kitti.read_scan(tmp_path / "velodyne" / "000012.bin")
    assert not scan.has_labels
    assert scan.frame_id == 12          # parsed from the filename
    assert np.all(scan.avr_label == labelmap.VOID)


def test_sequence_indexes_a_generated_scene(tmp_path, scenes, sensor):
    scene = scenes["S1_flat_road"]
    for frame in range(3):
        xyzi, packed = raycast(scene, sensor, t_scene=frame * 0.1)
        export_kitti(xyzi, packed, tmp_path, frame)

    seq = kitti.KittiSequence(tmp_path)
    assert len(seq) == 3
    assert seq.has_labels
    assert [s.frame_id for s in seq] == [0, 1, 2]
    assert "3 scans" in repr(seq)


def test_sequence_limit_and_missing_directory(tmp_path, scenes, sensor):
    for frame in range(4):
        xyzi, packed = raycast(scenes["S1_flat_road"], sensor)
        export_kitti(xyzi, packed, tmp_path, frame)
    assert len(kitti.KittiSequence(tmp_path, limit=2)) == 2
    with pytest.raises(FileNotFoundError, match="velodyne"):
        kitti.KittiSequence(tmp_path / "nope")
