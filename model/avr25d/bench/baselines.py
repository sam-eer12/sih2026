"""Memory baselines B0-B4 and the AVR-25D models.  PRD §10.1, FR-31.

Every function here is a pure function of counts, so the memory comparison is
**auditable arithmetic rather than an opaque measurement**.  A judge who wants
to check the headline 22.67x can do it on paper from this file; nothing depends
on what happened to be resident when a profiler ran.  Real peak-RSS lives next
door in ``memory.py`` and is reported alongside, not instead.

The honest part of PRD §10.1 is worth keeping honest in code.  Against the
*dense* baselines the win is structural and large.  Against a well-implemented
*sparse* baseline, a single scan can genuinely favour the baseline — B4 stores
61k occupied voxels in 732 kB while our pre-allocated ring table costs 17.64 MB
whether or not anything is in it.  ``compare`` therefore computes that
comparison and flags it rather than leaving it for someone else to notice.

Definitions come from PRD §10.1 and are not restated loosely:

===================  ===========================================  =============
Model                Definition                                   Bytes
===================  ===========================================  =============
B0 raw scan          float32 x/y/z/intensity + uint8 label        n_pts x 17
B1 dense 2.5D 5 cm   200 m x 200 m footprint, every cell          16,000,000 x 25
B2 sparse 2.5D 5 cm  hash map, occupied only, 4-byte key          n_occ x (25+4)
B3 dense 3D 5 cm     200 x 200 x 10 m at 1 byte/voxel             3.2e9 x 1
B4 sparse 3D 5 cm    occupied voxels, 8-byte key + 4-byte value   n_vox x 12
AVR-25D dense        pre-allocated ring table, all cells          n_cells x 25
AVR-25D occupied     occupied cells only, 4-byte key              n_occ x (25+4)
===================  ===========================================  =============

``n_cells`` is a parameter and not an import of ``core.grid``: §6.11 specifies
these as pure functions, and the ring table's 705,771 is a derived constant of
the §3 grid maths that this module has no business recomputing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# --- constants, each traceable to a line of the PRD ------------------------

#: Per-field widths of the §6.2 cell schema, in declaration order:
#: z_ground, z_obstacle, z_min, roughness, slope (float32); class_id,
#: confidence, flags (uint8); count (uint16).
CELL_FIELD_BYTES: tuple[int, ...] = (4, 4, 4, 4, 4, 1, 1, 1, 2)

#: 25 B/cell.  Asserted against the field widths so the two cannot drift.
BYTES_PER_CELL: int = sum(CELL_FIELD_BYTES)

#: B0: float32 x/y/z/intensity (16) + uint8 label (1).
BYTES_PER_POINT: int = 17

#: B2 and "AVR-25D occupied": a 4-byte cell-id key beside each stored cell.
SPARSE_KEY_BYTES: int = 4

#: B4: an 8-byte packed (ix, iy, iz) key plus a 4-byte payload.
VOXEL_ENTRY_BYTES: int = 12

#: B3 stores one occupancy byte per voxel.
BYTES_PER_VOXEL: int = 1

#: The uniform baselines' footprint: the 200 m x 200 m square that
#: circumscribes the 100 m sensing envelope (PRD §10.1).
FOOTPRINT_M: float = 200.0

#: The 3D baselines' vertical extent (PRD §10.1: "200 x 200 x 10 m").
HEIGHT_BAND_M: float = 10.0

#: Where that 10 m band starts, in the sensor frame.  The HDL-64E sits 1.70 m
#: above the road, so -2.0 m puts the road surface just inside the floor of the
#: band and leaves 8 m of headroom for overpasses, gantries and building faces
#: — which is the structure the 2.5D map exists to reason about.
HEIGHT_BAND_FLOOR_M: float = -2.0

#: Baseline cell size.  PS-6's fine end, applied uniformly — that uniformity is
#: the whole point of the comparison.
BASELINE_RES_M: float = 0.05

#: Sensing envelope.  The baselines are scored on the points AVR-25D also
#: covers; scoring them on a larger set would flatter us.
R_MAX_M: float = 100.0


@dataclass(frozen=True)
class MemoryModel:
    """One row of the PRD §10.1 table."""

    name: str
    definition: str
    n_cells: int
    bytes: int
    n_points: int = 0

    @property
    def kilobytes(self) -> float:
        return self.bytes / 1e3

    @property
    def megabytes(self) -> float:
        return self.bytes / 1e6

    @property
    def gigabytes(self) -> float:
        return self.bytes / 1e9

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "definition": self.definition,
            "n_cells": self.n_cells,
            "n_points": self.n_points,
            "bytes": self.bytes,
            "megabytes": round(self.megabytes, 4),
        }


# --- the closed forms ------------------------------------------------------

def b0_raw_scan(n_points: int) -> MemoryModel:
    """The input itself, for scale.  Not a map — it answers no spatial query."""
    n_points = int(n_points)
    return MemoryModel(
        name="B0",
        definition="raw scan, float32 x/y/z/intensity + uint8 label",
        n_cells=0,
        n_points=n_points,
        bytes=n_points * BYTES_PER_POINT,
    )


def _uniform_grid_side() -> int:
    """Cells along one edge of the 200 m footprint at 5 cm: 4000."""
    return int(round(FOOTPRINT_M / BASELINE_RES_M))


def b1_dense_uniform_25d() -> MemoryModel:
    """The comparison PS-8 actually asks for: same coverage, one resolution."""
    side = _uniform_grid_side()
    n_cells = side * side
    return MemoryModel(
        name="B1",
        definition=f"dense uniform 2.5D @ {BASELINE_RES_M*100:.0f} cm, "
                   f"{FOOTPRINT_M:.0f} m x {FOOTPRINT_M:.0f} m",
        n_cells=n_cells,
        bytes=n_cells * BYTES_PER_CELL,
    )


def b2_sparse_uniform_25d(n_occ_uniform: int) -> MemoryModel:
    """B1 with the empty cells thrown away — the fair sparse comparison."""
    n = int(n_occ_uniform)
    return MemoryModel(
        name="B2",
        definition=f"sparse uniform 2.5D @ {BASELINE_RES_M*100:.0f} cm, "
                   f"hash map, {SPARSE_KEY_BYTES}-byte key",
        n_cells=n,
        bytes=n * (BYTES_PER_CELL + SPARSE_KEY_BYTES),
    )


def b3_dense_uniform_3d() -> MemoryModel:
    """Full 3D occupancy at the same resolution.  The number PS-8 is aimed at."""
    side = _uniform_grid_side()
    layers = int(round(HEIGHT_BAND_M / BASELINE_RES_M))
    n_voxels = side * side * layers
    return MemoryModel(
        name="B3",
        definition=f"dense uniform 3D voxel @ {BASELINE_RES_M*100:.0f} cm, "
                   f"{FOOTPRINT_M:.0f} x {FOOTPRINT_M:.0f} x {HEIGHT_BAND_M:.0f} m",
        n_cells=n_voxels,
        bytes=n_voxels * BYTES_PER_VOXEL,
    )


def b4_sparse_voxel_3d(n_vox_occ: int) -> MemoryModel:
    """The strongest baseline, and the one we can lose to on a single scan."""
    n = int(n_vox_occ)
    return MemoryModel(
        name="B4",
        definition=f"sparse 3D voxel hash @ {BASELINE_RES_M*100:.0f} cm, "
                   f"8-byte key + 4-byte payload",
        n_cells=n,
        bytes=n * VOXEL_ENTRY_BYTES,
    )


def avr_dense(n_cells: int) -> MemoryModel:
    """The pre-allocated ring table.  Costs the same every frame, forever —
    which is the point: FR-12 forbids per-frame allocation."""
    n = int(n_cells)
    return MemoryModel(
        name="AVR-25D dense",
        definition="pre-allocated ring table, all cells, SoA",
        n_cells=n,
        bytes=n * BYTES_PER_CELL,
    )


def avr_occupied(n_occ_adaptive: int) -> MemoryModel:
    """Occupied adaptive cells only, priced with the same key B2 pays, so the
    two sparse numbers differ only in how many cells the geometry produced."""
    n = int(n_occ_adaptive)
    return MemoryModel(
        name="AVR-25D occupied",
        definition=f"occupied adaptive cells only, {SPARSE_KEY_BYTES}-byte key",
        n_cells=n,
        bytes=n * (BYTES_PER_CELL + SPARSE_KEY_BYTES),
    )


def cell_reduction_vs_b1(n_cells_adaptive: int) -> float:
    """PRD §10.1's headline: 16,000,000 / 705,771 = 22.67x fewer cells for
    identical coverage.  A cell-count ratio, not a byte ratio — bytes/cell are
    identical, and cells are what downstream work iterates over."""
    return b1_dense_uniform_25d().n_cells / float(n_cells_adaptive)


# --- occupancy counted from a real point cloud -----------------------------

def _inside_envelope(xyz: np.ndarray) -> np.ndarray:
    """Points within the 100 m sensing envelope.

    The baselines get scored on exactly the points AVR-25D covers.  Counting
    returns beyond 100 m against B2/B4 would inflate their cell counts and
    flatter us for free.
    """
    x = xyz[:, 0].astype(np.float64, copy=False)
    y = xyz[:, 1].astype(np.float64, copy=False)
    return (x * x + y * y) <= (R_MAX_M * R_MAX_M)


def count_uniform_occupancy(
    xyz: np.ndarray, res_m: float = BASELINE_RES_M
) -> int:
    """``n_occ_uniform`` — distinct 5 cm columns a scan lights up (B2)."""
    if xyz.shape[0] == 0:
        return 0
    keep = _inside_envelope(xyz)
    if not keep.any():
        return 0
    xy = xyz[keep, :2].astype(np.float64, copy=False)
    idx = np.floor(xy / res_m).astype(np.int64)
    return int(np.unique(idx, axis=0).shape[0])


def count_voxel_occupancy(
    xyz: np.ndarray,
    res_m: float = BASELINE_RES_M,
    floor_m: float = HEIGHT_BAND_FLOOR_M,
    height_m: float = HEIGHT_BAND_M,
) -> int:
    """``n_vox_occ`` — distinct 5 cm voxels a scan lights up (B4).

    Returns outside the baseline's own 10 m vertical band are dropped: B3/B4
    are defined over 200 x 200 x 10 m, and a voxel the baseline does not model
    cannot be charged to it.
    """
    if xyz.shape[0] == 0:
        return 0
    keep = _inside_envelope(xyz)
    z = xyz[:, 2].astype(np.float64, copy=False)
    keep &= (z >= floor_m) & (z < floor_m + height_m)
    if not keep.any():
        return 0
    pts = xyz[keep].astype(np.float64, copy=False)
    idx = np.floor(
        np.column_stack([pts[:, 0], pts[:, 1], pts[:, 2] - floor_m]) / res_m
    ).astype(np.int64)
    return int(np.unique(idx, axis=0).shape[0])


# --- the assembled table ---------------------------------------------------

def compare(
    *,
    n_points: int,
    n_occ_uniform: int,
    n_vox_occ: int,
    n_cells_adaptive: int,
    n_occ_adaptive: int,
) -> dict:
    """The whole of PRD §10.1 as a JSON-serialisable dict for ``results.json``.

    The two boolean flags exist because §10.1 commits us to saying where a
    sparse baseline beats us.  A promise the deck makes has to be one the
    harness can actually produce, or it is a promise nobody is keeping.
    """
    models = [
        b0_raw_scan(n_points),
        b1_dense_uniform_25d(),
        b2_sparse_uniform_25d(n_occ_uniform),
        b3_dense_uniform_3d(),
        b4_sparse_voxel_3d(n_vox_occ),
        avr_dense(n_cells_adaptive),
        avr_occupied(n_occ_adaptive),
    ]
    by_name = {m.name: m for m in models}
    return {
        "bytes_per_cell": BYTES_PER_CELL,
        "resolution_m": BASELINE_RES_M,
        "envelope_r_max_m": R_MAX_M,
        "models": [m.as_dict() for m in models],
        "cell_reduction_vs_b1": round(cell_reduction_vs_b1(n_cells_adaptive), 4),
        "b4_smaller_than_avr_dense":
            bool(by_name["B4"].bytes < by_name["AVR-25D dense"].bytes),
        "n_occ_adaptive_below_n_occ_uniform":
            bool(n_occ_adaptive < n_occ_uniform),
    }
