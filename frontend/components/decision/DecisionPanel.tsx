// DecisionPanel.tsx — the explainable-routing claim, on screen.
//
// The reroute beat of the run-book (70–82 s) is this panel: the route
// switches to the alternative, the risk level moves, and a sentence says why.
// The deck's claim is that the decision layer is deterministic and
// explainable, so the reason string is the thing a judge reads — it is set in
// the largest type here and must be legible from three metres.
//
// Every value is the server's. `reason` is rendered verbatim: it is generated
// by decision/explain.py, which is deterministic by requirement, and
// reformatting or truncating it here would undermine the point of showing it.
'use client';

import { useEffect, useState } from 'react';
import type { Decision, Track } from '../../lib/protocol';
import { num } from '../hud/format';
import TrackList from './TrackList';

/** Matches the HUD's cadence — the panel is read, not watched. */
const SAMPLE_HZ = 4;

export interface DecisionSnapshot {
  decision: Decision | undefined;
  tracks: Track[];
}

export type DecisionSampler = () => DecisionSnapshot | null;

// Risk is its own semantic axis, so these are deliberately NOT the class
// colours from palette.ts — that file's rule is that class colours mean
// "what is it", and reusing them for "how dangerous is it" would make two
// different things share a colour in the same frame.
const RISK_COLOUR: Record<string, string> = {
  LOW: '#00E676',
  MEDIUM: '#FFC400',
  HIGH: '#FF3D00',
};

/** Sampling wrapper. Holds the timer and nothing else. */
export default function DecisionPanel({ sample }: { sample: DecisionSampler }) {
  const [snap, setSnap] = useState<DecisionSnapshot | null>(null);

  useEffect(() => {
    const id = window.setInterval(() => setSnap(sample()), 1000 / SAMPLE_HZ);
    return () => window.clearInterval(id);
  }, [sample]);

  if (!snap) return null;
  return <DecisionView decision={snap.decision} tracks={snap.tracks} />;
}

/**
 * The panel itself — a pure function of one snapshot.
 *
 * Split out from the sampling wrapper so it can be rendered and asserted on
 * without a browser or a running stream, which is what makes the missing-data
 * paths testable rather than hoped-about.
 */
export function DecisionView({ decision, tracks }: DecisionSnapshot) {
  const risk = decision?.risk ?? '';
  const riskColour = RISK_COLOUR[risk] ?? '#8b8b9e';
  const rerouted = decision?.selected === 'alternative';

  return (
    <aside style={PANEL}>
      <header style={HEADER}>
        <h2 style={LABEL}>Decision</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={routeBadge(rerouted)}>
            {rerouted ? 'ALTERNATIVE' : 'PRIMARY'}
          </span>
          <span style={{ ...riskBadge, color: riskColour, borderColor: riskColour }}>
            {risk || '—'} RISK
          </span>
        </div>
      </header>

      <div style={{ display: 'flex', gap: 22, marginBottom: 10 }}>
        <Figure label="ETA" value={`${num(decision?.eta_s, 1)} s`} />
        <Figure label="Route pts" value={num(decision?.route?.length, 0)} />
        <Figure label="Alt pts" value={num(decision?.alternative?.length, 0)} />
      </div>

      {/* The sentence the whole decision layer exists to produce. */}
      <p style={REASON}>{decision?.reason || 'No decision reported for this frame.'}</p>

      <div style={{ height: 10 }} />
      <TrackList tracks={tracks} />
    </aside>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        style={{
          font: '700 19px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
          color: '#e8e8ef',
        }}
      >
        {value}
      </div>
      <div style={{ ...LABEL, margin: '5px 0 0' }}>{label}</div>
    </div>
  );
}

function routeBadge(rerouted: boolean): React.CSSProperties {
  const colour = rerouted ? '#FF6D00' : '#00C853';
  return {
    padding: '4px 9px',
    borderRadius: 4,
    border: `1px solid ${colour}`,
    background: `${colour}22`,
    color: colour,
    font: '700 11px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
    letterSpacing: '0.08em',
  };
}

const riskBadge: React.CSSProperties = {
  padding: '4px 9px',
  borderRadius: 4,
  border: '1px solid',
  font: '700 11px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
  letterSpacing: '0.08em',
};

const PANEL: React.CSSProperties = {
  position: 'absolute',
  bottom: 16,
  right: 16,
  zIndex: 10,
  width: 430,
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

const LABEL: React.CSSProperties = {
  margin: 0,
  font: '600 10px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
  letterSpacing: '0.14em',
  textTransform: 'uppercase',
  color: '#8b8b9e',
};

// Read from three metres: 15px, generous leading, full contrast.
const REASON: React.CSSProperties = {
  margin: 0,
  padding: '10px 12px',
  borderRadius: 5,
  borderLeft: '3px solid #2979FF',
  background: 'rgba(41,121,255,0.10)',
  font: '15px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace',
  color: '#f0f0f6',
};
