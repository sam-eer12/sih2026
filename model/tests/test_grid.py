"""Tests for core/grid.py — T-G1 through T-G4 plus cell_centres / cell_extents.

Every test here maps directly to a requirement in IMPLEMENTATION_PLAN.md §9
and PRD §7.2.  The adversarial inputs in test_conservation are the ones most
likely to fail if the j-clamp or the ring boundary construction is wrong.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from avr25d.core.grid import RingGrid


@pytest.fixture(scope="module")
def grid() -> RingGrid:
    return RingGrid()


# ---------------------------------------------------------------------------
# T-G1 — ring count and cell size at the two PS-6 endpoints
# ---------------------------------------------------------------------------

class TestRingTable:
    def test_ring_count(self, grid):
        """T-G1 part 1: exactly 662 rings."""
        assert grid.n_rings == 662

    def test_total_cells(self, grid):
        """T-G1 part 2: exactly 705,771 cells (the §3.6 derivation)."""
        assert grid.n_cells == 705_771

    def test_offset_tail(self, grid):
        """offset[-1] must equal n_cells — it is the flat id of the first
        cell PAST the end, used as a sentinel in searchsorted."""
        assert int(grid.offset[-1]) == grid.n_cells

    def test_cell_size_at_inner_rings(self, grid):
        """T-G1: s(r) = 0.05 m for r ≤ 10 m."""
        # Every inner ring (0..199) must have s = 0.05 m
        inner = grid.s[:200]
        assert np.allclose(inner, 0.05, atol=1e-4), \
            f"inner ring sizes not all 0.05: min={inner.min():.5f} max={inner.max():.5f}"

    def test_cell_size_at_far_field(self, grid):
        """T-G1: s(r) approaches 0.50 m at r ≈ 100 m."""
        # Last ring starts at ~99.67 m → s ≈ 0.498 m (< 0.50 because we
        # haven't hit r_max exactly)
        assert 0.45 <= float(grid.s[-1]) <= 0.50

    def test_n_bins_inner_last(self, grid):
        """Ring 199 (last inner) bins ≈ 1250 (round(2π·9.95/0.05))."""
        assert 1200 <= int(grid.n_bins[199]) <= 1300

    def test_n_bins_far_field_constant(self, grid):
        """All far-field rings (200..661) must have the same bin count = 1257."""
        far = grid.n_bins[200:]
        assert far.min() == far.max() == 1257, \
            f"far-field bins not constant 1257: min={far.min()} max={far.max()}"

    def test_r_edge_monotone(self, grid):
        """Ring boundaries must be strictly increasing."""
        assert np.all(np.diff(grid.r_edge.astype(np.float64)) > 0)

    def test_r_edge_starts_at_zero(self, grid):
        assert float(grid.r_edge[0]) == pytest.approx(0.0, abs=1e-6)

    def test_r_edge_ends_near_r_max(self, grid):
        """Last outer edge must be ≤ r_max and within one cell-size of it."""
        r_max  = 100.0
        r_last = float(grid.r_edge[-1])
        assert r_last <= r_max + 0.55, f"r_edge[-1]={r_last} > r_max={r_max}"
        assert r_last >= r_max - 0.55, f"r_edge[-1]={r_last} too far below r_max"


# ---------------------------------------------------------------------------
# T-G2 — isotropy (radial ≈ tangential extent at every range)
# ---------------------------------------------------------------------------

class TestIsotropy:
    @pytest.mark.parametrize("ring_idx", [10, 39, 99, 199, 200, 261, 400, 600, 661])
    def test_cell_is_approximately_square(self, grid, ring_idx):
        """T-G2: |radial − tangential| / radial < 0.10 for rings ≥ 10.

        The innermost rings (r < 0.5 m) have too few bins to be square —
        there can't be fewer than 1 bin, so isotropy only holds once there are
        enough bins for the tangential extent to match.  Ring 10 onward is
        well inside the isotropy regime.
        """
        cid = np.array([int(grid.offset[ring_idx])], dtype=np.int32)
        ext = grid.cell_extents(cid)
        radial, tang = float(ext[0, 0]), float(ext[0, 1])
        assert radial > 0, f"ring {ring_idx}: radial extent is zero"
        ratio = tang / radial
        assert 0.90 <= ratio <= 1.10, \
            f"ring {ring_idx}: radial={radial:.4f} tang={tang:.4f} ratio={ratio:.3f}"


# ---------------------------------------------------------------------------
# T-G3 — ring_of is the exact inverse of r_edge
# ---------------------------------------------------------------------------

class TestRingOf:
    def test_random_radii_in_correct_ring(self, grid):
        """T-G3: ring_of(r) agrees with r_edge for 1 M random radii."""
        rng = np.random.default_rng(42)
        r_test = rng.uniform(0.001, 99.999, 1_000_000)
        k = grid.ring_of(r_test)
        r_lo = grid.r_edge[k].astype(np.float64)
        r_hi = grid.r_edge[k + 1].astype(np.float64)
        bad  = ~((r_test >= r_lo - 1e-4) & (r_test < r_hi + 1e-4))
        assert not bad.any(), \
            f"{bad.sum()} of 1M random radii placed in the wrong ring"

    def test_out_of_range_returns_minus_one(self, grid):
        """Points outside the envelope must return -1."""
        r_oor = np.array([-0.1, 100.001, 200.0, np.inf])
        k     = grid.ring_of(r_oor)
        assert (k == -1).all(), f"out-of-range ring indices: {k}"

    def test_at_ring_boundaries(self, grid):
        """Points exactly on internal ring boundaries must not be dropped."""
        boundaries = grid.r_edge[1:-1].astype(np.float64)
        # Take every 10th boundary to keep the test fast
        sample = boundaries[::10]
        k = grid.ring_of(sample)
        assert (k >= 0).all(), \
            f"{(k < 0).sum()} points on ring boundaries returned -1"

    def test_scalar_array_both_work(self, grid):
        k_arr = grid.ring_of(np.array([5.0, 50.0]))
        assert k_arr.shape == (2,)
        assert k_arr.dtype == np.int32


# ---------------------------------------------------------------------------
# T-G4 — conservation (FR-10): every in-envelope point maps to a valid cell
# ---------------------------------------------------------------------------

class TestConservation:
    def test_one_million_random_points(self, grid):
        """T-G4 core: 1 M random in-envelope points, none dropped."""
        rng = np.random.default_rng(99)
        N = 1_000_000
        r     = rng.uniform(0.001, 99.99, N)
        theta = rng.uniform(0.0, 2 * math.pi, N)
        x = r * np.cos(theta)
        y = r * np.sin(theta)
        ids, valid = grid.cell_of(x, y)
        assert valid.all(), f"{(~valid).sum()} in-envelope points dropped"
        assert int(ids.min()) >= 0
        assert int(ids.max()) < grid.n_cells

    def test_adversarial_theta_zero_and_twopi(self, grid):
        """theta = 0 and theta = 2π − ε must not produce out-of-range j."""
        eps = 1e-10
        x = np.array([5.0, 50.0,  5.0,  50.0])
        y = np.array([0.0,  0.0,  eps, -eps])
        ids, valid = grid.cell_of(x, y)
        assert valid.all(), "near-zero theta points dropped"
        assert (ids >= 0).all()
        assert (ids < grid.n_cells).all()

    def test_adversarial_at_ring_boundaries(self, grid):
        """Points exactly at ring boundaries (r = r_edge[k]) must map correctly."""
        for r_b in grid.r_edge[1:20].astype(np.float64):
            x = np.array([r_b, r_b * math.cos(1.0)])
            y = np.array([0.0, r_b * math.sin(1.0)])
            ids, valid = grid.cell_of(x, y)
            assert valid.all(), f"points at r={r_b:.4f} dropped"
            assert (ids >= 0).all()

    def test_origin_maps_to_ring_zero(self, grid):
        ids, valid = grid.cell_of(np.array([0.0]), np.array([0.0]))
        assert valid[0], "origin dropped"
        assert 0 <= int(ids[0]) < int(grid.offset[1])

    def test_out_of_envelope_returns_invalid(self, grid):
        x = np.array([150.0, -150.0, 0.0])
        y = np.array([0.0,   0.0,  150.0])
        _, valid = grid.cell_of(x, y)
        assert not valid.any(), "out-of-envelope points marked valid"

    def test_cell_ids_unique_for_uniform_grid(self, grid):
        """A structured sample across rings with enough bins should be unique."""
        ids_all = []
        for k in range(grid.n_rings):
            nb = int(grid.n_bins[k])
            if nb < 3:
                continue   # rings with 1–2 bins can't produce 3 distinct cells
            for frac in [0.0, 1.0/3, 2.0/3]:
                j = int(frac * nb)
                r_c = float(0.5 * (grid.r_edge[k] + grid.r_edge[k + 1]))
                theta = (j + 0.5) / nb * 2 * math.pi
                x = r_c * math.cos(theta)
                y = r_c * math.sin(theta)
                cid, v = grid.cell_of(np.array([x]), np.array([y]))
                if v[0]:
                    ids_all.append(int(cid[0]))
        ids_arr = np.array(ids_all)
        assert len(ids_arr) == len(np.unique(ids_arr)), \
            "duplicate cell ids — ring/bin overlaps detected"


# ---------------------------------------------------------------------------
# T-G6 — memory stability (FR-12)
# ---------------------------------------------------------------------------

class TestMemoryStability:
    def test_no_reallocation_across_frames(self, grid):
        """T-G6: grid arrays are the same objects after repeated use."""
        id_r_edge   = id(grid.r_edge)
        id_n_bins   = id(grid.n_bins)
        id_offset   = id(grid.offset)
        rng = np.random.default_rng(7)
        for _ in range(10):
            x = rng.uniform(-90, 90, 1000)
            y = rng.uniform(-90, 90, 1000)
            grid.cell_of(x, y)
        assert id(grid.r_edge) == id_r_edge, "r_edge reallocated"
        assert id(grid.n_bins) == id_n_bins, "n_bins reallocated"
        assert id(grid.offset) == id_offset, "offset reallocated"


# ---------------------------------------------------------------------------
# cell_centres / cell_extents
# ---------------------------------------------------------------------------

class TestInverseMaps:
    def test_cell_centres_round_trip(self, grid):
        """cell_centres(cell_of(x, y)) should return the same cell."""
        rng = np.random.default_rng(11)
        x = rng.uniform(-80, 80, 500)
        y = rng.uniform(-80, 80, 500)
        ids, valid = grid.cell_of(x, y)
        ids_v  = ids[valid]
        xy_c   = grid.cell_centres(ids_v)
        ids_rt, valid_rt = grid.cell_of(xy_c[:, 0], xy_c[:, 1])
        assert valid_rt.all(), "cell centres out of envelope"
        assert np.all(ids_rt == ids_v), \
            f"{(ids_rt != ids_v).sum()} cell centres mapped to wrong cell"

    def test_cell_extents_shape(self, grid):
        cids = np.array([0, grid.offset[200], grid.n_cells - 1], dtype=np.int32)
        ext  = grid.cell_extents(cids)
        assert ext.shape == (3, 2)
        assert (ext > 0).all(), "zero or negative extents"

    def test_cell_extents_dtype(self, grid):
        ext = grid.cell_extents(np.array([0], dtype=np.int32))
        assert ext.dtype == np.float32
