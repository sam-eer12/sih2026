// terrain.ts — the heightmap both representations of the hero share.
//
// The hero morphs a photographed-looking mountain into a LiDAR point cloud.
// For that to be honest rather than a filter, both states must be the SAME
// geometry: the mesh is the surface, the points are samples of that surface.
// So the height field is generated once, here, and handed to both.
//
// It is procedural rather than a photograph for a reason beyond having no
// asset to hand: a photo has no depth, so a photo-to-pointcloud transition
// has to invent one from luminance. Generating the terrain means we hold the
// real height at every vertex — which is the thing the product is actually
// about.

/** Grid resolution. 220² = 48,400 vertices — one draw call, comfortable at 60 FPS. */
export const GRID = 220;
export const SIZE = 60;        // world units across
export const PEAK = 13.5;      // max elevation

// ── Deterministic value noise ──────────────────────────────────────
// Seeded so the mountain is identical on every load and between machines:
// a hero that reshuffles on refresh reads as a screensaver, not a readout.

function hash2(x: number, y: number): number {
  const h = Math.sin(x * 127.1 + y * 311.7) * 43758.5453123;
  return h - Math.floor(h);
}

function smooth(t: number): number {
  return t * t * (3 - 2 * t);
}

function valueNoise(x: number, y: number): number {
  const xi = Math.floor(x);
  const yi = Math.floor(y);
  const xf = x - xi;
  const yf = y - yi;

  const a = hash2(xi, yi);
  const b = hash2(xi + 1, yi);
  const c = hash2(xi, yi + 1);
  const d = hash2(xi + 1, yi + 1);

  const u = smooth(xf);
  const v = smooth(yf);
  return a * (1 - u) * (1 - v) + b * u * (1 - v) + c * (1 - u) * v + d * u * v;
}

/** Fractal Brownian motion — octaves of value noise at halving amplitude. */
function fbm(x: number, y: number, octaves = 6): number {
  let sum = 0;
  let amp = 0.5;
  let freq = 1;
  let norm = 0;
  for (let i = 0; i < octaves; i++) {
    sum += amp * valueNoise(x * freq, y * freq);
    norm += amp;
    amp *= 0.5;
    freq *= 2.02;      // not exactly 2, to avoid axis-aligned repetition
  }
  return sum / norm;
}

/**
 * Height at normalised (u, v) in [0,1].
 *
 * A ridge term gives the silhouette an actual peak rather than rolling hills —
 * `1 - |2n - 1|` folds the noise about its midpoint, which is what makes
 * mountains look like mountains instead of dunes.
 */
export function heightAt(u: number, v: number): number {
  const x = u * 3.2;
  const y = v * 3.2;

  const base = fbm(x, y, 6);
  const ridge = 1 - Math.abs(2 * fbm(x * 0.8 + 11.3, y * 0.8 + 7.7, 5) - 1);

  // Radial falloff so the massif sits in frame and drops to a plain at the
  // edges, instead of being clipped by the geometry bounds.
  const dx = u - 0.5;
  const dy = v - 0.52;
  const r = Math.sqrt(dx * dx + dy * dy) * 2.05;
  const falloff = Math.max(0, 1 - r * r);

  const h = (base * 0.42 + ridge * 0.78) * falloff * falloff;
  return Math.max(0, h);
}

export interface TerrainData {
  /** xyz per vertex, Y-up, centred on the origin. */
  positions: Float32Array;
  normals: Float32Array;
  /** Normalised height in [0,1] — drives both shading and class colour. */
  elevation: Float32Array;
  /** Triangle indices for the mesh representation. */
  indices: Uint32Array;
  count: number;
}

/** Build the shared height field, its normals, and the mesh topology. */
export function buildTerrain(): TerrainData {
  const n = GRID;
  const count = n * n;
  const positions = new Float32Array(count * 3);
  const elevation = new Float32Array(count);
  const step = SIZE / (n - 1);

  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      const idx = j * n + i;
      const u = i / (n - 1);
      const v = j / (n - 1);
      const h = heightAt(u, v);

      positions[idx * 3] = (u - 0.5) * SIZE;
      positions[idx * 3 + 1] = h * PEAK;
      positions[idx * 3 + 2] = (v - 0.5) * SIZE;
      elevation[idx] = h;
    }
  }

  // Normals from central differences on the height field. Cheaper and
  // smoother than accumulating face normals, and exact enough for shading.
  const normals = new Float32Array(count * 3);
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      const idx = j * n + i;
      const iL = j * n + Math.max(i - 1, 0);
      const iR = j * n + Math.min(i + 1, n - 1);
      const jD = Math.max(j - 1, 0) * n + i;
      const jU = Math.min(j + 1, n - 1) * n + i;

      const dhdx = (positions[iR * 3 + 1] - positions[iL * 3 + 1]) / (2 * step);
      const dhdz = (positions[jU * 3 + 1] - positions[jD * 3 + 1]) / (2 * step);

      const nx = -dhdx;
      const ny = 1;
      const nz = -dhdz;
      const len = Math.hypot(nx, ny, nz) || 1;
      normals[idx * 3] = nx / len;
      normals[idx * 3 + 1] = ny / len;
      normals[idx * 3 + 2] = nz / len;
    }
  }

  const quads = (n - 1) * (n - 1);
  const indices = new Uint32Array(quads * 6);
  let k = 0;
  for (let j = 0; j < n - 1; j++) {
    for (let i = 0; i < n - 1; i++) {
      const a = j * n + i;
      const b = a + 1;
      const c = a + n;
      const d = c + 1;
      indices[k++] = a; indices[k++] = c; indices[k++] = b;
      indices[k++] = b; indices[k++] = c; indices[k++] = d;
    }
  }

  return { positions, normals, elevation, indices, count };
}
