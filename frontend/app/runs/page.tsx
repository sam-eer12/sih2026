// runs/page.tsx — FR-38. The run history.
//
// The reason this page exists beyond the demo: every number in the deck comes
// from a results.json, and every results.json lands in a run document with the
// config and git commit that produced it. When a judge asks where 22.67x came
// from, the answer should be a run id rather than a memory.
'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { apiGet, ApiError } from '../../lib/apiClient';

interface RunSummary {
  _id: string;
  startedAt?: string;
  finishedAt?: string;
  mode?: string;
  gitCommit?: string;
  platform?: string;
}

export default function RunsPage() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);

  useEffect(() => {
    apiGet<{ runs: RunSummary[] }>('/api/runs')
      .then((d) => setRuns(d.runs))
      .catch(setError);
  }, []);

  return (
    <main style={PAGE}>
      <header style={HEADER}>
        <div>
          <h1 style={TITLE}>Runs</h1>
          <p style={SUB}>
            Every pipeline and benchmark run, with the config and commit that produced it.
          </p>
        </div>
        <Link href="/dashboard" style={LINK}>
          Live dashboard →
        </Link>
      </header>

      {error ? <Problem error={error} /> : null}

      {!error && runs === null ? <p style={SUB}>Loading…</p> : null}

      {runs?.length === 0 ? (
        <p style={SUB}>
          No runs recorded yet. A run appears here once <code style={CODE}>make bench</code>{' '}
          posts its <code style={CODE}>results.json</code>.
        </p>
      ) : null}

      {runs && runs.length > 0 ? (
        <table style={TABLE}>
          <thead>
            <tr>
              <Th>Started</Th>
              <Th>Mode</Th>
              <Th>Commit</Th>
              <Th>Platform</Th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r._id}>
                <Td>
                  <Link href={`/runs/${r._id}`} style={{ color: '#2979FF' }}>
                    {formatDate(r.startedAt)}
                  </Link>
                </Td>
                <Td>{r.mode ?? '—'}</Td>
                <Td style={{ fontFamily: 'inherit' }}>
                  {r.gitCommit ? r.gitCommit.slice(0, 9) : '—'}
                </Td>
                <Td>{r.platform ?? '—'}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </main>
  );
}

export function Problem({ error }: { error: Error }) {
  const unconfigured = error instanceof ApiError && error.isUnconfigured;
  return (
    <div style={NOTICE}>
      <strong>{unconfigured ? 'Persistence is switched off' : 'Could not load runs'}</strong>
      <p style={{ margin: '6px 0 0', color: '#b9b9c8' }}>
        {unconfigured
          ? 'No MONGODB_URI is set, so run history is unavailable. The dashboard, the viewer and the HUD are entirely local and keep working without it.'
          : error.message}
      </p>
    </div>
  );
}

export function formatDate(iso: string | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('en-GB');
}

function Th({ children }: { children: React.ReactNode }) {
  return <th style={TH}>{children}</th>;
}
function Td({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return <td style={{ ...TD, ...style }}>{children}</td>;
}

export const PAGE: React.CSSProperties = {
  minHeight: '100vh',
  padding: '40px 32px',
  background: '#0b0b14',
  color: '#e8e8ef',
  font: '14px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace',
};
export const HEADER: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 16,
  justifyContent: 'space-between',
  alignItems: 'flex-start',
  marginBottom: 28,
};
export const TITLE: React.CSSProperties = { margin: 0, font: '700 26px/1.2 inherit' };
export const SUB: React.CSSProperties = { margin: '6px 0 0', color: '#b9b9c8' };
export const LINK: React.CSSProperties = { color: '#2979FF', textDecoration: 'none' };
export const CODE: React.CSSProperties = {
  padding: '1px 4px',
  borderRadius: 3,
  background: 'rgba(255,255,255,0.10)',
};
export const NOTICE: React.CSSProperties = {
  padding: '12px 14px',
  borderRadius: 6,
  border: '1px solid rgba(255,214,0,0.5)',
  background: 'rgba(255,214,0,0.08)',
  marginBottom: 20,
};
const TABLE: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  maxWidth: 900,
};
const TH: React.CSSProperties = {
  textAlign: 'left',
  padding: '8px 12px 8px 0',
  borderBottom: '1px solid rgba(255,255,255,0.16)',
  font: '600 10px/1 inherit',
  letterSpacing: '0.14em',
  textTransform: 'uppercase',
  color: '#8b8b9e',
};
const TD: React.CSSProperties = {
  padding: '9px 12px 9px 0',
  borderBottom: '1px solid rgba(255,255,255,0.07)',
};
