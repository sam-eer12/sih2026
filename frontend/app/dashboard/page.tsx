// app/dashboard/page.tsx
// The live viewer page — imports Shubham's Viewer component.
// Navya will add the HUD and decision panel around this.
'use client';
import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useRef } from 'react';
import { connectFrames, DEFAULT_STREAM_URL } from '../../lib/ws';
import type { SceneHandle } from '../../components/viewer/useThreeScene';
import StreamStatus, { type StatusSink } from '../../components/hud/StreamStatus';
import Hud from '../../components/hud/Hud';
import ViewControls from '../../components/hud/ViewControls';
import DecisionPanel, {
  type DecisionSnapshot,
} from '../../components/decision/DecisionPanel';
import type { HudSnapshot } from '../../components/hud/types';
import type { FrameMessage } from '../../lib/protocol';

// Dynamic import with SSR disabled — Three.js requires the browser's WebGL context
const Viewer = dynamic(() => import('../../components/viewer/Viewer'), {
  ssr: false,
  loading: () => (
    <div style={{
      width: '100%',
      height: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#1a1a2e',
      color: '#888',
      fontFamily: 'monospace',
      fontSize: '14px',
    }}>
      Loading 3D viewer…
    </div>
  ),
});

export default function DashboardPage() {
  const disconnectRef = useRef<(() => void) | null>(null);
  const statusSinkRef = useRef<StatusSink | null>(null);
  // The newest frame and the scene handle live in refs, never in state. This
  // is the FR-42 line: frames reach the GPU and the HUD samples them, but
  // React is never told a frame arrived.
  const latestFrameRef = useRef<FrameMessage | null>(null);
  const sceneRef = useRef<SceneHandle | null>(null);

  // Fires once, from inside the viewer's mount effect. It must not set React
  // state — the frame path stays outside reconciliation entirely (FR-42), so
  // the socket is held in a ref and the frames go straight to pushFrame.
  const handleReady = useCallback((handle: SceneHandle) => {
    disconnectRef.current?.();
    sceneRef.current = handle;
    disconnectRef.current = connectFrames(
      DEFAULT_STREAM_URL,
      (msg) => {
        latestFrameRef.current = msg;
        handle.pushFrame(msg);
      },
      {
        onStatus: (status, detail) => {
          console.log(`[stream] ${status}${detail ? ` — ${detail}` : ''}`);
          statusSinkRef.current?.(status, detail);
        },
        onDecodeError: (err) => console.error('[stream] decode failed:', err.message),
      }
    );
  }, []);

  // Called by the HUD on its own timer, not per frame. Everything it returns
  // is either straight off the wire or read from the viewer's own getters —
  // nothing about the scene is recomputed here.
  const sampleHud = useCallback((): HudSnapshot | null => {
    const msg = latestFrameRef.current;
    const handle = sceneRef.current;
    if (!msg || !handle) return null;
    return {
      frameId: msg.frame_id,
      mode: msg.mode,
      stats: msg.stats,
      perf: handle.getPerf(),
      uniform: handle.getUniformCounts(),
      capacity: handle.getGridCapacity(),
    };
  }, []);

  // Same discipline as the HUD: read the newest frame from the ref on the
  // panel's own timer. `tracks` is defaulted here because fixtures legitimately
  // send an empty array when the crossing truck is out of frame.
  const sampleDecision = useCallback((): DecisionSnapshot | null => {
    const msg = latestFrameRef.current;
    if (!msg) return null;
    return { decision: msg.decision, tracks: msg.tracks ?? [] };
  }, []);

  const getHandle = useCallback(() => sceneRef.current, []);

  const handleStatusMount = useCallback((sink: StatusSink) => {
    statusSinkRef.current = sink;
  }, []);

  // The viewer element is built once and never rebuilt. Anything else on this
  // page can re-render without touching the canvas subtree, which is what
  // keeps T-W7 (fewer than 10 React renders across 300 frames) safe as the
  // HUD grows in Step 3.
  const viewer = useMemo(
    () => <Viewer onReady={handleReady} enableKeyboard />,
    [handleReady]
  );

  useEffect(() => {
    return () => {
      disconnectRef.current?.();
      disconnectRef.current = null;
      sceneRef.current = null;
      latestFrameRef.current = null;
    };
  }, []);

  return (
    <main style={{ position: 'relative', width: '100vw', height: '100vh', overflow: 'hidden' }}>
      {/* Live frames from the FastAPI server — browser to backend, no Next.js
          in the path (FR-41). `devStream` is deliberately not passed; the
          synthetic generator stays in the tree as Shubham's offline fallback. */}
      {viewer}
      <StreamStatus onMount={handleStatusMount} />
      <Hud sample={sampleHud} />
      <ViewControls getHandle={getHandle} />
      <DecisionPanel sample={sampleDecision} />
    </main>
  );
}
