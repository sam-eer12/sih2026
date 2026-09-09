// runs/[id]/page.tsx — one run: config, results, and its decision log.
//
// Uses useParams() rather than the page's `params` prop. In Next 15+ `params`
// is a promise in server components, and this page has to be a client
// component anyway to attach the caller's ID token — useParams sidesteps the
// async-props question entirely.
'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { apiGet } from '../../../lib/apiClient';
import { Problem, formatDate, PAGE, HEADER, TITLE, SUB, LINK, CODE, MONO } from '../page';

interface RunDetail {
  _id: string;
  startedAt?: string;
  finishedAt?: string;
  mode?: string;
  gitCommit?: string;
  platform?: string;
  config?: unknown;
  results?: unknown;
}

interface DecisionRow {
  _id: string;
  frameId: number;
  tSec: number;
  selected: string;
  risk: string;
  etaS: number;
  reason: string;
  changed: boolean;
}

export default function RunDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;

  const [run, setRun] = useState<RunDetail | null>(null);
  const [decisions, setDecisions] = useState<DecisionRow[]>([]);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!id) return;
    apiGet<{ run: RunDetail }>(`/api/runs?id=${encodeURIComponent(id)}`)
      .then((d) => setRun(d.run))
      .catch(setError);
    // The audit log is supporting detail: if it fails, still show the run.
    apiGet<{ decisions: DecisionRow[] }>(`/api/decisions?runId=${encodeURIComponent(id)}`)
      .then((d) => setDecisions(d.decisions))
      .catch(() => setDecisions([]));
  }, [id]);

  return (
    <main style={PAGE}>
      <header style={HEADER}>
        <div>
          <h1 style={TITLE}>Run</h1>
          <p style={SUB}>
            <code style={CODE}>{id ?? '—'}</code>
          </p>
        </div>
        <Link href="/runs" style={LINK}>
          ← All runs
        </Link>
      </header>

      {error ? <Problem error={error} /> : null}
      {!error && !run ? <p style={SUB}>Loading…</p> : null}

      {run ? (
        <>
          <dl style={META}>
            <Meta label="Started" value={formatDate(run.startedAt)} />
            <Meta label="Finished" value={formatDate(run.finishedAt)} />
            <Meta label="Mode" value={run.mode ?? '—'} />
            <Meta label="Commit" value={run.gitCommit ?? '—'} />
            <Meta label="Platform" value={run.platform ?? '—'} />
          </dl>

          {/* Rendered verbatim. This is the provenance of every number in the
              deck, so it is shown exactly as it was stored rather than
              summarised into something prettier and less checkable. */}
          <Section title="Results" body={run.results} empty="No results payload recorded." />
          <Section title="Config" body={run.config} empty="No config snapshot recorded." />

          <h2 style={H2}>Decision log</h2>
          {decisions.length === 0 ? (
            <p style={SUB}>
              No decision records. They are written on change plus a heartbeat (FR-39), never
              per frame.
            </p>
          ) : (
            <table style={TABLE}>
              <thead>
                <tr>
                  <th style={TH}>Frame</th>
                  <th style={TH}>t (s)</th>
                  <th style={TH}>Route</th>
                  <th style={TH}>Risk</th>
                  <th style={TH}>Why</th>
                  <th style={TH}>Reason</th>
                </tr>
              </thead>
              <tbody>
                {decisions.map((d) => (
                  <tr key={d._id}>
                    <td style={TD_NUM}>{d.frameId}</td>
                    <td style={TD_NUM}>{Number.isFinite(d.tSec) ? d.tSec.toFixed(1) : '—'}</td>
                    <td style={TD}>{d.selected || '—'}</td>
                    <td style={TD}>{d.risk || '—'}</td>
                    <td style={{ ...TD, color: d.changed ? '#FF6D00' : '#8b8b9e' }}>
                      {d.changed ? 'change' : 'heartbeat'}
                    </td>
                    <td style={{ ...TD, maxWidth: 420 }}>{d.reason || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      ) : null}
    </main>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt style={DT}>{label}</dt>
      <dd style={DD}>{value}</dd>
    </div>
  );
}

function Section({ title, body, empty }: { title: string; body: unknown; empty: string }) {
  return (
    <section style={{ marginBottom: 28 }}>
      <h2 style={H2}>{title}</h2>
      {body === undefined || body === null ? (
        <p style={SUB}>{empty}</p>
      ) : (
        <pre style={PRE}>{JSON.stringify(body, null, 2)}</pre>
      )}
    </section>
  );
}

const META: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
  gap: 14,
  margin: '0 0 28px',
  maxWidth: 900,
};
const DT: React.CSSProperties = {
  font: '500 12.5px/1.3 var(--ui)',
  color: '#8b8b9e',
};
// Metadata values are timestamps, hashes and platform strings — identifiers,
// so mono, which is also what separates them from their labels above.
const DD: React.CSSProperties = { ...MONO, margin: '6px 0 0', wordBreak: 'break-all' };
const H2: React.CSSProperties = {
  margin: '0 0 12px',
  font: '600 17px/1.25 var(--ui)',
  letterSpacing: '-0.015em',
};
const PRE: React.CSSProperties = {
  margin: 0,
  padding: 16,
  borderRadius: 6,
  border: '1px solid rgba(255,255,255,0.12)',
  background: 'rgba(0,0,0,0.35)',
  maxWidth: 900,
  maxHeight: 340,
  overflow: 'auto',
  // Verbatim JSON — the one place on the page where mono is the whole point.
  font: '12.5px/1.55 var(--tech)',
};
const TABLE: React.CSSProperties = { width: '100%', borderCollapse: 'collapse', maxWidth: 1100 };
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
  padding: '10px 14px 10px 0',
  borderBottom: '1px solid rgba(255,255,255,0.07)',
  verticalAlign: 'top',
};
/** Frame ids and timings: numeric columns, so they line up. */
const TD_NUM: React.CSSProperties = { ...TD, ...MONO };
