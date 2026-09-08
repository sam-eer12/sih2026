## What this is

Two viewer commits, two performance fixes to frozen code, and the docs that go with them.

**This needs a freeze exception (`docs/FEATURE_FREEZE.md`). Sameer's call.**
Everything below is laid out against the four exception criteria so it can be
approved or refused in one read.

---

## The performance fixes

Running the pipeline on real SemanticKITTI for the first time — sequence 04,
fetched tonight — showed the server delivering **1.4–2.1 fps**, not the 30 the
demo assumes. Two causes, both invisible on fixture data.

### 1. `decision/tracker.py` — a sort that never needed to happen

`cluster_centroids` did `np.array(sorted(cKDTree(xy).query_pairs(link_m)))`.

A car at close range occupies thousands of 5 cm cells, so on a real scan:

```
dynamic cells : 5,567
pairs found   : 281,829
query_pairs   :  33.7 ms
sorted()+array: 146.3 ms   <-- sorting a Python set of 281,829 tuples
```

The sort cost 4x the spatial query it was sorting, and was never needed —
`connected_components` does not care about edge order. Now
`query_pairs(link_m, output_type="ndarray")`.

Fixture scenes could not have shown this: their dynamic cells are sparse, and
`t_decision_ms` read **0.8 ms** against the real scan's **223.6 ms**.

### 2. `core/cell.py` — a constant recomputed 30 times a second

`analyse()` rebuilt each cell's four cardinal neighbour ids every frame, over
all 705,771 cells. Those ids are a pure function of the ring geometry and are
identical on every frame — **21.3 ms per frame**, 12% of the budget, spent
rederiving a constant. Now memoised on first use. The derivation is unchanged,
only hoisted out of the per-frame path.

### Result

```
                  start    +tracker   +nb cache
decision         591.4 ms   43-65 ms      —
analysis          53.9 ms   77.0 ms    44.4 ms
TOTAL            693.7 ms  172.7 ms   149.1 ms
pipeline fps         1.4        5.8        6.7
```

Target is 10 Hz — the Velodyne's rate. A pipeline faster than the sensor is
idle, so 100 ms is the finish line, not 33 ms. **We are at 149 ms, not there.**
The remaining budget is the pure-Python A* (37.7 ms) and full-grid work in
`accumulate`/`analyse` where only ~6% of cells are occupied. Both are real
changes to core code and are **written up rather than attempted** — see
`docs/progress/shubham.md`.

---

## Against the exception criteria

**1. Fixes a defect that breaks the demo or misstates a published number.**

Both, I think, but it is your call:

- 1.4 fps is not a demo. The live view stepped roughly once per second.
- `DECK_NUMBERS.md` quotes **9.2 ms median end-to-end** and says it is
  "comfortably inside a 10 Hz budget". That figure is `Read + Segment + Score`
  with cached labels — the map build. **It does not include the decision
  layer, which no published benchmark covers.** Before these fixes the live
  server was 1.4 Hz. A judge who watches the demo and then reads the deck can
  find that gap.

Neither change is polish or a refactor-while-I-was-in-there. Each removes work
that was provably unnecessary: a sort whose order is never read, and a constant
recomputed per frame.

**2. Sameer approves in writing before the commit.** — NOT MET. The commits
exist on this branch only; nothing is merged. This PR is the request.

**3. `make test` green.** — **382/382 pass** after each change, run separately.

**4. Benchmark figures and `demo.log`.** — **This is the part that costs
something, and it is why I did not merge.**

- `core/cell.py::analyse` feeds `OVERHANG` and `NEGATIVE_OBSTACLE`. That is
  the hazard table.
- `decision/tracker.py` clustering feeds dynamic-object recall (0.930).

Tests passing proves behaviour is unchanged on sequence 04. It does **not**
prove the published figures still describe the code. Per the freeze document,
accepting this means `make bench-authoritative` is re-run, deck numbers are
re-issued to Veda, and **`demo.log` is invalidated and Anuj re-records**.

If that cost is not worth 1.4 -> 6.7 fps the night before filming, refusing
this is a reasonable answer and the demo still runs.

**Verification I did before touching anything:** identical clustering
partitions across 8 real frames for the tracker change; memoised neighbour ids
compared against the inline derivation.

---

## The viewer commits

`68ea90c` and `c8b4bd4` — `frontend/**`, also frozen, but lower risk: no
published number depends on them.

- **Real stream connected.** Navya's `lib/ws.ts` and `lib/protocol.ts` landed
  and the `onReady` handoff worked with zero rewiring. Confirmed by cell count:
  backend 41,996/frame vs the dev generator's 43,946.
- **One source of truth for wire types.** `components/viewer/types.ts` had
  grown a parallel copy of Navya's interfaces and the two had already drifted —
  mine widened `selected`/`risk` to `| string` and made `tracks`/`stats`
  optional, permitting frames the real stream never sends. It now re-exports
  hers. That immediately caught `devFrames.ts` emitting
  `stats: { n_cells, fps }`, which is not a `FrameStats` at all.
- **Class legend** (`components/hud/ClassLegend.tsx`). Nothing on screen said
  what the colours meant. **Navya: this is in your directory** — it reads only
  `lib/palette.ts`, and it is there rather than in `components/viewer/` because
  it is chrome, not canvas. Move or restyle freely.
- **`DEMO_RUNBOOK.md` gained a viewer section.** It had roles, timings and four
  fallback paths but never said which keys to press.

Shubham's checklist is **30/30**, verified on the real stream: all four views,
0 errors and 0 warnings, 60 FPS render, T-V6 60 FPS at 109,404 instances,
T-W7 326 frames to 3 React renders.

---

## Reproduce

```bash
python tools/fetch_kitti.py --sequences 04
cd model
../backend/.venv/bin/python ../tools/build_cache.py --mode geometric --sequences 04
../backend/.venv/bin/python -m avr25d.server.app --infer cached --seq 04 \
    --cache data/cache/geometric
```

## One negative result, recorded so nobody repeats it

`np.add.at` is **not** the bottleneck it is assumed to be. Measured against
`np.bincount` on a real frame: 0.1 ms vs 0.4 ms for the 1D accumulators.
Modern numpy has optimised `ufunc.at`. Only the 2D class histogram would gain
(4.2 -> 1.8 ms), which is not worth touching core for.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
