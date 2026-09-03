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

Detecting the stall was not enough, which is the 2026-09-02 failure. The whole
pipeline succeeded that day — every gate passed, the forecast was committed and
pushed — and the Render build for it never shipped: all 40 polls saw the
2026-09-01 snapshot. CI then simply gave up. Nothing re-triggers a deploy for a
*data* commit (Render's hook is POSTed once, and the ``deploy-backend`` workflow
cannot help: pushes made with ``GITHUB_TOKEN`` do not fire workflows), so one
flaky build left the fresh forecast unpublished until the NEXT day's cron
happened to POST the hook again — a >24 h publication outage, long enough for
``/system/health`` to cross its 36 h fail-closed limit and 503 the whole API.

So when the served snapshot stops advancing, this script now re-POSTs the deploy
hook itself (up to ``--max-retriggers`` times) before failing. A healthy build
lands in ~2 min (measured: the 2026-09-01 run verified 20:31:47 -> 20:33:48),
so the default 5-minute stall window is ~2.5x that and safe to treat as a dead
build rather than a slow one. Re-triggering is idempotent — it rebuilds the same
commit — and if the build is failing *deterministically* the retries change
nothing and the job still goes red with the same message, now naming how many
were spent.

Usage:
  python scripts/verify_deploy.py [--curated ../data/curated/] [--url URL]
                                  [--attempts N] [--interval SECONDS]
                                  [--deploy-hook-env RENDER_DEPLOY_HOOK]
                                  [--retrigger-after N] [--max-retriggers N]

Exit codes:
  0  the endpoint served a snapshot at least as fresh as the local one.
  1  it never did within the polling budget, or the local/served payload could
     not be read (fail-closed — an unverifiable deploy is a failed deploy).
"""

from __future__ import annotations

import argparse
import json
import os
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

# Env var holding the Render deploy hook URL. It is a SECRET (possession of the
# URL is authorisation to deploy), so it is never printed — see _redact.
_HOOK_ENV_VAR = "RENDER_DEPLOY_HOOK"

# 60 x 30 s = 30 min. Was 20 min, which was already 10x a healthy build; the
# extra 10 min is headroom for the re-triggered builds below to land, and the
# daily job has ~68 min of its 170 min budget spare.
_DEFAULT_ATTEMPTS = 60

# Polls of no progress before re-POSTing the hook. 10 x 30 s = 5 min against a
# ~2 min healthy build, so this never fires on a merely slow deploy.
_DEFAULT_RETRIGGER_AFTER = 10

# Capped so a deterministically-failing build cannot spin Render forever.
_DEFAULT_MAX_RETRIGGERS = 2


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


def _redact(message: str, secret: str) -> str:
    """Strip a secret URL out of a message before it reaches the build log.

    urllib's exception strings can embed the URL they failed on, and the deploy
    hook URL is a credential — anyone holding it can deploy. Belt-and-braces:
    the hook is also never interpolated into a message deliberately.
    """
    if not secret:
        return message
    return message.replace(secret, "<deploy-hook>")


def _retrigger_deploy(hook_url: str, timeout: float) -> tuple[bool, str]:
    """Re-POST the Render deploy hook. Returns (accepted, redacted status)."""
    request = urllib.request.Request(hook_url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return True, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return False, _redact(f"HTTP {exc.code}", hook_url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, _redact(f"unreachable ({exc})", hook_url)


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
        default=_DEFAULT_ATTEMPTS,
        help=f"Polls before giving up (default {_DEFAULT_ATTEMPTS}).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=30.0,
        help=f"Seconds between polls (default 30 — {_DEFAULT_ATTEMPTS}x30s = "
        f"{_DEFAULT_ATTEMPTS // 2} min, enough for a Render image rebuild plus a "
        "free-tier cold start, plus room for a re-triggered build to land).",
    )
    parser.add_argument(
        "--deploy-hook-env",
        default=_HOOK_ENV_VAR,
        help="Env var holding the Render deploy hook URL, used to re-trigger a "
        "stalled deploy. Unset (PRs, forks, local runs) means poll-only.",
    )
    parser.add_argument(
        "--retrigger-after",
        type=int,
        default=_DEFAULT_RETRIGGER_AFTER,
        help=f"Polls with no progress before re-POSTing the deploy hook "
        f"(default {_DEFAULT_RETRIGGER_AFTER}).",
    )
    parser.add_argument(
        "--max-retriggers",
        type=int,
        default=_DEFAULT_MAX_RETRIGGERS,
        help=f"Cap on re-triggered deploys (default {_DEFAULT_MAX_RETRIGGERS}); "
        "0 restores pure detect-and-fail.",
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

    hook_url = os.environ.get(args.deploy_hook_env, "").strip()
    can_retrigger = bool(hook_url) and args.max_retriggers > 0
    if can_retrigger:
        print(
            f"A stall of {args.retrigger_after} polls will re-POST the deploy hook "
            f"(up to {args.max_retriggers}x)."
        )
    else:
        why = "no --max-retriggers budget" if hook_url else f"${args.deploy_hook_env} is unset"
        print(f"Poll-only: {why}; a stalled deploy will fail rather than be retried.")

    status = "no attempt made"
    served: datetime | None = None
    retriggers = 0
    stalled_polls = 0
    for attempt in range(1, args.attempts + 1):
        served, status = _fetch_served(args.url, args.request_timeout)
        if _is_live(served, expected):
            print(f"Deploy verified on attempt {attempt}/{args.attempts}: {status}")
            return 0
        print(f"Attempt {attempt}/{args.attempts}: {status} — retrying in {args.interval:.0f}s...")

        # Nothing is coming: a healthy build lands in ~2 min, so a stall this
        # long means the build died (or was never started) and no amount of
        # further polling will change that. Ask Render for another one — the
        # same commit, so the rebuild is idempotent.
        stalled_polls += 1
        should_retrigger = (
            can_retrigger
            and retriggers < args.max_retriggers
            and stalled_polls >= args.retrigger_after
            # Pointless on the final poll: nothing would be left to observe it.
            and attempt < args.attempts
        )
        if should_retrigger:
            accepted, detail = _retrigger_deploy(hook_url, args.request_timeout)
            retriggers += 1
            stalled_polls = 0
            verb = "re-triggered" if accepted else "FAILED to re-trigger"
            print(
                f"No progress in {args.retrigger_after} polls — {verb} the Render "
                f"deploy ({retriggers}/{args.max_retriggers}): {detail}"
            )

        if attempt < args.attempts:
            time.sleep(args.interval)

    lag = ""
    if served is not None:
        lag_hours = (expected - served).total_seconds() / 3600
        lag = f" It is still serving a snapshot {lag_hours:.1f} h older than this run's."
    budget_min = args.attempts * args.interval / 60
    if retriggers:
        remediation = (
            f" The deploy hook was re-POSTed {retriggers}x and the served snapshot still "
            f"never moved, so the build is failing repeatably rather than flaking — read "
            f"this commit's BUILD LOG in the Render dashboard."
        )
    elif can_retrigger:
        remediation = " No re-trigger was spent, so the stall was shorter than the budget."
    else:
        remediation = (
            f" Re-triggering was disabled (${args.deploy_hook_env} unset or "
            f"--max-retriggers 0) — check the Render dashboard for this commit's deploy."
        )
    print(
        f"::error::Fresh data was committed but never went live: {args.url} did not "
        f"serve pipeline_freshness >= {expected.isoformat()} within {budget_min:.0f} min "
        f"(last status: {status}).{lag}{remediation}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
