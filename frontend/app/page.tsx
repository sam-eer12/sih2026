// app/page.tsx — the landing page.
//
// The hero is the argument: a mountain that becomes a point cloud under the
// cursor. It is the product's one-sentence pitch made literal — take a
// surface, keep only what a sensor returns, and colour what remains by what
// it is. Copy and figures are unchanged from the plain version; only the
// staging is new, and every number still traces to results.json.

import Link from 'next/link';
import LidarMountain from '../components/landing/LidarMountain';
import NeuralField from '../components/landing/NeuralField';

const CELLS_ADAPTIVE = (705_771).toLocaleString('en-GB');
const CELLS_UNIFORM = (16_000_000).toLocaleString('en-GB');

export default function Home() {
  return (
    <main className="relative min-h-screen overflow-hidden bg-[var(--ink-900)]">
      {/* Motif sits behind everything and is inert to the pointer. */}
      <NeuralField className="pointer-events-none absolute inset-0 z-0 h-full w-full opacity-60" />

      {/* ── Hero ─────────────────────────────────────────────── */}
      <section className="relative z-10">
        <div className="relative h-[76vh] min-h-[520px] w-full">
          <LidarMountain className="absolute inset-0 h-full w-full" />

          {/* The terrain fades into the page rather than ending at an edge. */}
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-56 bg-gradient-to-b from-transparent to-[var(--ink-900)]" />
          {/* Scrim under the headline column. The cloud is bright enough to
              swallow body copy once scanned; this keeps the text legible
              without dimming the terrain itself. */}
          <div className="pointer-events-none absolute inset-y-0 left-0 w-full max-w-3xl bg-gradient-to-r from-[var(--ink-900)] via-[var(--ink-900)]/80 to-transparent" />

          <div className="pointer-events-none absolute inset-0 flex flex-col justify-center px-8 md:px-16">
            <div className="max-w-2xl">
              <p className="rise tabular text-[11px] uppercase tracking-[0.34em] text-[var(--text-lo)]">
                SIH26053 · DRDO / IDEX
              </p>
              <h1
                className="rise mt-4 text-6xl font-semibold tracking-tight text-[var(--text-hi)] md:text-8xl"
                style={{ animationDelay: '80ms' }}
              >
                AVR-25D
              </h1>
              <p
                className="rise mt-5 max-w-xl text-base leading-relaxed text-[var(--text)] md:text-lg"
                style={{ animationDelay: '160ms' }}
              >
                Adaptive variable-resolution 2.5D LiDAR mapping for dynamic environment
                perception. Resolution is allocated the way the eye allocates it — 5&nbsp;cm
                inside 10&nbsp;m, coarsening to 50&nbsp;cm at 100&nbsp;m, matched to the
                sensor&rsquo;s own angular sampling.
              </p>
              <p
                className="rise mt-6 text-[12px] tracking-wide text-[var(--text-lo)]"
                style={{ animationDelay: '240ms' }}
              >
                Move across the terrain to scan it.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Figures ──────────────────────────────────────────── */}
      <section className="relative z-10 px-8 pb-24 md:px-16">
        <dl className="flex flex-wrap gap-x-16 gap-y-8 border-t border-[var(--line)] pt-10">
          <Figure value={CELLS_ADAPTIVE} label="cells, adaptive" />
          <Figure value={CELLS_UNIFORM} label="cells, uniform 5 cm" />
          <Figure value="22.67×" label="reduction" accent />
          <Figure value="0.878" label="mIoU, 971 scans" />
        </dl>

        <p className="mt-10 max-w-2xl text-base leading-relaxed text-[var(--text)]">
          Because each cell keeps ground height and obstacle height separately, the map
          represents the three hazards a 2D occupancy grid destroys: curbs, potholes and
          overhanging structures. A deterministic decision layer turns the map into a
          route, a risk level and a stated reason.
        </p>

        <div className="mt-9 flex flex-wrap gap-3">
          <Link
            href="/dashboard"
            className="rounded-md bg-[var(--accent)] px-5 py-2.5 text-sm font-semibold text-[#062713] transition-transform duration-200 hover:-translate-y-0.5"
          >
            Live dashboard
          </Link>
          <Link
            href="/runs"
            className="rounded-md border border-[var(--line)] px-5 py-2.5 text-sm font-semibold text-[var(--text-hi)] transition-colors duration-200 hover:border-[var(--accent)] hover:text-[var(--accent)]"
          >
            Run history
          </Link>
        </div>

        <p className="mt-10 max-w-2xl text-[13px] leading-relaxed text-[var(--text-lo)]">
          The live frame stream runs from <Code>http://localhost:3000</Code> against a
          local pipeline server. A deployed page cannot open a <Code>ws://</Code> socket —
          browsers block mixed content — so the dashboard there reports that it cannot
          connect rather than sitting blank.
        </p>
      </section>
    </main>
  );
}

function Figure({ value, label, accent }: { value: string; label: string; accent?: boolean }) {
  return (
    <div>
      <dt
        className="tabular text-3xl font-semibold md:text-4xl"
        style={{ color: accent ? 'var(--accent)' : 'var(--text-hi)' }}
      >
        {value}
      </dt>
      <dd className="mt-2 text-[11px] uppercase tracking-[0.18em] text-[var(--text-lo)]">
        {label}
      </dd>
    </div>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="tabular rounded bg-[var(--ink-700)] px-1.5 py-0.5 text-[12px] text-[var(--text)]">
      {children}
    </code>
  );
}
