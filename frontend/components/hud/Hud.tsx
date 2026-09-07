// Hud.tsx — FR-28. The live telemetry panel.
//
// ── The FR-42 boundary, which is the whole design ─────────────────────────
// Frames never enter React. The dashboard parks the newest FrameMessage in a
// ref and hands this component a sampler; the HUD reads that ref on a timer
// and renders a snapshot. At 30 Hz with per-frame state this subtree would
// reconcile 30 times a second; at SAMPLE_HZ it reconciles 4, and the viewer
// is memoized in the dashboard so it is not in this subtree at all and cannot
// re-render no matter what happens here.
//
// T-W7 measures renders inside Viewer.tsx and currently sits at 3 against a
// limit of 10. Nothing here can move that number.
//
// Sampling rather than streaming also matches what the panel is for: a judge
// reads numbers, and digits changing 30 times a second are unreadable.
'use client';

import { useEffect, useState } from 'react';
import ModeBadge from './ModeBadge';
import LatencyBars from './LatencyBars';
import MemoryPanel from './MemoryPanel';
import { count, num } from './format';
import type { HudSampler, HudSnapshot } from './types';

/** Refresh rate for the panel. Readable, and 7x cheaper than per-frame. */
const SAMPLE_HZ = 4;

export default function Hud({ sample }: { sample: HudSampler }) {
  const [snap, setSnap] = useState<HudSnapshot | null>(null);

  useEffect(() => {
    const id = window.setInterval(() => setSnap(sample()), 1000 / SAMPLE_HZ);
    return () => window.clearInterval(id);
  }, [sample]);

  // Before the first frame there is nothing honest to show. StreamStatus is
  // already reporting the connection state, so stay out of the way.
  if (!snap) return null;

  const { stats, perf, uniform, capacity, mode, frameId } = snap;

  // FR-10. Conservation is a ratio of two reported counts, not a measurement
  // of our own — the assertion itself lives in CellGrid.accumulate.
  const conserved =
    typeof stats.n_points === 'number' && stats.n_points > 0
      ? (stats.n_points_conserved / stats.n_points) * 100
      : undefined;

  return (
    <aside style={PANEL}>
      <header style={HEADER}>
        <ModeBadge mode={mode} />
        <span style={FRAME_ID} title="FrameMessage.frame_id">
          #{count(frameId)}
        </span>
      </header>

      <div style={{ display: 'flex', gap: 20, marginBottom: 12 }}>
        <Stat
          value={num(stats.fps, 1)}
          label="pipeline fps"
          title="stats.fps — the rate the server produced frames"
        />
        <Stat
          value={num(perf.fps, 0)}
          label="render fps"
          title={`Measured in the viewer. 1% low ${num(perf.fpsLow, 0)}, ` +
            `${count(perf.instances)} instances (T-V6)`}
          colour={perf.fps >= 30 ? '#00C853' : '#FF6D00'}
        />
      </div>

      <LatencyBars stats={stats} />
      <div style={{ height: 12 }} />
      <MemoryPanel stats={stats} uniform={uniform} capacity={capacity} />

      <footer style={FOOTER} title="FR-10 — every projected point lands in a cell">
        <span style={{ color: '#8b8b9e' }}>Points conserved</span>
        <span style={{ color: conserved === 100 ? '#00C853' : '#FF6D00' }}>
          {num(conserved, 1)}% · {count(stats.n_points_conserved)}/{count(stats.n_points)}
        </span>
      </footer>
    </aside>
  );
}

function Stat({
  value,
  label,
  title,
  colour = '#e8e8ef',
}: {
  value: string;
  label: string;
  title?: string;
  colour?: string;
}) {
  return (
    <div title={title}>
      <div
        style={{
          font: `700 30px/1 ui-monospace, SFMono-Regular, Menlo, monospace`,
          color: colour,
        }}
      >
        {value}
      </div>
      <div
        style={{
          font: '600 10px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          color: '#8b8b9e',
          marginTop: 4,
        }}
      >
        {label}
      </div>
    </div>
  );
}

// Judged on a projector, possibly in a bright room: high contrast, generous
// type, no thin greys on the numbers that matter.
const PANEL: React.CSSProperties = {
  position: 'absolute',
  top: 16,
  right: 16,
  zIndex: 10,
  width: 320,
  padding: '14px 16px',
  borderRadius: 8,
  border: '1px solid rgba(255,255,255,0.14)',
  background: 'rgba(10, 10, 20, 0.86)',
  backdropFilter: 'blur(6px)',
  color: '#e8e8ef',
  pointerEvents: 'none',
};

const HEADER: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  marginBottom: 12,
};

const FRAME_ID: React.CSSProperties = {
  font: '12px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
  color: '#8b8b9e',
};

const FOOTER: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  marginTop: 12,
  paddingTop: 10,
  borderTop: '1px solid rgba(255,255,255,0.10)',
  font: '11px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
};
