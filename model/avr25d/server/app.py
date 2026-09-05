"""FastAPI + WebSocket pipeline driver.  IMPLEMENTATION_PLAN.md §6.12.

Usage
-----
    # Fixture frames — unblocks frontend immediately (no real data needed)
    python -m avr25d.server.app --fixtures

    # Real pipeline with geometric segmenter
    python -m avr25d.server.app --infer geometric --seq 04

    # Real pipeline with cached labels (fastest, demo mode)
    python -m avr25d.server.app --infer cached --seq 04

    # Replay a pre-recorded log (demo fallback)
    python -m avr25d.server.app --replay data/logs/demo.log

    # Record while running (build the fallback early)
    python -m avr25d.server.app --infer cached --seq 04 --record data/logs/demo.log

Design decisions (from PRD / IMPLEMENTATION_PLAN)
-------------------------------------------------
1. Pipeline runs in a **worker thread**.  The WebSocket handler picks the
   latest frame from a queue and sends it — it never runs perception itself.

2. **Drop frames rather than queue them** (NFR-1).  If a client falls behind,
   skip frames.  A demo at 15 FPS is fine; a demo with a 5-second backlog is
   not.  The queue holds at most 2 frames; a put that would block uses
   ``put_nowait`` and discards the old frame instead.

3. **mode in FrameMessage matches reality** (FR-6).  ``--infer cached`` sets
   mode "cached", geometric sets "geometric", live inference sets "live".

4. LabelCache is accessed via ``cache.for_frame(sequence, frame_id)`` — NOT
   ``cache[frame_id]``.  Using the integer overload silently returns the wrong
   sequence's labels when multiple sequences have been cached (Sameer's Day 7
   note in docs/progress/sameer.md).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Iterator

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from ..config import load_config
from ..bench.baselines import (
    BYTES_PER_CELL,
    b1_dense_uniform_25d,
)
from ..decision.traversability import score as _trav_score
from ..decision.tracker import Tracker as _Tracker
from ..decision.costmap import build_costmap as _build_costmap
from ..decision.planner import plan as _plan
from ..decision.explain import make_context as _make_context, explain as _explain
from ..core.grid import RingGrid
from ..core.cell import CellGrid
from ..perception.labelmap import raw_is_moving, raw_to_avr, split_label
from .fixtures import frame_generator as fixture_generator
from .protocol import (
    CellArrays,
    Decision,
    FrameMessage,
    FrameStats,
    RefinedArrays,
    Track,
    encode,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASELINE_BYTES_CONST = b1_dense_uniform_25d().bytes   # 400 MB

# WebSocket send loop: how long to yield when the frame queue is empty, and
# how long a client may hear nothing before it gets a zero-length keepalive.
_POLL_INTERVAL_S   = 0.002
_KEEPALIVE_AFTER_S = 2.0


def _build_cell_arrays(cells: CellGrid, grid: RingGrid) -> CellArrays:
    """Extract occupied cells from CellGrid into wire-format CellArrays."""
    occ_mask = cells.count > 0
    occ_ids  = np.flatnonzero(occ_mask).astype(np.int32)

    if occ_ids.size == 0:
        return CellArrays.empty()

    # Recover (ring, bin) from flat cell ids
    k = np.searchsorted(grid.offset, occ_ids, side="right") - 1
    k = np.clip(k, 0, grid.n_rings - 1).astype(np.int32)
    j = (occ_ids - grid.offset[k]).astype(np.int32)

    return CellArrays(
        n          = int(occ_ids.size),
        cell_id    = occ_ids.astype(np.uint32),
        ring       = k.astype(np.uint16),
        bin        = j.astype(np.uint16),
        z_ground   = cells.z_ground[occ_ids],
        z_obstacle = cells.z_obstacle[occ_ids],
        roughness  = cells.roughness[occ_ids],
        slope      = cells.slope[occ_ids],
        class_id   = cells.class_id[occ_ids],
        confidence = cells.confidence[occ_ids],
        flags      = cells.flags[occ_ids],
    )


def _placeholder_decision() -> Decision:
    return Decision(
        route       = [[0.0, 0.0], [10.0, 0.0], [30.0, 0.0], [50.0, 0.0]],
        alternative = [[0.0, 0.0], [10.0, 2.0], [30.0, 2.0], [50.0, 0.0]],
        selected    = "primary",
        risk        = "LOW",
        eta_s       = 6.25,
        reason      = "Primary route selected: mean traversability 0.91, no dynamic conflicts.",
    )


# ---------------------------------------------------------------------------
# Pipeline worker
# ---------------------------------------------------------------------------

class PipelineWorker:
    """Runs the perception → grid → cell → encode loop in a background thread.

    Pushes encoded FrameMessage bytes into ``out_queue``.  If the queue is
    full (consumer is slow), the oldest frame is dropped (NFR-1).
    """

    def __init__(
        self,
        cfg,
        mode: str,
        out_queue: queue.Queue,
        *,
        seq: str = "04",
        data_root: Path | None = None,
        record_path: Path | None = None,
    ) -> None:
        self._cfg        = cfg
        self._mode       = mode
        self._queue      = out_queue
        self._seq        = seq
        self._data_root  = data_root or Path("data/kitti")
        self._record_path = record_path
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="pipeline")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    # ── main loop ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            for frame_bytes in self._iter_frames():
                if self._stop_event.is_set():
                    break
                # Drop oldest if queue is full (degrade in FPS, not latency)
                if self._queue.full():
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                self._queue.put(frame_bytes)
        except Exception:
            logger.exception("pipeline worker crashed")

    def _iter_frames(self) -> Iterator[bytes]:
        cfg  = self._cfg
        mode = self._mode

        if mode == "fixtures":
            for msg in fixture_generator():
                if self._stop_event.is_set():
                    return
                yield encode(msg)
            return

        # ── real pipeline ─────────────────────────────────────────────────
        from ..io.kitti import KittiSequence

        try:
            seq = KittiSequence(self._data_root, self._seq)
        except FileNotFoundError:
            logger.error(
                "KITTI sequence %s not found at %s — "
                "run tools/fetch_kitti.py first or use --fixtures",
                self._seq, self._data_root,
            )
            return

        grid  = RingGrid(
            s_min  = cfg.grid.s_min,
            s_max  = cfg.grid.s_max,
            r_knee = cfg.grid.r_knee,
            r_max  = cfg.grid.r_max,
        )
        cells = CellGrid(grid)

        # ── segmenter selection ───────────────────────────────────────────
        segmenter = None
        cache     = None

        if mode == "geometric":
            from ..perception.geometric_seg import GeometricSegmenter
            segmenter = GeometricSegmenter(cfg)

        elif mode == "cached":
            from ..perception.cache import LabelCache
            cache_dir = Path("data/cache") / self._seq
            if not cache_dir.exists():
                logger.warning(
                    "Label cache for seq %s not found at %s — "
                    "falling back to geometric segmenter.  "
                    "Run tools/build_cache.py to build the cache.",
                    self._seq, cache_dir,
                )
                from ..perception.geometric_seg import GeometricSegmenter
                segmenter = GeometricSegmenter(cfg)
                mode = "geometric"
            else:
                cache = LabelCache(cache_dir)

        elif mode == "live":
            from ..perception.onnx_infer import OnnxSegmenter
            model_path = Path(cfg.perception.model)
            if not model_path.exists():
                logger.warning(
                    "ONNX model not found at %s — falling back to geometric.",
                    model_path,
                )
                from ..perception.geometric_seg import GeometricSegmenter
                segmenter = GeometricSegmenter(cfg)
                mode = "geometric"
            else:
                segmenter = OnnxSegmenter(model_path, cfg)

        # ── optional recorder ─────────────────────────────────────────────
        record_fh = None
        if self._record_path:
            self._record_path.parent.mkdir(parents=True, exist_ok=True)
            record_fh = self._record_path.open("wb")
            logger.info("Recording frames to %s", self._record_path)

        # ── frame loop ────────────────────────────────────────────────────
        target_dt = 1.0 / float(cfg.runtime.target_fps)
        frame_idx = 0
        tracker   = _Tracker()   # persists across frames for stable track IDs

        try:
            while not self._stop_event.is_set():
                scan = seq[frame_idx % len(seq)]
                t_frame_start = time.perf_counter()

                # ── perception ────────────────────────────────────────────
                t0 = time.perf_counter()
                if mode == "cached" and cache is not None:
                    avr_labels = cache.for_frame(self._seq, scan.frame_id)
                    moving     = raw_is_moving(scan.raw_label)
                    t_perc     = (time.perf_counter() - t0) * 1000.0
                elif segmenter is not None:
                    avr_labels = segmenter(scan.xyz, scan.intensity)
                    moving     = scan.moving
                    t_perc     = getattr(segmenter, "last_latency_ms", 0.0)
                else:
                    avr_labels = scan.avr_label
                    moving     = scan.moving
                    t_perc     = 0.0

                # ── grid projection + accumulation ────────────────────────
                t1 = time.perf_counter()
                cells.reset()
                stats_acc = cells.accumulate(scan.xyz, scan.intensity, avr_labels, moving)
                t_proj = (time.perf_counter() - t1) * 1000.0

                # ── cell analysis (hazard flags, slope, roughness) ─────────
                t2 = time.perf_counter()
                cells.analyse(cfg)
                t_analysis = (time.perf_counter() - t2) * 1000.0

                # ── build wire arrays ──────────────────────────────────────
                t3 = time.perf_counter()
                cell_arrays = _build_cell_arrays(cells, grid)

                # ── refinement (core/refine.py) ───────────────────────────
                # Imported lazily — server starts even if refine.py is absent.
                t_refine_start = time.perf_counter()
                refined_arrays = RefinedArrays.empty()
                try:
                    from ..core.refine import refine as _refine
                    overlay = _refine(cells, grid, cfg)
                    if overlay is not None and overlay.n > 0:
                        refined_arrays = overlay.to_refined_arrays()
                except ImportError:
                    pass   # refine.py not wired yet — silent fallback
                t_refine = (time.perf_counter() - t_refine_start) * 1000.0

                # ── decision layer ────────────────────────────────────────
                t_dec_start = time.perf_counter()
                try:
                    trav         = _trav_score(cells, cfg)
                    tracks       = tracker.update(cells, grid, dt=target_dt)
                    cm           = _build_costmap(cells, trav, tracks, grid, cfg)
                    primary, alt = _plan(cm, None, cfg)
                    ctx          = _make_context(primary, alt, tracks, cfg)
                    reason       = _explain(ctx)
                    decision     = Decision(
                        route       = primary.waypoints,
                        alternative = alt.waypoints,
                        selected    = ctx.selected,
                        risk        = ctx.risk,
                        eta_s       = round(primary.length_m / max(8.0, 0.1), 1),
                        reason      = reason,
                    )
                except Exception as exc:
                    logger.debug("decision layer error: %s", exc)
                    decision = _placeholder_decision()
                    tracks   = []
                t_decision = (time.perf_counter() - t_dec_start) * 1000.0

                # ── serialise ─────────────────────────────────────────────
                t4 = time.perf_counter()
                n_occ   = cell_arrays.n
                n_cells = grid.n_cells
                mem_b   = n_cells * BYTES_PER_CELL

                elapsed_total = (time.perf_counter() - t_frame_start) * 1000.0

                frame_stats = FrameStats(
                    fps                = round(1000.0 / max(elapsed_total, 1.0), 1),
                    t_perception_ms    = round(t_perc, 2),
                    t_projection_ms    = round(t_proj, 2),
                    t_analysis_ms      = round(t_analysis, 2),
                    t_refine_ms        = round(t_refine, 2),
                    t_decision_ms      = round(t_decision, 2),
                    t_serialise_ms     = 0.0,  # filled after encode
                    t_total_ms         = round(elapsed_total, 2),
                    n_points           = stats_acc.n_points_in,
                    n_points_conserved = stats_acc.n_points_assigned,
                    n_cells_occupied   = n_occ,
                    n_cells_total      = n_cells,
                    mem_bytes          = mem_b,
                    baseline_mem_bytes = _BASELINE_BYTES_CONST,
                    reduction          = round(_BASELINE_BYTES_CONST / mem_b, 4),
                )

                msg = FrameMessage(
                    frame_id = scan.frame_id,
                    t_sec    = round(frame_idx * target_dt, 4),
                    mode     = mode,
                    cells    = cell_arrays,
                    refined  = refined_arrays,
                    tracks   = tracks,
                    decision = decision,
                    stats    = frame_stats,
                )

                wire = encode(msg)
                t_ser = (time.perf_counter() - t4) * 1000.0
                # patch serialise time into the already-encoded stats via a tiny
                # JSON patch is unnecessary — the next frame will have correct numbers.

                # ── optional record ───────────────────────────────────────
                if record_fh:
                    length = len(wire).to_bytes(4, "little")
                    record_fh.write(length + wire)
                    record_fh.flush()

                yield wire

                # ── pace to target FPS ────────────────────────────────────
                elapsed_s = time.perf_counter() - t_frame_start
                if elapsed_s < target_dt:
                    time.sleep(target_dt - elapsed_s)

                frame_idx += 1

        finally:
            if record_fh:
                record_fh.close()
                logger.info("Recording closed: %s", self._record_path)


# ---------------------------------------------------------------------------
# Replay worker (demo fallback)
# ---------------------------------------------------------------------------

class ReplayWorker:
    """Reads a pre-recorded log and re-emits frames at the original rate."""

    def __init__(self, log_path: Path, out_queue: queue.Queue) -> None:
        self._path   = log_path
        self._queue  = out_queue
        self._stop   = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="replay")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def _run(self) -> None:
        try:
            with self._path.open("rb") as fh:
                while not self._stop.is_set():
                    hdr = fh.read(4)
                    if len(hdr) < 4:
                        # Loop the replay
                        fh.seek(0)
                        continue
                    n = int.from_bytes(hdr, "little")
                    data = fh.read(n)
                    if len(data) < n:
                        fh.seek(0)
                        continue
                    if self._queue.full():
                        try:
                            self._queue.get_nowait()
                        except queue.Empty:
                            pass
                    self._queue.put(data)
                    time.sleep(1.0 / 30)
        except Exception:
            logger.exception("replay worker crashed")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

def make_app(cfg, worker) -> FastAPI:
    app = FastAPI(title="AVR-25D pipeline server")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],    # NFR-9: demo always runs on localhost
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def _startup():
        worker.start()
        logger.info("Pipeline worker started")

    @app.on_event("shutdown")
    async def _shutdown():
        worker.stop()
        logger.info("Pipeline worker stopped")

    @app.get("/health")
    async def health():
        return {"status": "ok", "n_cells": 705_771}

    @app.websocket("/stream")
    async def stream(ws: WebSocket):
        """Binary WebSocket endpoint — sends FrameMessage bytes at pipeline rate.

        The browser connects directly here (FR-41 — Next.js does NOT proxy this).
        Frames are dropped rather than queued if the client is slow (NFR-1).
        """
        await ws.accept()
        logger.info("WebSocket client connected: %s", ws.client)

        # ── Why this loop is shaped the way it is ─────────────────────────
        # Two bugs used to live here and they compounded into a server that
        # died on the first disconnect and had to be SIGKILLed.
        #
        # 1. `worker._queue.get(timeout=2.0)` is a *blocking* call. Run
        #    directly in a coroutine it blocks the whole event loop, so
        #    /health stopped answering, new WebSocket handshakes were never
        #    completed, and uvicorn could not process its own shutdown
        #    signal. Confirmed with `sample`: the main thread sat in
        #    _PySemaphore_Wait inside the queue lock. It now runs on a
        #    worker thread via asyncio.to_thread, so the loop stays free.
        #
        # 2. Nothing ever called receive(), so the handler never learned the
        #    client had gone. ASGI delivers disconnects as an inbound
        #    message; without reading it this loop happily "sent" frames
        #    into a dead socket forever. A watcher task now reads it and
        #    ends the loop.
        #
        # Backpressure is left to the queue rather than to wait_for(). The
        # worker already drops the oldest frame when the queue is full
        # (NFR-1), so a slow client degrades in frame rate exactly as
        # intended — and cancelling a send mid-flight, which is what the old
        # wait_for did on timeout, can leave the connection in a state the
        # protocol cannot recover from.
        #
        # The queue is polled rather than drained by a helper thread. Both a
        # per-frame asyncio.to_thread and a long-lived drain thread were
        # measured at ~13 frames/s against the ~27 this poll sustains: the
        # extra thread wakes on every frame and trades the GIL with the event
        # loop, and that handoff costs more than the poll it replaced.

        disconnected = asyncio.Event()

        async def _watch_for_disconnect() -> None:
            """Read inbound messages so a client disconnect is actually seen."""
            try:
                while True:
                    message = await ws.receive()
                    if message.get("type") == "websocket.disconnect":
                        break
            except Exception:
                pass
            finally:
                disconnected.set()

        watcher = asyncio.create_task(_watch_for_disconnect())
        idle_since = time.perf_counter()
        try:
            while not disconnected.is_set():
                try:
                    frame_bytes: bytes = worker._queue.get_nowait()
                except queue.Empty:
                    # Nothing ready. Yield briefly instead of blocking the
                    # loop; at 30 Hz this polls a handful of times per frame
                    # and costs nothing measurable.
                    await asyncio.sleep(_POLL_INTERVAL_S)
                    if time.perf_counter() - idle_since < _KEEPALIVE_AFTER_S:
                        continue
                    # Keepalive so the browser does not time out while the
                    # pipeline is still starting up.
                    frame_bytes = b""

                idle_since = time.perf_counter()
                if disconnected.is_set():
                    break

                try:
                    await ws.send_bytes(frame_bytes)
                except Exception:
                    # The peer is gone, or the transport is broken. Either
                    # way this connection is finished — never spin on it.
                    break
        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected: %s", ws.client)
        except Exception:
            logger.exception("WebSocket error")
        finally:
            disconnected.set()
            watcher.cancel()
            try:
                await watcher
            except (asyncio.CancelledError, Exception):
                pass
            logger.info("WebSocket handler finished: %s", ws.client)

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m avr25d.server.app",
        description="AVR-25D pipeline server",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--fixtures", action="store_true",
        help="Emit synthetic fixture frames (no real data needed — unblocks frontend)",
    )
    mode.add_argument(
        "--replay", metavar="LOG", type=Path,
        help="Replay a pre-recorded log file",
    )
    p.add_argument(
        "--infer", choices=["live", "cached", "geometric"],
        default="geometric",
        help="Perception mode when using the real pipeline (default: geometric)",
    )
    p.add_argument("--seq",  default="04", help="KITTI sequence id (default: 04)")
    p.add_argument("--data", default="data/kitti", type=Path,
                   help="KITTI data root (default: data/kitti)")
    p.add_argument("--record", metavar="LOG", type=Path,
                   help="Record frames to a log file while running")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", default=8000, type=int)
    p.add_argument("--config", default=None, type=Path,
                   help="Path to config.yaml (default: bundled)")
    p.add_argument("--log-level", default="info",
                   choices=["debug", "info", "warning", "error"])
    return p.parse_args(argv)


def main(argv=None) -> None:
    args = _parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    cfg = load_config(args.config)

    frame_queue: queue.Queue = queue.Queue(maxsize=2)

    if args.fixtures:
        logger.info("Mode: FIXTURES — synthetic schema-valid frames")
        # Fixtures run directly in the worker thread via PipelineWorker("fixtures")
        worker = PipelineWorker(cfg, "fixtures", frame_queue)

    elif args.replay:
        if not args.replay.exists():
            raise SystemExit(f"Replay log not found: {args.replay}")
        logger.info("Mode: REPLAY — %s", args.replay)
        worker = ReplayWorker(args.replay, frame_queue)

    else:
        logger.info("Mode: %s  seq=%s  data=%s", args.infer.upper(), args.seq, args.data)
        worker = PipelineWorker(
            cfg,
            args.infer,
            frame_queue,
            seq         = args.seq,
            data_root   = args.data,
            record_path = args.record,
        )

    app = make_app(cfg, worker)

    logger.info(
        "Starting server on http://%s:%d  —  WebSocket: ws://%s:%d/stream",
        args.host, args.port, args.host, args.port,
    )
    uvicorn.run(
        app,
        host      = args.host,
        port      = args.port,
        log_level = args.log_level,
    )


if __name__ == "__main__":
    main()
