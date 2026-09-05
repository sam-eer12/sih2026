// app/page.tsx — the landing page.
//
// Replaces the create-next-app boilerplate. Deliberately plain: the demo opens
// on /dashboard, and this page exists so the deployed submission link lands
// somewhere that explains what the project is.

import Link from 'next/link';

const CELLS_ADAPTIVE = (705_771).toLocaleString('en-GB');
const CELLS_UNIFORM = (16_000_000).toLocaleString('en-GB');

export default function Home() {
  return (
    <main style={PAGE}>
      <div style={{ maxWidth: 720 }}>
        <p style={EYEBROW}>SIH26053 · DRDO / IDEX</p>
        <h1 style={TITLE}>AVR-25D</h1>
        <p style={LEAD}>
          Adaptive variable-resolution 2.5D LiDAR mapping for dynamic environment
          perception. Resolution is allocated the way the eye allocates it — 5 cm inside
          10 m, coarsening to 50 cm at 100 m, matched to the sensor&rsquo;s own angular
          sampling.
        </p>

        <dl style={FIGURES}>
          <Figure value={CELLS_ADAPTIVE} label="cells, adaptive" />
          <Figure value={CELLS_UNIFORM} label="cells, uniform 5 cm" />
          <Figure value="22.67×" label="reduction" accent />
        </dl>

        <p style={BODY}>
          Because each cell keeps ground height and obstacle height separately, the map
          represents the three hazards a 2D occupancy grid destroys: curbs, potholes and
          overhanging structures. A deterministic decision layer turns the map into a
          route, a risk level and a stated reason.
        </p>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 28 }}>
          <Link href="/dashboard" style={PRIMARY}>
            Live dashboard
          </Link>
          <Link href="/runs" style={SECONDARY}>
            Run history
          </Link>
        </div>

        <p style={NOTE}>
          The live frame stream runs from <code style={CODE}>http://localhost:3000</code>{' '}
          against a local pipeline server. A deployed page cannot open a{' '}
          <code style={CODE}>ws://</code> socket — browsers block mixed content — so the
          dashboard there reports that it cannot connect rather than sitting blank.
        </p>
      </div>
    </main>
  );
}

function Figure({ value, label, accent }: { value: string; label: string; accent?: boolean }) {
  return (
    <div>
      <dt style={{ ...FIGURE_VALUE, color: accent ? '#00C853' : '#e8e8ef' }}>{value}</dt>
      <dd style={FIGURE_LABEL}>{label}</dd>
    </div>
  );
}

const PAGE: React.CSSProperties = {
  minHeight: '100vh',
  display: 'flex',
  alignItems: 'center',
  padding: '48px 32px',
  background: '#0b0b14',
  color: '#e8e8ef',
  font: '15px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace',
};
const EYEBROW: React.CSSProperties = {
  margin: 0,
  font: '600 11px/1 inherit',
  letterSpacing: '0.16em',
  textTransform: 'uppercase',
  color: '#8b8b9e',
};
const TITLE: React.CSSProperties = { margin: '10px 0 0', font: '700 44px/1.1 inherit' };
const LEAD: React.CSSProperties = { margin: '14px 0 0', color: '#c8c8d6' };
const BODY: React.CSSProperties = { margin: '20px 0 0', color: '#b9b9c8' };
const FIGURES: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 36,
  margin: '28px 0 0',
};
const FIGURE_VALUE: React.CSSProperties = { font: '700 26px/1 inherit' };
const FIGURE_LABEL: React.CSSProperties = {
  margin: '6px 0 0',
  font: '600 10px/1 inherit',
  letterSpacing: '0.14em',
  textTransform: 'uppercase',
  color: '#8b8b9e',
};
const PRIMARY: React.CSSProperties = {
  padding: '12px 20px',
  borderRadius: 6,
  background: '#00C853',
  color: '#04120a',
  font: '700 14px/1 inherit',
  textDecoration: 'none',
};
const SECONDARY: React.CSSProperties = {
  padding: '12px 20px',
  borderRadius: 6,
  border: '1px solid rgba(255,255,255,0.22)',
  color: '#e8e8ef',
  font: '600 14px/1 inherit',
  textDecoration: 'none',
};
const NOTE: React.CSSProperties = {
  margin: '28px 0 0',
  font: '12px/1.6 inherit',
  color: '#8b8b9e',
};
const CODE: React.CSSProperties = {
  padding: '1px 4px',
  borderRadius: 3,
  background: 'rgba(255,255,255,0.10)',
};
