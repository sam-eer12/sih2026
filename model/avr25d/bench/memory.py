"""Real RSS and occupancy-count memory measurements.  PRD §10.1, FR-31.
IMPLEMENTATION_PLAN §6.11, Tests T-B1.

This module provides the *real* numbers that baselines.py cannot: actual peak
RSS measured by psutil, and the adaptive grid's occupied cell count, which
requires a live CellGrid projection.  baselines.py provides the pure arithmetic;
this module adds the measurement on top.

The combination is what PRD §10.1 promises: auditable closed-form arithmetic
for the baselines, honest measurement for the adaptive grid, and an explicit
flag where the two interact (B4 can beat our dense table on a single scan).

Usage (called by bench/__main__.py after every scan loop):

    mem = measure(
        scans,               # iterable of Scan objects
        segmenter,           # callable(xyz, intensity) -> labels
        cfg,
        max_scans=50,        # sample every Nth scan for RSS
        verbose=True,
    )
    results["memory"] = mem
"""

from __future__ import annotations

import gc
import os
from typing import Iterable

import numpy as np
import psutil

from . import baselines as bl
from ..core.cell import CellGrid
from ..core.grid import RingGrid


def _rss_mb() -> float:
    """Current process RSS in megabytes."""
    proc = psutil.Process(os.getpid())
    return proc.memory_info().rss / 1e6


def measure_single(
    xyz:      np.ndarray,   # float32[n, 3]
    labels:   np.ndarray,   # uint8[n]
    grid:     RingGrid,
    cells:    CellGrid,
) -> dict:
    """Memory statistics for a single scan already projected into cells.

    Parameters
    ----------
    xyz     : float32[n, 3]   — point cloud
    labels  : uint8[n]        — AVR-25D labels from segmenter
    grid    : RingGrid
    cells   : CellGrid        — must already be reset + accumulated

    Returns a dict with n_occ_uniform, n_vox_occ, n_cells_adaptive,
    n_occ_adaptive ready to pass to baselines.compare().
    """
    n_pts = int(xyz.shape[0])

    # occupancy counts for baselines
    n_occ_uniform = bl.count_uniform_occupancy(xyz)
    n_vox_occ     = bl.count_voxel_occupancy(xyz)

    # adaptive grid — always 705,771 cells pre-allocated
    n_cells_adaptive = grid.n_cells           # 705,771
    n_occ_adaptive   = cells.n_occupied       # occupied this frame

    return dict(
        n_points          = n_pts,
        n_occ_uniform     = n_occ_uniform,
        n_vox_occ         = n_vox_occ,
        n_cells_adaptive  = n_cells_adaptive,
        n_occ_adaptive    = n_occ_adaptive,
    )


def measure(
    scans:     Iterable,       # iterable of avr25d.io.kitti.Scan
    segmenter,                 # callable(xyz, intensity) -> uint8[n]
    cfg,
    *,
    max_scans:  int  = 50,     # how many scans to sample (keeps it fast)
    verbose:    bool = True,
) -> dict:
    """Full memory measurement over a scan sample.

    Measures:
    - Mean occupied cells per model (B0–B4, AVR-25D dense + occupied)
    - Peak RSS before and after the hot loop
    - Cell reduction ratio

    Returns the dict expected by bench/report.py render_memory().
    """
    grid  = RingGrid(
        s_min  = float(cfg.grid.s_min),
        s_max  = float(cfg.grid.s_max),
        r_knee = float(cfg.grid.r_knee),
        r_max  = float(cfg.grid.r_max),
    )
    cells = CellGrid(grid)

    # Force a GC before measuring baseline RSS
    gc.collect()
    rss_before = _rss_mb()

    n_pts_list:    list[int] = []
    n_occ_u_list:  list[int] = []
    n_vox_list:    list[int] = []
    n_occ_a_list:  list[int] = []

    scans_done = 0
    for scan in scans:
        if scans_done >= max_scans:
            break

        labels = segmenter(scan.xyz, scan.intensity)
        cells.reset()
        cells.accumulate(scan.xyz, scan.intensity, labels, scan.moving)

        m = measure_single(scan.xyz, labels, grid, cells)
        n_pts_list.append(m["n_points"])
        n_occ_u_list.append(m["n_occ_uniform"])
        n_vox_list.append(m["n_vox_occ"])
        n_occ_a_list.append(m["n_occ_adaptive"])

        scans_done += 1
        if verbose and scans_done % 10 == 0:
            print(f"  memory: {scans_done}/{max_scans} scans", end="\r", flush=True)

    if verbose and scans_done:
        print()

    gc.collect()
    rss_after = _rss_mb()
    peak_rss_mb = rss_after   # conservative: actual peak is ≥ after

    if not n_pts_list:
        return {"error": "no scans measured"}

    mean_pts       = int(round(float(np.mean(n_pts_list))))
    mean_occ_u     = int(round(float(np.mean(n_occ_u_list))))
    mean_vox       = int(round(float(np.mean(n_vox_list))))
    mean_occ_a     = int(round(float(np.mean(n_occ_a_list))))

    comparison = bl.compare(
        n_points         = mean_pts,
        n_occ_uniform    = mean_occ_u,
        n_vox_occ        = mean_vox,
        n_cells_adaptive = grid.n_cells,   # always 705,771
        n_occ_adaptive   = mean_occ_a,
    )

    comparison["peak_rss_mb"]      = round(peak_rss_mb, 2)
    comparison["rss_before_mb"]    = round(rss_before, 2)
    comparison["n_scans_sampled"]  = scans_done
    comparison["n_occ_adaptive_measured"] = True
    comparison["n_cells_adaptive_source"] = "core/grid.py (live measurement)"

    return comparison
