"""Scene assembly from a spec CSV, and exact ground truth derived from it.

A scene is a table.  One primitive per row, so authoring a new hazard scene is
editing a spreadsheet rather than writing code — which is the point: the
scenes have to be cheap enough that adding an adversarial one on Day 9 is an
afternoon, not a rewrite.

Columns::

    type,x,y,z,sx,sy,sz,class,vx,vy,hazard,note

``x,y,z`` is the centre of the primitive and ``sx,sy,sz`` its full extents, in
the **road frame** (``z = 0`` is the road surface).  See ``raycast`` for why
that frame, and for the primitive types.  ``vx,vy`` are metres per second and
make a primitive move across frames.  ``hazard`` tags the row as carrying a
ground-truth measurement; ``note`` is free text.

Trailing columns may be left blank, so the eight-column form in the plan's
example still parses.

``#`` lines are comments.  One of them is load-bearing::

    # frames: 40

sets the sequence length.

Ground truth
------------
Because the geometry is analytic, ground truth is exact and free — it is read
straight back off the primitive that produced the hazard.  The pothole is
0.220 m deep because the row says ``sz = 0.22``, not because someone measured a
render.  ``ground_truth(scene)`` returns that as a JSON-serialisable dict, which
is what ``bench/hazard.py`` scores against and what FR-40 stores in the
``scenes`` collection.  Quantities that are differences (depth, clearance, step
height) are frame-independent; anything absolute is additionally given in the
sensor frame, because that is what the grid measures.
"""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

from avr25d.synth.raycast import Primitive, Scene, SensorSpec, instance_ids

SCENES_DIR = Path(__file__).parent / "scenes"

_REQUIRED_COLUMNS = ("type", "x", "y", "z", "sx", "sy", "sz", "class")
_FRAMES_RE = re.compile(r"^\s*#\s*frames\s*:\s*(\d+)", re.IGNORECASE)


def list_scenes() -> list[Path]:
    """Every packaged scene CSV, in name order."""
    return sorted(SCENES_DIR.glob("*.csv"))


def scene_path(name: str) -> Path:
    """Resolve a scene by name (``"S2_pothole"``) or by path."""
    p = Path(name)
    if p.exists():
        return p
    candidate = SCENES_DIR / (name if name.endswith(".csv") else f"{name}.csv")
    if not candidate.exists():
        raise FileNotFoundError(
            f"no scene {name!r}; available: "
            f"{', '.join(s.stem for s in list_scenes())}"
        )
    return candidate


def _f(row: dict, key: str, default: float = 0.0) -> float:
    value = (row.get(key) or "").strip()
    return default if value == "" else float(value)


def load_scene(csv_path: str | Path) -> Scene:
    """Parse a scene CSV.  -> ``Scene`` with ``ground_truth`` populated."""
    path = scene_path(str(csv_path))
    text = path.read_text(encoding="utf-8")

    n_frames = 1
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            m = _FRAMES_RE.match(line)
            if m:
                n_frames = int(m.group(1))
            continue
        if line.strip():
            data_lines.append(line)

    if not data_lines:
        raise ValueError(f"{path}: no primitive rows")

    reader = csv.DictReader(data_lines, skipinitialspace=True)
    if reader.fieldnames is None:
        raise ValueError(f"{path}: missing header row")
    header = [f.strip() for f in reader.fieldnames]
    missing = [c for c in _REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ValueError(f"{path}: header is missing required columns {missing}")

    prims: list[Primitive] = []
    for lineno, row in enumerate(reader, start=2):
        row = {(k.strip() if k else k): v for k, v in row.items()}
        kind = (row.get("type") or "").strip().lower()
        if not kind:
            continue
        try:
            prims.append(
                Primitive(
                    kind=kind,
                    x=_f(row, "x"), y=_f(row, "y"), z=_f(row, "z"),
                    sx=_f(row, "sx"), sy=_f(row, "sy"), sz=_f(row, "sz"),
                    class_id=int(_f(row, "class")),
                    vx=_f(row, "vx"), vy=_f(row, "vy"),
                    hazard=(row.get("hazard") or "").strip().lower(),
                    note=(row.get("note") or "").strip(),
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path}:{lineno}: {exc}") from None

    bare = Scene(name=path.stem, primitives=tuple(prims), n_frames=n_frames)
    return Scene(
        name=bare.name,
        primitives=bare.primitives,
        n_frames=n_frames,
        ground_truth=ground_truth(bare),
    )


def ground_truth(
    scene: Scene,
    sensor: SensorSpec | None = None,
    frame_dt: float = 0.10,
) -> dict:
    """Exact ground truth for ``scene``, derived from its primitives.

    Every number here is a consequence of a CSV cell, which is what makes
    T-W5 ("groundTruth equals the CSV specification exactly") checkable rather
    than aspirational.
    """
    sensor = sensor or SensorSpec()
    h = sensor.sensor_height

    instances = instance_ids(scene.primitives)
    hazards: list[dict] = []
    for index, p in enumerate(scene.primitives):
        if not p.hazard or p.hazard == "control":
            continue
        lo, hi = p.lo, p.hi
        record = {
            "index": index,
            "instance_id": int(instances[index]),
            "tag": p.hazard,
            "type": p.kind,
            "class_id": int(p.class_id),
            "note": p.note,
            "centre_xy_m": [round(p.x, 6), round(p.y, 6)],
            "range_m": round(math.hypot(p.x, p.y), 6),
            "footprint_xy_m": [
                [round(lo[0], 6), round(lo[1], 6)],
                [round(hi[0], 6), round(hi[1], 6)],
            ],
        }

        if p.hazard == "pothole":
            record |= {
                "depth_m": round(p.sz, 6),
                "length_m": round(p.sx, 6),
                "width_m": round(p.sy, 6),
                "floor_z_road_m": round(lo[2], 6),
                "rim_z_road_m": round(hi[2], 6),
                "floor_z_sensor_m": round(lo[2] - h, 6),
                "rim_z_sensor_m": round(hi[2] - h, 6),
            }
        elif p.hazard == "clearance":
            record |= {
                "clearance_m": round(lo[2], 6),
                "structure_depth_m": round(p.sz, 6),
                "span_m": round(p.sy, 6),
                "underside_z_road_m": round(lo[2], 6),
                "underside_z_sensor_m": round(lo[2] - h, 6),
            }
        elif p.hazard == "step":
            record |= {
                "height_m": round(hi[2], 6),        # above the road plane at z = 0
                "width_m": round(p.sy, 6),
                "top_z_road_m": round(hi[2], 6),
                "top_z_sensor_m": round(hi[2] - h, 6),
                "edge_y_m": round(lo[1], 6),
            }
        elif p.hazard == "track":
            record |= {
                "speed_mps": round(math.hypot(p.vx, p.vy), 6),
                "velocity_mps": [round(p.vx, 6), round(p.vy, 6)],
                "heading_deg": round(math.degrees(math.atan2(p.vy, p.vx)), 6),
                "dims_m": [round(p.sx, 6), round(p.sy, 6), round(p.sz, 6)],
                "positions_xy_m": [
                    [round(p.x + p.vx * (f * frame_dt), 6),
                     round(p.y + p.vy * (f * frame_dt), 6)]
                    for f in range(scene.n_frames)
                ],
            }
        else:
            raise ValueError(
                f"scene {scene.name!r}: unknown hazard tag {p.hazard!r}; "
                "expected one of control, pothole, clearance, step, track"
            )
        hazards.append(record)

    return {
        "scene": scene.name,
        "n_frames": scene.n_frames,
        "frame_dt_s": frame_dt,
        "frame": "road frame (z=0 at the road surface); *_sensor_m is z in the sensor frame",
        "sensor": {
            "height_m": h,
            "n_beams": sensor.n_beams,
            "n_azimuth": sensor.n_azimuth,
            "fov_up_deg": sensor.fov_up,
            "fov_down_deg": sensor.fov_down,
            "r_max_m": sensor.r_max,
            "range_sigma_m": sensor.range_sigma,
            "seed": sensor.seed,
        },
        "expect_no_hazards": (
            any(p.hazard == "control" for p in scene.primitives) and not hazards
        ),
        "hazards": hazards,
        "n_primitives": len(scene.primitives),
    }


def generate(
    scene: Scene,
    out_dir: str | Path,
    sensor: SensorSpec | None = None,
    frame_dt: float = 0.10,
) -> dict:
    """Ray-cast every frame of ``scene`` and write a KITTI sequence directory.

    Returns the ground-truth dict, which is also written alongside the scans as
    ``ground_truth.json``.
    """
    from avr25d.synth.export import export_kitti
    from avr25d.synth.raycast import raycast

    sensor = sensor or SensorSpec()
    out_dir = Path(out_dir)
    for frame in range(scene.n_frames):
        xyzi, labels = raycast(scene, sensor, t_scene=frame * frame_dt)
        export_kitti(xyzi, labels, out_dir, frame)

    gt = ground_truth(scene, sensor, frame_dt=frame_dt)
    (out_dir / "ground_truth.json").write_text(
        json.dumps(gt, indent=2) + "\n", encoding="utf-8"
    )
    return gt


def _main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m avr25d.synth.scenegen",
        description="Generate synthetic LiDAR scenes with exact ground truth.",
    )
    ap.add_argument("scenes", nargs="*", help="scene names; default is all of them")
    ap.add_argument("--out", default="data/synthetic", help="output root directory")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--frame-dt", type=float, default=0.10)
    args = ap.parse_args(argv)

    paths = [scene_path(s) for s in args.scenes] if args.scenes else list_scenes()
    sensor = SensorSpec(seed=args.seed) if args.seed is not None else SensorSpec()

    out_root = Path(args.out)
    for path in paths:
        scene = load_scene(path)
        target = out_root / scene.name
        gt = generate(scene, target, sensor, frame_dt=args.frame_dt)
        print(
            f"{scene.name:<20} {scene.n_frames:>3} frame(s)  "
            f"{len(scene.primitives)} primitive(s)  "
            f"{len(gt['hazards'])} hazard(s)  -> {target}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
