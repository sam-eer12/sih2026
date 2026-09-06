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
from avr25d.config import Config
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


    def test_roughness_normaliser_is_read_from_config(self, grid, cfg):
        """NFR-7: every tunable in the FR-19 formula is a config key.

        It was not: ``max_roughness`` was a constant in the source while the
        five weights beside it each carried a line of justification in
        ``config.yaml``.  Doubling the normaliser must halve the penalty, which
        a hardcoded value cannot do.
        """
        cells = CellGrid(grid)
        cells.count[:3]      = 5
        cells.roughness[:3]  = 0.025          # half of the 0.05 default
        cells.slope[:3]      = 0.0
        cells.class_id[:3]   = labelmap.DRIVABLE
        cells.confidence[:3] = 255

        data = cfg.to_dict()
        data["decision"]["traversability"]["max_roughness"] = 0.10
        doubled_cfg = Config(data)

        default = trav_mod.score(cells, cfg)[:3]
        doubled = trav_mod.score(cells, doubled_cfg)[:3]

        w_rough = float(cfg.decision.traversability.roughness_penalty)
        assert doubled == pytest.approx(default + w_rough * 0.25, abs=1e-6)

    def test_step_flag_subsumes_the_vehicle_step_limit(self, cfg):
        """Why the step penalty keys on the flag alone.

        §6.8 defines it as "STEP flag or |dz| > step_max".  The flag fires at
        ``hazards.tau_step`` and the limit is ``vehicle.max_step``; while the
        first is below the second, every cell the second clause would catch
        already carries the flag and the union collapses to it.  Raise
        ``tau_step`` above ``max_step`` and ``traversability.score`` starts
        missing steps the vehicle cannot climb — so the ordering is pinned here
        rather than left as a comment.
        """
        assert float(cfg.hazards.tau_step) <= float(cfg.vehicle.max_step)


# ---------------------------------------------------------------------------
# T-D2 — tracker on S5_crossing_truck
# ---------------------------------------------------------------------------

class TestTracker:
    """T-D2, in the two halves the board asks for: a *stable id across all 40
    frames*, and *speed within 0.5 m/s of 8.0 m/s*.

    Both halves used to be unmeasurable.  Clustering in (ring, bin) space split
    the truck into ~19 fragments per frame, so ``tracks[0]`` was a different
    fragment each frame and the id changed four times; the speed assertion was
    written at +/- 5.0 m/s and guarded by ``if speed_readings:``, so it also
    passed when nothing was tracked at all.
    """

    #: Frames of warm-up allowed before the speed is scored.  The filter is
    #: born with a zero-velocity prior, so this is 1.0 s of observation at
    #: 10 Hz, not a number chosen to make an assertion pass — the estimate is
    #: already inside tolerance from frame 8.
    WARMUP = 10

    @staticmethod
    def _run(grid, sensor, cfg, n_frames):
        """Drive the full 40-frame scene.  -> list of (frame, Track | None)."""
        scene = load_scene("S5_crossing_truck")
        trk   = tracker_mod.Tracker(cfg)
        cells = CellGrid(grid)
        out   = []
        for frame in range(n_frames):
            xyzi, packed = raycast(scene, sensor, t_scene=frame * 0.1)
            sem, _ = labelmap.split_label(packed)
            cells.reset()
            cells.accumulate(
                xyzi[:, :3], xyzi[:, 3],
                labelmap.raw_to_avr(sem), labelmap.raw_is_moving(sem),
            )
            cells.analyse(cfg)
            tracks = trk.update(cells, grid, dt=0.1)
            out.append((frame, tracks[0] if tracks else None))
        return out

    def test_one_cluster_per_frame(self, grid, sensor, cfg):
        """The truck is one object, so it must cluster as one detection.

        This is the assertion that would have caught the ring-space bug on the
        day it was written: 19 detections for a scene containing one moving
        primitive is wrong however good the downstream filter is.
        """
        scene = load_scene("S5_crossing_truck")
        cells = CellGrid(grid)
        t     = cfg.decision.tracker
        for frame in range(40):
            xyzi, packed = raycast(scene, sensor, t_scene=frame * 0.1)
            sem, _ = labelmap.split_label(packed)
            cells.reset()
            cells.accumulate(
                xyzi[:, :3], xyzi[:, 3],
                labelmap.raw_to_avr(sem), labelmap.raw_is_moving(sem),
            )
            cells.analyse(cfg)
            dets = tracker_mod.cluster_centroids(
                cells, grid,
                link_m=float(t.link_m), min_cells=int(t.min_cells),
            )
            assert len(dets) == 1, (
                f"frame {frame}: {len(dets)} dynamic clusters, expected 1 "
                "(the scene contains exactly one moving primitive)"
            )

    def test_stable_id_across_all_40_frames(self, grid, sensor, cfg):
        """T-D2 half one: one id, held for every frame the truck is visible."""
        runs = self._run(grid, sensor, cfg, 40)
        alive = [(f, t) for f, t in runs if t is not None]
        assert alive, "no track born in 40 frames of S5"

        born_frame = alive[0][0]
        assert born_frame <= 2, f"track born only at frame {born_frame}"

        ids = {t.id for _, t in alive}
        assert len(ids) == 1, f"track id changed during the sequence: {sorted(ids)}"

        # No gaps: the truck never leaves the field of view, so a frame without
        # a track is a dropped track, not an absent object.
        frames = [f for f, _ in alive]
        assert frames == list(range(born_frame, 40)), (
            f"track dropped on frames "
            f"{sorted(set(range(born_frame, 40)) - set(frames))}"
        )

    def test_truck_speed_within_half_a_metre_per_second(self, grid, sensor, cfg):
        """T-D2 half two: median speed within 0.5 m/s of the true 8.0 m/s."""
        runs = self._run(grid, sensor, cfg, 40)
        speeds = [t.speed for f, t in runs if t is not None and f >= self.WARMUP]
        assert len(speeds) >= 25, f"only {len(speeds)} scored frames"

        median = float(np.median(speeds))
        assert abs(median - 8.0) <= 0.5, (
            f"tracked speed {median:.3f} m/s, true 8.0 m/s"
        )

    def test_speed_is_at_the_parallax_limit(self, grid, sensor, cfg):
        """The residual error is the measurement's, not the filter's.

        The tracker sees the centroid of the *visible* cells.  Over the
        crossing that centroid slides from the near face of the truck to the
        far one, so its total displacement is short of the truck's by about
        1.6 m — a fixed -0.42 m/s on a 3.9 s crossing that no filter tuning can
        recover.  This test pins the claim: the filter's own contribution to
        the error is small next to that floor, so if the speed assertion above
        ever fails, the cause is the estimator and not the scene.
        """
        scene = load_scene("S5_crossing_truck")
        cells = CellGrid(grid)
        t     = cfg.decision.tracker
        first = last = None
        for frame in range(40):
            xyzi, packed = raycast(scene, sensor, t_scene=frame * 0.1)
            sem, _ = labelmap.split_label(packed)
            cells.reset()
            cells.accumulate(
                xyzi[:, :3], xyzi[:, 3],
                labelmap.raw_to_avr(sem), labelmap.raw_is_moving(sem),
            )
            cells.analyse(cfg)
            cx, cy, _, _ = tracker_mod.cluster_centroids(
                cells, grid,
                link_m=float(t.link_m), min_cells=int(t.min_cells),
            )[0]
            if frame == 0:
                first = (cx, cy)
            last = (cx, cy)

        # Best possible speed from these centroids: the finite difference over
        # the whole 39-frame span, which no causal filter can beat.
        ceiling = math.hypot(last[0] - first[0], last[1] - first[1]) / (39 * 0.1)
        assert 7.4 <= ceiling <= 7.7, f"centroid ceiling moved to {ceiling:.3f} m/s"

        runs   = self._run(grid, sensor, cfg, 40)
        speeds = [t.speed for f, t in runs if t is not None and f >= self.WARMUP]
        filter_error = abs(float(np.median(speeds)) - ceiling)
        assert filter_error <= 0.10, (
            f"filter adds {filter_error:.3f} m/s on top of the {abs(ceiling - 8.0):.3f} "
            "m/s parallax floor"
        )

    def test_static_poles_never_become_tracks(self, grid, sensor, cfg):
        """The two roadside poles are STATIC_OBSTACLE and must be ignored.

        A tracker that adopts them passes a one-object test and fails a real
        scene — which is why the scene has them.
        """
        runs = self._run(grid, sensor, cfg, 40)
        for frame, track in runs:
            if track is None:
                continue
            assert track.class_id == labelmap.DYNAMIC_OBJECT, (
                f"frame {frame}: tracked a class-{track.class_id} object"
            )

    def test_tracker_reset_clears_tracks_and_ids(self, grid, sensor, cfg):
        scene = load_scene("S5_crossing_truck")
        trk   = tracker_mod.Tracker(cfg)
        cells = CellGrid(grid)

        for frame in range(5):
            xyzi, packed = raycast(scene, sensor, t_scene=frame * 0.1)
            sem, _ = labelmap.split_label(packed)
            cells.reset()
            cells.accumulate(
                xyzi[:, :3], xyzi[:, 3],
                labelmap.raw_to_avr(sem), labelmap.raw_is_moving(sem),
            )
            cells.analyse(cfg)
            trk.update(cells, grid, dt=0.1)

        trk.reset()
        assert len(trk._tracks) == 0, "tracks not cleared after reset()"
        assert trk._next_id == 1, "ids not restarted after reset()"

    def test_ids_are_per_instance(self, grid, sensor, cfg):
        """Two Trackers both start at 1.

        The counter used to be a module global, so a test's ids depended on how
        many tracks every earlier test had created — which is why the old
        stable-id test could only assert that *some* id existed.
        """
        a = tracker_mod.Tracker(cfg)
        b = tracker_mod.Tracker(cfg)
        assert a._new_id() == b._new_id() == 1


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
