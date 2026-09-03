"""Polar ring map → ego-front Cartesian costmap.  FR-21.
IMPLEMENTATION_PLAN §6.10, Tests T-D3.

Owner: Anuj

Algorithm
---------
Resample the polar ring map into a 160 × 160 Cartesian grid covering
40 m × 40 m in front of the vehicle, at 0.25 m/cell.

    Grid origin: ego position (x=0, y=0).
    x-axis: forward.  y-axis: left.
    Cell (ix, iy): world centre = (ix * res, iy * res - half_extent)
                   ix ∈ [0, size)  →  x ∈ [0, extent)
                   iy ∈ [0, size)  →  y ∈ [-half, +half)

Resampling: nearest-neighbour only — NO interpolation.
Reason: interpolating a traversability score across a curb edge invents a ramp
that doesn't exist.  The point is preserved information, not smoothed guesses.

Obstacle inflation: each STATIC or DYNAMIC obstacle cell inflates by
vehicle_half_width (1.25 m default) in all four cardinal directions.

Track prediction: a track predicted to occupy a cell at t + horizon_s adds
a soft cost (configurable).
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

from ..core.cell import FLAG_OVERHANG, FLAG_STEP, CellGrid
from ..core.grid import RingGrid
from ..perception.labelmap import DYNAMIC_OBJECT, STATIC_OBSTACLE
from ..server.protocol import Track


class Costmap(NamedTuple):
    """The 160×160 ego-front Cartesian costmap.

    All arrays have shape (size, size) where size = round(extent / res).
    Row 0 = x=0 (ego), row size-1 = x=extent.
    Col 0 = y=-half_extent, col size-1 = y=+half_extent.
    """
    cost:        np.ndarray   # float32[size, size]  — total traversal cost
    traversability: np.ndarray  # float32[size, size]  — raw trav score
    class_id:    np.ndarray   # uint8[size, size]
    flags:       np.ndarray   # uint8[size, size]
    extent_m:    float        # 40.0
    res_m:       float        # 0.25
    size:        int          # 160


def build_costmap(
    cells:  CellGrid,
    trav:   np.ndarray,    # float32[n_cells] from traversability.score()
    tracks: list[Track],
    grid:   RingGrid,
    cfg,
) -> Costmap:
    """Build the ego-front Cartesian costmap.  FR-21.

    Parameters
    ----------
    cells   : CellGrid        — analysed cell grid for this frame
    trav    : np.ndarray      — float32[n_cells] traversability scores
    tracks  : list[Track]     — live tracks from Tracker.update()
    grid    : RingGrid
    cfg     : Config

    Returns
    -------
    Costmap namedtuple
    """
    extent_m   = float(cfg.decision.costmap.extent_m)   # 40.0
    res_m      = float(cfg.decision.costmap.res_m)       # 0.25
    horizon_s  = float(cfg.decision.horizon_s)           # 4.0
    veh_w      = float(cfg.vehicle.width)                 # 2.50 m
    half_w     = veh_w / 2.0                              # inflation radius

    size = int(round(extent_m / res_m))                  # 160

    # ── build Cartesian sample points ─────────────────────────────────────
    # ix ∈ [0, size): x_world = (ix + 0.5) * res_m
    # iy ∈ [0, size): y_world = (iy + 0.5) * res_m - extent_m / 2
    half_ext = extent_m / 2.0
    ix_arr = np.arange(size, dtype=np.float64)
    iy_arr = np.arange(size, dtype=np.float64)
    x_world = (ix_arr + 0.5) * res_m                     # [size]
    y_world = (iy_arr + 0.5) * res_m - half_ext          # [size]

    # Broadcast to (size, size) grids then flatten
    x_grid, y_grid = np.meshgrid(x_world, y_world, indexing="ij")  # both [size, size]
    x_flat = x_grid.ravel()
    y_flat = y_grid.ravel()

    # ── nearest-neighbour lookup in the polar ring map ────────────────────
    cell_ids, valid = grid.cell_of(x_flat, y_flat)

    n_cart = size * size
    trav_map = np.full(n_cart, 0.5, dtype=np.float32)   # default: unknown
    cls_map  = np.zeros(n_cart, dtype=np.uint8)
    flag_map = np.zeros(n_cart, dtype=np.uint8)

    v = valid
    cids = cell_ids[v]
    trav_map[v] = np.where(
        cells.count[cids] > 0,
        trav[cids],
        0.5,
    )
    cls_map[v]  = cells.class_id[cids]
    flag_map[v] = cells.flags[cids]

    # ── obstacle inflation ────────────────────────────────────────────────
    # Any cell that is a static or dynamic obstacle inflates by half_w in x/y.
    is_obstacle_flat = (cls_map == STATIC_OBSTACLE) | (cls_map == DYNAMIC_OBJECT)
    trav_map_2d  = trav_map.reshape(size, size)
    obs_map_2d   = is_obstacle_flat.reshape(size, size)

    inflate_cells = int(np.ceil(half_w / res_m))
    if inflate_cells > 0 and obs_map_2d.any():
        from scipy.ndimage import binary_dilation
        inflated = binary_dilation(
            obs_map_2d,
            iterations=inflate_cells,
        )
        # Inflated zone: zero traversability (cannot drive through the vehicle body)
        trav_map_2d[inflated & ~obs_map_2d] = 0.0

    # ── track prediction soft cost ────────────────────────────────────────
    TRACK_COST = 0.3   # soft penalty added to trav where a track is predicted
    for track in tracks:
        for pred_xy in track.predicted:
            px, py = float(pred_xy[0]), float(pred_xy[1])
            if not (0 <= px < extent_m and -half_ext <= py < half_ext):
                continue
            pix = int(px / res_m)
            piy = int((py + half_ext) / res_m)
            pix = np.clip(pix, 0, size - 1)
            piy = np.clip(piy, 0, size - 1)
            trav_map_2d[pix, piy] = max(
                0.0, float(trav_map_2d[pix, piy]) - TRACK_COST
            )

    # ── cost = 1 - traversability ─────────────────────────────────────────
    # Low traversability = high cost.  Planner minimises cost.
    cost_2d = np.clip(1.0 - trav_map_2d, 0.0, 1.0).astype(np.float32)

    return Costmap(
        cost          = cost_2d,
        traversability= trav_map_2d.astype(np.float32),
        class_id      = cls_map.reshape(size, size).astype(np.uint8),
        flags         = flag_map.reshape(size, size).astype(np.uint8),
        extent_m      = extent_m,
        res_m         = res_m,
        size          = size,
    )
