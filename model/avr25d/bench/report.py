"""``results.json`` -> ``docs/RESULTS.md``.  §6.11, PRD §11, NFR-5.  T-B5.

PRD §11 opens with a rule that this module exists to enforce mechanically:

    A number that has not been measured does not go in a table, a slide, or a
    sentence.

So every cell here is either a measured value or an explicit marker.  There is
no code path that prints ``0.000`` because a section was absent, and no default
that quietly turns a missing measurement into a plausible one.  A section that
did not run says so, in the table, where anyone reading the table will see it.

Determinism is a requirement, not a nicety (T-B5): the report is regenerated on
Day 12 and the numbers in the deck are cross-checked against it.  Rendering
therefore reads only from the results document, sorts nothing by hash order,
and never mutates its input.
"""

from __future__ import annotations

from typing import Any

#: What an unmeasured section says.  One string, used everywhere, so it can be
#: grepped for before the deck is filled.
NOT_MEASURED = "_not measured_"

#: What an empty cell inside a measured section says — the 60-100 m bin with
#: no returns is a real observation, not a missing one.
EMPTY = "—"


def fmt(value: Any, places: int = 3) -> str:
    """A number, or ``EMPTY`` for ``None``.  Never a fabricated zero."""
    if value is None:
        return EMPTY
    return f"{float(value):.{places}f}"


def _int(value: Any) -> str:
    return EMPTY if value is None else f"{int(value):,}"


def _get(results: dict, key: str) -> dict | None:
    section = results.get(key)
    return section if isinstance(section, dict) and section else None


# --- §11.1 --------------------------------------------------------------

def render_memory(results: dict) -> str:
    head = "### 11.1 Representation and memory\n"
    mem = _get(results, "memory")
    if mem is None:
        return head + f"\n{NOT_MEASURED} — run `make bench`.\n"

    by_name = {m["name"]: m for m in mem.get("models", [])}
    b1 = by_name.get("B1", {})
    b4 = by_name.get("B4", {})
    avr = by_name.get("AVR-25D dense", {})
    occ = by_name.get("AVR-25D occupied", {})
    b2 = by_name.get("B2", {})
    ratio = mem.get("cell_reduction_vs_b1")

    rows = [
        "| Metric | B1 dense uniform 2.5D | B4 sparse 3D voxel | AVR-25D | Ratio |",
        "|---|---|---|---|---|",
        f"| Total cells (full envelope) | {_int(b1.get('n_cells'))} | {EMPTY} | "
        f"{_int(avr.get('n_cells'))} | **{fmt(ratio, 2)}×** |",
        f"| Occupied cells / frame | {_int(b2.get('n_cells'))} | "
        f"{_int(b4.get('n_cells'))} | {_int(occ.get('n_cells'))} | {EMPTY} |",
        f"| Bytes / frame | {fmt(b1.get('megabytes'), 1)} MB | "
        f"{fmt(b4.get('megabytes'), 3)} MB | "
        f"{fmt(avr.get('megabytes'), 2)} MB dense | {EMPTY} |",
    ]

    rss = mem.get("peak_rss_mb")
    rows.append(
        f"| Peak RSS | {EMPTY} | {EMPTY} | "
        f"{fmt(rss, 1) + ' MB' if rss is not None else NOT_MEASURED} | {EMPTY} |"
    )

    note = ""
    if mem.get("peak_rss_scope"):
        note += f"\nPeak RSS is the {mem['peak_rss_scope']}.\n"
    if mem.get("b4_smaller_than_avr_dense"):
        note = (
            "\n**B4 is smaller than our dense ring table on this scan, and we say "
            "so** (PRD §10.1). The pre-allocated table costs the same every frame "
            "whether or not anything is in it; the argument rests on the cell-count "
            "reduction, deterministic `offset[k] + j` access, and the "
            "proportional cut in all downstream per-cell work — not on this row.\n"
        )
    return head + "\n" + "\n".join(rows) + "\n" + note


# --- §11.2 --------------------------------------------------------------

def render_latency(results: dict) -> str:
    head = "### 11.2 Latency\n"
    lat = _get(results, "latency")
    if lat is None:
        return head + f"\n{NOT_MEASURED} — run `make bench`.\n"

    rows = [
        "| Stage | Mean (ms) | Median (ms) | p95 (ms) | Max (ms) |",
        "|---|---:|---:|---:|---:|",
    ]

    def _row(label: str, s: dict | None) -> str:
        if not s:
            return f"| {label} | {EMPTY} | {EMPTY} | {EMPTY} | {EMPTY} |"
        return (
            f"| {label} | {fmt(s.get('mean_ms'), 1)} | {fmt(s.get('median_ms'), 1)} "
            f"| {fmt(s.get('p95_ms'), 1)} | {fmt(s.get('max_ms'), 1)} |"
        )

    for name, stats in (lat.get("stages") or {}).items():
        rows.append(_row(name.replace("_", " ").capitalize(), stats))
    rows.append(_row("**End-to-end**", lat.get("end_to_end")))

    n = lat.get("n_frames", 0)
    if lat.get("meets_fr32"):
        note = f"\nOver {n:,} scans — satisfies FR-32's ≥200-scan requirement.\n"
    else:
        note = (
            f"\n**Over {n:,} scans — does NOT satisfy FR-32**, which requires ≥200. "
            "These numbers are indicative and must not be presented as the "
            "authoritative latency result.\n"
        )

    dropped = lat.get("n_warmup_discarded")
    if dropped:
        windows = lat.get("n_warmup_windows") or 1
        note += (
            f"\n{dropped} warm-up scans were discarded before timing"
            + (f", across {windows} sequence boundaries" if windows > 1 else "")
            + ". The first read of a region of the label-cache mmap pays "
            "first-touch page faults — 46.9 ms against a 5.9 ms median on "
            "sequence 05 — which is a property of reading a file for the "
            "first time, not of the pipeline. The count is stated here rather "
            "than the frames being quietly dropped.\n"
        )
    return head + "\n" + "\n".join(rows) + "\n" + note


# --- §11.3 --------------------------------------------------------------

_BIN_LABELS = (
    ("0-10m", "0–10 m"),
    ("10-30m", "10–30 m"),
    ("30-60m", "30–60 m"),
    ("60-100m", "60–100 m"),
)


def render_accuracy(results: dict) -> str:
    head = "### 11.3 Distance-binned accuracy\n"
    acc = _get(results, "accuracy")
    if acc is None:
        return head + f"\n{NOT_MEASURED} — run `make bench`.\n"

    recall_bins = ((results.get("object_recall") or {}).get("bins") or {})
    recall_all = ((results.get("object_recall") or {}).get("overall") or {})

    rows = [
        "| Range | mIoU | DRIVABLE IoU | STATIC IoU | DYNAMIC IoU | Object recall | Points |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    def _row(label: str, block: dict | None, recall: dict | None) -> str:
        block = block or {}
        iou = block.get("iou") or {}
        return (
            f"| {label} | {fmt(block.get('miou'))} | "
            f"{fmt(iou.get('DRIVABLE'))} | {fmt(iou.get('STATIC_OBSTACLE'))} | "
            f"{fmt(iou.get('DYNAMIC_OBJECT'))} | "
            f"{fmt((recall or {}).get('recall'))} | "
            f"{_int(block.get('n_points'))} |"
        )

    for key, label in _BIN_LABELS:
        rows.append(_row(label, (acc.get("bins") or {}).get(key), recall_bins.get(key)))
    rows.append(_row("**Overall**", acc.get("overall"), recall_all))

    note = (
        "\nmIoU excludes `VOID`: ground-truth *unlabeled* points are dropped from "
        "the evaluation entirely, as SemanticKITTI does. Predicting `VOID` on a "
        "labelled point still counts against that class.\n"
    )

    # A bin holding points of which none are labelled is not a zero score — it
    # is an absence of ground truth, and the distinction is the difference
    # between "our accuracy is 0.000 out there" and "the dataset does not label
    # out there". Say which.
    for key, label in _BIN_LABELS:
        block = (acc.get("bins") or {}).get(key) or {}
        n, scored = block.get("n_points") or 0, block.get("n_points_scored")
        if n > 0 and scored == 0:
            note += (
                f"\n**The {label} bin is unscored, not zero.** It holds "
                f"{n:,} points and *every one of them is unlabelled* in the "
                "ground truth, so there is nothing there to be right or wrong "
                "about. Reporting 0.000 would state a measured failure where "
                "the dataset simply stops annotating.\n"
            )

    return head + "\n" + "\n".join(rows) + "\n" + note


def render_variance(results: dict) -> str:
    """§11.3.1 — does the headline hold from one sequence to the next?"""
    head = "### 11.3.1 Per-sequence variance\n"
    per = _get(results, "per_sequence")
    var = _get(results, "variance")
    if per is None or var is None:
        return head + (
            f"\n{NOT_MEASURED} — run `make bench` with more than one "
            "`--seq`.\n"
        )
    if len(per) < 2:
        only = next(iter(per))
        return head + (
            f"\nOne sequence only ({only}). Spread across sequences is the "
            "measurement that answers *does this generalise?*, and it needs at "
            "least two: run `--seq 00 04 05`.\n"
        )

    rows = [
        "| Sequence | Scans | mIoU | Point accuracy | Object recall | "
        "Median (ms) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in sorted(per):
        b = per[name]
        acc = (b.get("accuracy") or {}).get("overall") or {}
        rec = (b.get("object_recall") or {}).get("overall") or {}
        lat = (b.get("latency") or {}).get("end_to_end") or {}
        rows.append(
            f"| {name} | {_int(b.get('n_scans'))} | {fmt(acc.get('miou'))} | "
            f"{fmt(acc.get('accuracy'))} | {fmt(rec.get('recall'))} | "
            f"{fmt(lat.get('median_ms'), 1)} |"
        )

    spread = [
        "",
        "| Metric | Mean | SD | Min | Max | Relative spread |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, label in (
        ("miou", "mIoU"),
        ("point_accuracy", "Point accuracy"),
        ("object_recall", "Object recall"),
        ("median_ms", "Median latency (ms)"),
    ):
        v = var.get(key)
        if not v:
            continue
        pct = v.get("spread_pct")
        spread.append(
            f"| {label} | {fmt(v.get('mean'))} | {fmt(v.get('sd'))} | "
            f"{fmt(v.get('min'))} | {fmt(v.get('max'))} | "
            f"{EMPTY if pct is None else f'{pct:.1f} %'} |"
        )

    return (
        head + "\n" + "\n".join(rows) + "\n" + "\n".join(spread) + "\n"
        + "\nThe headline mIoU above is pooled over every scan — one confusion "
        "matrix, not a mean of per-sequence means, so a long sequence is not "
        "given the same weight as a short one. This table is what says whether "
        "that headline survives a change of scene.\n"
    )


# --- §11.4 --------------------------------------------------------------

def render_hazards(results: dict) -> str:
    head = "### 11.4 Hazard preservation\n"
    haz = _get(results, "hazards")
    if haz is None:
        return head + (
            f"\n{NOT_MEASURED} — `bench/hazard.py` scores the synthetic scenes "
            "against their exact ground truth.\n"
        )

    rows = [
        "| Scene | Hazard | True | Measured | Error | Cells flagged | "
        "Detection | 2D grid |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    notes: list[str] = []
    for scene in haz.get("scenes", []):
        cf = scene.get("counterfactual_2d") or {}
        representable = cf.get("hazard_representable")
        verdict = (
            "not representable" if representable is False
            else (EMPTY if representable is None else "representable")
        )
        cells = (
            f"{_int(scene.get('cells_flagged'))} / "
            f"{_int(scene.get('cells_covering'))}"
            if scene.get("cells_covering") is not None else EMPTY
        )
        rows.append(
            f"| {scene.get('scene', EMPTY)} | {scene.get('hazard', EMPTY)} | "
            f"{fmt(scene.get('true_value'), 2)} | {fmt(scene.get('measured'), 4)} | "
            f"{fmt(scene.get('error'), 4)} | {cells} | "
            f"{fmt(scene.get('detection_rate'))} | {verdict} |"
        )
        if scene.get("note"):
            notes.append(f"- **{scene.get('scene')}** — {scene['note']}.")
        if cf.get("verdict") and representable is False:
            frac = cf.get("blocked_fraction")
            tail = "" if frac is None else (
                f" ({fmt(frac, 3)} of its cells blocked)"
            )
            notes.append(
                f"- **{scene.get('scene')} in 2D** — {cf['verdict']}{tail}."
            )

    body = head + "\n" + "\n".join(rows) + "\n"

    fp = haz.get("false_positives")
    if fp is not None:
        body += (
            f"\n**False positives across every control scene: {int(fp)}.** "
            "S1_flat_road is the test most likely to fail first when a "
            "threshold is tuned too aggressively, so a zero here is what makes "
            "the detection rates above worth quoting.\n"
        )
    if haz.get("max_error_m") is not None:
        body += (
            f"\nLargest geometric error over every scored hazard: "
            f"**{fmt(haz['max_error_m'], 4)}**"
            " (metres, or m/s for the tracked speed).\n"
        )
    if haz.get("counterfactual_note"):
        body += f"\n{haz['counterfactual_note']}.\n"
    if notes:
        body += "\n" + "\n".join(notes) + "\n"
    return body


# --- §11.5 --------------------------------------------------------------

def render_projection(results: dict) -> str:
    head = "### 11.5 Projection integrity\n"
    proj = _get(results, "projection")
    if proj is None:
        return head + (
            f"\n{NOT_MEASURED} — needs `core/grid.py`'s cell assignment.\n"
        )
    rows = [
        "| Metric | Target | Measured |",
        "|---|---|---:|",
        f"| Points conserved | 100.000 % | "
        f"{fmt(proj.get('points_conserved_pct'), 3)} % |",
        f"| Points dropped at ring boundaries | 0 | "
        f"{_int(proj.get('points_dropped'))} |",
        f"| Cells with ambiguous assignment | 0 | "
        f"{_int(proj.get('cells_ambiguous'))} |",
    ]
    return head + "\n" + "\n".join(rows) + "\n"


# --- the document ---------------------------------------------------------

def render(results: dict) -> str:
    """The whole of PRD §11 as Markdown."""
    meta = results.get("meta") or {}
    lines = [
        "# Results — AVR-25D",
        "",
        "**Generated by `make bench`. Do not edit by hand.** Every number in the "
        "deck must trace to a row in this file, and every row traces to "
        "`results.json` (NFR-5, PRD §11).",
        "",
        f"| Generated | {meta.get('generated', NOT_MEASURED)} |",
        "|---|---|",
        f"| Commit | `{meta.get('git_commit', NOT_MEASURED)}` |",
        f"| Dataset | {meta.get('dataset', NOT_MEASURED)} |",
        f"| Perception mode | {meta.get('perception_mode', NOT_MEASURED)} |",
        "",
        "---",
        "",
    ]
    for section in (
        render_memory, render_latency, render_accuracy, render_variance,
        render_hazards, render_projection,
    ):
        lines.append(section(results))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
