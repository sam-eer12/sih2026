// pointCloud.ts — View 1, the raw cloud.
//
// NOTE ON FIDELITY: the FrameMessage does not carry raw LiDAR returns — the
// wire format is already aggregated to cells (see protocol.py). So View 1
// renders one point per occupied cell, at the cell centre and obstacle top.
// At demo zoom this is visually indistinguishable from the raw scan, and it
// is the documented R-4 fallback anyway. If a judge asks for genuinely raw
// points, Anuj has to add a points array to the protocol.

import * as THREE from 'three';
import { RING_RADIUS, RING_DTHETA } from './ringGeometry';
import { writeCellColour, type ColourMode } from './colouring';
import type { CellArrays } from './types';

const _colour = new THREE.Color();

export interface PointsRef {
  current: THREE.Points | null;
}

function allocate(scene: THREE.Scene, ref: PointsRef, capacity: number): THREE.Points {
  disposePoints(scene, ref);

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    'position',
    new THREE.BufferAttribute(new Float32Array(capacity * 3), 3).setUsage(THREE.DynamicDrawUsage)
  );
  geometry.setAttribute(
    'color',
    new THREE.BufferAttribute(new Float32Array(capacity * 3), 3).setUsage(THREE.DynamicDrawUsage)
  );

  const material = new THREE.PointsMaterial({
    size: 0.25,
    sizeAttenuation: true,
    vertexColors: true,
  });

  const points = new THREE.Points(geometry, material);
  points.frustumCulled = false;
  scene.add(points);
  ref.current = points;
  return points;
}

/** Update the point cloud from cell data. Same allocation discipline as the mesh. */
export function updatePoints(
  scene: THREE.Scene,
  ref: PointsRef,
  cells: CellArrays,
  mode: ColourMode
): void {
  const n = cells.n;
  let points = ref.current;
  const capacity = points
    ? (points.geometry.getAttribute('position') as THREE.BufferAttribute).count
    : 0;

  if (!points || n > capacity) {
    let cap = 1;
    while (cap < n) cap *= 2;
    points = allocate(scene, ref, cap);
  }

  const posAttr = points.geometry.getAttribute('position') as THREE.BufferAttribute;
  const colAttr = points.geometry.getAttribute('color') as THREE.BufferAttribute;
  const pos = posAttr.array as Float32Array;
  const col = colAttr.array as Float32Array;

  const { ring, bin, z_ground, z_obstacle, class_id } = cells;

  for (let i = 0; i < n; i++) {
    const k = ring[i];
    const r = RING_RADIUS[k];
    const theta = (bin[i] + 0.5) * RING_DTHETA[k];

    const zObs = z_obstacle[i];
    const zTop = Number.isNaN(zObs) ? z_ground[i] : zObs;

    const o = i * 3;
    pos[o] = r * Math.cos(theta);
    pos[o + 1] = zTop;              // Three is Y-up
    pos[o + 2] = r * Math.sin(theta);

    writeCellColour(_colour, mode, class_id[i], zTop);
    col[o] = _colour.r;
    col[o + 1] = _colour.g;
    col[o + 2] = _colour.b;
  }

  points.geometry.setDrawRange(0, n);
  posAttr.needsUpdate = true;
  colAttr.needsUpdate = true;
}

export function disposePoints(scene: THREE.Scene, ref: PointsRef): void {
  const points = ref.current;
  if (!points) return;
  scene.remove(points);
  points.geometry.dispose();
  (points.material as THREE.Material).dispose();
  ref.current = null;
}
