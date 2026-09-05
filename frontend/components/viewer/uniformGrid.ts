// uniformGrid.ts — View 2, the uniform 5 cm grid.
//
// This view exists for one reason: to make "22.67× reduction" something a
// judge watches rather than reads. It resamples THE SAME SCAN onto a flat
// 5 cm lattice and renders it beside the adaptive grid.
//
// ── What is actually drawn, and why it is not 16,000,000 boxes ────────
//
// The uniform 5 cm baseline over the 200 m envelope is 4000 × 4000 =
// 16,000,000 cells (see bench/baselines.py — 400 MB at 25 B/cell). Nothing
// renders that many instances at 30 FPS, and it would be pointless if it
// could: at demo zoom a 5 cm cell is far smaller than one pixel.
//
// So the lattice is built over the scan's actual footprint and stride-sampled
// down to an instance budget, at TRUE 5 cm cell size. The visual claim is
// "cells this small, everywhere, at every range" — which is the honest claim,
// and the one that contrasts with the adaptive grid. Every count is reported
// separately by stats(): what is drawn, what the footprint holds, and the
// 16,000,000 analytic total. Never show the drawn count as the headline.

import * as THREE from 'three';
import {
  cellIdOfPoint,
  N_CELLS,
  R_OUTER,
  RING_RADIUS,
  RING_DTHETA,
} from './ringGeometry';
import { writeCellColour, type ColourMode } from './colouring';
import type { CellArrays } from './types';

export const UNIFORM_CELL_SIZE = 0.05;   // m — the 5 cm baseline

/** The analytic headline: 4000 × 4000 over the 200 m envelope. */
export const UNIFORM_TOTAL_CELLS = Math.round(
  Math.pow((2 * 100.0) / UNIFORM_CELL_SIZE, 2)
);   // 16,000,000

/**
 * Instances we are willing to draw, tuned against the perf meter.
 *
 * This must be high enough to leave the stride at 1 over the scan footprint.
 * Any stride > 1 scatters the uniform cells into isolated dots — one adaptive
 * far-field cell covers ~100 uniform cells, so drawing 1 in 9 of them makes
 * the uniform side look SPARSER than the adaptive side, which argues the
 * exact opposite of the 22.67x claim. Contiguity is the whole point: the
 * uniform side has to read as a fine dense mosaic.
 */
const DEFAULT_BUDGET = 1_600_000;

const _dummy = new THREE.Object3D();
const _colour = new THREE.Color();

export interface UniformRef {
  current: THREE.InstancedMesh | null;
}

interface Lattice {
  x: Float32Array;
  y: Float32Array;
  cellId: Int32Array;    // adaptive cell covering each site, -1 if outside
  n: number;             // sites actually kept (after stride)
  footprintSites: number; // true 5 cm sites over the footprint, before stride
  stride: number;
}

let _lattice: Lattice | null = null;

// cell_id → index into the current frame's arrays. Allocated once; 2.8 MB.
const _cellIndex = new Int32Array(N_CELLS);

/**
 * Build the lattice over the footprint of a representative frame.
 * Done once — the sensor frame does not move, so the lattice does not either.
 */
function buildLattice(cells: CellArrays, budget: number): Lattice {
  // Footprint = bounding box of the occupied cells, clipped to the envelope.
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  const { ring, bin } = cells;

  for (let i = 0; i < cells.n; i++) {
    const k = ring[i];
    const r = RING_RADIUS[k];
    const theta = (bin[i] + 0.5) * RING_DTHETA[k];
    const x = r * Math.cos(theta);
    const y = r * Math.sin(theta);
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  }

  const lim = R_OUTER;
  minX = Math.max(minX, -lim); maxX = Math.min(maxX, lim);
  minY = Math.max(minY, -lim); maxY = Math.min(maxY, lim);

  const nx = Math.max(1, Math.ceil((maxX - minX) / UNIFORM_CELL_SIZE));
  const ny = Math.max(1, Math.ceil((maxY - minY) / UNIFORM_CELL_SIZE));
  const footprintSites = nx * ny;

  // Stride equally in both axes so the sample stays isotropic — striding one
  // axis only would read as stripes, not as a grid.
  const stride = Math.max(1, Math.ceil(Math.sqrt(footprintSites / budget)));

  const sx = Math.ceil(nx / stride);
  const sy = Math.ceil(ny / stride);
  const cap = sx * sy;

  const x = new Float32Array(cap);
  const y = new Float32Array(cap);
  const cellId = new Int32Array(cap);

  let n = 0;
  for (let iy = 0; iy < ny; iy += stride) {
    const wy = minY + (iy + 0.5) * UNIFORM_CELL_SIZE;
    for (let ix = 0; ix < nx; ix += stride) {
      const wx = minX + (ix + 0.5) * UNIFORM_CELL_SIZE;
      const id = cellIdOfPoint(wx, wy);
      if (id < 0) continue;          // outside the 100 m envelope
      x[n] = wx;
      y[n] = wy;
      cellId[n] = id;
      n++;
    }
  }

  return { x, y, cellId, n, footprintSites, stride };
}

function allocate(scene: THREE.Scene, ref: UniformRef, capacity: number): THREE.InstancedMesh {
  disposeUniform(scene, ref);
  const geometry = new THREE.BoxGeometry(1, 1, 1);
  const material = new THREE.MeshLambertMaterial();
  const mesh = new THREE.InstancedMesh(geometry, material, capacity);
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  mesh.frustumCulled = false;
  scene.add(mesh);
  ref.current = mesh;
  return mesh;
}

/** Resample the frame onto the uniform lattice and write it to the GPU. */
export function updateUniform(
  scene: THREE.Scene,
  ref: UniformRef,
  cells: CellArrays,
  colourMode: ColourMode,
  budget: number = DEFAULT_BUDGET
): void {
  if (!_lattice) _lattice = buildLattice(cells, budget);
  const lat = _lattice;

  let mesh = ref.current;
  if (!mesh || lat.n > mesh.instanceMatrix.count) {
    let cap = 1;
    while (cap < lat.n) cap *= 2;
    mesh = allocate(scene, ref, cap);
  }

  // Invert the frame's cell list so a lattice site can find its cell in O(1).
  _cellIndex.fill(-1);
  for (let i = 0; i < cells.n; i++) _cellIndex[cells.cell_id[i]] = i;

  const { z_ground, z_obstacle, class_id } = cells;

  let drawn = 0;
  for (let i = 0; i < lat.n; i++) {
    const idx = _cellIndex[lat.cellId[i]];
    if (idx < 0) continue;           // that cell was not occupied this frame

    const zGround = z_ground[idx];
    const zObs = z_obstacle[idx];
    const height = Number.isNaN(zObs) ? 0.1 : Math.max(zObs - zGround, 0.1);

    _dummy.position.set(lat.x[i], zGround + height / 2, lat.y[i]);
    _dummy.rotation.set(0, 0, 0);    // axis-aligned: that is the whole point
    _dummy.scale.set(UNIFORM_CELL_SIZE, height, UNIFORM_CELL_SIZE);
    _dummy.updateMatrix();
    mesh.setMatrixAt(drawn, _dummy.matrix);

    writeCellColour(_colour, colourMode, class_id[idx], zGround + height);
    mesh.setColorAt(drawn, _colour);
    drawn++;
  }

  mesh.count = drawn;
  mesh.instanceMatrix.needsUpdate = true;
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
}

export interface UniformStats {
  drawn: number;
  footprintSites: number;
  analyticTotal: number;
  stride: number;
}

export function uniformStats(ref: UniformRef): UniformStats {
  return {
    drawn: ref.current?.count ?? 0,
    footprintSites: _lattice?.footprintSites ?? 0,
    analyticTotal: UNIFORM_TOTAL_CELLS,
    stride: _lattice?.stride ?? 0,
  };
}

export function disposeUniform(scene: THREE.Scene, ref: UniformRef): void {
  const mesh = ref.current;
  if (!mesh) return;
  scene.remove(mesh);
  mesh.geometry.dispose();
  (mesh.material as THREE.Material).dispose();
  mesh.dispose();
  ref.current = null;
}
