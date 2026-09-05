// LatencyBars.tsx — FR-28, the per-stage latency breakdown.
//
// Every value comes from `stats`. The bars are scaled against the 33 ms frame
// budget rather than against the largest stage, so the picture answers "how
// much of the budget did this frame use" instead of silently rescaling itself
// whenever one stage happens to dominate — the same reasoning that fixes the
// elevation ramp's range in palette.ts.
'use client';

import type { FrameStats } from '../../lib/protocol';
import { ms } from './format';

/** 30 FPS. PRD NFR-1. */
const BUDGET_MS = 33.3;

const STAGES: ReadonlyArray<readonly [keyof FrameStats, string, string]> = [
  ['t_perception_ms', 'Perception', '#2979FF'],
  ['t_projection_ms', 'Projection', '#00B8D4'],
  ['t_analysis_ms', 'Analysis', '#00C853'],
  ['t_refine_ms', 'Refine', '#FFD600'],
  ['t_decision_ms', 'Decision', '#FF6D00'],
  ['t_serialise_ms', 'Serialise', '#AA00FF'],
] as const;

export default function LatencyBars({ stats }: { stats: FrameStats }) {
  const total = stats.t_total_ms;
  const overBudget = typeof total === 'number' && total > BUDGET_MS;

  return (
    <section>
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 6,
        }}
      >
        <h2 style={LABEL}>Latency</h2>
        <span
          style={{
            font: '700 16px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
            color: overBudget ? '#FF6D00' : '#e8e8ef',
          }}
          title={`Frame budget ${BUDGET_MS} ms at 30 FPS`}
        >
          {ms(total, 1)}
        </span>
      </header>

      {STAGES.map(([key, label, colour]) => {
        const value = stats[key];
        const width =
          typeof value === 'number' && Number.isFinite(value)
            ? Math.min((value / BUDGET_MS) * 100, 100)
            : 0;
        return (
          <div key={String(key)} style={ROW}>
            <span style={NAME}>{label}</span>
            <span style={TRACK}>
              <span
                style={{
                  display: 'block',
                  height: '100%',
                  width: `${width}%`,
                  background: colour,
                  borderRadius: 2,
                }}
              />
            </span>
            <span style={VALUE}>{ms(typeof value === 'number' ? value : undefined, 1)}</span>
          </div>
        );
      })}
    </section>
  );
}

const LABEL: React.CSSProperties = {
  margin: 0,
  font: '600 10px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
  letterSpacing: '0.14em',
  textTransform: 'uppercase',
  color: '#8b8b9e',
};

const ROW: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '72px 1fr 58px',
  alignItems: 'center',
  gap: 8,
  marginBottom: 3,
};

const NAME: React.CSSProperties = {
  font: '11px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
  color: '#b9b9c8',
};

const TRACK: React.CSSProperties = {
  display: 'block',
  height: 7,
  background: 'rgba(255,255,255,0.08)',
  borderRadius: 2,
  overflow: 'hidden',
};

const VALUE: React.CSSProperties = {
  font: '11px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
  color: '#e8e8ef',
  textAlign: 'right',
};
