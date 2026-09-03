"""FrameMessage encode / decode — FROZEN after Day 1.

Wire layout (little-endian):
    [4 bytes]           header_len  — uint32, byte length of the JSON header
    [header_len bytes]  UTF-8 JSON  — the FrameMessage dict; typed-array fields
                                      carry the string "payload" as a sentinel
    [payload bytes...]  typed arrays in declaration order (cells, then refined):
                            cell_id   uint32[n]
                            ring      uint16[n]
                            bin       uint16[n]
                            z_ground  float32[n]
                            z_obstacle float32[n]
                            roughness  float32[n]
                            slope      float32[n]
                            class_id   uint8[n]
                            confidence uint8[n]
                            flags      uint8[n]
                        then refined (same layout, m entries):
                            parent_id  uint32[m]
                            quadrant   uint8[m]
                            z_ground   float32[m]
                            z_obstacle float32[m]
                            class_id   uint8[m]
                            flags      uint8[m]

Tracks, decision, and stats are fully JSON — they are small and the browser
reads them with zero-copy (JSON.parse is not on the hot path).

The browser reconstructs typed arrays from ArrayBuffer views over the payload
bytes that follow the header.  lib/protocol.ts mirrors this layout exactly.

Changing anything here after Day 1 requires the integration lead's sign-off
and a message to the whole team (IMPLEMENTATION_PLAN.md §5.1).
"""

from __future__ import annotations

import json
import struct
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# dtype map: field name -> (numpy dtype, itemsize)
# ---------------------------------------------------------------------------

# Dense cells — in transmission order
_CELL_FIELDS: tuple[tuple[str, np.dtype], ...] = (
    ("cell_id",    np.dtype("<u4")),   # uint32
    ("ring",       np.dtype("<u2")),   # uint16
    ("bin",        np.dtype("<u2")),   # uint16
    ("z_ground",   np.dtype("<f4")),   # float32
    ("z_obstacle", np.dtype("<f4")),
    ("roughness",  np.dtype("<f4")),
    ("slope",      np.dtype("<f4")),
    ("class_id",   np.dtype("u1")),    # uint8
    ("confidence", np.dtype("u1")),
    ("flags",      np.dtype("u1")),
)

# Refined overlay — in transmission order
_REFINED_FIELDS: tuple[tuple[str, np.dtype], ...] = (
    ("parent_id",  np.dtype("<u4")),
    ("quadrant",   np.dtype("u1")),
    ("z_ground",   np.dtype("<f4")),
    ("z_obstacle", np.dtype("<f4")),
    ("class_id",   np.dtype("u1")),
    ("flags",      np.dtype("u1")),
)


# ---------------------------------------------------------------------------
# Thin containers — used by both Python sides (server and tests)
# ---------------------------------------------------------------------------

@dataclass
class CellArrays:
    """Dense occupied-cell data for one frame."""
    n: int
    cell_id:    np.ndarray   # uint32[n]
    ring:       np.ndarray   # uint16[n]
    bin:        np.ndarray   # uint16[n]
    z_ground:   np.ndarray   # float32[n]
    z_obstacle: np.ndarray   # float32[n]
    roughness:  np.ndarray   # float32[n]
    slope:      np.ndarray   # float32[n]
    class_id:   np.ndarray   # uint8[n]
    confidence: np.ndarray   # uint8[n]
    flags:      np.ndarray   # uint8[n]

    @staticmethod
    def empty() -> "CellArrays":
        return CellArrays(
            n=0,
            cell_id=np.zeros(0, "<u4"),
            ring=np.zeros(0, "<u2"),
            bin=np.zeros(0, "<u2"),
            z_ground=np.zeros(0, "<f4"),
            z_obstacle=np.zeros(0, "<f4"),
            roughness=np.zeros(0, "<f4"),
            slope=np.zeros(0, "<f4"),
            class_id=np.zeros(0, "u1"),
            confidence=np.zeros(0, "u1"),
            flags=np.zeros(0, "u1"),
        )


@dataclass
class RefinedArrays:
    """Sub-cell overlay (FR-17)."""
    n: int
    parent_id:  np.ndarray   # uint32[m]
    quadrant:   np.ndarray   # uint8[m]
    z_ground:   np.ndarray   # float32[m]
    z_obstacle: np.ndarray   # float32[m]
    class_id:   np.ndarray   # uint8[m]
    flags:      np.ndarray   # uint8[m]

    @staticmethod
    def empty() -> "RefinedArrays":
        return RefinedArrays(
            n=0,
            parent_id=np.zeros(0, "<u4"),
            quadrant=np.zeros(0, "u1"),
            z_ground=np.zeros(0, "<f4"),
            z_obstacle=np.zeros(0, "<f4"),
            class_id=np.zeros(0, "u1"),
            flags=np.zeros(0, "u1"),
        )


@dataclass
class Track:
    id: int
    x: float
    y: float
    vx: float
    vy: float
    class_id: int
    age: int
    speed: float
    predicted: list[list[float]] = field(default_factory=list)


@dataclass
class Decision:
    route: list[list[float]]
    alternative: list[list[float]]
    selected: str      # "primary" | "alternative"
    risk: str          # "LOW" | "MEDIUM" | "HIGH"
    eta_s: float
    reason: str


@dataclass
class FrameStats:
    fps: float
    t_perception_ms: float
    t_projection_ms: float
    t_analysis_ms: float
    t_refine_ms: float
    t_decision_ms: float
    t_serialise_ms: float
    t_total_ms: float
    n_points: int
    n_points_conserved: int   # FR-10: must equal n_points
    n_cells_occupied: int
    n_cells_total: int        # 705_771
    mem_bytes: int
    baseline_mem_bytes: int
    reduction: float


@dataclass
class FrameMessage:
    """One pipeline output frame, ready to encode."""
    frame_id:  int
    t_sec:     float
    mode:      str            # "live" | "cached" | "geometric"
    cells:     CellArrays
    refined:   RefinedArrays
    tracks:    list[Track]
    decision:  Decision
    stats:     FrameStats


# ---------------------------------------------------------------------------
# Encode
# ---------------------------------------------------------------------------

def encode(msg: FrameMessage) -> bytes:
    """Serialise a FrameMessage to the binary wire format.

    Returns: header_len (4 bytes, uint32 LE) | JSON header | payload bytes.
    """
    # Build the payload first so we can reference byte offsets in the header.
    payload_parts: list[bytes] = []

    def _append_arrays(arrays_data: list[tuple[str, np.ndarray]]) -> dict[str, str]:
        """Serialise arrays and return JSON sentinel dict."""
        sentinel: dict[str, str] = {}
        for name, arr in arrays_data:
            b = np.asarray(arr).tobytes()
            payload_parts.append(b)
            sentinel[name] = f"{arr.dtype}[{len(arr)}]"
        return sentinel

    cells_sentinel = _append_arrays([
        ("cell_id",    msg.cells.cell_id.astype("<u4")),
        ("ring",       msg.cells.ring.astype("<u2")),
        ("bin",        msg.cells.bin.astype("<u2")),
        ("z_ground",   msg.cells.z_ground.astype("<f4")),
        ("z_obstacle", msg.cells.z_obstacle.astype("<f4")),
        ("roughness",  msg.cells.roughness.astype("<f4")),
        ("slope",      msg.cells.slope.astype("<f4")),
        ("class_id",   msg.cells.class_id.astype("u1")),
        ("confidence", msg.cells.confidence.astype("u1")),
        ("flags",      msg.cells.flags.astype("u1")),
    ])
    refined_sentinel = _append_arrays([
        ("parent_id",  msg.refined.parent_id.astype("<u4")),
        ("quadrant",   msg.refined.quadrant.astype("u1")),
        ("z_ground",   msg.refined.z_ground.astype("<f4")),
        ("z_obstacle", msg.refined.z_obstacle.astype("<f4")),
        ("class_id",   msg.refined.class_id.astype("u1")),
        ("flags",      msg.refined.flags.astype("u1")),
    ])

    header_dict: dict[str, Any] = {
        "frame_id": msg.frame_id,
        "t_sec":    round(msg.t_sec, 4),
        "mode":     msg.mode,
        "cells": {"n": msg.cells.n, **cells_sentinel},
        "refined": {"n": msg.refined.n, **refined_sentinel},
        "tracks": [
            {
                "id":        t.id,
                "x":         round(t.x, 4),
                "y":         round(t.y, 4),
                "vx":        round(t.vx, 4),
                "vy":        round(t.vy, 4),
                "class_id":  t.class_id,
                "age":       t.age,
                "speed":     round(t.speed, 4),
                "predicted": [[round(p[0], 4), round(p[1], 4)] for p in t.predicted],
            }
            for t in msg.tracks
        ],
        "decision": {
            "route":       [[round(p[0], 4), round(p[1], 4)] for p in msg.decision.route],
            "alternative": [[round(p[0], 4), round(p[1], 4)] for p in msg.decision.alternative],
            "selected":    msg.decision.selected,
            "risk":        msg.decision.risk,
            "eta_s":       round(msg.decision.eta_s, 2),
            "reason":      msg.decision.reason,
        },
        "stats": {
            "fps":                  round(msg.stats.fps, 2),
            "t_perception_ms":      round(msg.stats.t_perception_ms, 2),
            "t_projection_ms":      round(msg.stats.t_projection_ms, 2),
            "t_analysis_ms":        round(msg.stats.t_analysis_ms, 2),
            "t_refine_ms":          round(msg.stats.t_refine_ms, 2),
            "t_decision_ms":        round(msg.stats.t_decision_ms, 2),
            "t_serialise_ms":       round(msg.stats.t_serialise_ms, 2),
            "t_total_ms":           round(msg.stats.t_total_ms, 2),
            "n_points":             msg.stats.n_points,
            "n_points_conserved":   msg.stats.n_points_conserved,
            "n_cells_occupied":     msg.stats.n_cells_occupied,
            "n_cells_total":        msg.stats.n_cells_total,
            "mem_bytes":            msg.stats.mem_bytes,
            "baseline_mem_bytes":   msg.stats.baseline_mem_bytes,
            "reduction":            round(msg.stats.reduction, 4),
        },
    }

    header_bytes = json.dumps(header_dict, separators=(",", ":")).encode("utf-8")
    header_len = struct.pack("<I", len(header_bytes))
    payload = b"".join(payload_parts)
    return header_len + header_bytes + payload


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------

def decode(data: bytes | bytearray | memoryview) -> dict[str, Any]:
    """Deserialise a FrameMessage from the wire format.

    Returns the header dict with typed-array sentinel strings intact
    and a ``_arrays`` sub-dict carrying the actual numpy arrays.

    The frontend (lib/protocol.ts) does the same reconstruction.
    """
    if len(data) < 4:
        raise ValueError(f"too short to contain a header length: {len(data)} bytes")

    header_len = struct.unpack_from("<I", data, 0)[0]
    if len(data) < 4 + header_len:
        raise ValueError(
            f"message truncated: need {4 + header_len} bytes, got {len(data)}"
        )

    header = json.loads(data[4:4 + header_len])
    payload = memoryview(data)[4 + header_len:]
    offset = 0

    def _read(dtype: np.dtype, n: int) -> np.ndarray:
        nonlocal offset
        nbytes = n * dtype.itemsize
        arr = np.frombuffer(payload[offset:offset + nbytes], dtype=dtype)
        offset += nbytes
        return arr

    n_cells = header["cells"]["n"]
    cells_arrays: dict[str, np.ndarray] = {}
    for name, dtype in _CELL_FIELDS:
        cells_arrays[name] = _read(dtype, n_cells)

    n_refined = header["refined"]["n"]
    refined_arrays: dict[str, np.ndarray] = {}
    for name, dtype in _REFINED_FIELDS:
        refined_arrays[name] = _read(dtype, n_refined)

    header["_arrays"] = {
        "cells":   cells_arrays,
        "refined": refined_arrays,
    }
    return header


# ---------------------------------------------------------------------------
# Round-trip helper (used by tests and fixtures)
# ---------------------------------------------------------------------------

def round_trip(msg: FrameMessage) -> dict[str, Any]:
    """encode then decode — used in tests to verify the wire contract."""
    return decode(encode(msg))
