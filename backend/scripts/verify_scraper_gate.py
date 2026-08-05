"""Fail the daily job when the advisory scraper's G.1 observability gate tripped.

Reads ``data/curated/system_health.json`` (``scraper_gate``, written by
``scripts/fetch_county_advisories.py``) and exits:

  * 0 when the gate passed — every scraped advisory resolved to a beach_id, or
    the only unresolved ones are on the known-unmapped allowlist.
  * 1 when it did not, printing every blocker, so the workflow step fails and
    the existing ``notify-failure`` job opens the de-duped ``pipeline-failure``
    issue.

Run AFTER the data commit/push step in ``.github/workflows/daily-forecast.yml``,
for the same reason ``verify_release_gate.py`` runs there: the scraper's verdict
(and the refreshed ``unresolved_advisories.parquet``) must reach the repo so the
state is auditable, and only THEN does this script's non-zero exit fail the job.

This split exists because of the 2026-08-05 outage. The scraper used to exit 1
in place, which aborted the workflow BEFORE ML training — so one unmatched beach
name (5 unresolved of 49 scraped, 10.2% against a 10% threshold) cost the day's
forecast entirely. Dropping an advisory we cannot resolve is unavoidable at that
point; also dropping the forecast is not, and the served snapshot goes stale
toward the 48h staleness cliff. Truly untrustworthy runs (mass resolution loss,
or a county that resolved yesterday and resolves nothing today) still hard-fail
inside the scraper, before training consumes ``advisory_active_prev_14d``.

Usage:
  python scripts/verify_scraper_gate.py [--curated ../data/curated/]

Exit codes:
  0  scraper_gate.passed is true.
  1  scraper_gate.passed is false, or system_health.json is missing/
     unparseable/lacks the block (fail-closed — a missing verdict means the
     scraper did not run to completion, which is itself worth alerting on).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HEALTH_FILE = "system_health.json"


def resolve_gate(payload: dict) -> tuple[bool, list[str]]:
    """Return (passed, blockers) from a system_health.json payload."""
    gate = payload.get("scraper_gate")
    if isinstance(gate, dict) and "passed" in gate:
        return bool(gate.get("passed")), list(gate.get("blockers") or [])
    return False, [
        "system_health.json carries no scraper_gate verdict — "
        "fetch_county_advisories.py did not run to completion. Failing closed."
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the advisory-scraper observability gate from system_health.json"
    )
    parser.add_argument(
        "--curated",
        default="data/curated",
        help="Path to the curated data directory holding system_health.json "
        "(default: data/curated).",
    )
    args = parser.parse_args()

    health_path = Path(args.curated) / _HEALTH_FILE
    if not health_path.exists():
        print(f"SCRAPER GATE: {health_path} not found — failing closed.", file=sys.stderr)
        return 1
    try:
        payload = json.loads(health_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"SCRAPER GATE: could not read {health_path}: {exc} — failing closed.", file=sys.stderr)
        return 1

    passed, blockers = resolve_gate(payload)
    gate = payload.get("scraper_gate") if isinstance(payload.get("scraper_gate"), dict) else {}
    if passed:
        print(
            "SCRAPER GATE PASSED: "
            f"{gate.get('unresolved_unexpected', 0)} unexpected unresolved advisories "
            f"of {gate.get('total_scraped', 0)} scraped "
            f"({gate.get('unresolved_expected', 0)} known-unmapped)."
        )
        return 0

    print("SCRAPER GATE FAILED. Blockers:", file=sys.stderr)
    if blockers:
        for blocker in blockers:
            print(f"  - {blocker}", file=sys.stderr)
    else:
        print("  - (no blocker detail recorded)", file=sys.stderr)

    for row in (gate.get("unexpected_names") or []):
        print(f"    [unresolved] {row.get('county')}: {row.get('name')}", file=sys.stderr)

    print(
        "\nThe advisories that failed to resolve were DROPPED — they are not in "
        "advisories.parquet and users did not see them. Fix by adding the beach to "
        "beaches.parquet, adding an alias row to "
        "app/data/pipeline/_static_data/county_beach_name_to_station.csv, or — only "
        "when a venue genuinely has no beach counterpart — allowlisting it in "
        "app/data/pipeline/_static_data/unmapped_advisory_venues.csv. "
        "The full history is in data/curated/unresolved_advisories.parquet.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
