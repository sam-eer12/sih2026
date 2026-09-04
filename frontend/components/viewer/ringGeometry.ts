// ringGeometry.ts — the ring/bin → world geometry lookup.
//
// The FrameMessage carries `ring` and `bin` per cell, NOT x/y centres or
// extents. Recomputing them from scratch for ~42,000 cells at 30 Hz would
// cost millions of transcendental calls per second, so everything that
// depends only on the ring index is precomputed once into flat typed arrays.
//
// This is a faithful port of avr25d/core/grid.py::RingGrid — the REAL grid,
// not the self-contained approximation in fixtures.py. That distinction
// matters: fixtures.py totals 706,396 cells because it derives bin counts
// from ring CENTRES, while RingGrid uses ring INNER EDGES and totals the
// canonical 705,771. On Day 12 the server switches from fixtures to the real
// pipeline; if these disagree, every cell lands in the wrong place.
//
// Verified against RingGrid: 662 rings, 705,771 cells.

const S_MIN = 0.05;    // m — cell size at r <= R_KNEE
const S_MAX = 0.50;    // m — cell size ceiling
const R_KNEE = 10.0;   // m
const R_MAX = 100.0;   // m

/**
 * Round-half-to-even, matching Python's built-in round().
 * JavaScript's Math.round is half-UP, which puts a handful of rings off by
 * one bin — enough to break cell_id alignment with the backend.
 */
function roundHalfToEven(x: number): number {
  const floor = Math.floor(x);
  const diff = x - floor;
  if (diff > 0.5) return floor + 1;
  if (diff < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}

// ── Build the ring table, once at module load ──────────────────────
// Rings are laid down one at a time from r = 0, exactly as RingGrid does.

const _rInner: number[] = [];
const _s: number[] = [];
for (let r = 0.0; r < R_MAX; ) {
  const s = r <= R_KNEE ? S_MIN : Math.min(S_MIN * (r / R_KNEE), S_MAX);
  _rInner.push(r);
  _s.push(s);
  r += s;
}

export const N_RINGS = _rInner.length;   // 662

/** Inner boundary radius per ring — this is what the ring overlay draws (FR-27). */
export const RING_INNER_RADIUS = new Float32Array(N_RINGS);
/** Ring-centre radius per ring. */
export const RING_RADIUS = new Float32Array(N_RINGS);
/** Radial extent (metres) per ring. */
export const RING_EXTENT_R = new Float32Array(N_RINGS);
/** Tangential extent (metres) per ring — arc length of one bin at the centre. */
export const RING_EXTENT_T = new Float32Array(N_RINGS);
/** Angular bin count per ring. */
export const RING_BINS = new Int32Array(N_RINGS);
/** Radians per angular bin, per ring. */
export const RING_DTHETA = new Float64Array(N_RINGS);
/** Prefix sum of RING_BINS — flat cell id of the first cell in each ring. */
export const RING_OFFSET = new Int32Array(N_RINGS + 1);

for (let k = 0; k < N_RINGS; k++) {
  const rIn = _rInner[k];
  const s = _s[k];
  const rOut = rIn + s;

  // Bin count uses the INNER edge — this is the line that produces 705,771.
  const nBins = rIn === 0.0 ? 1 : Math.max(1, roundHalfToEven((2 * Math.PI * rIn) / s));

  RING_INNER_RADIUS[k] = rIn;
  RING_RADIUS[k] = 0.5 * (rIn + rOut);
  RING_EXTENT_R[k] = s;
  RING_BINS[k] = nBins;
  RING_DTHETA[k] = (2 * Math.PI) / nBins;
  RING_EXTENT_T[k] = (2 * Math.PI * RING_RADIUS[k]) / nBins;
  RING_OFFSET[k + 1] = RING_OFFSET[k] + nBins;
}

/** Total cell count across the whole grid — the 705,771 headline number. */
export const N_CELLS = RING_OFFSET[N_RINGS];

/** Outer edge of the last ring. */
export const R_OUTER = _rInner[N_RINGS - 1] + _s[N_RINGS - 1];

// ── Per-cell geometry ──────────────────────────────────────────────

/**
 * World-space centre of cell (ring, bin), written into `out` as [x, y].
 * `y` is the LiDAR lateral axis — the caller maps it to Three's z.
 */
export function cellCentre(ring: number, bin: number, out: Float32Array): void {
  const r = RING_RADIUS[ring];
  const theta = (bin + 0.5) * RING_DTHETA[ring];
  out[0] = r * Math.cos(theta);
  out[1] = r * Math.sin(theta);
}

/** Recover the ring index from a flat cell id (binary search on RING_OFFSET). */
export function ringOfCellId(cellId: number): number {
  let lo = 0;
  let hi = N_RINGS - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (RING_OFFSET[mid] <= cellId) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}
