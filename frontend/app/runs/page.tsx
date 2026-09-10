// runs/page.tsx — FR-38. The run history.
//
// The reason this page exists beyond the demo: every number in the deck comes
// from a results.json, and every results.json lands in a run document with the
// config and git commit that produced it. When a judge asks where 22.67x came
// from, the answer should be a run id rather than a memory.
'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { apiGet, ApiError } from '../../lib/apiClient';
import { isAuthConfigured } from '../../lib/firebase/client';

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
                <Td style={MONO}>
                  <Link href={`/runs/${r._id}`} style={{ color: '#2979FF' }}>
                    {formatDate(r.startedAt)}
                  </Link>
                </Td>
                <Td>{r.mode ?? '—'}</Td>
                {/* A commit hash is an identifier — the one column that has to
                    stay mono for the characters to be distinguishable. */}
                <Td style={MONO}>{r.gitCommit ? r.gitCommit.slice(0, 9) : '—'}</Td>
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
  // Come back to whichever runs page the reader was actually on, rather than
  // the hardcoded /runs the detail page would otherwise inherit.
  const here = usePathname();
  const status = error instanceof ApiError ? error.status : 0;
  // 503 now has two causes — no MONGODB_URI and no FIREBASE_SERVICE_ACCOUNT —
  // so the copy can no longer name one of them. The server's message already
  // names whichever it is; print that and keep only the reassurance.
  const unconfigured = status === 503;
  // A 401 with no Firebase project is not "you need to sign in" — there is
  // nothing to sign in to, and offering the link sends the reader to a page
  // that only says sign-in is switched off. Say the true thing instead.
  const signedOut = status === 401 && isAuthConfigured;
  const authOff = status === 401 && !isAuthConfigured;

  return (
    <div style={NOTICE}>
      <strong style={{ font: '600 15px/1.3 var(--ui)' }}>
        {unconfigured
          ? 'Run history is unavailable'
          : signedOut
            ? 'Not signed in'
            : authOff
              ? 'Authentication is switched off'
              : 'Could not load runs'}
      </strong>
      <p style={{ margin: '8px 0 0', color: '#b9b9c8', maxWidth: 640 }}>
        {unconfigured ? (
          <>
            {error.message} The dashboard, the viewer and the HUD are entirely local and
            keep working without it.
          </>
        ) : signedOut ? (
          <>
            This session is not signed in, so run history cannot be read.{' '}
            <Link href={`/login?next=${encodeURIComponent(here)}`} style={LINK}>
              Sign in
            </Link>
            .
          </>
        ) : authOff ? (
          <>
            No Firebase project is configured, so requests carry no identity and the
            server has nobody to attribute a run to. Fill in the{' '}
            <code style={CODE}>NEXT_PUBLIC_FIREBASE_*</code> values in{' '}
            <code style={CODE}>.env.local</code> to turn it on. The dashboard, the viewer
            and the HUD are entirely local and keep working without it.
          </>
        ) : (
          error.message
        )}
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

// The page was set in mono end to end, which made a history table read like a
// terminal dump. Sans is the page voice now; MONO is opted into per cell for
// the things that are genuinely identifiers or measurements — commit hashes,
// frame ids, timings, and the verbatim JSON payloads.
export const PAGE: React.CSSProperties = {
  minHeight: '100vh',
  padding: '40px 32px',
  background: '#0b0b14',
  color: '#e8e8ef',
  font: '14.5px/1.6 var(--ui)',
};
export const MONO: React.CSSProperties = {
  fontFamily: 'var(--tech)',
  fontVariantNumeric: 'tabular-nums',
  fontSize: 13.5,
  letterSpacing: '-0.01em',
};
export const HEADER: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 16,
  justifyContent: 'space-between',
  alignItems: 'flex-start',
  marginBottom: 28,
};
export const TITLE: React.CSSProperties = {
  margin: 0,
  font: '600 28px/1.2 var(--ui)',
  letterSpacing: '-0.022em',
};
export const SUB: React.CSSProperties = { margin: '8px 0 0', color: '#b9b9c8', maxWidth: 620 };
export const LINK: React.CSSProperties = {
  color: '#2979FF',
  textDecoration: 'none',
  fontWeight: 500,
};
export const CODE: React.CSSProperties = {
  ...MONO,
  padding: '2px 6px',
  borderRadius: 4,
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
  padding: '10px 14px 10px 0',
  borderBottom: '1px solid rgba(255,255,255,0.16)',
  font: '600 12px/1 var(--ui)',
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
  color: '#8b8b9e',
};
const TD: React.CSSProperties = {
  padding: '11px 14px 11px 0',
  borderBottom: '1px solid rgba(255,255,255,0.07)',
};
