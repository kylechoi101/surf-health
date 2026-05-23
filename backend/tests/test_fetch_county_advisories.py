"""Tests for the scraper observability + precedence rules (G.1, G.3).

The scraper has historically had two pain points:
  - silent name-resolution drops (e.g. "Salt Creek" vanishing when OC
    changed its naming format) that the audit script catches months later.
  - state-CSV records winning over fresher county-scraper records when
    the county scraper resolves a beach_id (Doheny San Juan Creek case).

These tests pin down both behaviors.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from fetch_county_advisories import (  # noqa: E402
    CountyAdvisory,
    CountyReport,
    StationResolver,
    _UNRESOLVED_ABSOLUTE_FLOOR,
    _UNRESOLVED_PARQUET,
    _UNRESOLVED_RATIO_THRESHOLD,
    merge_and_rebuild,
    persist_unresolved,
    resolve_advisories,
)


def _make_beaches() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "beach_id": "ca001-orange-doheny-state-beach-san-juan-creek",
                "name": "San Juan Creek",
                "beach_name": "Doheny State Beach",
                "county": "Orange",
                "region": "South",
                "station_code": "OC-DOH-01",
                "support_status": "production",
                "latitude": 33.46,
                "longitude": -117.69,
                "latest_official_sample_at": "2026-05-18T08:00:00",
            },
            {
                "beach_id": "ca002-orange-newport-beach",
                "name": "Newport Pier",
                "beach_name": "Newport Beach",
                "county": "Orange",
                "region": "South",
                "station_code": "OC-NB-01",
                "support_status": "production",
                "latitude": 33.60,
                "longitude": -117.93,
                "latest_official_sample_at": "2026-05-18T08:00:00",
            },
        ]
    )


def test_resolve_advisories_captures_unresolved_into_sink():
    """G.1: every advisory we cannot resolve to a known beach_id must land
    in the unresolved sink so the workflow can report+gate on it."""
    beaches = _make_beaches()
    resolver = StationResolver(beaches)
    sink: list[dict] = []
    rpt = CountyReport(
        county="Orange",
        success=True,
        last_attempted_at="2026-05-18T16:00:00Z",
        source_url="https://example.test",
    )
    advisories = [
        CountyAdvisory(
            county="Orange",
            station_code=None,
            area="Salt Creek",  # not in roster — should land in sink
            advisory_type="Posting",
            started_at=pd.Timestamp("2026-05-18"),
            advisory_website="https://example.test",
        ),
        CountyAdvisory(
            county="Orange",
            station_code="OC-NB-01",  # resolves
            area="Newport Pier",
            advisory_type="Posting",
            started_at=pd.Timestamp("2026-05-18"),
            advisory_website="https://example.test",
        ),
    ]
    resolved = resolve_advisories(advisories, resolver, rpt, unresolved_sink=sink)
    assert len(resolved) == 1
    assert resolved[0].beach_id == "ca002-orange-newport-beach"
    assert len(sink) == 1
    row = sink[0]
    assert row["source_county"] == "Orange"
    assert row["scraped_name"] == "Salt Creek"
    assert row["scraped_date"] == pd.Timestamp("2026-05-18")


def test_persist_unresolved_appends_to_parquet(tmp_path):
    rows = [
        {
            "source_county": "Orange",
            "scraped_name": "Salt Creek",
            "scraped_date": pd.Timestamp("2026-05-18"),
            "scraped_at": pd.Timestamp("2026-05-18T16:00:00"),
        }
    ]
    n = persist_unresolved(rows, tmp_path)
    assert n == 1
    parquet_path = tmp_path / _UNRESOLVED_PARQUET
    assert parquet_path.exists()
    df = pd.read_parquet(parquet_path)
    assert len(df) == 1

    # Appending should add to existing rows, not replace
    more = [
        {
            "source_county": "San Diego",
            "scraped_name": "Mystery Beach",
            "scraped_date": pd.Timestamp("2026-05-19"),
            "scraped_at": pd.Timestamp("2026-05-19T16:00:00"),
        }
    ]
    persist_unresolved(more, tmp_path)
    df2 = pd.read_parquet(parquet_path)
    assert len(df2) == 2


def _write_minimal_curated(curated: Path) -> None:
    """Make a curated dir with just enough parquets for the script to run end-to-end."""
    curated.mkdir(parents=True, exist_ok=True)
    _make_beaches().to_parquet(curated / "beaches.parquet", index=False)
    # advisories.parquet (state-feed) — empty schema is fine
    pd.DataFrame(
        columns=[
            "beach_id", "advisory_type", "started_at", "ended_at",
            "status", "cause", "county", "advisory_website",
        ]
    ).to_parquet(curated / "advisories.parquet", index=False)


def test_main_exits_one_when_unresolved_exceeds_absolute_floor(tmp_path, monkeypatch):
    """G.1: when more than the absolute floor of advisories fail resolution,
    main() must exit non-zero. We stub the per-county fetcher to emit
    UNRESOLVED rows so the gate trips."""
    curated = tmp_path / "curated"
    _write_minimal_curated(curated)

    # Replace the first-class fetcher list with a single stub that emits
    # six unresolvable rows. Six > 5 (the absolute floor) so the gate
    # MUST trip independent of the relative ratio.
    from fetch_county_advisories import CountyReport as _Report

    def _stub_fetch(client, resolver):
        rpt = _Report(
            county="Orange",
            success=True,
            last_attempted_at="2026-05-18T16:00:00Z",
            source_url="https://example.test",
        )
        advs = [
            CountyAdvisory(
                county="Orange",
                station_code=None,
                area=f"Unknown Beach #{i}",
                advisory_type="Posting",
                started_at=pd.Timestamp("2026-05-18"),
                advisory_website="https://example.test",
            )
            for i in range(_UNRESOLVED_ABSOLUTE_FLOOR + 1)
        ]
        return advs, rpt

    import fetch_county_advisories as fca
    monkeypatch.setattr(fca, "COUNTIES_FIRST_CLASS", [("Orange", _stub_fetch)])
    monkeypatch.setattr(fca, "BEST_EFFORT_COUNTIES", {})

    # Patch sys.argv so main()'s argparser sees our curated dir
    monkeypatch.setattr(sys, "argv", ["fetch_county_advisories.py", "--curated", str(curated)])

    rc = fca.main()
    assert rc == 1, "expected main() to exit 1 when unresolved_count > absolute floor"

    parquet_path = curated / _UNRESOLVED_PARQUET
    assert parquet_path.exists()
    df = pd.read_parquet(parquet_path)
    assert len(df) == _UNRESOLVED_ABSOLUTE_FLOOR + 1


def test_main_exits_zero_when_all_resolved(tmp_path, monkeypatch):
    """Happy path: every advisory resolves, no gate trip, main returns 0."""
    curated = tmp_path / "curated"
    _write_minimal_curated(curated)

    def _stub_fetch(client, resolver):
        rpt = CountyReport(
            county="Orange",
            success=True,
            last_attempted_at="2026-05-18T16:00:00Z",
            source_url="https://example.test",
        )
        advs = [
            CountyAdvisory(
                county="Orange",
                station_code="OC-NB-01",
                area="Newport Pier",
                advisory_type="Posting",
                started_at=pd.Timestamp("2026-05-18"),
                advisory_website="https://example.test",
            ),
        ]
        return advs, rpt

    import fetch_county_advisories as fca
    monkeypatch.setattr(fca, "COUNTIES_FIRST_CLASS", [("Orange", _stub_fetch)])
    monkeypatch.setattr(fca, "BEST_EFFORT_COUNTIES", {})
    monkeypatch.setattr(sys, "argv", ["fetch_county_advisories.py", "--curated", str(curated)])

    rc = fca.main()
    assert rc == 0


def test_main_exits_one_on_ratio_threshold(tmp_path, monkeypatch):
    """G.1: ratio threshold trips even when absolute count is small.
    With 1 unresolved out of 2 scraped (50% > 10%) the gate must fail."""
    curated = tmp_path / "curated"
    _write_minimal_curated(curated)

    # Use 2 advisories where 1 resolves and 1 doesn't -> 50% unresolved.
    # The absolute floor is _UNRESOLVED_ABSOLUTE_FLOOR (=5), so this gate
    # ONLY trips via the ratio threshold.
    assert _UNRESOLVED_RATIO_THRESHOLD < 0.5  # sanity

    def _stub_fetch(client, resolver):
        rpt = CountyReport(
            county="Orange",
            success=True,
            last_attempted_at="2026-05-18T16:00:00Z",
            source_url="https://example.test",
        )
        return [
            CountyAdvisory(
                county="Orange",
                station_code="OC-NB-01",
                area="Newport Pier",
                advisory_type="Posting",
                started_at=pd.Timestamp("2026-05-18"),
                advisory_website="https://example.test",
            ),
            CountyAdvisory(
                county="Orange",
                station_code=None,
                area="Bigfoot Cove",
                advisory_type="Posting",
                started_at=pd.Timestamp("2026-05-18"),
                advisory_website="https://example.test",
            ),
        ], rpt

    import fetch_county_advisories as fca
    monkeypatch.setattr(fca, "COUNTIES_FIRST_CLASS", [("Orange", _stub_fetch)])
    monkeypatch.setattr(fca, "BEST_EFFORT_COUNTIES", {})
    monkeypatch.setattr(sys, "argv", ["fetch_county_advisories.py", "--curated", str(curated)])

    rc = fca.main()
    assert rc == 1, "expected ratio-based G.1 gate to trip at 50% unresolved"


def test_merge_and_rebuild_scraper_wins_over_state_csv(tmp_path):
    """G.3: when the county scraper produces an active record for a beach,
    that record must win over a stale state-CSV record for the same
    beach_id. Concretely: state CSV says Doheny is active with cause
    'Foo' since 2026-04-01; scraper says Doheny is Closure with cause
    'Tijuana' since 2026-05-18. Result must be a single active row
    sourced from the scraper.
    """
    curated = tmp_path / "curated"
    curated.mkdir()
    doheny = "ca001-orange-doheny-state-beach-san-juan-creek"
    state_feed = pd.DataFrame(
        [
            {
                "beach_id": doheny,
                "advisory_type": "Posting",
                "started_at": pd.Timestamp("2026-04-01"),
                "ended_at": pd.NaT,
                "status": "active",
                "cause": "STALE_STATE_CAUSE",
                "county": "Orange",
                "advisory_website": "https://state.example",
            }
        ]
    )
    state_feed.to_parquet(curated / "advisories.parquet", index=False)

    scraper_row = CountyAdvisory(
        county="Orange",
        station_code="OC-DOH-01",
        area="Doheny State Beach",
        advisory_type="Closure",
        started_at=pd.Timestamp("2026-05-18"),
        advisory_website="https://ocbeachinfo.com",
        cause="FRESH_SCRAPER_CAUSE",
        beach_id=doheny,
    )

    added, demoted = merge_and_rebuild(
        [scraper_row],
        curated,
        rebuild_beach_day=False,
        authoritative_counties={"Orange"},
    )
    assert added == 1
    assert demoted == 1

    result = pd.read_parquet(curated / "advisories.parquet")
    doheny_rows = result[result["beach_id"] == doheny]
    # Exactly one row for Doheny in the final advisories.parquet — the scraper's.
    assert len(doheny_rows) == 1
    row = doheny_rows.iloc[0]
    assert row["status"] == "active"
    assert row["cause"] == "FRESH_SCRAPER_CAUSE"
    assert row["advisory_type"] == "Closure"
    assert row["advisory_website"] == "https://ocbeachinfo.com"


def test_merge_and_rebuild_preserves_state_csv_active_when_scraper_silent(tmp_path):
    """Health-safety conservatism (2026-05-23): scraper silence ≠ no advisory.

    When the OC scraper runs successfully but doesn't enumerate Newport,
    a stale state-CSV Newport active record is PRESERVED, NOT demoted.
    The county website may be lagging the State board's update (e.g.
    Tourmaline FM-030 was cleared on sdbeachinfo.com but still flagged by
    the State board the same day). Under-warning on a health app is a
    worse failure mode than over-warning, so we keep the State board's
    signal.

    Stale state-feed cruft is bounded by:
      - G.2 auto-expire (14-day age cap, non-Chronic),
      - state CSV refreshes (next pull may drop the row),
      - the audit gate (>30d zombies fail the workflow).
    """
    curated = tmp_path / "curated"
    curated.mkdir()
    newport = "ca002-orange-newport-beach"
    state_feed = pd.DataFrame(
        [
            {
                "beach_id": newport,
                "advisory_type": "Posting",
                "started_at": pd.Timestamp("2024-01-01"),  # 1+ year stale
                "ended_at": pd.NaT,
                "status": "active",
                "cause": "STALE",
                "county": "Orange",
                "advisory_website": "https://state.example",
            }
        ]
    )
    state_feed.to_parquet(curated / "advisories.parquet", index=False)

    added, demoted = merge_and_rebuild(
        [],  # no scraper advisories at all (all-clear case)
        curated,
        rebuild_beach_day=False,
        authoritative_counties={"Orange"},
    )
    assert added == 0
    assert demoted == 0  # scraper-silence no longer demotes; G.2 handles aging
    result = pd.read_parquet(curated / "advisories.parquet")
    assert (result["status"] == "active").sum() == 1  # state-CSV row survives
