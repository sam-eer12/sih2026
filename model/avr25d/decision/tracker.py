"""Constant-velocity Kalman tracker for dynamic objects.  FR-20.
IMPLEMENTATION_PLAN §6.9.

Owner: Sameer (this stub gives the correct signature; Sameer replaces the body).

Algorithm
---------
1. Cluster DYNAMIC_OBJECT cells using connected-components in ring-bin space.
2. Associate clusters to existing tracks by nearest-neighbour gating
   (gate radius = v_max * dt + 1.0 m).
3. Update each matched track with a Kalman filter:
       state x = [px, py, vx, vy]
       F = [[1, 0, dt, 0],
            [0, 1, 0,  dt],
            [0, 0, 1,  0 ],
            [0, 0, 0,  1 ]]
4. Birth: a cluster that matches for 2 consecutive frames becomes a track.
5. Death: a track with 3 consecutive misses is dropped.

Tests: T-D2  (stable ID across S5's 40 frames, speed within 0.5 m/s of 8.0 m/s)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core.cell import FLAG_MOVING, CellGrid
from ..core.grid import RingGrid
from ..perception.labelmap import DYNAMIC_OBJECT
from ..server.protocol import Track


# ---------------------------------------------------------------------------
# Internal track state
# ---------------------------------------------------------------------------

@dataclass
class _TrackState:
    id: int
    x: np.ndarray       # float64[4]  — [px, py, vx, vy]
    P: np.ndarray       # float64[4,4] — covariance
    class_id: int
    age: int            # frames since birth
    hits: int           # consecutive hits (need 2 to be born)
    misses: int         # consecutive misses (3 → delete)
    born: bool          # True once hits >= 2


# Process noise (position uncertainty per second)
_Q_DIAG = np.array([0.05, 0.05, 0.5, 0.5], dtype=np.float64)

# Measurement noise (cluster centroid uncertainty)
_R_DIAG = np.array([0.5, 0.5], dtype=np.float64)

# Initial covariance
_P0_DIAG = np.array([1.0, 1.0, 9.0, 9.0], dtype=np.float64)

# Maximum gate radius expansion factor beyond v_max * dt
_GATE_EXTRA_M = 1.0

# v_max for gating (m/s) — a human at 3 m/s, a vehicle at 30 m/s
_V_MAX = 30.0

_next_id = 1


def _new_id() -> int:
    global _next_id
    _next_id += 1
    return _next_id - 1


def _F(dt: float) -> np.ndarray:
    return np.array([
        [1, 0, dt, 0],
        [0, 1, 0,  dt],
        [0, 0, 1,  0],
        [0, 0, 0,  1],
    ], dtype=np.float64)


def _cluster_centroids(
    cells: CellGrid,
    grid: RingGrid,
) -> list[tuple[float, float, int, np.ndarray]]:
    """Connected components of DYNAMIC_OBJECT cells → centroids.

    Returns list of (cx, cy, class_id, cell_ids_array).
    Uses a simple union-find in ring-bin space.
    """
    occ = cells.count > 0
    dyn = occ & (cells.class_id == DYNAMIC_OBJECT)
    dyn_ids = np.flatnonzero(dyn)
    if dyn_ids.size == 0:
        return []

    # Use scipy's connected components on an adjacency in flat-id space.
    # Two cells are adjacent if they share a ring or bin edge.
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    k = cells._cell_ring[dyn_ids]   # ring index per occupied dynamic cell
    j = cells._cell_bin[dyn_ids]    # bin  index

    n = dyn_ids.size
    # Build adjacency: (same ring, consecutive bins) or (consecutive rings, same bin)
    rows, cols = [], []
    id_map = {int(cid): i for i, cid in enumerate(dyn_ids)}

    for idx_local, (ki, ji) in enumerate(zip(k, j)):
        nb_k   = int(grid.n_bins[ki])
        # ring-neighbour
        if ki + 1 < grid.n_rings:
            nb_j = int(round(ji * grid.n_bins[ki + 1] / nb_k))
            nb_id = int(grid.offset[ki + 1]) + nb_j
            if nb_id in id_map:
                rows.append(idx_local); cols.append(id_map[nb_id])
        # bin-neighbours (wrap)
        for dj in (-1, 1):
            nb_j  = (ji + dj) % nb_k
            nb_id = int(grid.offset[ki]) + nb_j
            if nb_id in id_map:
                rows.append(idx_local); cols.append(id_map[nb_id])

    if rows:
        adj = coo_matrix(
            (np.ones(len(rows), dtype=np.int8), (rows, cols)),
            shape=(n, n),
        )
        _, labels = connected_components(adj, directed=False)
    else:
        labels = np.arange(n, dtype=np.int32)

    centroids: list[tuple[float, float, int, np.ndarray]] = []
    xy_all = grid.cell_centres(dyn_ids)

    for label in np.unique(labels):
        members  = dyn_ids[labels == label]
        xy_mem   = xy_all[labels == label]
        cx, cy   = float(xy_mem[:, 0].mean()), float(xy_mem[:, 1].mean())
        cls      = int(DYNAMIC_OBJECT)
        centroids.append((cx, cy, cls, members))

    return centroids


class Tracker:
    """Frame-to-frame nearest-neighbour Kalman tracker."""

    def __init__(self) -> None:
        self._tracks: list[_TrackState] = []

    def update(self, cells: CellGrid, grid: RingGrid, dt: float) -> list[Track]:
        """Cluster DYNAMIC_OBJECT cells and update tracks.

        Parameters
        ----------
        cells : CellGrid   — analysed cell grid for this frame
        grid  : RingGrid
        dt    : float      — seconds since last call (1/FPS)

        Returns
        -------
        list[Track]  — born tracks (age >= 2 consecutive hits)
        """
        detections = _cluster_centroids(cells, grid)
        gate_r     = _V_MAX * dt + _GATE_EXTRA_M

        # ── predict all existing tracks ───────────────────────────────────
        F = _F(dt)
        Q = np.diag(_Q_DIAG * dt)
        for t in self._tracks:
            t.x = F @ t.x
            t.P = F @ t.P @ F.T + Q

        # ── greedy nearest-neighbour association ──────────────────────────
        matched_tracks:  list[int] = []
        matched_detect:  list[int] = []
        used_det = set()

        if self._tracks and detections:
            # Cost matrix: Euclidean distance between predicted position and detection
            pred_xy  = np.array([[t.x[0], t.x[1]] for t in self._tracks])
            det_xy   = np.array([[d[0], d[1]] for d in detections])
            dist_mat = np.linalg.norm(
                pred_xy[:, None, :] - det_xy[None, :, :], axis=2
            )   # shape (n_tracks, n_detections)

            # Greedy: match closest pairs within gate
            order = np.argsort(dist_mat.ravel())
            for flat_idx in order:
                ti = int(flat_idx // len(detections))
                di = int(flat_idx  % len(detections))
                if ti in matched_tracks or di in used_det:
                    continue
                if dist_mat[ti, di] > gate_r:
                    continue
                matched_tracks.append(ti)
                matched_detect.append(di)
                used_det.add(di)

        # ── Kalman update for matched pairs ───────────────────────────────
        H  = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float64)
        R  = np.diag(_R_DIAG)
        for ti, di in zip(matched_tracks, matched_detect):
            t  = self._tracks[ti]
            z  = np.array([detections[di][0], detections[di][1]], dtype=np.float64)
            y  = z - H @ t.x
            S  = H @ t.P @ H.T + R
            K  = t.P @ H.T @ np.linalg.inv(S)
            t.x = t.x + K @ y
            t.P = (np.eye(4) - K @ H) @ t.P
            t.hits  += 1
            t.misses = 0
            t.age   += 1
            if t.hits >= 2:
                t.born = True

        # ── miss / death ──────────────────────────────────────────────────
        for ti, t in enumerate(self._tracks):
            if ti not in matched_tracks:
                t.misses += 1
                t.age    += 1

        self._tracks = [t for t in self._tracks if t.misses < 3]

        # ── birth new tracks for unmatched detections ─────────────────────
        for di, det in enumerate(detections):
            if di in used_det:
                continue
            cx, cy, cls, _ = det
            x0 = np.array([cx, cy, 0.0, 0.0], dtype=np.float64)
            self._tracks.append(_TrackState(
                id=_new_id(), x=x0, P=np.diag(_P0_DIAG),
                class_id=cls, age=1, hits=1, misses=0, born=False,
            ))

        # ── emit born tracks as protocol Track objects ────────────────────
        horizon_s = 4.0
        n_steps   = 5
        out: list[Track] = []
        for t in self._tracks:
            if not t.born:
                continue
            speed = float(np.hypot(t.x[2], t.x[3]))
            predicted = [
                [
                    round(t.x[0] + t.x[2] * horizon_s * s / n_steps, 3),
                    round(t.x[1] + t.x[3] * horizon_s * s / n_steps, 3),
                ]
                for s in range(1, n_steps + 1)
            ]
            out.append(Track(
                id        = t.id,
                x         = round(float(t.x[0]), 3),
                y         = round(float(t.x[1]), 3),
                vx        = round(float(t.x[2]), 3),
                vy        = round(float(t.x[3]), 3),
                class_id  = t.class_id,
                age       = t.age,
                speed     = round(speed, 3),
                predicted = predicted,
            ))
        return out

    def reset(self) -> None:
        """Clear all tracks (call at sequence boundaries)."""
        self._tracks.clear()
