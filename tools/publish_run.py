#!/usr/bin/env python3
"""Publish an authoritative benchmark run to MongoDB via ``/api/runs``.  FR-38.

This is the last link in the provenance chain. ``make bench-authoritative``
writes ``results.json``; this puts it behind a run id, so "where did 22.67x
come from" is answered with a URL instead of a memory.

    # 1. get an ID token and post the current results.json
    python tools/publish_run.py --email you@example.com

    # 2. or paste a token you already have (browser devtools -> getIdToken())
    python tools/publish_run.py --token eyJhbGci...

    # 3. against the deployed app rather than localhost
    python tools/publish_run.py --base-url https://avr25d.vercel.app --email ...

    # 4. see exactly what would be sent, without sending it
    python tools/publish_run.py --dry-run

**Blocked until Atlas and Firebase are live (C5, C6).**  ``--dry-run`` works
today and validates the whole payload, so the only thing waiting on Navya is
the network call itself.

Stdlib only, on purpose: this has to run on whichever machine has the fresh
``results.json``, and that machine is not guaranteed to have ``requests``.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "model" / "results.json"
CONFIG = REPO / "model" / "avr25d" / "config.yaml"

# Firebase's REST endpoint for password sign-in. The Web API key is public by
# design (it identifies the project, it does not authorise anything), so it
# lives in .env.local.example alongside the other NEXT_PUBLIC_ values.
SIGNIN_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={key}"
)


def _git_commit() -> str:
    """The short SHA the run was measured at — not today's HEAD if they differ."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO, capture_output=True, text=True, timeout=5, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def _read_env_local() -> dict[str, str]:
    """Parse frontend/.env.local for the Web API key, if it exists.

    Deliberately not a dotenv dependency: we want one key, and a five-line
    parser beats a package that has to be installed on the demo machine.
    """
    env: dict[str, str] = {}
    path = REPO / "frontend" / ".env.local"
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _post_json(url: str, payload: dict, token: str | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise SystemExit(f"HTTP {e.code} from {url}\n{detail}") from None
    except urllib.error.URLError as e:
        raise SystemExit(f"Could not reach {url}: {e.reason}") from None


def _id_token(args) -> str:
    """An ID token, however the caller wants to supply one."""
    if args.token:
        return args.token
    env_token = os.environ.get("AVR25D_ID_TOKEN")
    if env_token:
        return env_token

    api_key = args.api_key or os.environ.get("NEXT_PUBLIC_FIREBASE_API_KEY") \
        or _read_env_local().get("NEXT_PUBLIC_FIREBASE_API_KEY")
    if not api_key:
        raise SystemExit(
            "No Firebase Web API key. Set NEXT_PUBLIC_FIREBASE_API_KEY in "
            "frontend/.env.local, pass --api-key, or pass --token directly."
        )
    if not args.email:
        raise SystemExit("Pass --email (or --token) to authenticate.")

    # Never a CLI flag: a password in --password lands in the shell history.
    password = os.environ.get("AVR25D_PASSWORD") or getpass.getpass(
        f"Firebase password for {args.email}: "
    )
    out = _post_json(
        SIGNIN_URL.format(key=api_key),
        {"email": args.email, "password": password, "returnSecureToken": True},
    )
    token = out.get("idToken")
    if not token:
        raise SystemExit(f"Sign-in returned no idToken: {out}")
    return token


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://localhost:3000",
                    help="Where the Next.js app is served (default: localhost:3000)")
    ap.add_argument("--results", type=Path, default=RESULTS)
    ap.add_argument("--config", type=Path, default=CONFIG)
    ap.add_argument("--token", default=None, help="A Firebase ID token")
    ap.add_argument("--email", default=None, help="Exchange this for an ID token")
    ap.add_argument("--api-key", default=None, help="Firebase Web API key")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the payload and exit without posting")
    args = ap.parse_args(argv)

    if not args.results.is_file():
        raise SystemExit(
            f"No results at {args.results}. Run `make bench-authoritative` first."
        )
    results = json.loads(args.results.read_text(encoding="utf-8"))

    # config.yaml is shipped verbatim as text. Parsing it to a dict would need
    # PyYAML and would silently normalise comments away — and the comments are
    # where every threshold's justification lives.
    config_text = args.config.read_text(encoding="utf-8") if args.config.is_file() else None

    meta = results.get("meta", {})
    # The commit that MEASURED the run, from results.json, falling back to HEAD.
    # These differ exactly when someone benchmarks a dirty tree, which is the
    # mistake this field exists to make visible.
    commit = meta.get("git_commit") or _git_commit()
    head = _git_commit()
    if commit != head:
        print(f"  note: results.json was measured at {commit}, HEAD is {head}",
              file=sys.stderr)

    payload = {
        "startedAt": meta.get("generated") or datetime.now(timezone.utc).isoformat(),
        "finishedAt": datetime.now(timezone.utc).isoformat(),
        "gitCommit": commit,
        "platform": f"{platform.system()} {platform.release()} {platform.machine()} "
                    f"py{platform.python_version()}",
        "mode": meta.get("perception_mode", "cached"),
        "config": config_text,
        "results": results,
    }

    size_kb = len(json.dumps(payload)) / 1024
    print(f"  commit   {payload['gitCommit']}")
    print(f"  mode     {payload['mode']}")
    print(f"  platform {payload['platform']}")
    print(f"  mIoU     {results.get('accuracy', {}).get('overall', {}).get('miou')}")
    print(f"  payload  {size_kb:.1f} KB")

    if args.dry_run:
        print("  --dry-run: nothing posted")
        return 0

    url = args.base_url.rstrip("/") + "/api/runs"
    out = _post_json(url, payload, token=_id_token(args))
    run_id = out.get("id")
    print(f"\n  run id   {run_id}")
    print(f"  detail   {args.base_url.rstrip('/')}/runs/{run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
