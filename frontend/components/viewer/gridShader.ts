// gridShader.ts — the grid STRUCTURE layer (FR-27, and the A/B wipe).
//
// The wipe has to make "16,000,000 vs 705,771" visible. Those are grid
// CAPACITY numbers, not occupied-return counts — a scan lights up only ~6%
// of either grid, so contrasting coloured cells cannot show the ratio.
// What differs is the grid itself: uniform cells stay 5 cm out to 100 m,
// adaptive cells grow with range.
//
// Drawing that as instances is impossible and, worse, misleading. 16,000,000
// quads will not render; sampling them down makes the uniform side look
// SPARSER than the adaptive side, inverting the argument. So the boundaries
// are drawn procedurally in a fragment shader instead: every cell edge, at
// true position, one draw call, correct at any zoom. Where cells fall below
// one pixel the lines blend into a wash — which is not a rendering artifact
// but the honest visual consequence of 16 million cells, and is exactly the
// contrast the demo is claiming.
//
// The ring maths mirrors ringGeometry.ts, which mirrors core/grid.py.

import * as THREE from 'three';

export type GridKind = 'uniform' | 'adaptive';

// Kept in TS only where TS needs them. The GLSL below hard-codes the same
// §3 constants as literals — WebGL1 has no way to share them, so if
// ringGeometry.ts ever changes, the shader constants must change with it.
const S_MIN = 0.05;
const R_MAX = 100.0;

const VERT = /* glsl */ `
varying vec2 vWorld;
void main() {
  vec4 world = modelMatrix * vec4(position, 1.0);
  vWorld = world.xz;                 // ground plane: Three is Y-up
  gl_Position = projectionMatrix * viewMatrix * world;
}
`;

const FRAG = /* glsl */ `
precision highp float;

varying vec2 vWorld;

uniform int   uKind;        // 0 = uniform lattice, 1 = adaptive ring-sector
uniform vec3  uColour;
uniform float uOpacity;

const float S_MIN   = 0.050000;
const float S_MAX   = 0.500000;
const float R_KNEE  = 10.000000;
const float R_MAX   = 100.000000;
const float N_INNER = 200.0;
const float RATIO   = 1.00500000;
const float TAU     = 6.28318530718;

/**
 * Analytically-filtered grid coverage.
 *
 * 'coord' is measured in CELL INDICES, so a boundary sits at every integer.
 * Dividing distance-to-boundary by fwidth(coord) — the change in index across
 * one pixel — makes each line exactly one pixel wide at any zoom, and makes
 * coverage saturate once cells fall below a pixel. That saturation IS the
 * wash: it is what 16,000,000 cells honestly look like from 100 m up, and it
 * is reached by filtering rather than by aliasing.
 *
 * Doing this on raw world distances instead produces moire — a false coarse
 * pattern that makes a 5 cm grid and a 50 cm grid look alike.
 */
float gridCoverage(vec2 coord, vec2 deriv) {
  vec2 d = abs(fract(coord - 0.5) - 0.5) / max(deriv, vec2(1e-6));
  return 1.0 - min(min(d.x, d.y), 1.0);
}

void main() {
  float r = length(vWorld);
  if (r > R_MAX) discard;

  float cov;

  if (uKind == 0) {
    // ── Uniform 5 cm lattice: index space is world / cell size ───
    // The derivative is taken on the WORLD coordinate and scaled, not on the
    // index coordinate. They are equal in exact arithmetic, but the index
    // reaches 2000 at the envelope edge, and fwidth() of numbers that large
    // loses enough mantissa to make the pattern drop out entirely.
    cov = gridCoverage(vWorld / S_MIN, fwidth(vWorld) / S_MIN);
  } else {
    // ── Adaptive ring-sector grid ────────────────────────────────
    // Continuous ring coordinate: integer at every ring boundary, rising by
    // exactly 1 per ring. Same branch as RingGrid.ring_of.
    float ringCoord = (r <= R_KNEE)
      ? r / S_MIN
      : N_INNER + log(r / R_KNEE) / log(RATIO);

    // Bin count for the ring we are inside, from its INNER edge.
    float k = floor(ringCoord);
    float rInner = (k < N_INNER) ? k * S_MIN : R_KNEE * pow(RATIO, k - N_INNER);
    float s = (rInner <= R_KNEE) ? S_MIN : min(S_MIN * (rInner / R_KNEE), S_MAX);
    float nBins = max(1.0, floor(TAU * rInner / s + 0.5));

    float theta = atan(vWorld.y, vWorld.x);
    if (theta < 0.0) theta += TAU;

    // Continuous bin coordinate: integer at every sector boundary.
    float binCoord = theta * nBins / TAU;

    // Ring and bin indices stay under ~1300, so fwidth on them is safe.
    cov = gridCoverage(vec2(ringCoord, binCoord), fwidth(vec2(ringCoord, binCoord)));
  }

  if (cov <= 0.002) discard;
  gl_FragColor = vec4(uColour, cov * uOpacity);
}
`;

export interface GridLayer {
  mesh: THREE.Mesh;
  setKind: (kind: GridKind) => void;
  dispose: () => void;
}

/**
 * Each grid is tinted to match its number in the wipe labels, so a viewer can
 * tell at a glance which half they are looking at — and so a screenshot is
 * self-evidencing rather than needing a caption.
 */
export const GRID_COLOUR: Record<GridKind, number> = {
  uniform: 0xff8a80,    // matches the 16,000,000 label
  adaptive: 0x69f0ae,   // matches the 705,771 label
};

/**
 * A ground-plane layer that draws one grid's cell boundaries.
 * Sits just below y = 0 so it never z-fights the cell instances above it.
 */
export function createGridLayer(kind: GridKind): GridLayer {
  const geometry = new THREE.PlaneGeometry(2 * R_MAX, 2 * R_MAX);
  geometry.rotateX(-Math.PI / 2);

  const material = new THREE.ShaderMaterial({
    vertexShader: VERT,
    fragmentShader: FRAG,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    uniforms: {
      uKind: { value: kind === 'uniform' ? 0 : 1 },
      uColour: { value: new THREE.Color(GRID_COLOUR[kind]) },
      uOpacity: { value: 0.55 },
    },
  });

  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.y = -0.02;
  mesh.frustumCulled = false;
  mesh.renderOrder = -1;

  return {
    mesh,
    setKind: (k) => {
      material.uniforms.uKind.value = k === 'uniform' ? 0 : 1;
      (material.uniforms.uColour.value as THREE.Color).setHex(GRID_COLOUR[k]);
    },
    dispose: () => {
      geometry.dispose();
      material.dispose();
    },
  };
}

/** Headline capacities — what the wipe labels read. */
export const GRID_CAPACITY = {
  uniform: Math.round(Math.pow((2 * R_MAX) / S_MIN, 2)),   // 16,000,000
  adaptive: 705_771,
} as const;

export const REDUCTION_FACTOR = GRID_CAPACITY.uniform / GRID_CAPACITY.adaptive;
