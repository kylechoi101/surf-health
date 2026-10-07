"""Tests for Monterey County beach sample scraper and parser."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx
import pandas as pd

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fetch_county_advisories as f  # noqa: E402
from app.data.pipeline.county_direct import (  # noqa: E402
    DATA_SOURCE,
    INGEST_COUNTIES,
    merge_county_direct_into_observations,
    normalize_county_direct_samples,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "county_scrapers" / "monterey"


def test_monterey_station_map():
    """Monterey station map hard-codes 8 county pages to station_code."""
    expected = {
        "sunset": "SDA",
        "spanish_bay": "SPB",
        "lovers_point": "LOP",
        "san_carlos": "SCB",
        "del_monte": "DMB",
        "monterey_state_beach": "MBH",
        "stillwater_cove": "STCO",
        "carmel": "CBOA",
    }
    assert f.MONTEREY_PAGES == expected
    assert not hasattr(f, "MONTEREY_STATIONS")
    assert not hasattr(f, "MONTEREY_PAGE_TO_STATION")


def test_monterey_broken_header_case_yields_5_dates():
    """FrontPage HTML broken header markup (<FONT </td>) swallows a date cell for
    standard HTML table parsers, but regex over Analysis Name -> Single Sample
    yields all 5 sampling dates."""
    sunset_path = FIXTURES_DIR / "sunset.htm"
    html = sunset_path.read_text(encoding="cp1252")

    # A standard HTMLParser on header row finds only 4 date cells because of broken markup
    table_parser = f._MontereyHTMLParser()
    table_parser.feed(html)
    header_row = table_parser.rows[0]

    date_cells = [c for c in header_row if re.match(r"^\d{1,2}/\d{1,2}/20\d\d$", c)]
    assert len(date_cells) == 4
    assert date_cells == ["9/9/2026", "9/16/2026", "9/22/2026", "9/29/2026"]

    # _monterey_parse_page uses regex over header chunk and yields 5 dates per analyte
    readings = f._monterey_parse_page(html)
    entero_readings = [r for r in readings if r.analyte == "ENTEROCOCCUS"]
    assert len(entero_readings) == 5
    unique_dates = sorted({r.sample_date for r in entero_readings})
    assert len(unique_dates) == 5
    # Total readings: 5 dates * 3 analytes = 15
    assert len(readings) == 15


def test_monterey_qualifiers_and_skips():
    """<10 and ND is non-detect -> 10.0; >, >=, = qualifiers are stripped; non-numeric cells are skipped."""
    # Non-detect <10 -> 10.0
    assert f._monterey_parse_value("<10") == 10.0
    assert f._monterey_parse_value(" <10 ") == 10.0

    # Non-detect ND -> 10.0 (case-insensitive)
    assert f._monterey_parse_value("ND") == 10.0
    assert f._monterey_parse_value("nd") == 10.0
    assert f._monterey_parse_value("Nd") == 10.0
    assert f._monterey_parse_value(" ND ") == 10.0

    # Leading qualifiers stripped
    assert f._monterey_parse_value(">63") == 63.0
    assert f._monterey_parse_value("=10") == 10.0
    assert f._monterey_parse_value(">=10") == 10.0
    assert f._monterey_parse_value(">1421") == 1421.0
    assert f._monterey_parse_value("10") == 10.0
    assert f._monterey_parse_value("691") == 691.0

    # Non-numeric cells skipped
    assert f._monterey_parse_value("Not Sampled") is None
    assert f._monterey_parse_value("Data Missing") is None
    assert f._monterey_parse_value("NA") is None
    assert f._monterey_parse_value("N/A") is None
    assert f._monterey_parse_value("") is None
    assert f._monterey_parse_value("   ") is None


def test_monterey_date_offset_minus_one_day():
    """Page date = sample date + 1 day, so stored sample_date = page date - 1 day."""
    snippet = """
    <table>
      <tr>
        <td>Analysis Name</td>
        <td>10/6/2026</td>
        <td>Single Sample</td>
      </tr>
      <tr>
        <td>Enterococcus</td>
        <td>10</td>
      </tr>
    </table>
    """
    readings = f._monterey_parse_page(snippet)
    assert len(readings) == 1
    # Page date 10/6/2026 -> sample_date 2026-10-05
    assert readings[0].sample_date == pd.Timestamp("2026-10-05")
    assert readings[0].analyte == "ENTEROCOCCUS"
    assert readings[0].value == 10.0


def test_monterey_19_value_mirror_table():
    """Verify the 19 of 19 enterococcus values and -1 day dates against state records across Oct-2025 fixtures."""
    expected_mirror = {
        "sunset": {
            "dates": ["2025-09-18", "2025-09-29", "2025-10-06", "2025-10-17", "2025-10-20"],
            "values": [10.0, 10.0, 63.0, 10.0, 10.0],
        },
        "spanish_bay": {
            "dates": ["2025-09-18", "2025-09-29", "2025-10-06", "2025-10-17", "2025-10-20"],
            "values": [10.0, 10.0, 10.0, 10.0, 10.0],
        },
        "san_carlos": {
            # 9/23 is 'Data Missing' and skipped
            "dates": ["2025-09-29", "2025-10-06", "2025-10-17", "2025-10-20"],
            "values": [41.0, 20.0, 10.0, 691.0],
        },
        "monterey_state_beach": {
            "dates": ["2025-09-18", "2025-09-29", "2025-10-06", "2025-10-17", "2025-10-20"],
            "values": [10.0, 10.0, 20.0, 10.0, 62.0],
        },
    }

    total_values = 0
    for page_name, exp in expected_mirror.items():
        fixture_file = FIXTURES_DIR / "2025-10" / f"{page_name}.htm"
        html = fixture_file.read_text(encoding="cp1252")
        readings = [r for r in f._monterey_parse_page(html) if r.analyte == "ENTEROCOCCUS"]
        actual_dates = [r.sample_date.strftime("%Y-%m-%d") for r in readings]
        actual_values = [r.value for r in readings]
        assert actual_dates == exp["dates"], f"Date mismatch for {page_name}"
        assert actual_values == exp["values"], f"Value mismatch for {page_name}"
        total_values += len(readings)

    # 5 + 5 + 4 + 5 = 19 values
    assert total_values == 19


def test_monterey_parser_every_fixture():
    """Verify parser runs cleanly on every fixture file in test directory."""
    fixtures = sorted(FIXTURES_DIR.glob("**/*.htm"))
    # index.htm is directory index, not a beach page
    beach_fixtures = [p for p in fixtures if p.name != "index.htm"]
    assert len(beach_fixtures) == 12  # 8 current + 4 in 2025-10

    for path in beach_fixtures:
        html = path.read_text(encoding="cp1252")
        readings = f._monterey_parse_page(html)

        if path.parent.name == "monterey" and path.name == "san_carlos.htm":
            # Current san_carlos fixture is 'Not Sampled' on all dates
            assert len(readings) == 0
            continue

        # All other fixtures contain 5 sampling dates across 3 analytes
        assert len(readings) in (13, 15)  # 2025-10 san_carlos has 13 (missing 2 cells)
        for r in readings:
            assert isinstance(r.sample_date, pd.Timestamp)
            assert r.analyte in {"ENTEROCOCCUS", "FECAL_COLIFORM", "TOTAL_COLIFORM"}
            assert isinstance(r.value, float)
            assert r.value >= 0


def test_monterey_spanish_bay_current_dates():
    """Verify spanish_bay current fixture has dates 9/16, 9/22, 9/23, 9/29, 10/6/2026."""
    html = (FIXTURES_DIR / "spanish_bay.htm").read_text(encoding="cp1252")
    readings = [r for r in f._monterey_parse_page(html) if r.analyte == "ENTEROCOCCUS"]
    actual_dates = [r.sample_date.strftime("%Y-%m-%d") for r in readings]
    expected_sample_dates = ["2026-09-15", "2026-09-21", "2026-09-22", "2026-09-28", "2026-10-05"]
    assert actual_dates == expected_sample_dates


def test_monterey_parse_page_empty_or_malformed():
    """Malformed or missing table returns empty list, never raises."""
    assert f._monterey_parse_page("") == []
    assert f._monterey_parse_page("<html><body>no table here</body></html>") == []
    assert f._monterey_parse_page("Analysis Name without dates Single Sample") == []


def test_monterey_nd_in_page():
    """Verify ND (any case) in HTML table is parsed as 10.0, same as <10."""
    snippet = """
    <table>
      <tr>
        <td>Analysis Name</td>
        <td>10/6/2026</td>
        <td>Single Sample</td>
      </tr>
      <tr>
        <td>Enterococcus</td>
        <td>ND</td>
      </tr>
      <tr>
        <td>Fecal coliform</td>
        <td>nd</td>
      </tr>
    </table>
    """
    readings = f._monterey_parse_page(snippet)
    assert len(readings) == 2
    assert readings[0].analyte == "ENTEROCOCCUS"
    assert readings[0].value == 10.0
    assert readings[1].analyte == "FECAL_COLIFORM"
    assert readings[1].value == 10.0


def test_monterey_not_in_no_source_counties():
    """Monterey is no longer in NO_SOURCE_COUNTIES."""
    assert "Monterey" not in f.NO_SOURCE_COUNTIES


def test_fetch_monterey_samples_fake_client_partial_404():
    """Fake client where one page returns 404: others are still collected, never raises."""
    f._COLLECTED_SAMPLES.clear()

    beaches_path = Path(__file__).resolve().parent.parent.parent / "data" / "curated" / "beaches.parquet"
    resolver = f.StationResolver(pd.read_parquet(beaches_path))

    class FakeClient:
        def get(self, url: str, headers=None, timeout=None):
            # simulate 404 for carmel
            if "carmel.htm" in url:
                req = httpx.Request("GET", url)
                resp = httpx.Response(404, request=req)
                resp.raise_for_status()
            for slug in f.MONTEREY_PAGES:
                if f"{slug}.htm" in url:
                    fixture = FIXTURES_DIR / f"{slug}.htm"
                    req = httpx.Request("GET", url)
                    return httpx.Response(200, content=fixture.read_bytes(), request=req)
            req = httpx.Request("GET", url)
            return httpx.Response(404, request=req)

    count = f.fetch_monterey_samples(FakeClient(), resolver)
    assert count > 0

    collected = [s for s in f._COLLECTED_SAMPLES if s.county == "Monterey"]
    assert len(collected) == count
    # Carmel was 404 so its station CBOA must not be in collected stations
    stations = {s.station_code for s in collected}
    assert "CBOA" not in stations
    # Other stations should be present (san_carlos current fixture is Not Sampled, so remaining 6 stations)
    assert len(stations) == 6

    # Verify properties of CountySample
    for s in collected:
        assert s.county == "Monterey"
        assert s.area == s.station_code
        assert s.beach_id is not None
        assert s.source_url.startswith(f.MONTEREY_BASE_URL)
        assert isinstance(s.sample_date, pd.Timestamp)
        assert s.analyte in {"ENTEROCOCCUS", "FECAL_COLIFORM", "TOTAL_COLIFORM"}
        limit = f.MONTEREY_LIMITS[s.analyte]
        assert s.exceeds_limit == (s.value > limit)


def test_fetch_monterey_samples_complete_failure_never_raises():
    """Client raising network error on all pages returns 0 and never raises."""
    f._COLLECTED_SAMPLES.clear()
    beaches_path = Path(__file__).resolve().parent.parent.parent / "data" / "curated" / "beaches.parquet"
    resolver = f.StationResolver(pd.read_parquet(beaches_path))

    class ErrorClient:
        def get(self, url: str, headers=None, timeout=None):
            raise httpx.ConnectError("Network unreachable")

    count = f.fetch_monterey_samples(ErrorClient(), resolver)
    assert count == 0


def test_main_monterey_report_success(tmp_path, monkeypatch):
    """Verify Monterey CountyReport in main() on successful scrape."""
    curated = tmp_path / "curated"
    curated.mkdir(parents=True)
    beaches_path = Path(__file__).resolve().parent.parent.parent / "data" / "curated" / "beaches.parquet"
    pd.read_parquet(beaches_path).to_parquet(curated / "beaches.parquet", index=False)
    pd.DataFrame(
        columns=[
            "beach_id", "advisory_type", "started_at", "ended_at",
            "status", "cause", "county", "advisory_website",
        ]
    ).to_parquet(curated / "advisories.parquet", index=False)

    monkeypatch.setattr(f, "COUNTIES_FIRST_CLASS", [])
    monkeypatch.setattr(f, "BEST_EFFORT_COUNTIES", {})
    monkeypatch.setattr(
        f,
        "fetch_state_board_advisories",
        lambda client, resolver: (
            [],
            f.CountyReport(county="State Board", success=True, last_attempted_at="", source_url=""),
        ),
    )
    monkeypatch.setattr(f, "fetch_orange_county_samples", lambda client, resolver: 0)
    monkeypatch.setattr(f, "fetch_monterey_samples", lambda client, resolver: 42)

    monkeypatch.setattr(sys, "argv", ["fetch_county_advisories.py", "--curated", str(curated)])

    rc = f.main()
    assert rc == 0

    report_path = curated / "county_advisories_report.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text())
    m_reports = [r for r in data["counties"] if r["county"] == "Monterey"]
    assert len(m_reports) == 1
    mr = m_reports[0]
    assert mr["success"] is True
    assert mr["source_url"] == f.MONTEREY_BASE_URL
    assert mr["samples_collected"] == 42
    assert mr["error"] is None
    assert mr["no_public_source"] is None


def test_main_monterey_report_failure_reported_as_breakage(tmp_path, monkeypatch):
    """When Monterey samples fetch collects 0, CountyReport has success=False and error string (breakage, not known gap)."""
    curated = tmp_path / "curated"
    curated.mkdir(parents=True)
    beaches_path = Path(__file__).resolve().parent.parent.parent / "data" / "curated" / "beaches.parquet"
    pd.read_parquet(beaches_path).to_parquet(curated / "beaches.parquet", index=False)
    pd.DataFrame(
        columns=[
            "beach_id", "advisory_type", "started_at", "ended_at",
            "status", "cause", "county", "advisory_website",
        ]
    ).to_parquet(curated / "advisories.parquet", index=False)

    monkeypatch.setattr(f, "COUNTIES_FIRST_CLASS", [])
    monkeypatch.setattr(f, "BEST_EFFORT_COUNTIES", {})
    monkeypatch.setattr(
        f,
        "fetch_state_board_advisories",
        lambda client, resolver: (
            [],
            f.CountyReport(county="State Board", success=True, last_attempted_at="", source_url=""),
        ),
    )
    monkeypatch.setattr(f, "fetch_orange_county_samples", lambda client, resolver: 0)
    monkeypatch.setattr(f, "fetch_monterey_samples", lambda client, resolver: 0)

    monkeypatch.setattr(sys, "argv", ["fetch_county_advisories.py", "--curated", str(curated)])

    rc = f.main()
    assert rc == 0

    report_path = curated / "county_advisories_report.json"
    data = json.loads(report_path.read_text())
    m_reports = [r for r in data["counties"] if r["county"] == "Monterey"]
    assert len(m_reports) == 1
    mr = m_reports[0]
    assert mr["success"] is False
    assert mr["source_url"] == f.MONTEREY_BASE_URL
    assert mr["samples_collected"] == 0
    assert mr["error"] is not None
    assert mr["no_public_source"] is None

    import data_change_report
    assert data_change_report._is_known_gap(mr) is False


def test_main_monterey_respects_only_flag(tmp_path, monkeypatch):
    """--only flag filters Monterey fetch."""
    curated = tmp_path / "curated"
    curated.mkdir(parents=True)
    beaches_path = Path(__file__).resolve().parent.parent.parent / "data" / "curated" / "beaches.parquet"
    pd.read_parquet(beaches_path).to_parquet(curated / "beaches.parquet", index=False)
    pd.DataFrame(
        columns=[
            "beach_id", "advisory_type", "started_at", "ended_at",
            "status", "cause", "county", "advisory_website",
        ]
    ).to_parquet(curated / "advisories.parquet", index=False)

    monkeypatch.setattr(f, "COUNTIES_FIRST_CLASS", [])
    monkeypatch.setattr(f, "BEST_EFFORT_COUNTIES", {})
    monkeypatch.setattr(
        f,
        "fetch_state_board_advisories",
        lambda client, resolver: (
            [],
            f.CountyReport(county="State Board", success=True, last_attempted_at="", source_url=""),
        ),
    )
    called = []
    monkeypatch.setattr(f, "fetch_monterey_samples", lambda client, resolver: (called.append("monterey") or 10))

    # Test --only orange -> Monterey not called
    called.clear()
    monkeypatch.setattr(sys, "argv", ["fetch_county_advisories.py", "--curated", str(curated), "--only", "orange"])
    f.main()
    assert "monterey" not in called

    # Test --only monterey -> Monterey is called
    called.clear()
    monkeypatch.setattr(sys, "argv", ["fetch_county_advisories.py", "--curated", str(curated), "--only", "monterey"])
    f.main()
    assert "monterey" in called


def test_monterey_county_direct_ingest_and_gap_fill():
    """Monterey rows are normalized/ingested and dropped when a state row already holds (beach_id, date, analyte)."""
    assert "Monterey" in INGEST_COUNTIES

    stations = pd.DataFrame([
        {
            "beach_id": "monterey-lop",
            "station_code": "LOP",
            "usepa_id": "CA-MON-01",
            "county": "Monterey",
            "beach_name": "Lover's Point",
        }
    ])

    raw_samples = pd.DataFrame([
        {
            "county": "Monterey",
            "beach_id": "monterey-lop",
            "area": "LOP",
            "station_code": "LOP",
            "sample_date": pd.Timestamp("2026-09-29"),
            "analyte": "ENTEROCOCCUS",
            "value": 10.0,
            "exceeds_limit": False,
            "source_url": f"{f.MONTEREY_BASE_URL}/lovers_point.htm",
        },
        {
            "county": "Monterey",
            "beach_id": "monterey-lop",
            "area": "LOP",
            "station_code": "LOP",
            "sample_date": pd.Timestamp("2026-10-06"),
            "analyte": "ENTEROCOCCUS",
            "value": 150.0,
            "exceeds_limit": True,
            "source_url": f"{f.MONTEREY_BASE_URL}/lovers_point.htm",
        },
        {
            "county": "Monterey",
            "beach_id": "monterey-lop",
            "area": "LOP",
            "station_code": "LOP",
            "sample_date": pd.Timestamp("2026-10-06"),
            "analyte": "FECAL_COLIFORM",
            "value": 300.0,
            "exceeds_limit": False,
            "source_url": f"{f.MONTEREY_BASE_URL}/lovers_point.htm",
        },
    ])

    # 1. Normalization: enterococcus only, culture threshold (104 STV), data_source = DATA_SOURCE
    direct = normalize_county_direct_samples(
        raw_samples, stations, 104.0, now=pd.Timestamp("2026-10-07")
    )
    assert len(direct) == 2
    assert (direct["county"] == "Monterey").all()
    assert (direct["analyte"] == "enterococcus").all()
    assert (direct["data_source"] == DATA_SOURCE).all()
    assert (direct["units"] == "MPN/100mL").all()
    assert (direct["method"] == "unknown").all()

    by_date = direct.set_index("sample_date")
    assert by_date.loc[pd.Timestamp("2026-09-29").date(), "value"] == 10.0
    assert bool(by_date.loc[pd.Timestamp("2026-09-29").date(), "exceeds_stv"]) is False
    assert by_date.loc[pd.Timestamp("2026-10-06").date(), "value"] == 150.0
    assert bool(by_date.loc[pd.Timestamp("2026-10-06").date(), "exceeds_stv"]) is True

    # 2. Existing observations already holds state row for 2026-09-29
    observations = pd.DataFrame([
        {
            "beach_id": "monterey-lop",
            "sample_time": pd.Timestamp("2026-09-29 09:30:00"),
            "sample_date": pd.Timestamp("2026-09-29").date(),
            "analyte": "enterococcus",
            "method": "SM 9230 D",
            "units": "MPN/100ml",
            "value": 10.0,
            "exceeds_stv": False,
            "county": "Monterey",
            "station_name": "LOP",
            "beach_name": "Lover's Point",
            "usepa_id": "CA-MON-01",
            "data_source": "BeachWatch.SafeToSwim",
        }
    ])

    # 3. Merge: 2026-09-29 direct row dropped (duplicate/mirror); 2026-10-06 ingested (gap-fill)
    merged = merge_county_direct_into_observations(observations, direct)
    assert len(merged) == 2

    # State row is untouched
    state_row = merged.loc[merged["data_source"] == "BeachWatch.SafeToSwim"].iloc[0]
    assert state_row["sample_time"] == pd.Timestamp("2026-09-29 09:30:00")
    assert state_row["value"] == 10.0

    # Direct row fills the gap
    direct_row = merged.loc[merged["data_source"] == DATA_SOURCE].iloc[0]
    assert direct_row["sample_time"] == pd.Timestamp("2026-10-06 00:00:00")
    assert direct_row["value"] == 150.0
    assert bool(direct_row["exceeds_stv"]) is True


