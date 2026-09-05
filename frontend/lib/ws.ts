// ws.ts — the realtime path. Browser -> FastAPI, directly (FR-41).
//
// Next.js does not proxy, buffer or re-serialise frame data. This module opens
// a WebSocket straight at the pipeline server, decodes each message with
// lib/protocol.ts, and hands the result to a callback — normally the viewer's
// handle.pushFrame, which writes it into GPU buffers. Nothing here touches
// React state (FR-42).
//
// ── Drop, never queue ─────────────────────────────────────────────────────
// NFR-1: a demo degrades in frame rate, never in latency. The server already
// drops frames when a client is slow; the browser has to do the same, because
// a WebSocket's message events queue without bound and a consumer that falls
// behind would otherwise render an ever-older scene while memory grows.
//
// So a message is not decoded on arrival. The raw buffer is parked in a
// one-slot mailbox — a newer frame overwrites an older unprocessed one — and
// at most one frame is decoded and delivered per animation frame. Two things
// follow: the decode cost of a dropped frame is never paid at all, and the
// viewer is fed at exactly the rate it can draw. `dropped` counts what this
// discards, so the HUD can show it rather than hide it.
//
// ── On stalls, and why they do not trigger a reconnect ────────────────────
// server/app.py:487 makes a blocking queue.get inside an async handler, which
// blocks uvicorn's event loop. Any disconnect can leave the server alive on
// the socket but no longer sending. Reconnecting into that does not help and a
// backoff loop hammering a wedged server makes it worse, so a stall is
// reported through onStatus and left for a human. Reconnect is reserved for an
// actually-closed socket. Remove this once app.py is fixed.

import { decodeFrame, type FrameMessage } from './protocol';

export type StreamStatus =
  | 'connecting'
  | 'open'
  /** Socket is open but no frame has arrived for `stallMs`. See the note above. */
  | 'stalled'
  | 'reconnecting'
  /** Disconnected on purpose. Terminal — no reconnect follows. */
  | 'closed';

export interface StreamOptions {
  /** Connection-state changes. Never called per frame. */
  onStatus?: (status: StreamStatus, detail?: string) => void;
  /** A malformed frame. The frame is discarded; the stream continues. */
  onDecodeError?: (error: Error) => void;
  /** First reconnect delay, doubling to maxBackoffMs. Default 250 ms. */
  initialBackoffMs?: number;
  /** Reconnect delay ceiling. Default 8000 ms. */
  maxBackoffMs?: number;
  /** Silence before a stall is reported. Default 3000 ms. 0 disables. */
  stallMs?: number;
  /**
   * How long to wait for the socket to open before giving up and retrying.
   * Default 5000 ms.
   *
   * This is not theoretical. A server whose event loop is blocked still
   * accepts the TCP connection, so the browser sits in CONNECTING forever
   * and no `close` event ever fires — which means no reconnect, no error,
   * and a canvas that stays blank with nothing in the console but
   * "connecting". That is exactly what a blocked pipeline server did.
   */
  connectTimeoutMs?: number;
}

/**
 * ws://localhost:8000/stream unless NEXT_PUBLIC_WS_URL says otherwise.
 *
 * NFR-9: this is a `ws://` origin, so the page must be served over http from
 * localhost. An https origin on Vercel cannot open it — browsers block the
 * mixed content and the stream silently never connects. The deployment exists
 * for the submission link; the demo runs from http://localhost:3000.
 */
export const DEFAULT_STREAM_URL =
  process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000/stream';

export interface StreamHealth {
  /** Frames delivered to onFrame. */
  delivered: number;
  /** Frames discarded unread because a newer one arrived first. */
  dropped: number;
  /** Zero-length keepalives skipped. */
  keepalives: number;
  /** Frames that failed to decode. */
  errors: number;
  /** Successful socket opens, including reconnects. */
  connects: number;
  status: StreamStatus;
}

/**
 * Connect and stream frames until the returned function is called.
 *
 * ```ts
 * <Viewer onReady={h => connectFrames(DEFAULT_STREAM_URL, h.pushFrame)} />
 * ```
 *
 * Returns a disconnect function; calling it twice is safe. `health` is a live
 * object, readable at any time — read it, do not subscribe per frame.
 */
export function connectFrames(
  url: string,
  onFrame: (msg: FrameMessage) => void,
  options: StreamOptions = {}
): (() => void) & { health: StreamHealth } {
  const {
    onStatus,
    onDecodeError,
    initialBackoffMs = 250,
    maxBackoffMs = 8000,
    stallMs = 3000,
    connectTimeoutMs = 5000,
  } = options;

  const health: StreamHealth = {
    delivered: 0,
    dropped: 0,
    keepalives: 0,
    errors: 0,
    connects: 0,
    status: 'connecting',
  };

  let socket: WebSocket | null = null;
  let stopped = false;
  let backoff = initialBackoffMs;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let connectTimer: ReturnType<typeof setTimeout> | null = null;
  let rafId = 0;

  // The one-slot mailbox. A newer frame replaces an older unprocessed one.
  let pending: ArrayBuffer | null = null;
  let lastFrameAt = 0;
  let stalled = false;

  function setStatus(next: StreamStatus, detail?: string) {
    if (health.status === next) return;
    health.status = next;
    onStatus?.(next, detail);
  }

  // ── Delivery loop — at most one frame per animation frame ───────────────
  function pump() {
    if (stopped) return;
    rafId = requestAnimationFrame(pump);

    if (stallMs > 0 && !stalled && health.status === 'open' && lastFrameAt > 0) {
      if (performance.now() - lastFrameAt > stallMs) {
        stalled = true;
        setStatus('stalled', `no frame for ${stallMs} ms`);
      }
    }

    const buf = pending;
    if (!buf) return;
    pending = null;

    let msg: FrameMessage | null;
    try {
      msg = decodeFrame(buf);
    } catch (err) {
      health.errors += 1;
      onDecodeError?.(err as Error);
      return;
    }
    if (msg === null) {
      health.keepalives += 1;
      return;
    }

    health.delivered += 1;
    // A throw here is the consumer's bug, not the stream's. Surface it, but
    // never let it tear down the socket or stop the pump.
    try {
      onFrame(msg);
    } catch (err) {
      onDecodeError?.(err as Error);
    }
  }

  // ── Socket lifecycle ────────────────────────────────────────────────────
  function open() {
    if (stopped) return;

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch (err) {
      scheduleReconnect((err as Error).message);
      return;
    }
    ws.binaryType = 'arraybuffer';
    socket = ws;

    // A socket that never opens fires no close event, so nothing else here
    // would ever retry. Give up on our own schedule instead.
    if (connectTimeoutMs > 0) {
      connectTimer = setTimeout(() => {
        connectTimer = null;
        if (stopped || ws.readyState === WebSocket.OPEN) return;
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        try {
          ws.close();
        } catch {
          /* already dead */
        }
        if (socket === ws) socket = null;
        scheduleReconnect(
          `no handshake within ${connectTimeoutMs} ms — is the server's event loop blocked?`
        );
      }, connectTimeoutMs);
    }

    ws.onopen = () => {
      if (stopped) return;
      clearConnectTimer();
      health.connects += 1;
      backoff = initialBackoffMs; // a good connection resets the penalty
      lastFrameAt = performance.now();
      stalled = false;
      setStatus('open');
    };

    ws.onmessage = (ev: MessageEvent) => {
      if (stopped || typeof ev.data === 'string') return;
      lastFrameAt = performance.now();
      if (stalled) {
        stalled = false;
        setStatus('open');
      }
      // Overwriting an unread buffer is the drop. Count it and move on.
      if (pending !== null) health.dropped += 1;
      pending = ev.data as ArrayBuffer;
    };

    ws.onerror = () => {
      // The browser fires error then close; close does the reconnecting, and
      // the event carries no useful detail. Nothing to do here but note it.
    };

    ws.onclose = (ev: CloseEvent) => {
      if (stopped) return;
      clearConnectTimer();
      socket = null;
      scheduleReconnect(`socket closed (${ev.code})`);
    };
  }

  function clearConnectTimer() {
    if (connectTimer !== null) {
      clearTimeout(connectTimer);
      connectTimer = null;
    }
  }

  function scheduleReconnect(detail: string) {
    if (stopped || reconnectTimer !== null) return;
    setStatus('reconnecting', detail);
    // Jitter so several tabs reopening do not land on the server together.
    const wait = backoff + Math.random() * backoff * 0.3;
    backoff = Math.min(backoff * 2, maxBackoffMs);
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      open();
    }, wait);
  }

  // ── Start ───────────────────────────────────────────────────────────────
  setStatus('connecting');
  open();
  rafId = requestAnimationFrame(pump);

  const disconnect = () => {
    if (stopped) return;
    stopped = true;
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    clearConnectTimer();
    cancelAnimationFrame(rafId);
    pending = null;
    if (socket) {
      // Drop the handlers first: closing fires onclose, and a live handler
      // there would schedule a reconnect we just cancelled.
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      if (
        socket.readyState === WebSocket.OPEN ||
        socket.readyState === WebSocket.CONNECTING
      ) {
        socket.close(1000, 'client disconnect');
      }
      socket = null;
    }
    setStatus('closed');
  };

  return Object.assign(disconnect, { health });
}
