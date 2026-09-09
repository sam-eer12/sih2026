// ConsoleChrome.tsx — the perception console's instrument layer.
//
// Composition: the 3D scene is full-bleed behind everything. Two narrow rails
// float over its edges — perception and system on the left, decision and
// objects on the right — with the middle left clear so the cloud is never
// covered. Nothing here is laid out in a grid of equal cards.
//
// Every figure comes from a real frame: `stats` off the wire, the viewer's own
// perf/uniform getters, or the planner's decision and tracks. Nothing is
// synthesised; the sparkline histories are real samples buffered client-side.
//
// Sampling, not streaming: each rail polls its sampler at SAMPLE_HZ. At 30 Hz
// these subtrees would reconcile thirty times a second for numbers nobody can
// read that fast, and frames would be entering React state (FR-42).
'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import type { HudSampler, HudSnapshot } from '../hud/types';
import type { DecisionSampler, DecisionSnapshot } from '../decision/DecisionPanel';
import { CLASS_ID_TO_COLOUR, CLASS_NAMES } from '../../lib/palette';
import { count, megabytes, num, ratio } from '../hud/format';
import type { StreamStatus } from '../../lib/ws';
import {
  Arc, LIDAR, ADAPTIVE, OK, WARN, RISK,
  PlanView, Sparkline, StageBar, useSeries, type PlanTrack,
} from './instruments';

const SAMPLE_HZ = 4;
/** 30 fps. PRD NFR-1. */
const BUDGET_MS = 33.3;

function useSampled<T>(sample: () => T | null): T | null {
  const [snap, setSnap] = useState<T | null>(null);
  useEffect(() => {
    const id = window.setInterval(() => setSnap(sample()), 1000 / SAMPLE_HZ);
    return () => window.clearInterval(id);
  }, [sample]);
  return snap;
}

/** Beyond this the right rail would run past the viewport on a laptop. */
const MAX_TRACK_ROWS = 6;

// Two label ranks, and only two. SECTION names a module and is the one place
// uppercase is used; LABEL names a value inline and is sentence case, because
// a row of 9px caps beside every number reads as texture rather than
// hierarchy. Sizes come from the scale in globals.css.
const SECTION = 't-section text-white/55';
const LABEL = 't-label text-white/50';

/** A rail module. Translucent and hairlined — a frame, not a card. */
function Module({
  title,
  aside,
  children,
  delay = 0,
}: {
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  delay?: number;
}) {
  return (
    <section
      className="hud-in border-t border-white/10 pt-2.5"
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="mb-2.5 flex items-baseline justify-between gap-3">
        <h2 className={SECTION}>{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

const VALUE = 't-value text-white/90';

/**
 * `nowrap` on both halves is load-bearing. At the old 10.5px a long label
 * still fitted the 154px column beside the arc gauge; at 12.5px it does not,
 * and the failure mode without this is a label silently wrapping to two lines
 * and shoving the row below it out of alignment.
 */
function Row({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: string;
  tone?: string;
  hint?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2.5" title={hint}>
      <span className={`${LABEL} whitespace-nowrap`}>{label}</span>
      <span className={`${VALUE} whitespace-nowrap`} style={tone ? { color: tone } : undefined}>
        {value}
      </span>
    </div>
  );
}

/* ── Atmosphere ──────────────────────────────────────────────────────────
   Depth around the scene. CSS and a decorative particle field only — none of
   it derives from frame data, so it can never read as a sensor return. */

export function StageAtmosphere() {
  return (
    <div className="pointer-events-none absolute inset-0 z-10 overflow-hidden">
      <div className="stage-horizon absolute inset-0" />
      <div className="absolute left-1/2 top-1/2 h-[160vmax] w-[160vmax] -translate-x-1/2 -translate-y-1/2">
        <div className="stage-sweep absolute inset-0 rounded-full" />
      </div>
      <div className="stage-vignette absolute inset-0" />
      <div className="stage-reticle absolute inset-x-4 inset-y-14" />
    </div>
  );
}

/* ── Top rail ────────────────────────────────────────────────────────── */

const STATE_LABEL: Record<StreamStatus, string> = {
  connecting: 'Acquiring',
  open: 'Live',
  stalled: 'Stalled',
  reconnecting: 'Reconnecting',
  closed: 'Offline',
};

function statusColour(s: StreamStatus): string {
  if (s === 'open') return OK;
  if (s === 'closed') return RISK;
  return WARN;
}

export function TopRail({
  status,
  sample,
  session,
}: {
  status: StreamStatus;
  sample: HudSampler;
  session?: React.ReactNode;
}) {
  const snap = useSampled<HudSnapshot>(sample);
  const colour = statusColour(status);
  const conserved =
    snap && typeof snap.stats.n_points === 'number' && snap.stats.n_points > 0
      ? (snap.stats.n_points_conserved / snap.stats.n_points) * 100
      : undefined;

  return (
    <header className="pointer-events-none absolute inset-x-0 top-0 z-30 flex h-12 items-center gap-4 px-4">
      <Link
        href="/"
        className="pointer-events-auto flex items-baseline gap-2 transition-opacity hover:opacity-75"
      >
        {/* nowrap: the hyphen in "AVR-25D" is a legal break opportunity, and
            this link is a flex item that the rail will happily squeeze. */}
        <span className="t-heading whitespace-nowrap text-white">AVR-25D</span>
        <span className="t-label whitespace-nowrap text-white/45">Perception</span>
      </Link>

      <span className="h-3.5 w-px bg-white/12" />

      <div className="flex items-center gap-2">
        <span className="relative flex h-1.5 w-1.5">
          {status === 'open' ? (
            <span
              className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
              style={{ background: colour }}
            />
          ) : null}
          <span
            className="relative inline-flex h-1.5 w-1.5 rounded-full"
            style={{ background: colour, boxShadow: `0 0 9px ${colour}` }}
          />
        </span>
        {/* A state, not a measurement — so it is set in sans like every other
            word on the page. */}
        <span className="t-label font-semibold" style={{ color: colour }}>
          {STATE_LABEL[status]}
        </span>
      </div>

      {/* Frame identity, live scale, and the conservation invariant.
          The perception mode used to sit here and read as a control rather
          than a readout; it moved to the Pipeline latency module, beside the
          perception stage whose cost it explains. FR-6 requires it on the HUD
          at all times, so it is displayed, not dropped. */}
      <div className="ml-4 hidden items-center gap-6 lg:flex">
        <Stat label="Frame" value={snap ? count(snap.frameId) : '—'} />
        <Stat
          label="Cells"
          value={snap ? count(snap.stats.n_cells_occupied) : '—'}
          tone={ADAPTIVE}
          hint="stats.n_cells_occupied — cells this scan actually filled"
        />
        <Stat
          label="Conserved"
          value={conserved !== undefined ? `${num(conserved, 1)}%` : '—'}
          tone={conserved === 100 ? OK : WARN}
          hint="FR-10 — every projected point lands in a cell"
        />
      </div>

      <div className="ml-auto flex items-center gap-4">
        <Link
          href="/runs"
          className="pointer-events-auto t-label font-medium text-white/50 transition-colors hover:text-white"
        >
          Runs
        </Link>
        <div className="pointer-events-auto">{session}</div>
      </div>
    </header>
  );
}

function Stat({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: string;
  tone?: string;
  hint?: string;
}) {
  return (
    <div className="flex items-baseline gap-2 whitespace-nowrap" title={hint}>
      <span className={LABEL}>{label}</span>
      <span className="t-value" style={{ color: tone ?? 'rgba(255,255,255,0.92)' }}>
        {value}
      </span>
    </div>
  );
}

/* ── Left rail — perception and system ───────────────────────────────── */

const STAGES: { key: keyof HudSnapshot['stats']; label: string; colour: string }[] = [
  { key: 't_perception_ms', label: 'Perception', colour: LIDAR },
  { key: 't_projection_ms', label: 'Projection', colour: '#38bdf8' },
  { key: 't_analysis_ms', label: 'Analysis', colour: '#818cf8' },
  { key: 't_refine_ms', label: 'Refine', colour: ADAPTIVE },
  { key: 't_decision_ms', label: 'Decision', colour: '#c084fc' },
  { key: 't_serialise_ms', label: 'Serialise', colour: '#64748b' },
];

/** Module scope: a stable identity, so useSeries keeps one interval. */
const selectPipelineFps = (s: HudSnapshot) =>
  typeof s.stats.fps === 'number' ? s.stats.fps : undefined;
const selectRenderFps = (s: HudSnapshot) => s.perf.fps;

export function PerceptionRail({ sample }: { sample: HudSampler }) {
  const snap = useSampled<HudSnapshot>(sample);
  const stats = snap?.stats;

  const pipelineFps = useSeries(sample, selectPipelineFps);
  const renderFps = useSeries(sample, selectRenderFps);

  const stages = STAGES.map((s) => ({
    label: s.label,
    colour: s.colour,
    ms: typeof stats?.[s.key] === 'number' ? (stats[s.key] as number) : 0,
  }));

  const occupancy =
    stats && snap ? (stats.n_cells_occupied as number) / Math.max(snap.capacity, 1) : 0;

  return (
    <aside className="pointer-events-none absolute bottom-20 left-4 top-16 z-20 flex w-[228px] flex-col gap-4 overflow-hidden">
      <Module title="Throughput" aside={<span className={LABEL}>fps</span>}>
        {/* Three ranks in one row: the headline rate, the secondary rate, and
            what each one is. Previously all three sat within 13px of each
            other, so nothing led. */}
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="t-metric text-white">{snap ? num(stats?.fps, 1) : '—'}</p>
            <p className={`mt-1.5 ${LABEL}`}>Pipeline</p>
          </div>
          <div className="text-right">
            <p className="t-value-lg" style={{ color: LIDAR }}>
              {snap ? num(snap.perf.fps, 0) : '—'}
            </p>
            <p className={`mt-1.5 ${LABEL}`}>Render</p>
          </div>
        </div>
        <div className="mt-2">
          <Sparkline values={pipelineFps} colour="rgba(255,255,255,0.55)" height={26} max={40} />
          <div className="-mt-2">
            <Sparkline values={renderFps} colour={LIDAR} height={26} max={70} />
          </div>
        </div>
      </Module>

      <Module
        title="Pipeline latency"
        delay={70}
        aside={
          <span
            className="t-value-sm"
            style={{
              color:
                typeof stats?.t_total_ms === 'number' && stats.t_total_ms > BUDGET_MS ? WARN : OK,
            }}
          >
            {snap ? `${num(stats?.t_total_ms, 1)} ms` : '—'}
          </span>
        }
      >
        {/* FR-6: FrameMessage.mode verbatim, never inferred. It belongs with
            the perception stage — it is what t_perception_ms was spent on. */}
        <div className="mb-2.5">
          <Row
            label="Perception mode"
            value={snap ? snap.mode : '—'}
            tone={ADAPTIVE}
            hint="FrameMessage.mode — live, cached or geometric (FR-6)"
          />
        </div>
        <StageBar stages={stages} budgetMs={BUDGET_MS} />
        {/* gap-x-2, not 3: the legend labels grew, and two columns of a 228px
            rail only fit if the gutter gives the extra pixels back. */}
        <div className="mt-2.5 grid grid-cols-2 gap-x-2 gap-y-1.5">
          {stages.map((s) => (
            <div key={s.label} className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 shrink-0 rounded-sm" style={{ background: s.colour }} />
              <span className="t-caption truncate text-white/50">{s.label}</span>
              <span className="t-value-sm ml-auto text-white/75">{s.ms.toFixed(1)}</span>
            </div>
          ))}
        </div>
      </Module>

      <Module title="Adaptive grid" delay={140}>
        <div className="flex items-center gap-3">
          <Arc fraction={occupancy} colour={ADAPTIVE}>
            <span className="t-value-sm text-white/90">
              {snap ? `${num(occupancy * 100, 1)}%` : '—'}
            </span>
          </Arc>
          <div className="min-w-0 flex-1 space-y-1">
            <Row label="Occupied" value={snap ? count(stats?.n_cells_occupied) : '—'} />
            <Row label="Capacity" value={snap ? count(snap.capacity) : '—'} />
            {/* "Uniform", not "Uniform 5 cm": the cell size is stated once, in
                the Resolution module directly below, and the longer label no
                longer fits this column beside an eight-digit count. */}
            <Row
              label="Uniform"
              value={snap ? count(snap.uniform.analyticTotal) : '—'}
              hint="A uniform 5 cm grid over the same footprint"
            />
          </div>
        </div>

        <div className="mt-3 space-y-1 border-t border-white/8 pt-2.5">
          <Row label="Reduction" value={snap ? ratio(stats?.reduction) : '—'} tone={ADAPTIVE} />
          <Row label="Map memory" value={snap ? megabytes(stats?.mem_bytes) : '—'} />
          <Row label="Baseline" value={snap ? megabytes(stats?.baseline_mem_bytes) : '—'} />
        </div>
      </Module>

      <Module title="Resolution" delay={210}>
        {/* The adaptive law itself: 5 cm inside the knee, growing with range. */}
        <div className="flex h-1.5 w-full overflow-hidden rounded-full">
          <span className="h-full w-[22%]" style={{ background: LIDAR }} />
          <span
            className="h-full flex-1"
            style={{ background: `linear-gradient(90deg, ${LIDAR}, ${ADAPTIVE})` }}
          />
        </div>
        <div className="mt-1.5 flex justify-between">
          <span className="t-value-sm text-white/55">5 cm · 0–10 m</span>
          <span className="t-value-sm text-white/55">50 cm · 100 m</span>
        </div>
      </Module>
    </aside>
  );
}

/* ── Right rail — decision and objects ───────────────────────────────── */

const RISK_TONE: Record<string, string> = { LOW: OK, MEDIUM: WARN, HIGH: RISK };

export function DecisionRail({ sample }: { sample: DecisionSampler }) {
  const snap = useSampled<DecisionSnapshot>(sample);
  const decision = snap?.decision;
  const tracks = snap?.tracks ?? [];

  const risk = decision?.risk ?? '';
  const tone = RISK_TONE[risk] ?? 'rgba(255,255,255,0.45)';
  const rerouted = decision?.selected === 'alternative';

  // A reroute is the moment worth noticing, so the rail acknowledges a change
  // once rather than animating continuously.
  const previous = useRef<string | undefined>(undefined);
  const [flash, setFlash] = useState(false);
  useEffect(() => {
    if (!decision) return;
    const key = `${decision.selected}|${decision.risk}`;
    if (previous.current !== undefined && previous.current !== key) {
      setFlash(true);
      const id = window.setTimeout(() => setFlash(false), 1000);
      return () => window.clearTimeout(id);
    }
    previous.current = key;
  }, [decision]);

  const plan: PlanTrack[] = tracks.map((t) => ({
    id: t.id,
    x: t.x,
    y: t.y,
    colour: `#${(CLASS_ID_TO_COLOUR[t.class_id] ?? 0x808080).toString(16).padStart(6, '0')}`,
  }));

  return (
    <aside className="pointer-events-none absolute bottom-20 right-4 top-16 z-20 flex w-[248px] flex-col gap-4 overflow-hidden">
      {/* The one element with a surface of its own — it is the only thing here
          whose meaning changes rather than its value. */}
      <section
        className="hud-in relative overflow-hidden rounded-md pl-3.5 pr-3 py-3 transition-all duration-500"
        style={{
          background: flash
            ? `linear-gradient(90deg, color-mix(in srgb, ${tone} 16%, transparent), rgba(255,255,255,0.02))`
            : 'rgba(255,255,255,0.03)',
          boxShadow: flash ? `0 0 26px -6px ${tone}` : 'none',
        }}
      >
        <span
          className="absolute inset-y-0 left-0 w-[2px] transition-all duration-500"
          style={{ background: tone, boxShadow: `0 0 ${flash ? 14 : 7}px ${tone}` }}
        />
        <p className={SECTION}>Decision</p>
        {decision ? (
          <>
            {/* The route taken is the largest thing in the rail; the risk word
                sits beside it as a chip, and the counts below it drop to
                measurement rank. */}
            <p className="mt-2 flex items-baseline gap-2.5">
              <span className="t-title text-white">
                {rerouted ? 'Alternative' : 'Primary'}
              </span>
              <span className="t-section" style={{ color: tone }}>
                {risk || 'unknown'}
              </span>
            </p>
            <p className="t-value-sm mt-2.5 text-white/50">
              ETA {num(decision.eta_s, 1)}s · route {num(decision.route?.length, 0)} · alt{' '}
              {num(decision.alternative?.length, 0)}
            </p>
            <p className="t-body mt-2.5 text-white/75">{decision.reason}</p>
          </>
        ) : (
          <p className="t-label mt-2 text-white/50">Waiting for the planner.</p>
        )}
      </section>

      <Module
        title="Plan view"
        delay={70}
        aside={<span className="t-value-sm text-white/45">45 m</span>}
      >
        <PlanView tracks={plan} route={decision?.route} alternative={decision?.alternative} />
      </Module>

      <Module
        title="Tracked objects"
        delay={140}
        aside={<span className="t-value text-white/75">{tracks.length}</span>}
      >
        {tracks.length === 0 ? (
          <p className="t-label text-white/40">No dynamic objects in view.</p>
        ) : (
          <div className="space-y-2">
            {/* Capped so a busy scene cannot push the rail off-screen. The
                rails stay pointer-transparent so the scene can be orbited
                through them, which rules out scrolling them instead. */}
            {tracks.slice(0, MAX_TRACK_ROWS).map((t) => {
              const colour = `#${(CLASS_ID_TO_COLOUR[t.class_id] ?? 0x808080)
                .toString(16)
                .padStart(6, '0')}`;
              return (
                <div key={t.id} className="hud-in">
                  <div className="flex items-center gap-2">
                    <span
                      className="h-1.5 w-1.5 shrink-0 rounded-full"
                      style={{ background: colour, boxShadow: `0 0 8px ${colour}` }}
                    />
                    {/* Class name is language, so sans; the id, speed and
                        coordinates below it are measurements, so mono. */}
                    <span className="t-label truncate font-medium text-white/90">
                      {CLASS_NAMES[t.class_id] ?? 'Unknown'}
                    </span>
                    <span className="t-value-sm text-white/40">#{t.id}</span>
                    <span className="t-value-sm ml-auto" style={{ color: LIDAR }}>
                      {num(t.speed, 1)} m/s
                    </span>
                  </div>
                  <p className="t-value-sm mt-1 pl-3.5 text-white/40">
                    x {num(t.x, 1)} · y {num(t.y, 1)} · age {count(t.age)}
                  </p>
                </div>
              );
            })}
            {tracks.length > MAX_TRACK_ROWS ? (
              <p className="t-label pt-1 text-white/40">
                +{tracks.length - MAX_TRACK_ROWS} more tracked
              </p>
            ) : null}
          </div>
        )}
      </Module>
    </aside>
  );
}

/* ── Empty state ─────────────────────────────────────────────────────── */

export function StageMessage({ status }: { status: StreamStatus }) {
  const copy: Record<StreamStatus, { title: string; body: string } | null> = {
    open: null,
    connecting: { title: 'Acquiring frames', body: 'Waiting for the first frame from the perception server.' },
    reconnecting: { title: 'Reconnecting', body: 'The stream dropped. The viewer resumes on the next frame.' },
    stalled: { title: 'Stream stalled', body: 'The connection is open but no frames are arriving.' },
    closed: { title: 'Not connected', body: 'The perception server is unreachable. Start it and the viewer picks up automatically.' },
  };
  const state = copy[status];
  if (!state) return null;

  return (
    <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center">
      <div className="hud-in max-w-sm px-8 text-center">
        <p className="t-title text-white">{state.title}</p>
        <p className="t-body mt-2.5 text-white/55">{state.body}</p>
        {status === 'closed' || status === 'stalled' ? (
          <code className="t-value-sm mt-4 inline-block rounded border border-white/12 bg-black/40 px-3 py-2 text-white/75">
            python -m avr25d.server.app --fixtures
          </code>
        ) : null}
      </div>
    </div>
  );
}
