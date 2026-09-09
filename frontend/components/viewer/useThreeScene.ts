// useThreeScene.ts — Module 2
// Creates renderer, scene, camera ONCE in a React effect keyed on [].
// Returns a ref to an imperative handle. Frames arrive via
// handle.pushFrame(msg) and are written straight into GPU buffers.
// React NEVER re-renders.

import { useRef, useEffect } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { createSceneDressing } from './sceneDressing';
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
import { RING_RADIUS, RING_DTHETA } from './ringGeometry';
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
    // Filmic response so bright returns roll off instead of clipping to flat
    // white, which is what made the cloud look like paint rather than light.
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x070a14);   // --ink-900
    // Depth cue. Distant cells fade into the background instead of ending at
    // a hard edge, which is most of why the scene reads as flat without it.
    scene.fog = new THREE.Fog(0x070a14, 55, 210);

    const camera = new THREE.PerspectiveCamera(
      60, canvas.clientWidth / canvas.clientHeight, 0.1, 500
    );

    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.055;          // weightier, less twitchy
    controls.maxPolarAngle = Math.PI * 0.49; // never orbit under the ground
    controls.minDistance = 12;
    controls.maxDistance = 260;
    // A slow drift while nobody is driving, so the scene reads as live rather
    // than as a still. It stops the instant anyone touches it and does not
    // resume — a view that creeps while you are reading it is worse than
    // static.
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.22;

    // ── Framing ──────────────────────────────────────────────────
    // The old fixed position (0, 80, 80) sat ~113 m back, which at a 60°
    // vertical fov spans roughly 130 m of scene. The occupied cloud is dense
    // near the sensor and sparse towards the 100 m envelope, so the part worth
    // looking at filled a small patch of the frame and the rest was empty.
    //
    // Frame a sphere instead, solving for the distance from the actual fov and
    // aspect. A wide laptop window then no longer shrinks the cloud, and the
    // framing is recomputed on resize rather than being a constant that only
    // suits one window size.
    //
    // ── Why the fit is measured, not assumed ──────────────────────────────
    // It used to be a 38 m sphere centred on the sensor. A scan does not fill
    // the envelope it is allowed to occupy: measured off the live stream, the
    // occupied cells span 100 m forward but only 13 m across, with 99.98% of
    // them inside a 50 degree wedge. Framing a 38 m sphere at the origin
    // therefore spent most of the frame on empty grid and pushed two thirds of
    // the corridor off-screen, which is what made a 42,000-cell scan read as a
    // thin band lying across the middle of the picture.
    //
    // So the fit comes from where the cells actually are. Nothing about the
    // data changes — this only decides where to stand to look at it, and it
    // adapts on its own if the source switches from a road corridor to a scan
    // that fills all 360 degrees.
    // The measured bounds of the occupied cells, in Three's axes. Seeded with
    // the old 38 m envelope so the first paint, before any frame lands, is
    // unchanged.
    const fit = {
      min: new THREE.Vector3(-38, 0, -38),
      max: new THREE.Vector3(38, 0, 38),
    };
    /** Oblique three-quarter view, used when the scan surrounds the sensor. */
    const SYMMETRIC_DIR = new THREE.Vector3(0, 0.52, 1).normalize();
    /** tan of the look-down angle when standing off a one-sided scan. */
    const ELEVATION = 0.38;

    const _centre = new THREE.Vector3();
    const _corner = new THREE.Vector3();

    /**
     * Where to stand.
     *
     * A scan spread evenly around the sensor has no long axis worth aligning
     * to, so it keeps the oblique view. A one-sided scan — a road corridor is
     * the usual case — is viewed from behind its centre of mass looking back
     * along its length, because a corridor seen end-on recedes and a corridor
     * seen side-on is a stripe. The threshold is "the bulk of the data sits
     * off to one side by more than a third of its own radius".
     */
    function viewDirection(centre: THREE.Vector3, radius: number): THREE.Vector3 {
      const offset = Math.hypot(centre.x, centre.z);
      if (offset < radius * 0.3) return SYMMETRIC_DIR.clone();
      return new THREE.Vector3(-centre.x / offset, ELEVATION, -centre.z / offset).normalize();
    }

    function frameScene() {
      // clientWidth is 0 until layout settles, which makes aspect NaN and
      // would put the camera at NaN — a permanently black canvas. The resize
      // observer calls this again with a real size.
      if (!Number.isFinite(camera.aspect) || camera.aspect <= 0) return;
      const vFov = THREE.MathUtils.degToRad(camera.fov);
      const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);
      // Fit against whichever axis is tighter so nothing is cropped.
      const halfFov = Math.min(vFov, hFov) / 2;

      _centre.addVectors(fit.min, fit.max).multiplyScalar(0.5);
      const dir = viewDirection(_centre, 0.5 * fit.min.distanceTo(fit.max));

      // Split the box's own extent into the part running ALONG the view axis
      // and the part running ACROSS it. Only the across part has to fit inside
      // the frustum; the along part is depth, which perspective handles for
      // free. Fitting the bounding sphere instead treats a 100 m corridor as
      // though it were 100 m wide and stands the camera about a third further
      // back than it needs to be, which is most of why a full scan reads as a
      // small sliver in the middle of the frame.
      let along = 0;
      let across = 0;
      for (let c = 0; c < 8; c++) {
        _corner
          .set(
            c & 1 ? fit.max.x : fit.min.x,
            c & 2 ? fit.max.y : fit.min.y,
            c & 4 ? fit.max.z : fit.min.z
          )
          .sub(_centre);
        const d = _corner.dot(dir);
        along = Math.max(along, Math.abs(d));
        // Drop the component along the axis; what is left is the offset that
        // has to survive the frustum test.
        across = Math.max(across, _corner.addScaledVector(dir, -d).length());
      }

      // Clear the near face, then back off far enough that the nearest slice
      // still fits across the frame. Everything behind it fits by construction.
      const distance = along + across / Math.tan(halfFov);
      controls.target.copy(_centre);
      camera.position
        .copy(dir)
        .multiplyScalar(THREE.MathUtils.clamp(distance, controls.minDistance, controls.maxDistance))
        .add(_centre);
      controls.update();
    }

    /**
     * Measure the occupied cells once and reframe.
     *
     * Read-only over the cells the handle was already given, run on the first
     * frame only — ~42,000 iterations once is far below a single frame's
     * budget, and nothing here writes to the data or to any buffer.
     */
    let fitMeasured = false;
    function measureFit(cells: FrameMessage['cells']): void {
      const n = cells.n;
      if (n === 0) return;
      const { ring, bin, z_ground } = cells;

      let minX = Infinity, maxX = -Infinity;
      let minZ = Infinity, maxZ = -Infinity;
      let minY = Infinity, maxY = -Infinity;
      for (let i = 0; i < n; i++) {
        const k = ring[i];
        const r = RING_RADIUS[k];
        const theta = (bin[i] + 0.5) * RING_DTHETA[k];
        // The same LiDAR -> Three mapping instancedCells.ts uses: the LiDAR's
        // lateral y becomes Three's z, and its up z becomes Three's y.
        const x = r * Math.cos(theta);
        const z = r * Math.sin(theta);
        const y = z_ground[i];
        if (x < minX) minX = x; if (x > maxX) maxX = x;
        if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
        if (y < minY) minY = y; if (y > maxY) maxY = y;
      }
      if (!Number.isFinite(minX) || !Number.isFinite(minZ)) return;

      // A little air, so the outermost cells are not flush against the edge,
      // and a floor on each axis: a scan can be almost perfectly planar — the
      // measured ground relief here is 4 cm — and a zero-thickness box would
      // make the fit degenerate.
      const pad = Math.max((maxX - minX + maxZ - minZ) * 0.03, 1);
      fit.min.set(minX - pad, minY - pad, minZ - pad);
      fit.max.set(maxX + pad, maxY + pad, maxZ + pad);

      fitMeasured = true;
      if (!userFramed) frameScene();
    }

    // Once someone orbits, the view is theirs — a resize must not yank it back.
    let userFramed = false;
    controls.addEventListener('start', () => {
      userFramed = true;
      controls.autoRotate = false;
    });

    frameScene();

    // NOTE: the skeleton's THREE.GridHelper(200, 200) is deliberately gone.
    // It drew a 1 m reference lattice — indistinguishable from a real grid,
    // and directly misleading in a view whose whole subject is cell size.
    // gridShader.ts draws the actual grid instead.

    // ── Lighting ─────────────────────────────────────────────────
    // Ambient stays high enough that class colour, not lighting, remains what
    // distinguishes a cell — the palette is the data here.
    scene.add(new THREE.AmbientLight(0xffffff, 0.52));
    // Cyan from above, violet from below: the sensor/adaptive pairing the rest
    // of the interface uses, as light rather than as recolouring.
    scene.add(new THREE.HemisphereLight(0x22d3ee, 0xa78bfa, 0.38));
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

    // ── Reference geometry and atmosphere ────────────────────────
    // Decoration only: range rings, spokes, a ground wash and a rotating
    // sweep. No sensor data, derived from no frame. See sceneDressing.ts for
    // why this is rings rather than a lattice.
    const dressing = createSceneDressing();
    scene.add(dressing.group);

    // ── Bloom ────────────────────────────────────────────────────
    // Restrained: a high threshold so only the brightest returns and the
    // dressing's additive sweep bloom at all, and the rest of the cloud stays
    // crisp. Built defensively — if the composer cannot be created on this
    // GPU the loop falls back to a direct render rather than a black canvas.
    let composer: EffectComposer | null = null;
    try {
      const c = new EffectComposer(renderer);
      c.addPass(new RenderPass(scene, camera));
      c.addPass(
        new UnrealBloomPass(
          new THREE.Vector2(canvas.clientWidth || 1, canvas.clientHeight || 1),
          0.42,   // strength
          0.7,    // radius
          0.82    // threshold — only genuinely bright pixels contribute
        )
      );
      c.addPass(new OutputPass());
      // Bloom is the expensive pass and the one thing here that could
      // threaten T-V6 (>=30 fps at 100k instances), so it runs at a lower
      // ratio than the main render. Render fps is on the telemetry rail, so a
      // regression is visible immediately rather than needing a profiler.
      c.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
      composer = c;
    } catch (err) {
      console.warn('[viewer] bloom unavailable, rendering directly:', err);
    }
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
      dressing.update(now / 1000);
      // The wipe draws both sides itself; it returns false when disabled.
      // It renders with a scissor test, which the composer cannot honour, so
      // the wipe deliberately keeps the direct path.
      if (!wipe.render(renderer, scene, camera, objects, gridLayer)) {
        if (composer) composer.render();
        else renderer.render(scene, camera);
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
      composer?.setSize(w, h);
      if (!userFramed) frameScene();
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
        // One shot, on the first frame that carries cells: aim the camera at
        // where the data actually is. Never runs again, so this is not on the
        // per-frame path in any meaningful sense.
        if (!fitMeasured) measureFit(msg.cells);
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
        scene.remove(dressing.group);
        dressing.dispose();
        composer?.dispose();
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
