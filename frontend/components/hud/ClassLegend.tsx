// ClassLegend.tsx — what the colours mean (FR-28).
//
// OWNERSHIP: this file sits in Navya's components/hud/, but it renders
// Shubham's lib/palette.ts and nothing else. It is here rather than in
// components/viewer/ because it is chrome, not canvas — putting HUD markup
// inside the viewer to respect a directory boundary would be the wrong trade.
//
// Why it exists: every semantic colour in the scene came from palette.ts, and
// until now nothing on screen said what any of them meant. CLASS_NAMES has
// carried the comment "For the HUD legend" since day one. A judge watching a
// recording cannot ask, so an unlabelled green road is just a green road.
//
// Renders straight from the palette arrays — a hand-written legend is a second
// source of truth that goes stale the moment a colour changes.

'use client';

import { CLASS_ID_TO_COLOUR, CLASS_NAMES } from '../../lib/palette';

const hex = (c: number) => `#${c.toString(16).padStart(6, '0')}`;

export default function ClassLegend() {
  return (
    <section style={WRAP} aria-label="Semantic class colours">
      <h2 style={TITLE}>Classes</h2>
      <ul style={LIST}>
        {CLASS_NAMES.map((name, id) => (
          <li key={name} style={ROW}>
            <span style={{ ...SWATCH, background: hex(CLASS_ID_TO_COLOUR[id]) }} />
            <span style={LABEL}>{name}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

const WRAP: React.CSSProperties = {
  borderTop: '1px solid #2a2a3c',
  paddingTop: 10,
  marginTop: 12,
};

const TITLE: React.CSSProperties = {
  font: '600 10px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
  letterSpacing: '0.14em',
  textTransform: 'uppercase',
  color: '#8b8b9e',
  margin: '0 0 8px',
};

const LIST: React.CSSProperties = {
  listStyle: 'none',
  margin: 0,
  padding: 0,
  display: 'grid',
  gap: 5,
};

const ROW: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
};

const SWATCH: React.CSSProperties = {
  width: 12,
  height: 12,
  borderRadius: 3,
  flex: '0 0 auto',
  // A hairline keeps dark swatches legible against the dark panel, and keeps
  // the shapes distinguishable if the projector crushes the colours.
  boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.22)',
};

const LABEL: React.CSSProperties = {
  font: '500 11px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace',
  color: '#c9c9d6',
};
