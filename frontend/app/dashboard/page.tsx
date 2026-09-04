// app/dashboard/page.tsx
// The live viewer page — imports Shubham's Viewer component.
// Navya will add the HUD and decision panel around this.
'use client';
import dynamic from 'next/dynamic';

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
  return (
    <main style={{ width: '100vw', height: '100vh', overflow: 'hidden' }}>
      {/* devStream: synthetic frames until lib/ws.ts lands */}
      <Viewer devStream enableKeyboard />
    </main>
  );
}
