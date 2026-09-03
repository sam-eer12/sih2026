"""Per-cell traversability score in [0, 1].  FR-19.  IMPLEMENTATION_PLAN §6.8.

Owner: Sameer (this stub gives the correct signature so costmap.py can import
it without error; Sameer replaces the body).

Score formula (weights from config.yaml decision.traversability):

    score = clip(1 - Σ wᵢ · pᵢ, 0, 1)

    penalty_slope      = slope_deg / max_slope_deg          (capped at 1.0)
    penalty_roughness  = roughness / max_roughness           (capped at 1.0)
    penalty_step       = 1.0  if STEP flag set, else 0.0
    penalty_class      = {DRIVABLE: 0.0, TERRAIN: 0.5, obstacle: 1.0}
    penalty_clearance  = 1.0  if OVERHANG and clearance < H_vehicle, else 0.0

    LOW_CONFIDENCE cells are pulled toward 0.5:
        score = score * conf_weight + 0.5 * (1 - conf_weight)
        where conf_weight = confidence / 255

Tests: T-D1
"""

from __future__ import annotations

import numpy as np

from ..core.cell import (
    FLAG_LOW_CONFIDENCE,
    FLAG_OVERHANG,
    FLAG_STEP,
    CellGrid,
)
from ..perception.labelmap import DRIVABLE, DYNAMIC_OBJECT, NON_DRIVABLE_TERRAIN


def score(cells: CellGrid, cfg) -> np.ndarray:
    """Per-cell traversability in [0, 1].

    Parameters
    ----------
    cells : CellGrid
        Populated and analysed cell grid for this frame.
    cfg : Config
        Loaded config.yaml.  Reads cfg.decision.traversability.* and
        cfg.vehicle.* and cfg.vehicle.max_slope_deg.

    Returns
    -------
    np.ndarray, float32, shape (n_cells,)
        1.0 = fully traversable, 0.0 = impassable.
        Unoccupied cells (count == 0) return 0.5 (unknown).
    """
    t = cfg.decision.traversability
    w_slope     = float(t.slope_penalty)       # 0.30
    w_rough     = float(t.roughness_penalty)   # 0.20
    w_step      = float(t.step_penalty)        # 0.20
    w_class     = float(t.class_penalty)       # 0.20
    w_clear     = float(t.clearance_penalty)   # 0.10
    conf_pull   = float(t.low_confidence_pull) # 0.5

    max_slope   = float(cfg.vehicle.max_slope_deg)   # 15 deg
    max_rough   = 0.05   # m²  (not in config but documented in §6.8)
    n = cells._grid.n_cells
    occ = cells.count > 0

    # ── slope penalty ─────────────────────────────────────────────────────
    p_slope = np.clip(
        cells.slope.astype(np.float32) / max_slope, 0.0, 1.0
    )

    # ── roughness penalty ─────────────────────────────────────────────────
    p_rough = np.clip(
        cells.roughness.astype(np.float32) / max_rough, 0.0, 1.0
    )

    # ── step penalty ──────────────────────────────────────────────────────
    p_step = ((cells.flags & FLAG_STEP).astype(bool)).astype(np.float32)

    # ── class penalty ─────────────────────────────────────────────────────
    p_class = np.where(
        cells.class_id == DRIVABLE, 0.0,
        np.where(
            cells.class_id == NON_DRIVABLE_TERRAIN, 0.5, 1.0
        )
    ).astype(np.float32)

    # ── clearance penalty ─────────────────────────────────────────────────
    p_clear = ((cells.flags & FLAG_OVERHANG).astype(bool)).astype(np.float32)

    # ── weighted sum ──────────────────────────────────────────────────────
    raw = 1.0 - (
        w_slope * p_slope
        + w_rough * p_rough
        + w_step  * p_step
        + w_class * p_class
        + w_clear * p_clear
    )
    trav = np.clip(raw, 0.0, 1.0).astype(np.float32)

    # ── LOW_CONFIDENCE pull toward 0.5 ────────────────────────────────────
    low_conf = (cells.flags & FLAG_LOW_CONFIDENCE).astype(bool)
    conf_w   = cells.confidence.astype(np.float32) / 255.0
    trav[low_conf] = (
        trav[low_conf] * conf_w[low_conf]
        + conf_pull * (1.0 - conf_w[low_conf])
    )

    # ── unoccupied cells → unknown (0.5) ──────────────────────────────────
    trav[~occ] = 0.5

    return trav
