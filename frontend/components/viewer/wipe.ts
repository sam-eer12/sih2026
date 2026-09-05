// wipe.ts — the A/B comparison wipe. THE MONEY SHOT.
//
// Same scan, same camera, same frame_id, split by a draggable divider:
// uniform 5 cm on the left, AVR-25D adaptive on the right. The claim it has
// to make visible is 16,000,000 vs 705,771 — grid CAPACITY, not occupied
// returns (a scan lights up only ~6% of either grid, so coloured cells alone
// cannot show the ratio; see gridShader.ts).
//
// Implemented as two scissored renders of ONE scene graph, per the brief.
// Two canvases would double the WebGL context cost for no benefit.

import * as THREE from 'three';
import type { ViewObjects } from './views';
import type { GridLayer } from './gridShader';

const HANDLE_GRAB_PX = 14;   // how close the pointer must be to grab the divider

export interface WipeController {
  readonly enabled: boolean;
  readonly divider: number;              // 0..1 across the canvas
  setEnabled: (on: boolean) => void;
  setDivider: (x: number) => void;
  onDividerChange: (cb: (x: number) => void) => void;
  /** Fires on drag start/end — item 21 wants proof the drag drops no frames. */
  onDragStateChange: (cb: (dragging: boolean) => void) => void;
  /** Draw both sides. Returns false if the wipe is off and the caller should render normally. */
  render: (
    renderer: THREE.WebGLRenderer,
    scene: THREE.Scene,
    camera: THREE.Camera,
    objects: ViewObjects,
    grid: GridLayer
  ) => boolean;
  dispose: () => void;
}

export function createWipe(
  canvas: HTMLCanvasElement,
  controls: { enabled: boolean }
): WipeController {
  let enabled = false;
  let divider = 0.5;
  let dragging = false;
  let notify: ((x: number) => void) | null = null;
  let notifyDrag: ((dragging: boolean) => void) | null = null;

  function dividerPx(): number {
    return divider * canvas.clientWidth;
  }

  function setDivider(x: number) {
    divider = Math.min(0.98, Math.max(0.02, x));
    notify?.(divider);
  }

  function onPointerDown(e: PointerEvent) {
    if (!enabled) return;
    if (Math.abs(e.offsetX - dividerPx()) > HANDLE_GRAB_PX) return;
    dragging = true;
    notifyDrag?.(true);
    // Orbit must yield while dragging, or the camera spins under the divider.
    controls.enabled = false;
    canvas.setPointerCapture(e.pointerId);
    e.preventDefault();
  }

  function onPointerMove(e: PointerEvent) {
    if (!enabled) return;
    if (!dragging) {
      // Hint that the divider is grabbable before the user commits.
      canvas.style.cursor =
        Math.abs(e.offsetX - dividerPx()) <= HANDLE_GRAB_PX ? 'ew-resize' : '';
      return;
    }
    setDivider(e.offsetX / canvas.clientWidth);
    e.preventDefault();
  }

  function onPointerUp(e: PointerEvent) {
    if (!dragging) return;
    dragging = false;
    notifyDrag?.(false);
    controls.enabled = true;
    if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
  }

  canvas.addEventListener('pointerdown', onPointerDown);
  canvas.addEventListener('pointermove', onPointerMove);
  canvas.addEventListener('pointerup', onPointerUp);
  canvas.addEventListener('pointercancel', onPointerUp);

  function showUniform(objects: ViewObjects, grid: GridLayer) {
    grid.setKind('uniform');
    if (objects.uniformMesh.current) objects.uniformMesh.current.visible = true;
    if (objects.cellMesh.current) objects.cellMesh.current.visible = false;
    if (objects.pointCloud.current) objects.pointCloud.current.visible = false;
  }

  function showAdaptive(objects: ViewObjects, grid: GridLayer) {
    grid.setKind('adaptive');
    if (objects.uniformMesh.current) objects.uniformMesh.current.visible = false;
    if (objects.cellMesh.current) objects.cellMesh.current.visible = true;
    if (objects.pointCloud.current) objects.pointCloud.current.visible = false;
  }

  return {
    get enabled() { return enabled; },
    get divider() { return divider; },
    setEnabled: (on) => {
      enabled = on;
      if (!on) {
        dragging = false;
        controls.enabled = true;
        canvas.style.cursor = '';
      }
    },
    setDivider,
    onDividerChange: (cb) => { notify = cb; },
    onDragStateChange: (cb) => { notifyDrag = cb; },

    render: (renderer, scene, camera, objects, grid) => {
      if (!enabled) return false;

      // CSS pixels, NOT buffer pixels. Three multiplies setScissor/setViewport
      // by the renderer's pixelRatio internally, so passing domElement.width
      // (already buffer pixels) doubles everything on a 2x display: the split
      // lands at twice the divider's position and the DOM divider line no
      // longer matches the seam it is supposed to mark.
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      const splitPx = Math.round(divider * w);

      renderer.setScissorTest(true);
      renderer.setViewport(0, 0, w, h);   // full viewport both times; only the scissor differs

      // LEFT — uniform 5 cm
      renderer.setScissor(0, 0, splitPx, h);
      showUniform(objects, grid);
      renderer.render(scene, camera);

      // RIGHT — AVR-25D adaptive
      renderer.setScissor(splitPx, 0, w - splitPx, h);
      showAdaptive(objects, grid);
      renderer.render(scene, camera);

      // Leaving scissor on would clip every later render, including the next
      // frame's non-wipe path.
      renderer.setScissorTest(false);
      return true;
    },

    dispose: () => {
      canvas.removeEventListener('pointerdown', onPointerDown);
      canvas.removeEventListener('pointermove', onPointerMove);
      canvas.removeEventListener('pointerup', onPointerUp);
      canvas.removeEventListener('pointercancel', onPointerUp);
      canvas.style.cursor = '';
    },
  };
}
