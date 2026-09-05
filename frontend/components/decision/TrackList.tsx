// TrackList.tsx — the tracker's output, per FR-25 View 4.
//
// Fixtures genuinely emit `tracks: []` — the crossing truck is only in frame
// for part of its trajectory — so the empty case is the normal case, not an
// error, and it says so rather than rendering an empty box.
'use client';

import type { Track } from '../../lib/protocol';
import { CLASS_ID_TO_COLOUR, CLASS_NAMES } from '../../lib/palette';
import { num } from '../hud/format';

function hex(v: number): string {
  return `#${v.toString(16).padStart(6, '0')}`;
}

export default function TrackList({ tracks }: { tracks: Track[] }) {
  return (
    <section>
      <h3 style={LABEL}>
        Tracks{tracks.length > 0 ? ` · ${tracks.length}` : ''}
      </h3>

      {tracks.length === 0 ? (
        <p style={EMPTY}>No dynamic objects in view</p>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {tracks.map((t) => (
            <li key={t.id} style={ROW}>
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: hex(CLASS_ID_TO_COLOUR[t.class_id] ?? 0x808080),
                  flexShrink: 0,
                }}
              />
              <span style={{ color: '#e8e8ef' }}>#{t.id}</span>
              <span style={{ color: '#b9b9c8', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {CLASS_NAMES[t.class_id] ?? 'Unknown'}
              </span>
              <span style={{ color: '#e8e8ef', textAlign: 'right' }}>
                {num(t.speed, 1)} m/s
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const LABEL: React.CSSProperties = {
  margin: '0 0 6px',
  font: '600 10px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
  letterSpacing: '0.14em',
  textTransform: 'uppercase',
  color: '#8b8b9e',
};

const EMPTY: React.CSSProperties = {
  margin: 0,
  font: '12px/1.3 ui-monospace, SFMono-Regular, Menlo, monospace',
  color: '#6f6f83',
};

const ROW: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '10px 32px 1fr 66px',
  alignItems: 'center',
  gap: 8,
  padding: '3px 0',
  font: '12px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
};
