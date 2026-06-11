"""Fail the daily job when the model is NOT eligible for public release.

Reads ``data/curated/system_health.json`` (the single source of truth the ML
training step writes after its promotion assessment) and exits:

  * 0 when ``model_registry.public_release_eligible`` is true — the freshly
    trained model cleared every spatial-holdout gate and a new forecast was
    published.
  * 1 when it is false (or the file/field is missing) — printing every blocker —
    so the workflow step fails and the existing ``notify-failure`` job opens the
    de-duped ``pipeline-failure`` issue.

Run AFTER the data commit/push step in ``.github/workflows/daily-forecast.yml``:
the system_health.json update (with the blockers) must reach the repo so the
state is auditable, and only THEN does this script's non-zero exit fail the job.
``--enforce-release-gate`` on the training invocation is what skips overwriting
forecasts.parquet when ineligible, so the last-validated forecast keeps serving;
this script is the loud failure signal that the block happened.

Usage:
  python scripts/verify_release_gate.py [--curated ../data/curated/]

Exit codes:
  0  public_release_eligible is true.
  1  public_release_eligible is false, or system_health.json is missing/
     unparseable/lacks the field (fail-closed — a missing verdict is treated as
     ineligible for a public-health product).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HEALTH_FILE = "system_health.json"


def _resolve_eligibility(payload: dict) -> tuple[bool, list[str]]:
    """Return (eligible, blockers) from a system_health.json payload.

    Prefers the dedicated ``release_gate`` block the training step writes; falls
    back to ``model_registry`` for older payloads. Fail-closed: when neither
    carries an explicit verdict, treat the model as ineligible.
    """
    release_gate = payload.get("release_gate")
    if isinstance(release_gate, dict) and "public_release_eligible" in release_gate:
        eligible = bool(release_gate.get("public_release_eligible"))
        blockers = list(release_gate.get("blockers") or [])
        return eligible, blockers

    registry = payload.get("model_registry")
    if isinstance(registry, dict) and "public_release_eligible" in registry:
        eligible = bool(registry.get("public_release_eligible"))
        blockers = list(registry.get("promotion_blockers") or [])
        return eligible, blockers

    return False, [
        "system_health.json carries no public_release_eligible verdict "
        "(neither release_gate nor model_registry) — failing closed."
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the public-release gate from system_health.json")
    parser.add_argument(
        "--curated",
        default="data/curated",
        help="Path to the curated data directory holding system_health.json "
        "(default: data/curated).",
    )
    args = parser.parse_args()

    health_path = Path(args.curated) / _HEALTH_FILE
    if not health_path.exists():
        print(f"RELEASE GATE: {health_path} not found — failing closed.", file=sys.stderr)
        return 1
    try:
        payload = json.loads(health_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"RELEASE GATE: could not read {health_path}: {exc} — failing closed.", file=sys.stderr)
        return 1

    eligible, blockers = _resolve_eligibility(payload)
    if eligible:
        print("RELEASE GATE PASSED: public_release_eligible=true. Forecast published.")
        return 0

    print("RELEASE GATE FAILED: public_release_eligible=false. Blockers:", file=sys.stderr)
    if blockers:
        for blocker in blockers:
            print(f"  - {blocker}", file=sys.stderr)
    else:
        print("  - (no blocker detail recorded)", file=sys.stderr)
    print(
        "\nforecasts.parquet was NOT overwritten — the last-validated forecast "
        "keeps serving. Inspect the training logs, fix the spatial-holdout "
        "regression, and re-run before re-promoting.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
