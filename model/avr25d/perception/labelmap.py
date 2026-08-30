"""SemanticKITTI → AVR-25D class merge (PRD §6.1).

Two lookup tables, because two different things arrive here:

``RAW_TO_AVR``
    SemanticKITTI *raw* label ids as stored in ``.label`` files (0…259, with
    the ``moving-*`` variants at 252…259).  This is what ground truth looks
    like on disk.

``LEARNING_TO_AVR``
    SemanticKITTI *learning* ids 0…19 — the 20-way output of a pretrained
    range-image network.  This is what ONNX inference produces.

Both collapse onto the five AVR-25D classes.  Collapsing 19 classes to 5 raises
per-class accuracy, shrinks the model and maps 1:1 onto the problem statement's
three distinctions plus a terrain split and a void class.

The ``moving-*`` ids are free supervision and are kept separately.  A parked car
and a moving car both classify as ``DYNAMIC_OBJECT``, but a ``moving-*`` origin
sets the cell's ``MOVING`` bit, which the tracker uses to seed candidates
(PRD §6.3 bit 5).  Discarding that during the merge would throw away a label
someone already paid to annotate.

One deliberate divergence from the stock ``semantic-kitti.yaml`` learning map:
that map sends ``other-structure`` (52) and ``other-object`` (99) to *unlabeled*.
PRD §6.1 assigns both to ``STATIC_OBSTACLE``, which is right for us — they are
solid things a vehicle would hit, and calling them void would hide obstacles.
``RAW_TO_AVR`` follows the PRD.  ``LEARNING_TO_AVR`` cannot recover them,
because the network never emits them as a distinct id.
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# The five classes (PRD §6.1)
# ---------------------------------------------------------------------------

VOID = 0
DRIVABLE = 1
NON_DRIVABLE_TERRAIN = 2
STATIC_OBSTACLE = 3
DYNAMIC_OBJECT = 4

N_CLASSES = 5

CLASS_NAMES: tuple[str, ...] = (
    "VOID",
    "DRIVABLE",
    "NON_DRIVABLE_TERRAIN",
    "STATIC_OBSTACLE",
    "DYNAMIC_OBJECT",
)

#: Dashboard colours.  Single source of truth on the Python side; mirrored by
#: ``webapp/lib/palette.ts``.  The red/green pair is separated by luminance as
#: well as hue, for deuteranopia/protanopia.
CLASS_COLOURS: tuple[str, ...] = (
    "#3a3a42",  # VOID                  grey
    "#2e7d32",  # DRIVABLE              green
    "#f9a825",  # NON_DRIVABLE_TERRAIN  amber
    "#c62828",  # STATIC_OBSTACLE       red
    "#1565c0",  # DYNAMIC_OBJECT        blue
)

#: Classes whose returns describe the traversable surface, and therefore the
#: ones ``z_ground`` is estimated from (IMPLEMENTATION_PLAN.md §6.2).
GROUND_CLASSES: tuple[int, ...] = (DRIVABLE, NON_DRIVABLE_TERRAIN)

# ---------------------------------------------------------------------------
# Raw SemanticKITTI ids
# ---------------------------------------------------------------------------

#: Raw id → human name, for diagnostics and for asserting the tables are total.
RAW_NAMES: dict[int, str] = {
    0: "unlabeled", 1: "outlier",
    10: "car", 11: "bicycle", 13: "bus", 15: "motorcycle", 16: "on-rails",
    18: "truck", 20: "other-vehicle",
    30: "person", 31: "bicyclist", 32: "motorcyclist",
    40: "road", 44: "parking", 48: "sidewalk", 49: "other-ground",
    50: "building", 51: "fence", 52: "other-structure",
    60: "lane-marking",
    70: "vegetation", 71: "trunk", 72: "terrain",
    80: "pole", 81: "traffic-sign", 99: "other-object",
    252: "moving-car", 253: "moving-bicyclist", 254: "moving-person",
    255: "moving-motorcyclist", 256: "moving-on-rails", 257: "moving-bus",
    258: "moving-truck", 259: "moving-other-vehicle",
}

#: Raw id → AVR-25D class, exactly as tabulated in PRD §6.1.
RAW_TO_AVR_SPEC: dict[int, int] = {
    # VOID
    0: VOID, 1: VOID,
    # DRIVABLE — road, parking, lane-marking
    40: DRIVABLE, 44: DRIVABLE, 60: DRIVABLE,
    # NON_DRIVABLE_TERRAIN — sidewalk, other-ground, terrain, vegetation
    48: NON_DRIVABLE_TERRAIN, 49: NON_DRIVABLE_TERRAIN,
    70: NON_DRIVABLE_TERRAIN, 72: NON_DRIVABLE_TERRAIN,
    # STATIC_OBSTACLE — building, fence, pole, traffic-sign, trunk,
    #                   other-structure, other-object
    50: STATIC_OBSTACLE, 51: STATIC_OBSTACLE, 52: STATIC_OBSTACLE,
    71: STATIC_OBSTACLE, 80: STATIC_OBSTACLE, 81: STATIC_OBSTACLE,
    99: STATIC_OBSTACLE,
    # DYNAMIC_OBJECT — every vehicle and every person, static or moving
    10: DYNAMIC_OBJECT, 11: DYNAMIC_OBJECT, 13: DYNAMIC_OBJECT,
    15: DYNAMIC_OBJECT, 16: DYNAMIC_OBJECT, 18: DYNAMIC_OBJECT,
    20: DYNAMIC_OBJECT, 30: DYNAMIC_OBJECT, 31: DYNAMIC_OBJECT,
    32: DYNAMIC_OBJECT,
    252: DYNAMIC_OBJECT, 253: DYNAMIC_OBJECT, 254: DYNAMIC_OBJECT,
    255: DYNAMIC_OBJECT, 256: DYNAMIC_OBJECT, 257: DYNAMIC_OBJECT,
    258: DYNAMIC_OBJECT, 259: DYNAMIC_OBJECT,
}

#: Raw ids that carry the ``moving-*`` annotation (PRD §6.3, bit 5).
MOVING_RAW_IDS: tuple[int, ...] = tuple(range(252, 260))

_RAW_TABLE_SIZE = 260  # highest raw id is 259

#: uint8[260] lookup: ``RAW_TO_AVR[raw_id] -> AVR class``.  Ids the dataset
#: never emits fall through to ``VOID``, so an unexpected value degrades to
#: "unknown" rather than to a confident wrong class.
RAW_TO_AVR: np.ndarray = np.full(_RAW_TABLE_SIZE, VOID, dtype=np.uint8)
for _raw, _avr in RAW_TO_AVR_SPEC.items():
    RAW_TO_AVR[_raw] = _avr

#: bool[260] lookup: does this raw id mean "annotated as moving"?
RAW_IS_MOVING: np.ndarray = np.zeros(_RAW_TABLE_SIZE, dtype=bool)
RAW_IS_MOVING[list(MOVING_RAW_IDS)] = True

#: AVR class → a representative raw SemanticKITTI id.  Used when writing
#: synthetic scenes, so they are byte-compatible with the real ``.label``
#: reader and travel through exactly the same code path as KITTI does
#: (``avr25d/synth/export.py``).
AVR_TO_RAW: dict[int, int] = {
    VOID: 0,                    # unlabeled
    DRIVABLE: 40,               # road
    NON_DRIVABLE_TERRAIN: 72,   # terrain
    STATIC_OBSTACLE: 50,        # building
    DYNAMIC_OBJECT: 18,         # truck
}

#: As above, for a primitive that is annotated as moving.
AVR_TO_RAW_MOVING: dict[int, int] = {**AVR_TO_RAW, DYNAMIC_OBJECT: 258}  # moving-truck

# ---------------------------------------------------------------------------
# Learning ids 0…19 (network output)
# ---------------------------------------------------------------------------

LEARNING_NAMES: tuple[str, ...] = (
    "unlabeled", "car", "bicycle", "motorcycle", "truck", "other-vehicle",
    "person", "bicyclist", "motorcyclist", "road", "parking", "sidewalk",
    "other-ground", "building", "fence", "vegetation", "trunk", "terrain",
    "pole", "traffic-sign",
)

N_LEARNING = len(LEARNING_NAMES)  # 20 ids; id 0 is excluded from mIoU

#: uint8[20] lookup: ``LEARNING_TO_AVR[learning_id] -> AVR class``.
LEARNING_TO_AVR: np.ndarray = np.array(
    [
        VOID,                  # 0  unlabeled
        DYNAMIC_OBJECT,        # 1  car
        DYNAMIC_OBJECT,        # 2  bicycle
        DYNAMIC_OBJECT,        # 3  motorcycle
        DYNAMIC_OBJECT,        # 4  truck
        DYNAMIC_OBJECT,        # 5  other-vehicle
        DYNAMIC_OBJECT,        # 6  person
        DYNAMIC_OBJECT,        # 7  bicyclist
        DYNAMIC_OBJECT,        # 8  motorcyclist
        DRIVABLE,              # 9  road (lane-marking merges here upstream)
        DRIVABLE,              # 10 parking
        NON_DRIVABLE_TERRAIN,  # 11 sidewalk
        NON_DRIVABLE_TERRAIN,  # 12 other-ground
        STATIC_OBSTACLE,       # 13 building
        STATIC_OBSTACLE,       # 14 fence
        NON_DRIVABLE_TERRAIN,  # 15 vegetation
        STATIC_OBSTACLE,       # 16 trunk
        NON_DRIVABLE_TERRAIN,  # 17 terrain
        STATIC_OBSTACLE,       # 18 pole
        STATIC_OBSTACLE,       # 19 traffic-sign
    ],
    dtype=np.uint8,
)

#: Raw id → learning id, the stock SemanticKITTI map.  Needed only to compare
#: against published 19-class numbers; the pipeline uses ``RAW_TO_AVR``.
RAW_TO_LEARNING_SPEC: dict[int, int] = {
    0: 0, 1: 0, 10: 1, 11: 2, 13: 5, 15: 3, 16: 5, 18: 4, 20: 5, 30: 6,
    31: 7, 32: 8, 40: 9, 44: 10, 48: 11, 49: 12, 50: 13, 51: 14, 52: 0,
    60: 9, 70: 15, 71: 16, 72: 17, 80: 18, 81: 19, 99: 0,
    252: 1, 253: 7, 254: 6, 255: 8, 256: 5, 257: 5, 258: 4, 259: 5,
}

RAW_TO_LEARNING: np.ndarray = np.zeros(_RAW_TABLE_SIZE, dtype=np.uint8)
for _raw, _learn in RAW_TO_LEARNING_SPEC.items():
    RAW_TO_LEARNING[_raw] = _learn


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

def split_label(packed: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split a SemanticKITTI ``.label`` word into (semantic, instance).

    ``.label`` files store one ``uint32`` per point: the low 16 bits are the
    semantic id, the high 16 bits the instance id.
    """
    packed = np.asarray(packed, dtype=np.uint32)
    semantic = (packed & 0xFFFF).astype(np.uint16)
    instance = (packed >> 16).astype(np.uint16)
    return semantic, instance


def raw_to_avr(semantic: np.ndarray) -> np.ndarray:
    """Raw SemanticKITTI semantic ids → AVR-25D classes.  ``uint8[n]``."""
    semantic = np.asarray(semantic)
    if semantic.size == 0:
        return np.empty(0, dtype=np.uint8)
    idx = np.asarray(semantic, dtype=np.int64)
    if idx.min() < 0 or idx.max() >= _RAW_TABLE_SIZE:
        raise ValueError(
            f"semantic id out of range [0,{_RAW_TABLE_SIZE}): "
            f"saw [{idx.min()},{idx.max()}]"
        )
    return RAW_TO_AVR[idx]


def raw_is_moving(semantic: np.ndarray) -> np.ndarray:
    """True where the raw id is one of the ``moving-*`` variants.  ``bool[n]``."""
    semantic = np.asarray(semantic)
    if semantic.size == 0:
        return np.empty(0, dtype=bool)
    return RAW_IS_MOVING[np.asarray(semantic, dtype=np.int64)]


def learning_to_avr(learning: np.ndarray) -> np.ndarray:
    """Network learning ids 0…19 → AVR-25D classes.  ``uint8[...]``.

    Shape-preserving, so it works on a per-point vector or straight on an
    ``[h, w]`` range-image argmax.
    """
    learning = np.asarray(learning)
    if learning.size == 0:
        return np.empty(learning.shape, dtype=np.uint8)
    idx = np.asarray(learning, dtype=np.int64)
    if idx.min() < 0 or idx.max() >= N_LEARNING:
        raise ValueError(
            f"learning id out of range [0,{N_LEARNING}): "
            f"saw [{idx.min()},{idx.max()}]"
        )
    return LEARNING_TO_AVR[idx]


def decode_labels(packed: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``.label`` words → (avr_class uint8, moving bool, instance uint16).

    The one call the pipeline actually makes: it keeps the ``moving-*``
    supervision instead of dropping it on the floor during the merge.
    """
    semantic, instance = split_label(packed)
    return raw_to_avr(semantic), raw_is_moving(semantic), instance
