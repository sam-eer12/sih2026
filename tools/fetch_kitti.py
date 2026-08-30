#!/usr/bin/env python3
"""Fetch the SemanticKITTI subset — without downloading 84.8 GB to get 1.8 GB.

Why this is a Python script and not ``fetch_kitti.sh``
-----------------------------------------------------
KITTI publishes the odometry point clouds as **one 84.8 GB zip** covering
sequences 00–21.  There is no per-sequence download.  The plan asks for three
sequences totalling about a thousand scans, which is roughly 1.8 GB — two per
cent of the archive.

The archive is served from S3 with ``Accept-Ranges: bytes``, and a zip keeps its
central directory at the end of the file.  So: read the last few kilobytes to
find the directory, read the directory to find where each member lives, then
issue one ranged request per member we actually want.  ``zipfile`` does all the
ZIP64 parsing itself as long as it is handed a seekable file object, so the only
thing this script really provides is that object.

That is not expressible in shell, and NFR-4 requires one source tree that runs
on macOS and Windows, which a ``.sh`` does not.  Hence ``.py``.  Stdlib only —
it has to run before ``pip install -e model/``.

One thing about the archive costs real time if you do not know it: **members are
not stored in frame order.**  Within sequence 04, frame ``000000`` sits at a
higher offset than ``000007``, so extraction runs in ``header_offset`` order —
walking by filename seeks backwards on nearly every file and threw away the
read-ahead window each time, which made one benchmark transfer 912 MB to extract
114 MB.  For the same reason, asking for "the first N frames" of a long sequence
is expensive: see ``select`` and ``--sampling``.

Usage
-----
    python tools/fetch_kitti.py --dry-run          # what it would fetch, and how big
    python tools/fetch_kitti.py                    # the default subset (PRD §9.1)
    python tools/fetch_kitti.py --sequences 04     # just the smoke-test sequence
    python tools/fetch_kitti.py --sequences 00 --limit 400 --sampling contiguous

Re-running is cheap: a scan already on disk at the right size is skipped, so an
interrupted download resumes rather than restarting, and the manifest merges
across invocations.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import http.client
import io
import json
import posixpath
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

VELODYNE_URL = "https://s3.eu-central-1.amazonaws.com/avg-kitti/data_odometry_velodyne.zip"
LABELS_URL = "http://www.semantic-kitti.org/assets/data_odometry_labels.zip"
CALIB_URL = "https://s3.eu-central-1.amazonaws.com/avg-kitti/data_odometry_calib.zip"

#: PRD §9.1, plus a per-sequence sampling mode the PRD does not have and needs.
#: Sequence 04 first because it is small and proves the pipeline; 00 for dense
#: urban structure; 05 because it has the moving traffic.  ``None`` means the
#: whole sequence.  See ``select`` for what the sampling mode costs.
#:
#: Sequence 00 is sampled ``contiguous``: the accuracy set wants coverage of the
#: whole drive more than it wants 400 consecutive frames of one stretch of road,
#: and it is 4.6x cheaper to transfer.  Sequence 05 is sampled ``frames``
#: because temporal continuity is the entire point of that sequence.
DEFAULT_SUBSET: tuple[tuple[str, int | None, str], ...] = (
    ("04", None, "frames"),
    ("00", 400, "contiguous"),
    ("05", 300, "frames"),
)


def _ssl_context() -> ssl.SSLContext:
    """A context with a CA bundle that actually exists.

    The python.org macOS builds ship without a configured trust store unless
    someone runs ``Install Certificates.command``, so ``urllib`` fails with
    CERTIFICATE_VERIFY_FAILED on a machine where ``curl`` works fine.  Prefer
    ``certifi``, fall back to the system bundle, and say what to do if neither
    is there — rather than leaving a teammate to decode an SSL traceback on
    Day 1.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for bundle in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
        if Path(bundle).exists():
            return ssl.create_default_context(cafile=bundle)
    print(
        "warning: no CA bundle found. Install one with `pip install certifi`, "
        "or on macOS run Install Certificates.command from your Python "
        "installation directory.",
        file=sys.stderr,
    )
    return ssl.create_default_context()


_SSL = _ssl_context()


_MEMBER_RE = re.compile(
    r"sequences/(?P<seq>\d{2})/(?P<kind>velodyne|labels)/(?P<frame>\d{6})"
    r"\.(?P<ext>bin|label)$"
)


# ---------------------------------------------------------------------------
# A seekable file over HTTP range requests
# ---------------------------------------------------------------------------

class HTTPRangeFile(io.RawIOBase):
    """Read-only seekable file backed by HTTP ``Range`` requests.

    Hand this to ``zipfile.ZipFile`` and it will parse an 84 GB remote archive
    while transferring only the bytes it actually reads.

    Three things make this fast enough to be worth doing.  The first version of
    this file had none of them and achieved 0.10 MB/s — five hours for the
    subset — against a link that measures 1.0 MB/s on one connection.

    *Block-aligned caching.*  ``zipfile`` reads a local header, then the member
    body, in separate small reads, and the members we want are stored
    consecutively.  Reads are served from ``chunk``-sized blocks on fixed
    boundaries, so one block covers a local header, its member, and the several
    members after it.  At 8 MB that is about four KITTI scans per request.

    *A kept-alive connection per worker.*  ``urllib`` opens a fresh TCP+TLS
    connection per request; against S3 in eu-central-1 that handshake costs
    more than the megabyte it then transfers.

    *Parallel prefetch.*  S3 shapes each connection separately, so a single
    stream tops out around 1 MB/s regardless of the local link.  Reading block
    *k* queues background fetches of *k+1 … k+jobs* on their own connections,
    which hides latency and gets past the per-connection ceiling.  It is the
    same reason ``aws s3 cp`` is multipart.
    """

    def __init__(
        self,
        url: str,
        chunk: int = 8 << 20,
        timeout: float = 120.0,
        retries: int = 6,
        jobs: int = 6,
    ):
        self.chunk = chunk
        self.timeout = timeout
        self.retries = retries
        self.jobs = max(1, jobs)
        self._pos = 0
        self._last_index: int | None = None
        self.bytes_fetched = 0

        self._local = threading.local()           # one connection per worker
        self._lock = threading.Lock()
        self._blocks: dict[int, bytes] = {}        # block index -> bytes
        self._pending: dict[int, concurrent.futures.Future] = {}
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.jobs, thread_name_prefix="range"
        )

        # Resolve redirects once, then talk to the final host directly.
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
            self.url = resp.url
            self.size = int(resp.headers["Content-Length"])
            if resp.headers.get("Accept-Ranges", "").lower() != "bytes":
                raise RuntimeError(
                    f"{url} does not advertise byte ranges; the whole archive "
                    "would have to be downloaded"
                )
        parsed = urlparse(self.url)
        self._scheme = parsed.scheme
        self._host = parsed.netloc
        self._path = parsed.path + (f"?{parsed.query}" if parsed.query else "")

    # -- file protocol ----------------------------------------------------
    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        elif whence == io.SEEK_END:
            self._pos = self.size + offset
        else:
            raise ValueError(f"bad whence {whence}")
        self._pos = max(0, min(self._pos, self.size))
        return self._pos

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self._pos
        n = min(n, self.size - self._pos)
        if n <= 0:
            return b""

        out = bytearray()
        while len(out) < n:
            index = self._pos // self.chunk
            block = self._block(index)
            off = self._pos - index * self.chunk
            take = min(n - len(out), len(block) - off)
            if take <= 0:
                break
            out += block[off:off + take]
            self._pos += take
        return bytes(out)

    # -- block cache ------------------------------------------------------
    def _block(self, index: int) -> bytes:
        with self._lock:
            data = self._blocks.get(index)
            future = None if data is not None else self._pending.pop(index, None)
        if data is None:
            data = future.result() if future is not None else self._fetch_block(index)
            with self._lock:
                self._blocks[index] = data
        self._prefetch(index)
        self._evict(index)
        return data

    def _prefetch(self, index: int) -> None:
        """Queue the next few blocks so the link stays busy while we write.

        Only when the reads are actually running forward.  Prefetching after a
        seek costs a full window of wasted transfer, and ``zipfile`` seeks to
        the end of the file to find the central directory before it reads
        anything we want.
        """
        sequential = self._last_index is not None and index - self._last_index in (0, 1)
        self._last_index = index
        if not sequential:
            return
        n_blocks = (self.size + self.chunk - 1) // self.chunk
        with self._lock:
            for ahead in range(1, self.jobs + 1):
                nxt = index + ahead
                if nxt >= n_blocks or nxt in self._blocks or nxt in self._pending:
                    continue
                self._pending[nxt] = self._pool.submit(self._fetch_block, nxt)

    def _evict(self, index: int) -> None:
        """Drop blocks behind the read head; access is essentially sequential."""
        with self._lock:
            for old_index in [k for k in self._blocks if k < index]:
                del self._blocks[old_index]

    def _fetch_block(self, index: int) -> bytes:
        start = index * self.chunk
        return self._fetch(start, min(start + self.chunk, self.size))

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._drop_conn()
        super().close()

    # -- the actual transfer ----------------------------------------------
    def _conn(self) -> http.client.HTTPConnection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            if self._scheme == "https":
                conn = http.client.HTTPSConnection(
                    self._host, timeout=self.timeout, context=_SSL
                )
            else:
                conn = http.client.HTTPConnection(self._host, timeout=self.timeout)
            self._local.conn = conn
        return conn

    def _drop_conn(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
        self._local.conn = None

    def _fetch(self, start: int, stop: int) -> bytes:
        headers = {
            "Range": f"bytes={start}-{stop - 1}",
            "Connection": "keep-alive",
            "User-Agent": "avr25d-fetch-kitti/1.0",
        }
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                conn = self._conn()
                conn.request("GET", self._path, headers=headers)
                resp = conn.getresponse()
                if resp.status not in (200, 206):
                    resp.read()
                    raise RuntimeError(f"unexpected status {resp.status}")
                data = resp.read()
                if len(data) != stop - start:
                    raise RuntimeError(
                        f"short range: asked {stop - start}, got {len(data)}"
                    )
                with self._lock:
                    self.bytes_fetched += len(data)
                return data
            except (
                http.client.HTTPException, urllib.error.URLError,
                TimeoutError, RuntimeError, OSError,
            ) as exc:
                last = exc
                self._drop_conn()        # a broken connection is not reusable
                time.sleep(min(2**attempt, 20))
        raise RuntimeError(
            f"range {start}-{stop} of {self.url} failed after "
            f"{self.retries} attempts: {last}"
        )


# ---------------------------------------------------------------------------
# Planning and extraction
# ---------------------------------------------------------------------------

@dataclass
class Plan:
    """What one archive is going to give us."""

    url: str
    members: list[zipfile.ZipInfo] = field(default_factory=list)
    zf: zipfile.ZipFile | None = None
    fp: HTTPRangeFile | None = None

    @property
    def n_bytes(self) -> int:
        return sum(m.compress_size for m in self.members)


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return ""


def open_archive(
    url: str, label: str, chunk: int = 8 << 20, jobs: int = 6
) -> tuple[HTTPRangeFile, zipfile.ZipFile]:
    print(f"  reading central directory of {label} ...", end="", flush=True)
    t0 = time.perf_counter()
    fp = HTTPRangeFile(url, chunk=chunk, jobs=jobs)
    zf = zipfile.ZipFile(fp)
    print(
        f" {len(zf.namelist()):,} entries, {_human(fp.bytes_fetched)} transferred,"
        f" {time.perf_counter() - t0:.1f}s"
    )
    return fp, zf


def select(
    zf: zipfile.ZipFile,
    kind: str,
    wanted: dict[str, tuple[int | None, str]],
) -> list[zipfile.ZipInfo]:
    """Members of ``kind`` belonging to the wanted sequences.

    ``sampling`` decides *which* n scans a limit selects, and it is worth far
    more than it sounds.  KITTI's archive does not store frames in frame order:
    within sequence 04, frame 000000 sits at a higher offset than frame 000007,
    and the first 60 frames by number are scattered over 533 MB.  So

    ``frames``
        the first n frames by number, as the plan specifies.  Temporally
        consecutive, which is what a tracker or a demo replay needs — and what
        the sequence-05 subset is for.  Costs 4.4x its payload in transfer,
        because those frames are strewn across the sequence's whole region.
    ``contiguous``
        n frames adjacent *in the archive*.  Costs 1.0x — exactly its payload.
        The frames come out spread across the whole drive (for sequence 00, ids
        8 to 4524), which for a *segmentation accuracy* set is better sampling
        than 400 consecutive frames of one stretch of road, not worse.  Useless
        for tracking.

    Whole sequences are contiguous either way, so sequence 04 costs 1.0x
    regardless.
    """
    by_seq: dict[str, list[zipfile.ZipInfo]] = {s: [] for s in wanted}
    for info in zf.infolist():
        if info.is_dir():
            continue
        m = _MEMBER_RE.search(info.filename)
        if m and m.group("kind") == kind and m.group("seq") in by_seq:
            by_seq[m.group("seq")].append(info)

    out: list[zipfile.ZipInfo] = []
    for seq, (limit, sampling) in wanted.items():
        members = sorted(by_seq[seq], key=lambda i: i.filename)
        if not members:
            raise RuntimeError(
                f"sequence {seq} has no {kind} members in the archive — "
                "check the sequence id"
            )
        if limit is None:
            out.extend(members)
        elif sampling == "contiguous":
            out.extend(sorted(members, key=lambda m: m.header_offset)[:limit])
        else:
            out.extend(members[:limit])
    return out


def frame_ids(members: list[zipfile.ZipInfo]) -> list[int]:
    """Frame numbers of the selected members, ascending."""
    return sorted(int(Path(m.filename).stem) for m in members)


def extract(
    zf: zipfile.ZipFile,
    fp: HTTPRangeFile,
    members: list[zipfile.ZipInfo],
    root: Path,
    label: str,
) -> tuple[int, int]:
    """Extract members under ``root``, skipping any already the right size."""
    written = skipped = 0
    total = len(members)
    t0 = time.perf_counter()
    start_bytes = fp.bytes_fetched

    # Extract in *archive* order, not filename order.  KITTI's zip does not
    # store members alphabetically: sequence 04's frame 000000 sits at a higher
    # offset than frame 000007.  Walking them by name seeks backwards on almost
    # every file, which throws away the read-ahead window each time and made
    # this transfer 912 MB to extract 114 MB.  Sorting by header_offset makes
    # access strictly sequential.  Where the files land on disk is unaffected.
    for i, info in enumerate(sorted(members, key=lambda m: m.header_offset), 1):
        # Archive paths are 'dataset/sequences/04/velodyne/000000.bin' or
        # 'sequences/...'; keep everything from 'sequences/' onward.
        parts = posixpath.normpath(info.filename).split("/")
        rel = Path(*parts[parts.index("sequences"):])
        target = root / rel

        if target.exists() and target.stat().st_size == info.file_size:
            skipped += 1
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        with zf.open(info) as src, tmp.open("wb") as dst:
            while block := src.read(4 << 20):
                dst.write(block)
        tmp.replace(target)
        written += 1

        if written % 25 == 0 or i == total:
            moved = fp.bytes_fetched - start_bytes
            rate = moved / max(time.perf_counter() - t0, 1e-6)
            print(
                f"    {label}: {i}/{total} files, {_human(moved)} "
                f"at {_human(rate)}/s, {skipped} already present",
                flush=True,
            )
    return written, skipped


def verify(root: Path, sequences: list[str]) -> list[str]:
    """Scan and label counts must agree, or accuracy numbers are meaningless."""
    problems = []
    for seq in sequences:
        d = root / "sequences" / seq
        scans = sorted((d / "velodyne").glob("*.bin")) if (d / "velodyne").is_dir() else []
        labels = sorted((d / "labels").glob("*.label")) if (d / "labels").is_dir() else []
        if not scans:
            problems.append(f"sequence {seq}: no scans")
            continue
        scan_ids = {p.stem for p in scans}
        label_ids = {p.stem for p in labels}
        missing = scan_ids - label_ids
        if missing:
            problems.append(
                f"sequence {seq}: {len(missing)} scans without labels "
                f"(e.g. {sorted(missing)[0]})"
            )
        print(
            f"  sequence {seq}: {len(scans)} scans, {len(labels)} labels, "
            f"{_human(sum(p.stat().st_size for p in scans))}"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python tools/fetch_kitti.py",
        description=__doc__.split("Usage")[0].strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--root", default="model/data/kitti", help="output dataset root")
    ap.add_argument(
        "--sequences", nargs="*",
        help="sequence ids, e.g. 04 00 05; default is the PRD §9.1 subset",
    )
    ap.add_argument(
        "--limit", type=int,
        help="max scans per sequence (only with --sequences)",
    )
    ap.add_argument(
        "--chunk-mb", type=float, default=8.0,
        help="block size in MB; bigger means fewer round trips (default 8)",
    )
    ap.add_argument(
        "--jobs", type=int, default=6,
        help="parallel range requests. S3 shapes each connection separately, "
             "so this is what gets past the ~1 MB/s single-stream ceiling",
    )
    ap.add_argument(
        "--sampling", choices=("frames", "contiguous"), default="frames",
        help="how a --limit picks its scans: 'frames' takes the first n by "
             "frame number (temporally consecutive, needed for tracking, but "
             "~4.5x transfer amplification); 'contiguous' takes n adjacent in "
             "the archive (1.0x, spread across the whole drive, good for "
             "accuracy evaluation)",
    )
    ap.add_argument("--dry-run", action="store_true", help="plan only, fetch nothing")
    ap.add_argument("--no-calib", action="store_true")
    args = ap.parse_args(argv)

    if args.sequences:
        wanted = {s: (args.limit, args.sampling) for s in args.sequences}
    else:
        wanted = {seq: (n, mode) for seq, n, mode in DEFAULT_SUBSET}
        if args.limit is not None:
            ap.error("--limit only applies together with --sequences")

    root = Path(args.root)
    print("SemanticKITTI subset")
    print("  sequences: " + ", ".join(
        f"{s} ({'all' if n is None else f'{n} {mode}'})"
        for s, (n, mode) in wanted.items()
    ))
    print(f"  root:      {root}")
    print()

    chunk = int(args.chunk_mb * (1 << 20))
    v_fp, v_zf = open_archive(
        VELODYNE_URL, "velodyne (84.8 GB archive)", chunk, args.jobs
    )
    l_fp, l_zf = open_archive(LABELS_URL, "labels", chunk, args.jobs)

    v_members = select(v_zf, "velodyne", wanted)
    # Labels must be the *same* frames as the scans, whatever the sampling
    # picked, so they are chosen by frame id rather than re-sampled.
    chosen: dict[str, set[int]] = {}
    for m in v_members:
        chosen.setdefault(Path(m.filename).parts[-3], set()).add(
            int(Path(m.filename).stem)
        )
    l_members = [
        m for m in select(l_zf, "labels", {s: (None, "frames") for s in wanted})
        if int(Path(m.filename).stem) in chosen.get(Path(m.filename).parts[-3], ())
    ]

    print()
    print(f"  velodyne: {len(v_members):,} files, {_human(sum(m.compress_size for m in v_members))}")
    print(f"  labels:   {len(l_members):,} files, {_human(sum(m.compress_size for m in l_members))}")
    total = sum(m.compress_size for m in v_members) + sum(m.compress_size for m in l_members)
    print(f"  total to transfer: {_human(total)} "
          f"({100 * total / v_fp.size:.1f}% of the velodyne archive alone)")

    if args.dry_run:
        print("\n(dry run — nothing fetched)")
        return 0

    print()
    extract(l_zf, l_fp, l_members, root, "labels")
    extract(v_zf, v_fp, v_members, root, "velodyne")

    if not args.no_calib:
        calib = root / "data_odometry_calib.zip"
        calib.parent.mkdir(parents=True, exist_ok=True)
        if not calib.exists():
            print("\n  fetching calib (600 KB) ...")
            with urllib.request.urlopen(CALIB_URL, context=_SSL) as r:
                calib.write_bytes(r.read())
        with zipfile.ZipFile(calib) as zf:
            for info in zf.infolist():
                parts = posixpath.normpath(info.filename).split("/")
                if "sequences" not in parts or info.is_dir():
                    continue
                if parts[parts.index("sequences") + 1] not in wanted:
                    continue
                rel = Path(*parts[parts.index("sequences"):])
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_bytes(zf.read(info))

    print("\nverifying")
    # Verify every sequence on disk, not just the ones this invocation asked
    # for: fetching 00 must not quietly leave a half-downloaded 05 unchecked.
    on_disk = sorted(
        d.name for d in (root / "sequences").iterdir() if d.is_dir()
    ) if (root / "sequences").is_dir() else list(wanted)
    problems = verify(root, on_disk)

    manifest = {
        "sequences": {
            s: {"limit": n if n is not None else "all", "sampling": mode}
            for s, (n, mode) in wanted.items()
        },
        "frames": {s: sorted(f) for s, f in chosen.items()},
        "n_scans": len(v_members),
        "bytes_transferred": v_fp.bytes_fetched + l_fp.bytes_fetched,
        "velodyne_url": VELODYNE_URL,
        "labels_url": LABELS_URL,
        "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    manifest_path = root / "manifest.json"
    if manifest_path.exists():          # merge, so fetching one sequence at a
        prior = json.loads(manifest_path.read_text())   # time still records all
        manifest["sequences"] = {**prior.get("sequences", {}), **manifest["sequences"]}
        manifest["frames"] = {**prior.get("frames", {}), **manifest["frames"]}
        manifest["n_scans"] = sum(len(f) for f in manifest["frames"].values())
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print(f"  ! {p}")
        return 1
    print(f"\nok — {len(v_members)} scans, "
          f"{_human(v_fp.bytes_fetched + l_fp.bytes_fetched)} transferred")
    return 0


if __name__ == "__main__":
    sys.exit(main())
