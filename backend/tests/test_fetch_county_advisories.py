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
    _UNRESOLVED_HARD_FLOOR,
    _UNRESOLVED_PARQUET,
    _UNRESOLVED_RATIO_THRESHOLD,
    detect_county_resolution_regressions,
    evaluate_scraper_gate,
    load_unmapped_venues,
    merge_and_rebuild,
    persist_unresolved,
    resolve_advisories,
)
from verify_scraper_gate import resolve_gate  # noqa: E402


def _state_board_stub(client, resolver):
    """The State Board scraper runs first in main(); stub it out so tests don't
    depend on the network or the live statewide roster size."""
    return [], CountyReport(
        county="State Board",
        success=True,
        last_attempted_at="2026-05-18T16:00:00Z",
        source_url="https://example.test",
    )


def _read_gate(curated: Path) -> dict:
    """The scraper_gate block main() publishes into system_health.json."""
    import json

    return json.loads((curated / "system_health.json").read_text())["scraper_gate"]


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


def test_main_soft_trips_without_exiting_when_over_absolute_floor(tmp_path, monkeypatch):
    """G.1 (2026-08-05 severity split): more than the absolute floor of
    unresolved advisories is a SOFT trip. main() must publish a failed verdict
    but still return 0, so the daily pipeline goes on to produce a forecast;
    verify_scraper_gate.py is what fails the job after the data commit."""
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
    # State board scraper runs first in main(); stub it out so the test
    # doesn't depend on network or the live State board roster size.
    def _state_board_stub(client, resolver):
        return [], CountyReport(county="State Board", success=True,
                                last_attempted_at="2026-05-18T16:00:00Z",
                                source_url="https://example.test")
    monkeypatch.setattr(fca, "fetch_state_board_advisories", _state_board_stub)

    # Patch sys.argv so main()'s argparser sees our curated dir
    monkeypatch.setattr(sys, "argv", ["fetch_county_advisories.py", "--curated", str(curated)])

    rc = fca.main()
    assert rc == 0, "a soft gate trip must NOT abort the pipeline before training"

    gate = _read_gate(curated)
    assert gate["passed"] is False
    assert gate["hard_failed"] is False
    assert gate["unresolved_unexpected"] == _UNRESOLVED_ABSOLUTE_FLOOR + 1
    assert any("absolute floor" in b for b in gate["blockers"])
    # ...and the post-commit verifier is the thing that fails the job.
    assert resolve_gate({"scraper_gate": gate})[0] is False

    parquet_path = curated / _UNRESOLVED_PARQUET
    assert parquet_path.exists()
    df = pd.read_parquet(parquet_path)
    assert len(df) == _UNRESOLVED_ABSOLUTE_FLOOR + 1


def test_main_hard_fails_above_hard_floor(tmp_path, monkeypatch):
    """G.1: mass resolution loss means the advisory feed cannot be trusted by
    the training step that consumes advisory_active_prev_14d, so the scraper
    must still abort in place."""
    curated = tmp_path / "curated"
    _write_minimal_curated(curated)

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
                station_code=None,
                area=f"Unknown Beach #{i}",
                advisory_type="Posting",
                started_at=pd.Timestamp("2026-05-18"),
                advisory_website="https://example.test",
            )
            for i in range(_UNRESOLVED_HARD_FLOOR + 1)
        ], rpt

    import fetch_county_advisories as fca
    monkeypatch.setattr(fca, "COUNTIES_FIRST_CLASS", [("Orange", _stub_fetch)])
    monkeypatch.setattr(fca, "BEST_EFFORT_COUNTIES", {})
    monkeypatch.setattr(fca, "fetch_state_board_advisories", _state_board_stub)
    monkeypatch.setattr(sys, "argv", ["fetch_county_advisories.py", "--curated", str(curated)])

    assert fca.main() == 1
    gate = _read_gate(curated)
    assert gate["hard_failed"] is True
    assert any("hard floor" in b for b in gate["blockers"])


def test_main_hard_fails_on_county_resolution_regression(tmp_path, monkeypatch):
    """A county that resolved advisories last run and resolves NONE now is the
    schema-drift signal G.1 exists for — independent of scrape volume."""
    import json

    curated = tmp_path / "curated"
    _write_minimal_curated(curated)
    # Previous run's telemetry: Orange resolved 4 advisories.
    (curated / "county_advisories_report.json").write_text(
        json.dumps({
            "counties": [
                {"county": "Orange", "matched_via_live_list": 4,
                 "matched_via_csv": 0, "matched_via_fuzzy": 0},
            ]
        })
    )

    def _stub_fetch(client, resolver):
        rpt = CountyReport(
            county="Orange",
            success=True,
            last_attempted_at="2026-05-18T16:00:00Z",
            source_url="https://example.test",
        )
        # Two parsed, neither resolvable — a renamed roster, not an empty day.
        return [
            CountyAdvisory(
                county="Orange",
                station_code=None,
                area=f"OC::STATION::{i}",
                advisory_type="Posting",
                started_at=pd.Timestamp("2026-05-18"),
                advisory_website="https://example.test",
            )
            for i in range(2)
        ], rpt

    import fetch_county_advisories as fca
    monkeypatch.setattr(fca, "COUNTIES_FIRST_CLASS", [("Orange", _stub_fetch)])
    monkeypatch.setattr(fca, "BEST_EFFORT_COUNTIES", {})
    monkeypatch.setattr(fca, "fetch_state_board_advisories", _state_board_stub)
    monkeypatch.setattr(sys, "argv", ["fetch_county_advisories.py", "--curated", str(curated)])

    assert fca.main() == 1, "a county-wide resolution regression must hard-fail"
    gate = _read_gate(curated)
    assert gate["hard_failed"] is True
    assert any("naming convention likely changed" in b for b in gate["blockers"])


def test_county_with_nothing_posted_is_not_a_regression():
    """An all-clear day (0 parsed) must never look like schema drift."""
    quiet = CountyReport(
        county="Ventura",
        success=True,
        last_attempted_at="2026-05-18T16:00:00Z",
        source_url="https://example.test",
    )
    quiet.advisories_parsed = 0
    previous = {"counties": [{"county": "Ventura", "matched_via_live_list": 3}]}
    assert detect_county_resolution_regressions([quiet], previous) == []


def test_known_unmapped_venues_do_not_trip_the_gate():
    """A venue with no possible beach_id is reported but excluded from the
    gate's numerator — otherwise it pins the counter at the threshold forever
    and any single new posting fails the workflow (the 2026-08-05 outage)."""
    allowlist = {("East Bay Parks District", "lake temescal"): "freshwater lake"}
    rows = [
        {"source_county": "East Bay Parks District",
         "scraped_name": "Lake Temescal",
         "scraped_name_normalized": "lake temescal"},
        {"source_county": "East Bay Parks District",
         "scraped_name": "Some New Venue",
         "scraped_name_normalized": "some new venue"},
    ]
    verdict = evaluate_scraper_gate(rows, total_scraped=40, regressions=[], allowlist=allowlist)
    assert verdict["unresolved_total"] == 2
    assert verdict["unresolved_expected"] == 1
    # Only the un-allowlisted name counts — 1/40 = 2.5%, under the 10% ratio.
    assert verdict["unresolved_unexpected"] == 1
    assert verdict["passed"] is True


def test_expired_allowlist_entry_stops_suppressing(tmp_path):
    """`review_by` is enforced: the allowlist is a deferral, not a permanent
    mute, so a stale entry starts counting against the gate again."""
    csv_path = tmp_path / "unmapped.csv"
    csv_path.write_text(
        "county,scraped_name_normalized,reason,review_by\n"
        "Marin,ghost venue,no counterpart,2026-01-01\n"
        "Marin,live venue,no counterpart,2099-01-01\n"
    )
    allowed = load_unmapped_venues(csv_path, today=pd.Timestamp("2026-08-05"))
    assert ("Marin", "live venue") in allowed
    assert ("Marin", "ghost venue") not in allowed


def test_shipped_allowlist_entries_are_normalized_and_unexpired():
    """The committed allowlist must be usable: names already normalized (so
    they can match the sink's normalized key) and not silently expired."""
    from fetch_county_advisories import _UNMAPPED_VENUES_CSV, _normalize_name

    raw = pd.read_csv(_UNMAPPED_VENUES_CSV, comment="#")
    assert not raw.empty
    for name in raw["scraped_name_normalized"]:
        assert _normalize_name(str(name)) == str(name), (
            f"{name!r} is not in _normalize_name() form — it can never match the sink key"
        )
    loaded = load_unmapped_venues(_UNMAPPED_VENUES_CSV, today=pd.Timestamp.now().normalize())
    assert len(loaded) == len(raw), "a shipped allowlist entry has already expired"


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
    # State board scraper runs first in main(); stub it out so the test
    # doesn't depend on network or the live State board roster size.
    def _state_board_stub(client, resolver):
        return [], CountyReport(county="State Board", success=True,
                                last_attempted_at="2026-05-18T16:00:00Z",
                                source_url="https://example.test")
    monkeypatch.setattr(fca, "fetch_state_board_advisories", _state_board_stub)
    monkeypatch.setattr(sys, "argv", ["fetch_county_advisories.py", "--curated", str(curated)])

    rc = fca.main()
    assert rc == 0


def test_main_soft_trips_on_ratio_threshold(tmp_path, monkeypatch):
    """G.1: ratio threshold trips even when absolute count is small.
    With 1 unresolved out of 2 scraped (50% > 10%) the gate must record a
    failure — as a soft trip, so the pipeline still reaches training."""
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
    # State board scraper runs first in main(); stub it out so the test
    # doesn't depend on network or the live State board roster size.
    def _state_board_stub(client, resolver):
        return [], CountyReport(county="State Board", success=True,
                                last_attempted_at="2026-05-18T16:00:00Z",
                                source_url="https://example.test")
    monkeypatch.setattr(fca, "fetch_state_board_advisories", _state_board_stub)
    monkeypatch.setattr(sys, "argv", ["fetch_county_advisories.py", "--curated", str(curated)])

    rc = fca.main()
    assert rc == 0, "a ratio-only trip is soft — it must not abort before training"
    gate = _read_gate(curated)
    assert gate["passed"] is False
    assert gate["hard_failed"] is False
    assert any("ratio threshold" in b for b in gate["blockers"])


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


# ---------- State Water Board scraper ----------

def test_state_board_parse_row_extracts_active_posting():
    """Active = empty DateClosed; row parser pulls the 11 columns we need."""
    from scripts.fetch_county_advisories import _state_board_parse_row
    cells = [
        "Posting", "San Diego", "FM-030", "Tourmaline drain outlet",
        "Tourmaline Surfing Park", "Bacterial Standards Violation",
        "Unknown", ".", "2026-05-20", "", "Enterococcus",
    ]
    parsed = _state_board_parse_row(cells)
    assert parsed is not None
    assert parsed["type"] == "Posting"
    assert parsed["county"] == "San Diego"
    assert parsed["station_code"] == "FM-030"
    assert parsed["started_at"] == "2026-05-20"
    assert parsed["ended_at"] is None  # empty DateClosed → still active


def test_state_board_parse_row_skips_closed_rows():
    """Non-empty DateClosed → not currently active; caller filters out."""
    from scripts.fetch_county_advisories import _state_board_parse_row
    cells = [
        "Posting", "San Diego", "FM-030", "Tourmaline drain outlet",
        "Tourmaline Surfing Park", "Bacterial Standards Violation",
        "Unknown", ".", "2026-04-15", "2026-04-16", "Enterococcus",
    ]
    parsed = _state_board_parse_row(cells)
    assert parsed is not None
    assert parsed["ended_at"] == "2026-04-16"


def test_state_board_parse_row_rejects_header_row():
    """Header row has 'Type' in cell 0, not a valid type enum value."""
    from scripts.fetch_county_advisories import _state_board_parse_row
    header = ["Type", "County", "Station Code", "Station Name", "Beach",
              "Cause", "Source", "Substance", "Start Date", "End Date", "Analyte"]
    assert _state_board_parse_row(header) is None


def test_state_board_parse_row_rejects_short_row():
    from scripts.fetch_county_advisories import _state_board_parse_row
    assert _state_board_parse_row(["Posting", "San Diego"]) is None


def test_state_board_advisories_are_unioned_into_merge(tmp_path):
    """The new scraper feeds merge_and_rebuild like any other county source.
    Verifies an active State-board row for a beach NOT in the prior parquet
    gets added as active after merge."""
    curated = tmp_path / "curated"
    curated.mkdir()
    # Empty starting parquet (no prior state-CSV entries for this beach)
    pd.DataFrame(
        columns=["beach_id", "advisory_type", "started_at", "ended_at",
                 "status", "cause", "county", "advisory_website"]
    ).to_parquet(curated / "advisories.parquet", index=False)

    from scripts.fetch_county_advisories import CountyAdvisory, merge_and_rebuild
    state_board_advisory = CountyAdvisory(
        county="San Diego",
        station_code="FM-030",
        area="Tourmaline Surfing Park",
        advisory_type="Posting",
        started_at=pd.Timestamp("2026-05-20"),
        advisory_website="https://beachwatch.waterboards.ca.gov/public/advisory.php",
        cause="Bacterial Standards Violation",
    )
    state_board_advisory.beach_id = "ca748587-san-diego-tourmaline-surfing-park-fm-030"

    added, demoted = merge_and_rebuild(
        [state_board_advisory], curated, rebuild_beach_day=False,
        authoritative_counties={"San Diego"},
    )
    assert added == 1
    result = pd.read_parquet(curated / "advisories.parquet")
    active = result[result["status"] == "active"]
    assert len(active) == 1
    assert active.iloc[0]["beach_id"] == "ca748587-san-diego-tourmaline-surfing-park-fm-030"


# ---------- Resolver mapping (2026-08-05 regressions) ---------- #


def _ebrpd_marin_beaches() -> pd.DataFrame:
    """A registry slice reproducing the two shapes that broke resolution:

    * Marin's GREEN BRIDGE, whose `beach_name` is the county-wide placeholder
      "All_Marin_County" — its identity lives only in `name`/`station_code`.
    * EBRPD's multi-point groups, where several sampled beaches share one
      `beach_name` ("Del Valle", "Crown Beach (Alameda Co)").
    """
    def _row(beach_id, name, beach_name, county, station_code):
        return {
            "beach_id": beach_id,
            "name": name,
            "beach_name": beach_name,
            "county": county,
            "region": "North",
            "station_code": station_code,
            "support_status": "production",
            "latitude": 37.9,
            "longitude": -122.3,
        }

    return pd.DataFrame([
        _row("marin-green-bridge", "GREEN BRIDGE", "All_Marin_County", "Marin", "GREEN BRIDGE"),
        _row("marin-inkwells", "Inkwells", "All_Marin_County", "Marin", "Inkwells"),
        _row("ebrpd-del-valle-west", "Del Valle WEST Swim Beach", "Del Valle",
             "East Bay Parks District", "Del Valle West"),
        _row("ebrpd-del-valle-east", "Del Valle EAST Swim Beach", "Del Valle",
             "East Bay Parks District", "Del Valle East"),
        _row("ebrpd-alameda-point-mid", "Alameda Point Encinal Beach Mid", "Alameda Point",
             "East Bay Parks District", "Alameda Mid"),
        _row("ebrpd-crown-crab-cove", "Crab Cove", "Crown Beach (Alameda Co)",
             "East Bay Parks District", "Crown Crab Cove"),
        _row("ebrpd-crown-bath-house", "Bath House", "Crown Beach (Alameda Co)",
             "East Bay Parks District", "Crown Bath House"),
    ])


def test_secondary_index_resolves_site_name_under_placeholder_beach_name():
    """GREEN BRIDGE is a production Marin beach whose beach_name is the
    "All_Marin_County" placeholder, so a beach_name-only index cannot see it.
    Its 2026-08-05 posting was dropped for exactly this reason."""
    resolver = StationResolver(_ebrpd_marin_beaches())
    beach_ids, kind = resolver.resolve_all_by_name("Marin", "Green Bridge")
    assert beach_ids == ["marin-green-bridge"]
    assert kind == "live_list"


def test_multi_point_group_resolves_to_the_right_site_not_a_sibling():
    """Both Del Valle beaches share beach_name "Del Valle", so the primary
    index collapses them to one arbitrary id — the WEST posting used to land on
    the EAST beach while WEST showed clean."""
    resolver = StationResolver(_ebrpd_marin_beaches())
    west, _ = resolver.resolve_all_by_name("East Bay Parks District", "Del Valle WEST Swim Beach")
    east, _ = resolver.resolve_all_by_name("East Bay Parks District", "Del Valle EAST Swim Beach")
    assert west == ["ebrpd-del-valle-west"]
    assert east == ["ebrpd-del-valle-east"]


def test_substring_rule_rejects_single_incidental_token_match():
    """"Shinn Pond at Alameda Creek Trails" (a Fremont freshwater pond) used to
    resolve onto "Alameda Point Encinal Beach Mid" on the single shared token
    "alameda". A dropped advisory is a miss; a mis-mapped one posts a warning on
    the wrong beach AND clears the real one, so this must now be a miss.

    Covers BOTH layers that can make this match: the substring rule and the
    fuzzy fallback. rapidfuzz's token_set_ratio scores a token-subset pair 100,
    so guarding only the substring layer left the mis-map fully intact wherever
    rapidfuzz is installed — which is CI and production, but not necessarily a
    dev sandbox, so this test is silently weaker without it.
    """
    import fetch_county_advisories as fca

    resolver = StationResolver(_ebrpd_marin_beaches())
    beach_ids, kind = resolver.resolve_all_by_name(
        "East Bay Parks District", "Shinn Pond at Alameda Creek Trails"
    )
    assert beach_ids == []
    assert kind == "miss"
    assert fca.HAS_RAPIDFUZZ, (
        "rapidfuzz is missing, so the fuzzy layer was skipped and this test did "
        "not actually exercise it — install it (it is in the CI dependency set)"
    )


def test_fuzzy_layer_still_matches_a_genuine_misspelling():
    """The token guard must not turn the fuzzy layer off entirely: a near-
    identical string is still a match via the length-sensitive `ratio`."""
    beaches = pd.DataFrame([
        {"beach_id": "stinson", "name": "Stinson", "beach_name": "Stinson Cove",
         "county": "Marin", "region": "N", "station_code": "S1",
         "support_status": "production", "latitude": 1.0, "longitude": 2.0},
    ])
    resolver = StationResolver(beaches)
    # A misspelling: shares only 1 token with the roster key, so it survives
    # solely on the whole-string ratio (91.7) — the path the guard preserves.
    beach_ids, kind = resolver.resolve_all_by_name("Marin", "Stinsen Cove")
    assert beach_ids == ["stinson"]
    assert kind == "fuzzy"


def test_substring_rule_still_matches_on_two_shared_tokens():
    """The guard must not break legitimate substring matches: EBRPD posts
    "Del Valle Swim Beach" against roster key "del valle"."""
    resolver = StationResolver(_ebrpd_marin_beaches().iloc[[2]])  # WEST only
    beach_ids, kind = resolver.resolve_all_by_name(
        "East Bay Parks District", "Del Valle Swim Beach Area"
    )
    assert beach_ids == ["ebrpd-del-valle-west"]
    assert kind == "live_list"


def test_ambiguous_substring_match_is_a_miss_not_a_coin_flip():
    """When several roster keys qualify, dict order must not decide which beach
    gets the advisory — drop to the unresolved sink instead."""
    beaches = pd.DataFrame([
        {"beach_id": "a", "name": "A", "beach_name": "Sunset Cove North", "county": "Marin",
         "region": "N", "station_code": "A1", "support_status": "production",
         "latitude": 1.0, "longitude": 2.0},
        {"beach_id": "b", "name": "B", "beach_name": "Sunset Cove South", "county": "Marin",
         "region": "N", "station_code": "B1", "support_status": "production",
         "latitude": 1.0, "longitude": 2.0},
    ])
    resolver = StationResolver(beaches)
    beach_ids, kind = resolver.resolve_all_by_name("Marin", "Sunset Cove")
    assert beach_ids == []
    assert kind == "miss"


def test_ambiguous_secondary_key_is_dropped():
    """Two sites sharing a normalized `name` within a county must not resolve
    arbitrarily through the secondary index."""
    beaches = pd.DataFrame([
        {"beach_id": "a", "name": "North Cove", "beach_name": "Harbor One", "county": "Marin",
         "region": "N", "station_code": "A1", "support_status": "production",
         "latitude": 1.0, "longitude": 2.0},
        {"beach_id": "b", "name": "North Cove", "beach_name": "Harbor Two", "county": "Marin",
         "region": "N", "station_code": "B1", "support_status": "production",
         "latitude": 1.0, "longitude": 2.0},
    ])
    resolver = StationResolver(beaches)
    assert resolver.resolve_all_by_name("Marin", "North Cove")[0] == []


def test_alias_fan_out_replicates_advisory_onto_every_covered_beach(tmp_path, monkeypatch):
    """EBRPD posts ONE district-wide notice for Crown Beach, which the registry
    splits into several sampled points. Resolving to a single point would leave
    the rest showing clean under a live district posting."""
    import fetch_county_advisories as fca

    alias_csv = tmp_path / "alias.csv"
    alias_csv.write_text(
        "county,beach_name_normalized,station_code,beach_id,notes\n"
        "East Bay Parks District,crown regional shoreline,,ebrpd-crown-crab-cove,fan-out\n"
        "East Bay Parks District,crown regional shoreline,,ebrpd-crown-bath-house,fan-out\n"
    )
    monkeypatch.setattr(fca, "_STATIC_ALIAS_CSV", alias_csv)

    resolver = StationResolver(_ebrpd_marin_beaches())
    beach_ids, kind = resolver.resolve_all_by_name(
        "East Bay Parks District", "Crown Beach Regional Shoreline"
    )
    assert kind == "csv"
    assert sorted(beach_ids) == ["ebrpd-crown-bath-house", "ebrpd-crown-crab-cove"]

    rpt = CountyReport(
        county="East Bay Parks District",
        success=True,
        last_attempted_at="2026-08-05T16:00:00Z",
        source_url="https://example.test",
    )
    resolved = resolve_advisories(
        [CountyAdvisory(
            county="East Bay Parks District",
            station_code=None,
            area="Crown Beach Regional Shoreline",
            advisory_type="Posting",
            started_at=pd.Timestamp("2026-08-05"),
            advisory_website="https://example.test",
        )],
        resolver,
        rpt,
    )
    assert sorted(a.beach_id for a in resolved) == [
        "ebrpd-crown-bath-house", "ebrpd-crown-crab-cove",
    ]
    # One scraped posting, so it counts once against the telemetry.
    assert rpt.matched_via_csv == 1


def test_resolve_by_name_stays_single_valued_for_samples(tmp_path, monkeypatch):
    """A scraped MPN reading is ONE physical measurement — persist_samples must
    not fan it out across a group the way a district-wide advisory is."""
    import fetch_county_advisories as fca

    alias_csv = tmp_path / "alias.csv"
    alias_csv.write_text(
        "county,beach_name_normalized,station_code,beach_id,notes\n"
        "East Bay Parks District,crown regional shoreline,,ebrpd-crown-crab-cove,fan-out\n"
        "East Bay Parks District,crown regional shoreline,,ebrpd-crown-bath-house,fan-out\n"
    )
    monkeypatch.setattr(fca, "_STATIC_ALIAS_CSV", alias_csv)

    resolver = StationResolver(_ebrpd_marin_beaches())
    beach_id, kind = resolver.resolve_by_name(
        "East Bay Parks District", "Crown Beach Regional Shoreline"
    )
    assert isinstance(beach_id, str)
    assert kind == "csv"


def test_alias_csv_outranks_the_substring_heuristic(tmp_path, monkeypatch):
    """The curated alias file is the operator's escape hatch: it must be able to
    correct a bad heuristic match, which requires it to run first."""
    import fetch_county_advisories as fca

    alias_csv = tmp_path / "alias.csv"
    alias_csv.write_text(
        "county,beach_name_normalized,station_code,beach_id,notes\n"
        "East Bay Parks District,del valle swim area,,ebrpd-del-valle-east,operator override\n"
    )
    monkeypatch.setattr(fca, "_STATIC_ALIAS_CSV", alias_csv)

    resolver = StationResolver(_ebrpd_marin_beaches())
    beach_ids, kind = resolver.resolve_all_by_name(
        "East Bay Parks District", "Del Valle Swim Area"
    )
    assert kind == "csv"
    assert beach_ids == ["ebrpd-del-valle-east"]
