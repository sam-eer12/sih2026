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
| `lib/ws.ts` | Missing — **Shubham is still blocked on this one** |
| `components/hud/*`, `components/decision/*` | Missing |
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
- ⚠️ **The server wedges when a client disconnects** — `server/app.py:487` blocks the event
  loop. Symptom: `/health` times out and the process ignores SIGTERM; recover with
  `pkill -9 -f avr25d.server.app` and restart. Anuj's fix, raised Day 8 (§7). Until it lands,
  expect to restart the backend after each disconnect while developing `lib/ws.ts`.
- **Measured frame shape** (fixtures, Day 8): 1,134,852 bytes · `cells.n = 41,990` ·
  `refined.n = 0` · 15 `stats` fields · `n_points_conserved == n_points == 121,344` ·
  `n_cells_total = 705,771`. Matches the ~42,000 cells / ~1.1 MB in Shubham's guide.
- **`mode` reads `"geometric"` in fixtures mode**, not `"fixtures"`. The FR-6 perception-mode
  badge must not imply live inference when the server is on `--fixtures`; decide how to
  present that honestly in Step 3.
- **`tracks` can be empty and `decision.selected` can be `"primary"`.** The fixture truck
  crosses periodically, so a frame sampled at random may have no tracks and no reroute. The
  decision panel must render an empty track list without breaking (Step 4).

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

### Step 2 — `lib/ws.ts` and stream cut-over `[ ]`

**Objective.** Real frames on screen; **Shubham unblocked**.
**Files.** `frontend/lib/ws.ts`, `frontend/app/dashboard/page.tsx`.
**Tasks.** `connectFrames(url, onFrame): () => void` — `binaryType = 'arraybuffer'`,
exponential-backoff reconnect, skip empty messages, drop rather than queue, never awaited.
Switch the dashboard to `<Viewer onReady={h => connectFrames(url, h.pushFrame)} />`. Retire the
`devStream` path once verified (with Shubham).
**Verification.** T-W6 — no Next.js handler in the network trace for `/stream`, and killing
`next dev` mid-stream does not interrupt rendering. Reconnect works after restarting the server.
**Done when.** Views 1 and 3 render **real streamed frames** — this closes Shubham's Day 3.

### Step 3 — HUD `[ ]`

**Objective.** FR-28 on screen, every value from `stats`.
**Files.** `frontend/components/hud/{Hud,LatencyBars,MemoryPanel,ModeBadge}.tsx`.
**Tasks.** FPS, per-stage latency (perception / projection / analysis / refine / decision /
serialise), total latency, occupied cells, AVR-25D memory, baseline memory, reduction factor,
perception-mode badge (FR-6), frame index. Throttled leaf subscription; memoize `<Viewer>`.
Large, high-contrast type — it is judged on a projector.
**Verification.** T-V4 — no `NaN`, no `undefined`, across a full fixture run. T-W7 — render
counter stays under 10 across 300 frames (expect 2 in dev; StrictMode double-renders on mount).
**Done when.** Every FR-28 field is populated from real frames and T-W7 still passes.

### Step 4 — View controls and decision panel `[ ]`

**Objective.** Drive the demo from the UI; make the reroute legible.
**Files.** `frontend/components/hud/` (controls), `frontend/components/decision/{DecisionPanel,TrackList}.tsx`.
**Tasks.** Buttons/keys for views 1–4, elevation toggle, ring overlay, wipe — calling
`SceneHandle`, gracefully disabled for views Shubham has not built. Decision panel: selected
route, risk, ETA, reason string. Track list: id, class, speed.
**Verification.** Run-book beats 58–82 s work: track appears, reroute fires, reason string
readable from three metres.
**Done when.** The demo can be driven without touching the keyboard bindings inside `Viewer.tsx`.

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
