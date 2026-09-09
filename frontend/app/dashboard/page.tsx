// app/dashboard/page.tsx — the live perception console.
//
// The viewer is the page. Everything else floats over it on scrims and
// hairlines rather than sitting in a grid of cards, so the scene stays the
// thing you look at and the chrome stays readable on top of it.
//
// The data path below is unchanged from the working version: frames go into a
// ref and straight to the GPU, the panels sample that ref on their own timers,
// and React is never told a frame arrived (FR-42). Nothing in this file talks
// to the protocol or the scene beyond the handle the viewer hands back.
'use client';

import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { connectFrames, DEFAULT_STREAM_URL, type StreamStatus } from '../../lib/ws';
import type { SceneHandle } from '../../components/viewer/useThreeScene';
import SessionChip from '../../components/hud/SessionChip';
import { startRunSession, type RunSession } from '../../lib/runSession';
import ViewControls from '../../components/hud/ViewControls';
import type { DecisionSnapshot } from '../../components/decision/DecisionPanel';
import type { HudSnapshot } from '../../components/hud/types';
import type { FrameMessage } from '../../lib/protocol';
import {
  TopRail,
  PerceptionRail,
  DecisionRail,
  StageAtmosphere,
  StageMessage,
} from '../../components/dashboard/ConsoleChrome';
import NeuralField from '../../components/landing/NeuralField';

// Dynamic import with SSR disabled — Three.js requires the browser's WebGL context
const Viewer = dynamic(() => import('../../components/viewer/Viewer'), {
  ssr: false,
  loading: () => null,
});

export default function DashboardPage() {
  const disconnectRef = useRef<(() => void) | null>(null);
  // The newest frame and the scene handle live in refs, never in state. This
  // is the FR-42 line: frames reach the GPU and the panels sample them, but
  // React is never told a frame arrived.
  const latestFrameRef = useRef<FrameMessage | null>(null);
  const sceneRef = useRef<SceneHandle | null>(null);
  // The audit trail (FR-38, FR-39). Inert until there is a signed-in user and
  // a reachable database, so the frame path below does not branch on config.
  const sessionRef = useRef<RunSession | null>(null);

  // Connection state changes a handful of times a session, never per frame.
  const [status, setStatus] = useState<StreamStatus>('connecting');

  // Wipe state lives here so ViewControls and Viewer stay in sync without
  // either component owning it. Changes only on user interaction — never on
  // a streamed frame — so this does not affect T-W7.
  const [wipeActive, setWipeActive] = useState(false);

  const handleWipeChange = useCallback((active: boolean) => {
    setWipeActive(active);
  }, []);

  // Fires once, from inside the viewer's mount effect. It must not set React
  // state per frame — the frame path stays outside reconciliation entirely
  // (FR-42), so the socket is held in a ref and frames go straight to
  // pushFrame.
  const handleReady = useCallback((handle: SceneHandle) => {
    disconnectRef.current?.();
    sceneRef.current = handle;
    sessionRef.current ??= startRunSession({
      onError: (err) => console.error('[runs]', err.message),
    });
    disconnectRef.current = connectFrames(
      DEFAULT_STREAM_URL,
      (msg) => {
        latestFrameRef.current = msg;
        handle.pushFrame(msg);
        // Synchronous and cheap: the log decides whether this frame is worth a
        // record, and nothing is awaited here (FR-39).
        sessionRef.current?.record(msg);
      },
      {
        onStatus: (next, detail) => {
          console.log(`[stream] ${next}${detail ? ` — ${detail}` : ''}`);
          setStatus(next);
        },
        onDecodeError: (err) => console.error('[stream] decode failed:', err.message),
      }
    );
  }, []);

  // Called by the panels on their own timers, not per frame. Everything
  // returned is either straight off the wire or read from the viewer's own
  // getters — nothing about the scene is recomputed here.
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

  // `tracks` is defaulted here because fixtures legitimately send an empty
  // array when the crossing truck is out of frame.
  const sampleDecision = useCallback((): DecisionSnapshot | null => {
    const msg = latestFrameRef.current;
    if (!msg) return null;
    return { decision: msg.decision, tracks: msg.tracks ?? [] };
  }, []);

  const getHandle = useCallback(() => sceneRef.current, []);

  // The viewer element is built once and never rebuilt. Anything else on this
  // page can re-render without touching the canvas subtree, which is what
  // keeps T-W7 (fewer than 10 React renders across 300 frames) safe.
  //
  // wipeActive is the one exception that requires a re-render: the WipeOverlay
  // React element is conditionally mounted inside Viewer based on this prop.
  // That is exactly correct — a wipe toggle is a user action, not a frame
  // event, so T-W7 is unaffected.
  const viewer = useMemo(
    () => (
      <Viewer
        onReady={handleReady}
        enableKeyboard
        isWipeActive={wipeActive}
        onWipeChange={handleWipeChange}
      />
    ),
    [handleReady, wipeActive, handleWipeChange]
  );

  useEffect(() => {
    return () => {
      disconnectRef.current?.();
      disconnectRef.current = null;
      sceneRef.current = null;
      latestFrameRef.current = null;
      // Flush whatever the log still holds and close the run. Fire-and-forget:
      // an unmount cannot await, and losing the tail of an audit trail must
      // never surface as an error while the page is going away.
      void sessionRef.current?.stop();
      sessionRef.current = null;
    };
  }, []);

  return (
    <main className="relative h-screen w-screen overflow-hidden bg-[var(--ink-900)]">
      {/* The scene fills the page — the chrome floats over it.
          Live frames come from the FastAPI server, browser to backend, with no
          Next.js in the path (FR-41). `devStream` is deliberately not passed;
          the synthetic generator stays in the tree as an offline fallback. */}
      <div className="absolute inset-0">{viewer}</div>

      {/* Depth around the scene, and scrims so the readouts stay legible
          without dimming the middle, which is where the grid is. */}
      <NeuralField
        className="pointer-events-none absolute inset-0 z-10 h-full w-full opacity-25"
        density={40}
        linkRadius={120}
      />
      <StageAtmosphere />
      <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-28 bg-gradient-to-b from-[var(--ink-900)] via-[var(--ink-900)]/45 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-24 bg-gradient-to-t from-[var(--ink-900)]/90 to-transparent" />

      <StageMessage status={status} />

      <TopRail status={status} sample={sampleHud} session={<SessionChip />} />
      <PerceptionRail sample={sampleHud} />
      <DecisionRail sample={sampleDecision} />

      {/* Controls sit centred at the bottom, clear of both side columns. */}
      <div
        className="rise pointer-events-none absolute inset-x-0 bottom-6 z-30 flex justify-center px-6"
        style={{ animationDelay: '160ms' }}
      >
        <ViewControls getHandle={getHandle} onWipeChange={handleWipeChange} />
      </div>
    </main>
  );
}
