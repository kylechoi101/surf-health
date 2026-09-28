"""Fail the daily job when the served estimate silently fell back to the plain lookup.

``lookup_serving`` serves the logistic model on top of the per-beach lookup and,
if anything on that path fails (a missing artifact, a coefficient guard, a dead
rain feed, the model's lookup term drifting from ``compute_lookup``), serves the
plain lookup instead so the day's forecast is never lost. That fallback is the
right call for users and the wrong one to leave silent: a schema change that
breaks the model would otherwise revert production to the lookup every day with
CI green. This script reads ``system_health.json["serving_method"]`` and exits:

  * 0 when the method that served is the one that was requested — the logistic
    model, or the lookup when ``SHORELIFE_SERVED_ESTIMATE=lookup`` asked for it.
  * 1 when "logit" was requested and the lookup served, printing the recorded
    ``fallback_reason``, or when the block is missing (fail-closed: the serving
    step did not run to completion).

Runs AFTER the commit and the Render deploy in ``daily-forecast.yml``, like
``verify_scraper_gate.py``: the fallback forecast is still a valid forecast and
must ship; this only makes sure someone is told.

Usage:
  python scripts/verify_served_estimate.py [--curated ../data/curated/]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HEALTH_FILE = "system_health.json"
LOGIT_VERSION = "logit-lookup-offset-v1"


def resolve(payload: dict) -> tuple[bool, str]:
    """Return (ok, message) from a system_health.json payload."""
    block = payload.get("serving_method")
    if not isinstance(block, dict) or "name" not in block:
        return False, (
            "system_health.json carries no serving_method block — the serving step "
            "(app.ml.lookup_serving) did not run to completion. Failing closed."
        )
    requested = block.get("method_requested", "logit")
    served = block.get("name")
    if requested == "logit" and served != LOGIT_VERSION:
        reason = block.get("fallback_reason") or "no reason recorded"
        return False, (
            f"The logistic estimate was requested but {served} served instead: {reason}. "
            "Users got the plain lookup today. Fix the cause, or set the repository "
            "variable SHORELIFE_SERVED_ESTIMATE=lookup to make the lookup deliberate."
        )
    return True, f"Served estimate OK: {served} (requested {requested})."


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the served estimate did not silently fall back")
    parser.add_argument("--curated", type=Path, default=Path("../data/curated/"))
    args = parser.parse_args()
    path = args.curated / _HEALTH_FILE
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        print(f"FAIL: cannot read {path}: {exc}", file=sys.stderr)
        return 1
    ok, message = resolve(payload)
    print(message if ok else f"FAIL: {message}", file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
