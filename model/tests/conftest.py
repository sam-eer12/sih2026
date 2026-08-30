"""Shared fixtures.

Ray-casting a scene costs about a second, so every scene is cast once per
session and shared.  Tests must therefore treat the arrays as read-only.
"""

from __future__ import annotations

import numpy as np
import pytest

from avr25d import load_config
from avr25d.perception import labelmap
from avr25d.synth import SensorSpec, load_scene, raycast

SCENE_NAMES = (
    "S1_flat_road",
    "S2_pothole",
    "S3_overhang",
    "S4_curb",
    "S5_crossing_truck",
)


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture(scope="session")
def sensor():
    return SensorSpec()


@pytest.fixture(scope="session")
def scenes():
    return {name: load_scene(name) for name in SCENE_NAMES}


@pytest.fixture(scope="session")
def casts(scenes, sensor):
    """``{scene_name: (xyzi, packed_labels, avr, moving, instance)}`` at t = 0."""
    out = {}
    for name, scene in scenes.items():
        xyzi, packed = raycast(scene, sensor)
        semantic, instance = labelmap.split_label(packed)
        out[name] = {
            "xyzi": xyzi,
            "packed": packed,
            "semantic": semantic,
            "instance": instance,
            "avr": labelmap.raw_to_avr(semantic),
            "moving": labelmap.raw_is_moving(semantic),
            "z_road": xyzi[:, 2] + np.float32(sensor.sensor_height),
        }
    return out
