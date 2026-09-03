# Progress log

One file per contributor. **Newest entry at the top.** Append an entry whenever
you finish a day's work or land something the rest of the team should know about
— it takes two minutes and it is what makes the 10:00 standup and the 21:00
integration checkpoint short.

| File | Owner | Track |
|---|---|---|
| [`sameer.md`](./sameer.md) | Sameer | Perception, benchmarking, synthetic scenes, integration lead |
| [`anuj.md`](./anuj.md) | Anuj | Grid engine, wire protocol, server, planner |
| [`shubham.md`](./shubham.md) | Shubham | Three.js viewer |
| [`navya.md`](./navya.md) | Navya | Next.js platform, auth, persistence, HUD |
| [`khanak.md`](./khanak.md) | Khanak | Drone LiDAR payload — models and analysis |
| [`veda.md`](./veda.md) | Veda | Drone LiDAR payload co-design, documentation, evidence, submission |

## Entry format

Copy this. Keep it short; the acceptance criterion is the part that matters.

```markdown
## Day N · <weekday> DD Mon 2026

**Landed.** What now exists and runs. Name files.

**Acceptance.** The day's exit criterion from `WORK_DISTRIBUTION.md`, and
whether it is met. "Made progress on X" is not an exit criterion.

**Blocked / blocking.** Who you are waiting on, who is waiting on you.

**Decisions and surprises.** Anything that changed the plan, contradicted a
document, or that someone else would otherwise rediscover the hard way. This
section is the reason the log exists.
```

## Rules

- **Write it the same day.** A log reconstructed on Day 12 is a work of fiction.
- **Record contradictions.** If the code had to diverge from `PRD.md` or
  `IMPLEMENTATION_PLAN.md`, say so here and raise it at the checkpoint. A silent
  divergence is a merge conflict with a two-week fuse.
- **Numbers, not adjectives.** "17 ms per scan on M-series CPU" beats "fast".
- **Link the commit** where it is not obvious.
