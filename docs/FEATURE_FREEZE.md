# Feature freeze — AVR-25D

**Declared:** Mon 7 Sep 2026, Day 11 standup
**Declared by:** Sameer (integration lead)
**Frozen commit:** `1ccc876f6049280de0d32257fa1846c5813aa54a` (`1ccc876`)
**Branch:** `main`

> Every number in the deck, the recorded `demo.log`, and the live demo all
> trace to this commit. If the tree moves, they stop agreeing, and the only
> person who finds out is a judge.

---

## Why now

The freeze exists to make three things true at the same time, which is
otherwise impossible on a moving tree:

1. `results.json` describes the code that will run in the demo.
2. `demo.log` was recorded from the code that will run in the demo.
3. The slides quote `results.json`.

Until today none of those held. `docs/RESULTS.md` carried
`git_commit: b75aa46` while 50 commits had landed on top of it — including
`9cbdf6a`, which rewrote the FR-14 ground reference that feeds the
`NEGATIVE_OBSTACLE` and `OVERHANG` flags. The published hazard table was
measured against code nobody is running any more.

## Evidence at the moment of freeze

| Check | Result |
|---|---|
| `make test` | **382 passed**, exit 0 |
| `git status` | clean, no untracked or modified files |
| `make scenes` re-run | 99 scene files + registry **byte-identical** |
| Platform | macOS 26.6.2, arm64, Python 3.14.0 |

The scene re-generation check is the one worth keeping: S1–S7 regenerate from
the frozen generator to the same bytes already on disk, so the hazard numbers
below are reproducible in a fresh clone rather than being an artefact of one
laptop's history.

---

## What "frozen" means

**Frozen — needs an exception (below):**

- `model/avr25d/**` — perception, core grid, decision, bench, synth, server
- `frontend/**` application code and the wire protocol
- `model/avr25d/config.yaml` — any threshold that moves changes a published number
- Anything that would change a figure in `results.json`

**Not frozen — carry on, no exception needed:**

| Work | Owner | Why it is not a code change |
|---|---|---|
| Firebase project + Atlas M0 provisioning | Navya | Environment only, no tree change |
| Vercel deployment of the frozen commit | Navya | Deploys this commit, does not alter it |
| Seeding the `scenes` collection | Navya | Data load from the frozen registry |
| Deck, script, Q&A bank | Veda | Not in the tree |
| `demo.log` recording | Anuj | Output of the frozen build |
| `docs/**` — progress logs, this file, hand-offs | anyone | Prose about the freeze, not the freeze |
| The 3-minute video | Navya + Veda | Not in the tree |

## Exception process

A change lands after the freeze only if all four are true:

1. It fixes a defect that **breaks the demo or misstates a published number**.
   Polish, refactors, and "while I was in there" do not qualify.
2. Sameer approves it in the standup channel, in writing, before the commit.
3. `make test` is green after it.
4. If it can touch a benchmark figure, `make bench-authoritative` is re-run and
   the deck numbers are re-issued to Veda. **Any code exception invalidates
   `demo.log`** and Anuj re-records — see H8.

L1 (sub-cell re-accumulation) and L2 (`requirements.txt` cleanup) are
explicitly **out of scope** for the exception process. Both are documented
known states, neither breaks anything, and L2 in particular would change the
interpreter environment three days before a demo.

## Known states we ship with, deliberately

These are documented rather than fixed, and each has an honest answer ready:

- **`requirements.txt` carries `nupy`** — a typosquat of `numpy` — alongside
  ~180 irrelevant packages. Nothing installs from it in this environment; the
  venv is built and working. Flagged as L2, not touched during freeze.
- **`npm audit`: 6 moderate advisories**, all transitive through
  `firebase-admin`. No fix available upstream that does not bump a major.
- **Sub-cell point re-accumulation** — sub-cells inherit parent statistics.
  Conservative and correct, not a defect; the true quadrant geometry is an
  upgrade.
- **`implementation_plan.md` folder references are stale** (`webapp/` for
  `frontend/`, `hardware/matlab/` for `hardware/scilab/`).

---

## Sign-off

| Person | Confirms |
|---|---|
| Sameer | Freeze declared; authoritative bench run; numbers issued to Veda |
| Anuj | `demo.log` recorded **from `1ccc876`** and `--replay` verified |
| Navya | Vercel deploy is of `1ccc876`; no local-only code in the build |
| Veda | Every deck figure traces to the issued `results.json` |
| Khanak | Eye-safety and BOM numbers final before the deck freezes |
| Shubham | Viewer verified at demo resolution on `1ccc876` |
