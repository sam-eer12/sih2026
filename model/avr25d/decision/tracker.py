"""Constant-velocity Kalman tracker for dynamic objects.  FR-20.
IMPLEMENTATION_PLAN §6.9.

Algorithm
---------
1. Cluster DYNAMIC_OBJECT cells by connected components of a radius graph in
   the **metric XY plane**.
2. Associate clusters to existing tracks by greedy nearest-neighbour gating
   (gate radius = v_max * dt + gate_extra_m).
3. Update each matched track with a Kalman filter:
       state x = [px, py, vx, vy]
       F = [[1, 0, dt, 0],
            [0, 1, 0,  dt],
            [0, 0, 1,  0 ],
            [0, 0, 0,  1 ]]
4. Birth: a cluster that matches for `birth_hits` consecutive frames.
5. Death: a track with `death_misses` consecutive misses is dropped.

Why metres and not (ring, bin)
------------------------------
The obvious clustering is 4-connectivity over the ring table, and it is wrong.
A vehicle at a fixed x sweeping across y occupies a *diagonal* swath of the
table: its visible face spans several metres of range, so its cells climb one
ring per bin or so, and 4-connectivity shears the object into one fragment per
ring.  Measured on ``S5_crossing_truck``: 74 truck cells spread over 42 rings
became **19 clusters**, and because ``tracks[0]`` was then a different fragment
from frame to frame the reported id changed four times in forty frames.  The
one frame that clustered correctly was frame 20 — the truck directly ahead,
where its face is at constant range and occupies two rings.

A radius graph in metres has no preferred axis and no such failure mode: one
cluster on all 40 frames, id stable, and the speed estimate stops being the
finite difference of two different fragments' centroids.

What the speed estimate can and cannot be
-----------------------------------------
The measurement is the centroid of the **visible** cells, not of the object.
On S5 the visible-surface offset runs from +0.81 m when the truck is on the
left to -0.81 m when it is on the right — parallax, as the sensor comes to see
the far side of a box rather than the near one.  That is a real -0.42 m/s bias
on a 3.9 s crossing and no amount of filter tuning removes it: the information
is not in the returns.  T-D2's 0.5 m/s tolerance is met with 0.08 m/s to spare,
and the honest statement is that most of the budget is spent on parallax rather
than on the filter.

Tests: T-D2  (stable ID across S5's 40 frames, speed within 0.5 m/s of 8.0 m/s)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.cell import CellGrid
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
    hits: int           # consecutive hits (need birth_hits to be born)
    misses: int         # consecutive misses
    born: bool          # True once hits >= birth_hits
    n_cells: int        # cells in the last associated cluster


def _F(dt: float) -> np.ndarray:
    return np.array([
        [1, 0, dt, 0],
        [0, 1, 0,  dt],
        [0, 0, 1,  0],
        [0, 0, 0,  1],
    ], dtype=np.float64)


def cluster_centroids(
    cells: CellGrid,
    grid: RingGrid,
    link_m: float = 1.5,
    min_cells: int = 4,
) -> list[tuple[float, float, int, np.ndarray]]:
    """Connected components of DYNAMIC_OBJECT cells in metric XY.

    Returns a list of ``(cx, cy, class_id, cell_ids)``, largest cluster first,
    so a caller that only wants the dominant object can take ``[0]`` and mean
    it.  Clusters smaller than ``min_cells`` are dropped as sensor noise.
    """
    occ = cells.count > 0
    dyn_ids = np.flatnonzero(occ & (cells.class_id == DYNAMIC_OBJECT))
    if dyn_ids.size == 0:
        return []

    xy = grid.cell_centres(dyn_ids)[:, :2]

    if dyn_ids.size == 1:
        labels = np.zeros(1, dtype=np.int32)
    else:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        from scipy.spatial import cKDTree

        pairs = np.array(
            sorted(cKDTree(xy).query_pairs(link_m)), dtype=np.int64
        ).reshape(-1, 2)
        if pairs.size:
            adj = coo_matrix(
                (np.ones(pairs.shape[0], dtype=np.int8), (pairs[:, 0], pairs[:, 1])),
                shape=(dyn_ids.size, dyn_ids.size),
            )
            _, labels = connected_components(adj, directed=False)
        else:
            labels = np.arange(dyn_ids.size, dtype=np.int32)

    out: list[tuple[float, float, int, np.ndarray]] = []
    for label in np.unique(labels):
        member = labels == label
        if int(member.sum()) < min_cells:
            continue
        out.append((
            float(xy[member, 0].mean()),
            float(xy[member, 1].mean()),
            int(DYNAMIC_OBJECT),
            dyn_ids[member],
        ))
    out.sort(key=lambda c: -c[3].size)
    return out


#: Retained under its old private name: ``server/app.py`` and the Day-6 tests
#: import it, and renaming a working call site is not part of fixing the maths.
_cluster_centroids = cluster_centroids


class Tracker:
    """Frame-to-frame nearest-neighbour Kalman tracker.

    Track ids are per-instance and restart at 1 on ``reset()``.  A module-level
    counter would make the id a track gets depend on how many tracks every
    *other* Tracker in the process had already created, which is untestable and,
    in a server that reconstructs the tracker on a sequence change, unbounded.
    """

    def __init__(self, cfg=None) -> None:
        if cfg is None:
            from .. import load_config
            cfg = load_config()
        t = cfg.decision.tracker

        self._link_m       = float(t.link_m)
        self._min_cells    = int(t.min_cells)
        self._v_max        = float(t.v_max)
        self._gate_extra   = float(t.gate_extra_m)
        self._birth_hits   = int(t.birth_hits)
        self._death_misses = int(t.death_misses)
        self._horizon_s    = float(t.horizon_s)
        self._n_steps      = int(t.predict_steps)

        self._Q_diag = np.array(
            [t.q_pos, t.q_pos, t.q_vel, t.q_vel], dtype=np.float64
        )
        self._R = np.diag([float(t.r_meas), float(t.r_meas)])
        self._P0 = np.diag(
            [float(t.p0_pos), float(t.p0_pos), float(t.p0_vel), float(t.p0_vel)]
        )

        self._tracks: list[_TrackState] = []
        self._next_id = 1

    # ── ids ───────────────────────────────────────────────────────────────

    def _new_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    # ── the frame step ────────────────────────────────────────────────────

    def update(self, cells: CellGrid, grid: RingGrid, dt: float) -> list[Track]:
        """Cluster DYNAMIC_OBJECT cells and update tracks.

        Parameters
        ----------
        cells : CellGrid   — analysed cell grid for this frame
        grid  : RingGrid
        dt    : float      — seconds since last call (1/FPS)

        Returns
        -------
        list[Track]  — born tracks, largest first
        """
        detections = cluster_centroids(
            cells, grid, link_m=self._link_m, min_cells=self._min_cells
        )
        gate_r = self._v_max * dt + self._gate_extra

        # ── predict all existing tracks ───────────────────────────────────
        F = _F(dt)
        Q = np.diag(self._Q_diag * dt)
        for t in self._tracks:
            t.x = F @ t.x
            t.P = F @ t.P @ F.T + Q

        # ── greedy nearest-neighbour association ──────────────────────────
        matched_tracks: set[int] = set()
        pairs: list[tuple[int, int]] = []
        used_det: set[int] = set()

        if self._tracks and detections:
            pred_xy = np.array([[t.x[0], t.x[1]] for t in self._tracks])
            det_xy = np.array([[d[0], d[1]] for d in detections])
            dist = np.linalg.norm(pred_xy[:, None, :] - det_xy[None, :, :], axis=2)

            for flat in np.argsort(dist, axis=None):
                ti, di = int(flat // len(detections)), int(flat % len(detections))
                if ti in matched_tracks or di in used_det:
                    continue
                if dist[ti, di] > gate_r:
                    break          # argsort is ascending: nothing later fits
                matched_tracks.add(ti)
                used_det.add(di)
                pairs.append((ti, di))

        # ── Kalman update for matched pairs ───────────────────────────────
        H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float64)
        for ti, di in pairs:
            t = self._tracks[ti]
            z = np.array([detections[di][0], detections[di][1]], dtype=np.float64)
            y = z - H @ t.x
            S = H @ t.P @ H.T + self._R
            K = t.P @ H.T @ np.linalg.inv(S)
            t.x = t.x + K @ y
            t.P = (np.eye(4) - K @ H) @ t.P
            t.hits += 1
            t.misses = 0
            t.age += 1
            t.n_cells = int(detections[di][3].size)
            if t.hits >= self._birth_hits:
                t.born = True

        # ── miss / death ──────────────────────────────────────────────────
        for ti, t in enumerate(self._tracks):
            if ti not in matched_tracks:
                t.misses += 1
                t.hits = 0
                t.age += 1

        self._tracks = [t for t in self._tracks if t.misses < self._death_misses]

        # ── birth new tracks for unmatched detections ─────────────────────
        for di, det in enumerate(detections):
            if di in used_det:
                continue
            cx, cy, cls, members = det
            self._tracks.append(_TrackState(
                id=self._new_id(),
                x=np.array([cx, cy, 0.0, 0.0], dtype=np.float64),
                P=self._P0.copy(),
                class_id=cls, age=1, hits=1, misses=0,
                born=self._birth_hits <= 1,
                n_cells=int(members.size),
            ))

        # ── emit born tracks as protocol Track objects, largest first ─────
        out: list[Track] = []
        for t in sorted(self._tracks, key=lambda t: -t.n_cells):
            if not t.born:
                continue
            step = self._horizon_s / self._n_steps
            out.append(Track(
                id        = t.id,
                x         = round(float(t.x[0]), 3),
                y         = round(float(t.x[1]), 3),
                vx        = round(float(t.x[2]), 3),
                vy        = round(float(t.x[3]), 3),
                class_id  = t.class_id,
                age       = t.age,
                speed     = round(float(np.hypot(t.x[2], t.x[3])), 3),
                predicted = [
                    [round(t.x[0] + t.x[2] * step * s, 3),
                     round(t.x[1] + t.x[3] * step * s, 3)]
                    for s in range(1, self._n_steps + 1)
                ],
            ))
        return out

    def reset(self) -> None:
        """Clear all tracks and restart ids (call at sequence boundaries)."""
        self._tracks.clear()
        self._next_id = 1
