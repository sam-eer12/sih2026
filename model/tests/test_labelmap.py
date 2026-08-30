"""Class taxonomy and the SemanticKITTI merge (PRD §6.1)."""

from __future__ import annotations

import numpy as np
import pytest

from avr25d.perception import labelmap as lm


def test_five_classes_and_matching_metadata():
    assert lm.N_CLASSES == 5
    assert len(lm.CLASS_NAMES) == 5
    assert len(lm.CLASS_COLOURS) == 5
    assert lm.CLASS_NAMES == (
        "VOID", "DRIVABLE", "NON_DRIVABLE_TERRAIN",
        "STATIC_OBSTACLE", "DYNAMIC_OBJECT",
    )
    assert all(c.startswith("#") and len(c) == 7 for c in lm.CLASS_COLOURS)


def test_every_dataset_raw_id_is_mapped():
    """No raw id the dataset can emit falls through to an accidental default."""
    unmapped = sorted(set(lm.RAW_NAMES) - set(lm.RAW_TO_AVR_SPEC))
    assert unmapped == [], f"raw ids present in the dataset but unmapped: {unmapped}"


def test_lookup_tables_match_their_specs():
    for raw, avr in lm.RAW_TO_AVR_SPEC.items():
        assert lm.RAW_TO_AVR[raw] == avr, f"raw {raw} ({lm.RAW_NAMES[raw]})"
    for raw, learn in lm.RAW_TO_LEARNING_SPEC.items():
        assert lm.RAW_TO_LEARNING[raw] == learn


@pytest.mark.parametrize(
    "raw, expected",
    [
        (0, lm.VOID), (1, lm.VOID),                       # unlabeled, outlier
        (40, lm.DRIVABLE), (44, lm.DRIVABLE), (60, lm.DRIVABLE),
        (48, lm.NON_DRIVABLE_TERRAIN), (49, lm.NON_DRIVABLE_TERRAIN),
        (70, lm.NON_DRIVABLE_TERRAIN), (72, lm.NON_DRIVABLE_TERRAIN),
        (50, lm.STATIC_OBSTACLE), (51, lm.STATIC_OBSTACLE),
        (52, lm.STATIC_OBSTACLE), (71, lm.STATIC_OBSTACLE),
        (80, lm.STATIC_OBSTACLE), (81, lm.STATIC_OBSTACLE),
        (99, lm.STATIC_OBSTACLE),
        (10, lm.DYNAMIC_OBJECT), (18, lm.DYNAMIC_OBJECT),
        (30, lm.DYNAMIC_OBJECT), (32, lm.DYNAMIC_OBJECT),
        (252, lm.DYNAMIC_OBJECT), (258, lm.DYNAMIC_OBJECT),
    ],
)
def test_prd_table_row_by_row(raw, expected):
    """Each row of PRD §6.1, asserted individually so a failure names the class."""
    assert lm.raw_to_avr(np.array([raw]))[0] == expected, lm.RAW_NAMES[raw]


def test_other_structure_and_object_are_obstacles_not_void():
    """Our one deliberate divergence from the stock learning map (PRD §6.1)."""
    assert lm.RAW_TO_AVR[52] == lm.STATIC_OBSTACLE   # other-structure
    assert lm.RAW_TO_AVR[99] == lm.STATIC_OBSTACLE   # other-object
    assert lm.RAW_TO_LEARNING[52] == 0               # ...unlike the stock map


def test_moving_ids_are_dynamic_and_flagged():
    moving = np.array(lm.MOVING_RAW_IDS)
    assert lm.MOVING_RAW_IDS == tuple(range(252, 260))
    assert np.all(lm.raw_to_avr(moving) == lm.DYNAMIC_OBJECT)
    assert np.all(lm.raw_is_moving(moving))
    # A parked car classifies the same but is not flagged: PRD §6.3 bit 5.
    assert lm.raw_to_avr(np.array([10]))[0] == lm.DYNAMIC_OBJECT
    assert not lm.raw_is_moving(np.array([10]))[0]


def test_learning_map_covers_all_twenty_ids():
    assert len(lm.LEARNING_TO_AVR) == lm.N_LEARNING == 20
    out = lm.learning_to_avr(np.arange(20))
    assert out.dtype == np.uint8
    assert set(out.tolist()) <= set(range(5))
    assert out[0] == lm.VOID
    assert np.all(out[1:9] == lm.DYNAMIC_OBJECT)     # every vehicle and person
    assert np.all(out[9:11] == lm.DRIVABLE)          # road, parking


def test_learning_map_is_shape_preserving():
    """It runs straight on an [h, w] range-image argmax, not just a vector."""
    pred = np.zeros((4, 6), dtype=np.int64)
    pred[1, 2] = 9
    out = lm.learning_to_avr(pred)
    assert out.shape == (4, 6)
    assert out[1, 2] == lm.DRIVABLE


def test_label_packing_round_trips():
    semantic = np.array([40, 252, 0, 81], dtype=np.uint32)
    instance = np.array([0, 7, 0, 3], dtype=np.uint32)
    packed = (instance << np.uint32(16)) | semantic
    got_sem, got_inst = lm.split_label(packed)
    assert np.array_equal(got_sem, semantic)
    assert np.array_equal(got_inst, instance)


def test_decode_labels_keeps_the_moving_supervision():
    packed = ((np.uint32(7) << np.uint32(16)) | np.array([258, 18], dtype=np.uint32))
    avr, moving, instance = lm.decode_labels(packed)
    assert np.array_equal(avr, [lm.DYNAMIC_OBJECT, lm.DYNAMIC_OBJECT])
    assert np.array_equal(moving, [True, False])
    assert np.array_equal(instance, [7, 7])


def test_out_of_range_ids_raise_rather_than_wrap():
    with pytest.raises(ValueError, match="out of range"):
        lm.raw_to_avr(np.array([9999]))
    with pytest.raises(ValueError, match="out of range"):
        lm.learning_to_avr(np.array([20]))


def test_empty_input_is_handled():
    assert lm.raw_to_avr(np.empty(0, dtype=np.uint16)).shape == (0,)
    assert lm.raw_is_moving(np.empty(0, dtype=np.uint16)).shape == (0,)
    assert lm.learning_to_avr(np.empty(0, dtype=np.int64)).shape == (0,)
