// ModeBadge.tsx — FR-6, the active perception mode.
//
// "Is the segmentation running live?" is on the judge Q&A list, and the
// documented answer is "the HUD says so, always" (WORK_DISTRIBUTION §6.2.4).
// So this renders FrameMessage.mode verbatim and never guesses.
//
// It would be easy to show "fixtures" when the server is started with
// --fixtures. The wire does not carry that: fixture frames report
// mode "geometric", identical to a real geometric run. A badge that inferred
// the difference would be asserting something the pipeline never said, which
// is the opposite of what FR-6 is for.
'use client';

import { CLASS_COLOURS } from '../../lib/palette';

/** Known modes from protocol.py: "live" | "cached" | "geometric". */
const MODE_COLOUR: Record<string, number> = {
  live: CLASS_COLOURS.DRIVABLE,              // green — inference running now
  cached: CLASS_COLOURS.DYNAMIC_OBJECT,      // blue  — precomputed labels
  geometric: CLASS_COLOURS.NON_DRIVABLE_TERRAIN, // amber — classical fallback
};

const MODE_LABEL: Record<string, string> = {
  live: 'LIVE INFERENCE',
  cached: 'CACHED LABELS',
  geometric: 'GEOMETRIC',
};

function hex(v: number): string {
  return `#${v.toString(16).padStart(6, '0')}`;
}

export default function ModeBadge({ mode }: { mode: string }) {
  // An unrecognised mode is shown as-is rather than mapped to a default. If
  // the server starts reporting something new, that should be visible.
  const colour = hex(MODE_COLOUR[mode] ?? CLASS_COLOURS.UNLABELED);
  const label = MODE_LABEL[mode] ?? mode.toUpperCase();

  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        padding: '5px 10px',
        borderRadius: 4,
        border: `1px solid ${colour}`,
        background: `${colour}22`,
        color: colour,
        font: '700 13px/1 ui-monospace, SFMono-Regular, Menlo, monospace',
        letterSpacing: '0.06em',
        whiteSpace: 'nowrap',
      }}
      title={`FrameMessage.mode = "${mode}" (FR-6)`}
    >
      <span
        style={{ width: 8, height: 8, borderRadius: '50%', background: colour }}
      />
      {label}
    </div>
  );
}
