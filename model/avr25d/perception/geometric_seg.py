"""Deep-learning-free fallback segmenter (FR-5).

RANSAC ground plane, then Euclidean clustering of what is left, then a
bounding-box gate that splits clusters into static structure and traffic.  Same
five classes as the network, selectable at runtime with ``--infer geometric``.

**This exists on Day 1 and it is not a contingency.**  It costs about three
hours and it removes the largest schedule risk in the project (R-2): from the
moment it lands, the grid engine, the decision layer, the dashboard and the
benchmark harness all have labelled input, whether or not an ONNX checkpoint
ever materialises.  Afterwards it keeps earning its place as the ablation that
shows what the network actually buys.

Two deliberate behaviours worth knowing before reading a result table:

*Sub-plane points are terrain, not obstacles.*  A pothole floor is 0.22 m below
the fitted plane and therefore is not a ground inlier, but calling it a
``STATIC_OBSTACLE`` would be actively misleading — there is nothing there to
hit.  Points below the plane are classified ``NON_DRIVABLE_TERRAIN``.  The
negative obstacle is then detected *geometrically*, by the grid, from the
``z_ground`` drop (FR-14); the segmenter's job is only to not lie about it.

*Beyond the fit radius the cautious class wins.*  The plane is fitted over
``r < fit_radius`` where returns are dense; past that it is an extrapolation.
Points that sit within the tight ``ground_tol`` band of the extrapolated plane
are still called ``DRIVABLE``, but the wider ``terrain_tol`` skirt around it —
points that are nearly-but-not-quite on the plane, which is what a verge or a
rough shoulder looks like at 60 m — is called ``NON_DRIVABLE_TERRAIN`` rather
than being promoted to road.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from avr25d.perception.labelmap import (
    DRIVABLE,
    DYNAMIC_OBJECT,
    NON_DRIVABLE_TERRAIN,
    STATIC_OBSTACLE,
    VOID,
)

#: Points sampled when scoring RANSAC hypotheses.  Scoring against a subsample
#: and then assigning against the full cloud is standard, and it is the
#: difference between a 30 ms segmenter and a 400 ms one.
_SCORE_SUBSAMPLE = 20_000


@dataclass(frozen=True)
class GroundPlane:
    """A fitted ground plane, ``n·p + d = 0`` with ``n`` unit and pointing up."""

    normal: np.ndarray   # float64[3]
    d: float
    n_inliers: int
    tilt_deg: float

    def signed_distance(self, xyz: np.ndarray) -> np.ndarray:
        """Height above the plane, float32[n].  Negative is below it."""
        return (xyz @ self.normal + self.d).astype(np.float32)


def _geometric_cfg(cfg):
    """Accept the whole config or just the ``perception.geometric`` subtree."""
    if hasattr(cfg, "perception"):
        return cfg.perception.geometric
    if hasattr(cfg, "geometric"):
        return cfg.geometric
    return cfg


def fit_ground_plane(xyz: np.ndarray, cfg) -> GroundPlane | None:
    """RANSAC ground-plane fit over ``r < fit_radius``.  None if no fit holds.

    Hypotheses whose normal tilts more than ``max_normal_tilt_deg`` from
    vertical are rejected outright.  Without that gate the fit happily locks
    onto the side of a building, which has more coplanar points than the road in
    a narrow street and would invert the entire segmentation.
    """
    g = _geometric_cfg(cfg)
    xy_r = np.hypot(xyz[:, 0], xyz[:, 1])
    candidate = np.flatnonzero(xy_r < g.fit_radius)
    if candidate.size < 3:
        return None

    rng = np.random.default_rng(g.seed)
    scoring = candidate
    if scoring.size > _SCORE_SUBSAMPLE:
        scoring = rng.choice(scoring, _SCORE_SUBSAMPLE, replace=False)
    pts = xyz[scoring].astype(np.float64)

    cos_limit = np.cos(np.deg2rad(g.max_normal_tilt_deg))
    best_normal: np.ndarray | None = None
    best_d = 0.0
    best_count = -1

    triples = rng.integers(0, pts.shape[0], size=(int(g.iterations), 3))
    for tri in triples:
        a, b, c = pts[tri[0]], pts[tri[1]], pts[tri[2]]
        n = np.cross(b - a, c - a)
        norm = np.linalg.norm(n)
        if norm < 1e-9:
            continue
        n = n / norm
        if n[2] < 0:
            n = -n
        if n[2] < cos_limit:          # too tilted to be ground
            continue
        d = -float(n @ a)
        count = int(np.count_nonzero(np.abs(pts @ n + d) <= g.ground_tol))
        if count > best_count:
            best_count, best_normal, best_d = count, n, d

    if best_normal is None or best_count < 3:
        return None

    # Refit by least squares on the consensus set.  The minimal 3-point sample
    # fixes the plane's orientation to within the noise of three points; the
    # refit uses every inlier and is what gets the RMS down to the sensor's own
    # noise floor rather than three times it.
    full = xyz[candidate].astype(np.float64)
    inliers = full[np.abs(full @ best_normal + best_d) <= g.ground_tol]
    if inliers.shape[0] >= 3:
        centroid = inliers.mean(axis=0)
        _, _, vh = np.linalg.svd(inliers - centroid, full_matrices=False)
        n = vh[-1]
        if n[2] < 0:
            n = -n
        if n[2] >= cos_limit:
            best_normal, best_d = n, -float(n @ centroid)
            best_count = int(
                np.count_nonzero(np.abs(full @ best_normal + best_d) <= g.ground_tol)
            )

    return GroundPlane(
        normal=best_normal,
        d=best_d,
        n_inliers=best_count,
        tilt_deg=float(np.degrees(np.arccos(np.clip(best_normal[2], -1.0, 1.0)))),
    )


def cluster(xyz: np.ndarray, cfg) -> np.ndarray:
    """Euclidean clustering by connected components.  -> int32[n] cluster ids.

    Edges come from each point's ``cluster_knn`` nearest neighbours, filtered to
    ``cluster_radius``.  A full radius-pair query is the textbook formulation
    but its edge count is unbounded — a dense urban scan can produce tens of
    millions of pairs and turn a 20 ms stage into a 2 s one.  The k-NN graph
    caps edges at ``k·n`` and gives the same components wherever the object is
    denser than ``k`` points, which is every object we care about.
    """
    g = _geometric_cfg(cfg)
    n = xyz.shape[0]
    if n == 0:
        return np.zeros(0, dtype=np.int32)
    if n == 1:
        return np.zeros(1, dtype=np.int32)

    k = min(int(g.cluster_knn) + 1, n)     # +1: the query point is its own NN
    tree = cKDTree(xyz)
    dist, idx = tree.query(xyz, k=k, workers=-1)

    src = np.repeat(np.arange(n), k - 1)
    dst = idx[:, 1:].ravel()
    keep = dist[:, 1:].ravel() <= g.cluster_radius
    src, dst = src[keep], dst[keep]

    if src.size == 0:
        return np.arange(n, dtype=np.int32)

    graph = coo_matrix(
        (np.ones(src.size, dtype=np.int8), (src, dst)), shape=(n, n)
    )
    _, labels = connected_components(graph, directed=False)
    return labels.astype(np.int32)


def _classify_cluster(pts: np.ndarray, height: np.ndarray, g) -> int:
    """Bounding-box gate: is this cluster raised ground, traffic, or structure?

    Four questions in order, each answerable from the bounding box alone, and
    each with a number in ``config.yaml`` behind it.  The order matters.

    1. *Is it floating?*  A cluster whose base sits well above the road is
       structure — an overpass deck, a gantry, a canopy.  This is asked first
       because the two tests below are about things standing on the ground, and
       an overpass deck answers "large, low and flat" affirmatively if you let
       it.
    2. *Is it raised ground?*  Large, flat and resting on the road — a footway
       or a verge.  A 0.15 m kerb line runs for a hundred metres, and without
       this test it is one enormous cluster that gets called a wall.
    3. *Is it traffic?*  Vehicle-shaped or person-shaped.  ``min_aspect`` is the
       gate that earns its keep: a vehicle is at least as long as it is tall,
       which a bridge pier, a lamp post and a tree trunk are emphatically not.
    4. *Otherwise it is structure.*  The safe default — an unrecognised solid
       thing above the road is an obstacle, not something to drive through.
    """
    if pts.shape[0] < g.min_cluster_points:
        return VOID

    extent = pts.max(axis=0) - pts.min(axis=0)
    footprint = float(max(extent[0], extent[1]))
    top = float(height.max())
    base = float(height.min())
    span = top - base

    d = g.dynamic
    if base > d.max_base_offset:               # floating: structure, not traffic
        return STATIC_OBSTACLE

    slab = g.terrain_slab
    if span <= slab.max_height and footprint >= slab.min_footprint:
        return NON_DRIVABLE_TERRAIN

    v = d.vehicle
    is_vehicle = (
        v.min_height <= top <= v.max_height
        and v.min_footprint <= footprint <= v.max_footprint
        and footprint >= v.min_aspect * top
    )
    p_ = d.person
    is_person = (
        p_.min_height <= top <= p_.max_height
        and footprint <= p_.max_footprint
    )
    return DYNAMIC_OBJECT if (is_vehicle or is_person) else STATIC_OBSTACLE


def segment(xyz: np.ndarray, intensity: np.ndarray, cfg) -> np.ndarray:
    """Classify every point into one of the five AVR-25D classes.  -> uint8[n].

    ``intensity`` is accepted for interface parity with the ONNX segmenter and
    is deliberately unused: a fallback that quietly depends on a calibrated
    intensity channel is a fallback that breaks on the first sensor swap.
    """
    xyz = np.asarray(xyz, dtype=np.float32).reshape(-1, 3)
    n = xyz.shape[0]
    labels = np.full(n, VOID, dtype=np.uint8)
    if n == 0:
        return labels

    g = _geometric_cfg(cfg)
    plane = fit_ground_plane(xyz, cfg)
    if plane is None:
        return labels                      # no ground found; everything stays VOID

    height = plane.signed_distance(xyz)
    xy_r = np.hypot(xyz[:, 0], xyz[:, 1])

    # 1. Ground inliers, at every range — DRIVABLE.
    ground = np.abs(height) <= g.ground_tol
    labels[ground] = DRIVABLE

    # 2. The skirt beyond the fit radius, and everything below the plane —
    #    NON_DRIVABLE_TERRAIN.  See the module docstring for both.
    skirt = (~ground) & (xy_r > g.fit_radius) & (np.abs(height) <= g.terrain_tol)
    labels[skirt] = NON_DRIVABLE_TERRAIN
    below = (~ground) & (height < -g.ground_tol)
    labels[below] = NON_DRIVABLE_TERRAIN

    # 3. What is left above the plane is a candidate obstacle.
    above = np.flatnonzero((~ground) & (~skirt) & (height > g.ground_tol))
    if above.size == 0:
        return labels

    # 4. Cluster, then gate each cluster by its bounding box.
    cluster_id = cluster(xyz[above], cfg)
    order = np.argsort(cluster_id, kind="stable")
    sorted_ids = cluster_id[order]
    boundaries = np.flatnonzero(np.diff(sorted_ids)) + 1
    for group in np.split(order, boundaries):
        members = above[group]
        labels[members] = _classify_cluster(xyz[members], height[members], g)

    return labels


class GeometricSegmenter:
    """Callable wrapper with the same surface as ``OnnxSegmenter`` (FR-6).

    Keeping the two interchangeable is what makes ``--infer geometric`` a flag
    rather than a code path, and it is what lets the benchmark harness time both
    with one loop.
    """

    mode = "geometric"

    def __init__(self, cfg):
        self.cfg = cfg
        self._last_latency_ms = 0.0

    def __call__(self, xyz: np.ndarray, intensity: np.ndarray) -> np.ndarray:
        t0 = time.perf_counter()
        out = segment(xyz, intensity, self.cfg)
        self._last_latency_ms = (time.perf_counter() - t0) * 1000.0
        return out

    @property
    def last_latency_ms(self) -> float:
        return self._last_latency_ms
