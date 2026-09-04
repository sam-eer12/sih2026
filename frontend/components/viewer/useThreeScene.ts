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
  type ViewMode,
} from './views';
import type { ColourMode } from './colouring';
import type { FrameMessage } from './types';

export type { ViewMode } from './views';
export type { ColourMode } from './colouring';

export interface SceneHandle {
  pushFrame: (msg: FrameMessage) => void;
  setView: (view: ViewMode) => void;
  getView: () => ViewMode;
  setColourMode: (mode: ColourMode) => void;
  getColourMode: () => ColourMode;
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

    // ── Ground reference grid ────────────────────────────────────
    const gridHelper = new THREE.GridHelper(200, 200, 0x444444, 0x222222);
    scene.add(gridHelper);

    // ── Lighting ─────────────────────────────────────────────────
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
    dirLight.position.set(50, 100, 50);
    scene.add(dirLight);

    // ── Renderable representations (Modules 3 and 5 write into these) ──
    const objects = createViewObjects();

    // ── Current view + colour mode ───────────────────────────────
    let currentView: ViewMode = 'adaptive';
    let colourMode: ColourMode = 'class';

    // The most recent frame, kept so switching view or colour mode can
    // repaint immediately instead of waiting up to 33 ms for the next one.
    let lastCells: FrameMessage['cells'] | null = null;

    function repaint() {
      if (lastCells) renderFrame(scene, objects, currentView, lastCells, colourMode);
      else applyVisibility(objects, currentView);
    }

    // ── Animation loop — plain requestAnimationFrame, NOT React state ──
    let animId = 0;
    function animate() {
      animId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }
    animate();

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
        lastCells = msg.cells;
        renderFrame(scene, objects, currentView, msg.cells, colourMode);
      },
      setView: (view) => {
        if (view === currentView) return;
        currentView = view;
        repaint();
      },
      getView: () => currentView,
      setColourMode: (mode) => {
        if (mode === colourMode) return;
        colourMode = mode;
        repaint();
      },
      getColourMode: () => colourMode,
      dispose: () => {
        cancelAnimationFrame(animId);
        resizeObserver.disconnect();
        window.removeEventListener('resize', onResize);
        controls.dispose();
        disposeViewObjects(scene, objects);
        gridHelper.geometry.dispose();
        (gridHelper.material as THREE.Material).dispose();
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
