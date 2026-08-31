"""Range-binned accuracy and object recall (§6.11, FR-33, FR-34).  T-B3, T-B4.

The binning is the part of the evaluation most likely to be wrong in a way
nobody notices: a point dropped between two bins, or double-counted across
them, moves a headline mIoU without ever failing loudly.  T-B3 exists to make
that impossible, so it is asserted as a partition, not as a spot check.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from avr25d.bench import distance_bins as db
from avr25d.perception import labelmap as lm


def _ring(radii, n_each=1):
    """Points on the +x axis at the given radii."""
    r = np.repeat(np.asarray(radii, dtype=np.float32), n_each)
    xyz = np.zeros((r.size, 3), dtype=np.float32)
    xyz[:, 0] = r
    return xyz


# --- T-B3: the binning is a partition --------------------------------------

def test_the_four_bins_are_the_fr33_bins():
    assert db.BIN_EDGES_M == (0.0, 10.0, 30.0, 60.0, 100.0)
    assert db.BIN_NAMES == ("0-10m", "10-30m", "30-60m", "60-100m")


def test_every_point_lands_in_exactly_one_bin():
    xyz = _ring([0.5, 9.99, 10.0, 29.9, 30.0, 59.9, 60.0, 99.9, 100.0])
    b = db.assign_bins(xyz)
    assert b.tolist() == [0, 0, 1, 1, 2, 2, 3, 3, 3]


def test_bin_boundaries_are_half_open_upward():
    """Exactly 10.0 m belongs to 10-30, not to 0-10.  Stated, because a
    boundary convention nobody wrote down is a boundary convention somebody
    will get wrong."""
    xyz = _ring([10.0, 30.0, 60.0])
    assert db.assign_bins(xyz).tolist() == [1, 2, 3]


def test_the_final_bin_is_closed_at_the_100m_envelope():
    """r = 100.0 is inside the sensing envelope, so it must be counted."""
    assert db.assign_bins(_ring([100.0])).tolist() == [3]
    assert db.assign_bins(_ring([100.001])).tolist() == [-1]


def test_points_beyond_the_envelope_are_marked_not_silently_binned():
    xyz = _ring([50.0, 150.0])
    assert db.assign_bins(xyz).tolist() == [2, -1]


def test_bin_counts_sum_to_the_points_inside_the_envelope():
    """T-B3 as literally written: bins sum to the total."""
    rng = np.random.default_rng(20260830)
    xyz = rng.uniform(-120, 120, size=(4_000, 3)).astype(np.float32)
    b = db.assign_bins(xyz)
    counts = np.bincount(b[b >= 0], minlength=len(db.BIN_NAMES))
    assert counts.sum() == int((b >= 0).sum())
    assert counts.sum() + int((b < 0).sum()) == xyz.shape[0]


def test_binning_ignores_height():
    """Range is horizontal, matching how the grid and PS-6 define radius."""
    xyz = np.array([[20.0, 0.0, 0.0], [20.0, 0.0, 40.0]], dtype=np.float32)
    assert db.assign_bins(xyz).tolist() == [1, 1]


# --- IoU and mIoU ----------------------------------------------------------

def test_perfect_prediction_scores_iou_one_everywhere():
    truth = np.array([1, 1, 2, 3, 4], dtype=np.uint8)
    cm = db.confusion(truth, truth)
    iou = db.iou_per_class(cm)
    assert np.allclose(iou[[1, 2, 3, 4]], 1.0)


def test_iou_matches_a_hand_computed_value():
    #  truth: 3 x DRIVABLE, 1 x TERRAIN.  pred: 2 right, 1 DRIVABLE->TERRAIN,
    #  1 TERRAIN correct.  DRIVABLE: TP=2 FP=0 FN=1 -> 2/3.
    #  TERRAIN:  TP=1 FP=1 FN=0 -> 1/2.
    truth = np.array([1, 1, 1, 2], dtype=np.uint8)
    pred = np.array([1, 1, 2, 2], dtype=np.uint8)
    iou = db.iou_per_class(db.confusion(truth, pred))
    assert iou[lm.DRIVABLE] == pytest.approx(2 / 3)
    assert iou[lm.NON_DRIVABLE_TERRAIN] == pytest.approx(0.5)


def test_a_class_absent_from_both_truth_and_prediction_is_nan_not_zero():
    """Scoring an absent class as 0.0 drags mIoU down for a class nobody was
    ever asked about.  SemanticKITTI excludes it; so do we."""
    truth = np.array([1, 1], dtype=np.uint8)
    iou = db.iou_per_class(db.confusion(truth, truth))
    assert np.isnan(iou[lm.DYNAMIC_OBJECT])


def test_miou_excludes_void_by_default():
    """Ground-truth 'unlabeled' is ~2% of KITTI points and SemanticKITTI
    excludes it from mIoU.  The published 0.823/0.868 figures do too."""
    truth = np.array([0, 1, 2], dtype=np.uint8)
    pred = np.array([1, 1, 2], dtype=np.uint8)     # VOID predicted wrong
    cm = db.confusion(truth, pred)
    assert db.miou(cm) == pytest.approx(1.0)
    assert db.miou(cm, exclude=()) < 1.0


def test_a_void_truth_point_does_not_become_a_false_positive():
    """Excluding VOID from the mean is not enough.  A point whose truth is
    'unlabeled' but which the model called DRIVABLE must not depress
    DRIVABLE's IoU — nobody asked it to classify that point."""
    truth = np.array([0, 1], dtype=np.uint8)
    pred = np.array([1, 1], dtype=np.uint8)
    scored = db.drop_excluded_truth(db.confusion(truth, pred), (lm.VOID,))
    assert db.iou_per_class(scored)[lm.DRIVABLE] == pytest.approx(1.0)


def test_predicting_void_on_a_real_class_still_counts_against_it():
    """Deliberately asymmetric with the row drop: refusing to answer is an
    error, not a free pass.  The geometric segmenter can emit VOID and must
    not be flattered for it."""
    truth = np.array([1, 1], dtype=np.uint8)
    pred = np.array([1, 0], dtype=np.uint8)          # one refusal
    scored = db.drop_excluded_truth(db.confusion(truth, pred), (lm.VOID,))
    assert db.iou_per_class(scored)[lm.DRIVABLE] == pytest.approx(0.5)
    assert db.miou(db.confusion(truth, pred)) == pytest.approx(0.5)


def test_n_points_scored_reports_what_the_metrics_actually_covered():
    xyz = _ring([5.0, 6.0])
    truth = np.array([0, 1], dtype=np.uint8)          # half the scan is VOID
    out = db.evaluate(truth, truth, xyz)
    assert out["overall"]["n_points"] == 2
    assert out["overall"]["n_points_scored"] == 1


def test_miou_of_no_scorable_class_is_nan():
    truth = np.array([0, 0], dtype=np.uint8)
    assert np.isnan(db.miou(db.confusion(truth, truth)))


# --- the binned evaluation -------------------------------------------------

def test_evaluate_reports_overall_and_every_bin():
    xyz = _ring([5.0, 20.0, 45.0, 80.0])
    truth = np.array([1, 1, 3, 3], dtype=np.uint8)
    pred = np.array([1, 2, 3, 3], dtype=np.uint8)
    out = db.evaluate(pred, truth, xyz)
    assert set(out["bins"]) == set(db.BIN_NAMES)
    assert out["overall"]["n_points"] == 4
    assert sum(b["n_points"] for b in out["bins"].values()) == 4


def test_evaluate_reports_an_empty_bin_as_empty_rather_than_perfect():
    """A bin with no points must not report mIoU 1.0 — the Day 3 numbers had
    exactly this shape at 60-100 m, and 0.000 there is information."""
    xyz = _ring([5.0, 6.0])
    truth = np.array([1, 1], dtype=np.uint8)
    out = db.evaluate(truth, truth, xyz)
    far = out["bins"]["60-100m"]
    assert far["n_points"] == 0
    assert far["miou"] is None


def test_evaluate_counts_points_outside_the_envelope_separately():
    xyz = _ring([5.0, 500.0])
    truth = np.array([1, 1], dtype=np.uint8)
    out = db.evaluate(truth, truth, xyz)
    assert out["n_points_outside_envelope"] == 1
    assert out["overall"]["n_points"] == 1


def test_evaluate_is_json_serialisable():
    xyz = _ring([5.0, 20.0, 45.0, 80.0])
    truth = np.array([1, 2, 3, 4], dtype=np.uint8)
    json.dumps(db.evaluate(truth, truth, xyz))


# --- streaming accumulation over a sequence --------------------------------

def test_accumulating_scans_equals_evaluating_them_concatenated():
    """The harness cannot hold 271 scans x 125k points in memory, so it
    accumulates.  Accumulating must give byte-identical answers to the
    all-at-once evaluation, or the streaming path is its own untested metric.
    """
    rng = np.random.default_rng(20260831)
    scans = []
    for _ in range(3):
        n = 500
        xyz = rng.uniform(-90, 90, size=(n, 3)).astype(np.float32)
        truth = rng.integers(0, 5, size=n).astype(np.uint8)
        pred = np.where(rng.random(n) < 0.7, truth,
                        rng.integers(0, 5, size=n).astype(np.uint8)).astype(np.uint8)
        scans.append((xyz, truth, pred))

    acc = db.BinnedAccumulator()
    for xyz, truth, pred in scans:
        acc.add(pred, truth, xyz)

    all_xyz = np.concatenate([s[0] for s in scans])
    all_truth = np.concatenate([s[1] for s in scans])
    all_pred = np.concatenate([s[2] for s in scans])

    assert acc.result() == db.evaluate(all_pred, all_truth, all_xyz)


def test_accumulator_with_no_scans_reports_empty_rather_than_perfect():
    out = db.BinnedAccumulator().result()
    assert out["overall"]["n_points"] == 0
    assert out["overall"]["miou"] is None


def test_accumulator_tracks_the_scan_count():
    acc = db.BinnedAccumulator()
    xyz = _ring([5.0, 20.0])
    truth = np.array([1, 1], dtype=np.uint8)
    acc.add(truth, truth, xyz)
    acc.add(truth, truth, xyz)
    assert acc.n_scans == 2


# --- T-B4: object recall ---------------------------------------------------

def test_object_recall_matches_a_hand_computed_value():
    """Three objects at known ranges.  Two are recovered, one is not.

    obj 1 (car, r=5 m):    4 points, 4 predicted DYNAMIC_OBJECT  -> hit
    obj 2 (pole, r=20 m):  4 points, 1 predicted STATIC_OBSTACLE -> miss (25%)
    obj 3 (car, r=45 m):   4 points, 3 predicted DYNAMIC_OBJECT  -> hit (75%)
    """
    xyz = _ring([5.0, 20.0, 45.0], n_each=4)
    truth = np.array([4, 4, 4, 4, 3, 3, 3, 3, 4, 4, 4, 4], dtype=np.uint8)
    inst = np.array([1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3], dtype=np.uint32)
    pred = np.array([4, 4, 4, 4,
                     3, 1, 1, 1,
                     4, 4, 4, 1], dtype=np.uint8)
    out = db.object_recall(pred, truth, inst, xyz, min_points=1, hit_fraction=0.5)
    assert out["overall"]["n_objects"] == 3
    assert out["overall"]["n_recalled"] == 2
    assert out["overall"]["recall"] == pytest.approx(2 / 3)


def test_object_recall_is_reported_per_range_bin():
    xyz = _ring([5.0, 45.0], n_each=4)
    truth = np.full(8, lm.DYNAMIC_OBJECT, dtype=np.uint8)
    inst = np.array([1, 1, 1, 1, 2, 2, 2, 2], dtype=np.uint32)
    pred = np.array([4, 4, 4, 4, 1, 1, 1, 1], dtype=np.uint8)
    out = db.object_recall(pred, truth, inst, xyz, min_points=1)
    assert out["bins"]["0-10m"]["recall"] == pytest.approx(1.0)
    assert out["bins"]["30-60m"]["recall"] == pytest.approx(0.0)
    assert out["bins"]["10-30m"]["n_objects"] == 0
    assert out["bins"]["10-30m"]["recall"] is None


def test_object_recall_is_reported_per_class():
    xyz = _ring([5.0, 6.0], n_each=4)
    truth = np.array([4, 4, 4, 4, 3, 3, 3, 3], dtype=np.uint8)
    inst = np.array([1, 1, 1, 1, 2, 2, 2, 2], dtype=np.uint32)
    pred = np.array([4, 4, 4, 4, 1, 1, 1, 1], dtype=np.uint8)
    out = db.object_recall(pred, truth, inst, xyz, min_points=1)
    assert out["classes"]["DYNAMIC_OBJECT"]["recall"] == pytest.approx(1.0)
    assert out["classes"]["STATIC_OBSTACLE"]["recall"] == pytest.approx(0.0)


def test_objects_below_the_minimum_point_count_are_excluded():
    """A 3-point return is not a detection opportunity, and counting it as a
    miss would penalise the segmenter for the sensor's beam pitch.  The
    threshold is explicit so the number can be defended."""
    xyz = _ring([50.0], n_each=3)
    truth = np.full(3, lm.DYNAMIC_OBJECT, dtype=np.uint8)
    inst = np.full(3, 1, dtype=np.uint32)
    pred = np.full(3, lm.DRIVABLE, dtype=np.uint8)
    out = db.object_recall(pred, truth, inst, xyz, min_points=5)
    assert out["overall"]["n_objects"] == 0
    assert out["overall"]["recall"] is None
    assert out["n_objects_below_min_points"] == 1


def test_recall_accumulator_sums_detection_opportunities_across_scans():
    """Across a sequence, each scan is a fresh detection opportunity for the
    objects visible in it — the same truck at frame 10 and frame 11 is two
    chances to see it, not one.  Counts therefore sum."""
    xyz = _ring([5.0], n_each=4)
    truth = np.full(4, lm.DYNAMIC_OBJECT, dtype=np.uint8)
    inst = np.full(4, 1, dtype=np.uint32)
    hit = truth.copy()
    miss = np.full(4, lm.DRIVABLE, dtype=np.uint8)

    acc = db.RecallAccumulator(min_points=1)
    acc.add(hit, truth, inst, xyz)      # seen
    acc.add(miss, truth, inst, xyz)     # missed
    out = acc.result()
    assert out["overall"]["n_objects"] == 2
    assert out["overall"]["n_recalled"] == 1
    assert out["overall"]["recall"] == pytest.approx(0.5)
    assert out["bins"]["0-10m"]["n_objects"] == 2


def test_recall_accumulator_with_no_scans_reports_none():
    out = db.RecallAccumulator().result()
    assert out["overall"]["n_objects"] == 0
    assert out["overall"]["recall"] is None


def test_instance_zero_is_not_an_object():
    """SemanticKITTI uses instance 0 for 'no instance' — stuff, not things."""
    xyz = _ring([5.0], n_each=4)
    truth = np.full(4, lm.STATIC_OBSTACLE, dtype=np.uint8)
    inst = np.zeros(4, dtype=np.uint32)
    out = db.object_recall(truth, truth, inst, xyz, min_points=1)
    assert out["overall"]["n_objects"] == 0


def test_only_thing_classes_count_as_objects():
    """Road and terrain have no object identity; recall over them is
    meaningless and would dilute the number FR-34 asks for."""
    xyz = _ring([5.0], n_each=4)
    truth = np.full(4, lm.DRIVABLE, dtype=np.uint8)
    inst = np.full(4, 7, dtype=np.uint32)
    out = db.object_recall(truth, truth, inst, xyz, min_points=1)
    assert out["overall"]["n_objects"] == 0
    assert db.OBJECT_CLASSES == (lm.STATIC_OBSTACLE, lm.DYNAMIC_OBJECT)
