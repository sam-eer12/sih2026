# Navya — Next.js platform, auth, persistence, HUD

Living implementation plan **and** progress log. Format rules: [`README.md`](./README.md).
Progress entries are newest-at-the-top in [§7](#7-progress-log); everything above §7 is the
plan and is edited in place as work lands.

Source documents: [`WORK_DISTRIBUTION.md §5.2`](../WORK_DISTRIBUTION.md) ·
[`IMPLEMENTATION_PLAN.md §5, §6.14`](../IMPLEMENTATION_PLAN.md) ·
[`PRD.md` FR-28, FR-36…FR-42, NFR-9](../PRD.md) ·
[`HOW_TO_PROCEED_SHUBHAM.md`](../HOW_TO_PROCEED_SHUBHAM.md) ·
[`shubham.md`](./shubham.md) · [`anuj.md`](./anuj.md)

---

## 1. Ownership

| Owner | Owns | Paths |
|---|---|---|
| **Navya (me)** | Everything **around** the canvas — Next.js app, auth, persistence, HUD, decision panel, the realtime client | `frontend/app/*`, `frontend/lib/*` (except `palette.ts`), `frontend/components/hud/*`, `frontend/components/decision/*`, Firebase project, Atlas cluster |
| **Shubham** | Everything **inside** the canvas — rendering, instancing, views, wipe, ring overlay | `frontend/components/viewer/*`, `frontend/lib/palette.ts` |
| **Anuj** | Grid engine, wire protocol, FastAPI server, decision layer | `model/avr25d/core/*`, `model/avr25d/server/*`, `model/avr25d/decision/{costmap,planner,explain}.py` |

Shared contracts: `lib/palette.ts` is the only source of class colours; `lib/protocol.ts` (mine)
mirrors `avr25d/server/protocol.py` (Anuj's, **frozen**). Nobody hard-codes a hex value or a
field offset anywhere else.

> The docs say `webapp/`. The real directory is **`frontend/`**. Docs are stale on this point;
> Shubham already corrected it in his guide.

---

## 2. Status snapshot

Last verified against the code: **Fri 4 Sep 2026** (Day 8 of 14).

**Complete (not mine).** Backend pipeline end-to-end — grid, cells, hazards, refine, decision
layer, server; 303 tests green. Wire protocol frozen and tested. Viewer scene, ring geometry,
instanced grid (View 3), point cloud (View 1), class + elevation colouring, palette.

**Partial (not mine).** Views 1 and 3 render **synthetic** frames from
`components/viewer/__dev__/devFrames.ts` only — the Day 3 criterion is "real streamed frames"
and it is unmet because it needs my decoder. FPS unmeasured (T-V6 untested). Canvas never
visually inspected by anyone. Shubham has not built View 2, the A/B wipe, the ring overlay or
View 4.

**Missing — all of it is mine.**

| Area | State |
|---|---|
| `lib/protocol.ts` | **Done** Day 8 — decoder verified against Anuj's encoder, 118 assertions |
| `lib/ws.ts` | **Done** Day 9 — reconnect, drop-not-queue, keepalives; **T-W6 passes** |
| `components/hud/StreamStatus.tsx` | **Done** Day 9 — connection state on screen; the rest of the HUD is Step 3 |
| `components/hud/*` | **Done** Day 9 — FR-28 complete; T-V4 and T-W7 pass |
| `components/decision/*` | **Done** Day 9 — decision panel and track list; `tracks: []` handled |
| `lib/firebase/{client,admin}.ts`, `lib/mongo.ts` | Missing |
| `app/(auth)/login`, `/dashboard` gate, `app/api/{runs,decisions,scenes}` | Missing |
| `app/runs`, `app/runs/[id]` | Missing |
| `.env.local.example`, Firebase project, Atlas M0 cluster | Missing / unconfirmed |
| `app/page.tsx`, `app/layout.tsx` metadata | Still create-next-app boilerplate |
| `docs/progress/navya.md` | This file — first entry Day 8 |

**Environment.** Installed and verified Day 8 (Step 0). `frontend/node_modules` present (372
packages, 0 vulnerabilities). `backend/.venv` present on Python 3.14.5 with
`requirements.txt` + `pip install -e model/`. Node v22.19.0, npm 10.9.3. Still no `.env*` files
and **no `firebase`, `firebase-admin` or `mongodb`** in `package.json` — those arrive in
Steps 6–7.

**Git.** `main` = `4a6e80d` (PR #1 merge). `shubham/viewer-setup` is fully merged and 0 ahead.
Working branch `navya/platform-hud` — it already existed at `main` with no commits on it, so it
was reused rather than recreated. Branches live less than a day.

---

## 3. Architectural constraints — non-negotiable

1. **FR-41 — the frame stream bypasses Next.js.** Browser opens `ws://localhost:8000/stream`
   directly. No route handler, no proxy, no re-serialisation. (T-W6)
2. **FR-42 — per-frame data never becomes React state.** The canvas is imperative. The HUD
   must not re-render the viewer subtree; throttle HUD updates (~4 Hz) in a **leaf** component
   and memoize `<Viewer>`. Over 300 frames React must render < 10 times. (T-W7)
3. **NFR-9 — the demo runs from `http://localhost:3000`.** An HTTPS origin cannot open
   `ws://localhost`. Vercel exists for the submission link only. Verify early, not on Day 13.
4. **Never compute a displayed number in the browser.** Every HUD value comes from `stats` in
   the `FrameMessage`, so the HUD and `results.json` cannot disagree.
5. **`requireUser()` first, in every write route** (FR-37). Verify the Firebase ID token
   server-side *before* touching MongoDB. One unprotected handler is the whole vulnerability.
6. **Module-scoped cached `MongoClient`** (never per request — it exhausts the Atlas pool).
7. **Decision writes are batched** (FR-39): on change of route/risk/reason, plus a heartbeat at
   most every 60 frames. Flushed on a timer with `insertMany`, never awaited in the frame loop.
8. **Next 16 / React 19, not Next 14.** The docs predate the scaffold. Read
   `frontend/node_modules/next/dist/docs/` before writing App Router code — see
   `frontend/AGENTS.md`.

### Wire format facts I must honour (from `protocol.py`, frozen)

- Layout: `uint32 header_len | UTF-8 JSON header | concatenated typed arrays`, little-endian.
- Cell arrays in order: `cell_id u32, ring u16, bin u16, z_ground f32, z_obstacle f32,
  roughness f32, slope f32, class_id u8, confidence u8, flags u8` — **27 bytes per cell**.
  Then refined: `parent_id u32, quadrant u8, z_ground f32, z_obstacle f32, class_id u8,
  flags u8`.
- `tracks`, `decision`, `stats` are **fully in the JSON header**. Typed-array fields appear
  there as sentinel strings like `"uint32[42000]"`.
- The wire carries `ring` and `bin` — **not** centres or extents. Geometry is derived
  client-side by Shubham's `ringGeometry.ts`. My decoder passes the arrays through untouched.
- **Alignment — confirmed, solved, and measured.** `new Uint32Array(buf, byteOffset, n)` throws
  unless the offset is 4-aligned, and `header_len` is arbitrary. Measured on a real fixture
  frame: `header_len = 1118`, payload at byte **1122, `% 4 == 2`** — a direct view throws on
  every frame. **Resolved** in `lib/protocol.ts` by copying the payload once into its own
  buffer, after which the cell arrays are self-aligning (`cell_id` at 0, `ring` at 4n, floats
  at 8n/12n/16n/20n); only `refined` can still land badly (27n is 4-aligned only when
  `n % 4 == 0`) and `alignedView` absorbs that with a small second copy. Cost measured at
  **0.131 ms/frame — 0.4% of the 33 ms budget**, so the header-padding request to Anuj is
  dropped. `IMPLEMENTATION_PLAN.md §6.14`'s "zero copies" is unachievable and does not need to
  be achieved.
- **Skip zero-length messages.** The server sends `b""` keepalives while the pipeline queue is
  empty (`app.py`). Decoding one will throw on every startup.
- **`frame_id` does not start at 0** — the generator free-runs, so I always join mid-stream.
- Server: `ws://localhost:8000/stream` (binary), `GET /health`, `CORS allow_origins=["*"]`,
  frames dropped rather than queued. Start it with
  `backend/.venv/bin/python -m avr25d.server.app --fixtures`.
- ✅ **The disconnect wedge is fixed** (Day 9, `server/app.py`). It blocked the event loop with
  a synchronous `queue.get` and never read inbound messages, so it never learned a client had
  gone. Now polls the queue without blocking and watches for the ASGI disconnect. Verified:
  clean close, abrupt kill, six rapid refresh cycles, SIGTERM honoured in ~1 s, idle CPU 0%,
  throughput ~26 fps / 29 MB/s. **This is Anuj's module — tell him.**
- ⚠️ **Two clients starve each other.** All WebSocket handlers pop from one shared
  `worker._queue`, so each frame goes to exactly one connection. A second tab — or a forgotten
  one — silently halves or steals the stream, and the symptom is a viewer that stutters or
  freezes for no visible reason. Pre-existing, not introduced by the wedge fix. **Keep exactly
  one dashboard tab open during the demo.** Proper fix is per-connection fan-out; Anuj's call.
- **Measured frame shape** (fixtures, Day 8): 1,134,852 bytes · `cells.n = 41,990` ·
  `refined.n = 0` · 15 `stats` fields · `n_points_conserved == n_points == 121,344` ·
  `n_cells_total = 705,771`. Matches the ~42,000 cells / ~1.1 MB in Shubham's guide.
- **`mode` reads `"geometric"` in fixtures mode**, not `"fixtures"`. The FR-6 perception-mode
  badge must not imply live inference when the server is on `--fixtures`; decide how to
  present that honestly in Step 3.
- **`tracks` can be empty and `decision.selected` can be `"primary"`.** The decision panel must
  render an empty track list without breaking (Step 4).
  *Correction, Day 9:* this note originally said the fixture truck "crosses periodically". It
  did not — `_truck_position` was monotonic, so the truck crossed once in the first 8 s of
  server uptime and then drove away for good (26 km out by frame 100,000). That is why a live
  dashboard showed no track, no reroute and a frozen reason string. **Fixed** in
  `server/fixtures.py`: the trajectory now repeats on a 10 s cycle with a 1.9 s off-scene gap,
  so the run-book's "track appears" and reroute beats are rehearsable and the empty-`tracks`
  path still gets exercised. Anuj's file — tell him.

---

## 4. Do Not Touch — Shubham's viewer

These files are his. Do not edit, refactor, rename or "improve" them:

```
frontend/components/viewer/Viewer.tsx          useThreeScene.ts   views.ts
frontend/components/viewer/instancedCells.ts   pointCloud.ts      colouring.ts
frontend/components/viewer/ringGeometry.ts     types.ts           __dev__/devFrames.ts
frontend/lib/palette.ts
```

- **Integrate through the public seam only:** `<Viewer onReady={h => …} />` hands me a
  `SceneHandle` with `pushFrame` / `setView` / `getView` / `setColourMode` / `getColourMode` /
  `dispose`. That is the entire contract.
- Do not put the WebSocket inside the viewer. Do not re-derive ring geometry — `ringGeometry.ts`
  is already verified against `RingGrid` (662 rings, 705,771 cells). Do not import
  `__dev__/devFrames.ts` from anything outside `components/viewer/__dev__/`.
- `viewer/types.ts` is his mirror of the wire shapes. My `lib/protocol.ts` exports the canonical
  types and must stay **structurally compatible** so nothing in the canvas changes. If they need
  to converge, he makes that edit, not me.
- Two exceptions, and only with his agreement at standup: deleting the temporary `devStream`
  prop once the real stream is verified, and moving the temporary keyboard bindings out of
  `Viewer.tsx` into my HUD controls.

---

## 5. Roadmap

Status key: `[ ]` not started · `[~]` in progress · `[x]` done and verified.

> **Divergence from `WORK_DISTRIBUTION.md` §5.2 — raise at standup.** The document orders my
> work accounts-and-auth first (its Day 1–2). It is Day 8 with six days to the internal
> hackathon, Shubham is blocked on two of my files, and the demo is judged on the canvas and the
> HUD — not on the login page. So auth and persistence move behind the realtime path and the
> HUD. Nothing is dropped; the order changes. If this is wrong, Sameer decides.

### Step 0 — Environment and baseline `[x]`

**Objective.** A running dev loop and a first honest look at the canvas.
**Files.** None (no source changes). ✅ none made.
**Tasks.** `npm install` in `frontend/`. Create `backend/.venv`,
`pip install -r backend/requirements.txt`, `pip install -e model/`. Run
`python -m avr25d.server.app --fixtures`. Run `npm run dev`. Open `/dashboard`.
Branch `navya/platform-hud` off `main`.
**Verification.** `GET localhost:8000/health` returns `{"status":"ok","n_cells":705771}`;
`/dashboard` shows cells on the synthetic stream; console clean.
**Done when.** Both servers run and I have seen the canvas render — this closes item 10 of
Shubham's checklist, which nobody has verified.

**Status Day 8 — everything green except the one thing that needs eyes.**

- [x] Branch `navya/platform-hud` (pre-existing at `main`, reused)
- [x] `npm install` — 372 packages, 0 vulnerabilities
- [x] `backend/.venv` on Python 3.14.5, requirements + editable `model/`
- [x] `make test` → **347 passed, 0 failed** (Anuj logged 303; Sameer's later merges added 44)
- [x] `RingGrid` → 662 rings, 705,771 cells, `r_edge[-1] = 100.16604614` — matches
      Shubham's `ringGeometry.ts` port exactly
- [x] Fixture server up; `/health` → `{"status":"ok","n_cells":705771}`
- [x] `next dev` up; `GET /dashboard` → 200
- [x] `npx tsc --noEmit` clean · `npx eslint .` clean
- [x] WebSocket delivers decodable frames — probed one live frame end to end
- [x] **Canvas visually confirmed** — Navya opened `/dashboard` and the LiDAR scene renders
      correctly. Closes item 10 of Shubham's checklist, open since Day 8 session 1.

**Step 0 is complete.**

### Step 1 — `lib/protocol.ts` `[x]`

**Objective.** Decode the binary `FrameMessage` into the shape the viewer already consumes.
**Files.** `frontend/lib/protocol.ts` — created, 1 file, no other source touched.
**Tasks.** Read `header_len`, `JSON.parse` the header, map typed-array views in declaration
order over the payload. Handle the alignment and keepalive cases in §3. Export canonical
`FrameMessage`, `CellArrays`, `RefinedArrays`, `Track`, `Decision`, `FrameStats` types.
**Verification.** Decode one captured frame; assert `cells.n` matches the header, `ring`/`bin`
are within `[0, 662)` / `[0, RING_BINS[ring])`, `stats.n_points_conserved === stats.n_points`
(FR-10), and no field is `undefined` (T-V4).
**Done when.** A live fixture frame decodes without throwing and the arrays are the right
lengths and dtypes.

**Verified Day 8 — 118 assertions, 0 failures.** Method: decode the *same bytes* in Python and
TypeScript and compare, using Anuj's `encode`/`decode` as the oracle rather than my reading of
the spec.

- [x] All 16 arrays across 4 frames **byte-identical to numpy** (SHA-1 per array), correct
      dtype and length
- [x] NaN preserved exactly in `z_obstacle` — flat cells legitimately carry NaN and a naive
      copy would smear it
- [x] Fixtures: live 41,990-cell frame · misaligned `refined` (n=3, `27n % 4 == 1`) ·
      aligned (n=4) · empty (n=0, m=0)
- [x] All 15 `stats` fields, `decision` (incl. a reason string with quotes, `°` and `✓`),
      `tracks[].predicted` match the header exactly
- [x] FR-10 conservation held on every frame
- [x] Zero-length keepalive → `null`, no throw
- [x] Truncated header / truncated payload / 2-byte buffer → `ProtocolError`
- [x] **Sentinel drift guard**: corrupting `cells.class_id` to `uint16[...]` throws rather than
      silently rendering a wrong picture — protects against the frozen protocol moving
- [x] Compile-time proof the output satisfies Shubham's `viewer/types.ts` (`FrameMessage`,
      `CellArrays`, `FrameStats`), with a **negative control** confirming the check is not
      vacuous — switching `FrameStats` to an `interface` fails to compile
- [x] `tsc --noEmit` and `eslint` clean across the project
- [x] Decode cost on a real 1.13 MB frame: **mean 0.131 ms**, p95 0.193 ms — **0.4% of the
      33 ms budget, 252× headroom**. Settles the "zero copies" question empirically: the one
      contiguous copy is free at this scale.

### Step 2 — `lib/ws.ts` and stream cut-over `[x]`

**Objective.** Real frames on screen; **Shubham unblocked**.
**Files.** `frontend/lib/ws.ts` (new), `frontend/app/dashboard/page.tsx` (cut-over). No file of
Shubham's touched.
**Tasks.** `connectFrames(url, onFrame): () => void` — `binaryType = 'arraybuffer'`,
exponential-backoff reconnect, skip empty messages, drop rather than queue, never awaited.
Switch the dashboard to `<Viewer onReady={h => connectFrames(url, h.pushFrame)} />`. Retire the
`devStream` path once verified (with Shubham).
**Verification.** T-W6 — no Next.js handler in the network trace for `/stream`, and killing
`next dev` mid-stream does not interrupt rendering. Reconnect works after restarting the server.
**Done when.** Views 1 and 3 render **real streamed frames** — this closes Shubham's Day 3.

**Status Day 9 — code complete and verified headlessly; two browser checks outstanding.**

- [x] `connectFrames(url, onFrame, opts?)` returning a disconnect function, per
      `IMPLEMENTATION_PLAN.md §6.14`
- [x] Dashboard cut over to the live stream; `devStream` no longer passed (Shubham's synthetic
      generator stays in the tree as his offline fallback — his file, his call to remove)
- [x] **Drop-not-queue proved under a slow consumer**: 100 ms/frame consumer against a 30 Hz
      stream → delivered 34, dropped 78, and the last frame delivered was id **109 while 111
      had been received**. Two frames behind in time, not 78. That is NFR-1 — degrade in frame
      rate, never in latency — measured rather than asserted
- [x] Delivered frame ids strictly increasing — a stale frame is never replayed
- [x] Reconnect after server hangup: 2 connects, `reconnecting` → `open`, backoff reset
- [x] Zero-length keepalives skipped, every message accounted for
      (delivered + dropped + keepalives)
- [x] `disconnect()` idempotent; no frames delivered after it; no reconnect scheduled
- [x] End-to-end against the real fixture server: **108 frames, 41,990 cells each, 0 errors**,
      ids consecutive 388 → 495
- [x] `tsc --noEmit` and `eslint` clean
- [x] **T-W6 part 1** — no Next.js handler in the network trace for `/stream`; the browser
      talks straight to `ws://localhost:8000/stream` (FR-41). Confirmed by Navya, Day 9
- [x] **T-W6 part 2** — `next dev` killed mid-stream, canvas kept rendering. Confirmed by
      Navya, Day 9
- [x] Views render real streamed frames in the browser — **this closes Shubham's Day 3 exit
      criterion**, open since Day 8

**Step 2 is complete.** T-W6 passes.

**Navya: the browser checks need you** (no working browser tool in any session so far). Open
`http://localhost:3000/dashboard`, then DevTools → Network → WS. Refreshing is now safe — the
wedge is fixed — but keep to **one tab**, or the two connections will starve each other (§3).

**Added Day 9 after the blank-dashboard incident:**

- [x] `connectTimeoutMs` (default 5 s) in `ws.ts` — a socket that never completes its handshake
      now times out and retries instead of sitting in `connecting` forever. Verified against a
      listener that accepts and never handshakes: 4 retry attempts in 7 s, where the old code
      made exactly 1 and then waited indefinitely
- [x] `components/hud/StreamStatus.tsx` — connection state on screen, so "no frames" can never
      again look identical to "working". A leaf component; the viewer element is memoized so a
      status change cannot re-render the canvas (T-W7)

### Step 3 — HUD `[x]`

**Objective.** FR-28 on screen, every value from `stats`.
**Files.** `frontend/components/hud/{Hud,LatencyBars,MemoryPanel,ModeBadge,types,format}.tsx|ts`,
`frontend/app/dashboard/page.tsx`. No file of Shubham's touched.
**Tasks.** FPS, per-stage latency (perception / projection / analysis / refine / decision /
serialise), total latency, occupied cells, AVR-25D memory, baseline memory, reduction factor,
perception-mode badge (FR-6), frame index. Throttled leaf subscription; memoize `<Viewer>`.
Large, high-contrast type — it is judged on a projector.
**Verification.** T-V4 — no `NaN`, no `undefined`, across a full fixture run. T-W7 — render
counter stays under 10 across 300 frames (expect 2 in dev; StrictMode double-renders on mount).
**Done when.** Every FR-28 field is populated from real frames and T-W7 still passes.

**Status Day 9 — built and verified headlessly; the render count needs a browser.**

Every FR-28 field is present and sourced, not computed:

| Field | Source |
|---|---|
| FPS (pipeline) | `stats.fps` |
| FPS (rendered), 1% low, instances | `SceneHandle.getPerf()` |
| Per-stage latency ×6, total | `stats.t_*_ms` |
| Occupied cells | `stats.n_cells_occupied` |
| AVR-25D / baseline memory, reduction | `stats.mem_bytes`, `stats.baseline_mem_bytes`, `stats.reduction` |
| Grid capacity | `SceneHandle.getGridCapacity()` |
| Uniform capacity | `SceneHandle.getUniformCounts()` |
| Perception mode (FR-6) | `FrameMessage.mode`, verbatim |
| Frame index | `FrameMessage.frame_id` |
| Points conserved (FR-10) | `stats.n_points_conserved` / `stats.n_points` |

- [x] **T-V4 — 17 assertions, 0 failures.** Components rendered with
      `react-dom/server` against a real captured frame *and* against degenerate stats with
      `undefined` / `NaN` / `null` fields. No `NaN` or `undefined` reaches the markup in either
      case; missing values fall back to an em dash
- [x] Reduction, capacities and mode all render from their source, verified by asserting on
      the markup (`22.67×`, `705,771`, `16,000,000`, `GEOMETRIC`)
- [x] An unrecognised mode string surfaces as-is rather than being mapped to a default
- [x] `tsc --noEmit`, `eslint`, and a full `next build` (Turbopack) all clean — 5 static routes
- [x] **T-W7 passes — 304 frames → 2 React renders**, against a limit of 10. Confirmed by Navya
      in the browser, Day 9. Adding the HUD did not cost a single render: the count went from
      Shubham's 3 to 2, which is the StrictMode mount pair and nothing else. The HUD owns its
      own state, `DashboardPage` holds none, and the `<Viewer>` element is memoized so it sits
      outside the HUD's subtree
- [x] Panel legible and correct in the browser — confirmed by Navya

**Step 3 is complete.** T-V4 and T-W7 both pass.

### Step 4 — View controls and decision panel `[~]`

**Objective.** Drive the demo from the UI; make the reroute legible.
**Files.** `frontend/components/hud/ViewControls.tsx`,
`frontend/components/decision/{DecisionPanel,TrackList}.tsx`,
`frontend/app/dashboard/page.tsx`. No file of Shubham's touched.
**Tasks.** Buttons/keys for views 1–4, elevation toggle, ring overlay, wipe — calling
`SceneHandle`, gracefully disabled for views Shubham has not built. Decision panel: selected
route, risk, ETA, reason string. Track list: id, class, speed.
**Verification.** Run-book beats 58–82 s work: track appears, reroute fires, reason string
readable from three metres.
**Done when.** The demo can be driven without touching the keyboard bindings inside `Viewer.tsx`.

**Status Day 9 — built and verified headlessly; the interactions need a browser.**

- [x] Buttons for all four views, elevation, grid overlay and wipe, each showing its run-book
      key so the presenter can use either
- [x] Control state is **read back** from `SceneHandle` at 4 Hz, so pressing `3` on the keyboard
      moves the button highlight too. A panel that drifted out of sync with the scene would be
      worse than no panel
- [x] Decision panel: selected route, risk, ETA, route/alternative point counts, and the reason
      string verbatim — 15 px with a rule beside it, sized to read from three metres
- [x] Track list: id, class name from `palette.ts`, speed
- [x] **`tracks: []` handled** — and confirmed to be the *normal* case, not an error: the live
      fixture frame used in the test genuinely carries an empty array, because the crossing
      truck is only in frame for part of its trajectory. Renders "No dynamic objects in view"
- [x] **24 assertions, 0 failures** on the decision components; the earlier 17 HUD assertions
      still pass. Covers a real primary/LOW frame, a reroute frame (ALTERNATIVE/HIGH, one
      track), a missing `decision` entirely, an out-of-range `class_id`, and a `NaN` speed. No
      `NaN` or `undefined` reaches the markup in any of them
- [x] `tsc`, `eslint` and `next build` clean; `/dashboard` still prerenders, which exercises the
      controls' no-handle path
- [ ] **Browser: the controls actually drive the scene** — each button changes the view, and
      keyboard and buttons stay in sync
- [ ] **Browser: the A/B wipe button shows the draggable divider** (see the constraint below)
- [ ] **Browser: run-book beats 58–82 s** — track appears, reroute fires, reason legible from
      three metres. *First attempt showed nothing: the fixture truck crossed once in the first
      8 s of server uptime and never returned. That was a fixture bug, not a panel bug — fixed
      Day 9 (§7). Re-check: a track and a reroute should now recur every 10 s.*

**One integration constraint, and it is Shubham's to close.** `setWipe()` on `SceneHandle`
drives the scissor-rect render, but the draggable divider is a React overlay inside
`Viewer.tsx` gated on `wipeOn`, a piece of state only that file's own key handler sets. Calling
`setWipe()` from outside would enable the wipe with no draggable divider — worse than not
offering the button. So the wipe control **dispatches the `W` keystroke**, driving his existing
tested path and keeping his state and the scene in step, with a direct `setWipe()` fallback if
the viewer was mounted without `enableKeyboard`. It works, but it is a seam, not a design: the
clean fix is a controlled prop or an `onWipeChange` callback on `Viewer`. **His file, his call —
raise at standup.**

**Not implemented, deliberately: "gracefully disabled for views Shubham has not built."** All
four views are built as of his PR #2, and his `NOT_BUILT` set is now empty. Duplicating that
list here would create a second source of truth that goes stale the moment it disagrees with
his.

### Step 5 — NFR-9 verification `[ ]`

**Objective.** Close the mixed-content trap before it costs a day.
**Files.** None yet — a written finding in §7 and later a line in the run-book.
**Tasks.** Confirm the demo path is `http://localhost:3000` against the local FastAPI server;
confirm an HTTPS origin cannot reach `ws://localhost:8000`.
**Done when.** Recorded in the log and told to the team. ~15 minutes.

### Step 6 — Auth `[ ]`

**Objective.** FR-36 / FR-37 — the gate and server-side token verification.
**Files.** `frontend/lib/firebase/{client,admin}.ts`, `frontend/app/(auth)/login/page.tsx`,
middleware, `frontend/.env.local.example`.
**Tasks.** Create the Firebase project **first** (external lead time). Email/password + Google
providers. Gate `/dashboard`. `requireUser(req)` in `admin.ts`. Service-account JSON goes in
`FIREBASE_SERVICE_ACCOUNT` as a single-line env var and is **never committed**.
**Verification.** T-W1 — unauthenticated `/dashboard` redirects to `/login`; both providers
complete a sign-in.
**Done when.** T-W1 passes and `.env.local.example` documents every variable.

### Step 7 — Persistence `[ ]`

**Objective.** FR-38 / FR-39 / FR-40 — runs, decisions, scenes.
**Files.** `frontend/lib/mongo.ts`, `frontend/app/api/{runs,decisions,scenes}/route.ts`.
**Tasks.** Atlas M0, database `avr25d`, `MONGODB_URI`. Module-scoped cached client. Collections
and indexes per `IMPLEMENTATION_PLAN.md §6.14`: `runs {uid:1, startedAt:-1}`,
`decisions {runId:1, frameId:1}`, `scenes {name:1}` unique, `users`. `requireUser` first in
every write handler. Batched decision writes.
**Verification.** T-W2 (401 before any Mongo call, asserted per route), T-W3 (run round-trips
byte-identically against `results.json`), T-W4 (600-frame replay with 2 reroutes → 2 change
records + ~10 heartbeats, not 600), T-W5 (scene ground truth equals the CSV).
**Done when.** All four tests pass.

### Step 8 — Run history, deploy, polish `[ ]`

**Objective.** The submission link and the last rough edges.
**Files.** `frontend/app/runs/page.tsx`, `frontend/app/runs/[id]/page.tsx`,
`frontend/app/page.tsx`, `frontend/app/layout.tsx`.
**Tasks.** Run list and detail (config, results, decision log). Replace the create-next-app
boilerplate and the "Create Next App" metadata. Deploy to Vercel for the link, keeping
localhost as the demo path. Responsive at the demo machine's resolution.
**Done when.** A completed run renders its config, results and decision log; Vercel is live;
zero console errors.

---

## 6. Definition of done

- [ ] T-V4 — HUD shows no `NaN` and no `undefined` field
- [ ] T-W1 — unauthenticated `/dashboard` redirects; both providers sign in
- [ ] T-W2 — every write route rejects a bad token with 401 before touching Mongo
- [ ] T-W3 — a run document round-trips against `results.json`
- [ ] T-W4 — decision writes are batched, not per frame
- [ ] T-W5 — every scene's ground truth matches its CSV
- [ ] T-W6 — the frame stream is browser→FastAPI direct
- [ ] T-W7 — fewer than 10 React renders across 300 streamed frames
- [ ] NFR-9 verified and written down
- [ ] Every HUD number traces to `stats`; none computed in the browser
- [ ] No hard-coded colours outside `lib/palette.ts`
- [ ] Zero console errors on `/dashboard`; layout correct at demo resolution

---

## 7. Progress log

### Day 9 · Saturday 5 Sep 2026 (session 5) — the fixture truck drove away and never came back

**Landed.** `model/avr25d/server/fixtures.py` — the truck trajectory is periodic. One
expression, plus the comment explaining why. No protocol change, no frontend change.

**Acceptance.** The symptom Navya reported — only the ETA moving, no track, no reroute, a
frozen reason string — is gone. Suite still **347 passed, 0 failed**.

**Decisions and surprises.**

1. **`_truck_position` was monotonic, not periodic.** `y = -30 + 8t` grows without bound, so
   the truck crossed once during the first 8.1 s of server uptime and left for good: 50 m out
   at frame 300, **26 km at frame 100,000**. Measured against the generator, not inferred —
   tracks existed only in frames 0–243 and the reroute only in frames 94–206, out of an
   unbounded stream.
2. **The frontend was innocent, and its own dev stream is what hid this.** Shubham's
   `__dev__/devFrames.ts` loops its truck with `(t * 8) % 60`, so View 4 was built and verified
   against a stream where the crossing repeats every 7.5 s. The server never looped. The viewer
   looked right in development and empty against the real stream, and nothing in either
   codebase was wrong on its own terms.
3. **My Day 8 note asserted the fixture truck "crosses periodically".** I never checked it. It
   was wrong then and it is the reason this took a report from Navya to surface rather than
   being caught when I first probed the stream. §3 now carries the correction rather than a
   quiet edit.
4. **Chose an 80 m cycle over devFrames' 60 m.** A 60 m cycle keeps the truck inside the
   ±35 m visibility window at all times, so a dynamic object would be permanently parked in
   view: the run-book's "track appears" beat would never happen and the empty-`tracks` path
   would stop being exercised. 80 m gives a 10 s cycle with a 1.9 s off-scene gap, which
   reproduces the original crossing exactly and then repeats it.
5. **Verified the way the bug was found, not the way that is convenient.** Connecting to the
   generator offline proves the maths; the failure was about *when a browser connects*. So the
   live check waits 40 s after server start — long past the original single crossing — and then
   watches for 25 s: **3 separate track appearances, 3 separate reroutes, both reason
   strings.**
6. **Second edit to Anuj's module this session** (`app.py`, now `fixtures.py`). Both were
   demo-critical and both were done on Navya's explicit instruction, but two files of his have
   now changed without him in the loop. **That needs to be one conversation at standup, not a
   surprise in a diff.**

**Next step.** Navya re-runs browser check 3 from §5 Step 4.

---

### Day 9 · Saturday 5 Sep 2026 (session 4) — Step 4: controls and the decision panel

**Landed.** `components/hud/ViewControls.tsx`,
`components/decision/{DecisionPanel,TrackList}.tsx`, and the dashboard wiring. The demo is
drivable from the UI. No file of Shubham's touched.

**Acceptance.** Step 4 is **`[~]`**: 24 new assertions pass alongside the existing 17, and
`tsc`, `eslint` and `next build` are clean — but every remaining item is an interaction, and
interactions need a browser. Checklist in §5 Step 4.

**Blocked / blocking.** Not blocked. One item for Shubham at standup — the wipe seam below.

**Decisions and surprises.**

1. **The wipe cannot be driven cleanly through `SceneHandle`.** `setWipe()` runs the
   scissor-rect render, but the draggable divider is a React overlay inside `Viewer.tsx` gated
   on state only that file's key handler sets — so an external `setWipe(true)` gives a wipe with
   no draggable divider, which is worse than no button. The control therefore **dispatches the
   `W` keystroke** to drive his existing path, with a direct `setWipe()` fallback. It works and
   it touches nothing of his, but it is a seam: the clean fix is a controlled prop on `Viewer`.
   **His file, his call.**
2. **Controls read their state back from the scene.** Shubham's key bindings are still live, so
   the panel polls `getView` / `getColourMode` / `getGridOverlay` / `getWipe` at 4 Hz. Without
   that, pressing `3` would move the scene and leave the buttons lying about it — and the
   run-book has the presenter using keys.
3. **`tracks: []` is the normal case, not an edge case.** The live fixture frame in the test
   genuinely carries an empty array — the crossing truck is only in frame for part of its
   trajectory. Worth stating plainly because "handle the empty case" reads like defensive
   programming until you notice it is what the server sends most of the time.
4. **Split the decision panel into a sampling wrapper and a pure view.** `DecisionView` is a
   function of one snapshot, so the missing-data paths — no `decision`, unknown `class_id`,
   `NaN` speed — are rendered and asserted rather than reasoned about. The refactor was for
   testability but it is the better shape anyway; the timer and the markup are different jobs.
5. **Did not implement "gracefully disabled for views Shubham has not built."** All four views
   exist as of his PR #2 and his `NOT_BUILT` set is empty. Copying that list into my file would
   be a second source of truth that goes stale the moment it disagrees with his.
6. **Risk colours are deliberately not the class palette.** `palette.ts` is explicit that class
   colour answers "what is it"; risk answers "how dangerous is it". Sharing a colour between
   the two axes in one frame would be exactly the confusion that file exists to prevent, so the
   three risk colours are local and commented as such.

**Next step.** Navya runs the three browser checks in §5 Step 4. Then Step 5 — NFR-9, which is
fifteen minutes — and after that auth and persistence.

---

### Day 9 · Saturday 5 Sep 2026 (session 3) — Step 3: the HUD

**Landed.** `components/hud/{Hud,LatencyBars,MemoryPanel,ModeBadge,types,format}` and the
dashboard wiring. Every FR-28 field is on screen. No file of Shubham's touched.

**Acceptance.** Step 3 is **`[~]`**: T-V4 passes (17 assertions, including degenerate input),
and `tsc`, `eslint` and a full `next build` are clean. T-W7 needs a browser and is not claimed.
Field-by-field sourcing table in §5 Step 3.

**Blocked / blocking.** Nothing.

**Decisions and surprises.**

1. **The mode badge shows `FrameMessage.mode` verbatim and infers nothing.** It is tempting to
   label fixture runs "fixtures", but the wire cannot support it: `--fixtures` reports
   `"geometric"`, byte-identical to a real geometric run. A badge that guessed would be
   asserting something the pipeline never said, which is precisely what FR-6 exists to
   prevent — "is the segmentation running live?" is on the judge Q&A list and the documented
   answer is "the HUD says so, always". If the demo needs the distinction, **the server must
   put it on the wire**; that is a protocol change and Anuj's call.
2. **Nothing in the HUD computes a displayed quantity.** Reduction, memory and cell counts come
   from `stats`; render FPS, capacities and uniform counts come from Shubham's getters. The one
   arithmetic expression is the conservation percentage, which is a ratio of two reported
   counts — the assertion behind it lives in `CellGrid.accumulate`.
3. **The FR-42 boundary is sampling, not streaming.** Frames land in a ref; the HUD reads that
   ref on a 4 Hz timer. Per-frame state would reconcile this subtree 30 times a second, and it
   is also unreadable — digits changing 30 times a second are not information. The `<Viewer>`
   element is memoized, so it sits outside the HUD's subtree and cannot re-render regardless.
4. **T-V4 is testable without a browser.** `react-dom/server` renders the panels to markup and
   the test greps for `NaN` and `undefined`, including a deliberately degenerate stats object.
   That caught the class of bug T-V4 is actually about — a missing field printing as
   `undefined` on a projector — without waiting for a browser session.
5. **Latency bars scale against the 33 ms budget, not the largest stage.** A self-scaling chart
   silently re-normalises whenever one stage spikes, so the picture would look identical at
   5 ms and 50 ms. Same reasoning as the fixed elevation range in `palette.ts`.

**Confirmed by Navya, same day.** **T-W7 passes: 304 frames → 2 React renders** (limit 10), and
the panel reads correctly. Worth recording that the count *fell* from Shubham's 3 to 2 — adding
the HUD cost nothing, because sampling into a leaf never touches the canvas subtree. Step 3 is
**`[x]`**.

**Next step.** Step 4 — view controls and the decision panel. The controls should drive
`SceneHandle` (`setView`, `setColourMode`, `setGridOverlay`, `setWipe`, `setDivider`) and let me
retire the temporary keyboard bindings inside `Viewer.tsx` — Shubham's file, so his call at
standup. The decision panel must handle `tracks: []`, which fixtures do emit (§3).

---

### Day 9 · Saturday 5 Sep 2026 (session 2) — blank dashboard: the server bug, fixed

**Landed.** `model/avr25d/server/app.py` — the disconnect wedge is fixed. `lib/ws.ts` gains a
connect timeout. `components/hud/StreamStatus.tsx` puts connection state on screen.

**Acceptance.** The reported symptom is resolved and the underlying bug is gone, not worked
around. Backend suite still **347 passed, 0 failed**.

**Blocked / blocking.** Nothing. Step 2's two T-W6 browser checks remain open.

**Decisions and surprises.**

1. **The blank page was not a frontend bug.** The backend was wedged: listening, `R+` at 74%
   CPU, `/health` timing out, handshakes never completing. With no frames the scene draws
   *nothing* — Shubham removed the `GridHelper` deliberately — so an empty scene is a blank
   canvas. Blank was the honest rendering of no data.
2. **`sample` gave the proof.** The main thread sat in
   `lock_PyThread_acquire_lock → _PyMutex_LockTimed → _PySemaphore_Wait` — the blocking
   `queue.get` running on the event loop thread. Worth remembering: macOS ships `sample`, and
   it turned a plausible theory into evidence in one command.
3. **There were two bugs, not one.** The blocking `get` was half of it; the handler also never
   called `receive()`, so ASGI's disconnect message was never read and the loop kept "sending"
   into a dead socket forever. Fixing only the first would have left it spinning.
4. **My first two fixes were slower than the bug.** Per-frame `asyncio.to_thread` and then a
   long-lived drain thread both measured **~13 fps against the original's ~27** — the helper
   thread wakes on every frame and trades the GIL with the event loop, and that handoff costs
   more than the blocking call it replaced. A plain non-blocking poll with a 2 ms yield
   restored **~26 fps / 29 MB/s**. Measured on an isolated port, three runs each; I would have
   shipped a 2× throughput regression on the strength of "it no longer wedges".
5. **A blocked server is invisible to a WebSocket client.** It still accepts TCP, so the
   browser sits in `CONNECTING` with no error and no `close` event — no reconnect, nothing in
   the console but "connecting". That was a real gap in my `ws.ts`, now closed with
   `connectTimeoutMs`.
6. **Two clients starve each other** (§3). Discovered when my test client got 0 frames while a
   raw client got 102: Chrome had the tab open and was taking them all. Pre-existing, not
   caused by the fix, and a demo hazard worth naming — one tab only.
7. **I edited Anuj's module.** `server/app.py` is his under §1. Done on Navya's explicit
   instruction because it is demo-fatal; the change is confined to the WebSocket handler, the
   reasoning is in comments at the point of change, and the suite is green. **He needs to be
   told, not discover it in a diff.**

**Confirmed by Navya, same day.** The dashboard renders real streamed frames, and **both T-W6
checks pass** — no Next.js handler in the trace for `/stream`, and the canvas survives killing
`next dev`. Step 2 is **`[x]`**, and **Shubham's Day 3 exit criterion is closed** after two days
blocked on it.

**Next step.** Step 3 — the HUD (FR-28). Two things to settle before writing it: the FR-6 mode
badge cannot distinguish `--fixtures` from a real geometric run (both report
`mode: "geometric"`), and the HUD must read `SceneHandle`'s getters rather than compute
anything. T-W7 currently passes at 3 renders over 316 frames; the HUD is the thing that could
break it.

---

### Day 9 · Saturday 5 Sep 2026 (session 1) — Step 2: the stream is live

**Landed.** `frontend/lib/ws.ts` and the cut-over in `app/dashboard/page.tsx`. Merged
`origin/main` (Shubham's PR #2) into the branch first — see decision 1. No file of Shubham's
touched.

**Acceptance.** Step 2 is **`[~]`**: the code is complete and verified headlessly, but the two
T-W6 checks are browser-only and I had no working browser tool this session. Not claiming them.
Details and the exact checks for Navya are in §5 Step 2.

**Blocked / blocking.** Shubham's Day 3 criterion — "views render real streamed frames" — is
now satisfiable; it needs one look in a browser to confirm. Nothing blocks me.

**Decisions and surprises.**

1. **`main` had moved and the merge was not optional.** Shubham's PR #2 landed View 2, the A/B
   wipe, View 4, T-V6 and T-W7 — and changed `types.ts`, `Viewer.tsx` and `useThreeScene.ts`,
   the exact interfaces I integrate against. Merged before writing any Step 2 code, then re-ran
   the compatibility proof: my decoder still satisfies his types, **including the `Track` and
   `Decision` interfaces he added**, which my `protocol.ts` had independently declared. The
   `onReady`/`pushFrame` seam is unchanged. Clean merge, no conflicts.
2. **`SceneHandle` grew a lot and most of it is HUD material** — `getPerf()`, `getFrameCount()`,
   `getUniformCounts()`, `getGridCapacity()`, `setGridOverlay()`, `setWipe()`, `setDivider()`,
   `onDividerChange()`. Step 3 and Step 4 should read these rather than compute anything.
3. **"Drop rather than queue" needed a real test, and my first one was wrong.** I asserted the
   burst would be mostly dropped; it was not, because on localhost the *transfer* is the
   bottleneck, not the consumer, so the pump kept up and there was nothing to drop. Rewrote it
   with a deliberately slow consumer (100 ms/frame against 30 Hz). Result: delivered 34,
   dropped 78, and the newest delivered frame was **2 behind the newest received, not 78**.
   That is the property NFR-1 actually asks for, and the first test would have passed without
   demonstrating it.
4. **A stall does not trigger a reconnect, on purpose.** Given Anuj's wedge bug, a backoff loop
   hammering a blocked server makes things worse. `ws.ts` reports `stalled` through `onStatus`
   and reconnects only on a genuinely closed socket. Revisit once `app.py` is fixed.
5. **Anuj's server bug reproduced a third time**, this time from `lib/ws.ts`'s own clean
   `disconnect()`. `/health` stopped answering immediately afterwards. Still unfixed, still
   Anuj's, still the highest-priority item on the board — **a refresh of `/dashboard` will kill
   the backend during the demo**.
6. **The editable install had silently stopped working.** `import avr25d` failed from any
   directory; the `.pth` was present and correct but not executing at interpreter startup, so
   the package resolved only when `cwd` happened to be `model/`. Every earlier command had run
   with `cd model`, which masked it. Fixed with `pip install -e model/ --force-reinstall
   --no-deps` and **verified from `/tmp`** rather than from the directory that hides the
   problem. Worth knowing if anyone else sees a sudden `ModuleNotFoundError`.
7. **Shubham had already done the Next 16 compliance check** (`bc507a0`) and recorded the
   outcome — `ssr: false` is Client-Component-only and `dashboard/page.tsx` already carries
   `'use client'`. Read his finding instead of repeating the audit.

**Next step.** Navya runs the two browser checks above. Then Step 3 — the HUD — which should
read `SceneHandle`'s new getters and must keep React renders under 10 (T-W7 currently passes at
3 renders over 316 frames; the HUD is what could break it).

---

### Day 8 · Friday 4 Sep 2026 (session 3) — Step 1 done; a demo-fatal server bug found

**Landed.** `frontend/lib/protocol.ts` — binary `FrameMessage` decode, mirroring the frozen
`avr25d/server/protocol.py`. One file. No other source touched. Canvas visually confirmed by
Navya, so **Step 0 is closed** and Shubham's checklist item 10 is finally ticked.

**Acceptance.** Step 1's criterion — "a live fixture frame decodes without throwing and the
arrays are the right lengths and dtypes" — is **met and then some**: 118 assertions, 0 failures,
verified by decoding identical bytes in both languages and comparing per-array SHA-1 against
numpy. Details in §5 Step 1.

**Blocked / blocking.** Shubham is **half unblocked** — the decoder exists; `lib/ws.ts`
(Step 2) is the remaining half. Nothing blocks me.

**Decisions and surprises.**

1. **`server/app.py` wedges permanently when a WebSocket client disconnects. This is
   demo-fatal and it is Anuj's to fix — I have not touched it.**
   Line 487 calls `worker._queue.get(timeout=2.0)` — a *synchronous* `queue.Queue.get` inside
   an `async def` handler. It blocks uvicorn's event loop instead of yielding to it.
   Reproduced twice, deterministically: after any client goes away, the server stops serving
   `GET /health`, never completes the WebSocket close handshake, and **ignores SIGTERM**
   (graceful shutdown needs a running loop) — it takes `kill -9`. Both an abrupt kill and a
   clean `ws.close(1000)` trigger it.
   **Why nobody hit it before:** Shubham's viewer has only ever run on `__dev__/devFrames.ts`,
   so mine is the first real client the server has seen.
   **Why it matters:** a browser refresh of `/dashboard` is exactly this disconnect. In front
   of judges, one refresh kills the backend until someone force-kills it from a terminal.
   **Likely fix (Anuj's call):** `await asyncio.to_thread(worker._queue.get, ...)`, or an
   `asyncio.Queue` fed from the worker via `loop.call_soon_threadsafe`. **Raise at the 21:00
   checkpoint — this outranks anything on my board.**
2. **The "zero copies" question is settled by measurement, not argument.** One contiguous
   payload copy costs **0.131 ms mean** on a real 1.13 MB / 41,990-cell frame — 0.4% of the
   33 ms budget, 252× headroom. No reason to ask Anuj to pad the frozen header. Dropping that
   request.
3. **`FrameStats` had to be a `type`, not an `interface`.** `viewer/types.ts` types stats as
   `{ [key: string]: number | string }`, and TypeScript grants implicit index signatures only
   to type aliases. As an interface the viewer would have rejected every decoded frame. Proved
   both directions — the compat check passes as a type alias and fails as an interface.
4. **The refined stride is 15 bytes, not 14.** My own doc comment said 14; the code computed it
   from the field table and was right, and the cross-check against
   `protocol.py::_REFINED_FIELDS` caught the stale comment. Fixed. Worth noting that the code
   was right *because* the constant is derived rather than typed by hand.
5. **Live frames are ~1,134,850 bytes but the length varies frame to frame** (1134846 /
   1134849 / 1134853 observed) — the JSON header breathes with the reason string and float
   formatting. Nothing may assume a fixed frame size or a fixed payload offset.
6. **The decoder validates sentinels and fails loudly on drift.** If `protocol.py` ever moves,
   the frontend throws a named `ProtocolError` naming the field instead of rendering a
   plausible but wrong picture. Given "frozen" is a social contract, not an enforced one, that
   seemed worth the 16 string comparisons per frame.

**Next step.** Step 2 — `lib/ws.ts` and the stream cut-over. Note that Step 2's reconnect logic
will repeatedly disconnect from the server, so **finding 1 should be fixed first** or Step 2's
verification will spend its time fighting a wedged backend.

---

### Day 8 · Friday 4 Sep 2026 (session 2) — Step 0: environment up, baseline green

**Landed.** No source files created or modified. Environment only: `frontend/node_modules`
(372 packages), `backend/.venv` on Python 3.14.5 with requirements and editable `model/`,
working branch `navya/platform-hud`.

**Acceptance.** Step 0 is **`[~]` partial**. Every mechanical check passes — suite 347/347,
`RingGrid` 662/705,771, `/health` correct, `/dashboard` 200, `tsc` and `eslint` clean, and a
live frame decoded off the WebSocket. The one criterion I could not meet is the one that
matters most: **nobody has looked at the canvas yet.** I have no working browser tool this
session, so I am not claiming it. Shubham's checklist item 10 remains open for the second day.

**Blocked / blocking.** Still blocking Shubham on `lib/protocol.ts` + `lib/ws.ts` — Step 1
starts next. Nothing blocks me.

**Decisions and surprises.**

1. **The alignment problem is real, measured on the first frame.** `header_len = 1118` puts the
   payload at byte **1122 — `% 4 == 2`**. A direct `Uint32Array` view over the received buffer
   throws immediately; this is not an edge case, it is every frame. The `slice()`-then-view
   approach in §3 is now the confirmed plan, not a precaution. Raising the header-padding
   option with Anuj, but not blocking on a frozen file.
2. **Fixtures report `mode: "geometric"`, not `"fixtures"`.** The FR-6 badge must not imply
   live inference while the server is on `--fixtures`. Noted against Step 3.
3. **`tracks` can be empty.** Sampled a frame with `tracks: []`, `selected: "primary"`,
   `risk: "LOW"`. The fixture truck crosses periodically. The decision panel must handle the
   empty case — noted against Step 4.
4. **The suite is 347 tests, not the 303 in `anuj.md`.** Sameer's hazard/bench merges added 44.
   No failures; just a stale number in an older log.
5. **Measured frame:** 1,134,852 bytes, 41,990 cells, `refined.n = 0`, conservation
   121,344 == 121,344. Confirms the ~42,000 / ~1.1 MB figures in Shubham's guide.
6. **Two process notes.** A parallel shell `cd` leaked and created a stray
   `frontend/backend/.venv`; caught and removed within the minute — use absolute paths for
   venv creation. And I declined to add `.claude/launch.json` for the preview tool because it
   would land an untracked file in everyone's `git status` for a step declared "no source
   changes".

**Next step.** Step 1 — `lib/protocol.ts`. Both servers are left running for the visual check.

---

### Day 8 · Friday 4 Sep 2026 (session 1) — track opened; analysis only, no code

**Landed.** This document. No source files created or modified.

**Acceptance.** Nothing from `WORK_DISTRIBUTION.md` §5.2 is met yet. The platform track is at
**Day 0** while the calendar is at Day 8 — recording the gap rather than renumbering around it,
same as Shubham did. Six days to the internal hackathon.

**Blocked / blocking.** Nobody blocks me — `fixtures.py`, the frozen protocol and the live
server have all been available since Day 6. **I block Shubham** on `lib/protocol.ts` and
`lib/ws.ts`; until they land his viewer runs on synthetic frames and his Day 3 exit criterion
stays unmet.

**Decisions and surprises.**

1. **Roadmap order diverges from the document** — realtime path and HUD before auth and
   persistence. Rationale in §5. To be confirmed at standup.
2. **The "zero copies" decode is not reachable as specified.** The payload starts at
   `4 + header_len`, an arbitrary offset, and the cells block is 27 bytes per cell, so
   `refined.parent_id` is 4-aligned only when `n % 4 === 0`. Typed-array views will throw.
   Mitigation is a `slice()` of the payload plus a per-array copy fallback; the alternative is
   padding the header, which touches a frozen file. Raise with Anuj, do not block.
3. **The server sends `b""` keepalives** while the pipeline queue is empty, and `frame_id` does
   not start at 0. Both will break a naive client.
4. **The stack is Next 16 / React 19, not Next 14** as every planning document says. Also
   `frontend/`, not `webapp/`. Treating the code as the source of truth.
5. **The HUD is the FR-42 risk, not the canvas.** A `setState` per frame is 30 renders a second
   and would fail T-W7 on a component Shubham has already made clean. Throttled leaf state plus
   a memoized `<Viewer>`.
6. **Firebase and Atlas are unconfirmed.** No `.env*`, no `firebase`/`mongodb` dependencies. If
   the accounts do not exist, Step 6 starts with account creation and its lead time.

**Next step.** Step 0 — environment and baseline, then Step 1 (`lib/protocol.ts`).

---

## 8. Resume / handoff

**For the next session (human or Claude), in order:**

1. **Read this file first.** It is the plan of record for the platform track.
2. **Verify status against the actual code — do not trust the checkboxes.** Confirm what really
   exists: `ls frontend/lib frontend/components`, `git log --oneline -15`, `git status`, and
   check `frontend/package.json` for `firebase` / `firebase-admin` / `mongodb`. Fix any
   checkbox that disagrees with reality before doing anything else.
3. **Continue from the first incomplete step in §5.** Do not skip ahead and do not restart a
   step that is already `[x]` and verified.
4. **Respect §3 and §4.** The constraints are requirements with test IDs behind them, and the
   viewer files are another owner's.
5. **Update this file after meaningful progress** — tick the step, and add a dated entry at the
   top of §7 with what landed, whether the step's completion criterion is met, who is blocked,
   and any decision that contradicted a document. Same day; a log reconstructed later is
   fiction.
6. **Do not modify application source outside my ownership** (§1) without the owner's agreement
   at standup.
