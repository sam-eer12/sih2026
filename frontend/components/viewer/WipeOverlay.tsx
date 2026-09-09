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
  leftLabelRef: React.RefObject<HTMLDivElement | null>;
  rightLabelRef: React.RefObject<HTMLDivElement | null>;
  initialDivider: number;
}

// The labels ride the divider rather than sitting in the screen corners.
// In the corners the right-hand one lands underneath the HUD and the decision
// panel, which hides "705,771" — and a wipe that shows only the 16,000,000
// half is making half an argument. At the seam they are always visible, they
// move with the drag, and each number sits against the grid it describes.
const label: React.CSSProperties = {
  position: 'absolute',
  top: '50%',
  transform: 'translateY(-50%)',
  padding: '10px 14px',
  borderRadius: 6,
  background: 'rgba(10, 12, 24, 0.72)',
  color: '#e8ecf4',
  // The words are read as language and the figure as a measurement, so they
  // are set in different faces — which is also what makes the count the thing
  // your eye lands on rather than one line of uniform mono.
  font: '600 13px/1.35 var(--ui)',
  letterSpacing: '0.01em',
  whiteSpace: 'nowrap',
  pointerEvents: 'none',
};

const count: React.CSSProperties = {
  display: 'block',
  font: '600 26px/1.05 var(--tech)',
  fontVariantNumeric: 'tabular-nums',
  letterSpacing: '-0.03em',
  margin: '3px 0 1px',
};

export default function WipeOverlay({
  lineRef,
  knobRef,
  leftLabelRef,
  rightLabelRef,
  initialDivider,
}: WipeOverlayProps) {
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

      <div ref={leftLabelRef} style={{ ...label, right: `calc(100% - ${pct} + 18px)`, textAlign: 'right' }}>
        Uniform 5 cm
        <span style={{ ...count, color: '#ff8a80' }}>
          {GRID_CAPACITY.uniform.toLocaleString()}
        </span>
        cells
      </div>

      <div ref={rightLabelRef} style={{ ...label, left: `calc(${pct} + 18px)` }}>
        AVR-25D adaptive
        <span style={{ ...count, color: '#69f0ae' }}>
          {GRID_CAPACITY.adaptive.toLocaleString()}
        </span>
        cells · {REDUCTION_FACTOR.toFixed(2)}× fewer
      </div>
    </>
  );
}
