// Viewer.tsx — Module 4
// The React component that owns the canvas ref and wires everything together.
// React renders this component exactly ONCE.
'use client';

import { useRef, useEffect } from 'react';
import { useThreeScene, type SceneHandle, type ViewMode } from './useThreeScene';
import { startDevStream } from './__dev__/devFrames';

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

// Views 2 and 4 are scheduled for Days 4 and 7-8. Until then, say so out
// loud rather than silently falling back to the adaptive grid — a view
// that quietly shows the wrong thing is worse than one that refuses.
const NOT_BUILT: ReadonlySet<ViewMode> = new Set<ViewMode>(['uniform', 'decision']);

export default function Viewer({
  onReady,
  devStream = false,
  enableKeyboard = false,
}: ViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const handleRef = useThreeScene(canvasRef, onReady);

  // T-W7: over 300 streamed frames this must stay below 10.
  // Counted in an effect with no dependency array — that runs after every
  // render, which is exactly the thing being measured, and keeps the ref
  // write out of the render pass.
  const renderCount = useRef(0);
  useEffect(() => {
    renderCount.current += 1;
    if (process.env.NODE_ENV === 'development') {
      console.log('React renders:', renderCount.current);
    }
  });

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
      }
    }

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [enableKeyboard, handleRef]);

  return (
    <canvas
      ref={canvasRef}
      style={{
        width: '100%',
        height: '100%',
        display: 'block',
      }}
    />
  );
}
