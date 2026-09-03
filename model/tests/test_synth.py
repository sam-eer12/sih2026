"""Synthetic scenes and their exact ground truth (PRD §9.3).

These tests do two different jobs and it is worth keeping them apart.

The *ground-truth* tests assert that what ``ground_truth()`` reports is exactly
what the CSV says — this is T-W5, and it is what makes the numbers in PRD §11.4
traceable to a spec file rather than to a render.

The *geometry* tests assert that the ray-caster actually produces the hazard
the CSV describes, to within sensor noise.  They are the upstream half of
T-H1…T-H4: if the pothole is not in the point cloud, no amount of correct grid
code will detect it, and the failure would otherwise be diagnosed in the wrong
module.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from avr25d.perception import labelmap
from avr25d.synth import raycast
from avr25d.synth.scenegen import generate, ground_truth, list_scenes, load_scene

NOISE_TOL = 0.05     # m — T-H1/T-H2 tolerance; 2.5x the 0.02 m range sigma


# --------------------------------------------------------------------------
# Loading and ground truth
# --------------------------------------------------------------------------

def test_all_seven_scenes_are_present():
    """The five of PRD §9.3 plus the two adversarial ones from Days 9 and 10."""
    names = {p.stem for p in list_scenes()}
    assert names == {
        "S1_flat_road", "S2_pothole", "S3_overhang",
        "S4_curb", "S5_crossing_truck",
        "S6_occluded_pothole", "S7_tunnel_curb",
    }


def test_scenes_load_with_sane_primitives(scenes):
    for name, scene in scenes.items():
        assert scene.primitives, name
        assert scene.n_frames >= 1
        for p in scene.primitives:
            assert p.kind in {"plane", "box", "cyl", "pit"}, (name, p.kind)
            assert 0 <= p.class_id < labelmap.N_CLASSES, (name, p.class_id)


def test_ground_truth_is_json_serialisable(scenes):
    for scene in scenes.values():
        json.dumps(scene.ground_truth)      # raises if anything is a numpy scalar


def test_ground_truth_matches_the_csv_exactly(scenes):
    """T-W5 — every reported number is read back off the primitive that made it."""
    gt = {n: s.ground_truth for n, s in scenes.items()}

    assert gt["S1_flat_road"]["hazards"] == []
    assert gt["S1_flat_road"]["expect_no_hazards"] is True

    pothole = gt["S2_pothole"]["hazards"][0]
    assert pothole["tag"] == "pothole"
    assert pothole["depth_m"] == 0.22
    assert pothole["length_m"] == 1.4
    assert pothole["floor_z_road_m"] == -0.22
    assert pothole["rim_z_road_m"] == 0.0            # rim flush with the road
    assert pothole["range_m"] == pytest.approx(np.hypot(12.0, -0.5))

    clearance = gt["S3_overhang"]["hazards"][0]
    assert clearance["tag"] == "clearance"
    assert clearance["clearance_m"] == 3.10
    assert clearance["underside_z_sensor_m"] == pytest.approx(3.10 - 1.70)

    step = gt["S4_curb"]["hazards"][0]
    assert step["tag"] == "step"
    assert step["height_m"] == 0.15

    track = gt["S5_crossing_truck"]["hazards"][0]
    assert track["tag"] == "track"
    assert track["speed_mps"] == 8.0
    assert gt["S5_crossing_truck"]["n_frames"] == 40
    assert len(track["positions_xy_m"]) == 40


def test_track_ground_truth_positions_follow_the_stated_speed(scenes):
    track = scenes["S5_crossing_truck"].ground_truth["hazards"][0]
    pos = np.array(track["positions_xy_m"])
    step = np.linalg.norm(np.diff(pos, axis=0), axis=1)
    assert np.allclose(step, 8.0 * 0.10)          # 8 m/s at 10 Hz
    assert pos[-1, 1] - pos[0, 1] == pytest.approx(8.0 * 0.10 * 39)


def test_unknown_hazard_tag_is_rejected(scenes):
    from dataclasses import replace
    scene = scenes["S1_flat_road"]
    bad = replace(scene, primitives=(replace(scene.primitives[0], hazard="wat"),))
    with pytest.raises(ValueError, match="unknown hazard tag"):
        ground_truth(bad)


def test_missing_scene_names_the_alternatives():
    with pytest.raises(FileNotFoundError, match="S2_pothole"):
        load_scene("S9_does_not_exist")


# --------------------------------------------------------------------------
# Ray-cast geometry
# --------------------------------------------------------------------------

def test_every_cast_is_inside_the_envelope(casts, sensor):
    for name, c in casts.items():
        r = np.linalg.norm(c["xyzi"][:, :3], axis=1)
        assert r.max() <= sensor.r_max, name
        assert r.min() > 0.0, name
        assert c["xyzi"].dtype == np.float32
        assert c["packed"].shape[0] == c["xyzi"].shape[0]
        assert np.isfinite(c["xyzi"]).all(), name


def test_intensity_is_in_range(casts):
    for name, c in casts.items():
        i = c["xyzi"][:, 3]
        assert i.min() >= 0.0 and i.max() <= 1.0, name


def test_casting_is_deterministic(scenes, sensor):
    """Same seed, same bytes — scenes have to regenerate identically (NFR-5)."""
    a_pts, a_lab = raycast(scenes["S5_crossing_truck"], sensor, t_scene=0.7)
    b_pts, b_lab = raycast(scenes["S5_crossing_truck"], sensor, t_scene=0.7)
    assert np.array_equal(a_pts, b_pts)
    assert np.array_equal(a_lab, b_lab)


def test_s1_is_a_flat_road_and_nothing_else(casts, sensor):
    """The control scene: every return is the road plane, within noise."""
    c = casts["S1_flat_road"]
    assert np.all(c["avr"] == labelmap.DRIVABLE)
    assert np.abs(c["z_road"]).max() < 5 * sensor.range_sigma
    rms = float(np.sqrt(np.mean(c["z_road"] ** 2)))
    assert rms < 2 * sensor.range_sigma, f"ground-plane RMS {rms:.4f} m"


def test_s2_pothole_is_carved_to_the_specified_depth(casts, scenes):
    """The road must be *removed* over the hole, and the floor must be reachable."""
    c = casts["S2_pothole"]
    truth = scenes["S2_pothole"].ground_truth["hazards"][0]
    lo, hi = truth["footprint_xy_m"]

    inside = (
        (c["xyzi"][:, 0] >= lo[0]) & (c["xyzi"][:, 0] <= hi[0])
        & (c["xyzi"][:, 1] >= lo[1]) & (c["xyzi"][:, 1] <= hi[1])
    )
    assert inside.sum() > 0, "no returns inside the pothole footprint"

    depth = -c["z_road"][inside]
    assert depth.max() == pytest.approx(truth["depth_m"], abs=NOISE_TOL), (
        f"deepest return {depth.max():.4f} m vs true {truth['depth_m']} m"
    )
    # And nothing survives at road level inside the footprint: that would mean
    # the plane was not carved and the hole does not exist in the cloud.
    assert not np.any(depth < -3 * 0.02)


def test_s3_overhang_clearance_is_measurable_and_road_stays_drivable(casts, scenes):
    """T-H1, upstream half.  Both clauses matter — see the scene CSV."""
    c = casts["S3_overhang"]
    truth = scenes["S3_overhang"].ground_truth["hazards"][0]
    lo, hi = truth["footprint_xy_m"]

    deck = c["instance"] == truth["instance_id"]
    assert deck.sum() > 100, "the deck must be visible, not above the sensor FOV"
    lowest = float(c["z_road"][deck].min())
    assert lowest == pytest.approx(truth["clearance_m"], abs=NOISE_TOL), (
        f"measured clearance {lowest:.4f} m vs true {truth['clearance_m']} m"
    )

    beneath = (
        (c["xyzi"][:, 0] >= lo[0]) & (c["xyzi"][:, 0] <= hi[0])
        & (np.abs(c["xyzi"][:, 1]) < 3.0)
        & (c["z_road"] < 1.0)
    )
    assert beneath.sum() > 100, "the road under the deck must still be observed"
    assert np.all(c["avr"][beneath] == labelmap.DRIVABLE), (
        "ground beneath the overhang must stay DRIVABLE — flagging the whole "
        "column is the 2D failure this scene exists to disprove"
    )


def test_s4_curb_height_is_measurable(casts, scenes):
    c = casts["S4_curb"]
    truth = scenes["S4_curb"].ground_truth["hazards"][0]
    raised = c["avr"] == labelmap.NON_DRIVABLE_TERRAIN
    assert raised.sum() > 100
    top = float(np.percentile(c["z_road"][raised], 95))
    assert top == pytest.approx(truth["height_m"], abs=0.03)   # T-H3 tolerance


def test_s5_truck_crosses_at_the_stated_speed(scenes, sensor):
    """T-D2, upstream half: the motion in the cloud is the motion in the truth."""
    scene = scenes["S5_crossing_truck"]
    truth = scene.ground_truth["hazards"][0]
    dt = scene.ground_truth["frame_dt_s"]

    centroids = []
    for frame in (0, 10, 20, 30, 39):
        xyzi, packed = raycast(scene, sensor, t_scene=frame * dt)
        avr = labelmap.raw_to_avr(labelmap.split_label(packed)[0])
        moving = labelmap.raw_is_moving(labelmap.split_label(packed)[0])
        truck = (avr == labelmap.DYNAMIC_OBJECT) & moving
        assert truck.sum() > 100, f"truck lost at frame {frame}"
        centroids.append((frame, xyzi[truck, 1].mean()))

    frames = np.array([f for f, _ in centroids], dtype=float)
    ys = np.array([y for _, y in centroids], dtype=float)
    speed = np.polyfit(frames * dt, ys, 1)[0]
    assert speed == pytest.approx(truth["speed_mps"], abs=0.5)   # T-D2 tolerance


def test_moving_primitives_carry_the_moving_annotation(casts):
    """Free supervision: a velocity in the CSV becomes a moving-* raw id."""
    assert casts["S5_crossing_truck"]["moving"].sum() > 100
    for name in ("S1_flat_road", "S2_pothole", "S3_overhang", "S4_curb"):
        assert not casts[name]["moving"].any(), name


def test_static_primitives_get_stable_instance_ids(casts, scenes):
    """The ground plane is not an object; everything else is numbered."""
    c = casts["S3_overhang"]
    assert set(np.unique(c["instance"]).tolist()) == {0, 1, 2, 3}
    truth = scenes["S3_overhang"].ground_truth["hazards"][0]
    assert truth["instance_id"] == 1          # the deck is the first object
    assert np.all(c["instance"][c["avr"] == labelmap.DRIVABLE] == 0)


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

def test_generate_writes_a_readable_sequence(tmp_path, scenes, sensor):
    from avr25d.io.kitti import KittiSequence

    scene = scenes["S2_pothole"]
    gt = generate(scene, tmp_path, sensor)

    seq = KittiSequence(tmp_path)
    assert len(seq) == scene.n_frames
    assert seq[0].has_labels
    assert seq[0].n_points > 1000

    written = json.loads((tmp_path / "ground_truth.json").read_text())
    assert written == gt
    assert written["hazards"][0]["depth_m"] == 0.22
