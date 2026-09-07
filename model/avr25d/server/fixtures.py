"""Synthetic schema-valid FrameMessages for frontend development (IMPLEMENTATION_PLAN §5.3).

This module has ZERO dependency on ``core/``, ``perception/``, or any real
data.  It imports only from ``server/protocol.py`` and the standard library /
numpy.  That is the entire point: from Day 1 afternoon, Shubham and Navya can
render adaptive cells, colour them by class, draw routes and tracks, animate a
moving object, and populate the HUD without the real backend existing.

On Day 12, integration is a one-flag change:
    ``--fixtures`` → ``--infer cached``

Nothing in the frontend needs to change.

Scene
-----
A flat 100 m road running forward along x.  A few static obstacles to the sides.
One truck-shaped dynamic object crossing from y = -30 at 8 m/s.  A route going
straight ahead, rerouted around the truck once it gets close.  Stats that look
like a healthy 30 Hz cached-mode run.

Cell geometry
-------------
We generate ring-sector cells directly from the ring math in §3 of the plan,
without importing ``RingGrid``.  The formulas are the same — reproduced here so
this file stays self-contained.  Any discrepancy between these and the real grid
is caught by T-G3 anyway.
"""

from __future__ import annotations

import math
import time
from typing import Iterator

import numpy as np

from .protocol import (
    CellArrays,
    Decision,
    FrameMessage,
    FrameStats,
    RefinedArrays,
    Track,
)

# ---------------------------------------------------------------------------
# Grid constants (mirrors §3, self-contained)
# ---------------------------------------------------------------------------

_S_MIN    = 0.05    # m — cell size at r <= 10 m
_R_KNEE   = 10.0    # m
_R_MAX    = 100.0   # m
_N_INNER  = 200     # rings inside r_knee
_FAR_BINS = 1257    # angular bins per far-field ring (2π / 0.005, rounded)

# AVR-25D class ids
_VOID    = 0
_DRIVE   = 1
_TERRAIN = 2
_STATIC  = 3
_DYNAMIC = 4

# Bytes per cell (25), matching baselines.py
_BYTES_PER_CELL = 25
_N_CELLS_TOTAL  = 705_771
_BASELINE_BYTES = 400_000_000   # 16M cells × 25 B — the uniform 5 cm baseline


def _ring_of(r: float) -> int:
    """Closed-form ring index for a scalar radius."""
    if r <= 0.0:
        return 0
    if r <= _R_KNEE:
        return int(r / _S_MIN)
    k = _N_INNER + int(math.log(r / _R_KNEE) / math.log(1.005))
    return min(k, _N_INNER + 461)   # 462 outer rings → index 200..661


def _r_centre(k: int) -> float:
    """Approximate ring-centre radius for ring index k."""
    if k < _N_INNER:
        return (k + 0.5) * _S_MIN
    n_outer = k - _N_INNER
    r_lo = _R_KNEE * (1.005 ** n_outer)
    r_hi = r_lo * 1.005
    return (r_lo + r_hi) * 0.5


def _n_bins(k: int) -> int:
    """Angular sector count for ring k."""
    if k == 0:
        return 1
    r = _r_centre(k)
    s = _S_MIN if k < _N_INNER else min(0.005 * r, 0.50)
    return max(1, round(2 * math.pi * r / s))


def _cell_centre(k: int, j: int) -> tuple[float, float]:
    """(x, y) centre of cell (k, j)."""
    r = _r_centre(k)
    nb = _n_bins(k)
    theta = (j + 0.5) / nb * 2 * math.pi
    return r * math.cos(theta), r * math.sin(theta)


def _cell_extents(k: int) -> tuple[float, float]:
    """(radial, tangential) extents for ring k."""
    r = _r_centre(k)
    s = _S_MIN if k < _N_INNER else min(0.005 * r, 0.50)
    nb = _n_bins(k)
    tang = 2 * math.pi * r / nb
    return s, tang


# ---------------------------------------------------------------------------
# Scene geometry helpers
# ---------------------------------------------------------------------------

def _road_cells(rng: np.random.Generator) -> tuple[list[int], list[int], list[int]]:
    """
    Sample ring,bin pairs for the flat road surface.
    Returns (rings, bins, classes) for ~50 000 occupied cells.
    """
    rings_out, bins_out, cls_out = [], [], []

    for k in range(0, min(_N_INNER + 462, 662)):
        r = _r_centre(k)
        nb = _n_bins(k)
        # Road occupies roughly the forward 90° arc (theta in [-45°, +45°])
        # plus a narrower strip at the sides
        j_forward_lo = int(nb * (-0.125))  # -45°
        j_forward_hi = int(nb * 0.125)     # +45°
        for j in range(max(0, j_forward_lo), min(nb, j_forward_hi + 1)):
            x, y = _cell_centre(k, j)
            if abs(y) <= 4.0:   # 4 m road half-width
                rings_out.append(k)
                bins_out.append(j)
                # Verge cells just outside road width → terrain
                cls_out.append(_DRIVE)
            elif abs(y) <= 7.0:
                rings_out.append(k)
                bins_out.append(j)
                cls_out.append(_TERRAIN)
        if len(rings_out) > 55_000:
            break

    return rings_out, bins_out, cls_out


# ---------------------------------------------------------------------------
# Static pre-computation — done once at module import, reused every frame
# ---------------------------------------------------------------------------

_RNG_INIT = np.random.default_rng(20260828)

def _build_static_scene() -> dict:
    """Build the fixed parts of the scene once."""
    rng = np.random.default_rng(20260828)

    rings_r, bins_r, cls_r = _road_cells(rng)

    # A few static obstacle columns (poles / walls at the road edge)
    obstacle_specs = [
        (15.0,  5.5, _STATIC),
        (15.0, -5.5, _STATIC),
        (30.0,  6.0, _STATIC),
        (30.0, -6.0, _STATIC),
        (50.0,  7.0, _STATIC),
    ]
    for ox, oy, ocls in obstacle_specs:
        r_o = math.hypot(ox, oy)
        theta_o = math.atan2(oy, ox) % (2 * math.pi)
        k_o = _ring_of(r_o)
        nb_o = _n_bins(k_o)
        j_o = int(theta_o / (2 * math.pi) * nb_o) % nb_o
        rings_r.append(k_o)
        bins_r.append(j_o)
        cls_r.append(ocls)

    n = len(rings_r)
    rings_arr = np.array(rings_r, dtype=np.uint16)
    bins_arr  = np.array(bins_r,  dtype=np.uint16)
    cls_arr   = np.array(cls_r,   dtype=np.uint8)

    # Precompute cell geometry
    z_ground   = np.zeros(n, dtype=np.float32)
    z_obstacle = np.zeros(n, dtype=np.float32)
    for i, (k, j, c) in enumerate(zip(rings_arr, bins_arr, cls_arr)):
        if c == _STATIC:
            z_obstacle[i] = rng.uniform(1.0, 3.5)
        elif c == _TERRAIN:
            z_ground[i] = rng.uniform(-0.02, 0.02)
        z_obstacle[i] = max(z_obstacle[i], z_ground[i])

    roughness  = np.where(cls_arr == _TERRAIN,
                          rng.uniform(0.001, 0.015, n).astype(np.float32), 0.0)
    slope      = np.where(cls_arr == _TERRAIN,
                          rng.uniform(0.0, 3.0, n).astype(np.float32), 0.0)
    confidence = np.full(n, 220, dtype=np.uint8)
    confidence[cls_arr == _TERRAIN] = 160

    # Compute prefix-sum offsets to derive flat cell_ids without importing grid
    # Use a simple sequential id for fixtures — valid enough for the frontend.
    cell_id = np.arange(n, dtype=np.uint32) * 3 + rings_arr.astype(np.uint32)

    return dict(
        n=n,
        rings=rings_arr,
        bins=bins_arr,
        cls=cls_arr,
        z_ground=z_ground.astype(np.float32),
        z_obstacle=z_obstacle.astype(np.float32),
        roughness=roughness.astype(np.float32),
        slope=slope.astype(np.float32),
        confidence=confidence,
        cell_id=cell_id,
    )


_SCENE = _build_static_scene()

# ---------------------------------------------------------------------------
# Dynamic (per-frame) content
# ---------------------------------------------------------------------------

# The crossing repeats on this cycle so the demo beat can be rehearsed rather
# than caught once.  Previously y grew without bound, so the truck crossed in
# the first 8 s of server uptime and then drove away for good — 26 km out by
# frame 100,000.  A live viewer therefore saw no track, no reroute and a
# constant reason string, because by the time a browser connected the only
# dynamic object in the scene was long gone.  Frontend __dev__/devFrames.ts had
# always looped its truck; the server had not, which is why the viewer looked
# right in development and empty against the real stream.
#
# 80 m at 8 m/s is a 10 s cycle: the truck enters at y = -30, crosses the road,
# leaves the field of view at y = 35, and is off-scene for ~1.9 s before it
# re-enters.  That gap matters — it keeps the run-book's "track appears" beat
# demonstrable, and it keeps the empty-`tracks` path exercised rather than
# leaving a dynamic object permanently parked in view.
_TRUCK_CYCLE_M = 80.0


def _truck_position(frame_id: int, dt: float = 1.0 / 30) -> tuple[float, float]:
    """Truck crosses at 8.0 m/s in +y from y = -30, repeating every cycle."""
    t = frame_id * dt
    return 18.0, -30.0 + (8.0 * t) % _TRUCK_CYCLE_M   # x = 18 m ahead


def _truck_cells(x: float, y: float) -> tuple[list, list, list]:
    """Ring/bin pairs occupied by the crossing truck (3 m × 2 m footprint)."""
    r_list, b_list, c_list = [], [], []
    for dx in (-1.0, 0.0, 1.0):
        for dy in (-0.5, 0.5):
            px, py = x + dx, y + dy
            r = math.hypot(px, py)
            if r > _R_MAX or r < 0.01:
                continue
            theta = math.atan2(py, px) % (2 * math.pi)
            k = _ring_of(r)
            nb = _n_bins(k)
            j = int(theta / (2 * math.pi) * nb) % nb
            r_list.append(k)
            b_list.append(j)
            c_list.append(_DYNAMIC)
    return r_list, b_list, c_list


def _make_flags(cls: np.ndarray, z_ground: np.ndarray,
                z_obstacle: np.ndarray) -> np.ndarray:
    """Simple flag assignment: OCCUPIED=1 for all, MOVING=32 for DYNAMIC."""
    flags = np.ones(len(cls), dtype=np.uint8)   # bit 0 = OCCUPIED
    flags[cls == _DYNAMIC] |= np.uint8(1 << 5)  # bit 5 = MOVING
    return flags


# ---------------------------------------------------------------------------
# Public generator
# ---------------------------------------------------------------------------

def frame_generator(
    start_frame: int = 0,
    fps_target: float = 30.0,
) -> Iterator[FrameMessage]:
    """Yield FrameMessages indefinitely.

    Each call increments the frame counter and advances moving objects.
    Stats are plausible for a healthy cached-mode run at ~30 FPS.
    """
    scene = _SCENE
    frame_id = start_frame
    t_start = time.perf_counter()

    while True:
        t0 = time.perf_counter()
        t_sec = frame_id / fps_target

        # ── truck position ────────────────────────────────────────────────
        tx, ty = _truck_position(frame_id, 1.0 / fps_target)
        truck_visible = -35.0 <= ty <= 35.0 and math.hypot(tx, ty) < _R_MAX

        # ── assemble cell arrays ──────────────────────────────────────────
        if truck_visible:
            tr_list, tb_list, tc_list = _truck_cells(tx, ty)
            n_truck = len(tr_list)
        else:
            tr_list, tb_list, tc_list = [], [], []
            n_truck = 0

        n_static = scene["n"]
        n_total  = n_static + n_truck

        rings_all = np.empty(n_total, dtype=np.uint16)
        bins_all  = np.empty(n_total, dtype=np.uint16)
        cls_all   = np.empty(n_total, dtype=np.uint8)
        rings_all[:n_static] = scene["rings"]
        bins_all[:n_static]  = scene["bins"]
        cls_all[:n_static]   = scene["cls"]

        if n_truck:
            rings_all[n_static:] = np.array(tr_list, dtype=np.uint16)
            bins_all[n_static:]  = np.array(tb_list, dtype=np.uint16)
            cls_all[n_static:]   = np.array(tc_list, dtype=np.uint8)

        z_ground   = np.empty(n_total, dtype=np.float32)
        z_obstacle = np.empty(n_total, dtype=np.float32)
        roughness  = np.empty(n_total, dtype=np.float32)
        slope_arr  = np.empty(n_total, dtype=np.float32)
        confidence = np.empty(n_total, dtype=np.uint8)

        z_ground[:n_static]   = scene["z_ground"]
        z_obstacle[:n_static] = scene["z_obstacle"]
        roughness[:n_static]  = scene["roughness"]
        slope_arr[:n_static]  = scene["slope"]
        confidence[:n_static] = scene["confidence"]

        if n_truck:
            z_ground[n_static:]   = -1.70     # sensor frame: road at -1.7 m
            z_obstacle[n_static:] = -1.70 + 2.8  # truck is ~2.8 m tall
            roughness[n_static:]  = 0.0
            slope_arr[n_static:]  = 0.0
            confidence[n_static:] = 230

        flags = _make_flags(cls_all, z_ground, z_obstacle)

        cell_id = np.empty(n_total, dtype=np.uint32)
        cell_id[:n_static] = scene["cell_id"]
        if n_truck:
            cell_id[n_static:] = (
                rings_all[n_static:].astype(np.uint32) * 1257
                + bins_all[n_static:].astype(np.uint32)
            )

        cells = CellArrays(
            n=n_total,
            cell_id=cell_id,
            ring=rings_all,
            bin=bins_all,
            z_ground=z_ground,
            z_obstacle=z_obstacle,
            roughness=roughness,
            slope=slope_arr,
            class_id=cls_all,
            confidence=confidence,
            flags=flags,
        )

        # ── tracks ────────────────────────────────────────────────────────
        tracks: list[Track] = []
        if truck_visible:
            speed = 8.0
            horizon_s = 4.0
            steps = 5
            predicted = [
                [round(tx, 3), round(ty + speed * (horizon_s * s / steps), 3)]
                for s in range(1, steps + 1)
            ]
            tracks.append(Track(
                id=7,
                x=round(tx, 3),
                y=round(ty, 3),
                vx=0.0,
                vy=speed,
                class_id=_DYNAMIC,
                age=max(1, frame_id % 40),
                speed=speed,
                predicted=predicted,
            ))

        # ── decision ─────────────────────────────────────────────────────
        rerouting = truck_visible and -5.0 <= ty <= 25.0
        route = [[0.0, 0.0], [10.0, 0.0], [25.0, 0.0], [50.0, 0.0]]
        alt_route = [[0.0, 0.0], [10.0, 3.0], [25.0, 6.0], [50.0, 3.0]]

        if rerouting:
            selected = "alternative"
            risk = "MEDIUM"
            reason = (
                f"Rerouted: track #7 (DYNAMIC_OBJECT, 8.0 m/s) predicted to "
                f"intersect primary route at t+{max(0.1, round((25.0 - ty) / 8.0, 1)):.1f} s. "
                "Alternative adds 0.1 km at LOW terrain risk."
            )
        else:
            selected = "primary"
            risk = "LOW"
            reason = (
                "Primary route selected: mean traversability 0.92, max slope 1.2°, "
                "no dynamic conflicts within 4.0 s."
            )

        decision = Decision(
            route=route,
            alternative=alt_route,
            selected=selected,
            risk=risk,
            eta_s=round(50.0 / 8.0 + abs(ty) * 0.02, 1),
            reason=reason,
        )

        # ── stats ─────────────────────────────────────────────────────────
        n_pts = 121_344
        t_elapsed = (time.perf_counter() - t0) * 1000.0
        stats = FrameStats(
            fps=round(fps_target, 1),
            t_perception_ms=0.4,
            t_projection_ms=3.1,
            t_analysis_ms=1.2,
            t_refine_ms=0.3,
            t_decision_ms=0.8,
            t_serialise_ms=round(t_elapsed, 2),
            t_total_ms=round(0.4 + 3.1 + 1.2 + 0.3 + 0.8 + t_elapsed, 2),
            n_points=n_pts,
            n_points_conserved=n_pts,   # FR-10
            n_cells_occupied=n_total,
            n_cells_total=_N_CELLS_TOTAL,
            mem_bytes=_N_CELLS_TOTAL * _BYTES_PER_CELL,
            baseline_mem_bytes=_BASELINE_BYTES,
            reduction=round(_BASELINE_BYTES / (_N_CELLS_TOTAL * _BYTES_PER_CELL), 4),
        )

        yield FrameMessage(
            frame_id=frame_id,
            t_sec=round(t_sec, 4),
            mode="geometric",   # fixtures simulate geometric-mode output
            cells=cells,
            refined=RefinedArrays.empty(),
            tracks=tracks,
            decision=decision,
            stats=stats,
        )

        frame_id += 1

        # ── pace to target FPS (non-blocking) ─────────────────────────────
        elapsed = time.perf_counter() - t0
        target = 1.0 / fps_target
        if elapsed < target:
            time.sleep(target - elapsed)
