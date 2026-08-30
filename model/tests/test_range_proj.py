"""Range-image projection and the way back.  FR-2, FR-4 — tests T-P2, T-P4."""

from __future__ import annotations

import numpy as np
import pytest

from avr25d.perception.range_proj import (
    CH_INTENSITY,
    CH_MASK,
    CH_RANGE,
    CH_X,
    CH_Y,
    CH_Z,
    KITTI_MEAN,
    KITTI_STD,
    from_range_image,
    to_range_image,
)

H, W = 64, 2048


def _spherical(rows, cols, ranges, h=H, w=W, fov_up=3.0, fov_down=-25.0):
    """Points that land on given pixel centres, at given ranges.

    The inverse of the projection, so a test can name a pixel and get a point
    that provably projects back onto it.
    """
    rows = np.asarray(rows, dtype=np.float64)
    cols = np.asarray(cols, dtype=np.float64)
    ranges = np.asarray(ranges, dtype=np.float64)

    fov_up_r, fov_down_r = np.deg2rad(fov_up), np.deg2rad(fov_down)
    v = (rows + 0.5) / h
    u = (cols + 0.5) / w
    pitch = (1.0 - v) * (fov_up_r - fov_down_r) + fov_down_r
    yaw = (2.0 * u - 1.0) * np.pi

    z = ranges * np.sin(pitch)
    rho = ranges * np.cos(pitch)
    x = rho * np.cos(-yaw)
    y = rho * np.sin(-yaw)
    return np.stack([x, y, z], axis=1).astype(np.float32)


# --------------------------------------------------------------------------
# Forward projection
# --------------------------------------------------------------------------


def test_image_has_six_channels_and_requested_shape():
    xyz = _spherical([32], [1024], [10.0])
    proj = to_range_image(xyz, np.ones(1, np.float32))
    assert proj.image.shape == (6, H, W)
    assert proj.image.dtype == np.float32
    assert (proj.h, proj.w) == (H, W)


def test_channels_carry_range_xyz_intensity_and_mask_in_that_order():
    xyz = _spherical([20], [700], [17.5])
    proj = to_range_image(xyz, np.array([0.42], np.float32))
    py, px = int(proj.py[0]), int(proj.px[0])
    pixel = proj.image[:, py, px]

    assert pixel[CH_RANGE] == pytest.approx(17.5, abs=1e-3)
    assert pixel[CH_X] == pytest.approx(xyz[0, 0], abs=1e-3)
    assert pixel[CH_Y] == pytest.approx(xyz[0, 1], abs=1e-3)
    assert pixel[CH_Z] == pytest.approx(xyz[0, 2], abs=1e-3)
    assert pixel[CH_INTENSITY] == pytest.approx(0.42, abs=1e-6)
    assert pixel[CH_MASK] == 1.0


def test_a_point_straight_ahead_lands_in_the_centre_column():
    # +x is dead ahead; yaw = 0 puts it at u = 0.5.
    xyz = np.array([[25.0, 0.0, 0.0]], np.float32)
    proj = to_range_image(xyz, np.ones(1, np.float32))
    assert int(proj.px[0]) == W // 2


def test_pixels_addressed_by_px_py_hold_that_point_or_a_nearer_one():
    rows = np.repeat(np.arange(8, 56), 7)
    cols = np.tile(np.linspace(10, W - 10, 7).astype(int), 48)
    ranges = np.linspace(3.0, 60.0, rows.size)
    xyz = _spherical(rows, cols, ranges)
    proj = to_range_image(xyz, np.ones(rows.size, np.float32))

    np.testing.assert_array_equal(proj.py, rows)
    np.testing.assert_array_equal(proj.px, cols)
    assert np.allclose(proj.proj_range[proj.py, proj.px], ranges, atol=1e-2)


def test_the_nearest_point_wins_a_contested_pixel():
    xyz = _spherical([30, 30, 30], [512, 512, 512], [40.0, 8.0, 22.0])
    proj = to_range_image(xyz, np.array([0.1, 0.2, 0.3], np.float32))
    assert len(set(zip(proj.py.tolist(), proj.px.tolist()))) == 1
    assert proj.proj_range[30, 512] == pytest.approx(8.0, abs=1e-3)
    assert proj.image[CH_INTENSITY, 30, 512] == pytest.approx(0.2, abs=1e-6)


def test_untouched_pixels_are_marked_empty_not_zero_range():
    xyz = _spherical([30], [512], [12.0])
    proj = to_range_image(xyz, np.ones(1, np.float32))
    empty = proj.image[CH_MASK] == 0.0
    assert empty.sum() == H * W - 1
    assert np.all(proj.proj_range[empty] == -1.0)
    assert proj.occupancy == pytest.approx(1.0 / (H * W))


def test_points_outside_the_vertical_fov_are_clamped_not_dropped():
    # Straight up and straight down: far outside [-25, +3] degrees.
    xyz = np.array([[0.1, 0.0, 9.0], [0.1, 0.0, -9.0]], np.float32)
    proj = to_range_image(xyz, np.ones(2, np.float32))
    assert proj.n_points == 2
    assert int(proj.py[0]) == 0
    assert int(proj.py[1]) == H - 1
    assert np.all(proj.image[CH_MASK][[0, H - 1], proj.px] == 1.0)


def test_an_empty_scan_projects_to_an_empty_image():
    proj = to_range_image(np.zeros((0, 3), np.float32), np.zeros(0, np.float32))
    assert proj.n_points == 0
    assert proj.image.shape == (6, H, W)
    assert np.all(proj.proj_range == -1.0)


def test_intensity_length_must_match_the_point_count():
    with pytest.raises(ValueError, match="3 points but 2 intensities"):
        to_range_image(np.zeros((3, 3), np.float32), np.zeros(2, np.float32))


def test_normalised_input_is_five_channels_and_zero_where_unobserved():
    xyz = _spherical([30], [512], [12.0])
    proj = to_range_image(xyz, np.array([0.5], np.float32))
    net_in = proj.normalised()

    assert net_in.shape == (1, 5, H, W)
    assert net_in.dtype == np.float32

    occupied = np.zeros((H, W), bool)
    occupied[30, 512] = True
    assert np.all(net_in[0][:, ~occupied] == 0.0)

    expected = (proj.image[:5, 30, 512] - KITTI_MEAN) / KITTI_STD
    np.testing.assert_allclose(net_in[0, :, 30, 512], expected, rtol=1e-5)


# --------------------------------------------------------------------------
# T-P2 — projection then reprojection round-trips the index
# --------------------------------------------------------------------------


def test_TP2_index_round_trip_recovers_every_uncontested_point():
    """Point -> pixel -> point recovers the label for every point that owns its
    pixel, and for at least 99% of points overall on a smooth label field."""
    rng = np.random.default_rng(20260830)
    n = 60_000
    rows = rng.integers(0, H, n)
    cols = rng.integers(0, W, n)
    ranges = rng.uniform(3.0, 70.0, n)
    xyz = _spherical(rows, cols, ranges)
    proj = to_range_image(xyz, rng.random(n).astype(np.float32))

    np.testing.assert_array_equal(proj.py, rows)
    np.testing.assert_array_equal(proj.px, cols)

    # A label field that varies only with azimuth: smooth, as segmentation is.
    pred = (np.arange(W)[None, :] // 512 % 5) * np.ones((H, 1), np.int64)
    truth = pred[rows, cols].astype(np.uint8)

    got = from_range_image(pred, proj.px, proj.py, xyz)
    assert got.shape == (n,)
    agree = float((got == truth).mean())
    assert agree >= 0.99, f"round-trip agreement {agree:.4f}"


# --------------------------------------------------------------------------
# T-P4 — every point gets a label, occluded points get their own surface's
# --------------------------------------------------------------------------


def _occlusion_scene():
    """A far wall with a narrow near post in front of it.

    The post is 3 columns wide — narrower than the 5x5 search window — so every
    far point it hides can still see unoccluded wall pixels.
    """
    rows = np.arange(16, 48)
    cols = np.arange(500, 540)
    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    wall = _spherical(rr.ravel(), cc.ravel(), np.full(rr.size, 30.0))

    prows, pcols = np.meshgrid(rows, np.arange(519, 522), indexing="ij")
    post = _spherical(prows.ravel(), pcols.ravel(), np.full(prows.size, 10.0))

    xyz = np.concatenate([wall, post])
    truth = np.concatenate(
        [np.full(len(wall), 3, np.uint8), np.full(len(post), 1, np.uint8)]
    )
    hidden = np.zeros(len(xyz), bool)
    hidden[: len(wall)] = np.isin(cc.ravel(), [519, 520, 521])
    return xyz, truth, hidden


def test_TP4_every_point_receives_a_label_including_occluded_ones():
    xyz, truth, hidden = _occlusion_scene()
    assert hidden.sum() > 0, "the fixture must actually occlude something"

    proj = to_range_image(xyz, np.ones(len(xyz), np.float32))
    # The network only ever sees the winning surface at each pixel: scatter
    # farthest-first so the nearest label survives, as the projection does.
    order = np.argsort(-proj.point_range, kind="stable")
    pred = np.zeros((H, W), np.int64)
    pred[proj.py[order], proj.px[order]] = truth[order]

    labels = from_range_image(pred, proj.px, proj.py, xyz)

    assert labels.shape == (len(xyz),)
    assert labels.dtype == np.uint8
    assert np.all(np.isin(labels, [0, 1, 2, 3, 4]))
    # FR-4: 100% of points, not most of them.
    assert np.all(labels != 0), "every point must get a real class"


def test_TP4_occluded_points_keep_their_own_surface_not_the_occluders():
    xyz, truth, hidden = _occlusion_scene()
    proj = to_range_image(xyz, np.ones(len(xyz), np.float32))
    order = np.argsort(-proj.point_range, kind="stable")
    pred = np.zeros((H, W), np.int64)
    pred[proj.py[order], proj.px[order]] = truth[order]

    # Without range-awareness the hidden wall points read the post's label.
    naive = from_range_image(pred, proj.px, proj.py, xyz, search=1)
    assert np.all(naive[hidden] == 1)

    labels = from_range_image(pred, proj.px, proj.py, xyz)
    assert np.all(labels[hidden] == 3), (
        f"{(labels[hidden] != 3).sum()}/{hidden.sum()} occluded points took the "
        "occluder's label"
    )
    assert np.all(labels[truth == 1] == 1), "the post itself must stay the post"


def test_a_neighbour_nearer_than_the_cutoff_is_the_only_one_that_votes():
    """A lone pole pixel in front of a wall keeps its own label.

    Its 5x5 window is 24 wall pixels against itself, so a plain majority would
    erase it.  The cutoff is what saves it: the wall is 1.5 m behind, past the
    1 m gate, so none of those 24 pixels is allowed to vote.  Widen the gate
    past the gap and the wall does erase it — which is the failure the cutoff
    exists to prevent, and the reason thin structures survive at all.
    """
    rows = np.arange(20, 41)
    cols = np.arange(600, 641)
    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    wall = _spherical(rr.ravel(), cc.ravel(), np.full(rr.size, 11.5))
    pole = _spherical([30], [620], [10.0])

    xyz = np.concatenate([wall, pole])
    truth = np.concatenate([np.full(len(wall), 3, np.uint8), np.array([1], np.uint8)])

    proj = to_range_image(xyz, np.ones(len(xyz), np.float32))
    order = np.argsort(-proj.point_range, kind="stable")
    pred = np.zeros((H, W), np.int64)
    pred[proj.py[order], proj.px[order]] = truth[order]
    assert pred[30, 620] == 1, "the pole must win its own pixel"

    kept = from_range_image(pred, proj.px, proj.py, xyz)
    assert kept[-1] == 1

    erased = from_range_image(pred, proj.px, proj.py, xyz, cutoff=2.0)
    assert erased[-1] == 3


def test_reprojecting_an_empty_scan_returns_no_labels():
    out = from_range_image(
        np.zeros((H, W), np.int64),
        np.zeros(0, np.int32),
        np.zeros(0, np.int32),
        np.zeros((0, 3), np.float32),
    )
    assert out.shape == (0,)
    assert out.dtype == np.uint8


def test_reprojection_index_length_must_match_the_point_count():
    with pytest.raises(ValueError, match="3 points but 2 px"):
        from_range_image(
            np.zeros((H, W), np.int64),
            np.zeros(2, np.int32),
            np.zeros(3, np.int32),
            np.zeros((3, 3), np.float32),
        )


def test_unobserved_pixels_never_vote():
    """A lone return in an empty stretch of the image keeps its class.

    Empty pixels carry range -1, which is *nearer* than any real point, and
    they carry class 0.  Left in the running they outnumber the one real pixel
    and vote the point to VOID.  The far field of a real scan is mostly empty,
    so this is where sparse long-range returns would quietly disappear.
    """
    xyz = _spherical([30], [620], [5.0])
    proj = to_range_image(xyz, np.ones(1, np.float32))
    pred = np.zeros((H, W), np.int64)
    pred[30, 620] = 3

    # Wide enough that -1 would clear the gate if it were allowed through:
    # |(-1) - 5| = 6 m.
    labels = from_range_image(pred, proj.px, proj.py, xyz,
                              cutoff=8.0, sigma=4.0)
    assert labels[0] == 3
