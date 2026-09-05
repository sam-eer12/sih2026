// app/dashboard/page.tsx
// The live viewer page — imports Shubham's Viewer component.
// Navya will add the HUD and decision panel around this.
'use client';
import dynamic from 'next/dynamic';
import { useCallback, useEffect, useRef } from 'react';
import { connectFrames, DEFAULT_STREAM_URL } from '../../lib/ws';
import type { SceneHandle } from '../../components/viewer/useThreeScene';

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

  // Fires once, from inside the viewer's mount effect. It must not set React
  // state — the frame path stays outside reconciliation entirely (FR-42), so
  // the socket is held in a ref and the frames go straight to pushFrame.
  const handleReady = useCallback((handle: SceneHandle) => {
    disconnectRef.current?.();
    disconnectRef.current = connectFrames(DEFAULT_STREAM_URL, handle.pushFrame, {
      onStatus: (status, detail) =>
        console.log(`[stream] ${status}${detail ? ` — ${detail}` : ''}`),
      onDecodeError: (err) => console.error('[stream] decode failed:', err.message),
    });
  }, []);

  useEffect(() => {
    return () => {
      disconnectRef.current?.();
      disconnectRef.current = null;
    };
  }, []);

  return (
    <main style={{ width: '100vw', height: '100vh', overflow: 'hidden' }}>
      {/* Live frames from the FastAPI server — browser to backend, no Next.js
          in the path (FR-41). `devStream` is deliberately not passed; the
          synthetic generator stays in the tree as Shubham's offline fallback. */}
      <Viewer onReady={handleReady} enableKeyboard />
    </main>
  );
}
