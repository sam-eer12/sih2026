// WipeOverlay.tsx — the divider line and the two capacity labels.
//
// DOM rather than in-scene geometry: text stays crisp at projector
// resolution, and the divider never has to fight the depth buffer.
// Navya can restyle this to match the HUD; the numbers come from the handle.

'use client';

import { GRID_CAPACITY, REDUCTION_FACTOR } from './gridShader';

export interface WipeOverlayProps {
  /** Attached to the divider line and its grab handle. The drag moves these
   *  elements directly — routing pointer moves through React state would
   *  re-render the viewer dozens of times per drag for no benefit. */
  lineRef: React.RefObject<HTMLDivElement | null>;
  knobRef: React.RefObject<HTMLDivElement | null>;
  initialDivider: number;
}

const label: React.CSSProperties = {
  position: 'absolute',
  top: 24,
  padding: '10px 14px',
  borderRadius: 6,
  background: 'rgba(10, 12, 24, 0.72)',
  color: '#e8ecf4',
  font: '600 13px/1.35 ui-monospace, SFMono-Regular, Menlo, monospace',
  letterSpacing: '0.02em',
  whiteSpace: 'nowrap',
  pointerEvents: 'none',
};

const count: React.CSSProperties = {
  display: 'block',
  fontSize: 22,
  fontWeight: 700,
  marginTop: 2,
};

export default function WipeOverlay({ lineRef, knobRef, initialDivider }: WipeOverlayProps) {
  const pct = `${(initialDivider * 100).toFixed(2)}%`;

  return (
    <>
      {/* Divider. pointerEvents none — the canvas owns the drag. */}
      <div
        ref={lineRef}
        style={{
          position: 'absolute',
          left: pct,
          top: 0,
          bottom: 0,
          width: 2,
          marginLeft: -1,
          background: '#ffffff',
          boxShadow: '0 0 10px rgba(0,0,0,0.85)',
          pointerEvents: 'none',
        }}
      />
      {/* Grab affordance */}
      <div
        ref={knobRef}
        style={{
          position: 'absolute',
          left: pct,
          top: '50%',
          width: 34,
          height: 34,
          marginLeft: -17,
          marginTop: -17,
          borderRadius: '50%',
          border: '2px solid #ffffff',
          background: 'rgba(10, 12, 24, 0.6)',
          boxShadow: '0 0 10px rgba(0,0,0,0.85)',
          pointerEvents: 'none',
        }}
      />

      <div style={{ ...label, left: 24 }}>
        UNIFORM 5 cm
        <span style={{ ...count, color: '#ff8a80' }}>
          {GRID_CAPACITY.uniform.toLocaleString()}
        </span>
        cells
      </div>

      <div style={{ ...label, right: 24, textAlign: 'right' }}>
        AVR-25D ADAPTIVE
        <span style={{ ...count, color: '#69f0ae' }}>
          {GRID_CAPACITY.adaptive.toLocaleString()}
        </span>
        cells · {REDUCTION_FACTOR.toFixed(2)}× fewer
      </div>
    </>
  );
}
