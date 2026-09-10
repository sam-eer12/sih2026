// app/page.tsx — the landing page.
//
// The hero is the argument: a mountain that becomes a point cloud under the
// cursor. It is the product's one-sentence pitch made literal — take a
// surface, keep only what a sensor returns, and colour what remains by what
// it is. Every number still traces to results.json.
//
// The copy is deliberately short. Two lines and four figures say what this is;
// the terrain says the rest, and it says it better than a paragraph would. No
// eyebrow, no caps, no instructions — a visitor finds the interaction on their
// own, and telling them to look is what made the page read as a demo.

import Link from 'next/link';
import AuthLink from '../components/auth/AuthLink';
import LidarMountain from '../components/landing/LidarMountain';
import NeuralField from '../components/landing/NeuralField';

const CELLS_ADAPTIVE = (705_771).toLocaleString('en-GB');
const CELLS_UNIFORM = (16_000_000).toLocaleString('en-GB');

export default function Home() {
  return (
    <main className="relative min-h-screen overflow-hidden bg-[var(--ink-900)]">
      {/* Motif sits behind everything and is inert to the pointer. */}
      <NeuralField className="pointer-events-none absolute inset-0 z-0 h-full w-full opacity-60" />

      {/* z-20: the hero's scrims sit at z-10 and would otherwise swallow it. */}
      <AuthLink className="absolute top-6 right-8 z-20 md:right-16" />

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
              <h1 className="rise text-6xl font-semibold tracking-[-0.03em] text-[var(--text-hi)] md:text-8xl">
                NEXA
              </h1>
              <p
                className="rise mt-6 max-w-xl text-[20px] leading-[1.5] text-[var(--text-hi)] md:text-[23px] md:leading-[1.45]"
                style={{ animationDelay: '80ms' }}
              >
                Adaptive LiDAR perception for dynamic environments.
              </p>
              <p
                className="rise mt-4 max-w-xl text-[17px] leading-[1.6] text-[var(--text)]"
                style={{ animationDelay: '160ms' }}
              >
                Variable-resolution 2.5D mapping that preserves detail where it matters.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Figures ──────────────────────────────────────────── */}
      <section className="relative z-10 px-8 pb-24 md:px-16">
        {/* The qualifiers the labels used to carry — the 5 cm baseline, the
            971-scan sample — moved to `title` rather than being dropped: the
            claim stays checkable without putting fine print on the page. */}
        <dl className="flex flex-wrap gap-x-16 gap-y-8 border-t border-[var(--line)] pt-10">
          <Figure value={CELLS_ADAPTIVE} label="Adaptive cells" />
          <Figure
            value={CELLS_UNIFORM}
            label="Uniform cells"
            hint="A uniform 5 cm grid over the same 100 m footprint"
          />
          <Figure value="22.67×" label="Reduction" accent />
          <Figure value="0.878" label="mIoU" hint="Mean IoU over 971 SemanticKITTI scans" />
        </dl>

        <div className="mt-10 flex flex-wrap gap-3">
          <Link
            href="/dashboard"
            className="rounded-md bg-[var(--accent)] px-5 py-3 text-[15px] font-semibold text-[#062713] transition-transform duration-200 hover:-translate-y-0.5"
          >
            Live dashboard
          </Link>
          <Link
            href="/runs"
            className="rounded-md border border-[var(--line)] px-5 py-3 text-[15px] font-semibold text-[var(--text-hi)] transition-colors duration-200 hover:border-[var(--accent)] hover:text-[var(--accent)]"
          >
            Run history
          </Link>
        </div>
      </section>
    </main>
  );
}

function Figure({
  value,
  label,
  accent,
  hint,
}: {
  value: string;
  label: string;
  accent?: boolean;
  hint?: string;
}) {
  return (
    <div title={hint}>
      <dt
        className="tabular text-3xl font-semibold tracking-[-0.03em] md:text-4xl"
        style={{ color: accent ? 'var(--accent)' : 'var(--text-hi)' }}
      >
        {value}
      </dt>
      {/* Sentence case at a readable size. These caption a figure; they do not
          need to compete with it. */}
      <dd className="mt-2.5 text-[14px] text-[var(--text-lo)]">{label}</dd>
    </div>
  );
}
