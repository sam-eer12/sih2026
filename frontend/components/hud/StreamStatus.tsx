// StreamStatus.tsx — connection state, on screen.
//
// The scene draws nothing at all when no frames arrive: there is no ground
// plane and no reference grid (Shubham removed the GridHelper deliberately —
// it was indistinguishable from a real cell grid in a view whose whole subject
// is cell size). So "backend down" and "backend fine, camera pointed at empty
// space" looked identical, and a blocked server showed up as a blank page with
// nothing but "connecting" in the console.
//
// This is the smallest thing that makes that state legible. The full HUD
// (FR-28) lands in Step 3 and will absorb it.
//
// FR-42: this owns React state, but it is driven by connection-state changes —
// a handful over a session — never by frames. It is a leaf, and the viewer is
// not in its subtree, so a status change cannot re-render the canvas.
'use client';

import { useEffect, useState } from 'react';
import type { StreamStatus as Status } from '../../lib/ws';

/** Set by the dashboard when the stream reports a new state. */
export type StatusSink = (status: Status, detail?: string) => void;

const LABEL: Record<Status, string> = {
  connecting: 'Connecting to pipeline…',
  open: 'Live',
  stalled: 'Stream stalled — no frames arriving',
  reconnecting: 'Reconnecting…',
  closed: 'Disconnected',
};

const COLOUR: Record<Status, string> = {
  connecting: '#FFD600',
  open: '#00C853',
  stalled: '#FF6D00',
  reconnecting: '#FFD600',
  closed: '#D50000',
};

export interface StreamStatusProps {
  /** Called once with a setter the dashboard pushes status changes into. */
  onMount: (sink: StatusSink) => void;
}

export default function StreamStatus({ onMount }: StreamStatusProps) {
  const [status, setStatus] = useState<Status>('connecting');
  const [detail, setDetail] = useState<string | undefined>();

  useEffect(() => {
    onMount((next, why) => {
      setStatus(next);
      setDetail(why);
    });
  }, [onMount]);

  // Once frames are flowing the canvas speaks for itself.
  if (status === 'open') return null;

  return (
    <div
      style={{
        position: 'absolute',
        top: 16,
        left: 16,
        zIndex: 10,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '10px 14px',
        borderRadius: 6,
        border: `1px solid ${COLOUR[status]}`,
        background: 'rgba(10, 10, 20, 0.85)',
        color: '#e8e8ef',
        font: '13px ui-monospace, SFMono-Regular, Menlo, monospace',
        pointerEvents: 'none',
      }}
    >
      <span
        style={{
          width: 9,
          height: 9,
          borderRadius: '50%',
          background: COLOUR[status],
          flexShrink: 0,
        }}
      />
      <span>
        {LABEL[status]}
        {detail ? <span style={{ opacity: 0.6 }}> — {detail}</span> : null}
      </span>
    </div>
  );
}
