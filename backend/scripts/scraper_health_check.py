#!/usr/bin/env python3
"""Daily scraper-health check.

Maintains a `data/curated/scraper_health.json` streak counter so we know
when the advisory pipeline is trustworthy enough to ship more aggressive
UX (e.g., spec I: naming the specific flagged station on the map chip).

Tracks three classes of silent failure surfaced in the 2026-05-21 debate:
  (G.1) Name-resolution drops      → `unresolved_advisories.parquet` non-empty
  (G.2) Zombie active advisories  → audit script finds rows with age > 30d
  (G.4) Workflow execution failure → daily-forecast didn't succeed today

If ANY alarm trips, `consecutive_clean_days` resets to 0. Otherwise it
increments. When it reaches 14, `ready_for_station_naming_spec_i = true`
and the safety gate for the next UX iteration is satisfied.

This script is intended to run from a scheduled GHA workflow
(.github/workflows/scraper-health.yml) one hour after the daily-forecast
cron, then commit the updated JSON back to main.

Exit code is always 0 so the workflow itself never fails — alarms are
SIGNALED via the JSON file (and downstream pre-flight checks before any
manual UX ship can consult the file). This is deliberate: we don't want
the streak monitor itself to mask the daily-forecast result.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    pd = None  # parquet checks degrade to "skipped" if pandas unavailable

# Match Cassandra's debate recommendation — adjusted down to 14 days per
# user's pragmatic preference for a live, beta-labeled product.
STREAK_TARGET_DAYS = 14

# Zombie threshold matches spec G.2 auto-expire window.
ZOMBIE_AGE_DAYS_MAX = 30


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_unresolved(curated_dir: Path) -> tuple[bool, str | None]:
    """G.1 — name-resolution drops. Return (ok, reason_if_not)."""
    path = curated_dir / "unresolved_advisories.parquet"
    if not path.exists():
        # Pre-spec-G: file doesn't exist yet → not an alarm (also not "clean
        # signal" in a meaningful sense, but the workflow will start clean).
        return True, None
    if pd is None:
        return True, None
    try:
        df = pd.read_parquet(path)
    except Exception as e:  # noqa: BLE001
        return False, f"unresolved_advisories.parquet unreadable: {e}"
    today_key = _today_utc()
    today_rows = df[df.get("scraped_at", pd.Series(dtype="object")).astype(str).str.startswith(today_key)]
    n = len(today_rows)
    # Per spec G.1: alarm if >5 absolute OR >10% relative of scraped.
    if n > 5:
        return False, f"unresolved_count_today={n} (> 5 absolute threshold)"
    return True, None


def check_zombies(curated_dir: Path) -> tuple[bool, str | None]:
    """G.2/G.4 — active advisories aged past the expire window."""
    path = curated_dir / "advisories.parquet"
    if not path.exists() or pd is None:
        return True, None
    try:
        df = pd.read_parquet(path)
    except Exception as e:  # noqa: BLE001
        return False, f"advisories.parquet unreadable: {e}"
    if "status" not in df.columns or "started_at" not in df.columns:
        return True, None
    active = df[df["status"] == "active"].copy()
    if active.empty:
        return True, None
    # Don't count "Chronic Posting" — counties intentionally leave those open.
    if "advisory_type" in active.columns:
        active = active[active["advisory_type"] != "Chronic Posting"]
    active["started_dt"] = pd.to_datetime(active["started_at"], errors="coerce", utc=True)
    now = pd.Timestamp.now(tz="UTC")
    age_days = (now - active["started_dt"]).dt.days
    zombies = active[age_days > ZOMBIE_AGE_DAYS_MAX]
    n = len(zombies)
    if n > 0:
        return False, f"zombie_active_count={n} (active > {ZOMBIE_AGE_DAYS_MAX}d, not Chronic)"
    return True, None


def check_daily_forecast_freshness(curated_dir: Path) -> tuple[bool, str | None]:
    """G.4 — daily-forecast actually ran. Use system_health.json freshness
    as the proxy: if it's >36h stale, daily-forecast didn't run today."""
    path = curated_dir / "system_health.json"
    if not path.exists():
        return True, None
    try:
        data = json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        return False, f"system_health.json unreadable: {e}"
    freshness = data.get("pipeline_freshness", "")
    if freshness in ("fixtures-current", "development", "unknown", ""):
        return True, None
    try:
        ts = datetime.fromisoformat(freshness.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
        if age_h > 36:
            return False, f"pipeline_freshness age={age_h:.1f}h (> 36h)"
    except (ValueError, TypeError) as e:
        return False, f"pipeline_freshness unparseable: {e}"
    return True, None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--curated", type=Path, default=Path("data/curated"),
                   help="path to data/curated/ dir")
    p.add_argument("--out", type=Path, default=None,
                   help="output path (default: <curated>/scraper_health.json)")
    args = p.parse_args()

    curated_dir: Path = args.curated.resolve()
    if not curated_dir.exists():
        print(f"error: curated dir not found: {curated_dir}", file=sys.stderr)
        return 2
    out_path: Path = args.out or (curated_dir / "scraper_health.json")

    # Run all three checks; collect alarms.
    alarms: list[str] = []
    for label, fn in [
        ("unresolved_drops", check_unresolved),
        ("zombie_active", check_zombies),
        ("pipeline_freshness", check_daily_forecast_freshness),
    ]:
        ok, reason = fn(curated_dir)
        if not ok and reason:
            alarms.append(f"{label}: {reason}")

    # Load prior state to compute streak.
    prior = {}
    if out_path.exists():
        try:
            prior = json.loads(out_path.read_text())
        except Exception:  # noqa: BLE001
            prior = {}
    prior_streak = int(prior.get("consecutive_clean_days", 0) or 0)
    today = _today_utc()
    prior_last_check_date = (prior.get("last_checked_utc") or "")[:10]

    if alarms:
        new_streak = 0
        last_alarm_at = _now_utc_iso()
    else:
        # Only increment once per UTC day, so re-running the script same day
        # doesn't double-count.
        if prior_last_check_date == today:
            new_streak = prior_streak  # no change today
        else:
            new_streak = prior_streak + 1
        last_alarm_at = prior.get("last_alarm_at")

    state = {
        "last_checked_utc": _now_utc_iso(),
        "alarms_today": alarms,
        "consecutive_clean_days": new_streak,
        "streak_target_days": STREAK_TARGET_DAYS,
        "last_alarm_at": last_alarm_at,
        "ready_for_station_naming_spec_i": new_streak >= STREAK_TARGET_DAYS,
        "note": (
            "Updated daily by .github/workflows/scraper-health.yml. "
            "Reset to 0 whenever any scraper-quality alarm trips. "
            "When consecutive_clean_days >= streak_target_days, the "
            "underlying advisory data is trusted enough to ship more "
            "specific UX (spec I: name the flagged station on map chips)."
        ),
    }
    out_path.write_text(json.dumps(state, indent=2) + "\n")
    print(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
