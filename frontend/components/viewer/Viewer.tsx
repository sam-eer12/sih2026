// Viewer.tsx — Module 4
// The React component that owns the canvas ref and wires everything together.
// React renders this component exactly ONCE.
'use client';

import { useRef, useEffect, useState } from 'react';
import { useThreeScene, type SceneHandle, type ViewMode } from './useThreeScene';
import { startDevStream } from './__dev__/devFrames';
import WipeOverlay from './WipeOverlay';

export interface ViewerProps {
  /**
   * Called once, when the WebGL scene is ready. This is the integration
   * point for Navya's lib/ws.ts:
   *
   *   <Viewer onReady={h => connectStream(h.pushFrame)} />
   *
   * It fires from inside an effect, so it must not set React state that
   * re-renders this component (FR-42).
   */
  onReady?: (handle: SceneHandle) => void;
  /** Feed synthetic frames locally instead of waiting on the WebSocket. */
  devStream?: boolean;
  /**
   * Bind 1/2/3/4 to the views and E to elevation shading.
   * Temporary: these belong in Navya's HUD once it exists, but the viewer
   * needs some way to drive itself until then.
   */
  enableKeyboard?: boolean;
}

const KEY_TO_VIEW: Record<string, ViewMode> = {
  '1': 'raw',
  '2': 'uniform',
  '3': 'adaptive',
  '4': 'decision',
};

// Every view is built. Kept as a set so a future view cannot silently fall
// back to the adaptive grid — a view that quietly shows the wrong thing is
// worse than one that refuses.
const NOT_BUILT: ReadonlySet<ViewMode> = new Set<ViewMode>();

export default function Viewer({
  onReady,
  devStream = false,
  enableKeyboard = false,
}: ViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const handleRef = useThreeScene(canvasRef, onReady);

  // wipeOn is the only React state here, and it changes on a keypress —
  // never on a streamed frame, and never during a drag (FR-42).
  const [wipeOn, setWipeOn] = useState(false);
  const lineRef = useRef<HTMLDivElement>(null);
  const knobRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    handleRef.current?.onDividerChange((x) => {
      const pct = `${(x * 100).toFixed(3)}%`;
      if (lineRef.current) lineRef.current.style.left = pct;
      if (knobRef.current) knobRef.current.style.left = pct;
    });
  }, [handleRef, wipeOn]);

  // T-W7: over 300 streamed frames this must stay below 10.
  // Counted in an effect with no dependency array — that runs after every
  // render, which is exactly the thing being measured, and keeps the ref
  // write out of the render pass.
  const renderCount = useRef(0);
  useEffect(() => {
    renderCount.current += 1;
  });

  // T-W7 verdict, reported once 300 frames have actually streamed. Polling on
  // a timer rather than in the render path, so measuring cannot perturb the
  // thing being measured.
  useEffect(() => {
    if (process.env.NODE_ENV !== 'development') return;
    let reported = false;
    const timer = window.setInterval(() => {
      const frames = handleRef.current?.getFrameCount() ?? 0;
      if (reported || frames < 300) return;
      reported = true;
      const renders = renderCount.current;
      console.log(
        `[t-w7] ${frames} frames streamed → ${renders} React renders — ` +
        `${renders < 10 ? 'PASS' : 'FAIL'} (limit 10)`
      );
    }, 1000);
    return () => window.clearInterval(timer);
  }, [handleRef]);

  // TEMPORARY — delete once Navya's lib/ws.ts lands.
  useEffect(() => {
    if (!devStream) return;
    return startDevStream((msg) => handleRef.current?.pushFrame(msg));
  }, [devStream, handleRef]);

  useEffect(() => {
    if (!enableKeyboard) return;

    function onKeyDown(e: KeyboardEvent) {
      const handle = handleRef.current;
      if (!handle || e.metaKey || e.ctrlKey || e.altKey) return;

      const view = KEY_TO_VIEW[e.key];
      if (view) {
        if (NOT_BUILT.has(view)) {
          console.warn(`[viewer] view "${view}" is not built yet`);
          return;
        }
        handle.setView(view);
        console.log(`[viewer] view → ${view}`);
        return;
      }

      if (e.key === 'e' || e.key === 'E') {
        const next = handle.getColourMode() === 'class' ? 'elevation' : 'class';
        handle.setColourMode(next);
        console.log(`[viewer] colour → ${next}`);
        return;
      }

      if (e.key === 'w' || e.key === 'W') {
        const next = !handle.getWipe();
        handle.setWipe(next);
        setWipeOn(next);
        console.log(`[viewer] wipe → ${next ? 'on' : 'off'}`);
        return;
      }

      if (e.key === 'g' || e.key === 'G') {
        const next = !handle.getGridOverlay();
        handle.setGridOverlay(next);
        console.log(
          `[viewer] grid overlay → ${next ? 'on' : 'off'} ` +
          `(${handle.getGridCapacity().toLocaleString()} cells)`
        );
      }
    }

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [enableKeyboard, handleRef]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <canvas
        ref={canvasRef}
        style={{
          width: '100%',
          height: '100%',
          display: 'block',
        }}
      />
      {wipeOn && <WipeOverlay lineRef={lineRef} knobRef={knobRef} initialDivider={0.5} />}
    </div>
  );
}
