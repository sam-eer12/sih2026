"""Spherical range-image projection, and the way back (FR-2, FR-4).

A 64-beam LiDAR scan is a 2D image in disguise: one row per beam, one column
per azimuth sample.  Projecting into that image is what lets an ordinary 2D CNN
segment a point cloud on a CPU, with no sparse-convolution extension and no
CUDA — which is the whole reason FR-3 is achievable at all.

Forward: ``to_range_image``
--------------------------
Each point gets a pixel from its spherical angles::

    r     = |xyz|
    yaw   = -atan2(y, x)
    pitch = arcsin(z / r)
    u     = 0.5 * (yaw / pi + 1)                       -> [0, 1)
    v     = 1 - (pitch - fov_down) / (fov_up - fov_down)

Six channels, in the order FR-2 fixes: ``range, x, y, z, intensity, mask``.

Points are scattered farthest-first, so where several land on one pixel the
nearest one wins.  That is the correct choice — the near surface is what
occludes — but it is also exactly why the way back needs care.

Backward: ``from_range_image``
------------------------------
Around 10–15% of points lose that depth test and share a pixel with something
closer.  Handing every point the label of whichever point won is what shreds
object boundaries: the far side of a car adopts the label of the wall behind
it, one pixel at a time, all the way around the silhouette.

So labels come back through **range-aware k-NN voting** (the RangeNet++ post-
processing, and not optional).  For each point, look at the S x S pixel
neighbourhood around its own pixel, rank those pixels by how close their
*range* is to the point's own range, keep the ``k`` closest, and let them vote
with a Gaussian weight on that range difference.  A point behind a wall is
range-distant from the wall's pixels and range-near to the few pixels its own
surface did win, so it votes with its own surface rather than the occluder.

Every point gets a label, including occluded ones — FR-4, asserted by T-P4.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: SemanticKITTI channel statistics for ``range, x, y, z, intensity``, used to
#: normalise the network input.  These are the values the pretrained
#: range-image checkpoints were trained with (lidar-bonnetal ``data_cfg.yaml``);
#: changing them silently shifts the input distribution away from what the
#: weights expect, which shows up as a plausible-looking but wrong segmentation.
KITTI_MEAN = np.array([12.12, 10.88, 0.23, -1.04, 0.21], dtype=np.float32)
KITTI_STD = np.array([12.32, 11.47, 6.91, 0.86, 0.16], dtype=np.float32)

CH_RANGE, CH_X, CH_Y, CH_Z, CH_INTENSITY, CH_MASK = range(6)


@dataclass(frozen=True)
class RangeProjection:
    """A scan and its range image, with the index arrays that link them."""

    image: np.ndarray        # float32[6, h, w] — range, x, y, z, intensity, mask
    px: np.ndarray           # int32[n] — column each point projected to
    py: np.ndarray           # int32[n] — row each point projected to
    point_range: np.ndarray  # float32[n] — |xyz| per point, pre-projection

    @property
    def h(self) -> int:
        return int(self.image.shape[1])

    @property
    def w(self) -> int:
        return int(self.image.shape[2])

    @property
    def n_points(self) -> int:
        return int(self.px.shape[0])

    @property
    def proj_range(self) -> np.ndarray:
        """The range channel, float32[h, w].  ``-1`` where no point landed."""
        return self.image[CH_RANGE]

    @property
    def occupancy(self) -> float:
        """Fraction of pixels that received a point.  A diagnostic, not a metric."""
        return float(self.image[CH_MASK].mean())

    def normalised(
        self,
        mean: np.ndarray = KITTI_MEAN,
        std: np.ndarray = KITTI_STD,
    ) -> np.ndarray:
        """Network input: float32[1, 5, h, w], normalised and masked.

        The mask channel is dropped — it is redundant once empty pixels are
        zeroed, and the pretrained checkpoints take five channels.
        """
        x = (self.image[:5] - mean[:, None, None]) / std[:, None, None]
        return (x * self.image[CH_MASK][None]).astype(np.float32)[None]


def to_range_image(
    xyz: np.ndarray,
    intensity: np.ndarray,
    h: int = 64,
    w: int = 2048,
    fov_up: float = 3.0,
    fov_down: float = -25.0,
) -> RangeProjection:
    """Project a scan into a spherical range image.  FR-2.

    ``fov_up`` and ``fov_down`` are degrees and default to the HDL-64E's, which
    is what KITTI was recorded with.  Points outside the vertical field of view
    are clamped to the edge row rather than dropped: dropping them would break
    FR-4's promise that every point gets a label, and the clamp costs one row of
    accuracy at the extremes where there is nothing to see anyway.
    """
    xyz = np.asarray(xyz, dtype=np.float32).reshape(-1, 3)
    intensity = np.asarray(intensity, dtype=np.float32).reshape(-1)
    n = xyz.shape[0]
    if intensity.shape[0] != n:
        raise ValueError(f"{n} points but {intensity.shape[0]} intensities")

    image = np.zeros((6, h, w), dtype=np.float32)
    image[CH_RANGE] = -1.0
    if n == 0:
        return RangeProjection(
            image=image,
            px=np.zeros(0, np.int32),
            py=np.zeros(0, np.int32),
            point_range=np.zeros(0, np.float32),
        )

    point_range = np.linalg.norm(xyz, axis=1).astype(np.float32)
    safe = np.maximum(point_range, 1e-6)          # a point at the origin has no angle

    yaw = -np.arctan2(xyz[:, 1], xyz[:, 0])
    pitch = np.arcsin(np.clip(xyz[:, 2] / safe, -1.0, 1.0))

    fov_up_r = np.deg2rad(fov_up)
    fov_down_r = np.deg2rad(fov_down)
    fov = fov_up_r - fov_down_r

    u = 0.5 * (yaw / np.pi + 1.0)
    v = 1.0 - (pitch - fov_down_r) / fov

    px = np.floor(u * w).astype(np.int32)
    py = np.floor(v * h).astype(np.int32)
    np.clip(px, 0, w - 1, out=px)
    np.clip(py, 0, h - 1, out=py)

    # Farthest first, so the nearest point wins each contested pixel.
    order = np.argsort(-point_range, kind="stable")
    oy, ox = py[order], px[order]
    image[CH_RANGE, oy, ox] = point_range[order]
    image[CH_X, oy, ox] = xyz[order, 0]
    image[CH_Y, oy, ox] = xyz[order, 1]
    image[CH_Z, oy, ox] = xyz[order, 2]
    image[CH_INTENSITY, oy, ox] = intensity[order]
    image[CH_MASK, oy, ox] = 1.0

    return RangeProjection(image=image, px=px, py=py, point_range=point_range)


def from_range_image(
    pred_hw: np.ndarray,
    px: np.ndarray,
    py: np.ndarray,
    xyz: np.ndarray,
    k: int = 5,
    proj_range: np.ndarray | None = None,
    search: int = 5,
    cutoff: float = 1.0,
    sigma: float = 1.0,
    n_classes: int = 5,
) -> np.ndarray:
    """Per-pixel labels -> per-point labels, by range-aware k-NN voting.  FR-4.

    ``pred_hw``
        ``[h, w]`` class ids from the network.
    ``px``, ``py``, ``xyz``
        As returned by :func:`to_range_image`, for the same scan.
    ``k``
        Neighbours that get to vote.
    ``proj_range``
        The projected range image.  Optional: it is reconstructed from
        ``px``, ``py`` and ``xyz`` when absent, since a pixel's range is by
        definition the smallest range among the points that landed on it.
        Passing it in skips that scatter.
    ``search``
        Side of the square pixel neighbourhood.  5 is the RangeNet++ default.
    ``cutoff``
        Metres.  A neighbour whose range differs by more than this never votes —
        it is a different surface, and letting it vote is the boundary-shredding
        this function exists to prevent.
    ``sigma``
        Metres.  Gaussian vote weight on the range difference.

    Returns ``uint8[n]``: one label per input point, occluded ones included.
    """
    pred_hw = np.asarray(pred_hw)
    px = np.asarray(px, dtype=np.int64)
    py = np.asarray(py, dtype=np.int64)
    xyz = np.asarray(xyz, dtype=np.float32).reshape(-1, 3)
    n = xyz.shape[0]
    if n == 0:
        return np.zeros(0, dtype=np.uint8)
    if px.shape[0] != n or py.shape[0] != n:
        raise ValueError(
            f"{n} points but {px.shape[0]} px / {py.shape[0]} py indices"
        )

    h, w = pred_hw.shape
    point_range = np.linalg.norm(xyz, axis=1).astype(np.float32)

    if proj_range is None:
        proj_range = np.full((h, w), np.inf, dtype=np.float32)
        np.minimum.at(proj_range, (py, px), point_range)
        proj_range[~np.isfinite(proj_range)] = -1.0
    proj_range = np.asarray(proj_range, dtype=np.float32)

    # A single-pixel neighbourhood is just "take the winning label", which is
    # the failure mode described in the module docstring — but it is a legal
    # configuration and it is what the ablation compares against.
    if search <= 1 or k <= 0:
        return pred_hw[py, px].astype(np.uint8)

    pad = search // 2
    # Pad range with +inf and labels with 0: an out-of-image neighbour is
    # infinitely range-distant, so it is rejected by the cutoff and never votes.
    padded_range = np.pad(
        proj_range, pad, mode="constant", constant_values=np.inf
    )
    padded_pred = np.pad(pred_hw, pad, mode="constant", constant_values=0)
    # Empty pixels carry range -1; that is *nearer* than any real point and
    # would win every vote. Push them out of contention.
    padded_range[padded_range < 0] = np.inf

    windows_range = np.lib.stride_tricks.sliding_window_view(
        padded_range, (search, search)
    )                                             # [h, w, search, search]
    windows_pred = np.lib.stride_tricks.sliding_window_view(
        padded_pred, (search, search)
    )

    patch_range = windows_range[py, px].reshape(n, -1)     # [n, search*search]
    patch_pred = windows_pred[py, px].reshape(n, -1)

    delta = np.abs(patch_range - point_range[:, None])
    k_eff = min(k, delta.shape[1])
    nearest = np.argpartition(delta, k_eff - 1, axis=1)[:, :k_eff]

    rows = np.arange(n)[:, None]
    d = delta[rows, nearest]
    labels = patch_pred[rows, nearest].astype(np.int64)

    valid = np.isfinite(d) & (d <= cutoff)
    weight = np.where(valid, np.exp(-(d**2) / (2.0 * sigma**2)), 0.0)

    votes = np.zeros((n, n_classes), dtype=np.float32)
    np.add.at(votes, (rows, np.clip(labels, 0, n_classes - 1)), weight)

    out = votes.argmax(axis=1).astype(np.uint8)
    # A point whose whole neighbourhood was rejected still needs a label:
    # fall back to its own pixel.  FR-4 says *every* point, not most of them.
    orphan = ~valid.any(axis=1)
    if np.any(orphan):
        out[orphan] = pred_hw[py[orphan], px[orphan]].astype(np.uint8)
    return out
