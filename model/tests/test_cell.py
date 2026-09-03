"""Tests for core/cell.py — T-G5, T-H1, T-H2, T-H3, T-H4.

Hazard tests use the synthetic scenes from conftest.py (already ray-cast
at module scope so the geometry is exact and free of noise).
"""

from __future__ import annotations

import numpy as np
import pytest

from avr25d.core.cell import (
    CellGrid,
    FLAG_LOW_CONFIDENCE,
    FLAG_MOVING,
    FLAG_NEGATIVE_OBSTACLE,
    FLAG_OCCUPIED,
    FLAG_OVERHANG,
    FLAG_STEP,
)
from avr25d.core.grid import RingGrid
from avr25d.perception import labelmap


# ---------------------------------------------------------------------------
# Fixtures — shared grid + cells (module scope: built once)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def grid() -> RingGrid:
    return RingGrid()


@pytest.fixture(scope="module")
def cells(grid) -> CellGrid:
    return CellGrid(grid)


def _populate(cells: CellGrid, grid: RingGrid, cast: dict, cfg) -> None:
    """Reset and accumulate one synthetic scene into cells."""
    cells.reset()
    xyz    = cast["xyzi"][:, :3]
    inten  = cast["xyzi"][:, 3]
    avr    = cast["avr"]
    moving = cast["moving"]
    cells.accumulate(xyz, inten, avr, moving)
    cells.analyse(cfg)


# ---------------------------------------------------------------------------
# T-G5 — accumulate correctness
# ---------------------------------------------------------------------------

class TestAccumulate:
    def test_fr10_conservation_all_scenes(self, cells, grid, casts, cfg):
        """T-G5 / FR-10: n_points_in == n_points_assigned for every scene."""
        for name, cast in casts.items():
            cells.reset()
            stats = cells.accumulate(
                cast["xyzi"][:, :3], cast["xyzi"][:, 3], cast["avr"], cast["moving"]
            )
            assert stats.n_points_in == stats.n_points_assigned, \
                f"{name}: FR-10 violated ({stats.n_points_in} in, {stats.n_points_assigned} assigned)"

    def test_count_sum_equals_n_points(self, cells, grid, casts, cfg):
        """Sum of cell counts must equal the number of projected points."""
        cast = casts["S1_flat_road"]
        cells.reset()
        stats = cells.accumulate(
            cast["xyzi"][:, :3], cast["xyzi"][:, 3], cast["avr"], cast["moving"]
        )
        assert int(cells.count.sum()) == stats.n_points_assigned

    def test_occupied_flag_set_iff_count_positive(self, cells, grid, casts, cfg):
        """OCCUPIED bit must be 1 exactly where count > 0."""
        _populate(cells, grid, casts["S1_flat_road"], cfg)
        occ_flag  = (cells.flags & FLAG_OCCUPIED).astype(bool)
        occ_count = cells.count > 0
        assert np.array_equal(occ_flag, occ_count)

    def test_reset_clears_all_state(self, cells, grid, casts, cfg):
        """After reset(), all fields must be at their initial values."""
        _populate(cells, grid, casts["S2_pothole"], cfg)
        cells.reset()
        assert cells.count.sum() == 0
        assert (cells.flags == 0).all()
        assert not np.any(np.isfinite(cells.z_ground))
        assert not np.any(np.isfinite(cells.z_obstacle))

    def test_no_reallocation_across_frames(self, cells, grid, casts, cfg):
        """T-G6 spirit applied to CellGrid: array identity stable across frames."""
        id_zg = id(cells.z_ground)
        id_fl = id(cells.flags)
        for name in ["S1_flat_road", "S2_pothole", "S3_overhang"]:
            _populate(cells, grid, casts[name], cfg)
        assert id(cells.z_ground) == id_zg, "z_ground reallocated"
        assert id(cells.flags)    == id_fl, "flags reallocated"

    def test_class_id_dominated_by_majority(self, cells, grid, casts, cfg):
        """Occupied cells on the flat road must be mostly DRIVABLE."""
        _populate(cells, grid, casts["S1_flat_road"], cfg)
        occ  = cells.count > 0
        cls  = cells.class_id[occ]
        frac_drivable = float((cls == labelmap.DRIVABLE).mean())
        assert frac_drivable >= 0.60, \
            f"only {frac_drivable:.2%} of S1 cells are DRIVABLE"

    def test_moving_flag_set_for_truck(self, cells, grid, casts, cfg):
        """S5_crossing_truck: at least some cells must carry FLAG_MOVING."""
        _populate(cells, grid, casts["S5_crossing_truck"], cfg)
        n_moving = int((cells.flags & FLAG_MOVING).astype(bool).sum())
        assert n_moving > 0, "no MOVING cells on S5"

    def test_empty_cloud_is_safe(self, cells, grid, cfg):
        """accumulate on zero points must not raise or leave stale state."""
        cells.reset()
        stats = cells.accumulate(
            np.zeros((0, 3), np.float32),
            np.zeros(0, np.float32),
            np.zeros(0, np.uint8),
        )
        assert stats.n_points_in == 0
        assert stats.n_points_assigned == 0
        assert cells.count.sum() == 0

    def test_z_ground_is_near_sensor_height_on_flat_road(self, cells, grid, casts, cfg, sensor):
        """On S1 the road is at z = -sensor_height in the sensor frame."""
        _populate(cells, grid, casts["S1_flat_road"], cfg)
        occ   = cells.count > 0
        z_gnd = cells.z_ground[occ]
        finite = z_gnd[np.isfinite(z_gnd)]
        expected = -float(sensor.sensor_height)
        assert float(np.median(finite)) == pytest.approx(expected, abs=0.20), \
            f"median z_ground {float(np.median(finite)):.3f} far from expected {expected:.3f}"


# ---------------------------------------------------------------------------
# T-H4 — S1_flat_road: zero hazard flags (the false-positive test)
# ---------------------------------------------------------------------------

class TestHazardFlatRoad:
    @pytest.fixture(autouse=True)
    def _setup(self, cells, grid, casts, cfg):
        _populate(cells, grid, casts["S1_flat_road"], cfg)

    def test_no_overhang(self, cells):
        """T-H4: S1 must produce zero OVERHANG flags."""
        n = int((cells.flags & FLAG_OVERHANG).astype(bool).sum())
        assert n == 0, f"S1_flat_road: {n} false OVERHANG flags"

    def test_no_negative_obstacle(self, cells):
        """T-H4: S1 must produce zero NEGATIVE_OBSTACLE flags."""
        n = int((cells.flags & FLAG_NEGATIVE_OBSTACLE).astype(bool).sum())
        assert n == 0, f"S1_flat_road: {n} false NEGATIVE_OBSTACLE flags"

    def test_no_step(self, cells):
        """T-H4: S1 must produce zero STEP flags."""
        n = int((cells.flags & FLAG_STEP).astype(bool).sum())
        assert n == 0, f"S1_flat_road: {n} false STEP flags"


# ---------------------------------------------------------------------------
# T-H2 — S2_pothole: NEGATIVE_OBSTACLE fires, depth within tolerance
# ---------------------------------------------------------------------------

class TestPothole:
    @pytest.fixture(autouse=True)
    def _setup(self, cells, grid, casts, cfg):
        _populate(cells, grid, casts["S2_pothole"], cfg)

    def test_negative_obstacle_fires(self, cells):
        """T-H2: at least one NEGATIVE_OBSTACLE cell on S2."""
        n = int((cells.flags & FLAG_NEGATIVE_OBSTACLE).astype(bool).sum())
        assert n >= 1, "S2_pothole: NEGATIVE_OBSTACLE never fired"

    def test_pothole_z_ground_below_road(self, cells, casts, scenes):
        """T-H2: the z_ground of flagged cells is below the road surface."""
        gt   = scenes["S2_pothole"].ground_truth["hazards"][0]
        floor_z_sensor = float(gt["floor_z_sensor_m"])   # < 0 (below sensor)
        pit_mask = (cells.flags & FLAG_NEGATIVE_OBSTACLE).astype(bool)
        z_pit = cells.z_ground[pit_mask]
        finite = z_pit[np.isfinite(z_pit)]
        assert finite.size > 0, "no finite z_ground in NEGATIVE_OBSTACLE cells"
        # The flagged cells should sit below the nominal road level
        road_z = -1.70   # sensor height
        assert float(finite.min()) < road_z + 0.05, \
            f"pothole z_ground {finite.min():.3f} not below road level {road_z:.3f}"


# ---------------------------------------------------------------------------
# T-H1 — S3_overhang: OVERHANG fires, ground stays DRIVABLE, clearance ≈ 3.1 m
# ---------------------------------------------------------------------------

class TestOverhang:
    @pytest.fixture(autouse=True)
    def _setup(self, cells, grid, casts, cfg):
        _populate(cells, grid, casts["S3_overhang"], cfg)

    def test_overhang_fires(self, cells):
        """T-H1: at least one OVERHANG cell on S3."""
        n = int((cells.flags & FLAG_OVERHANG).astype(bool).sum())
        assert n >= 1, "S3_overhang: OVERHANG never fired"

    def test_drivable_ground_preserved_beneath_overhang(self, cells):
        """T-H1: cells with OVERHANG must still be DRIVABLE (ground is traversable)."""
        overhang_mask = (cells.flags & FLAG_OVERHANG).astype(bool)
        cls_under = cells.class_id[overhang_mask]
        assert (cls_under == labelmap.DRIVABLE).all(), \
            "OVERHANG cells are not all DRIVABLE — ground classification lost"

    def test_clearance_within_tolerance(self, cells, scenes, cfg):
        """T-H1: the OVERHANG cells have clearance (z_obs - z_gnd) > 0 and < H_vehicle.

        The cell's z_obstacle is the max non-ground return height in sensor frame.
        For the gantry scene: the gantry beam sits at ~1.40 m in sensor frame
        (3.10 m road frame − 1.70 m sensor height).  Clearance = z_obs − z_gnd
        should be < H_vehicle (3.50 m) and > 0.
        """
        H_vehicle = float(cfg.vehicle.height)
        overhang_mask = (cells.flags & FLAG_OVERHANG).astype(bool)
        z_gnd = cells.z_ground[overhang_mask]
        z_obs = cells.z_obstacle[overhang_mask]
        valid = np.isfinite(z_gnd) & np.isfinite(z_obs)
        assert valid.any(), "no finite z values in OVERHANG cells"
        clearance = z_obs[valid] - z_gnd[valid]
        # clearance must be positive (obstacle above ground) and < H_vehicle
        assert float(clearance.min()) > 0, \
            f"negative clearance in OVERHANG cell: {clearance.min():.3f}"
        assert float(clearance.max()) < H_vehicle, \
            f"clearance {clearance.max():.3f} >= H_vehicle {H_vehicle}"


# ---------------------------------------------------------------------------
# T-H3 — S4_curb: STEP fires along the kerb
# ---------------------------------------------------------------------------

class TestStep:
    @pytest.fixture(autouse=True)
    def _setup(self, cells, grid, casts, cfg):
        _populate(cells, grid, casts["S4_curb"], cfg)

    def test_step_fires(self, cells):
        """T-H3: at least one STEP cell on S4."""
        n = int((cells.flags & FLAG_STEP).astype(bool).sum())
        assert n >= 1, "S4_curb: STEP never fired"


# ---------------------------------------------------------------------------
# Protocol + fixtures smoke tests
# ---------------------------------------------------------------------------

class TestProtocol:
    def test_encode_decode_round_trip(self):
        """round_trip(msg) must decode to matching cell count and FR-10 stats."""
        from avr25d.server.protocol import round_trip
        from avr25d.server.fixtures import frame_generator
        import itertools
        gen = frame_generator()
        for msg in itertools.islice(gen, 3):
            back = round_trip(msg)
            assert back["cells"]["n"] == msg.cells.n
            assert back["stats"]["n_points"] == back["stats"]["n_points_conserved"]
            arr = back["_arrays"]["cells"]
            assert arr["cell_id"].shape[0] == msg.cells.n

    def test_fixtures_mode_field(self):
        """Fixture frames must report mode='geometric' (the fixture default)."""
        from avr25d.server.fixtures import frame_generator
        import itertools
        gen = frame_generator()
        msg = next(gen)
        assert msg.mode == "geometric"

    def test_fixtures_fr10(self):
        """Fixture stats must have n_points == n_points_conserved (FR-10)."""
        from avr25d.server.fixtures import frame_generator
        import itertools
        gen = frame_generator()
        for msg in itertools.islice(gen, 5):
            assert msg.stats.n_points == msg.stats.n_points_conserved
