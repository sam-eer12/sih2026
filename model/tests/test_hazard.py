"""Tests for bench/hazard.py — T-H1 … T-H4 at benchmark level, plus T-B5.

``tests/test_cell.py`` asserts that each hazard flag *fires at all*.  This file
asserts the numbers §11.4 actually publishes: the geometric error in metres,
the detection rate, the false-positive count, and the 2D counterfactual.  A
flag that fires on one cell passes the former and is worthless; these are the
assertions a judge's question lands on.
"""

from __future__ import annotations

import numpy as np
import pytest

from avr25d import load_config
from avr25d.bench import hazard
from avr25d.core.cell import CellGrid
from avr25d.core.grid import RingGrid


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def grid(cfg):
    return RingGrid(
        s_min=float(cfg.grid.s_min), s_max=float(cfg.grid.s_max),
        r_knee=float(cfg.grid.r_knee), r_max=float(cfg.grid.r_max),
    )


@pytest.fixture(scope="module")
def scored(cfg, grid):
    """Every scene, scored once.  ~4 s, so it is shared across the module."""
    return hazard.score_all(cfg)


def _row(scored, scene):
    rows = [r for r in scored["scenes"] if r["scene"] == scene]
    assert rows, f"no row for {scene}"
    return rows[0]


# ---------------------------------------------------------------------------
# T-H4 — the false-positive test
# ---------------------------------------------------------------------------

class TestFlatRoadFalsePositives:

    def test_zero_hazard_flags_on_s1(self, scored):
        """T-H4: a flat road raises no hazard flag at all."""
        row = _row(scored, "S1_flat_road")
        assert row["measured"] == 0.0, (
            f"{int(row['measured'])} false positives on a flat road "
            f"({row['false_positive_rate']:.2%} of {row['cells_covering']:,} "
            "occupied cells)"
        )

    def test_the_scene_is_not_trivially_empty(self, scored):
        """A zero that comes from an empty grid is not a passing test."""
        row = _row(scored, "S1_flat_road")
        assert row["cells_covering"] > 10_000, (
            f"only {row['cells_covering']} occupied cells — S1 did not render"
        )


# ---------------------------------------------------------------------------
# T-H2 — pothole depth
# ---------------------------------------------------------------------------

class TestPotholeDepth:

    def test_depth_within_5_cm(self, scored):
        """T-H2: depth within 0.05 m of the CSV's 0.22 m."""
        row = _row(scored, "S2_pothole")
        assert row["true_value"] == 0.22
        assert row["error"] <= 0.05, (
            f"measured {row['measured']} m against a true 0.22 m"
        )

    def test_flag_fires_on_every_sunken_cell(self, scored):
        """T-H2's 80%, with the rim taken out of the denominator.

        The pit's covering cells include its rim, which sits at road level by
        construction and must *not* raise NEGATIVE_OBSTACLE.  Six of the 27
        covering cells are rim, which caps the literal rate at 77.8% however
        good the detector is; every cell genuinely below the local road fires.
        """
        row = _row(scored, "S2_pothole")
        assert row["detection_rate_below_reference"] == 1.0, (
            f"{row['detection_rate_below_reference']:.1%} of the cells below "
            "the road reference carry NEGATIVE_OBSTACLE"
        )
        assert row["detection_rate"] >= 0.75, (
            f"literal covering-cell rate fell to {row['detection_rate']:.1%}"
        )

    def test_ring_neighbourhood_reference_is_the_road(self, scored):
        """The reference must be the road, not the pit.

        This is the regression test for the defect that made the whole row
        meaningless: a single ring's median was the pothole itself, because a
        pit's far wall lands in rings that ambient ground returns do not reach.
        A reference anywhere near the pit floor (-1.92 m) means it has come
        back.
        """
        row = _row(scored, "S2_pothole")
        assert -1.75 <= row["road_reference_z_m"] <= -1.65, (
            f"road reference is {row['road_reference_z_m']} m; the road is at "
            "-1.70 m and the pit floor at -1.92 m"
        )

    def test_2d_grid_cannot_represent_it(self, scored):
        """PS-10, measured: a 2D occupancy grid marks the hole free space."""
        row = _row(scored, "S2_pothole")
        cf = row["counterfactual_2d"]
        assert cf["blocked_fraction"] == 0.0
        assert cf["hazard_representable"] is False


# ---------------------------------------------------------------------------
# T-H1 — overhead clearance
# ---------------------------------------------------------------------------

class TestOverheadClearance:

    def test_clearance_within_5_cm(self, scored):
        """T-H1: clearance within 0.05 m of the CSV's 3.10 m."""
        row = _row(scored, "S3_overhang")
        assert row["true_value"] == 3.1
        assert row["error"] <= 0.05, (
            f"measured {row['measured']} m against a true 3.10 m"
        )

    def test_ground_beneath_stays_drivable(self, cfg, grid):
        """T-H1's other half, and the one that distinguishes 2.5D from 2D.

        Detecting the deck is easy.  Keeping the road under it classified
        DRIVABLE is the behaviour a 2D grid cannot produce, and it is the
        claim in the deck.
        """
        from avr25d.perception.labelmap import DRIVABLE
        from avr25d.synth import load_scene

        cells = CellGrid(grid)
        scene = load_scene("S3_overhang")
        xyz, _ = hazard._frame(
            scene, hazard.sensor_from_config(cfg), cfg, grid, cells, 0.0
        )
        gt = scene.ground_truth["hazards"][0]
        (x0, y0), (x1, y1) = gt["footprint_xy_m"]

        occ = np.flatnonzero(cells.count > 0)
        xy = grid.cell_centres(occ)
        under = occ[(xy[:, 0] >= x0) & (xy[:, 0] <= x1)
                    & (xy[:, 1] >= y0) & (xy[:, 1] <= y1)]
        drivable = int(np.count_nonzero(cells.class_id[under] == DRIVABLE))
        assert drivable > 300, (
            f"only {drivable} of {under.size} cells under the deck are "
            "DRIVABLE — the road has been lost, which is the 2D failure"
        )

    def test_per_cell_clearance_yield_is_recorded(self, scored):
        """FR-13's literal per-cell form is measurable on almost nothing.

        A beam that strikes the deck underside and a beam that strikes the road
        beneath it land at different ranges, so they land in different rings and
        almost never share a cell.  That is a property of the sensor, not a bug,
        and §11.4 has to state it rather than quietly reporting the clearance
        another way.  The test pins the fact so the number cannot silently
        change meaning.
        """
        row = _row(scored, "S3_overhang")
        assert "clearance_cells_with_both" in row
        assert row["clearance_cells_with_both"] < 10, (
            "per-cell clearance now has real yield — good news, but §11.4's "
            "note and this test need rewriting to match"
        )

    def test_2d_grid_loses_the_road(self, scored):
        """PS-10, measured: the deck's returns block the road beneath it."""
        row = _row(scored, "S3_overhang")
        cf = row["counterfactual_2d"]
        assert cf["blocked_fraction"] >= 0.99
        assert cf["hazard_representable"] is False


# ---------------------------------------------------------------------------
# T-H3 — step height
# ---------------------------------------------------------------------------

class TestStepHeight:

    def test_height_within_3_cm(self, scored):
        """T-H3: kerb height within 0.03 m of the CSV's 0.15 m."""
        row = _row(scored, "S4_curb")
        assert row["true_value"] == 0.15
        assert row["error"] <= 0.03, (
            f"measured {row['measured']} m against a true 0.15 m"
        )

    def test_step_flag_fires_along_the_kerb(self, scored):
        row = _row(scored, "S4_curb")
        assert row["cells_flagged"] >= 100, (
            f"STEP on only {row['cells_flagged']} of "
            f"{row['cells_covering']} kerb cells"
        )


# ---------------------------------------------------------------------------
# S5 — the moving object, shared with T-D2
# ---------------------------------------------------------------------------

class TestTrackRow:

    def test_speed_within_half_a_metre_per_second(self, scored):
        row = _row(scored, "S5_crossing_truck")
        assert row["true_value"] == 8.0
        assert row["error"] <= 0.5, (
            f"tracked {row['measured']} m/s against a true 8.0 m/s"
        )

    def test_one_id_for_the_whole_crossing(self, scored):
        row = _row(scored, "S5_crossing_truck")
        assert row["id_stable"], f"track ids seen: {row['track_ids']}"


# ---------------------------------------------------------------------------
# The adversarial scenes (Days 9 and 10)
# ---------------------------------------------------------------------------

class TestOccludedPothole:
    """S6 — S2 with 53% of the pit in a stopped car's shadow, same 12 m range.

    The scene exists to separate two things that a first draft conflated: what
    occlusion costs, and what *range* costs.  A pit is measurable only where a
    beam reaches its floor, and the grazing angle falls from 8.1 deg at 12 m to
    6.1 deg at 16 m — so the first S6, at 16 m, measured a 0.14 m error that had
    nothing to do with the occluder.  Range is held at S2's, and these tests
    assert the comparison stays controlled.
    """

    def test_range_is_held_at_s2s(self, scored):
        """Held constant on purpose; if it drifts the comparison is void."""
        from avr25d.synth import load_scene
        r2 = load_scene("S2_pothole").ground_truth["hazards"][0]["range_m"]
        r6 = load_scene("S6_occluded_pothole").ground_truth["hazards"][0]["range_m"]
        assert abs(r6 - r2) < 0.05, (
            f"S6 sits at {r6:.2f} m and S2 at {r2:.2f} m — the scenes now "
            "differ in range as well as occlusion and neither number means "
            "what it says"
        )

    def test_occlusion_actually_occludes(self, scored):
        """Half the covering cells should be gone relative to S2."""
        s2 = _row(scored, "S2_pothole")
        s6 = _row(scored, "S6_occluded_pothole")
        assert s6["cells_covering"] < s2["cells_covering"], (
            "S6 sees as much of the pit as S2 — the occluder is not occluding"
        )

    def test_depth_survives_the_occlusion(self, scored):
        """The finding: depth needs one beam on the floor, not many.

        Detection density halves and the depth estimate does not move, because
        depth is set by the deepest return that exists rather than by how many
        returns there are.
        """
        s6 = _row(scored, "S6_occluded_pothole")
        assert s6["error"] <= 0.05, (
            f"depth degraded to {s6['measured']} m under occlusion"
        )
        assert s6["detection_rate_below_reference"] == 1.0


class TestTunnelWithCurb:
    """S7 — a 3.40 m tunnel with a 0.15 m kerb inside it.

    Two hazards of different kinds in one place, and a 0.10 m margin against the
    3.50 m vehicle height that only a centimetre-accurate measurement can call.
    """

    @staticmethod
    def _rows(scored):
        return {r["tag"]: r for r in scored["scenes"] if r["scene"] == "S7_tunnel_curb"}

    def test_both_hazards_are_scored(self, scored):
        rows = self._rows(scored)
        assert set(rows) == {"clearance", "step"}, (
            "a scene with an overhead constraint and a surface constraint must "
            "report both; collapsing them is the failure the scene tests for"
        )

    def test_clearance_resolves_the_ten_centimetre_margin(self, scored, cfg):
        """3.40 m tunnel, 3.50 m vehicle — the error must be far below 0.10 m."""
        row = self._rows(scored)["clearance"]
        margin = float(cfg.vehicle.height) - 3.40
        assert row["error"] < margin / 5.0, (
            f"clearance error {row['error']} m against a {margin:.2f} m margin "
            "— the blocked/clear call is not safely resolvable"
        )

    def test_kerb_height_holds_at_tunnel_range(self, scored):
        """T-H3's tolerance, 30-60 m out instead of S4's near field."""
        row = self._rows(scored)["step"]
        assert row["error"] <= 0.03, (
            f"kerb measured {row['measured']} m against a true 0.15 m"
        )

    def test_detection_density_is_what_range_costs(self, scored):
        """Accuracy holds and detection thins — the two must not be confused.

        A 0.15 m face subtends 0.21 deg at 40 m against a 0.4375 deg beam
        pitch, so most beams miss the kerb entirely.  §11.4 reports the sparse
        cell count next to the accurate height precisely so nobody reads the
        good error as good coverage.
        """
        s4 = _row(scored, "S4_curb")
        s7 = self._rows(scored)["step"]
        assert s7["cells_covering"] < s4["cells_covering"] / 10, (
            "the tunnel kerb is no longer sparsely sampled — the scene has "
            "stopped being the far-field test it was built as"
        )
        assert s7["error"] <= s4["error"] * 3, (
            "geometric accuracy degraded with range as well as density, which "
            "contradicts the claim §11.4 makes about the two"
        )


# ---------------------------------------------------------------------------
# Aggregate + reproducibility (T-B5)
# ---------------------------------------------------------------------------

class TestAggregate:

    def test_every_scene_produces_a_row(self, scored, cfg):
        from avr25d.synth.scenegen import list_scenes
        names = {p.stem for p in list_scenes()}
        assert {r["scene"] for r in scored["scenes"]} == names

    def test_no_false_positives_anywhere(self, scored):
        assert scored["false_positives"] == 0

    def test_all_seven_scenes_are_present(self, scored):
        """Five from §9.3 plus the two adversarial ones from Days 9 and 10."""
        assert scored["n_scenes"] == 7

    def test_every_geometric_error_is_within_its_tolerance(self, scored):
        """One assertion over the whole of §11.4, so a new scene cannot be
        added with a failing row and go unnoticed."""
        tolerance = {"pothole": 0.05, "clearance": 0.05, "step": 0.03,
                     "track": 0.5}
        for row in scored["scenes"]:
            tol = tolerance.get(row["tag"])
            if tol is None:
                continue
            assert row["error"] <= tol, (
                f"{row['scene']}/{row['tag']}: error {row['error']} exceeds "
                f"its {tol} tolerance"
            )

    def test_repeat_run_is_identical(self, cfg, grid):
        """T-B5: the same input gives the same numbers.

        The scenes are seeded, so a difference here is non-determinism in the
        grid or the estimators, which would make every §11.4 figure unciteable.
        """
        a = hazard.score_scene("S4_curb", cfg, grid)
        b = hazard.score_scene("S4_curb", cfg, grid)
        assert a == b
