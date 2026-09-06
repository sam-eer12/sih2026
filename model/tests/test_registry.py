"""The FR-40 ``scenes`` collection — T-W5, from the model side.

T-W5 reads "each scene has a ``scenes`` document, and its ``groundTruth``
values equal the CSV specification exactly".  Its dashboard half belongs to the
route handler that seeds Mongo; its *exactness* half belongs here, because the
document is generated here and a seed script cannot check what it was handed.

So these tests re-parse the scene CSVs with ``csv.DictReader`` and recompute
each hazard value from the raw row, deliberately not going through
``scenegen``.  Asserting the export matches the parser it was built from would
only prove the code agrees with itself; the claim FR-40 makes is that the
number in Mongo is the number in the spreadsheet.

The round-trip test carries the other half of FR-40 — "the hazard-preservation
comparison reads truth from the same store the dashboard reads".  A document
that reconstructs the exact dict ``bench/hazard.py`` scores against is what
makes that one store rather than two that happen to agree today.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

from avr25d.synth.raycast import Primitive, Scene
from avr25d.synth.registry import (
    SCHEMA_VERSION,
    build_registry,
    flat_ground_truth,
    from_document,
    to_document,
)
from avr25d.synth.scenegen import ground_truth, list_scenes, load_scene

#: The numbers PRD §9.3 and §11.4 quote, written out by hand.  If a CSV is
#: edited, this table is the second signature that has to change with it.
STATED = {
    "S1_flat_road":        {},
    "S2_pothole":          {"potholeDepth": 0.22},
    "S3_overhang":         {"clearance": 3.10},
    "S4_curb":             {"curbHeight": 0.15},
    "S5_crossing_truck":   {"truckSpeed": 8.0},
    "S6_occluded_pothole": {"potholeDepth": 0.22},
    "S7_tunnel_curb":      {"clearance": 3.40, "curbHeight": 0.15},
}

FR40_KEYS = {"potholeDepth", "clearance", "curbHeight", "truckSpeed"}


@pytest.fixture(scope="module")
def registry():
    return build_registry()


@pytest.fixture(scope="module")
def documents(registry):
    return {doc["name"]: doc for doc in registry["scenes"]}


# ---------------------------------------------------------------------------
# The CSV, read independently of scenegen
# ---------------------------------------------------------------------------

def _csv_rows(path: Path) -> list[dict]:
    lines = [
        line for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return list(csv.DictReader(lines, skipinitialspace=True))


def _expected_flat(path: Path) -> dict:
    """The FR-40 four, recomputed from the raw CSV row that specifies each."""
    flat: dict[str, float] = {}
    for row in _csv_rows(path):
        tag = (row.get("hazard") or "").strip()
        z, sz = float(row["z"]), float(row["sz"])
        if tag == "pothole":
            flat["potholeDepth"] = sz                    # the pit's own depth
        elif tag == "clearance":
            flat["clearance"] = z - sz / 2               # underside of the structure
        elif tag == "step":
            flat["curbHeight"] = z + sz / 2              # top of the kerb
        elif tag == "track":
            flat["truckSpeed"] = math.hypot(
                float(row.get("vx") or 0.0), float(row.get("vy") or 0.0)
            )
    return flat


# ---------------------------------------------------------------------------
# T-W5
# ---------------------------------------------------------------------------

def test_every_scene_has_exactly_one_document(documents):
    assert set(documents) == {p.stem for p in list_scenes()}
    assert len(documents) == 7


def test_documents_carry_the_fr40_shape(documents):
    for name, doc in documents.items():
        assert doc["_id"] == name == doc["name"]
        assert doc["schemaVersion"] == SCHEMA_VERSION
        assert set(doc["groundTruth"]) == FR40_KEYS, name
        assert doc["primitives"], name
        assert doc["nPrimitives"] == len(doc["primitives"]), name


def test_ground_truth_equals_the_csv_specification_exactly(documents):
    """T-W5 — recomputed from the raw CSV, not from ``scenegen``."""
    for path in list_scenes():
        expected = _expected_flat(path)
        exported = documents[path.stem]["groundTruth"]

        for key in FR40_KEYS:
            want = expected.get(key)
            if want is None:
                assert exported[key] is None, (path.stem, key)
            else:
                assert exported[key] == pytest.approx(want), (path.stem, key)


def test_ground_truth_equals_the_numbers_the_prd_quotes(documents):
    for name, stated in STATED.items():
        exported = documents[name]["groundTruth"]
        for key in FR40_KEYS:
            if key in stated:
                assert exported[key] == pytest.approx(stated[key]), (name, key)
            else:
                assert exported[key] is None, (name, key)


def test_primitives_are_the_csv_rows(documents):
    """Column names, order and values — the document mirrors the spreadsheet."""
    for path in list_scenes():
        rows = _csv_rows(path)
        exported = documents[path.stem]["primitives"]
        assert len(exported) == len(rows), path.stem

        for row, prim in zip(rows, exported):
            assert list(prim) == [
                "type", "x", "y", "z", "sx", "sy", "sz",
                "class", "vx", "vy", "hazard", "note",
            ]
            assert prim["type"] == row["type"].strip()
            assert prim["class"] == int(row["class"])
            assert prim["hazard"] == (row.get("hazard") or "").strip()
            assert prim["note"] == (row.get("note") or "").strip()
            for col in ("x", "y", "z", "sx", "sy", "sz", "vx", "vy"):
                assert prim[col] == pytest.approx(float(row.get(col) or 0.0)), \
                    (path.stem, col)


def test_source_sha256_identifies_the_csv_that_produced_the_document(documents):
    import hashlib

    for path in list_scenes():
        source = documents[path.stem]["source"]
        assert source["csv"] == path.name
        assert source["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# One store, not two that agree today
# ---------------------------------------------------------------------------

def test_document_round_trips_to_the_ground_truth_bench_scores_against():
    for path in list_scenes():
        scene = load_scene(path)
        assert from_document(to_document(scene, path)) == scene.ground_truth


def test_round_trip_survives_a_json_round_trip():
    """Mongo hands back what a JSON codec hands back — tuples become lists."""
    for path in list_scenes():
        scene = load_scene(path)
        doc = json.loads(json.dumps(to_document(scene, path)))
        assert from_document(doc) == scene.ground_truth


def test_every_key_is_camel_case_and_bson_safe(registry):
    """No dots and no leading ``$``; ``_id`` is the one underscore Mongo defines."""

    def walk(value, path="registry"):
        if isinstance(value, dict):
            for key, sub in value.items():
                assert "." not in key and not key.startswith("$"), f"{path}.{key}"
                assert key == "_id" or "_" not in key, f"{path}.{key}"
                walk(sub, f"{path}.{key}")
        elif isinstance(value, list):
            for i, sub in enumerate(value):
                walk(sub, f"{path}[{i}]")

    walk(registry)


def test_registry_is_json_serialisable(registry):
    json.dumps(registry)        # raises on a numpy scalar or a Path


def test_registry_is_deterministic():
    """No timestamp, no ordering wobble — regenerating is a no-op diff."""
    first = json.dumps(build_registry(), indent=2)
    second = json.dumps(build_registry(), indent=2)
    assert first == second
    assert "generatedAt" not in first and "timestamp" not in first


def test_scenes_are_in_name_order(registry):
    names = [doc["name"] for doc in registry["scenes"]]
    assert names == sorted(names)


# ---------------------------------------------------------------------------
# What the flat shape cannot hold
# ---------------------------------------------------------------------------

def _pothole(y: float) -> Primitive:
    return Primitive(
        kind="pit", x=12.0, y=y, z=-0.11, sx=1.4, sy=1.0, sz=0.22,
        class_id=2, hazard="pothole", note="",
    )


def test_two_hazards_of_one_kind_are_refused_rather_than_summarised():
    scene = Scene(name="two_potholes", primitives=(_pothole(-0.5), _pothole(2.0)))
    with pytest.raises(ValueError, match="groundTruth.potholeDepth"):
        flat_ground_truth(ground_truth(scene), scene.name)


def test_a_hazard_tag_with_no_summary_key_is_refused():
    gt = {"scene": "made_up", "hazards": [{"tag": "landslide", "depth_m": 1.0}]}
    with pytest.raises(ValueError, match="no FR-40 summary key"):
        flat_ground_truth(gt)


def test_a_named_subset_exports_only_those_scenes():
    registry = build_registry(["S2_pothole", "S7_tunnel_curb"])
    assert [d["name"] for d in registry["scenes"]] == ["S2_pothole", "S7_tunnel_curb"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_writes_a_registry_that_reloads(tmp_path, capsys):
    from avr25d.synth.registry import _main

    out = tmp_path / "nested" / "scenes_registry.json"
    assert _main(["--out", str(out)]) == 0

    written = json.loads(out.read_text(encoding="utf-8"))
    assert len(written["scenes"]) == 7
    assert written["collection"] == "scenes"
    assert "7 document(s)" in capsys.readouterr().out


def test_cli_stdout_prints_the_same_json(capsys):
    from avr25d.synth.registry import _main

    assert _main(["S2_pothole", "--stdout"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["scenes"][0]["groundTruth"]["potholeDepth"] == 0.22
