"""Geometric fallback segmenter (FR-5).

T-P1 and T-P5 live here.  The per-object tests beyond them are not in the plan
but are the ones that would have caught the two real defects found while
writing this module: a bridge pier passing the vehicle gate and getting
tracked as a lorry, and an overpass deck passing the raised-ground gate and
being called a footway at 3.1 m.  Both were invisible in an aggregate accuracy
number and obvious per object.
"""

from __future__ import annotations

import numpy as np
import pytest

from avr25d.perception import geometric_seg as gs
from avr25d.perception import labelmap

DRIVABLE = labelmap.DRIVABLE
TERRAIN = labelmap.NON_DRIVABLE_TERRAIN
STATIC = labelmap.STATIC_OBSTACLE
DYNAMIC = labelmap.DYNAMIC_OBJECT


@pytest.fixture(scope="module")
def predictions(casts, cfg):
    return {
        name: gs.segment(c["xyzi"][:, :3], c["xyzi"][:, 3], cfg)
        for name, c in casts.items()
    }


def _dominant_class(pred, instance, instance_id):
    member = instance == instance_id
    assert member.sum() > 0, f"no returns for instance {instance_id}"
    return int(np.bincount(pred[member], minlength=5).argmax()), int(member.sum())


# --------------------------------------------------------------------------
# T-P1 — one label per point, all in range
# --------------------------------------------------------------------------

def test_one_label_per_point_all_in_range(predictions, casts):
    """T-P1."""
    for name, pred in predictions.items():
        assert pred.shape == (casts[name]["xyzi"].shape[0],), name
        assert pred.dtype == np.uint8, name
        assert pred.min() >= 0 and pred.max() < labelmap.N_CLASSES, name


def test_empty_cloud_returns_empty(cfg):
    out = gs.segment(np.zeros((0, 3), np.float32), np.zeros(0, np.float32), cfg)
    assert out.shape == (0,) and out.dtype == np.uint8


def test_degenerate_cloud_does_not_raise(cfg):
    """Two points cannot define a plane; the segmenter must say so, not crash."""
    out = gs.segment(
        np.array([[1.0, 0, 0], [2.0, 0, 0]], np.float32),
        np.zeros(2, np.float32),
        cfg,
    )
    assert out.shape == (2,)


def test_is_deterministic(casts, cfg):
    """FR-24's spirit: the same scan twice gives the same labels, byte for byte."""
    xyz = casts["S5_crossing_truck"]["xyzi"][:, :3]
    i = casts["S5_crossing_truck"]["xyzi"][:, 3]
    assert np.array_equal(gs.segment(xyz, i, cfg), gs.segment(xyz, i, cfg))


def test_does_not_depend_on_intensity(casts, cfg):
    """A fallback that quietly needs a calibrated intensity channel is not one."""
    xyz = casts["S3_overhang"]["xyzi"][:, :3]
    real = casts["S3_overhang"]["xyzi"][:, 3]
    assert np.array_equal(
        gs.segment(xyz, real, cfg), gs.segment(xyz, np.zeros_like(real), cfg)
    )


# --------------------------------------------------------------------------
# T-P5 — the control scene
# --------------------------------------------------------------------------

def test_flat_road_is_drivable(predictions, casts):
    """T-P5 — at least 95% of ground points on S1 classify as DRIVABLE."""
    pred = predictions["S1_flat_road"]
    truth = casts["S1_flat_road"]["avr"]
    ground = truth == DRIVABLE
    recall = float((pred[ground] == DRIVABLE).mean())
    assert recall >= 0.95, f"DRIVABLE recall {recall:.4f}"


def test_flat_road_produces_no_obstacles(predictions):
    """The false-positive half: a bare road must not grow furniture."""
    pred = predictions["S1_flat_road"]
    assert not np.any((pred == STATIC) | (pred == DYNAMIC))


# --------------------------------------------------------------------------
# Ground-plane fit
# --------------------------------------------------------------------------

def test_ground_plane_is_level_and_at_sensor_height(casts, cfg, sensor):
    plane = gs.fit_ground_plane(casts["S1_flat_road"]["xyzi"][:, :3], cfg)
    assert plane is not None
    assert plane.tilt_deg < 1.0
    # The plane passes through z = -sensor_height in the sensor frame.
    origin_height = float(np.array([0.0, 0.0, 0.0]) @ plane.normal + plane.d)
    assert origin_height == pytest.approx(sensor.sensor_height, abs=0.05)


def test_a_wall_does_not_become_the_ground(cfg):
    """The tilt gate: more coplanar points on a wall must not invert the fit."""
    rng = np.random.default_rng(0)
    ground = np.column_stack([
        rng.uniform(-20, 20, 2000), rng.uniform(-20, 20, 2000),
        np.full(2000, -1.7) + rng.normal(0, 0.02, 2000),
    ])
    wall = np.column_stack([                      # 4x as many points, vertical
        np.full(8000, 8.0) + rng.normal(0, 0.02, 8000),
        rng.uniform(-20, 20, 8000), rng.uniform(-1.7, 10, 8000),
    ])
    plane = gs.fit_ground_plane(
        np.vstack([ground, wall]).astype(np.float32), cfg
    )
    assert plane is not None
    assert plane.tilt_deg < cfg.perception.geometric.max_normal_tilt_deg


# --------------------------------------------------------------------------
# Per-object behaviour
# --------------------------------------------------------------------------

def test_overpass_deck_is_structure_not_raised_ground(predictions, casts, scenes):
    """A large flat cluster 3.1 m in the air is a deck, not a footway."""
    truth = scenes["S3_overhang"].ground_truth["hazards"][0]
    cls, n = _dominant_class(
        predictions["S3_overhang"], casts["S3_overhang"]["instance"],
        truth["instance_id"],
    )
    assert cls == STATIC, f"deck ({n} returns) classified {labelmap.CLASS_NAMES[cls]}"


def test_bridge_piers_are_structure_not_traffic(predictions, casts):
    """The aspect gate: a 1.2 m wide, 3.1 m tall cylinder is not a lorry."""
    pred, inst = predictions["S3_overhang"], casts["S3_overhang"]["instance"]
    for pier in (2, 3):
        cls, n = _dominant_class(pred, inst, pier)
        assert cls == STATIC, (
            f"pier {pier} ({n} returns) classified {labelmap.CLASS_NAMES[cls]}"
        )


def test_road_beneath_the_overhang_stays_drivable(predictions, casts):
    pred, c = predictions["S3_overhang"], casts["S3_overhang"]
    beneath = (
        (c["xyzi"][:, 0] > 26.0) & (c["xyzi"][:, 0] < 50.0)
        & (np.abs(c["xyzi"][:, 1]) < 3.0) & (c["z_road"] < 1.0)
    )
    assert beneath.sum() > 100
    assert float((pred[beneath] == DRIVABLE).mean()) > 0.99


def test_truck_is_dynamic_and_poles_are_not(predictions, casts, scenes):
    pred, inst = predictions["S5_crossing_truck"], casts["S5_crossing_truck"]["instance"]
    truck_id = scenes["S5_crossing_truck"].ground_truth["hazards"][0]["instance_id"]
    cls, _ = _dominant_class(pred, inst, truck_id)
    assert cls == DYNAMIC
    for pole in (2, 3):
        cls, n = _dominant_class(pred, inst, pole)
        assert cls == STATIC, (
            f"static pole {pole} ({n} returns) became "
            f"{labelmap.CLASS_NAMES[cls]} — a tracker seeded from this would "
            "carry a phantom track"
        )


def test_raised_footway_is_terrain_not_a_wall(predictions, casts):
    """The slab gate: a 120 m kerb line is raised ground, not a building."""
    cls, _ = _dominant_class(
        predictions["S4_curb"], casts["S4_curb"]["instance"], 2,   # the footway
    )
    assert cls == TERRAIN


def test_pothole_floor_is_never_called_an_obstacle(predictions, casts, scenes):
    """There is nothing in a hole to hit.  The grid detects it geometrically."""
    truth = scenes["S2_pothole"].ground_truth["hazards"][0]
    pred, inst = predictions["S2_pothole"], casts["S2_pothole"]["instance"]
    member = inst == truth["instance_id"]
    assert member.sum() > 0
    assert not np.any((pred[member] == STATIC) | (pred[member] == DYNAMIC))


# --------------------------------------------------------------------------
# Clustering
# --------------------------------------------------------------------------

def test_clustering_separates_well_separated_blobs(cfg):
    rng = np.random.default_rng(1)
    a = rng.normal(0, 0.1, size=(200, 3))
    b = rng.normal(0, 0.1, size=(200, 3)) + np.array([10.0, 0, 0])
    ids = gs.cluster(np.vstack([a, b]).astype(np.float32), cfg)
    assert len(np.unique(ids)) == 2
    assert len(np.unique(ids[:200])) == 1 and len(np.unique(ids[200:])) == 1


def test_clustering_handles_trivial_inputs(cfg):
    assert gs.cluster(np.zeros((0, 3), np.float32), cfg).shape == (0,)
    assert gs.cluster(np.zeros((1, 3), np.float32), cfg).shape == (1,)


def test_segmenter_wrapper_reports_latency(casts, cfg):
    seg = gs.GeometricSegmenter(cfg)
    out = seg(casts["S1_flat_road"]["xyzi"][:, :3], casts["S1_flat_road"]["xyzi"][:, 3])
    assert out.shape[0] == casts["S1_flat_road"]["xyzi"].shape[0]
    assert seg.last_latency_ms > 0.0
    assert seg.mode == "geometric"
