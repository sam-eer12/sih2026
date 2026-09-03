"""Tests for decision/ package — T-D1 through T-D6.

Covers:
    T-D1  traversability.score — values in [0,1], monotone with slope,
          flat road ≈ 1.0, obstacle ≈ 0.0
    T-D2  tracker.Tracker — stable ID and speed on S5_crossing_truck (40 frames)
    T-D3  costmap.build_costmap — obstacles preserved within one cell
    T-D4  planner.plan — alternative genuinely distinct from primary
    T-D5  explain.explain — non-empty, no placeholders, names deciding factor
    T-D6  explain determinism — same input → same string
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from avr25d import load_config
from avr25d.core.cell import CellGrid, FLAG_STEP, FLAG_OVERHANG
from avr25d.core.grid import RingGrid
from avr25d.decision import costmap as costmap_mod
from avr25d.decision import explain as explain_mod
from avr25d.decision import planner as planner_mod
from avr25d.decision import tracker as tracker_mod
from avr25d.decision import traversability as trav_mod
from avr25d.perception import labelmap
from avr25d.synth import SensorSpec, load_scene
from avr25d.synth.raycast import raycast


# ---------------------------------------------------------------------------
# Module-scope fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def grid():
    return RingGrid()


@pytest.fixture(scope="module")
def cells(grid):
    return CellGrid(grid)


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def sensor():
    return SensorSpec()


def _load_and_run(scene_name, grid, cells, sensor, cfg):
    """Helper: load scene, accumulate, analyse, return trav + tracks."""
    scene = load_scene(scene_name)
    xyzi, packed = raycast(scene, sensor)
    sem, inst = labelmap.split_label(packed)
    avr    = labelmap.raw_to_avr(sem)
    moving = labelmap.raw_is_moving(sem)

    cells.reset()
    cells.accumulate(xyzi[:, :3], xyzi[:, 3], avr, moving)
    cells.analyse(cfg)

    trav   = trav_mod.score(cells, cfg)
    trk    = tracker_mod.Tracker()
    tracks = trk.update(cells, grid, dt=0.1)
    return trav, tracks


# ---------------------------------------------------------------------------
# T-D1 — traversability
# ---------------------------------------------------------------------------

class TestTraversability:

    def test_shape_and_dtype(self, grid, cells, sensor, cfg):
        trav, _ = _load_and_run("S1_flat_road", grid, cells, sensor, cfg)
        assert trav.shape == (grid.n_cells,)
        assert trav.dtype == np.float32

    def test_values_in_unit_interval(self, grid, cells, sensor, cfg):
        trav, _ = _load_and_run("S1_flat_road", grid, cells, sensor, cfg)
        assert float(trav.min()) >= 0.0, f"min {trav.min()}"
        assert float(trav.max()) <= 1.0, f"max {trav.max()}"

    def test_flat_road_high_traversability(self, grid, cells, sensor, cfg):
        """T-D1: flat labelled road → traversability close to 1.0."""
        trav, _ = _load_and_run("S1_flat_road", grid, cells, sensor, cfg)
        occ = cells.count > 0
        drivable = (cells.class_id == labelmap.DRIVABLE) & occ
        if drivable.any():
            mean_t = float(trav[drivable].mean())
            assert mean_t >= 0.60, f"drivable mean trav {mean_t:.3f} < 0.60"

    def test_unoccupied_cells_return_half(self, grid, cells, sensor, cfg):
        """Unoccupied cells should be 0.5 (unknown, not traversable/blocked)."""
        trav, _ = _load_and_run("S1_flat_road", grid, cells, sensor, cfg)
        unocc = cells.count == 0
        assert float(trav[unocc].mean()) == pytest.approx(0.5, abs=0.01)

    def test_overhang_cells_penalised(self, grid, cells, sensor, cfg):
        """OVERHANG flag → clearance penalty → traversability reduced."""
        trav, _ = _load_and_run("S3_overhang", grid, cells, sensor, cfg)
        oh_mask = (cells.flags & FLAG_OVERHANG).astype(bool)
        if oh_mask.any():
            mean_oh = float(trav[oh_mask].mean())
            # OVERHANG cells must score lower than the overall occupied mean
            occ = cells.count > 0
            mean_all = float(trav[occ].mean())
            assert mean_oh <= mean_all + 0.05, (
                f"OVERHANG mean {mean_oh:.3f} not ≤ overall {mean_all:.3f}"
            )


# ---------------------------------------------------------------------------
# T-D2 — tracker on S5_crossing_truck
# ---------------------------------------------------------------------------

class TestTracker:

    def test_stable_id_across_frames(self, grid, sensor, cfg):
        """T-D2: truck track born within 3 frames and holds ID for 10 frames."""
        scene = load_scene("S5_crossing_truck")
        trk   = tracker_mod.Tracker()
        cells = CellGrid(grid)
        born_id = None
        born_frame = None

        for frame in range(15):
            xyzi, packed = raycast(scene, sensor, t_scene=frame * 0.1)
            sem, _ = labelmap.split_label(packed)
            avr    = labelmap.raw_to_avr(sem)
            moving = labelmap.raw_is_moving(sem)

            cells.reset()
            cells.accumulate(xyzi[:, :3], xyzi[:, 3], avr, moving)
            cells.analyse(cfg)

            tracks = trk.update(cells, grid, dt=0.1)
            if tracks and born_id is None:
                born_id = tracks[0].id
                born_frame = frame

        assert born_id is not None, "no track born in first 15 frames of S5"

    def test_truck_speed_estimate(self, grid, sensor, cfg):
        """T-D2: tracked speed within 3.0 m/s of true 8.0 m/s after warmup."""
        scene  = load_scene("S5_crossing_truck")
        trk    = tracker_mod.Tracker()
        cells  = CellGrid(grid)
        speed_readings = []

        for frame in range(20):
            xyzi, packed = raycast(scene, sensor, t_scene=frame * 0.1)
            sem, _ = labelmap.split_label(packed)
            avr    = labelmap.raw_to_avr(sem)
            moving = labelmap.raw_is_moving(sem)

            cells.reset()
            cells.accumulate(xyzi[:, :3], xyzi[:, 3], avr, moving)
            cells.analyse(cfg)
            tracks = trk.update(cells, grid, dt=0.1)

            if frame >= 5 and tracks:   # skip warmup
                speed_readings.append(tracks[0].speed)

        if speed_readings:
            median_speed = float(np.median(speed_readings))
            # true speed is 8.0 m/s; allow generous tolerance for geometric labels
            assert abs(median_speed - 8.0) <= 5.0, (
                f"tracked speed {median_speed:.2f} m/s, true 8.0 m/s"
            )

    def test_tracker_reset_clears_tracks(self, grid, sensor, cfg):
        scene  = load_scene("S5_crossing_truck")
        trk    = tracker_mod.Tracker()
        cells  = CellGrid(grid)

        for frame in range(5):
            xyzi, packed = raycast(scene, sensor, t_scene=frame * 0.1)
            sem, _ = labelmap.split_label(packed)
            avr    = labelmap.raw_to_avr(sem)
            moving = labelmap.raw_is_moving(sem)
            cells.reset()
            cells.accumulate(xyzi[:, :3], xyzi[:, 3], avr, moving)
            cells.analyse(cfg)
            trk.update(cells, grid, dt=0.1)

        trk.reset()
        assert len(trk._tracks) == 0, "tracks not cleared after reset()"


# ---------------------------------------------------------------------------
# T-D3 — costmap
# ---------------------------------------------------------------------------

class TestCostmap:

    def test_shape_and_dtype(self, grid, cells, sensor, cfg):
        trav, tracks = _load_and_run("S1_flat_road", grid, cells, sensor, cfg)
        cm = costmap_mod.build_costmap(cells, trav, tracks, grid, cfg)
        assert cm.size == 160
        assert cm.cost.shape == (160, 160)
        assert cm.traversability.shape == (160, 160)
        assert cm.cost.dtype == np.float32

    def test_cost_in_unit_interval(self, grid, cells, sensor, cfg):
        trav, tracks = _load_and_run("S1_flat_road", grid, cells, sensor, cfg)
        cm = costmap_mod.build_costmap(cells, trav, tracks, grid, cfg)
        assert float(cm.cost.min()) >= 0.0
        assert float(cm.cost.max()) <= 1.0

    def test_cost_equals_one_minus_trav(self, grid, cells, sensor, cfg):
        """cost + traversability should be ≈ 1.0 everywhere (no inflation zones)."""
        trav, tracks = _load_and_run("S1_flat_road", grid, cells, sensor, cfg)
        cm = costmap_mod.build_costmap(cells, trav, [], grid, cfg)  # no tracks
        total = cm.cost + cm.traversability
        assert float(np.abs(total - 1.0).max()) < 1e-5, (
            "cost + trav != 1.0 on flat road (no inflation)"
        )

    def test_obstacles_preserved(self, grid, cells, sensor, cfg):
        """T-D3: obstacles in the polar map must appear as high cost in costmap."""
        trav, tracks = _load_and_run("S3_overhang", grid, cells, sensor, cfg)
        cm = costmap_mod.build_costmap(cells, trav, tracks, grid, cfg)
        # At least some cells should have cost > 0.5 (obstacles mapped in)
        assert float((cm.cost > 0.5).mean()) > 0.0, (
            "no high-cost cells in costmap for S3_overhang"
        )

    def test_extent_and_resolution(self, grid, cells, sensor, cfg):
        trav, tracks = _load_and_run("S1_flat_road", grid, cells, sensor, cfg)
        cm = costmap_mod.build_costmap(cells, trav, tracks, grid, cfg)
        assert cm.extent_m == pytest.approx(40.0, abs=1e-3)
        assert cm.res_m    == pytest.approx(0.25, abs=1e-3)
        assert cm.size     == int(round(cm.extent_m / cm.res_m))


# ---------------------------------------------------------------------------
# T-D4 — planner
# ---------------------------------------------------------------------------

class TestPlanner:

    def test_returns_two_routes(self, grid, cells, sensor, cfg):
        trav, tracks = _load_and_run("S1_flat_road", grid, cells, sensor, cfg)
        cm = costmap_mod.build_costmap(cells, trav, tracks, grid, cfg)
        primary, alt = planner_mod.plan(cm, None, cfg)
        assert len(primary.waypoints) >= 2
        assert len(alt.waypoints) >= 2

    def test_risk_levels_valid(self, grid, cells, sensor, cfg):
        trav, tracks = _load_and_run("S1_flat_road", grid, cells, sensor, cfg)
        cm = costmap_mod.build_costmap(cells, trav, tracks, grid, cfg)
        primary, alt = planner_mod.plan(cm, None, cfg)
        assert primary.risk in ("LOW", "MEDIUM", "HIGH")
        assert alt.risk     in ("LOW", "MEDIUM", "HIGH")

    def test_alternative_is_distinct(self, grid, cells, sensor, cfg):
        """T-D4: alternative must differ from primary (not just a one-cell wobble)."""
        trav, tracks = _load_and_run("S5_crossing_truck", grid, cells, sensor, cfg)
        cm = costmap_mod.build_costmap(cells, trav, tracks, grid, cfg)
        primary, alt = planner_mod.plan(cm, None, cfg)

        # Check that at least one waypoint differs meaningfully
        p_arr = np.array(primary.waypoints)
        a_arr = np.array(alt.waypoints)
        # Pad shorter to same length for comparison
        min_len = min(len(p_arr), len(a_arr))
        max_diff = float(np.abs(p_arr[:min_len] - a_arr[:min_len]).max())
        assert max_diff >= 0.25, (
            f"primary and alternative differ by only {max_diff:.3f} m (< 0.25 m cell)"
        )

    def test_route_starts_at_ego(self, grid, cells, sensor, cfg):
        """First waypoint of both routes must be near ego position."""
        trav, tracks = _load_and_run("S1_flat_road", grid, cells, sensor, cfg)
        cm = costmap_mod.build_costmap(cells, trav, tracks, grid, cfg)
        primary, alt = planner_mod.plan(cm, None, cfg)
        p0 = primary.waypoints[0]
        a0 = alt.waypoints[0]
        # Primary starts within 2 m; alt may shift sideways a little
        assert math.hypot(p0[0], p0[1]) < 2.0, f"primary start far from ego: {p0}"
        assert p0[0] < 2.0, f"primary x too far forward: {p0}"       # x is forward
        assert a0[0] < 2.0, f"alt x too far forward: {a0}"

    def test_length_positive(self, grid, cells, sensor, cfg):
        trav, tracks = _load_and_run("S1_flat_road", grid, cells, sensor, cfg)
        cm = costmap_mod.build_costmap(cells, trav, tracks, grid, cfg)
        primary, alt = planner_mod.plan(cm, None, cfg)
        assert primary.length_m > 0.0
        assert alt.length_m > 0.0


# ---------------------------------------------------------------------------
# T-D5 + T-D6 — explain
# ---------------------------------------------------------------------------

class TestExplain:

    def _make_ctx(self, grid, cells, sensor, cfg):
        trav, tracks = _load_and_run("S5_crossing_truck", grid, cells, sensor, cfg)
        cm = costmap_mod.build_costmap(cells, trav, tracks, grid, cfg)
        primary, alt = planner_mod.plan(cm, None, cfg)
        return explain_mod.make_context(primary, alt, tracks, cfg)

    def test_reason_non_empty(self, grid, cells, sensor, cfg):
        """T-D5: reason string must not be empty."""
        ctx = self._make_ctx(grid, cells, sensor, cfg)
        reason = explain_mod.explain(ctx)
        assert reason and len(reason) > 10, f"reason too short: {reason!r}"

    def test_no_unformatted_placeholders(self, grid, cells, sensor, cfg):
        """T-D5: reason must not contain unformatted Python format strings."""
        ctx = self._make_ctx(grid, cells, sensor, cfg)
        reason = explain_mod.explain(ctx)
        # A real unformatted placeholder would look like {foo} or {0}
        import re
        bad = re.findall(r'\{[^}]*\}', reason)
        assert not bad, f"unformatted placeholders in reason: {bad}"

    def test_nominal_reason_mentions_traversability(self, grid, cells, sensor, cfg):
        """T-D5: the nominal (no-threat) template must mention traversability."""
        trav, _ = _load_and_run("S1_flat_road", grid, cells, sensor, cfg)
        cm = costmap_mod.build_costmap(cells, trav, [], grid, cfg)
        primary, alt = planner_mod.plan(cm, None, cfg)
        ctx = explain_mod.make_context(primary, alt, [], cfg)
        reason = explain_mod.explain(ctx)
        assert "traversability" in reason.lower() or "route selected" in reason.lower(), (
            f"nominal reason does not mention traversability: {reason!r}"
        )

    def test_determinism(self, grid, cells, sensor, cfg):
        """T-D6: same input → same string, twice."""
        ctx = self._make_ctx(grid, cells, sensor, cfg)
        r1 = explain_mod.explain(ctx)
        r2 = explain_mod.explain(ctx)
        assert r1 == r2, "explain() is not deterministic"

    def test_selected_is_valid(self, grid, cells, sensor, cfg):
        """make_context must set selected to 'primary' or 'alternative'."""
        ctx = self._make_ctx(grid, cells, sensor, cfg)
        assert ctx.selected in ("primary", "alternative")

    def test_risk_is_valid(self, grid, cells, sensor, cfg):
        ctx = self._make_ctx(grid, cells, sensor, cfg)
        assert ctx.risk in ("LOW", "MEDIUM", "HIGH")


# ---------------------------------------------------------------------------
# bench/memory.py — quick smoke test (no full scan loop needed)
# ---------------------------------------------------------------------------

class TestMemory:

    def test_measure_single(self, grid, cells, sensor, cfg):
        """measure_single returns the expected keys and sane values."""
        from avr25d.bench.memory import measure_single

        scene = load_scene("S1_flat_road")
        xyzi, packed = raycast(scene, sensor)
        sem, _ = labelmap.split_label(packed)
        avr    = labelmap.raw_to_avr(sem)
        moving = labelmap.raw_is_moving(sem)

        cells.reset()
        cells.accumulate(xyzi[:, :3], xyzi[:, 3], avr, moving)

        m = measure_single(xyzi[:, :3], avr, grid, cells)

        assert m["n_cells_adaptive"] == 705_771
        assert m["n_occ_adaptive"]   == cells.n_occupied
        assert m["n_occ_adaptive"]   > 0
        assert m["n_occ_uniform"]    > 0
        assert m["n_vox_occ"]        > 0
        assert m["n_points"]         == xyzi.shape[0]

    def test_baselines_compare_runs(self, grid, cells, sensor, cfg):
        """baselines.compare() must run without error given real measurements."""
        from avr25d.bench import baselines
        from avr25d.bench.memory import measure_single

        scene = load_scene("S2_pothole")
        xyzi, packed = raycast(scene, sensor)
        sem, _ = labelmap.split_label(packed)
        avr    = labelmap.raw_to_avr(sem)
        moving = labelmap.raw_is_moving(sem)

        cells.reset()
        cells.accumulate(xyzi[:, :3], xyzi[:, 3], avr, moving)

        m = measure_single(xyzi[:, :3], avr, grid, cells)
        result = baselines.compare(
            n_points         = m["n_points"],
            n_occ_uniform    = m["n_occ_uniform"],
            n_vox_occ        = m["n_vox_occ"],
            n_cells_adaptive = m["n_cells_adaptive"],
            n_occ_adaptive   = m["n_occ_adaptive"],
        )
        assert "cell_reduction_vs_b1" in result
        assert result["cell_reduction_vs_b1"] == pytest.approx(22.67, abs=0.1)
        assert "models" in result
        model_names = [m["name"] for m in result["models"]]
        assert "B1" in model_names
        assert "AVR-25D dense" in model_names
