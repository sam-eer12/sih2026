// views.ts — Module 5. The four views of FR-25.
//
//   View 1  raw       — point cloud, one point per cell
//   View 2  uniform   — the 5 cm uniform grid (Day 4, not built yet)
//   View 3  adaptive  — the AVR-25D instanced grid          ← default
//   View 4  decision  — tracks, routes, risk shading (Days 7-8)
//
// Switching a view only flips `visible` and re-renders the last frame into
// the newly-active representation. Nothing is reallocated, so a view change
// costs one frame's worth of buffer writes and never a GPU stall.

import * as THREE from 'three';
import { updateCells, disposeCells, type MeshRef } from './instancedCells';
import { updatePoints, disposePoints, type PointsRef } from './pointCloud';
import type { ColourMode } from './colouring';
import type { CellArrays } from './types';

export type ViewMode = 'raw' | 'uniform' | 'adaptive' | 'decision';

export interface ViewObjects {
  cellMesh: MeshRef;
  pointCloud: PointsRef;
}

export function createViewObjects(): ViewObjects {
  return { cellMesh: { current: null }, pointCloud: { current: null } };
}

/** Which representation does this view draw with? */
function representationOf(view: ViewMode): 'points' | 'cells' {
  return view === 'raw' ? 'points' : 'cells';
}

/**
 * Write a frame into whichever representation the active view needs.
 * The inactive one is left untouched — updating both would double the
 * per-frame CPU cost for something nobody is looking at.
 */
export function renderFrame(
  scene: THREE.Scene,
  objects: ViewObjects,
  view: ViewMode,
  cells: CellArrays,
  colourMode: ColourMode
): void {
  if (representationOf(view) === 'points') {
    updatePoints(scene, objects.pointCloud, cells, colourMode);
  } else {
    updateCells(scene, objects.cellMesh, cells, colourMode);
  }
  applyVisibility(objects, view);
}

/** Show the active representation, hide the rest. */
export function applyVisibility(objects: ViewObjects, view: ViewMode): void {
  const wantPoints = representationOf(view) === 'points';
  if (objects.pointCloud.current) objects.pointCloud.current.visible = wantPoints;
  if (objects.cellMesh.current) objects.cellMesh.current.visible = !wantPoints;
}

export function disposeViewObjects(scene: THREE.Scene, objects: ViewObjects): void {
  disposeCells(scene, objects.cellMesh);
  disposePoints(scene, objects.pointCloud);
}
