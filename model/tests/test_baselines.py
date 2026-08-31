"""Memory baselines B0-B4 and the AVR-25D models (PRD §10.1).  T-B1.

The point of these tests is that the memory argument in the deck is *auditable
arithmetic*, not a measurement anyone has to trust.  Every documented figure in
PRD §10.1 — 400.0 MB, 3.20 GB, 17.64 MB, 22.67x — is asserted here against the
closed form, so if someone edits a constant the table and the code disagree
loudly instead of quietly.
"""

from __future__ import annotations

import numpy as np
import pytest

from avr25d.bench import baselines as bl


# --- the documented closed forms ------------------------------------------

def test_bytes_per_cell_matches_the_cell_schema():
    """25 B/cell is the sum of the §6.2 field widths, not a chosen number."""
    assert bl.BYTES_PER_CELL == 25
    assert bl.CELL_FIELD_BYTES == (4, 4, 4, 4, 4, 1, 1, 1, 2)
    assert sum(bl.CELL_FIELD_BYTES) == bl.BYTES_PER_CELL


def test_b0_raw_scan_is_seventeen_bytes_per_point():
    m = bl.b0_raw_scan(125_718)
    assert m.n_cells == 0                      # a scan has no cells
    assert m.n_points == 125_718
    assert m.bytes == 125_718 * 17


def test_b1_dense_uniform_25d_is_the_documented_400_MB():
    m = bl.b1_dense_uniform_25d()
    assert m.n_cells == 16_000_000             # 4000 x 4000 @ 5 cm
    assert m.bytes == 400_000_000
    assert m.megabytes == pytest.approx(400.0, abs=0.005)


def test_b2_sparse_uniform_25d_pays_a_four_byte_key():
    m = bl.b2_sparse_uniform_25d(1_000)
    assert m.n_cells == 1_000
    assert m.bytes == 1_000 * (25 + 4)


def test_b3_dense_uniform_3d_is_the_documented_3_20_GB():
    m = bl.b3_dense_uniform_3d()
    assert m.n_cells == 3_200_000_000          # 4000 x 4000 x 200 @ 5 cm
    assert m.bytes == 3_200_000_000            # 1 byte per voxel
    assert m.gigabytes == pytest.approx(3.20, abs=0.005)


def test_b4_sparse_voxel_3d_pays_an_eight_byte_key_and_four_byte_payload():
    m = bl.b4_sparse_voxel_3d(1_000)
    assert m.bytes == 1_000 * 12


def test_avr_dense_is_the_documented_17_64_MB():
    m = bl.avr_dense(705_771)
    assert m.n_cells == 705_771
    assert m.bytes == 17_644_275
    assert m.megabytes == pytest.approx(17.64, abs=0.005)


def test_avr_occupied_pays_the_same_key_as_b2():
    m = bl.avr_occupied(1_000)
    assert m.bytes == 1_000 * (25 + 4)


def test_every_model_reports_integer_bytes():
    """Auditable arithmetic: no float rounding anywhere in the byte counts."""
    models = [
        bl.b0_raw_scan(100), bl.b1_dense_uniform_25d(), bl.b2_sparse_uniform_25d(100),
        bl.b3_dense_uniform_3d(), bl.b4_sparse_voxel_3d(100),
        bl.avr_dense(705_771), bl.avr_occupied(100),
    ]
    for m in models:
        assert isinstance(m.bytes, int), m.name
        assert isinstance(m.n_cells, int), m.name


# --- the headline ratio ----------------------------------------------------

def test_cell_reduction_against_b1_is_the_documented_22_67x():
    """PRD §10.1's headline structural claim."""
    assert bl.cell_reduction_vs_b1(705_771) == pytest.approx(22.67, abs=0.005)


# --- occupancy counting from a raw point cloud -----------------------------

def test_uniform_occupancy_counts_distinct_5cm_columns():
    """Three points, two of which share a 5 cm column -> 2 occupied cells."""
    xyz = np.array([
        [1.000, 1.000, 0.0],
        [1.020, 1.010, 5.0],   # same 5 cm column as the first, different height
        [2.000, 1.000, 0.0],
    ], dtype=np.float32)
    assert bl.count_uniform_occupancy(xyz, res_m=0.05) == 2


def test_voxel_occupancy_separates_what_the_25d_column_merges():
    """The same three points: 2.5D sees 2 columns, 3D sees 3 voxels."""
    xyz = np.array([
        [1.000, 1.000, 0.0],
        [1.020, 1.010, 5.0],
        [2.000, 1.000, 0.0],
    ], dtype=np.float32)
    assert bl.count_voxel_occupancy(xyz, res_m=0.05) == 3


def test_occupancy_excludes_points_outside_the_100m_envelope():
    """AVR-25D only covers r <= 100 m, so the baselines must be scored on the
    same points or the comparison is not like for like."""
    xyz = np.array([
        [10.0, 0.0, 0.0],       # inside
        [99.0, 0.0, 0.0],       # inside
        [101.0, 0.0, 0.0],      # outside the envelope
        [80.0, 80.0, 0.0],      # r = 113 m: inside the 200x200 square, outside the circle
    ], dtype=np.float32)
    assert bl.count_uniform_occupancy(xyz, res_m=0.05) == 2
    assert bl.count_voxel_occupancy(xyz, res_m=0.05) == 2


def test_occupancy_of_an_empty_cloud_is_zero():
    empty = np.zeros((0, 3), dtype=np.float32)
    assert bl.count_uniform_occupancy(empty) == 0
    assert bl.count_voxel_occupancy(empty) == 0


def test_voxel_occupancy_clamps_to_the_ten_metre_height_band():
    """B3's envelope is 200 x 200 x 10 m.  A return above that band is outside
    the baseline's own definition and must not be counted."""
    xyz = np.array([
        [1.0, 1.0, 0.0],
        [1.0, 1.0, 40.0],       # far above the 10 m band
    ], dtype=np.float32)
    assert bl.count_voxel_occupancy(xyz, res_m=0.05) == 1


def test_uniform_occupancy_never_exceeds_the_point_count():
    rng = np.random.default_rng(20260830)
    xyz = rng.uniform(-50, 50, size=(5_000, 3)).astype(np.float32)
    n = bl.count_uniform_occupancy(xyz)
    assert 0 < n <= 5_000


# --- the assembled comparison ---------------------------------------------

def test_compare_returns_every_baseline_and_is_json_serialisable():
    import json

    table = bl.compare(
        n_points=125_718,
        n_occ_uniform=48_000,
        n_vox_occ=61_000,
        n_cells_adaptive=705_771,
        n_occ_adaptive=31_000,
    )
    names = [row["name"] for row in table["models"]]
    assert names == ["B0", "B1", "B2", "B3", "B4", "AVR-25D dense", "AVR-25D occupied"]
    assert table["cell_reduction_vs_b1"] == pytest.approx(22.67, abs=0.005)
    json.dumps(table)   # must not raise — this lands in results.json


def test_compare_states_where_a_sparse_baseline_wins():
    """PRD §10.1 promises we say so when B4 beats the dense ring table.  A
    claim the deck makes must be one the harness can actually produce."""
    table = bl.compare(
        n_points=125_718,
        n_occ_uniform=48_000,
        n_vox_occ=61_000,          # 61_000 * 12 = 732 kB, far below 17.64 MB
        n_cells_adaptive=705_771,
        n_occ_adaptive=31_000,
    )
    assert table["b4_smaller_than_avr_dense"] is True
    assert table["n_occ_adaptive_below_n_occ_uniform"] is True
