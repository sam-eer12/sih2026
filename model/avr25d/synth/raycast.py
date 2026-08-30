"""Spherical ray-caster against analytic primitives (PRD §9.3).

64 beams x 1800 azimuths are cast from the sensor origin against every
primitive in the scene; the nearest hit wins and carries that primitive's
class.  Gaussian range noise is added and returns beyond ``r_max`` are dropped,
so the synthetic clouds have the same density falloff a real sensor produces.

Coordinate frames
-----------------
Two frames are in play and mixing them up is the one mistake that silently
ruins every ground-truth number.

*Road frame* — what the scene CSVs are written in.  ``z = 0`` is the road
surface, ``x`` forward, ``y`` left, ``z`` up.  A pothole floor is at
``z = -0.22``; a gantry underside at ``z = +3.10``.  Authoring a scene in this
frame is what makes a CSV row readable: the numbers in it are the numbers in
the requirement.

*Sensor frame* — what gets written to ``.bin``, and what every downstream
module sees.  The sensor sits at the origin, so the road is at
``z = -sensor_height``.  This is KITTI's convention, and matching it is why the
synthetic scenes can travel through exactly the same reader, the same grid and
the same benchmark as real scans.

``raycast`` does the conversion on the way out.  Nothing else needs to know.

Primitive conventions
---------------------
``x, y, z`` is the **centre** of the primitive and ``sx, sy, sz`` are its
**full** extents, for every type.  So a 0.22 m deep pothole whose rim is flush
with the road is ``z = -0.11, sz = 0.22``, and a gantry beam 0.5 m deep with
3.10 m of clearance beneath it is ``z = 3.35, sz = 0.5``.

(The illustrative CSV in ``IMPLEMENTATION_PLAN.md`` §6.15 mixes conventions —
its pothole and gantry rows are written base-referenced while its cylinder row
is centre-referenced.  Centre-referenced throughout is the convention here,
because one rule that always holds beats two rules that depend on the row.)

Types
-----
``plane``
    Horizontal rectangle at ``z``, extent ``sx`` x ``sy``.  The road.
``box``
    Solid axis-aligned box.  Nearest outside surface.  Kerbs, gantry beams,
    vehicles, walls.
``cyl``
    Vertical cylinder, diameter ``sx``, height ``sz``, including end caps.
    Poles and gantry supports.
``pit``
    An **open-top** box carved out of whatever lies above it — the only way a
    depression can exist in a nearest-hit ray-caster.  Rays that enter the
    volume from above hit its inner floor or inner walls, and any other
    primitive's hit falling inside the carve volume is suppressed, which is
    what removes the road surface over the hole.  Potholes.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from avr25d.perception import labelmap

EPS = 1e-6

#: Per-class base reflectivity used to synthesise a plausible intensity
#: channel.  Nothing measures intensity, but leaving it zero would make the
#: synthetic scans distinguishable from real ones by a trivial check, and a
#: fallback segmenter that quietly relies on intensity would not show it.
_BASE_REFLECTANCE = {
    labelmap.VOID: 0.10,
    labelmap.DRIVABLE: 0.18,
    labelmap.NON_DRIVABLE_TERRAIN: 0.30,
    labelmap.STATIC_OBSTACLE: 0.45,
    labelmap.DYNAMIC_OBJECT: 0.55,
}


@dataclass(frozen=True)
class SensorSpec:
    """Sensor geometry.  Defaults match the HDL-64E that KITTI was recorded on."""

    n_beams: int = 64
    n_azimuth: int = 1800
    fov_up: float = 3.0        # deg
    fov_down: float = -25.0    # deg
    sensor_height: float = 1.70  # m above the road plane
    r_max: float = 100.0       # m — matches the grid envelope
    range_sigma: float = 0.02  # m — Gaussian range noise
    dropout: float = 0.0       # fraction of returns randomly dropped
    seed: int = 20260830

    def rays(self) -> np.ndarray:
        """Unit direction vectors, float64[n_beams * n_azimuth, 3], road frame."""
        elev = np.deg2rad(
            np.linspace(self.fov_up, self.fov_down, self.n_beams, dtype=np.float64)
        )
        azim = np.linspace(
            0.0, 2.0 * np.pi, self.n_azimuth, endpoint=False, dtype=np.float64
        )
        e = elev[:, None]
        a = azim[None, :]
        ce = np.cos(e)
        d = np.empty((self.n_beams, self.n_azimuth, 3), dtype=np.float64)
        d[..., 0] = ce * np.cos(a)
        d[..., 1] = ce * np.sin(a)
        d[..., 2] = np.sin(e) * np.ones_like(a)
        return d.reshape(-1, 3)

    @property
    def origin(self) -> np.ndarray:
        """Ray origin in the road frame."""
        return np.array([0.0, 0.0, self.sensor_height], dtype=np.float64)


@dataclass(frozen=True)
class Primitive:
    """One row of a scene CSV."""

    kind: str            # plane | box | cyl | pit
    x: float
    y: float
    z: float             # centre of the z extent
    sx: float
    sy: float
    sz: float            # full extents
    class_id: int        # AVR-25D class, PRD §6.1
    vx: float = 0.0      # m/s — scene-relative velocity, x
    vy: float = 0.0      # m/s
    hazard: str = ""     # ground-truth tag; see scenegen.ground_truth
    note: str = ""

    @property
    def lo(self) -> np.ndarray:
        return np.array(
            [self.x - self.sx / 2, self.y - self.sy / 2, self.z - self.sz / 2]
        )

    @property
    def hi(self) -> np.ndarray:
        return np.array(
            [self.x + self.sx / 2, self.y + self.sy / 2, self.z + self.sz / 2]
        )

    @property
    def is_moving(self) -> bool:
        return self.vx != 0.0 or self.vy != 0.0

    def at(self, t: float) -> "Primitive":
        """This primitive advanced ``t`` seconds along its velocity."""
        if not self.is_moving or t == 0.0:
            return self
        return replace(self, x=self.x + self.vx * t, y=self.y + self.vy * t)


@dataclass(frozen=True)
class Scene:
    """A named list of primitives, plus the ground truth derived from them."""

    name: str
    primitives: tuple[Primitive, ...]
    n_frames: int = 1
    ground_truth: dict = field(default_factory=dict)

    def at(self, t: float) -> "Scene":
        """The scene ``t`` seconds in."""
        if t == 0.0:
            return self
        return replace(self, primitives=tuple(p.at(t) for p in self.primitives))


# ---------------------------------------------------------------------------
# Ray-primitive intersection.  Each returns t along the ray (inf where no hit).
# ---------------------------------------------------------------------------

def _safe_div(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """Elementwise divide, mapping a zero denominator to +/-inf, not NaN."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = num / den
    return np.where(den == 0.0, np.where(num >= 0.0, np.inf, -np.inf), out)


def _points_at(o: np.ndarray, d: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Hit points for a set of rays and finite parameters.  float64[m, 3].

    Callers must filter to finite ``t`` first: ``inf * 0`` on a ray with a zero
    direction component is NaN, and a NaN silently passes every subsequent
    bounds comparison as False rather than raising.
    """
    return o[None, :] + t[:, None] * d


def _hit_plane(o: np.ndarray, d: np.ndarray, p: Primitive) -> np.ndarray:
    t = _safe_div(p.z - o[2], d[:, 2])
    out = np.full(t.shape, np.inf)
    cand = np.isfinite(t) & (t > EPS)
    if not np.any(cand):
        return out
    hit = _points_at(o, d[cand], t[cand])
    inside = (
        (np.abs(hit[:, 0] - p.x) <= p.sx / 2)
        & (np.abs(hit[:, 1] - p.y) <= p.sy / 2)
    )
    idx = np.flatnonzero(cand)[inside]
    out[idx] = t[idx]
    return out


def _slabs(o: np.ndarray, d: np.ndarray, p: Primitive) -> tuple[np.ndarray, np.ndarray]:
    """Slab-method entry/exit parameters for an AABB.  -> (t_near, t_far)."""
    t1 = _safe_div(p.lo[None, :] - o[None, :], d)
    t2 = _safe_div(p.hi[None, :] - o[None, :], d)
    t_near = np.max(np.minimum(t1, t2), axis=1)
    t_far = np.min(np.maximum(t1, t2), axis=1)
    return t_near, t_far


def _hit_box(o: np.ndarray, d: np.ndarray, p: Primitive) -> np.ndarray:
    """Nearest *outside* surface of a solid box."""
    t_near, t_far = _slabs(o, d, p)
    valid = t_far >= np.maximum(t_near, EPS)
    t = np.where(t_near > EPS, t_near, t_far)   # t_far when the origin is inside
    return np.where(valid & (t > EPS), t, np.inf)


def _hit_pit(o: np.ndarray, d: np.ndarray, p: Primitive) -> np.ndarray:
    """Nearest *inside* surface of an open-top box — the floor or an inner wall.

    The ray must enter the volume from outside (``t_far > t_near > 0``); the
    surface it lands on is at ``t_far``.
    """
    t_near, t_far = _slabs(o, d, p)
    valid = (t_far > np.maximum(t_near, EPS)) & np.isfinite(t_far)
    return np.where(valid, t_far, np.inf)


def _hit_cyl(o: np.ndarray, d: np.ndarray, p: Primitive) -> np.ndarray:
    """Nearest surface of a vertical cylinder, side wall or end cap.

    ``sx`` is the diameter; ``sy`` is ignored (it exists so every row has the
    same column count).
    """
    radius = p.sx / 2.0
    z_lo, z_hi = p.z - p.sz / 2, p.z + p.sz / 2

    ox, oy = o[0] - p.x, o[1] - p.y
    dx, dy = d[:, 0], d[:, 1]

    a = dx * dx + dy * dy
    b = 2.0 * (ox * dx + oy * dy)
    c = ox * ox + oy * oy - radius * radius
    disc = b * b - 4.0 * a * c

    t_side = np.full(d.shape[0], np.inf)
    ok = (disc >= 0.0) & (a > EPS)
    if np.any(ok):
        sq = np.sqrt(disc[ok])
        t0 = (-b[ok] - sq) / (2.0 * a[ok])
        t1 = (-b[ok] + sq) / (2.0 * a[ok])
        cand = np.where(t0 > EPS, t0, t1)
        z_at = o[2] + cand * d[ok, 2]
        cand = np.where((cand > EPS) & (z_at >= z_lo) & (z_at <= z_hi), cand, np.inf)
        t_side[ok] = cand

    t_cap = np.full(d.shape[0], np.inf)
    for z_cap in (z_lo, z_hi):
        t = _safe_div(z_cap - o[2], d[:, 2])
        px = o[0] + t * d[:, 0] - p.x
        py = o[1] + t * d[:, 1] - p.y
        inside = (px * px + py * py) <= radius * radius
        t_cap = np.minimum(
            t_cap, np.where((t > EPS) & inside & np.isfinite(t), t, np.inf)
        )

    return np.minimum(t_side, t_cap)


def instance_ids(primitives) -> np.ndarray:
    """Per-primitive KITTI instance id.  uint32[n_primitives].

    Instance 0 means "no instance", so objects are numbered from 1 in CSV
    order.  Ground planes keep 0 — a road surface is not an object, and giving
    it an instance would put a spurious entry in every object-recall count.

    Shared with ``scenegen.ground_truth`` so the id a test selects on is the
    same id the ray-caster wrote.
    """
    ids = np.zeros(len(primitives), dtype=np.uint32)
    counter = 0
    for i, p in enumerate(primitives):
        if p.kind == "plane":
            continue
        counter += 1
        ids[i] = counter
    return ids


_DISPATCH = {
    "plane": _hit_plane,
    "box": _hit_box,
    "cyl": _hit_cyl,
    "pit": _hit_pit,
}


# ---------------------------------------------------------------------------
# The cast
# ---------------------------------------------------------------------------

def raycast(
    scene: Scene,
    sensor: SensorSpec | None = None,
    t_scene: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Cast ``scene`` and return (xyzi float32[n, 4], labels uint32[n]).

    Points are in the **sensor frame** (sensor at the origin) and labels are
    packed SemanticKITTI ``.label`` words — ``instance << 16 | semantic``, with
    ``semantic`` a real SemanticKITTI raw id rather than an AVR class, so the
    output is byte-compatible with ``avr25d.io.kitti`` and with anything
    downstream that reads KITTI.

    ``t_scene`` advances moving primitives, in seconds.
    """
    sensor = sensor or SensorSpec()
    scene = scene.at(t_scene)
    prims = scene.primitives
    if not prims:
        return (
            np.zeros((0, 4), dtype=np.float32),
            np.zeros(0, dtype=np.uint32),
        )

    o = sensor.origin
    d = sensor.rays()
    n_rays = d.shape[0]

    t_all = np.empty((len(prims), n_rays), dtype=np.float64)
    for i, p in enumerate(prims):
        try:
            fn = _DISPATCH[p.kind]
        except KeyError:
            raise ValueError(
                f"unknown primitive type {p.kind!r} in scene {scene.name!r}; "
                f"expected one of {sorted(_DISPATCH)}"
            ) from None
        t_all[i] = fn(o, d, p)

    # A pit carves its volume out of every other primitive: without this the
    # road plane would simply cover the hole and the pothole would not exist.
    for i, pit in enumerate(prims):
        if pit.kind != "pit":
            continue
        lo, hi = pit.lo, pit.hi
        for j in range(len(prims)):
            if j == i:
                continue
            t_j = t_all[j]
            finite = np.flatnonzero(np.isfinite(t_j))
            if finite.size == 0:
                continue
            hit = _points_at(o, d[finite], t_j[finite])
            inside = (
                (hit[:, 0] >= lo[0] - EPS) & (hit[:, 0] <= hi[0] + EPS)
                & (hit[:, 1] >= lo[1] - EPS) & (hit[:, 1] <= hi[1] + EPS)
                & (hit[:, 2] >= lo[2] - EPS) & (hit[:, 2] <= hi[2] + EPS)
            )
            t_all[j, finite[inside]] = np.inf

    # Nearest hit wins.
    winner = np.argmin(t_all, axis=0)
    t_hit = t_all[winner, np.arange(n_rays)]
    got = np.isfinite(t_hit)
    if not np.any(got):
        return (
            np.zeros((0, 4), dtype=np.float32),
            np.zeros(0, dtype=np.uint32),
        )

    winner = winner[got]
    t_hit = t_hit[got]
    d_hit = d[got]

    rng = np.random.default_rng(
        sensor.seed ^ (int(round(t_scene * 1000)) & 0xFFFFFFFF)
    )
    if sensor.range_sigma > 0.0:
        t_hit = t_hit + rng.normal(0.0, sensor.range_sigma, size=t_hit.shape)

    keep = (t_hit > 0.0) & (t_hit <= sensor.r_max)
    if sensor.dropout > 0.0:
        keep &= rng.random(t_hit.shape) >= sensor.dropout

    winner = winner[keep]
    t_hit = t_hit[keep]
    d_hit = d_hit[keep]

    # Road frame -> sensor frame: the sensor sits at the origin, so the road
    # plane lands at z = -sensor_height, exactly as in KITTI.
    xyz = (t_hit[:, None] * d_hit).astype(np.float32)

    class_ids = np.array([p.class_id for p in prims], dtype=np.int64)
    moving = np.array([p.is_moving for p in prims], dtype=bool)
    instances = instance_ids(prims)

    hit_class = class_ids[winner]
    hit_moving = moving[winner]
    raw = np.array(
        [
            labelmap.AVR_TO_RAW_MOVING[c] if m else labelmap.AVR_TO_RAW[c]
            for c, m in zip(hit_class.tolist(), hit_moving.tolist())
        ],
        dtype=np.uint32,
    ) if hit_class.size else np.zeros(0, dtype=np.uint32)
    labels = (instances[winner] << np.uint32(16)) | raw

    reflectance = np.array(
        [_BASE_REFLECTANCE.get(int(c), 0.2) for c in class_ids], dtype=np.float64
    )[winner]
    # Inverse-square falloff with a soft floor, plus a little noise.  Incidence
    # angle is folded in through |cos| against the surface normal we do not
    # track, so it is approximated by the ray's own elevation.
    falloff = 1.0 / (1.0 + (t_hit / 40.0) ** 2)
    intensity = np.clip(
        reflectance * falloff + rng.normal(0.0, 0.01, size=t_hit.shape), 0.0, 1.0
    ).astype(np.float32)

    xyzi = np.empty((xyz.shape[0], 4), dtype=np.float32)
    xyzi[:, :3] = xyz
    xyzi[:, 3] = intensity
    return xyzi, labels
