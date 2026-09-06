"""FR-40 — the ``scenes`` collection: exact ground truth in the shape Mongo stores.

``scenegen.ground_truth`` already derives every hazard number from the CSV that
specifies it.  This module is the boundary layer that turns one of those dicts
into the document ``IMPLEMENTATION_PLAN.md`` §8 defines::

    {_id, name, primitives, groundTruth: {potholeDepth, clearance,
                                          curbHeight, truckSpeed}}

Why a registry at all
---------------------
FR-40's clause is "so the hazard-preservation comparison reads truth from the
same store the dashboard reads".  The failure it prevents is the ordinary one:
§11.4 says the pothole is 0.22 m deep because it read a CSV, the dashboard says
0.20 m because someone typed it into a seed script, and the two disagree in
front of a judge.  Here the document is *derived* — every field is a
consequence of a CSV cell or of the sensor spec — and ``from_document``
reconstructs the exact dict ``bench/hazard.py`` scores against, so the two
paths cannot drift without a test failing.

Shape
-----
The document is a **superset** of the plan's four fields, because the four
cannot carry the comparison.  ``groundTruth`` is the flat summary the dashboard
renders and T-W5 checks; ``hazards`` is the per-hazard detail the benchmark
needs — footprints, instance ids, the truck's per-frame positions — and losing
it would mean the dashboard reads from the store while the benchmark still
reads from the file, which is the thing FR-40 exists to stop.

Field names are camelCase throughout because the consumer is a TypeScript route
handler, not Python.  ``_camel``/``_snake`` do the conversion mechanically in
both directions; what licenses that is ``test_registry.py``'s round trip over
every scene and every key, not the naming convention holding by inspection.

Provenance and determinism
--------------------------
Each document carries the SHA-256 of the CSV that produced it, so "does this
document match the spec file?" is checkable without re-deriving anything.  The
output carries **no timestamp**: the same CSVs produce a byte-identical file,
so ``make scenes-registry`` on two machines is a no-op diff rather than churn,
and the file is small enough and cheap enough — no ray-casting, no point
clouds, milliseconds in a fresh clone — to be committed alongside the CSVs.

    python -m avr25d.synth.registry              # -> data/scenes_registry.json
    python -m avr25d.synth.registry S2_pothole --stdout
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from avr25d.synth.raycast import Scene, SensorSpec
from avr25d.synth.scenegen import ground_truth, list_scenes, load_scene, scene_path

#: Bumped when the document shape changes in a way a consumer must notice.
#: Stored on every document, because documents outlive the file they shipped in.
SCHEMA_VERSION = 1

#: The MongoDB collection these documents belong to (IMPLEMENTATION_PLAN §8).
COLLECTION = "scenes"

DEFAULT_OUT = Path("data/scenes_registry.json")

#: hazard tag -> (flat ``groundTruth`` key, the detail field it summarises).
#: The four keys are FR-40's; every scene carries all four, ``None`` where the
#: scene has no hazard of that kind, so the dashboard renders a fixed set of
#: rows instead of branching on key existence.
_FLAT_KEYS = {
    "pothole":   ("potholeDepth", "depth_m"),
    "clearance": ("clearance",    "clearance_m"),
    "step":      ("curbHeight",   "height_m"),
    "track":     ("truckSpeed",   "speed_mps"),
}

#: CSV column order, which is also the document's ``primitives`` field order.
#: ``class`` rather than ``class_id`` — the document mirrors the spreadsheet a
#: scene is authored in, so T-W5's "equals the CSV specification" is literal.
_PRIMITIVE_COLUMNS = (
    "type", "x", "y", "z", "sx", "sy", "sz", "class", "vx", "vy", "hazard", "note"
)

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


# ---------------------------------------------------------------------------
# Key conversion.  Mechanical both ways; the round-trip test is the guarantee.
# ---------------------------------------------------------------------------

def _camel(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(w[:1].upper() + w[1:] for w in rest)


def _snake(key: str) -> str:
    return _CAMEL_BOUNDARY.sub("_", key).lower()


def _convert(value, fn):
    """Apply a key transform through nested dicts and lists."""
    if isinstance(value, dict):
        return {fn(k): _convert(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [_convert(v, fn) for v in value]
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

def _primitive_row(p) -> dict:
    """One primitive as its CSV row, typed."""
    return {
        "type": p.kind,
        "x": round(p.x, 6), "y": round(p.y, 6), "z": round(p.z, 6),
        "sx": round(p.sx, 6), "sy": round(p.sy, 6), "sz": round(p.sz, 6),
        "class": int(p.class_id),
        "vx": round(p.vx, 6), "vy": round(p.vy, 6),
        "hazard": p.hazard,
        "note": p.note,
    }


def flat_ground_truth(gt: dict, scene_name: str = "") -> dict:
    """The four FR-40 summary values, ``None`` where the scene has no such hazard."""
    flat = {key: None for key, _ in _FLAT_KEYS.values()}
    for hazard in gt["hazards"]:
        tag = hazard["tag"]
        if tag not in _FLAT_KEYS:
            raise ValueError(
                f"scene {scene_name or gt['scene']!r}: hazard tag {tag!r} has no "
                f"FR-40 summary key; expected one of {sorted(_FLAT_KEYS)}"
            )
        key, detail = _FLAT_KEYS[tag]
        if flat[key] is not None:
            # The flat shape holds one value per key by construction.  Two
            # potholes in one scene is a legitimate thing to author; it just
            # cannot be summarised this way, and silently keeping the last one
            # would put a wrong number on the dashboard.
            raise ValueError(
                f"scene {scene_name or gt['scene']!r}: two {tag!r} hazards map to "
                f"groundTruth.{key}; split them into separate scenes or extend "
                "_FLAT_KEYS with an indexed key"
            )
        flat[key] = hazard[detail]
    return flat


def to_document(
    scene: Scene,
    csv_path: str | Path | None = None,
    sensor: SensorSpec | None = None,
    frame_dt: float = 0.10,
) -> dict:
    """One ``scenes`` document for ``scene``.  JSON- and BSON-serialisable.

    ``_id`` is the scene name: the name is already unique and already the key
    everything else joins on, so an upsert on it makes re-seeding idempotent
    rather than duplicating the collection on every run.
    """
    gt = scene.ground_truth or ground_truth(scene, sensor, frame_dt=frame_dt)
    path = Path(csv_path) if csv_path else scene_path(scene.name)

    return {
        "_id": scene.name,
        "name": scene.name,
        "schemaVersion": SCHEMA_VERSION,
        "nFrames": gt["n_frames"],
        "frameDtS": gt["frame_dt_s"],
        "frame": gt["frame"],
        "sensor": _convert(gt["sensor"], _camel),
        "expectNoHazards": gt["expect_no_hazards"],
        "nPrimitives": gt["n_primitives"],
        "primitives": [_primitive_row(p) for p in scene.primitives],
        "groundTruth": flat_ground_truth(gt, scene.name),
        "hazards": _convert(gt["hazards"], _camel),
        "source": {"csv": path.name, "sha256": _sha256(path)},
    }


def from_document(doc: dict) -> dict:
    """Invert ``to_document``'s ground truth.

    Returns exactly what ``scenegen.ground_truth`` returns for the same scene,
    so a consumer holding only the Mongo document — a dashboard check, an
    offline validation run — scores against the same numbers ``bench/hazard.py``
    does.  ``primitives`` and ``source`` are provenance and have no counterpart
    in the ground-truth dict, so they are dropped here.
    """
    return {
        "scene": doc["name"],
        "n_frames": doc["nFrames"],
        "frame_dt_s": doc["frameDtS"],
        "frame": doc["frame"],
        "sensor": _convert(doc["sensor"], _snake),
        "expect_no_hazards": doc["expectNoHazards"],
        "hazards": _convert(doc["hazards"], _snake),
        "n_primitives": doc["nPrimitives"],
    }


# ---------------------------------------------------------------------------
# Registry file
# ---------------------------------------------------------------------------

def build_registry(
    scenes: list[str] | None = None,
    sensor: SensorSpec | None = None,
    frame_dt: float = 0.10,
) -> dict:
    """Every scene as a ``scenes`` document, in name order."""
    paths = [scene_path(s) for s in scenes] if scenes else list_scenes()

    documents = []
    seen: set[str] = set()
    for path in paths:
        scene = load_scene(path)
        if scene.name in seen:
            raise ValueError(f"duplicate scene name {scene.name!r} in the registry")
        seen.add(scene.name)
        documents.append(to_document(scene, path, sensor, frame_dt=frame_dt))

    return {
        "schemaVersion": SCHEMA_VERSION,
        "collection": COLLECTION,
        "generator": "avr25d.synth.registry",
        "scenes": documents,
    }


def write_registry(registry: dict, out_path: str | Path = DEFAULT_OUT) -> Path:
    """Write the registry as JSON.  -> the path written."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return out_path


def _main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m avr25d.synth.registry",
        description=(
            "Export synthetic-scene ground truth as MongoDB `scenes` documents "
            "(FR-40).  Derived from the scene CSVs alone — no ray-casting, no "
            "point clouds, no dataset."
        ),
    )
    ap.add_argument("scenes", nargs="*", help="scene names; default is all of them")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--frame-dt", type=float, default=0.10)
    ap.add_argument(
        "--stdout", action="store_true", help="print the JSON instead of writing it"
    )
    args = ap.parse_args(argv)

    registry = build_registry(args.scenes or None, frame_dt=args.frame_dt)

    if args.stdout:
        print(json.dumps(registry, indent=2))
        return 0

    path = write_registry(registry, args.out)
    for doc in registry["scenes"]:
        stated = ", ".join(
            f"{k}={v}" for k, v in doc["groundTruth"].items() if v is not None
        )
        print(
            f"{doc['name']:<20} {doc['nPrimitives']} primitive(s)  "
            f"{len(doc['hazards'])} hazard(s)  {stated or 'no hazards'}"
        )
    print(f"{len(registry['scenes'])} document(s) -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
