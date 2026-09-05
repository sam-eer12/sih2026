// decisionLog.ts — FR-39. Write on change, plus a heartbeat. Never per frame.
//
// At 30 FPS the naive version is 30 Atlas round-trips a second storing thirty
// near-identical documents: it would dominate the latency budget and produce
// an audit log nobody can read. So a record is queued only when the decision
// actually changes — the selected route, the risk level or the reason string —
// and otherwise at most once every `heartbeatFrames`.
//
// The heartbeat is on its own cadence rather than "N frames since the last
// write", so the arithmetic is predictable: 600 frames containing 2 reroutes
// produce 2 change records plus 10 heartbeats, which is precisely what T-W4
// asserts. Tying it to the last write would make the count depend on where the
// reroutes happened to fall.
//
// Nothing here is awaited from the frame loop. `record()` is synchronous and
// only ever touches an array; the flush runs on a timer and its failures are
// reported, never thrown at the caller. A dashboard that cannot reach Atlas
// must keep rendering — the audit log is the thing that degrades, not the demo
// (run-book: "Login or Atlas unreachable → the pipeline, viewer and HUD are
// entirely local and keep running").

export interface DecisionRecord {
  frameId: number;
  tSec: number;
  selected: string;
  risk: string;
  etaS: number;
  reason: string;
  trackIds: number[];
  /** True when a change triggered this record, false when the heartbeat did. */
  changed: boolean;
}

/** The per-frame input. Shaped to match a decoded FrameMessage. */
export interface DecisionInput {
  frameId: number;
  tSec: number;
  selected: string;
  risk: string;
  etaS: number;
  reason: string;
  trackIds: number[];
}

export interface DecisionLogOptions {
  /** Sends one batch. Rejections are reported, never thrown at the frame loop. */
  send: (records: DecisionRecord[]) => Promise<void>;
  /** Heartbeat cadence in frames. FR-39 says at most one per 60. */
  heartbeatFrames?: number;
  /** How often the queue drains. */
  flushMs?: number;
  onError?: (err: Error) => void;
}

export interface DecisionLog {
  /** Call once per frame. Synchronous, allocation-light, never throws. */
  record: (input: DecisionInput) => void;
  /** Send whatever is queued now. */
  flush: () => Promise<void>;
  /** Stop the timer and flush what is left. */
  stop: () => Promise<void>;
  /** Queued but not yet sent. */
  readonly pending: number;
  /** Records queued since creation — change-triggered and heartbeat. */
  readonly counts: { changed: number; heartbeat: number; sent: number; failed: number };
}

export function createDecisionLog(options: DecisionLogOptions): DecisionLog {
  const { send, heartbeatFrames = 60, flushMs = 2000, onError } = options;

  let queue: DecisionRecord[] = [];
  let framesSeen = 0;
  let last: { selected: string; risk: string; reason: string } | null = null;
  const counts = { changed: 0, heartbeat: 0, sent: 0, failed: 0 };

  const flush = async (): Promise<void> => {
    if (queue.length === 0) return;
    const batch = queue;
    queue = [];
    try {
      await send(batch);
      counts.sent += batch.length;
    } catch (err) {
      counts.failed += batch.length;
      // Deliberately not requeued. A failing endpoint would otherwise grow an
      // unbounded backlog behind a demo that is still running, and a partial
      // audit trail is better than a browser tab consuming memory until it dies.
      onError?.(err instanceof Error ? err : new Error(String(err)));
    }
  };

  const timer =
    typeof window !== 'undefined' ? window.setInterval(() => void flush(), flushMs) : null;

  return {
    record(input: DecisionInput) {
      const isHeartbeat = framesSeen % heartbeatFrames === 0;
      framesSeen += 1;

      const changed =
        last === null ||
        last.selected !== input.selected ||
        last.risk !== input.risk ||
        last.reason !== input.reason;

      if (!changed && !isHeartbeat) return;

      last = { selected: input.selected, risk: input.risk, reason: input.reason };
      if (changed) counts.changed += 1;
      else counts.heartbeat += 1;

      queue.push({ ...input, changed });
    },
    flush,
    async stop() {
      if (timer !== null) window.clearInterval(timer);
      await flush();
    },
    get pending() {
      return queue.length;
    },
    get counts() {
      return { ...counts };
    },
  };
}
