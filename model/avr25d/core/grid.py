"""Ring-sector variable-resolution grid — the mathematical core.

FR-7, FR-8, FR-9, FR-10, FR-11, FR-12.  Tests T-G1 … T-G6.

Mathematics (IMPLEMENTATION_PLAN.md §3)
---------------------------------------
Cell size grows linearly with range:

    s(r) = 0.05 m                       r ≤ r_knee  (10 m)
    s(r) = min(0.005 · r,  0.50 m)      r >  r_knee

This makes ring boundaries a geometric progression beyond r_knee:

    r_{k+1} = r_k · 1.005

so the outer-ring index inverts in closed form — no search, no binary search,
just one divide and one logarithm (FR-9).

Angular bins per ring are chosen so cells are approximately square:

    N_k = round(2π · r_k / s(r_k))

Beyond r_knee, s(r) ∝ r and the ratio is constant:

    N_k = round(2π / 0.005) = 1257   for all outer rings

This constant width is what makes the far field a rectangular block that
vectorises and caches cleanly.

Flat cell id:

    offset[k] = Σ_{i=0}^{k-1} N_i        (prefix sum, precomputed once)
    j = floor( θ / (2π) · N_k )
    cell_id = offset[k] + j

One integer add on a 662-element table that lives in L1 cache.  FR-9's
"no search, no hashing, no iteration" is a consequence of this construction,
not a separate implementation choice.

Conservation (FR-10)
--------------------
Every point within the 100 m envelope maps to exactly one cell.  The critical
clamp that ensures this:

    j = clip(j, 0, N_k - 1)

Without it, a point whose θ rounds to exactly 2π produces j = N_k, which is
one past the last bin.  That single line is the difference between passing
and failing T-G4's adversarial inputs.
"""

from __future__ import annotations

import math

import numpy as np


class RingGrid:
    """Pre-allocated ring-sector grid.  Built once at startup, reused every frame.

    Attributes
    ----------
    n_rings : int
        Total ring count.  Must be 662 for the §3 parameters.
    r_edge : np.ndarray, float32, shape (n_rings + 1,)
        Inner radius of each ring plus one trailing outer edge.
        ``r_edge[0] == 0``, ``r_edge[-1] == r_max``.
    s : np.ndarray, float32, shape (n_rings,)
        Radial cell size for each ring.
    n_bins : np.ndarray, int32, shape (n_rings,)
        Angular sector count per ring.
    offset : np.ndarray, int32, shape (n_rings + 1,)
        Prefix sum of n_bins.  ``offset[k]`` is the flat id of the first cell
        in ring ``k``.  ``offset[-1] == n_cells == 705_771``.
    n_cells : int
        Total cell count.  Must be 705_771 for the §3 parameters.
    """

    def __init__(
        self,
        s_min: float = 0.05,
        s_max: float = 0.50,
        r_knee: float = 10.0,
        r_max: float = 100.0,
    ) -> None:
        self._s_min   = float(s_min)
        self._s_max   = float(s_max)
        self._r_knee  = float(r_knee)
        self._r_max   = float(r_max)
        self._ratio   = 1.0 + s_min / r_knee   # 1.005 for default params

        # ── build ring boundary list ──────────────────────────────────────
        # Rings are laid down one at a time.  The resulting arrays are small
        # (662 entries) so the Python loop here is not performance-sensitive —
        # it runs once at startup and is never called again.
        #
        # We store (r_inner, s) pairs: r_inner is the inner edge of the ring,
        # s is the radial cell size.  This matches the §3.6 reference script
        # exactly — the bin count formula uses r_inner, not the ring centre.
        ring_pairs: list[tuple[float, float]] = []
        r = 0.0
        while r < r_max:
            s = s_min if r <= r_knee else min(s_min * (r / r_knee), s_max)
            ring_pairs.append((r, s))
            r += s

        n_rings = len(ring_pairs)

        # r_edge: inner edges of each ring, plus the outer edge of the last ring
        r_inner_arr = np.array([p[0] for p in ring_pairs], dtype=np.float64)
        s_exact_arr = np.array([p[1] for p in ring_pairs], dtype=np.float64)

        # Outer edge of each ring = inner edge + s (exact, not r_max forced)
        r_outer_arr = r_inner_arr + s_exact_arr

        # r_edge[k] = inner edge of ring k; r_edge[n_rings] = outer edge of last ring
        r_edge_arr = np.empty(n_rings + 1, dtype=np.float32)
        r_edge_arr[:n_rings] = r_inner_arr.astype(np.float32)
        r_edge_arr[n_rings]  = float(r_outer_arr[-1])

        s_arr = s_exact_arr.astype(np.float32)

        # ── angular bins per ring ──────────────────────────────────────────
        # N_k = round(2π · r_inner / s(r_inner))  — uses the INNER edge, not
        # the centre.  This matches the §3.6 reference script exactly and
        # produces the canonical 705,771 total cells.
        r_centre = 0.5 * (r_edge_arr[:-1].astype(np.float64) + r_edge_arr[1:].astype(np.float64))
        n_bins_arr = np.empty(n_rings, dtype=np.int32)
        for k in range(n_rings):
            r_inner = float(r_inner_arr[k])   # inner edge of ring k
            sc      = float(s_exact_arr[k])
            if r_inner == 0.0:
                n_bins_arr[k] = 1
            else:
                n_bins_arr[k] = max(1, round(2.0 * math.pi * r_inner / sc))

        # ── prefix sum (flat cell ids) ─────────────────────────────────────
        offset_arr = np.zeros(n_rings + 1, dtype=np.int64)
        offset_arr[1:] = np.cumsum(n_bins_arr)

        # ── public attributes ──────────────────────────────────────────────
        self.n_rings: int             = n_rings
        self.r_edge:  np.ndarray      = r_edge_arr            # float32[n_rings+1]
        self.s:       np.ndarray      = s_arr                  # float32[n_rings]
        self.n_bins:  np.ndarray      = n_bins_arr             # int32[n_rings]
        self.offset:  np.ndarray      = offset_arr.astype(np.int32)  # int32[n_rings+1]
        self.n_cells: int             = int(offset_arr[-1])

        # Precomputed ring-centre radii (float64, used in cell_centres / extents)
        self._r_centre: np.ndarray = r_centre.astype(np.float64)  # float64[n_rings]

        # ── inner-ring neighbour table (used by cell.py for slope / roughness) ──
        # For ring k < n_inner (variable bin counts), the neighbour of bin j in
        # ring k is bin round(j * N_{k+1} / N_k) in ring k+1.
        # For k >= n_inner the bin counts are all equal so the neighbour is j.
        # We store the mapping as an int32 array of shape (n_rings-1, max_bins_inner)
        # only for the inner rings; outer rings use the identity.
        n_inner = int(round(r_knee / s_min))   # 200
        self._n_inner: int = n_inner
        self._neighbour_table: np.ndarray | None = None   # built lazily

    # ── ring index (closed-form, vectorised) ──────────────────────────────

    def ring_of(self, r: np.ndarray) -> np.ndarray:
        """Closed-form ring index for an array of radii.  FR-9.

        Returns -1 for points beyond r_max (out of envelope).
        Uses np.where — single pass over the array, not two masked writes.

        Parameters
        ----------
        r : array-like, float
            Horizontal range in metres.  Shape arbitrary.

        Returns
        -------
        np.ndarray, int32, same shape as r.
        """
        r = np.asarray(r, dtype=np.float64)
        s_min  = self._s_min
        r_knee = self._r_knee
        r_max  = self._r_max
        ratio  = self._ratio

        # Inner rings: uniform spacing → simple floor divide
        r_clipped = np.where(np.isfinite(r), r, r_max + 1.0)   # push inf/nan out of range
        k_inner = np.floor(r_clipped / s_min).astype(np.int32)

        # Outer rings: geometric progression → logarithm
        # Guard against r <= 0 to avoid log(0)
        r_safe = np.where(r > r_knee, r, r_knee + 1e-9)
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            k_outer = (self._n_inner + np.floor(
                np.log(r_safe / r_knee) / math.log(ratio)
            )).astype(np.int32)

        k = np.where(r <= r_knee, k_inner, k_outer)

        # Clamp valid cells to [0, n_rings-1]; mark out-of-envelope as -1
        out_of_range = (r < 0) | (r > r_max)
        k = np.clip(k, 0, self.n_rings - 1)
        k = np.where(out_of_range, np.int32(-1), k)
        return k.astype(np.int32)

    # ── cell id (vectorised, O(1) per point) ──────────────────────────────

    def cell_of(
        self,
        x: np.ndarray,
        y: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Map (x, y) coordinates to flat cell ids.  FR-9, FR-11.

        Parameters
        ----------
        x, y : array-like, float
            Cartesian coordinates in the sensor frame (metres).
            Must have the same shape.

        Returns
        -------
        cell_id : np.ndarray, int32
            Flat cell id for each point.  Meaningless where valid == False.
        valid : np.ndarray, bool
            True for points that fall within the 100 m envelope.
        """
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)

        r     = np.hypot(x, y)
        theta = np.arctan2(y, x) % (2.0 * math.pi)   # normalise to [0, 2π)

        k     = self.ring_of(r)
        valid = k >= 0

        # Work on all points; the invalid ones produce garbage that we mask out.
        k_safe   = np.where(valid, k, 0)
        n_bins_k = self.n_bins[k_safe]
        offset_k = self.offset[k_safe]

        j = np.floor(theta / (2.0 * math.pi) * n_bins_k).astype(np.int32)
        # ── THE critical clamp (FR-10) ──────────────────────────────────────
        # theta can round to exactly 2π, making j == n_bins_k.  Clamp to the
        # last valid bin.  Without this single line T-G4 fails on adversarial
        # inputs at θ = 0 and θ = 2π - ε.
        j = np.minimum(j, n_bins_k - 1)
        j = np.maximum(j, 0)

        cell_id = (offset_k + j).astype(np.int32)
        cell_id = np.where(valid, cell_id, np.int32(-1))
        return cell_id, valid

    # ── inverse map: cell id → centre coordinates ─────────────────────────

    def cell_centres(self, cell_id: np.ndarray) -> np.ndarray:
        """Flat cell ids → (x, y) centre coordinates.  float64[n, 2].

        Used by the renderer and the costmap.
        """
        cell_id = np.asarray(cell_id, dtype=np.int32).ravel()
        n = cell_id.shape[0]
        xy = np.zeros((n, 2), dtype=np.float64)

        # Recover (ring, bin) from flat id via searchsorted on offset
        # offset is sorted and strictly increasing, so this is correct.
        k = np.searchsorted(self.offset, cell_id, side="right") - 1
        k = np.clip(k, 0, self.n_rings - 1)
        j = cell_id - self.offset[k]

        r_c  = self._r_centre[k]
        nb_k = self.n_bins[k].astype(np.float64)
        theta = (j.astype(np.float64) + 0.5) / nb_k * (2.0 * math.pi)

        xy[:, 0] = r_c * np.cos(theta)
        xy[:, 1] = r_c * np.sin(theta)
        return xy

    # ── cell extents ───────────────────────────────────────────────────────

    def cell_extents(self, cell_id: np.ndarray) -> np.ndarray:
        """Flat cell ids → (radial_extent, tangential_extent) in metres.

        Used by the renderer to draw correctly-sized cells (FR-30).
        Returns float32[n, 2].
        """
        cell_id = np.asarray(cell_id, dtype=np.int32).ravel()
        k = np.searchsorted(self.offset, cell_id, side="right") - 1
        k = np.clip(k, 0, self.n_rings - 1)

        s_k    = self.s[k].astype(np.float64)           # radial extent
        r_c    = self._r_centre[k]
        nb_k   = self.n_bins[k].astype(np.float64)
        tang   = 2.0 * math.pi * r_c / nb_k             # tangential extent

        return np.column_stack([s_k, tang]).astype(np.float32)

    # ── ring / bin decomposition (used by cell.py and bench) ──────────────

    def ring_bin_of(
        self,
        x: np.ndarray,
        y: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(x, y) → (ring, bin, valid).  Convenience for cell.py.

        Returns
        -------
        ring : int32[n]
        bin  : int32[n]
        valid : bool[n]
        """
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)

        r     = np.hypot(x, y)
        theta = np.arctan2(y, x) % (2.0 * math.pi)

        k     = self.ring_of(r)
        valid = k >= 0
        k_safe   = np.where(valid, k, 0)
        n_bins_k = self.n_bins[k_safe]

        j = np.floor(theta / (2.0 * math.pi) * n_bins_k).astype(np.int32)
        j = np.minimum(j, n_bins_k - 1)
        j = np.maximum(j, 0)

        ring = np.where(valid, k, np.int32(-1))
        bin_ = np.where(valid, j, np.int32(-1))
        return ring.astype(np.int32), bin_.astype(np.int32), valid

    # ── neighbour table (used by cell.py for slope/roughness) ────────────

    def neighbour_table(self) -> np.ndarray:
        """Outer-ring neighbour bin index.

        For ring k and bin j, the neighbour in ring k+1 is:
            - Inner rings (k < n_inner):  round(j * N_{k+1} / N_k)
            - Outer rings (k >= n_inner): j  (all have 1257 bins)

        Returns an int32 array of shape (n_inner, max_inner_bins) where
        entry [k, j] is the bin index in ring k+1.  Outer rings are handled
        trivially by the identity, so we don't store them.

        Built once and cached.
        """
        if self._neighbour_table is not None:
            return self._neighbour_table

        n_inner = self._n_inner
        if n_inner == 0:
            self._neighbour_table = np.zeros((0, 0), dtype=np.int32)
            return self._neighbour_table

        max_bins = int(self.n_bins[:n_inner].max())
        table = np.zeros((n_inner, max_bins), dtype=np.int32)

        for k in range(n_inner - 1):
            nk  = int(self.n_bins[k])
            nk1 = int(self.n_bins[k + 1])
            j_arr = np.arange(nk, dtype=np.float64)
            neighbour = np.round(j_arr * nk1 / nk).astype(np.int32)
            neighbour = np.clip(neighbour, 0, nk1 - 1)
            table[k, :nk] = neighbour

        # Last inner ring → first outer ring (both have constant bin count 1257
        # at the default parameters; handle the general case anyway)
        k_last = n_inner - 1
        nk  = int(self.n_bins[k_last])
        nk1 = int(self.n_bins[n_inner]) if n_inner < self.n_rings else nk
        j_arr = np.arange(nk, dtype=np.float64)
        neighbour = np.round(j_arr * nk1 / nk).astype(np.int32)
        neighbour = np.clip(neighbour, 0, nk1 - 1)
        table[k_last, :nk] = neighbour

        self._neighbour_table = table
        return table

    # ── convenience ───────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"RingGrid(n_rings={self.n_rings}, n_cells={self.n_cells:,}, "
            f"s_min={self._s_min} m, r_max={self._r_max} m)"
        )
