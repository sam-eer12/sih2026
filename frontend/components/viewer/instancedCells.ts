// instancedCells.ts — Module 3
// Takes decoded cells from a FrameMessage and writes per-instance
// transform matrices and colours into a THREE.InstancedMesh.
// One draw call for the whole grid.

import * as THREE from 'three';
import { RING_RADIUS, RING_DTHETA, RING_EXTENT_R, RING_EXTENT_T } from './ringGeometry';
import { writeCellColour, type ColourMode } from './colouring';
import type { CellArrays } from './types';

const _dummy = new THREE.Object3D();
const _colour = new THREE.Color();

const MIN_HEIGHT = 0.1;      // m — flat cells still need to be visible

export interface MeshRef {
  current: THREE.InstancedMesh | null;
}

/** Current allocated capacity, which is NOT mesh.count (that is the draw count). */
function capacityOf(mesh: THREE.InstancedMesh | null): number {
  return mesh ? mesh.instanceMatrix.count : 0;
}

function allocate(
  scene: THREE.Scene,
  meshRef: MeshRef,
  capacity: number
): THREE.InstancedMesh {
  disposeCells(scene, meshRef);

  const geometry = new THREE.BoxGeometry(1, 1, 1);
  const material = new THREE.MeshLambertMaterial();
  const mesh = new THREE.InstancedMesh(geometry, material, capacity);
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);

  // Instance positions are written on the CPU and the bounding sphere is
  // never recomputed, so Three's stale-sphere frustum test would cull the
  // whole mesh the moment the camera moves. One draw call is cheap enough
  // that culling buys nothing here anyway.
  mesh.frustumCulled = false;

  scene.add(mesh);
  meshRef.current = mesh;
  return mesh;
}

/**
 * Update the InstancedMesh with new cell data.
 *
 * Reallocates ONLY when n exceeds the current capacity, growing in powers
 * of two. Never allocates per frame.
 */
export function updateCells(
  scene: THREE.Scene,
  meshRef: MeshRef,
  cells: CellArrays,
  colourMode: ColourMode = 'class'
): void {
  const n = cells.n;
  let mesh = meshRef.current;

  // Compare against real capacity, not mesh.count — mesh.count is reset to n
  // at the end of every call, so using it here would rebuild the mesh on any
  // frame that grew by even one cell, leaking a geometry each time.
  if (!mesh || n > capacityOf(mesh)) {
    let capacity = 1;
    while (capacity < n) capacity *= 2;
    mesh = allocate(scene, meshRef, capacity);
  }

  const { ring, bin, z_ground, z_obstacle, class_id } = cells;

  for (let i = 0; i < n; i++) {
    const k = ring[i];

    // Cell centre in LiDAR frame: x forward, y lateral.
    const r = RING_RADIUS[k];
    const theta = (bin[i] + 0.5) * RING_DTHETA[k];
    const x = r * Math.cos(theta);
    const y = r * Math.sin(theta);

    const zGround = z_ground[i];
    const zObs = z_obstacle[i];
    const height = Number.isNaN(zObs) ? MIN_HEIGHT : Math.max(zObs - zGround, MIN_HEIGHT);

    // LiDAR (x, y, z) → Three (x, z, y): Three is Y-up.
    _dummy.position.set(x, zGround + height / 2, y);

    // The box is axis-aligned, so it must be rotated to sit along the ring's
    // tangent — otherwise far-field cells (0.5 m radial × 0.5 m tangential)
    // point the wrong way and the grid looks like scattered confetti.
    _dummy.rotation.set(0, -theta, 0);
    _dummy.scale.set(RING_EXTENT_R[k], height, RING_EXTENT_T[k]);
    _dummy.updateMatrix();
    mesh.setMatrixAt(i, _dummy.matrix);

    writeCellColour(_colour, colourMode, class_id[i], zGround + height);
    mesh.setColorAt(i, _colour);
  }

  mesh.count = n;
  mesh.instanceMatrix.needsUpdate = true;
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
}

/** Remove and free the instanced mesh. Called on realloc and on teardown. */
export function disposeCells(scene: THREE.Scene, meshRef: MeshRef): void {
  const mesh = meshRef.current;
  if (!mesh) return;
  scene.remove(mesh);
  mesh.geometry.dispose();
  (mesh.material as THREE.Material).dispose();
  mesh.dispose();
  meshRef.current = null;
}
