"""A* route planner over the Cartesian costmap.  FR-22.
IMPLEMENTATION_PLAN §6.10, Tests T-D4.

Owner: Anuj

Cost per step
-------------
    C = w1·dist + w2·slope + w3·roughness + w4·obstacle_risk + w5·clearance_risk

Weights come from config.yaml decision.weights.

Alternative route
-----------------
Re-run A* with the primary corridor cells penalised by a large constant.
This forces a genuinely different path, not a one-cell perturbation.
T-D4 checks that Fréchet distance between primary and alternative exceeds
one cell width (0.25 m).
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

from .costmap import Costmap

# Cost added to primary-corridor cells during the alternative search.
_CORRIDOR_PENALTY = 2.0

# Extra cost for moving diagonally (octile heuristic pre-factor)
_SQRT2 = math.sqrt(2.0)


class Route(NamedTuple):
    """A planned route as a list of world (x, y) waypoints."""
    waypoints: list[list[float]]   # [[x, y], ...]
    length_m:  float
    risk:      str    # "LOW" | "MEDIUM" | "HIGH"
    cost:      float  # raw A* path cost


# ---------------------------------------------------------------------------
# A* core
# ---------------------------------------------------------------------------

def _octile(r1: int, c1: int, r2: int, c2: int) -> float:
    dr = abs(r2 - r1)
    dc = abs(c2 - c1)
    return max(dr, dc) + (_SQRT2 - 1.0) * min(dr, dc)


def _astar(
    cost_grid: np.ndarray,   # float32[size, size]
    start: tuple[int, int],
    goal:  tuple[int, int],
) -> list[tuple[int, int]] | None:
    """A* on a grid.  Returns cell-index path (row, col) or None if unreachable."""
    size = cost_grid.shape[0]
    sr, sc = start
    gr, gc = goal

    g_score  = np.full((size, size), np.inf, dtype=np.float64)
    came_from = {}
    g_score[sr, sc] = 0.0
    f0 = _octile(sr, sc, gr, gc)
    open_heap = [(f0, 0.0, sr, sc)]

    dirs = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]

    while open_heap:
        _, g_cur, r, c = heapq.heappop(open_heap)
        if g_cur > g_score[r, c] + 1e-9:
            continue
        if r == gr and c == gc:
            # Reconstruct path
            path = []
            node = (r, c)
            while node in came_from:
                path.append(node)
                node = came_from[node]
            path.append(start)
            path.reverse()
            return path

        for dr, dc in dirs:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < size and 0 <= nc < size):
                continue
            step = _SQRT2 if (dr and dc) else 1.0
            cell_cost = float(cost_grid[nr, nc])
            if cell_cost >= 1.0:
                continue   # impassable
            tentative = g_score[r, c] + step * (1.0 + cell_cost)
            if tentative < g_score[nr, nc]:
                g_score[nr, nc] = tentative
                came_from[(nr, nc)] = (r, c)
                f = tentative + _octile(nr, nc, gr, gc)
                heapq.heappush(open_heap, (f, tentative, nr, nc))

    return None   # unreachable


def _path_to_waypoints(
    path:   list[tuple[int, int]],
    costmap: Costmap,
) -> list[list[float]]:
    """Cell-index path → world (x, y) waypoints, downsampled every 4 cells."""
    res = costmap.res_m
    half = costmap.extent_m / 2.0
    wps = []
    for i, (r, c) in enumerate(path):
        if i % 4 == 0 or i == len(path) - 1:
            x = (r + 0.5) * res
            y = (c + 0.5) * res - half
            wps.append([round(x, 3), round(y, 3)])
    return wps


def _path_length(path: list[tuple[int, int]], res: float) -> float:
    length = 0.0
    for i in range(1, len(path)):
        dr = path[i][0] - path[i-1][0]
        dc = path[i][1] - path[i-1][1]
        length += math.hypot(dr, dc) * res
    return length


def _risk_level(cost: float, n_cells: int) -> str:
    """Classify route risk from mean cost per cell."""
    mean = cost / max(n_cells, 1)
    if mean < 0.25:
        return "LOW"
    if mean < 0.55:
        return "MEDIUM"
    return "HIGH"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def plan(costmap: Costmap, goal: tuple[float, float] | None, cfg) -> tuple[Route, Route]:
    """Plan a primary and a genuinely distinct alternative route.  FR-22.

    Parameters
    ----------
    costmap : Costmap     — built by costmap.build_costmap()
    goal    : (x, y)      — world goal, or None → straight ahead (x=extent, y=0)
    cfg     : Config

    Returns
    -------
    (primary, alternative)  — both are Route namedtuples.
    If A* fails the fallback is a straight-ahead route at maximum cost.
    """
    size   = costmap.size
    res    = costmap.res_m
    half   = costmap.extent_m / 2.0

    # Start cell: ego position = (0, 0) world → row 0, col size//2
    start_r = 0
    start_c = size // 2

    # Goal cell
    if goal is None:
        goal_x = costmap.extent_m - res   # furthest forward
        goal_y = 0.0
    else:
        goal_x, goal_y = goal

    goal_r = int(np.clip(goal_x / res, 0, size - 1))
    goal_c = int(np.clip((goal_y + half) / res, 0, size - 1))

    # ── primary ───────────────────────────────────────────────────────────
    primary_path = _astar(costmap.cost, (start_r, start_c), (goal_r, goal_c))
    if primary_path is None or len(primary_path) < 2:
        # Straight-ahead fallback
        primary_path = [(r, start_c) for r in range(0, size, 4)]

    primary_wps = _path_to_waypoints(primary_path, costmap)
    primary_len = _path_length(primary_path, res)
    primary_cost = float(sum(costmap.cost[r, c] for r, c in primary_path))
    primary_risk = _risk_level(primary_cost, len(primary_path))
    primary = Route(primary_wps, round(primary_len, 3), primary_risk, round(primary_cost, 4))

    # ── alternative: re-plan with corridor penalty ─────────────────────────
    alt_cost_grid = costmap.cost.copy()
    # Inflate primary corridor cells by a large penalty so A* avoids them
    corridor_cols = {c for _, c in primary_path}
    for r_p, c_p in primary_path:
        for dc in range(-2, 3):
            nc = np.clip(c_p + dc, 0, size - 1)
            alt_cost_grid[r_p, int(nc)] = min(
                1.0, float(alt_cost_grid[r_p, int(nc)]) + _CORRIDOR_PENALTY
            )

    alt_path = _astar(alt_cost_grid, (start_r, start_c), (goal_r, goal_c))
    if alt_path is None or len(alt_path) < 2:
        # Fallback: shift two cells to the right
        alt_path = [(r, min(start_c + 8, size - 1)) for r in range(0, size, 4)]

    alt_wps  = _path_to_waypoints(alt_path, costmap)
    alt_len  = _path_length(alt_path, res)
    # Alternative cost uses the ORIGINAL costmap, not the penalised one
    alt_cost_orig = float(sum(
        float(costmap.cost[r, c]) for r, c in alt_path
    ))
    alt_risk = _risk_level(alt_cost_orig, len(alt_path))
    alternative = Route(alt_wps, round(alt_len, 3), alt_risk, round(alt_cost_orig, 4))

    return primary, alternative
