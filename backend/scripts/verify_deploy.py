"""Fail the job when the freshly committed data never reached production.

The API serves a *baked* snapshot: ``backend/Dockerfile`` COPYs ``data/curated/``
into the image, so committing fresh data to git changes NOTHING that users see
until Render finishes a new build. The daily pipeline's Render trigger is a
fire-and-forget ``curl -X POST`` against the deploy hook — the POST succeeding
only means Render *accepted* the request, not that the build shipped. A Render
build that fails (or reuses a cached ``COPY data/curated/`` layer) leaves the
previous image serving, and nothing in CI notices: the workflow is green, the
commit is in main, and the app quietly shows a day-old "last updated".

That is exactly the 2026-07-25 incident — the app read "47 hours ago" while
``forecasts.parquet`` in main was 22 h old, because the last build that actually
went live was the 2026-07-24 18:04 push deploy, which baked the 2026-07-23
forecast.

This script closes the loop: it polls the public health endpoint until the
*served* ``pipeline_freshness`` catches up to the timestamp in the local
(just-committed) ``system_health.json``, and exits non-zero if it never does —
which fails the workflow step and lets the existing ``notify-failure`` job open
the de-duped ``pipeline-failure`` issue.

Usage:
  python scripts/verify_deploy.py [--curated ../data/curated/] [--url URL]
                                  [--attempts N] [--interval SECONDS]

Exit codes:
  0  the endpoint served a snapshot at least as fresh as the local one.
  1  it never did within the polling budget, or the local/served payload could
     not be read (fail-closed — an unverifiable deploy is a failed deploy).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_HEALTH_FILE = "system_health.json"
_DEFAULT_URL = "https://surf-health-api-aabr.onrender.com/system/health"

# Sentinels written by fixtures/dev snapshots — never a real timestamp.
_SENTINELS = {"fixtures-current", "development", "unknown"}

# Clock skew / precision slack between the committed timestamp and whatever the
# served payload reports. A deploy that is a couple of seconds "behind" the file
# it was built from is still the right deploy.
_TOLERANCE_SECONDS = 5.0


def _parse_timestamp(raw: object) -> datetime | None:
    """Parse an ISO-8601 ``pipeline_freshness`` value into an aware datetime."""
    if not isinstance(raw, str) or raw in _SENTINELS:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _local_freshness(curated: Path) -> datetime:
    """Read the pipeline_freshness this run just committed. Fail-closed."""
    path = curated / _HEALTH_FILE
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: cannot read {path}: {exc}")

    freshness = _parse_timestamp(payload.get("pipeline_freshness"))
    if freshness is None:
        raise SystemExit(
            f"ERROR: {path} has no parseable pipeline_freshness "
            f"(got {payload.get('pipeline_freshness')!r}) — cannot verify the deploy."
        )
    return freshness


def _fetch_served(url: str, timeout: float) -> tuple[datetime | None, str]:
    """Return (served pipeline_freshness, human-readable status).

    A 503 is expected and retryable: the endpoint fails closed on a snapshot
    older than 36 h, which is precisely the state a stale deploy leaves behind.
    """
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200] if exc.fp else ""
        return None, f"HTTP {exc.code} {detail}".strip()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return None, f"unreachable ({exc})"

    served = _parse_timestamp(payload.get("pipeline_freshness"))
    if served is None:
        return None, f"served payload has no usable pipeline_freshness: {payload.get('pipeline_freshness')!r}"
    return served, f"serving {served.isoformat()}"


def _is_live(served: datetime | None, expected: datetime) -> bool:
    """True when the served snapshot is at least as fresh as the local one.

    ``>=`` rather than ``==``: a concurrent deploy of an even newer commit (the
    hourly closures refresh, a code push) is a perfectly good outcome — it also
    carries this run's data, because it was cut from a later commit.
    """
    if served is None:
        return False
    return (served - expected).total_seconds() >= -_TOLERANCE_SECONDS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--curated",
        type=Path,
        default=Path("../data/curated"),
        help="Curated data directory holding the just-committed system_health.json.",
    )
    parser.add_argument("--url", default=_DEFAULT_URL, help="Public health endpoint to poll.")
    parser.add_argument(
        "--attempts",
        type=int,
        default=40,
        help="Polls before giving up (default 40).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=30.0,
        help="Seconds between polls (default 30 — 40x30s = 20 min, enough for a "
        "Render image rebuild plus a free-tier cold start).",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=20.0,
        help="Per-request timeout in seconds.",
    )
    args = parser.parse_args(argv)

    expected = _local_freshness(args.curated)
    print(f"Waiting for {args.url} to serve pipeline_freshness >= {expected.isoformat()}")

    status = "no attempt made"
    served: datetime | None = None
    for attempt in range(1, args.attempts + 1):
        served, status = _fetch_served(args.url, args.request_timeout)
        if _is_live(served, expected):
            print(f"Deploy verified on attempt {attempt}/{args.attempts}: {status}")
            return 0
        print(f"Attempt {attempt}/{args.attempts}: {status} — retrying in {args.interval:.0f}s...")
        if attempt < args.attempts:
            time.sleep(args.interval)

    lag = ""
    if served is not None:
        lag_hours = (expected - served).total_seconds() / 3600
        lag = f" It is still serving a snapshot {lag_hours:.1f} h older than this run's."
    budget_min = args.attempts * args.interval / 60
    print(
        f"::error::Fresh data was committed but never went live: {args.url} did not "
        f"serve pipeline_freshness >= {expected.isoformat()} within {budget_min:.0f} min "
        f"(last status: {status}).{lag} The Render build almost certainly failed or was "
        f"never started — check the Render dashboard for this commit's deploy.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
