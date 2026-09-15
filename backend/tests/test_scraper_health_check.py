"""Tests for scripts/scraper_health_check.py.

The check is chained to the daily forecast's completion (workflow_run), not a
clock. Two consequences are pinned here:

- A forecast run that did not succeed is itself a G.4 alarm. The check now runs
  after EVERY completed forecast, so without this a failed day would grade
  whatever data happened to be on main and count as clean.
- A UTC day with no check at all (the forecast never fired, so nothing chained)
  breaks "consecutive" and resets the streak instead of silently bridging it.

The last test pins the workflow_run trigger to the forecast workflow's exact
`name:`. workflow_run matches by name, so a rename breaks the chain with no
error anywhere.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
WORKFLOWS = ROOT.parent / ".github" / "workflows"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import scraper_health_check as shc  # noqa: E402

NOW = datetime(2026, 9, 16, 21, 0, tzinfo=timezone.utc)


def _prior(last_checked: str, streak: int = 19) -> dict:
    return {
        "last_checked_utc": last_checked,
        "consecutive_clean_days": streak,
        "last_alarm_at": "2026-08-26T18:15:39Z",
    }


@pytest.fixture
def curated(tmp_path: Path) -> Path:
    # No parquet or system_health.json: every data check passes, isolating the
    # streak logic under test.
    return tmp_path


def test_clean_successful_forecast_on_next_day_increments(curated: Path) -> None:
    state = shc.evaluate(
        curated, _prior("2026-09-15T19:46:54Z"), forecast_conclusion="success", now=NOW
    )
    assert state["alarms_today"] == []
    assert state["consecutive_clean_days"] == 20
    assert state["last_checked_utc"] == "2026-09-16T21:00:00Z"


def test_second_check_same_utc_day_does_not_double_count(curated: Path) -> None:
    state = shc.evaluate(
        curated, _prior("2026-09-16T20:10:00Z", 20), forecast_conclusion="success", now=NOW
    )
    assert state["consecutive_clean_days"] == 20


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out"])
def test_unsuccessful_forecast_resets_streak(curated: Path, conclusion: str) -> None:
    state = shc.evaluate(
        curated, _prior("2026-09-15T19:46:54Z"), forecast_conclusion=conclusion, now=NOW
    )
    assert state["consecutive_clean_days"] == 0
    assert any(conclusion in a for a in state["alarms_today"])
    assert state["last_alarm_at"] == "2026-09-16T21:00:00Z"


@pytest.mark.parametrize("conclusion", [None, ""])
def test_manual_run_without_a_forecast_conclusion_is_not_an_alarm(
    curated: Path, conclusion: str | None
) -> None:
    state = shc.evaluate(
        curated, _prior("2026-09-15T19:46:54Z"), forecast_conclusion=conclusion, now=NOW
    )
    assert state["alarms_today"] == []
    assert state["consecutive_clean_days"] == 20


def test_utc_day_with_no_check_resets_streak(curated: Path) -> None:
    state = shc.evaluate(
        curated, _prior("2026-09-14T19:00:00Z"), forecast_conclusion="success", now=NOW
    )
    assert state["consecutive_clean_days"] == 0
    assert any("missed_check" in a for a in state["alarms_today"])


def test_first_ever_check_starts_the_streak(curated: Path) -> None:
    state = shc.evaluate(curated, {}, forecast_conclusion="success", now=NOW)
    assert state["alarms_today"] == []
    assert state["consecutive_clean_days"] == 1


def test_workflow_is_chained_to_the_forecast_by_its_exact_name() -> None:
    forecast = (WORKFLOWS / "daily-forecast.yml").read_text()
    forecast_name = re.search(r"^name:\s*(.+?)\s*$", forecast, re.M).group(1).strip("'\"")

    health = (WORKFLOWS / "scraper-health.yml").read_text()
    assert re.search(r"^\s*workflow_run:", health, re.M), "must trigger on forecast completion"
    listed = re.search(r"^\s*workflows:\s*\[([^\]]*)\]", health, re.M)
    assert listed, "workflow_run must list the upstream workflow"
    names = [n.strip().strip("'\"") for n in listed.group(1).split(",")]
    assert forecast_name in names

    # A clock trigger is exactly what raced the forecast; it must not come back.
    assert not re.search(r"^\s*schedule:", health, re.M)
