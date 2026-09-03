"""results.json -> docs/RESULTS.md, the PRD §11 tables.  §6.11, T-B5.

PRD §11 opens with a rule: *"A number that has not been measured does not go in
a table, a slide, or a sentence."*  Most of these tests exist to make that rule
mechanical, because the failure mode is silent — a renderer that prints 0.000
for a section nobody ran produces a table that looks measured and is not.
"""

from __future__ import annotations

import pytest

from avr25d.bench import report as rp


def _results():
    """A minimal but complete-enough results document."""
    return {
        "meta": {"generated": "2026-08-31T10:00:00Z", "git_commit": "abc1234"},
        "memory": {
            "models": [
                {"name": "B1", "n_cells": 16_000_000, "bytes": 400_000_000,
                 "megabytes": 400.0, "n_points": 0},
                {"name": "B4", "n_cells": 61_000, "bytes": 732_000,
                 "megabytes": 0.732, "n_points": 0},
                {"name": "AVR-25D dense", "n_cells": 705_771, "bytes": 17_644_275,
                 "megabytes": 17.644275, "n_points": 0},
            ],
            "cell_reduction_vs_b1": 22.6699,
        },
        "latency": {
            "n_frames": 271,
            "meets_fr32": True,
            "end_to_end": {"n": 271, "mean_ms": 60.2, "median_ms": 58.1,
                           "p95_ms": 70.1, "max_ms": 135.1, "min_ms": 50.0},
            "stages": {
                "segment": {"n": 271, "mean_ms": 58.0, "median_ms": 57.0,
                            "p95_ms": 69.0, "max_ms": 134.0, "min_ms": 49.0},
            },
        },
        "accuracy": {
            "overall": {"n_points": 125_718, "miou": 0.823, "accuracy": 0.9203,
                        "iou": {"DRIVABLE": 0.9, "STATIC_OBSTACLE": 0.7,
                                "DYNAMIC_OBJECT": 0.6}},
            "bins": {
                "0-10m": {"n_points": 40_000, "miou": 0.29, "accuracy": 0.5,
                          "iou": {"DRIVABLE": 0.6, "STATIC_OBSTACLE": 0.2,
                                  "DYNAMIC_OBJECT": 0.1}},
                "10-30m": {"n_points": 50_000, "miou": 0.291, "accuracy": 0.5,
                           "iou": {"DRIVABLE": 0.6, "STATIC_OBSTACLE": 0.2,
                                   "DYNAMIC_OBJECT": 0.1}},
                "30-60m": {"n_points": 30_000, "miou": 0.196, "accuracy": 0.4,
                           "iou": {"DRIVABLE": 0.5, "STATIC_OBSTACLE": 0.1,
                                   "DYNAMIC_OBJECT": 0.05}},
                "60-100m": {"n_points": 0, "miou": None, "accuracy": None,
                            "iou": {"DRIVABLE": None, "STATIC_OBSTACLE": None,
                                    "DYNAMIC_OBJECT": None}},
            },
        },
    }


# --- the measured/not-measured rule ---------------------------------------

def test_a_missing_section_is_marked_not_measured():
    md = rp.render({"meta": {}})
    assert rp.NOT_MEASURED in md
    assert "0.000" not in md


def test_a_missing_section_never_renders_a_zero():
    """The dangerous failure: a table that looks measured and is not."""
    md = rp.render({"meta": {}})
    for section in ("11.1", "11.2", "11.3", "11.4", "11.5"):
        assert section in md


def test_an_empty_bin_renders_a_dash_not_a_zero():
    """60-100 m had no points.  '0.000' there would be a claim; '—' is not."""
    md = rp.render(_results())
    far = [ln for ln in md.splitlines() if ln.startswith("| 60–100 m")]
    assert len(far) == 1
    assert "0.000" not in far[0]
    assert "—" in far[0]


def test_a_bin_with_points_but_nothing_labelled_says_why():
    """Sequence 04 has 20,943 points beyond 60 m and every one is ground-truth
    VOID.  Rendering a bare '—' invites 'so is your accuracy zero out there?',
    and the answer — the dataset labels nothing at that range — is a much
    better one than the question assumes."""
    r = _results()
    r["accuracy"]["bins"]["60-100m"] = {
        "n_points": 20_943, "n_points_scored": 0, "miou": None,
        "accuracy": None,
        "iou": {"DRIVABLE": None, "STATIC_OBSTACLE": None, "DYNAMIC_OBJECT": None},
        "truth_share": {"VOID": 1.0},
    }
    md = rp.render(r)
    assert "unlabelled" in md
    assert "20,943" in md


def test_no_such_note_when_every_bin_has_labelled_points():
    md = rp.render(_results())
    assert "unlabelled" not in md


def test_no_prd_placeholder_survives_where_a_value_exists():
    md = rp.render(_results())
    miou_row = [ln for ln in md.splitlines() if ln.startswith("| 0–10 m")][0]
    assert "_measured_" not in miou_row
    assert "0.290" in miou_row


# --- the tables ------------------------------------------------------------

def test_memory_table_carries_the_documented_constants():
    md = rp.render(_results())
    assert "16,000,000" in md
    assert "705,771" in md
    assert "22.67×" in md


def test_latency_table_reports_all_four_fr32_statistics():
    md = rp.render(_results())
    row = [ln for ln in md.splitlines() if "End-to-end" in ln][0]
    for value in ("60.2", "58.1", "70.1", "135.1"):
        assert value in row


def test_a_latency_run_below_200_scans_is_flagged_in_the_report():
    """FR-32 requires >=200 scans.  A 40-scan run must not read as compliant."""
    r = _results()
    r["latency"]["n_frames"] = 40
    r["latency"]["meets_fr32"] = False
    md = rp.render(r)
    assert "FR-32" in md
    assert "40" in md


def test_accuracy_table_has_a_row_per_bin_plus_overall():
    md = rp.render(_results())
    for name in ("0–10 m", "10–30 m", "30–60 m", "60–100 m", "Overall"):
        assert any(ln.startswith(f"| {name}") or ln.startswith(f"| **{name}**")
                   for ln in md.splitlines()), name


def test_report_states_the_commit_it_was_generated_from():
    """NFR-5: a number in the deck has to be traceable to a build."""
    md = rp.render(_results())
    assert "abc1234" in md


# --- T-B5: reproducibility -------------------------------------------------

def test_rendering_is_deterministic():
    r = _results()
    assert rp.render(r) == rp.render(r)


def test_rendering_does_not_mutate_its_input():
    r = _results()
    before = repr(r)
    rp.render(r)
    assert repr(r) == before


def test_dict_ordering_does_not_change_the_output():
    """Two results documents differing only in key insertion order must render
    identically, or 'reproducible' means nothing."""
    a = _results()
    b = {k: a[k] for k in reversed(list(a))}
    assert rp.render(a) == rp.render(b)


# --- formatting ------------------------------------------------------------

def test_iou_values_render_to_three_decimals():
    md = rp.render(_results())
    assert "0.823" in md


def test_latency_values_render_to_one_decimal_with_units_in_the_header():
    md = rp.render(_results())
    assert "58.1" in md
    assert "ms" in md


@pytest.mark.parametrize("value, expected", [
    (None, "—"),
    (0.0, "0.000"),
    (0.8234, "0.823"),
    (1.0, "1.000"),
])
def test_number_formatting_is_explicit_about_none(value, expected):
    assert rp.fmt(value, 3) == expected


# ---------------------------------------------------------------------------
# §11.3.1 — per-sequence variance (Day 11)
# ---------------------------------------------------------------------------

def _seq_block(miou, acc, rec, ms, n=100):
    return {
        "n_scans": n,
        "accuracy": {"overall": {"miou": miou, "accuracy": acc}},
        "object_recall": {"overall": {"recall": rec}},
        "latency": {"end_to_end": {"median_ms": ms}},
    }


class TestVarianceSection:

    def test_absent_when_not_measured(self):
        out = rp.render_variance({})
        assert rp.NOT_MEASURED in out

    def test_one_sequence_says_so_rather_than_printing_a_zero_spread(self):
        """A single sequence has zero spread and that is not a result.

        Printing 0.0 % here would read as perfect generalisation from one
        sequence, which is the exact opposite of what one sequence shows.
        """
        out = rp.render_variance({
            "per_sequence": {"04": _seq_block(0.8, 0.9, 0.9, 5.0)},
            "variance": {"sequences": ["04"], "miou": None},
        })
        assert "0.0 %" not in out
        assert "at least two" in out

    def test_renders_a_row_per_sequence_and_the_spread(self):
        results = {
            "per_sequence": {
                "00": _seq_block(0.890, 0.938, 0.934, 5.1, n=400),
                "04": _seq_block(0.845, 0.941, 0.914, 5.3, n=271),
                "05": _seq_block(0.864, 0.923, 0.924, 5.9, n=300),
            },
            "variance": {
                "sequences": ["00", "04", "05"],
                "miou": {"n": 3, "mean": 0.8663, "sd": 0.0226,
                         "min": 0.845, "max": 0.890, "spread_pct": 2.61},
            },
        }
        out = rp.render_variance(results)
        for name in ("00", "04", "05"):
            assert f"| {name} |" in out
        assert "0.866" in out and "0.023" in out
        assert "2.6 %" in out

    def test_sequence_rows_are_sorted_not_hash_ordered(self):
        """T-B5: the report must render identically run to run."""
        results = {
            "per_sequence": {
                "05": _seq_block(0.864, 0.923, 0.924, 5.9),
                "00": _seq_block(0.890, 0.938, 0.934, 5.1),
                "04": _seq_block(0.845, 0.941, 0.914, 5.3),
            },
            "variance": {"sequences": ["05", "00", "04"], "miou": None},
        }
        out = rp.render_variance(results)
        assert out.index("| 00 |") < out.index("| 04 |") < out.index("| 05 |")


# ---------------------------------------------------------------------------
# §11.4 — hazards
# ---------------------------------------------------------------------------

class TestHazardSection:

    def test_absent_when_not_measured(self):
        out = rp.render_hazards({"hazards": None})
        assert rp.NOT_MEASURED in out

    def test_renders_error_detection_and_the_2d_counterfactual(self):
        out = rp.render_hazards({"hazards": {
            "scenes": [{
                "scene": "S2_pothole", "hazard": "pothole depth",
                "true_value": 0.22, "measured": 0.2092, "error": 0.0108,
                "cells_covering": 27, "cells_flagged": 21,
                "detection_rate": 0.7778,
                "counterfactual_2d": {
                    "blocked_fraction": 0.0, "hazard_representable": False,
                    "verdict": "free space",
                },
            }],
            "max_error_m": 0.0108, "false_positives": 0,
        }})
        assert "0.2092" in out and "0.0108" in out
        assert "21 / 27" in out
        assert "not representable" in out
        assert "False positives" in out

    def test_a_false_positive_count_is_not_hidden(self):
        out = rp.render_hazards({"hazards": {
            "scenes": [], "max_error_m": None, "false_positives": 7,
        }})
        assert "7" in out
