// devFrames.ts — TEMPORARY dev-only frame source.
//
// Synthesises schema-valid CellArrays in the browser so the viewer can be
// built and verified before Navya's lib/protocol.ts and lib/ws.ts exist.
// The scene mirrors avr25d/server/fixtures.py: a flat road forward along x,
// terrain either side, static obstacles, one dynamic object crossing.
//
// DELETE THIS DIRECTORY once the real WebSocket stream is wired up.
// Nothing outside components/viewer/__dev__/ may import from it.

import {
  N_RINGS,
  RING_BINS,
  RING_RADIUS,
  RING_DTHETA,
  RING_OFFSET,
} from '../ringGeometry';
import type { CellArrays, FrameMessage } from '../types';

const DRIVE = 1, TERRAIN = 2, STATIC = 3, DYNAMIC = 4;

const R_VISIBLE = 60.0;   // m — how far the synthetic scan reaches

// Cell density relative to a full scan. 0.2 yields ~43,900 cells/frame,
// matching the ~42,000 the real fixture server emits. Raise to 0.5 for
// ~109,000 cells — the T-V6 stress target of 100k instances at >=30 FPS.
const DEFAULT_DENSITY = 0.2;
const ROAD_HALF = 4.0;    // m — drivable corridor half-width
const TERRAIN_HALF = 14.0;

interface StaticBox { x: number; y: number; hx: number; hy: number; h: number; }

const STATIC_BOXES: StaticBox[] = [
  { x: 18, y: 9.0, hx: 3.0, hy: 1.5, h: 2.5 },
  { x: 34, y: -8.5, hx: 2.0, hy: 2.0, h: 3.5 },
  { x: 47, y: 7.5, hx: 4.0, hy: 1.5, h: 2.0 },
  { x: -12, y: 8.0, hx: 2.5, hy: 2.5, h: 4.0 },
];

/** Build the fixed part of the scene once — ring/bin indices never change. */
function buildStaticScene(density: number) {
  const ring: number[] = [];
  const bin: number[] = [];
  const cx: number[] = [];
  const cy: number[] = [];

  for (let k = 1; k < N_RINGS; k++) {
    const r = RING_RADIUS[k];
    if (r > R_VISIBLE) break;

    const nBins = RING_BINS[k];
    const dTheta = RING_DTHETA[k];

    // Far rings are dense; subsample so the browser-side generator stays
    // fast. The real pipeline emits every occupied cell.
    const step = Math.max(1, Math.round((r < 12 ? 4 : 1) / density));

    for (let j = 0; j < nBins; j += step) {
      const theta = (j + 0.5) * dTheta;
      const x = r * Math.cos(theta);
      const y = r * Math.sin(theta);
      if (Math.abs(y) > TERRAIN_HALF) continue;
      ring.push(k);
      bin.push(j);
      cx.push(x);
      cy.push(y);
    }
  }

  return {
    ring: Uint16Array.from(ring),
    bin: Uint16Array.from(bin),
    cx: Float32Array.from(cx),
    cy: Float32Array.from(cy),
    n: ring.length,
  };
}

const SCENE = buildStaticScene(
  Number(process.env.NEXT_PUBLIC_DEV_DENSITY) || DEFAULT_DENSITY
);

function classify(x: number, y: number, truckY: number): [number, number] {
  // Dynamic object: a truck-sized box crossing the road.
  if (Math.abs(x - 25) < 2.5 && Math.abs(y - truckY) < 4.0) return [DYNAMIC, 3.0];

  for (const b of STATIC_BOXES) {
    if (Math.abs(x - b.x) < b.hx && Math.abs(y - b.y) < b.hy) return [STATIC, b.h];
  }

  if (Math.abs(y) <= ROAD_HALF) return [DRIVE, 0];
  return [TERRAIN, 0.15];
}

/** Allocate the output arrays once and rewrite them in place each frame. */
const N = SCENE.n;
const _cells: CellArrays = {
  n: N,
  cell_id: new Uint32Array(N),
  ring: SCENE.ring,
  bin: SCENE.bin,
  z_ground: new Float32Array(N),
  z_obstacle: new Float32Array(N),
  roughness: new Float32Array(N),
  slope: new Float32Array(N),
  class_id: new Uint8Array(N),
  confidence: new Uint8Array(N).fill(200),
  flags: new Uint8Array(N),
};

for (let i = 0; i < N; i++) {
  _cells.cell_id[i] = RING_OFFSET[SCENE.ring[i]] + SCENE.bin[i];
}

function makeFrame(frameId: number, t: number): FrameMessage {
  const truckY = -30 + ((t * 8) % 60);   // crossing at 8 m/s

  for (let i = 0; i < N; i++) {
    const x = SCENE.cx[i];
    const y = SCENE.cy[i];
    const [cls, height] = classify(x, y, truckY);

    // Gentle undulation so elevation shading has something to show.
    const zGround = Math.sin(x * 0.05) * 0.25 + Math.cos(y * 0.08) * 0.1;

    _cells.class_id[i] = cls;
    _cells.z_ground[i] = zGround;
    _cells.z_obstacle[i] = height > 0 ? zGround + height : NaN;
    _cells.roughness[i] = cls === TERRAIN ? 0.12 : 0.02;
    _cells.slope[i] = 0.01;
  }

  return {
    frame_id: frameId,
    t_sec: t,
    mode: 'dev',
    cells: _cells,
    stats: { n_cells: N, fps: 30 },
  };
}

/** Start pushing synthetic frames at 30 Hz. Returns a stop function. */
export function startDevStream(push: (msg: FrameMessage) => void): () => void {
  let frameId = 0;
  const t0 = performance.now();
  console.log(`[devFrames] synthetic stream: ${N} cells/frame at 30 Hz`);

  const timer = window.setInterval(() => {
    push(makeFrame(frameId++, (performance.now() - t0) / 1000));
  }, 1000 / 30);

  return () => window.clearInterval(timer);
}

export const DEV_CELL_COUNT = N;
