"""Synthetic scenes with exact ground truth (PRD §9.3).

SemanticKITTI has no pothole class, no annotated overhang with a known
clearance and no curb geometry, so it cannot support a *quantitative* claim
about hazard preservation — and hazard preservation is the whole argument for
2.5D over 2D.  These scenes fix that: because the geometry is analytic, the
pothole is 0.220 m deep and the gantry clearance is 3.100 m to machine
precision, which turns "the hazard is visible in the render" into a measurement
with an error in metres.
"""

from avr25d.synth.raycast import Primitive, Scene, SensorSpec, raycast
from avr25d.synth.scenegen import list_scenes, load_scene

__all__ = [
    "Primitive",
    "Scene",
    "SensorSpec",
    "raycast",
    "load_scene",
    "list_scenes",
]
