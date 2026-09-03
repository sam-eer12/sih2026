"""Tests for core/refine.py — T-R1 and T-R2.

T-R1  A far-field MOVING cell is subdivided; quadrant values are 0–3;
      the REFINED flag is set on the parent; wire conversion works.

T-R2  Adversarial: every far-field occupied cell qualifies.
      Refinement must still produce ≤ max_cells parents and finish
      within the latency budget (FR-18).
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from avr25d import load_config
from avr25d.core.cell import CellGrid, FLAG_MOVING, FLAG_REFINED
from avr25d.core.grid import RingGrid
from avr25d.core.refine import RefinedOverlay, refine
from avr25d.perception import labelmap
from avr25d.synth import SensorSpec, load_scene
from avr25d.synth.raycast import raycast


# ---------------------------------------------------------------------------
# Module-scope fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def grid() -> RingGrid:
    return RingGrid()


@pytest.fixture(scope="module")
def cells(grid) -> CellGrid:
    return CellGrid(grid)


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def sensor():
    return SensorSpec()


def _populate(cells, grid, sensor, cfg, scene_name: str):
    scene = load_scene(scene_name)
    xyzi, packed = raycast(scene, sensor)
    sem, _ = labelmap.split_label(packed)
    avr    = labelmap.raw_to_avr(sem)
    moving = labelmap.raw_is_moving(sem)
    cells.reset()
    cells.accumulate(xyzi[:, :3], xyzi[:, 3], avr, moving)
    cells.analyse(cfg)


# ---------------------------------------------------------------------------
# T-R1 — basic refinement: MOVING cell in S5 gets subdivided
# ---------------------------------------------------------------------------

class TestBasicRefinement:

    def test_refine_returns_overlay_or_none(self, cells, grid, sensor, cfg):
        """refine() must return RefinedOverlay or None — never raises."""
        _populate(cells, grid, sensor, cfg, "S5_crossing_truck")
        result = refine(cells, grid, cfg)
        assert result is None or isinstance(result, RefinedOverlay)

    def test_quadrants_are_0_to_3(self, cells, grid, sensor, cfg):
        """T-R1: every quadrant value must be in {0, 1, 2, 3}."""
        _populate(cells, grid, sensor, cfg, "S5_crossing_truck")
        result = refine(cells, grid, cfg)
        if result is None or result.n == 0:
            pytest.skip("no refinement candidates in this scene")
        assert set(result.quadrant.tolist()).issubset({0, 1, 2, 3}), (
            f"unexpected quadrant values: {np.unique(result.quadrant)}"
        )

    def test_sub_cells_are_multiples_of_four(self, cells, grid, sensor, cfg):
        """T-R1: each parent produces exactly 4 sub-cells."""
        _populate(cells, grid, sensor, cfg, "S5_crossing_truck")
        result = refine(cells, grid, cfg)
        if result is None or result.n == 0:
            pytest.skip("no refinement candidates")
        assert result.n % 4 == 0, f"n={result.n} is not a multiple of 4"

    def test_each_parent_has_all_four_quadrants(self, cells, grid, sensor, cfg):
        """T-R1: every parent_id must appear exactly 4 times (one per quadrant)."""
        _populate(cells, grid, sensor, cfg, "S5_crossing_truck")
        result = refine(cells, grid, cfg)
        if result is None or result.n == 0:
            pytest.skip("no refinement candidates")
        unique, counts = np.unique(result.parent_id, return_counts=True)
        bad = unique[counts != 4]
        assert len(bad) == 0, (
            f"{len(bad)} parent cells do not have exactly 4 sub-cells"
        )

    def test_refined_flag_set_on_parents(self, cells, grid, sensor, cfg):
        """T-R1: every refined parent must carry the REFINED flag."""
        _populate(cells, grid, sensor, cfg, "S5_crossing_truck")
        result = refine(cells, grid, cfg)
        if result is None or result.n == 0:
            pytest.skip("no refinement candidates")
        parents = np.unique(result.parent_id)
        parent_flags = cells.flags[parents]
        not_refined = ~(parent_flags & FLAG_REFINED).astype(bool)
        assert not not_refined.any(), (
            f"{not_refined.sum()} refined parents missing REFINED flag"
        )

    def test_parent_ids_are_valid_cell_ids(self, cells, grid, sensor, cfg):
        """T-R1: all parent_id values must be valid flat cell ids."""
        _populate(cells, grid, sensor, cfg, "S5_crossing_truck")
        result = refine(cells, grid, cfg)
        if result is None or result.n == 0:
            pytest.skip("no refinement candidates")
        assert int(result.parent_id.min()) >= 0
        assert int(result.parent_id.max()) < grid.n_cells

    def test_parent_cells_are_far_field(self, cells, grid, sensor, cfg):
        """T-R1: refinement only applies to far-field cells (ring >= n_inner=200)."""
        _populate(cells, grid, sensor, cfg, "S5_crossing_truck")
        result = refine(cells, grid, cfg)
        if result is None or result.n == 0:
            pytest.skip("no refinement candidates")
        parents    = np.unique(result.parent_id)
        parent_k   = cells._cell_ring[parents]
        inner_mask = parent_k < grid._n_inner
        assert not inner_mask.any(), (
            f"{inner_mask.sum()} refined cells are in inner rings (< 10 m)"
        )

    def test_to_refined_arrays_round_trip(self, cells, grid, sensor, cfg):
        """T-R1: to_refined_arrays() must produce valid RefinedArrays."""
        _populate(cells, grid, sensor, cfg, "S5_crossing_truck")
        result = refine(cells, grid, cfg)
        if result is None or result.n == 0:
            pytest.skip("no refinement candidates")
        from avr25d.server.protocol import RefinedArrays
        ra = result.to_refined_arrays()
        assert isinstance(ra, RefinedArrays)
        assert ra.n == result.n
        assert ra.parent_id.dtype == np.uint32
        assert ra.quadrant.dtype  == np.uint8
        assert ra.z_ground.dtype  == np.float32

    def test_flat_road_produces_no_refinement(self, cells, grid, sensor, cfg):
        """T-R1 sanity: S1_flat_road has no MOVING cells, so no refinement
        unless roughness/slope exceeds threshold on the road surface."""
        _populate(cells, grid, sensor, cfg, "S1_flat_road")
        result = refine(cells, grid, cfg)
        # Either None or very few cells (road is smooth and has no moving objects)
        if result is not None:
            n_moving_parents = (
                cells.flags[np.unique(result.parent_id)] & FLAG_MOVING
            ).astype(bool).sum()
            # None of the refined cells on S1 should be MOVING
            assert n_moving_parents == 0, (
                f"{n_moving_parents} MOVING parents on flat road"
            )

    def test_disabled_returns_none(self, grid, cells, sensor):
        """When cfg.refine.enabled is False, refine() must return None."""
        from avr25d import load_config
        from unittest.mock import patch
        cfg_real = load_config()
        # Patch the enabled flag by passing a mock config
        class _FakeRefine:
            enabled = False
            max_cells = 4096
            roughness_thresh = 0.03
            slope_thresh_deg = 10.0
        class _FakeCfg:
            refine = _FakeRefine()
        _populate(cells, grid, sensor, cfg_real, "S5_crossing_truck")
        result = refine(cells, grid, _FakeCfg())
        assert result is None


# ---------------------------------------------------------------------------
# T-R2 — adversarial: every far-field cell qualifies, cap must hold
# ---------------------------------------------------------------------------

class TestAdversarialCap:

    def _make_adversarial_cells(self, grid: RingGrid) -> CellGrid:
        """Create a CellGrid where every far-field cell has MOVING flag,
        high roughness, and high slope — worst-case candidate set."""
        cells = CellGrid(grid)
        n_inner = grid._n_inner
        far_start = int(grid.offset[n_inner])
        far_end   = grid.n_cells

        # Mark every far-field cell as occupied with high roughness and MOVING
        cells.count[far_start:far_end]     = np.uint16(50)
        cells.flags[far_start:far_end]    |= FLAG_MOVING
        cells.roughness[far_start:far_end] = np.float32(0.10)  # > thresh 0.03
        cells.slope[far_start:far_end]     = np.float32(20.0)  # > thresh 10.0
        cells.z_ground[far_start:far_end]  = np.float32(-1.7)
        cells.z_obstacle[far_start:far_end]= np.float32(-1.7)
        cells.class_id[far_start:far_end]  = np.uint8(1)       # DRIVABLE
        return cells

    def test_cap_enforced(self, grid, cfg):
        """T-R2: even with 580,734 qualifying cells, at most max_cells are refined."""
        cells = self._make_adversarial_cells(grid)
        result = refine(cells, grid, cfg)
        assert result is not None
        max_cells = int(cfg.refine.max_cells)   # 4096
        n_parents = result.n // 4
        assert n_parents <= max_cells, (
            f"{n_parents} parents refined, limit is {max_cells}"
        )
        assert result.n <= max_cells * 4

    def test_cap_within_latency_budget(self, grid, cfg):
        """T-R2: adversarial refinement must complete in under 50 ms."""
        cells = self._make_adversarial_cells(grid)
        t0 = time.perf_counter()
        refine(cells, grid, cfg)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert elapsed_ms < 50.0, (
            f"adversarial refine took {elapsed_ms:.1f} ms — exceeds 50 ms budget"
        )

    def test_cap_with_zero_max(self, grid):
        """max_cells=0 means no refinement — must return None."""
        cells = self._make_adversarial_cells(grid)

        class _ZeroRef:
            enabled = True
            max_cells = 0
            roughness_thresh = 0.0
            slope_thresh_deg = 0.0

        class _ZeroCfg:
            refine = _ZeroRef()

        result = refine(cells, grid, _ZeroCfg())
        assert result is None or result.n == 0

    def test_arrays_have_consistent_length(self, grid, cfg):
        """All overlay arrays must have the same length = n."""
        cells = self._make_adversarial_cells(grid)
        result = refine(cells, grid, cfg)
        assert result is not None
        n = result.n
        assert len(result.parent_id)  == n
        assert len(result.quadrant)   == n
        assert len(result.z_ground)   == n
        assert len(result.z_obstacle) == n
        assert len(result.class_id)   == n
        assert len(result.flags)      == n

    def test_only_far_field_refined_even_adversarial(self, grid, cfg):
        """T-R2: inner-ring cells must never appear in the overlay."""
        cells = self._make_adversarial_cells(grid)
        # Also mark inner ring cells with MOVING to try to trick the selector
        cells.count[:grid.offset[grid._n_inner]]    = np.uint16(50)
        cells.flags[:grid.offset[grid._n_inner]]   |= FLAG_MOVING
        cells.roughness[:grid.offset[grid._n_inner]]= np.float32(0.10)

        result = refine(cells, grid, cfg)
        assert result is not None
        parents  = np.unique(result.parent_id)
        k_vals   = cells._cell_ring[parents]
        inner    = k_vals < grid._n_inner
        assert not inner.any(), (
            f"{inner.sum()} inner-ring cells appeared in the adversarial overlay"
        )

    def test_repeated_calls_stable(self, grid, cfg):
        """Calling refine twice on the same cells gives consistent n_parents."""
        cells = self._make_adversarial_cells(grid)
        r1 = refine(cells, grid, cfg)
        # Reset REFINED flags so the second call sees a clean state
        if r1 is not None:
            cells.flags[np.unique(r1.parent_id)] &= ~FLAG_REFINED
        r2 = refine(cells, grid, cfg)
        if r1 is None or r2 is None:
            return
        # Both runs face the same candidate set — n must be equal
        assert r1.n == r2.n, f"first call: {r1.n}, second call: {r2.n}"
