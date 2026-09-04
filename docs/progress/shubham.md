# Shubham — Three.js viewer

Newest entry at the top. Format and rules: [`README.md`](./README.md).

---

## Day 8 · Friday 4 Sep 2026 — viewer track opened; cells on screen

First entry. The viewer track started today, which puts it **7 days behind**
the schedule in `HOW_TO_PROCEED_SHUBHAM.md` — that document's Day 8 exit
criterion is "View 4 complete, reroute legible from three metres away", and
what actually landed today is its Days 1–3. Recording the gap rather than
renumbering around it.

---

### Landed

| File | Status |
|---|---|
| `lib/palette.ts` | class colours + elevation ramp |
| `components/viewer/ringGeometry.ts` | **new** — ring/bin → world geometry |
| `components/viewer/types.ts` | **new** — wire shapes mirroring `protocol.py` |
| `components/viewer/colouring.ts` | **new** — single colour decision point |
| `components/viewer/instancedCells.ts` | View 3 — one `InstancedMesh`, one draw call |
| `components/viewer/pointCloud.ts` | **new** — View 1 |
| `components/viewer/views.ts` | **new** — view switching |
| `components/viewer/useThreeScene.ts` | scene/camera/controls, imperative handle |
| `components/viewer/Viewer.tsx` | canvas component, `onReady` integration point |
| `components/viewer/__dev__/devFrames.ts` | **temporary** — synthetic 30 Hz stream |
| `app/dashboard/page.tsx` | dynamic import, `ssr: false` |

Running: **43,946 cells/frame at 30 Hz**, 2 React renders, zero console
errors. Keyboard: `1` raw, `3` adaptive, `E` elevation shading. `tsc --noEmit`
and `eslint` both clean.

---

### Acceptance

Against the checklist in `HOW_TO_PROCEED_SHUBHAM.md`:

- Items 1–14 ✓ — scene renders, ~44k cells as one `InstancedMesh`,
  class-coloured from `palette.ts`, sized from real ring extents
- Item 15 ✓ — elevation-shading toggle
- Items 16–17 **partial** — Views 1 and 3 render, but on *synthetic* frames.
  The Day 3 criterion says "on real streamed frames"; that needs a binary
  decoder, which is Navya's `lib/protocol.ts`. **Not claiming Day 3.**
- **Not measured:** FPS. T-V6 (≥30 FPS at 100k instances) is untested — the
  30 Hz figure is the push rate, not a rendered frame rate.
- **Not built:** View 2, the A/B wipe, ring overlay, View 4.

Viewer track is at **Day 2 complete, Day 3 partial**.

---

### Blocked / blocking

**Waiting on Navya:** `lib/protocol.ts` (binary decode) and `lib/ws.ts`.
Until they land the viewer runs on `__dev__/devFrames.ts`. Swapping to the
real stream is one call — `<Viewer onReady={h => connectStream(h.pushFrame)} />`
— and nothing inside the canvas changes.

**Unblocking Navya:** `<Viewer />` exists and takes an `onReady` prop. She can
embed it now.

**Blocking Sameer:** View 4 (track markers) not started. He is waiting.

---

### Decisions and surprises

**1. `HOW_TO_PROCEED_SHUBHAM.md`'s skeletons do not match the wire format.**
The `instancedCells.ts` skeleton reads `cells.cx/cy/dx/dy`. Those fields do
not exist. `protocol.py` sends `ring` and `bin`; centres and extents must be
derived client-side. This is why `ringGeometry.ts` exists. **The document
should be corrected before anyone else follows it.**

**2. `fixtures.py` and `core/grid.py` compute different grids.** This one
matters and is for Anuj.

| Source | Bin count from | Total cells |
|---|---|---|
| `server/fixtures.py` | ring **centre** | 706,396 |
| `core/grid.py` (`RingGrid`) | ring **inner edge** | **705,771** |

`fixtures.py` already admits it approximates ("Any discrepancy … is caught by
T-G3 anyway"), but the discrepancy is 625 cells and it changes `cell_id`
alignment. The frontend ports **`RingGrid`**, since Day 12 swaps fixtures for
the real pipeline. Verified identical: 662 rings, 705,771 cells,
`r_edge[-1] = 100.166046`, matching `n_bins` at k = 0/199/200/661.

**3. Python `round()` is banker's rounding; JS `Math.round` is half-up.**
A naïve port puts several rings off by one bin and misaligns every downstream
`cell_id`. `ringGeometry.ts` carries an explicit `roundHalfToEven`.

**4. The `FrameMessage` carries no raw points.** View 1 ("raw cloud", FR-25)
therefore renders one point per occupied *cell*, not per LiDAR return. Visually
equivalent at demo zoom and it is the documented R-4 fallback — but if a judge
asks for genuinely raw points, **Anuj has to add a points array to the
protocol**, and `protocol.py` is frozen after Day 1. Raise at checkpoint.

**5. Three bugs in the skeleton code, worth not rediscovering:**
- `useThreeScene` returned `handleRef.current`, which is `null` during the
  only render the component ever does — so the handle was permanently
  unreachable. Now returns the ref object.
- The capacity check compared `cells.n > mesh.count`, but `mesh.count` is
  reset to `n` every frame, so power-of-two growth never held and a geometry
  leaked on any frame that grew. Now compares `instanceMatrix.count`.
- Instance boxes were never rotated to the ring tangent. Without it far-field
  cells (0.5 m radial × 0.5 m tangential) point the wrong way and the grid
  looks like confetti.

**6. `frustumCulled = false` is required.** Instance matrices are written on
the CPU and the bounding sphere is never recomputed, so Three culls the entire
mesh the moment the camera moves.

**7. The document's T-W7 render-counter snippet fails lint.** React 19's
`react-hooks/refs` rejects writing a ref during render. Counting inside a
`useEffect` with no dependency array measures the same thing and passes.

**8. `backend/.venv/` was not gitignored.** Added to root `.gitignore` before
someone committed a few hundred MB.

---
