"""FrameHub — frame fan-out to every connected client.

The rest of ``server/`` is covered; this piece was not, and it is the piece
that broke the demo twice.  The bug it exists to prevent: every WebSocket
handler used to *consume* from the one shared ``queue.Queue``, so a frame
taken by one connection was gone for the others.  One handler won the race
consistently and the rest received nothing at all — measured at 0 frames/s
for a second client.  A browser refresh lands exactly there, because the new
socket opens beside the old one.

``pytest-asyncio`` is not a dependency and the sprint is past the point of
adding one, so each test drives its own loop with ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import queue

import pytest

from avr25d.server.app import FrameHub


def _run(coro_fn):
    """Run an async test body on a fresh loop."""
    return asyncio.run(coro_fn())


def _hub_with(*payloads: bytes) -> tuple[FrameHub, queue.Queue]:
    source: queue.Queue = queue.Queue(maxsize=8)
    for p in payloads:
        source.put(p)
    return FrameHub(source), source


# ---------------------------------------------------------------------------
# Fan-out — the regression this file exists for
# ---------------------------------------------------------------------------

def test_two_readers_both_see_every_frame():
    """The bug: one connection consumed the frame and the other got nothing."""

    async def body():
        hub, source = _hub_with()
        hub.start()
        try:
            got_a: list[bytes] = []
            got_b: list[bytes] = []

            async def reader(sink: list[bytes], n: int) -> None:
                seen = 0
                for _ in range(n):
                    await hub.wait_for_new(seen)
                    seen, payload = hub.latest()
                    sink.append(payload)

            task_a = asyncio.create_task(reader(got_a, 3))
            task_b = asyncio.create_task(reader(got_b, 3))

            for i in range(3):
                source.put(f"frame-{i}".encode())
                await asyncio.sleep(0.05)

            await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=5.0)

            assert got_a == [b"frame-0", b"frame-1", b"frame-2"]
            assert got_b == got_a, "both connections must see the same frames"
        finally:
            await hub.stop()

    _run(body)


def test_a_reader_that_never_reads_does_not_starve_another():
    """A stalled connection must not hold frames away from a live one."""

    async def body():
        hub, source = _hub_with()
        hub.start()
        try:
            # This one subscribes and then never comes back — a wedged client.
            stalled = asyncio.create_task(hub.wait_for_new(0))
            await asyncio.sleep(0.02)

            seen = 0
            received = []
            for i in range(3):
                source.put(f"live-{i}".encode())
                await asyncio.wait_for(hub.wait_for_new(seen), timeout=2.0)
                seen, payload = hub.latest()
                received.append(payload)

            assert received == [b"live-0", b"live-1", b"live-2"]
            stalled.cancel()
        finally:
            await hub.stop()

    _run(body)


# ---------------------------------------------------------------------------
# Drop, never queue (NFR-1) — now per connection
# ---------------------------------------------------------------------------

def test_a_slow_reader_skips_frames_rather_than_queueing_them():
    """Degrade in frame rate, never in latency: the slow reader gets the newest."""

    async def body():
        hub, source = _hub_with()
        hub.start()
        try:
            for i in range(10):
                source.put(f"frame-{i}".encode())
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)

            # A reader arriving now must get the LATEST frame, not the oldest
            # one still sitting in a backlog.
            await asyncio.wait_for(hub.wait_for_new(0), timeout=2.0)
            version, payload = hub.latest()
            assert payload == b"frame-9", "a late reader gets the newest frame"
            assert version == 10, "every frame advanced the version"
        finally:
            await hub.stop()

    _run(body)


def test_version_advances_once_per_frame():
    async def body():
        hub, source = _hub_with()
        hub.start()
        try:
            assert hub.version == 0, "no frames published yet"
            for i in range(4):
                source.put(b"x")
                await asyncio.sleep(0.03)
            assert hub.version == 4
        finally:
            await hub.stop()

    _run(body)


# ---------------------------------------------------------------------------
# Waiting
# ---------------------------------------------------------------------------

def test_wait_returns_immediately_when_a_newer_frame_already_exists():
    """A handler that has just finished sending must not wait a whole period.

    Pushing into a one-slot mailbox per connection did exactly that and cost
    two thirds of the throughput — 8 fps against 26 — because the mailbox was
    empty at precisely the moment a handler came free.
    """

    async def body():
        hub, source = _hub_with()
        hub.start()
        try:
            source.put(b"first")
            await asyncio.sleep(0.05)

            # Caller has seen nothing; a frame exists; this must not block.
            await asyncio.wait_for(hub.wait_for_new(0), timeout=0.05)
            assert hub.latest()[1] == b"first"
        finally:
            await hub.stop()

    _run(body)


def test_a_timed_out_waiter_is_not_left_behind():
    """Keepalives time out constantly; leaked futures would grow without bound."""

    async def body():
        hub, _source = _hub_with()
        hub.start()
        try:
            for _ in range(5):
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(hub.wait_for_new(hub.version), timeout=0.02)
            assert hub._waiters == [], "cancelled waiters must be removed"
        finally:
            await hub.stop()

    _run(body)


def test_stop_is_safe_and_idempotent():
    async def body():
        hub, _source = _hub_with()
        hub.start()
        await hub.stop()
        await hub.stop()          # must not raise on an already-stopped hub

    _run(body)


def test_stop_without_start_is_safe():
    async def body():
        hub, _source = _hub_with()
        await hub.stop()

    _run(body)
