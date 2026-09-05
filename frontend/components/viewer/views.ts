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
import {
  updateUniform,
  disposeUniform,
  uniformStats,
  type UniformRef,
  type UniformStats,
} from './uniformGrid';
import type { ColourMode } from './colouring';
import { createDecisionLayer, type DecisionLayer } from './decisionLayer';
import type { CellArrays, FrameMessage } from './types';

export type ViewMode = 'raw' | 'uniform' | 'adaptive' | 'decision';

export interface ViewObjects {
  cellMesh: MeshRef;
  pointCloud: PointsRef;
  uniformMesh: UniformRef;
  decision: DecisionLayer;
}

export function createViewObjects(scene: THREE.Scene): ViewObjects {
  const decision = createDecisionLayer();
  scene.add(decision.group);
  return {
    cellMesh: { current: null },
    pointCloud: { current: null },
    uniformMesh: { current: null },
    decision,
  };
}

type Representation = 'points' | 'cells' | 'uniform';

/** Which representation does this view draw with? */
function representationOf(view: ViewMode): Representation {
  if (view === 'raw') return 'points';
  if (view === 'uniform') return 'uniform';
  return 'cells';   // 'adaptive' and 'decision' both draw the adaptive grid
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
  const rep = representationOf(view);
  if (rep === 'points') updatePoints(scene, objects.pointCloud, cells, colourMode);
  else if (rep === 'uniform') updateUniform(scene, objects.uniformMesh, cells, colourMode);
  else updateCells(scene, objects.cellMesh, cells, colourMode);
  applyVisibility(objects, view);
}

/** Routes, tracks and risk — only meaningful in View 4. */
export function renderDecision(
  objects: ViewObjects,
  view: ViewMode,
  msg: FrameMessage
): void {
  if (view === 'decision') objects.decision.update(msg);
}

/**
 * The wipe shows both representations of the SAME frame simultaneously
 * (T-V5), so both buffers must be current. Costs roughly double the per-frame
 * write — watch `push` in the perf report when this is on.
 */
export function renderBothForWipe(
  scene: THREE.Scene,
  objects: ViewObjects,
  cells: CellArrays,
  colourMode: ColourMode
): void {
  updateCells(scene, objects.cellMesh, cells, colourMode);
  updateUniform(scene, objects.uniformMesh, cells, colourMode);
}

/** Show the active representation, hide the rest. */
export function applyVisibility(objects: ViewObjects, view: ViewMode): void {
  const rep = representationOf(view);
  if (objects.pointCloud.current) objects.pointCloud.current.visible = rep === 'points';
  if (objects.cellMesh.current) objects.cellMesh.current.visible = rep === 'cells';
  if (objects.uniformMesh.current) objects.uniformMesh.current.visible = rep === 'uniform';
  objects.decision.setVisible(view === 'decision');
}

/** Cell counts for the uniform view — the 16,000,000 side of the wipe. */
export function uniformCounts(objects: ViewObjects): UniformStats {
  return uniformStats(objects.uniformMesh);
}

export function disposeViewObjects(scene: THREE.Scene, objects: ViewObjects): void {
  disposeCells(scene, objects.cellMesh);
  disposePoints(scene, objects.pointCloud);
  disposeUniform(scene, objects.uniformMesh);
  scene.remove(objects.decision.group);
  objects.decision.dispose();
}
