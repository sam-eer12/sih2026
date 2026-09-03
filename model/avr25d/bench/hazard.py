"""Hazard preservation scored against exact synthetic ground truth.

FR-16, PRD §10.4 and §11.4.  Tests: T-H1 … T-H4, T-B5.

Why this module exists
----------------------
Every other accuracy number in ``results.json`` comes from SemanticKITTI, and
SemanticKITTI cannot support the claim this project is actually making.  It has
no pothole class, no annotated overhang with a known clearance, and no curb
geometry — so on real data "the hazard is visible in the render" is the *most*
that can be said.  The synthetic scenes of ``avr25d/synth/`` fix that: their
geometry is analytic, so the pothole is 0.220 m deep and the deck underside is
3.100 m up to machine precision, and hazard preservation becomes an error in
metres.  That is what FR-16 asks for and it is the direct evidence for PS-10.

What is scored, and against what
--------------------------------
Cells are associated to a hazard by **instance id**, not by a bounding-box test
on cell centres.  The ray-caster writes each primitive's instance into the
KITTI label word, so "the cells covering the pothole" is exactly "the cells
containing points whose instance is the pothole's".  A footprint test on cell
centres sounds equivalent and is not: at 12 m the cells are 5.7 cm across, the
pit's far wall returns land in cells whose centres sit just outside the CSV
footprint, and a footprint test silently drops them — including, on S2, the
deepest return in the scene.  It cost an hour to find that; the instance id
cannot be wrong.

Labels are the scene's own, not a segmenter's.  §11.4 measures what the
*representation* preserves, and running perception first would fold two error
sources into one number that then answers neither question.  Perception
accuracy is §11.3's job and it has 971 real scans to do it on.

Estimators
----------
Each hazard type gets the estimator its definition implies, not a uniform one:

``pothole``
    depth = road reference − the **deepest** flagged cell's ``z_ground``.
    A pit's depth *is* its deepest point; a median over the covering cells
    measures the inner walls, which are genuinely shallower.  Requiring the
    cell to carry ``NEGATIVE_OBSTACLE`` is what keeps this from being "the
    lowest outlier": the flag already demands a drop against the surrounding
    ground, so the estimate is the deepest *corroborated* cell.
``clearance``
    the structure's own ``z_obstacle`` above the road reference.  Reported
    alongside the per-cell ``z_obstacle − z_ground`` that FR-13 defines, which
    on a horizontal deck is measurable on almost no cells at all — see
    ``clearance_cells_with_both`` and the note in ``docs/RESULTS.md``.
``step``
    height = the 90th percentile of the covering cells' ``z_ground`` above the
    road reference.  The kerb's cells include its vertical face, whose returns
    run the full 0.15 m; the *top* is what "0.15 m high" names, and p90 finds it
    without riding on a single return the way ``max`` would.
``track``
    the tracker's median speed after warm-up — the §11.4 row for S5.  Shares its
    definition with T-D2 so the two cannot disagree.

The road reference is the median ``z_ground`` of occupied cells in a ring band
around the hazard, excluding the hazard's own cells.  It is a measurement, not
``-sensor_height``: on real ground the road is not exactly flat and assuming it
is would hide exactly the errors this table exists to show.
"""

from __future__ import annotations

import numpy as np

from ..core.cell import (
    FLAG_NEGATIVE_OBSTACLE,
    FLAG_OVERHANG,
    FLAG_STEP,
    CellGrid,
)
from ..core.grid import RingGrid
from ..perception import labelmap
from ..synth import SensorSpec, load_scene
from ..synth.raycast import raycast

#: The flag each hazard tag is supposed to raise.
FLAG_FOR_TAG = {
    "pothole":   ("NEGATIVE_OBSTACLE", FLAG_NEGATIVE_OBSTACLE),
    "clearance": ("OVERHANG",          FLAG_OVERHANG),
    "step":      ("STEP",              FLAG_STEP),
}

#: Every hazard flag, for the S1 false-positive count.
ALL_HAZARD_FLAGS = np.uint8(
    FLAG_OVERHANG | FLAG_NEGATIVE_OBSTACLE | FLAG_STEP
)

#: Radial half-width of the band the road reference is taken from, in metres.
#: Wide enough to contain several beam ground-hits at hazard ranges (their
#: spacing is r²·δ/h — 0.65 m at 12 m, 3.2 m at 27 m), narrow enough that a
#: real road's grade does not walk the reference away from the hazard.
REFERENCE_BAND_M = 8.0

#: Frames of tracker warm-up before a ``track`` hazard's speed is scored.
#: 1.0 s at 10 Hz, the same figure T-D2 uses.
TRACK_WARMUP_FRAMES = 10


# ---------------------------------------------------------------------------
# Scene execution
# ---------------------------------------------------------------------------

def sensor_from_config(cfg) -> SensorSpec:
    """Build the ray-caster's sensor from ``config.yaml`` (NFR-7)."""
    s = cfg.synth
    return SensorSpec(
        n_beams=int(s.n_beams), n_azimuth=int(s.n_azimuth),
        fov_up=float(s.fov_up), fov_down=float(s.fov_down),
        sensor_height=float(s.sensor_height), r_max=float(s.r_max),
        range_sigma=float(s.range_sigma), dropout=float(s.dropout),
        seed=int(s.seed),
    )


def _frame(scene, sensor, cfg, grid, cells, t_scene):
    """Cast one frame and drive it through accumulate + analyse.

    Returns ``(xyz, instance)`` so callers can associate cells to primitives.
    """
    xyzi, packed = raycast(scene, sensor, t_scene=t_scene)
    sem, inst = labelmap.split_label(packed)
    cells.reset()
    cells.accumulate(
        xyzi[:, :3], xyzi[:, 3],
        labelmap.raw_to_avr(sem), labelmap.raw_is_moving(sem),
    )
    cells.analyse(cfg)
    return xyzi[:, :3], inst


def _cells_of_instance(grid: RingGrid, cells: CellGrid, xyz, inst, want: int):
    """Occupied cell ids containing at least one point of instance ``want``."""
    member = inst == want
    if not np.any(member):
        return np.zeros(0, dtype=np.int32)
    cid, valid = grid.cell_of(xyz[member, 0], xyz[member, 1])
    ids = np.unique(cid[valid])
    return ids[cells.count[ids] > 0]


def _road_reference(grid, cells, hazard_ids, r_centre: float) -> float:
    """Median ``z_ground`` of occupied cells in a band around ``r_centre``.

    Excludes the hazard's own cells, so a wide hazard cannot become its own
    reference — which is the failure that makes a whole-ring median useless
    for a pit (the pit is the only thing occupying its ring).
    """
    occ = np.flatnonzero(cells.count > 0)
    xy = grid.cell_centres(occ)
    r = np.hypot(xy[:, 0], xy[:, 1])
    band = occ[np.abs(r - r_centre) <= REFERENCE_BAND_M]
    band = band[~np.isin(band, hazard_ids)]
    z = cells.z_ground[band]
    z = z[np.isfinite(z)]
    if z.size == 0:
        return float("nan")
    return float(np.median(z))


# ---------------------------------------------------------------------------
# The 2D counterfactual (PRD §10.4)
# ---------------------------------------------------------------------------

def occupancy_2d(xyz: np.ndarray, res_m: float, z_free: float) -> dict:
    """A plain 2D occupancy grid, as a navigation stack would build one.

    A column is *occupied* if it holds any return higher than ``z_free`` — the
    highest a return can be and still be something the vehicle drives over.
    The naive "occupied if any return at all" version marks the road itself
    blocked and is not a baseline anyone would ship, so it is not the one we
    argue against.

    Returns integer cell coordinates for the occupied and the observed sets.
    """
    ij = np.floor(xyz[:, :2] / res_m).astype(np.int64)
    key = ij[:, 0] * np.int64(1 << 32) + ij[:, 1]
    above = xyz[:, 2] > z_free
    return {
        "observed": set(key.tolist()),
        "occupied": set(key[above].tolist()),
        "res_m": res_m,
    }


def _counterfactual(tag: str, xyz, inst, want: int, res_m: float, z_free: float) -> dict:
    """What a 2D occupancy grid does with this hazard, as a number."""
    grid2d = occupancy_2d(xyz, res_m, z_free)
    member = inst == want
    ij = np.floor(xyz[member, :2] / res_m).astype(np.int64)
    keys = set((ij[:, 0] * np.int64(1 << 32) + ij[:, 1]).tolist())
    if not keys:
        return {"verdict": "no returns"}

    blocked = len(keys & grid2d["occupied"])
    frac = blocked / len(keys)

    if tag == "pothole":
        return {
            "cells": len(keys), "blocked_fraction": round(frac, 4),
            "verdict": "free space — a depression holds no returns above the "
                       "road, so a 0.22 m hole is byte-identical to flat road",
            "hazard_representable": False,
        }
    if tag == "clearance":
        return {
            "cells": len(keys), "blocked_fraction": round(frac, 4),
            "verdict": "road lost — the deck's returns block the column, so "
                       "the drivable road beneath the overpass is marked "
                       "impassable",
            "hazard_representable": False,
        }
    if tag == "step":
        return {
            "cells": len(keys), "blocked_fraction": round(frac, 4),
            "verdict": "occupied, but at what height is not recoverable — a "
                       "0.15 m kerb sets the same single bit as a 3 m wall",
            "hazard_representable": False,
        }
    return {"cells": len(keys), "blocked_fraction": round(frac, 4)}


# ---------------------------------------------------------------------------
# Per-hazard measurement
# ---------------------------------------------------------------------------

def _measure(tag, gt, cells, ids, road_ref):
    """-> (true_value, measured, extras dict).  NaN measured where unmeasurable."""
    flagged = ids[(cells.flags[ids] & FLAG_FOR_TAG[tag][1]) != 0]

    if tag == "pothole":
        true = float(gt["depth_m"])
        pool = flagged if flagged.size else ids
        z = cells.z_ground[pool]
        z = z[np.isfinite(z)]
        measured = float(road_ref - z.min()) if z.size else float("nan")
        z_all = cells.z_ground[ids]
        z_all = z_all[np.isfinite(z_all)]
        # T-H2 asks for the flag on >= 80% of *covering* cells, and a pit's
        # covering cells include its rim, which is at road level by
        # construction and must not fire.  Both denominators are reported: the
        # literal one, and the one restricted to cells that are actually sunk
        # below the local road.
        sunk = ids[np.isfinite(cells.z_ground[ids])
                   & (road_ref - cells.z_ground[ids] > 0.10)]
        n_sunk_flagged = int(np.count_nonzero(
            cells.flags[sunk] & FLAG_NEGATIVE_OBSTACLE
        )) if sunk.size else 0
        extras = {
            "depth_from_corroborated_cell": measured,
            "cells_below_reference": int(sunk.size),
            "detection_rate_below_reference": (
                round(n_sunk_flagged / sunk.size, 4) if sunk.size else None
            ),
            "depth_p10_m": (
                round(float(road_ref - np.percentile(z_all, 10)), 4)
                if z_all.size else None
            ),
            "note": (
                "the pit is grazed at 8 deg at 12 m, so most returns land on "
                "its far inner wall rather than its floor: the p10 estimate "
                "measures the wall, the deepest corroborated cell measures the "
                "floor"
            ),
        }
        return true, measured, extras

    if tag == "clearance":
        true = float(gt["clearance_m"])
        zo = cells.z_obstacle[ids]
        zo = zo[np.isfinite(zo)]
        measured = float(zo.min() - road_ref) if zo.size else float("nan")
        # FR-13's literal per-cell form, reported so its yield is visible.
        both = ids[
            np.isfinite(cells.z_ground[ids])
            & np.isfinite(cells.z_obstacle[ids])
            & (cells.z_obstacle[ids] - cells.z_ground[ids] > 0.5)
        ]
        per_cell = (
            float(np.median(cells.z_obstacle[both] - cells.z_ground[both]))
            if both.size else None
        )
        return true, measured, {
            "clearance_cells_with_both": int(both.size),
            "clearance_per_cell_median_m": per_cell,
            "note": (
                "measured as the structure's lowest return above the road "
                "reference; FR-13's per-cell z_obstacle - z_ground is "
                "reported separately because a beam that strikes the deck "
                "underside and a beam that strikes the road beneath it land "
                "at different ranges, so they almost never share a cell"
            ),
        }

    if tag == "step":
        true = float(gt["height_m"])
        z = cells.z_ground[ids]
        z = z[np.isfinite(z)]
        measured = (
            float(np.percentile(z, 90) - road_ref) if z.size else float("nan")
        )
        return true, measured, {
            "height_p50_m": (
                round(float(np.median(z) - road_ref), 4) if z.size else None
            ),
            "note": (
                "p90 of the covering cells' z_ground: the kerb's cells include "
                "its vertical face, so the median measures the face and the "
                "top is the quantity named by 'a 0.15 m kerb'"
            ),
        }

    raise ValueError(f"no estimator for hazard tag {tag!r}")


def _score_track(scene, sensor, cfg, grid, cells, gt) -> dict:
    """S5's ``track`` row: median tracked speed against the CSV's velocity."""
    from ..decision.tracker import Tracker

    trk = Tracker(cfg)
    speeds: list[float] = []
    ids_seen: set[int] = set()
    frames_with_track = 0
    for f in range(scene.n_frames):
        _frame(scene, sensor, cfg, grid, cells, t_scene=f * float(cfg.synth.frame_dt))
        tracks = trk.update(cells, grid, dt=float(cfg.synth.frame_dt))
        if tracks:
            frames_with_track += 1
            ids_seen.add(tracks[0].id)
            if f >= TRACK_WARMUP_FRAMES:
                speeds.append(tracks[0].speed)

    true = float(gt["speed_mps"])
    measured = float(np.median(speeds)) if speeds else float("nan")
    return {
        "scene": scene.name,
        "hazard": "track speed",
        "tag": "track",
        "flag": "MOVING",
        "true_value": true,
        "measured": round(measured, 4),
        "error": round(abs(measured - true), 4),
        "cells_covering": None,
        "cells_flagged": None,
        "detection_rate": round(frames_with_track / scene.n_frames, 4),
        "frame_detection_rate": round(frames_with_track / scene.n_frames, 4),
        "n_frames": scene.n_frames,
        "track_ids": sorted(ids_seen),
        "id_stable": len(ids_seen) == 1,
        "counterfactual_2d": {
            "verdict": "position only — a 2D occupancy grid carries no height, "
                       "so a crossing truck and a bollard are the same cell",
            "hazard_representable": False,
        },
        "note": (
            f"median over frames >= {TRACK_WARMUP_FRAMES}; the residual is the "
            "visible-surface parallax described in decision/tracker.py, not "
            "filter error"
        ),
    }


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def score_scene(name: str, cfg, grid: RingGrid | None = None) -> dict:
    """Score one synthetic scene.  -> a list-of-rows dict for ``results.json``."""
    grid = grid or RingGrid(
        s_min=float(cfg.grid.s_min), s_max=float(cfg.grid.s_max),
        r_knee=float(cfg.grid.r_knee), r_max=float(cfg.grid.r_max),
    )
    cells = CellGrid(grid)
    sensor = sensor_from_config(cfg)
    scene = load_scene(name)
    gt_all = scene.ground_truth
    dt = float(cfg.synth.frame_dt)

    rows: list[dict] = []

    # ── control scenes: every flag is a false positive (T-H4) ─────────────
    if gt_all["expect_no_hazards"]:
        xyz, _ = _frame(scene, sensor, cfg, grid, cells, 0.0)
        occ = cells.count > 0
        fp = int(np.count_nonzero((cells.flags & ALL_HAZARD_FLAGS)[occ]))
        n_occ = int(occ.sum())
        rows.append({
            "scene": scene.name,
            "hazard": "false positives",
            "tag": "control",
            "flag": "OVERHANG|NEGATIVE_OBSTACLE|STEP",
            "true_value": 0.0,
            "measured": float(fp),
            "error": float(fp),
            "cells_covering": n_occ,
            "cells_flagged": fp,
            "detection_rate": None,
            "frame_detection_rate": None,
            "false_positive_rate": round(fp / n_occ, 6) if n_occ else None,
            "n_frames": scene.n_frames,
            "counterfactual_2d": {"verdict": "not applicable — no hazard"},
        })
        return {"scene": scene.name, "rows": rows}

    # ── S5's moving object is scored over the whole sequence ─────────────
    for gt in gt_all["hazards"]:
        if gt["tag"] == "track":
            rows.append(_score_track(scene, sensor, cfg, grid, cells, gt))

    static = [h for h in gt_all["hazards"] if h["tag"] != "track"]
    if not static:
        return {"scene": scene.name, "rows": rows}

    # ── static hazards: measured on frame 0, detected over every frame ───
    per_hazard_frames = {h["instance_id"]: 0 for h in static}
    measurement: dict[int, tuple] = {}

    for f in range(scene.n_frames):
        xyz, inst = _frame(scene, sensor, cfg, grid, cells, t_scene=f * dt)
        for gt in static:
            inst_id = gt["instance_id"]
            ids = _cells_of_instance(grid, cells, xyz, inst, inst_id)
            if ids.size == 0:
                continue
            flag = FLAG_FOR_TAG[gt["tag"]][1]
            n_flagged = int(np.count_nonzero(cells.flags[ids] & flag))
            if n_flagged:
                per_hazard_frames[inst_id] += 1
            if f == 0:
                road_ref = _road_reference(
                    grid, cells, ids, float(gt["range_m"])
                )
                true, measured, extras = _measure(
                    gt["tag"], gt, cells, ids, road_ref
                )
                measurement[inst_id] = (
                    true, measured, extras, ids.size, n_flagged, road_ref,
                    _counterfactual(
                        gt["tag"], xyz, inst, inst_id,
                        float(cfg.grid.s_min), road_ref + float(cfg.vehicle.max_step),
                    ),
                )

    for gt in static:
        inst_id = gt["instance_id"]
        if inst_id not in measurement:
            rows.append({
                "scene": scene.name, "hazard": gt["tag"], "tag": gt["tag"],
                "true_value": None, "measured": None, "error": None,
                "cells_covering": 0, "cells_flagged": 0,
                "detection_rate": 0.0, "frame_detection_rate": 0.0,
                "n_frames": scene.n_frames,
                "note": "no returns reached this hazard",
            })
            continue
        true, measured, extras, n_cov, n_flag, road_ref, cf = measurement[inst_id]
        rows.append({
            "scene": scene.name,
            "hazard": {"pothole": "pothole depth",
                       "clearance": "overhead clearance",
                       "step": "step height"}[gt["tag"]],
            "tag": gt["tag"],
            "flag": FLAG_FOR_TAG[gt["tag"]][0],
            "true_value": round(true, 4),
            "measured": round(measured, 4),
            "error": round(abs(measured - true), 4),
            "cells_covering": int(n_cov),
            "cells_flagged": int(n_flag),
            # §10.4 names the frame-level rate; T-H2 names the cell-level one.
            # Both are reported because on a one-frame scene the frame rate is
            # 0 or 1 and says almost nothing.
            "detection_rate": round(n_flag / n_cov, 4) if n_cov else 0.0,
            "frame_detection_rate": round(
                per_hazard_frames[inst_id] / scene.n_frames, 4
            ),
            "n_frames": scene.n_frames,
            "road_reference_z_m": round(road_ref, 4),
            "counterfactual_2d": cf,
            **extras,
        })

    return {"scene": scene.name, "rows": rows}


def score_all(cfg, scenes: list[str] | None = None) -> dict:
    """The ``hazards`` block of ``results.json``.  PRD §11.4."""
    from ..synth.scenegen import list_scenes

    names = scenes if scenes is not None else [p.stem for p in list_scenes()]
    grid = RingGrid(
        s_min=float(cfg.grid.s_min), s_max=float(cfg.grid.s_max),
        r_knee=float(cfg.grid.r_knee), r_max=float(cfg.grid.r_max),
    )

    rows: list[dict] = []
    for name in names:
        rows.extend(score_scene(name, cfg, grid)["rows"])

    scored = [r for r in rows if r.get("error") is not None and r["tag"] != "control"]
    control = [r for r in rows if r["tag"] == "control"]
    return {
        "scenes": rows,
        "n_scenes": len(names),
        "max_error_m": (
            round(max(r["error"] for r in scored), 4) if scored else None
        ),
        "false_positives": sum(int(r["measured"]) for r in control),
        "counterfactual_note": (
            "The 2D column marks a cell occupied when it holds a return more "
            f"than {float(cfg.vehicle.max_step):.2f} m above the local road — "
            "the standard navigation grid, not the strawman that blocks the "
            "road itself"
        ),
    }
