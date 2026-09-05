// useThreeScene.ts — Module 2
// Creates renderer, scene, camera ONCE in a React effect keyed on [].
// Returns a ref to an imperative handle. Frames arrive via
// handle.pushFrame(msg) and are written straight into GPU buffers.
// React NEVER re-renders.

import { useRef, useEffect } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import {
  createViewObjects,
  renderFrame,
  applyVisibility,
  disposeViewObjects,
  uniformCounts,
  renderBothForWipe,
  renderDecision,
  type ViewMode,
} from './views';
import { createWipe } from './wipe';
import type { UniformStats } from './uniformGrid';
import { createGridLayer, GRID_CAPACITY, REDUCTION_FACTOR } from './gridShader';
import type { ColourMode } from './colouring';
import { PerfMeter, formatReport, type PerfReport } from './perfMeter';
import type { FrameMessage } from './types';

export type { ViewMode } from './views';
export type { ColourMode } from './colouring';

export interface SceneHandle {
  pushFrame: (msg: FrameMessage) => void;
  setView: (view: ViewMode) => void;
  getView: () => ViewMode;
  setColourMode: (mode: ColourMode) => void;
  getColourMode: () => ColourMode;
  /** Live frame timing — T-V6, and whatever the HUD wants to show. */
  getPerf: () => PerfReport;
  /** Frames pushed since mount — the denominator for T-W7. */
  getFrameCount: () => number;
  /** Uniform-grid cell counts — the 16,000,000 side of the A/B wipe. */
  getUniformCounts: () => UniformStats;
  /** Grid-structure overlay: the cell boundaries themselves (FR-27). */
  setGridOverlay: (on: boolean) => void;
  getGridOverlay: () => boolean;
  /** Capacity of the grid the active view represents — the headline number. */
  getGridCapacity: () => number;
  /** A/B wipe: uniform left, adaptive right, one scan, one camera. */
  setWipe: (on: boolean) => void;
  getWipe: () => boolean;
  setDivider: (x: number) => void;
  onDividerChange: (cb: (x: number) => void) => void;
  dispose: () => void;
}

export function useThreeScene(
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  onReady?: (handle: SceneHandle) => void
): React.RefObject<SceneHandle | null> {
  const handleRef = useRef<SceneHandle | null>(null);

  // Keep onReady in a ref so the effect stays keyed on [] — a changing
  // callback identity must never tear down the WebGL context.
  const onReadyRef = useRef(onReady);
  useEffect(() => {
    onReadyRef.current = onReady;
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // ── Create renderer, scene, camera ONCE ──────────────────────
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a1a2e);

    const camera = new THREE.PerspectiveCamera(
      60, canvas.clientWidth / canvas.clientHeight, 0.1, 500
    );
    camera.position.set(0, 80, 80);
    camera.lookAt(0, 0, 0);

    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;

    // NOTE: the skeleton's THREE.GridHelper(200, 200) is deliberately gone.
    // It drew a 1 m reference lattice — indistinguishable from a real grid,
    // and directly misleading in a view whose whole subject is cell size.
    // gridShader.ts draws the actual grid instead.

    // ── Lighting ─────────────────────────────────────────────────
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
    dirLight.position.set(50, 100, 50);
    scene.add(dirLight);

    // ── Renderable representations (Modules 3 and 5 write into these) ──
    const objects = createViewObjects(scene);

    // ── Grid-structure overlay ───────────────────────────────────
    // One shader plane; its kind follows the active view so the boundaries
    // always describe the grid you are looking at.
    const gridLayer = createGridLayer('adaptive');
    gridLayer.mesh.visible = false;
    scene.add(gridLayer.mesh);
    let gridOn = false;

    // ── A/B wipe ─────────────────────────────────────────────────
    const wipe = createWipe(canvas, controls);
    const WIPE_PUSH_INTERVAL_MS = 100;   // 10 Hz, both sides in lockstep
    let lastWipePushAt = 0;

    // Item 21: the divider must drag without dropping frames. Measure the
    // drag in isolation — a whole-session average would hide a stutter that
    // only happens while the pointer is down.
    let dividerDragging = false;
    let skippedWhileDragging = 0;
    wipe.onDragStateChange((dragging) => {
      dividerDragging = dragging;
      if (dragging) {
        meter.reset();
        return;
      }
      const r = meter.report();
      // Report the skip count too: if this reads 0, the drag-freeze is not
      // live (usually a stale Fast Refresh closure — the WebGL effect is
      // keyed on [] and does not re-run) and the numbers mean nothing.
      if (r.frames > 0) {
        console.log(
          `[perf/drag] ${formatReport(r)} · pushes skipped while dragging: ${skippedWhileDragging}`
        );
      }
      skippedWhileDragging = 0;
    });

    // ── Current view + colour mode ───────────────────────────────
    let currentView: ViewMode = 'adaptive';
    let colourMode: ColourMode = 'class';

    // The most recent frame, kept so switching view or colour mode can
    // repaint immediately instead of waiting up to 33 ms for the next one.
    let lastCells: FrameMessage['cells'] | null = null;
    let framesPushed = 0;

    function repaint() {
      if (lastCells) renderFrame(scene, objects, currentView, lastCells, colourMode);
      else applyVisibility(objects, currentView);
      gridLayer.setKind(currentView === 'uniform' ? 'uniform' : 'adaptive');
    }

    // ── Frame timing ─────────────────────────────────────────────
    const meter = new PerfMeter();

    // ── Animation loop — plain requestAnimationFrame, NOT React state ──
    let animId = 0;
    function animate(now: number) {
      animId = requestAnimationFrame(animate);
      meter.recordFrame(now);
      controls.update();
      // The wipe draws both sides itself; it returns false when disabled.
      if (!wipe.render(renderer, scene, camera, objects, gridLayer)) {
        renderer.render(scene, camera);
      }
    }
    animId = requestAnimationFrame(animate);

    // Report periodically in development. This is how T-V6 gets a number
    // instead of an adjective.
    let perfTimer = 0;
    if (process.env.NODE_ENV === 'development') {
      perfTimer = window.setInterval(() => {
        const r = meter.report();
        if (r.frames > 0) console.log(`[perf] ${formatReport(r)}`);
      }, 3000);
    }

    // ── Resize handler ───────────────────────────────────────────
    function onResize() {
      const w = canvas!.clientWidth;
      const h = canvas!.clientHeight;
      if (w === 0 || h === 0) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
    }
    // clientWidth is 0 until layout settles; observe the element itself
    // rather than relying on window resize alone.
    const resizeObserver = new ResizeObserver(onResize);
    resizeObserver.observe(canvas);
    window.addEventListener('resize', onResize);

    // ── Build the imperative handle ──────────────────────────────
    const handle: SceneHandle = {
      pushFrame: (msg) => {
        if (!msg?.cells) return;
        framesPushed++;
        lastCells = msg.cells;
        const t0 = performance.now();
        if (wipe.enabled) {
          // The wipe writes both representations — ~283k instances against a
          // 33 ms budget, which does not fit at the full stream rate. Stepping
          // both sides together at a lower rate keeps them on the SAME
          // frame_id (T-V5) and leaves the render loop free to orbit at 60 FPS,
          // since rendering is decoupled from pushing. Dropping the uniform
          // side alone would desynchronise the two halves.
          // Freeze while the divider is being dragged. Each dual push blocks
          // the main thread for ~22 ms, which stretches one frame in every ten
          // to ~33 ms — a visible hitch precisely when the user is studying
          // the comparison. The scan is not what they are looking at during a
          // drag, and a frozen frame keeps both halves on one frame_id anyway.
          if (dividerDragging) skippedWhileDragging++;
          if (!dividerDragging && t0 - lastWipePushAt >= WIPE_PUSH_INTERVAL_MS) {
            lastWipePushAt = t0;
            renderBothForWipe(scene, objects, msg.cells, colourMode);
            meter.recordPush(performance.now() - t0, msg.cells.n);
          }
        } else {
          renderFrame(scene, objects, currentView, msg.cells, colourMode);
          renderDecision(objects, currentView, msg);
          meter.recordPush(performance.now() - t0, msg.cells.n);
        }
      },
      setView: (view) => {
        if (view === currentView) return;
        currentView = view;
        repaint();
        meter.reset();   // stale frame times would misreport the new view
        if (process.env.NODE_ENV === 'development') {
          console.log(
            `[grid] ${view} capacity ${(view === 'uniform'
              ? GRID_CAPACITY.uniform
              : GRID_CAPACITY.adaptive
            ).toLocaleString()} cells · reduction ${REDUCTION_FACTOR.toFixed(2)}x`
          );
        }
        if (process.env.NODE_ENV === 'development' && view === 'uniform') {
          const u = uniformCounts(objects);
          console.log(
            `[uniform] drawing ${u.drawn.toLocaleString()} of ` +
            `${u.footprintSites.toLocaleString()} footprint sites ` +
            `(stride ${u.stride}) · analytic total ` +
            `${u.analyticTotal.toLocaleString()}`
          );
        }
      },
      getView: () => currentView,
      setColourMode: (mode) => {
        if (mode === colourMode) return;
        colourMode = mode;
        repaint();
      },
      getColourMode: () => colourMode,
      getPerf: () => meter.report(),
      getFrameCount: () => framesPushed,
      getUniformCounts: () => uniformCounts(objects),
      setGridOverlay: (on) => {
        gridOn = on;
        gridLayer.mesh.visible = on;
      },
      getGridOverlay: () => gridOn,
      getGridCapacity: () =>
        currentView === 'uniform' ? GRID_CAPACITY.uniform : GRID_CAPACITY.adaptive,
      setWipe: (on) => {
        wipe.setEnabled(on);
        // The wipe always shows the grid structure — that is the whole claim.
        gridLayer.mesh.visible = on ? true : gridOn;
        if (on && lastCells) renderBothForWipe(scene, objects, lastCells, colourMode);
        if (!on) repaint();
        meter.reset();
      },
      getWipe: () => wipe.enabled,
      setDivider: (x) => wipe.setDivider(x),
      onDividerChange: (cb) => wipe.onDividerChange(cb),
      dispose: () => {
        cancelAnimationFrame(animId);
        if (perfTimer) window.clearInterval(perfTimer);
        resizeObserver.disconnect();
        window.removeEventListener('resize', onResize);
        controls.dispose();
        disposeViewObjects(scene, objects);
        wipe.dispose();
        scene.remove(gridLayer.mesh);
        gridLayer.dispose();
        renderer.dispose();
      },
    };

    handleRef.current = handle;
    onReadyRef.current?.(handle);

    return () => {
      handle.dispose();
      handleRef.current = null;
    };
  }, [canvasRef]); // canvasRef identity is stable — effect runs ONCE

  return handleRef;
}
