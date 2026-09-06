// runSession.ts — ties a live dashboard session to a `runs` document and its
// decision log (FR-38, FR-39).
//
// lib/decisionLog.ts had the batching but nothing called it. This is what
// calls it: on mount the dashboard opens a run, and every frame is offered to
// the log, which decides whether it is worth a record.
//
// ── Inert unless everything it needs is present ───────────────────────────
// A session needs a signed-in user and a reachable database. When either is
// missing — which is the state the project is in until the accounts exist —
// `record()` is a no-op that costs one null check per frame. The dashboard
// does not branch on configuration, and nothing in the frame path can throw
// because persistence is switched off. That is the run-book's failure path as
// code: losing Atlas costs the audit log, not the demo.

import { apiPatch, apiPost, ApiError } from './apiClient';
import { createDecisionLog, type DecisionLog } from './decisionLog';
import { isAuthConfigured, getIdToken } from './firebase/client';
import type { FrameMessage } from './protocol';

export interface RunSession {
  /** The run document's id once it exists, else null. */
  readonly runId: string | null;
  /** Why the session is inert, if it is. Surfaced for the HUD, not thrown. */
  readonly status: 'starting' | 'recording' | 'disabled';
  /** Offer one frame. Synchronous, never throws, cheap when disabled. */
  record: (msg: FrameMessage) => void;
  /** Flush, mark the run finished, and stop. */
  stop: () => Promise<void>;
}

export interface RunSessionOptions {
  mode?: string;
  onError?: (err: Error) => void;
}

export function startRunSession(options: RunSessionOptions = {}): RunSession {
  const { onError } = options;

  let runId: string | null = null;
  let log: DecisionLog | null = null;
  let status: RunSession['status'] = 'starting';
  let stopped = false;

  const disable = (reason?: Error) => {
    status = 'disabled';
    // A 401 or 503 is the expected state before the accounts exist, not an
    // error worth shouting about. Anything else is worth reporting.
    if (reason && !(reason instanceof ApiError)) onError?.(reason);
  };

  void (async () => {
    if (!isAuthConfigured) return disable();
    try {
      const token = await getIdToken();
      if (!token) return disable(); // signed out: nothing to attach a run to

      const { id } = await apiPost<{ id: string }>('/api/runs', {
        startedAt: new Date().toISOString(),
        mode: options.mode,
        platform: typeof navigator === 'undefined' ? undefined : navigator.userAgent,
      });
      if (stopped) return;

      runId = id;
      log = createDecisionLog({
        send: async (records) => {
          await apiPost('/api/decisions', { runId: id, records });
        },
        onError,
      });
      status = 'recording';
    } catch (err) {
      disable(err instanceof Error ? err : new Error(String(err)));
    }
  })();

  return {
    get runId() {
      return runId;
    },
    get status() {
      return status;
    },

    record(msg: FrameMessage) {
      // The hot path. One null check when there is nothing to record, which is
      // the common case, and no allocation until the log decides to keep it.
      if (log === null) return;
      const d = msg.decision;
      if (!d) return;
      log.record({
        frameId: msg.frame_id,
        tSec: msg.t_sec,
        selected: d.selected,
        risk: d.risk,
        etaS: d.eta_s,
        reason: d.reason,
        trackIds: msg.tracks?.map((t) => t.id) ?? [],
      });
    },

    async stop() {
      stopped = true;
      const current = log;
      log = null;
      await current?.stop();
      if (runId) {
        try {
          await apiPatch('/api/runs', {
            id: runId,
            finishedAt: new Date().toISOString(),
          });
        } catch {
          // Closing the run is bookkeeping. Failing to do it must not surface
          // as an error while a page is unmounting.
        }
      }
    },
  };
}
