# Demo runbook and rehearsal plan

**Owner:** Sameer · **For:** Day 13 rehearsals and the live demo
**Frozen commit:** `1ccc876` — see [`FEATURE_FREEZE.md`](./FEATURE_FREEZE.md)

Three paths, in the order we fall back through them. Every command below was
run on this tree today; the "you should see" lines are copied from real output,
not from memory.

---

## Before anything: the demo machine is not the internet

**The live demo runs from `http://localhost:3000`.** Not from Vercel.

`NEXT_PUBLIC_WS_URL` is a `ws://` URL, and a browser will not open an insecure
WebSocket from an `https://` origin — `lib/ws.ts` refuses it deliberately with
an explanation rather than retrying forever (NFR-9). The Vercel deployment is
the **submission link**, and it shows auth, run history and the scenes
collection. It cannot show the live frame stream. Say that out loud once,
early, and it becomes a design decision instead of a bug a judge finds.

---

## Path A — the demo (cached perception)

Two terminals. Terminal 1, from `model/`:

```
cd model
../backend/.venv/bin/python -m avr25d.server.app --infer cached --seq 04
```

**You should see, within a second:**

```
Mode: CACHED  seq=04  data=data/kitti
Label cache: data/cache/network — 971 frames, built by the network segmenter
Pipeline worker started
Application startup complete.
```

> **The second line is the one that matters.** If it is missing, the cache was
> not found and the server has silently fallen back to the geometric
> segmenter — that exact defect shipped for days before Day 11 caught it. No
> cache line means you are already on Path B whether you meant to be or not.

Terminal 2, from `frontend/`:

```
cd frontend
npm run dev
```

Then open **http://localhost:3000**.

## Path B — geometric fallback

If the cache is missing, corrupt, or the label mmap misbehaves:

```
cd model
../backend/.venv/bin/python -m avr25d.server.app --infer geometric --seq 04
```

Slower per frame (~8.5 ms perception against ~0.14 ms cached) and the HUD will
say `geometric` — **which is honest, and is the point**. The mode on the wire
is always the mode that actually ran. If asked: this is FR-5, the fallback
that exists so the vehicle degrades instead of stopping.

## Path C — replay (the safety net)

If the dataset, the venv, or the machine itself is having a bad day:

```
cd model
../backend/.venv/bin/python -m avr25d.server.app --replay data/logs/demo.log
```

Frames re-emit at their original rate and the log loops, so it will run as long
as you need it to. The frontend cannot tell the difference — it is the same
`FrameMessage` wire format.

> **Status: `model/data/logs/demo.log` does not exist yet.** C4 is Anuj's, on
> the demo machine, and H8 says it must be **re-recorded against `1ccc876`**
> now that the freeze is declared. Recorded with:
>
> ```
> cd model
> ../backend/.venv/bin/python -m avr25d.server.app \
>     --infer cached --seq 04 --record data/logs/demo.log
> ```
>
> Let it run through a full pass, stop it, then **verify the replay actually
> plays back** before calling it done. An unverified log is not a safety net.

## Path D — fixtures (last resort)

Needs no data at all. Synthetic, schema-valid frames:

```
cd model
../backend/.venv/bin/python -m avr25d.server.app --fixtures
```

This proves the wire format and the viewer, nothing about perception. Use it
only if A, B and C are all gone, and say what it is.

---

## The viewer: what to press, and when

Owner: Shubham. Every key below is bound in `components/viewer/Viewer.tsx`.
Item 29 of [`HOW_TO_PROCEED_SHUBHAM.md`](./HOW_TO_PROCEED_SHUBHAM.md) is the
end-to-end verification that each one still works on the demo machine — run it
before every rehearsal, not once.

The same keys are also buttons in the HUD's view controls, so nothing here
depends on keyboard focus landing in the right place. **Use the buttons when
presenting.** A keystroke that silently goes to the URL bar looks like a crash.

| Key | Does | Say while pressing it |
|---|---|---|
| `3` | Adaptive grid — **the default** | "This is our representation. Cells grow with range." |
| `G` | Grid boundaries on/off | "Those are the actual cell walls — fine near the vehicle, coarse at 100 m." |
| `W` | **The A/B wipe** | "Same scan, same camera. Uniform 5 cm on the left, ours on the right." |
| *drag* | Move the divider | "16,000,000 cells against 705,771. That is the 22.67×." |
| `4` | Decision layer | "The truck is tracked, its path predicted, and the route re-planned around it." |
| `E` | Elevation shading | Only if asked how height is handled. |
| `1` | Raw cloud | Only if asked what the input looks like. |
| `2` | Uniform grid alone | Rarely — the wipe already makes this point better. |

### The sixty seconds that matter

The wipe is the single most persuasive object in the submission. Give it the
full minute the timing sheet allows and do not rush to View 4.

1. Start on `3` with `G` **on**. Let them see the grid coarsen with range.
2. Press `W`. Do not touch the mouse for two seconds — let the split land.
3. Drag the divider **slowly**, once left, once right. The counts are already
   on screen; read them out rather than pointing.
4. Press `4` last. The reroute is the payoff, and it only reads as a decision
   if they have already accepted the map underneath it.

### Camera

The near field is 5 cm on **both** sides of the wipe by construction, so a
top-down view shows two identical halves and proves nothing. **Get low and look
along the road.** The difference only exists at range, and a grazing angle puts
the far field across most of the screen.

### If the viewer misbehaves

| Symptom | Cause | Do this |
|---|---|---|
| Canvas black, HUD fine | Stream connected, frames not decoding | Check `StreamStatus`; fall back to Path C |
| "Connecting…" forever | Backend not up, or https origin blocking `ws://` (NFR-9) | Demo from `http://localhost:3000`, never the deployed link |
| Wipe seam not under the divider | Stale build | Hard reload — Fast Refresh does not re-run the viewer's mount effect |
| Frame rate visibly poor | Another GPU-heavy tab | Close it. 60 FPS at 109k instances is the measured baseline |

---

## The three timed rehearsals

Same script every time, stopwatch running, no restarts mid-run. The point is
not to prove it works — it is to find the thing that only breaks on the fourth
run.

| # | Path | What we are testing | Pass condition |
|---|---|---|---|
| 1 | A — cached | The demo as intended | Under time, no console errors, cache line present |
| 2 | B — geometric | Fallback mid-sentence | Switch takes < 30 s, nobody narrates a stack trace |
| 3 | C — replay | Total-failure recovery | Replay running < 30 s from decision to pixels |

**Rehearsal 2 and 3 start by breaking it on purpose.** Rename the cache
directory before rehearsal 2; kill the venv's data path before rehearsal 3.
A fallback nobody has ever actually taken is a plan, not a fallback.

### Timing sheet — fill one per run

| Segment | Target | R1 | R2 | R3 |
|---|---:|---:|---:|---:|
| Problem + approach | 0:40 | | | |
| Live: adaptive grid, A/B wipe | 1:00 | | | |
| Live: hazard — pothole / overhang | 0:50 | | | |
| Results: the 22.67× and mIoU slide | 0:40 | | | |
| Hardware track | 0:30 | | | |
| Close | 0:20 | | | |
| **Total** | **4:00** | | | |

Record for each run: total time, where we overran, anything a judge would have
interrupted at, and whether the fallback was needed.

### Roles during the live run

| Person | Holds |
|---|---|
| Sameer | The two terminals. Calls the fallback — nobody else does |
| Veda | The narration. Does not stop for a technical wobble |
| Navya | The browser, the deployed link, the video if we have to cut to it |
| Anuj | Backend telemetry; knows A/B/C cold and can type them without looking |
| Khanak | Hardware questions, eye-safety margin |
| Shubham | Viewer rendering, resolution |

**One rule: only Sameer calls the fallback.** Two people fixing it at once is
how a ten-second wobble becomes a ninety-second silence.

---

## Numbers you will be asked for

Full sheet: [`DECK_NUMBERS.md`](./DECK_NUMBERS.md). The five to have cold:

- **22.67×** fewer cells than a dense uniform 2.5D grid
- **0.878** mIoU, **0.934** point accuracy, over 971 SemanticKITTI scans
- **9.2 ms** median end-to-end, 13.7 ms p95
- **0.930** dynamic-object recall
- **0** hazard false positives across the control scenes

And the two honest caveats, offered before they are asked:

- **B4, a sparse 3D voxel hash, is smaller than our dense ring table** on this
  scan (1.006 MB vs 17.64 MB). Our argument is cell count and deterministic
  access, not bytes.
- **The 60–100 m bin is unscored, not zero** — the dataset stops annotating
  there.
