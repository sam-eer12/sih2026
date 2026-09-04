# How Shubham Should Proceed — Step-by-Step

> You own the **Three.js viewer** — everything the judge actually looks at
> inside the canvas. Your files live in `frontend/components/viewer/`
> and `lib/palette.ts`.
>
> This document tells you exactly what to do, step by step, command by command.

---

## Before You Write a Single Line of Code

### Step 1 — Understand the boundary

The frontend is split between **you** and **Navya**:

| Owner | Owns | Files |
|---|---|---|
| **Shubham (you)** | Everything **inside** the canvas — rendering, instancing, views, wipe, ring overlay | `components/viewer/*`, `lib/palette.ts` |
| **Navya** | Everything **around** the canvas — Next.js app, auth, persistence, HUD, decision panel | `app/*`, `lib/*` (except palette), `components/hud/*`, `components/decision/*` |

You never touch auth, MongoDB, or route handlers. Navya never touches
Three.js, the render loop, or instance buffers.

### Step 2 — Set up the frontend environment

```bash
cd /Users/shubhamkhatri/sih2026/frontend

# Install dependencies
npm install

# Install Three.js (you need this — it's not in the project yet)
npm install three
npm install -D @types/three

# Start the dev server
npm run dev
```

**How to verify it worked:**

Open [http://localhost:3000](http://localhost:3000) in your browser. You should
see the default Next.js page. If it loads, your environment is ready.

> Every time you open a new terminal to work on this project, `cd` into
> `frontend/` first.

### Step 3 — Set up the backend (so you can receive fixture frames)

You need the Python backend running in a separate terminal to stream frames:

```bash
cd /Users/shubhamkhatri/sih2026

# Create the virtual environment (if not already done)
python3 -m venv backend/.venv

# Activate it
source backend/.venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

# Install the avr25d package
pip install -e model/

# Start the fixture server (fixtures.py has landed)
python -m avr25d.server.app --fixtures
```

This gives you `ws://localhost:8000/stream` streaming fake-but-schema-valid
frames at 30 Hz — roughly **42,000 occupied cells per frame, ~1.1 MB each**.
(705,771 is the grid's total capacity, not the per-frame count.) The generator
free-runs whether or not anyone is connected, so you always join mid-stream —
never assume `frame_id` starts at 0. You build entirely against fixtures — you never need real
KITTI data or the perception pipeline.

---

## Understanding Where Your Files Go

The repo expects this structure inside `frontend/`:

```
frontend/
├── app/
│   ├── layout.tsx
│   ├── page.tsx
│   ├── (auth)/login/page.tsx         ← Navya
│   ├── dashboard/page.tsx            ← the live viewer page
│   └── api/                          ← Navya
├── components/
│   ├── viewer/                       ← YOUR work — CREATE THIS
│   │   ├── Viewer.tsx                ← main viewer component (canvas + ref)
│   │   ├── useThreeScene.ts          ← creates renderer/scene/camera ONCE
│   │   ├── ringGeometry.ts           ← ring/bin → x, y, extents (see below)
│   │   ├── instancedCells.ts         ← writes per-instance data to GPU
│   │   ├── views.ts                  ← the four view modes
│   │   ├── ringOverlay.ts            ← ring boundary lines
│   │   └── wipe.ts                   ← the A/B comparison wipe
│   ├── hud/                          ← Navya
│   └── decision/                     ← Navya
├── lib/
│   ├── palette.ts                    ← YOUR work — class colours (single source of truth)
│   ├── protocol.ts                   ← Navya — decodes FrameMessage
│   ├── ws.ts                         ← Navya — WebSocket client
│   └── firebase/                     ← Navya
└── package.json
```

---

## Two Rules That Are Not Style Preferences

These are hard requirements. Break them and you break the frame rate.

### Rule 1: The frame stream bypasses Next.js entirely (FR-41)

The browser opens a WebSocket **straight to the FastAPI server**
(`ws://localhost:8000/stream`). Navya writes `lib/ws.ts` for this. Next.js
never proxies, buffers, or re-serialises frame data.

### Rule 2: Per-frame data never becomes React state (FR-42)

The viewer is a `useRef` canvas with a plain `requestAnimationFrame` loop.
React renders the chrome around it and **nothing inside it**.

```tsx
// ✅ CORRECT — imperative, no React re-renders
const canvasRef = useRef<HTMLCanvasElement>(null);
// Three.js scene, camera, renderer live in a ref — not state

// ❌ WRONG — this would run React reconciliation 30× per second
const [cells, setCells] = useState(frameCells);
```

`react-three-fiber` is **deliberately not used**. T-W7 enforces this:
over 300 streamed frames, React must re-render **fewer than 10 times**.

---

## The Build Order (Do NOT skip steps)

```
1. lib/palette.ts          ← class colours (no dependencies)
2. components/viewer/      ← canvas + scene + camera (uses palette.ts)
3. ringGeometry.ts          ← ring/bin → world geometry (blocks everything below)
4. instancedCells.ts        ← render fixture cells as InstancedMesh
5. Class colouring + sizing ← per-instance colour from palette, sizing from ring extents
6. View 1 + View 3          ← raw cloud + adaptive grid on real frames
7. View 2                   ← uniform 5 cm grid (for comparison)
8. The A/B wipe             ← THE MONEY SHOT — build on Day 5, not later
9. Ring overlay             ← ring boundary lines
10. View 4                  ← track markers, routes, risk shading
11. LOD / performance       ← verify ≥30 FPS at 100k instances
```

---

## Module 1: `lib/palette.ts`

**What it does:** The single source of truth for class colours. Both you
and Navya import from here. Nobody hard-codes a hex value anywhere else.

**Your task:** Create the file.

```bash
mkdir -p lib
```

Now create `lib/palette.ts` with the five AVR-25D semantic classes:

```typescript
/**
 * Class colour palette — single source of truth.
 * Mirrors the class taxonomy from avr25d/perception/labelmap.py.
 *
 * RULE: Nobody hard-codes a hex value anywhere else in the frontend.
 * Import from here. If the colours disagree between the viewer and
 * the HUD, a judge will notice.
 */

export const CLASS_COLOURS = {
  UNLABELED:             0x808080,  // grey
  DRIVABLE:              0x00C853,  // green — the road
  NON_DRIVABLE_TERRAIN:  0xFFD600,  // amber — grass, dirt
  STATIC_OBSTACLE:       0xD50000,  // red — walls, buildings
  DYNAMIC_OBJECT:        0x2979FF,  // blue — vehicles, people
} as const;

export type ClassName = keyof typeof CLASS_COLOURS;

// Map from class_id (uint8 in the FrameMessage) to colour
export const CLASS_ID_TO_COLOUR: number[] = [
  CLASS_COLOURS.UNLABELED,            // 0
  CLASS_COLOURS.DRIVABLE,             // 1
  CLASS_COLOURS.NON_DRIVABLE_TERRAIN, // 2
  CLASS_COLOURS.STATIC_OBSTACLE,      // 3
  CLASS_COLOURS.DYNAMIC_OBJECT,       // 4
];

// For the HUD legend — human-readable names
export const CLASS_NAMES: string[] = [
  'Unlabeled',
  'Drivable',
  'Non-drivable Terrain',
  'Static Obstacle',
  'Dynamic Object',
];
```

**Design note:** Verify these colours are distinguishable in **greyscale**.
If it survives greyscale, it survives a bad projector and colour-blind judges.

---

## Module 2: `components/viewer/useThreeScene.ts`

**What it does:** Creates the Three.js renderer, scene, and camera **ONCE**
in a React effect keyed on `[]`. Returns an imperative handle. Frames arrive
via `handle.pushFrame(msg)` from the WebSocket callback and are written
straight into GPU buffers. React **never re-renders**.

**Your task:** Create the directory and the file.

```bash
mkdir -p components/viewer
```

```typescript
// useThreeScene.ts — skeleton
import { useRef, useEffect, useCallback } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

export interface SceneHandle {
  pushFrame: (msg: any) => void;
  setView: (view: 'raw' | 'uniform' | 'adaptive' | 'decision') => void;
  dispose: () => void;
}

export function useThreeScene(
  canvasRef: React.RefObject<HTMLCanvasElement | null>
): React.RefObject<SceneHandle | null> {
  const handleRef = useRef<SceneHandle | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Create renderer, scene, camera ONCE
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(canvas.clientWidth, canvas.clientHeight);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a1a2e);

    const camera = new THREE.PerspectiveCamera(
      60, canvas.clientWidth / canvas.clientHeight, 0.1, 500
    );
    camera.position.set(0, 80, 80);
    camera.lookAt(0, 0, 0);

    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;

    // Ground reference grid
    const gridHelper = new THREE.GridHelper(200, 200, 0x444444, 0x222222);
    scene.add(gridHelper);

    // Ambient + directional lighting
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
    dirLight.position.set(50, 100, 50);
    scene.add(dirLight);

    // ---- The instanced mesh for cells goes here (Module 3) ----

    // Animation loop — plain requestAnimationFrame, NOT React state
    let animId = 0;
    function animate() {
      animId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }
    animate();

    // Resize handler
    function onResize() {
      const w = canvas!.clientWidth;
      const h = canvas!.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }
    window.addEventListener('resize', onResize);

    // Build the imperative handle
    const handle: SceneHandle = {
      pushFrame: (msg) => {
        // Module 3: update instanced cells from msg.cells
      },
      setView: (view) => {
        // Module 5: switch between the four views
      },
      dispose: () => {
        cancelAnimationFrame(animId);
        window.removeEventListener('resize', onResize);
        controls.dispose();
        renderer.dispose();
      },
    };

    handleRef.current = handle;

    return () => {
      handle.dispose();
      handleRef.current = null;
    };
  }, []); // ← keyed on [] — runs ONCE

  // Return the REF, not handleRef.current.
  //
  // The effect runs *after* render, and because React never re-renders this
  // component (FR-42), returning `handleRef.current` would hand back the
  // `null` it held during the only render that ever happens — the handle
  // would be permanently unreachable and nothing could ever push a frame.
  return handleRef;
}
```

**Getting the handle to Navya.** Take an `onReady` callback and fire it once
the scene is built, so `lib/ws.ts` can reach `pushFrame`:

```tsx
<Viewer onReady={(handle) => connectStream(handle.pushFrame)} />
```

Keep the callback in a ref (`onReadyRef.current = onReady`, refreshed in its
own dependency-less effect) so a changing callback identity can never re-run
the effect and tear down the WebGL context.

---

## Module 2.5: `components/viewer/ringGeometry.ts`

**What it does:** Turns `ring` and `bin` into world-space centres and extents.

**Why it exists — read this before writing Module 3.** The `FrameMessage`
does **not** carry cell centres or extents. Check `protocol.py`: the wire
fields are

```
cell_id, ring, bin, z_ground, z_obstacle, roughness, slope,
class_id, confidence, flags
```

There is no `cx`, `cy`, `dx` or `dy`. Geometry is *derived* on the client from
`ring` and `bin`. Everything below depends on getting this right.

**Port `core/grid.py::RingGrid`, not `server/fixtures.py`.** The two disagree:

| Source | Bin count derived from | Total cells |
|---|---|---|
| `server/fixtures.py` | ring **centre** | 706,396 |
| `core/grid.py` (`RingGrid`) | ring **inner edge** | **705,771** |

`fixtures.py` says so itself ("Any discrepancy … is caught by T-G3 anyway"),
but on Day 12 the server swaps fixtures for the real pipeline, and the real
pipeline is `RingGrid`. Match `RingGrid` or every cell lands in the wrong place.

**Two traps:**

1. **Python's `round()` is banker's rounding; JS `Math.round` is half-up.**
   A naïve port puts several rings off by one bin and misaligns every
   downstream `cell_id`. Write an explicit `roundHalfToEven`.
2. **Precompute per-ring values into typed arrays at module load.** At ~42,000
   cells × 30 Hz, recomputing radii and bin counts per cell is over a million
   transcendental calls a second.

Build the rings exactly as `RingGrid` does — accumulating from `r = 0`:

```typescript
for (let r = 0.0; r < R_MAX; ) {
  const s = r <= R_KNEE ? S_MIN : Math.min(S_MIN * (r / R_KNEE), S_MAX);
  rInner.push(r);
  sizes.push(s);
  r += s;
}
// bin count uses the INNER edge — this is the line that yields 705,771
const nBins = rIn === 0 ? 1 : Math.max(1, roundHalfToEven(2 * Math.PI * rIn / s));
```

**How to verify:** your table must reproduce **662 rings, 705,771 cells,
`r_edge[-1] = 100.166046`**, with `n_bins` of 1, 1250, 1257, 1257 at
k = 0, 199, 200, 661. Check against Python:

```bash
backend/.venv/bin/python -c "
from avr25d.core.grid import RingGrid
g = RingGrid(); print(g.n_rings, g.n_cells, g.r_edge[-1])"
```

---

## Module 3: `components/viewer/instancedCells.ts`

**What it does:** Takes the decoded `cells` from a `FrameMessage` and writes
per-instance transform matrices and colours into a `THREE.InstancedMesh`.
One draw call for ~42,000 cells.

**Key details:**

```typescript
// instancedCells.ts — skeleton
import * as THREE from 'three';
import { CLASS_ID_TO_COLOUR } from '../../lib/palette';
import { RING_RADIUS, RING_DTHETA, RING_EXTENT_R, RING_EXTENT_T } from './ringGeometry';
import type { CellArrays } from './types';

const _dummy = new THREE.Object3D();
const _colour = new THREE.Color();

/** Allocated capacity — NOT mesh.count, which is the per-frame draw count. */
function capacityOf(mesh: THREE.InstancedMesh | null): number {
  return mesh ? mesh.instanceMatrix.count : 0;
}

/**
 * Update the InstancedMesh with new cell data.
 *
 * Reallocates the mesh ONLY when n exceeds the current capacity,
 * growing in powers of two. Never allocate per frame.
 */
export function updateCells(
  scene: THREE.Scene,
  meshRef: { current: THREE.InstancedMesh | null },
  cells: CellArrays   // n, cell_id, ring, bin, z_ground, z_obstacle, class_id, …
): void {
  const n = cells.n;
  let mesh = meshRef.current;

  // Compare against the real capacity, not mesh.count. mesh.count is reset
  // to n at the end of every call, so comparing against it would rebuild the
  // mesh on any frame that grew by even one cell — leaking a geometry and a
  // material each time.
  if (!mesh || n > capacityOf(mesh)) {
    if (mesh) {
      scene.remove(mesh);
      mesh.geometry.dispose();
      (mesh.material as THREE.Material).dispose();
      mesh.dispose();
    }
    let capacity = 1;
    while (capacity < n) capacity *= 2;

    const geometry = new THREE.BoxGeometry(1, 1, 1);
    const material = new THREE.MeshLambertMaterial();
    mesh = new THREE.InstancedMesh(geometry, material, capacity);
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);

    // Instance positions are written on the CPU and the bounding sphere is
    // never recomputed, so Three's stale-sphere frustum test culls the whole
    // mesh the moment the camera moves. One draw call is cheap; culling it
    // buys nothing.
    mesh.frustumCulled = false;

    scene.add(mesh);
    meshRef.current = mesh;
  }

  const { ring, bin, z_ground, z_obstacle, class_id } = cells;

  for (let i = 0; i < n; i++) {
    const k = ring[i];

    // Geometry is DERIVED — the wire carries ring/bin only (Module 2.5).
    const r     = RING_RADIUS[k];
    const theta = (bin[i] + 0.5) * RING_DTHETA[k];
    const x     = r * Math.cos(theta);
    const y     = r * Math.sin(theta);

    const zGround = z_ground[i];
    const zObs    = z_obstacle[i];
    const height  = Number.isNaN(zObs) ? 0.1 : Math.max(zObs - zGround, 0.1);

    // LiDAR (x, y, z) → Three (x, z, y): Three is Y-up.
    _dummy.position.set(x, zGround + height / 2, y);

    // Rotate to the ring tangent. Without this, far-field cells
    // (0.5 m radial × 0.5 m tangential) point the wrong way and the grid
    // renders as scattered confetti.
    _dummy.rotation.set(0, -theta, 0);
    _dummy.scale.set(RING_EXTENT_R[k], height, RING_EXTENT_T[k]);
    _dummy.updateMatrix();
    mesh.setMatrixAt(i, _dummy.matrix);

    _colour.setHex(CLASS_ID_TO_COLOUR[class_id[i]] ?? 0x808080, THREE.SRGBColorSpace);
    mesh.setColorAt(i, _colour);
  }

  mesh.count = n;
  mesh.instanceMatrix.needsUpdate = true;
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
}
```

**Performance fallback (risk R-4):** If instancing underperforms, render cell
centroids as a `THREE.Points` cloud with per-point size. Visually
near-identical at demo zoom, far cheaper.

---

## Module 4: `components/viewer/Viewer.tsx`

**What it does:** The React component that owns the canvas ref and wires
everything together. React renders this component exactly ONCE.

```tsx
// Viewer.tsx
'use client';

import { useRef, useEffect } from 'react';
import { useThreeScene } from './useThreeScene';

export interface ViewerProps {
  /** Fires once, when the scene is ready. Navya's lib/ws.ts hooks in here. */
  onReady?: (handle: SceneHandle) => void;
}

export default function Viewer({ onReady }: ViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const handleRef = useThreeScene(canvasRef, onReady);   // a REF, not a value

  // The WebSocket lives in Navya's lib/ws.ts and calls handle.pushFrame.
  // Read the handle as handleRef.current inside effects and event handlers —
  // never during render.

  return (
    <canvas
      ref={canvasRef}
      style={{
        width: '100%',
        height: '100%',
        display: 'block',
      }}
    />
  );
}
```

**How to verify Module 2–4 work:**

```bash
cd /Users/shubhamkhatri/sih2026/frontend
npm run dev
```

Open [http://localhost:3000/dashboard](http://localhost:3000/dashboard)
(you may need to create `app/dashboard/page.tsx` that imports `<Viewer />`).
You should see a dark 3D scene with a grid helper and orbit controls.

---

## Module 5: The Four Views (`views.ts`)

**What it does:** Implements the four views from FR-25:

| View | What it shows | When to build |
|---|---|---|
| **View 1 — Raw Cloud** | The raw point cloud, coloured by class | Day 3 |
| **View 2 — Uniform Grid** | The 5 cm uniform grid (~16,000,000 cells) | Day 4 |
| **View 3 — Adaptive Grid** | The AVR-25D grid (~705,771 cells) | Day 3 |
| **View 4 — Decision Layer** | Routes, tracks, risk shading | Days 7–8 |

Views 1 and 3 come first because they use the streamed `FrameMessage` directly.
View 2 exists purely for the comparison — it shows what a uniform grid
would look like on the same scan.

> **View 1 is not literally the raw cloud.** The `FrameMessage` is already
> aggregated to cells — there is no array of LiDAR returns on the wire. So
> View 1 renders one point per occupied *cell*, placed at the cell centre and
> obstacle top. At demo zoom this is indistinguishable from the raw scan, and
> it is the documented R-4 fallback anyway. If a judge asks for genuinely raw
> points, Anuj has to add a points array to `protocol.py` — which is frozen
> after Day 1 and needs Sameer's sign-off. Raise it early or not at all.

---

## Module 6: The A/B Wipe (`wipe.ts`) — THE MONEY SHOT

**What it does:** Shows Views 2 and 3 side by side with a draggable divider.
Same scan, same camera. Live cell counts on both sides reading
**16,000,000 vs 705,771**.

> **This is the single most persuasive object in the whole submission.**
> It converts "22.67× reduction" from a claim into something the judge
> watches happen. Build it on Day 5, not in the final week.

**Implementation:** Two scissor-rect renders of the **same scene graph**
with different cell sets — NOT two canvases (which would double the WebGL
context cost).

```typescript
// wipe.ts — concept
export function renderWipe(
  renderer: THREE.WebGLRenderer,
  scene: THREE.Scene,
  camera: THREE.Camera,
  dividerX: number,       // 0.0 – 1.0, mouse-draggable
  uniformMesh: THREE.InstancedMesh,
  adaptiveMesh: THREE.InstancedMesh,
) {
  const w = renderer.domElement.width;
  const h = renderer.domElement.height;
  const splitPx = Math.floor(dividerX * w);

  renderer.setScissorTest(true);

  // LEFT side: uniform grid
  renderer.setScissor(0, 0, splitPx, h);
  renderer.setViewport(0, 0, w, h);  // full viewport, scissored
  uniformMesh.visible = true;
  adaptiveMesh.visible = false;
  renderer.render(scene, camera);

  // RIGHT side: adaptive grid
  renderer.setScissor(splitPx, 0, w - splitPx, h);
  uniformMesh.visible = false;
  adaptiveMesh.visible = true;
  renderer.render(scene, camera);

  renderer.setScissorTest(false);
}
```

---

## Module 7: Ring Overlay (`ringOverlay.ts`)

**What it does:** Draws the 662 ring boundaries as circles so the variable
resolution is **directly visible**, not merely asserted. FR-27.

Toggle on/off. Use `THREE.LineLoop` or `THREE.Line` with a
`BufferGeometry` circle for each ring. The ring radii come from the
`RingGrid` — Anuj will expose them in the `FrameMessage` or you can
hardcode the formula: rings 0–199 at 0.05 m spacing, rings 200–661
growing by factor 1.005.

---

## Build Checklist — Tick These Off In Order

```
[ ] 1.  npm install + npm install three @types/three
[ ] 2.  npm run dev  →  default page loads at localhost:3000
[ ] 3.  Backend venv created + activated
[ ] 4.  pip install -r backend/requirements.txt && pip install -e model/

[ ] 5.  Create lib/palette.ts (class colours, single source of truth)
[ ] 6.  mkdir components/viewer/
[ ] 7.  Write useThreeScene.ts (renderer, scene, camera, orbit controls)
[ ] 8.  Write Viewer.tsx (canvas ref component)
[ ] 9.  Create app/dashboard/page.tsx importing <Viewer />
[ ] 10. Verify: dark scene with grid helper and orbit controls in browser

[ ] 11. Write ringGeometry.ts — verify 662 rings / 705,771 cells / 100.166046
[ ] 11b. Write instancedCells.ts
[ ] 12. Render ~42,000 fixture cells as one InstancedMesh
        → EXIT CRITERION DAY 1: fixture cells render at interactive frame rate

[ ] 13. Class colouring from palette.ts
[ ] 14. Per-instance sizing from ring extents (radial × tangential)
[ ] 15. Elevation-shading toggle
        → EXIT CRITERION DAY 2: cells correctly sized at every range

[ ] 16. View 1 (raw point cloud) on real streamed frames
[ ] 17. View 3 (adaptive grid) on real streamed frames
        → EXIT CRITERION DAY 3: views render real frames, class-coloured

[ ] 18. View 2 (uniform 5 cm grid)
        → EXIT CRITERION DAY 4: uniform view renders the same scan as View 3

[ ] 19. THE A/B WIPE — scissor-rect, draggable divider, live cell counts
[ ] 20. Ring overlay toggle (662 boundaries)
        → EXIT CRITERION DAY 5: divider shows 16,000,000 vs 705,771

[ ] 21. Wipe polish, no frame drops while dragging the divider
[ ] 22. Performance pass on instance count
        → EXIT CRITERION DAY 6: smooth wipe, no frame drops

[ ] 23. View 4 scaffold: track markers + predicted trajectories
        → EXIT CRITERION DAY 7: tracks visible and individually identifiable

[ ] 24. View 4 complete: routes, risk shading
        → EXIT CRITERION DAY 8: reroute legible from three metres away

[ ] 25. LOD tuning
[ ] 26. Verify ≥30 FPS at 100,000 instances (T-V6)
[ ] 27. Verify React render count < 10 across 300 frames (T-W7)
        → EXIT CRITERION DAY 9: T-V6 and T-W7 pass

[ ] 28. Visual polish, verify at projector resolution
        → EXIT CRITERION DAY 10: renders correctly at projector resolution

[ ] 29. Demo keystroke sequence verified end to end
        → EXIT CRITERION DAY 11: every run-book keystroke works

[ ] 30. Bug fixes only — zero console errors across all four views
        → EXIT CRITERION DAY 12: clean console
```

---

## The Tests You Need to Pass

| Test | What it checks | When |
|---|---|---|
| **T-V1** | All four views render without console errors | Day 8 |
| **T-V2** | Rendered instance colours match `palette.ts` for each class | Day 2 |
| **T-V3** | Ring overlay draws 662 boundaries in the right places | Day 5 |
| **T-V5** | The A/B wipe shows both representations of the same `frame_id` | Day 5 |
| **T-V6** | 100,000 instances sustain ≥30 FPS on the demo machine (FR-30) | Day 9 |
| **T-W7** | Over 300 streamed frames, React re-renders **fewer than 10 times** (FR-42) | Day 9 |

**How to check T-W7:** Add a render counter in `Viewer.tsx`:

```tsx
const renderCount = useRef(0);
useEffect(() => {
  renderCount.current += 1;
  console.log('React renders:', renderCount.current);
});  // no dependency array → runs after every render, which is the thing measured
// After 300 WebSocket frames, this number must be < 10
```

Count inside the effect, not during render: React 19's `react-hooks/refs`
lint rule rejects writing a ref in the render pass, and `next lint` fails the
build on it. Expect **2** in development — StrictMode renders twice on mount.

---

## Common Mistakes to Avoid

**In `useThreeScene.ts`:**
- Using `useState` for anything per-frame — use `useRef` only. React reconciliation
  at 30 FPS will destroy performance.
- Creating the renderer inside `useState` — it must be in a `useEffect` with `[]` deps.
- Forgetting to `dispose()` the renderer, controls, and geometries in the cleanup.

**In `useThreeScene.ts` — the one that costs you an afternoon:**
- Returning `handleRef.current` instead of `handleRef`. The effect runs after
  render and React never re-renders, so callers get `null` forever.

**In `ringGeometry.ts`:**
- Porting `fixtures.py` instead of `core/grid.py`. They disagree by 625 cells.
- Using `Math.round` where Python used `round` — half-up vs banker's rounding.

**In `instancedCells.ts`:**
- Allocating a new `InstancedMesh` every frame — reallocate only when `n` exceeds
  capacity, growing in powers of two.
- Testing capacity with `cells.n > mesh.count`. `mesh.count` is the draw count
  and you reset it to `n` every frame, so the power-of-two growth never holds
  and you leak a geometry on any frame that grew. Test
  `mesh.instanceMatrix.count`.
- Forgetting `mesh.frustumCulled = false` — the bounding sphere is never
  recomputed, so the whole mesh vanishes as soon as you orbit.
- Forgetting to rotate instances to the ring tangent — the far field renders
  as confetti.
- Forgetting `mesh.instanceMatrix.needsUpdate = true` after writing transforms.
- Forgetting `mesh.instanceColor.needsUpdate = true` after writing colours.
- Using `mesh.count = capacity` instead of `mesh.count = cells.n` — you want to
  render only the actual cells, not empty slots.

**In `wipe.ts`:**
- Using two canvases — use scissor-rect on ONE canvas. Two canvases double the
  WebGL context cost.
- Forgetting `renderer.setScissorTest(false)` after the wipe render — this will
  clip all subsequent renders.

**In `palette.ts`:**
- Hard-coding colours anywhere else. Every colour must come from `palette.ts`.
- Using colours that are indistinguishable on a projector — verify in greyscale.

**General:**
- Importing anything from `react-three-fiber` — it is deliberately not used.
- Putting the WebSocket connection inside the viewer — that's Navya's `lib/ws.ts`.
  Your viewer just exposes `handle.pushFrame(msg)`.
- Computing stats in the browser — everything comes from `stats` in the `FrameMessage`.

---

## What You Are Waiting On / Who Is Waiting On You

### You are waiting on:
| Who | What | When |
|---|---|---|
| **Anuj** | `fixtures.py` pushed — fake frames to build against | Day 1 by 14:00 |
| **Navya** | `lib/protocol.ts` — decodes binary frames for you | Day 1 |
| **Navya** | `lib/ws.ts` — WebSocket client with reconnect | Day 2 |

### Others are waiting on you:
| Who | What | When |
|---|---|---|
| **Navya** | Your `Viewer.tsx` component to embed in `dashboard/page.tsx` | Day 1 |
| **The whole team** | The A/B wipe — it's the demo centrepiece | Day 5 |
| **Sameer** | View 4 with track markers — he needs to see his tracker output | Day 7 |

---

## How to Know You Are Done

**Day 1 done when:**
```
- npm run dev serves a page
- ~50,000 fixture cells render as InstancedMesh at interactive frame rate
```

**Day 5 done when:**
```
- The draggable divider shows uniform vs adaptive on the SAME scan
- Live cell counts read 16,000,000 vs 705,771
- Ring overlay toggles on/off
```

**Day 9 done when:**
```
- T-V6 passes: ≥30 FPS at 100,000 instances
- T-W7 passes: < 10 React renders across 300 streamed frames
```

**Fully done when:**
```
- All four views render without console errors (T-V1)
- Colours match palette.ts (T-V2)
- Ring overlay correct (T-V3)
- A/B wipe works (T-V5)
- 30 FPS at 100k instances (T-V6)
- React render count < 10 (T-W7)
- Zero console errors across all four views
- Renders correctly at projector resolution
- Every run-book keystroke works
```

---

## Phase 2 — 11 to 20 September 2026

Once Phase 1 is complete:
- **Timeline scrubber** — scrub through recorded frames
- **Side-by-side scene comparison** — compare different synthetic scenes
- **Exportable evidence screenshots** — for the deck and report

---

## Quick Reference: Key Numbers

| Item | Value |
|---|---|
| Rings | 662 |
| Total cells (adaptive) | 705,771 |
| Total cells (uniform 5 cm) | ~16,000,000 |
| Reduction factor | 22.67× |
| Inner ring spacing | 0.05 m (5 cm) |
| Outer ring spacing | up to 0.50 m |
| Knee radius | 10 m |
| Max radius | 100 m |
| Target FPS | ≥30 |
| Semantic classes | 5 (unlabeled, drivable, non-drivable terrain, static obstacle, dynamic object) |
| WebSocket URL | `ws://localhost:8000/stream` |
| Frame rate (server) | 30 Hz |
