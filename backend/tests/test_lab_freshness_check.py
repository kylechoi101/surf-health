"""Tests for lab_freshness_check.py."""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lab_freshness_check import (  # noqa: E402
    compute_lab_freshness,
    format_freshness_table,
    update_system_health,
)


def _make_rows(county: str, dates: list[date], analyte: str = "enterococcus") -> list[dict]:
    return [
        {
            "county": county,
            "sample_date": d,
            "analyte": analyte,
            "value": 10.0,
            "beach_id": f"{county.lower()}-b1",
        }
        for d in dates
    ]


def test_synthetic_frames_fresh_stale_ineligible_steady():
    """Test 4 synthetic county frames:
    1. Fresh county: sampled weekly, newest 2 days ago (age 2 <= 21).
    2. County gone quiet: sampled frequently (cadence 1d), but stopped 30 days ago (age 30 > 14).
    3. Ineligible sparse county: only 5 distinct sample dates in trailing 365 days (< 20).
    4. Steady county with slow cadence: sampled every 14 days, newest 20 days ago (age 20 <= 42, must NOT flag).
    """
    today = date(2026, 10, 12)

    # 1. Fresh county: 25 samples, every 7 days, newest 2 days ago
    fresh_dates = [today - timedelta(days=2 + 7 * i) for i in range(25)]

    # 2. County gone quiet: 50 daily samples ending 30 days ago
    quiet_dates = [today - timedelta(days=30 + i) for i in range(50)]

    # 3. Ineligible sparse county: 5 distinct sample dates in trailing 365d
    sparse_dates = [today - timedelta(days=20 + 30 * i) for i in range(5)]

    # 4. Steady slow county: every 14 days for 25 samples (eligible: 25 in 365d), newest 20 days ago
    steady_dates = [today - timedelta(days=20 + 14 * i) for i in range(25)]

    rows = (
        _make_rows("FreshCounty", fresh_dates)
        + _make_rows("QuietCounty", quiet_dates)
        + _make_rows("SparseCounty", sparse_dates)
        + _make_rows("SteadyCounty", steady_dates)
    )
    df = pd.DataFrame(rows)

    results = compute_lab_freshness(df, today)
    by_county = {r["county"]: r for r in results}

    # 1. FreshCounty
    fc = by_county["FreshCounty"]
    assert fc["eligible"] is True
    assert fc["newest"] == str(today - timedelta(days=2))
    assert fc["age_days"] == 2
    assert fc["cadence_days"] == 7.0
    assert fc["stale"] is False
    assert "fresh" in fc["reason"]

    # 2. QuietCounty
    qc = by_county["QuietCounty"]
    assert qc["eligible"] is True
    assert qc["newest"] == str(today - timedelta(days=30))
    assert qc["age_days"] == 30
    assert qc["cadence_days"] == 1.0
    assert qc["stale"] is True
    assert "stale" in qc["reason"]

    # 3. SparseCounty
    sc = by_county["SparseCounty"]
    assert sc["eligible"] is False
    assert sc["stale"] is False
    assert "ineligible" in sc["reason"]

    # 4. SteadyCounty
    tc = by_county["SteadyCounty"]
    assert tc["eligible"] is True
    assert tc["newest"] == str(today - timedelta(days=20))
    assert tc["age_days"] == 20
    assert tc["cadence_days"] == 14.0
    # threshold = max(14, 3 * 14) = 42. age 20 <= 42 -> NOT stale!
    assert tc["stale"] is False
    assert "fresh" in tc["reason"]


def test_filters_enterococcus_only():
    """Rows for other analytes (fecal coliform, etc.) are ignored."""
    today = date(2026, 10, 12)
    # 25 enterococcus samples (quiet: stopped 30d ago)
    entero_dates = [today - timedelta(days=30 + i) for i in range(50)]
    # Fresh fecal coliform samples today
    fecal_dates = [today - timedelta(days=i) for i in range(10)]

    rows = (
        _make_rows("TestCounty", entero_dates, analyte="enterococcus")
        + _make_rows("TestCounty", fecal_dates, analyte="fecal coliform")
    )
    df = pd.DataFrame(rows)

    results = compute_lab_freshness(df, today)
    assert len(results) == 1
    tc = results[0]
    # Newest enterococcus is 30 days ago, not today's fecal sample
    assert tc["newest"] == str(today - timedelta(days=30))
    assert tc["stale"] is True


def test_format_freshness_table():
    results = [
        {
            "county": "TestCounty",
            "eligible": True,
            "newest": "2026-10-01",
            "age_days": 11,
            "cadence_days": 7.0,
            "stale": False,
            "reason": "fresh: age 11d <= 21d",
        }
    ]
    table = format_freshness_table(results)
    assert "TestCounty" in table
    assert "2026-10-01" in table
    assert "11d" in table
    assert "7.0d" in table
    assert "no" in table


def test_update_system_health_merges_without_dropping_keys(tmp_path: Path):
    curated = tmp_path / "curated"
    curated.mkdir()
    existing_health = {
        "pipeline_freshness": "2026-10-12T00:00:00Z",
        "model_registry": {"winner": "m1"},
        "scraper_gate": {"passed": True},
    }
    (curated / "system_health.json").write_text(json.dumps(existing_health))

    freshness_payload = {
        "as_of": "2026-10-12",
        "stale_count": 0,
        "counties": [],
    }
    update_system_health(curated, freshness_payload)

    loaded = json.loads((curated / "system_health.json").read_text())
    assert loaded["pipeline_freshness"] == "2026-10-12T00:00:00Z"
    assert loaded["model_registry"] == {"winner": "m1"}
    assert loaded["scraper_gate"] == {"passed": True}
    assert loaded["lab_freshness"] == freshness_payload
