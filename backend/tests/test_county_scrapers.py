"""Tests for county scrapers (San Diego OutSystems, Santa Barbara ArcGIS, etc.)."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import httpx
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fetch_county_advisories as fca  # noqa: E402
from fetch_county_advisories import (  # noqa: E402
    SD_DEFAULT_API_VERSION,
    SD_EVENTS_URL,
    SD_HOMEPAGE,
    SD_MODULE_VERSION_URL,
    NO_SOURCE_COUNTIES,
    OC_HOMEPAGE,
    SM_HOMEPAGE,
    SM_KML_URL,
    CountyAdvisory,
    CountyReport,
    StationResolver,
    _COLLECTED_SAMPLES,
    _normalize_name,
    resolve_advisories,
    _oc_pick_newest_xlsx,
    _oc_samples_from_frame,
    fetch_orange_county_samples,
    _SD_API_VERSION_RE,
    _parse_sm_kml,
    _parse_sm_notices,
    _sm_color_is_posted,
    fetch_orange_county_advisories,
    fetch_san_mateo_advisories,
    fetch_ventura_advisories,
    _parse_sb_arcgis_payload,
    _parse_sd_events_payload,
    _sd_discover_api_version,
    fetch_san_diego_advisories,
    fetch_santa_barbara_advisories,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "county_scrapers"


@pytest.fixture
def test_resolver() -> StationResolver:
    beaches_df = pd.DataFrame([
        # San Diego stations from fixtures
        {
            "beach_id": "ca273334-san-diego-south-casa-beach-s-d-eh-310",
            "name": "Children's Pool",
            "beach_name": "South Casa Beach S.D.",
            "county": "San Diego",
            "station_code": "EH-310",
        },
        {
            "beach_id": "ca211999-san-diego-mission-bay-vacation-isle-mb-205",
            "name": "North Cove Vacation Isle",
            "beach_name": "Mission Bay, Vacation Isle",
            "county": "San Diego",
            "station_code": "MB-205",
        },
        {
            "beach_id": "ca997086-san-diego-la-jolla-cove-fm-070",
            "name": "La Jolla Cove",
            "beach_name": "La Jolla Cove",
            "county": "San Diego",
            "station_code": "FM-070",
        },
        {
            "beach_id": "ca499735-san-diego-windansea-beach-eh-280",
            "name": "Playa Del Norte",
            "beach_name": "WindanSea Beach",
            "county": "San Diego",
            "station_code": "EH-280",
        },
        {
            "beach_id": "ca068221-san-diego-imperial-beach-municipal-beach-other-eh-010",
            "name": "Cortez Ave",
            "beach_name": "Imperial Beach Municipal Beach",
            "county": "San Diego",
            "station_code": "EH-010",
        },
        {
            "beach_id": "ca809706-san-diego-border-field-state-park-ib-010",
            "name": "Border Fence N Side",
            "beach_name": "Border Field State Park",
            "county": "San Diego",
            "station_code": "IB-010",
        },
        {
            "beach_id": "ca809706-san-diego-border-field-state-park-ib-020",
            "name": "Monument Rd.",
            "beach_name": "Border Field State Park",
            "county": "San Diego",
            "station_code": "IB-020",
        },
        {
            "beach_id": "ca104746-san-diego-tijuana-slough-national-wildlife-refuge-ib-030",
            "name": "Tijuana Estuary mouth",
            "beach_name": "Tijuana Slough National Wildlife Refuge",
            "county": "San Diego",
            "station_code": "IB-030",
        },
        {
            "beach_id": "ca104746-san-diego-tijuana-slough-national-wildlife-refuge-ib-040",
            "name": "3/4 mi. N of TJ River",
            "beach_name": "Tijuana Slough National Wildlife Refuge",
            "county": "San Diego",
            "station_code": "IB-040",
        },
        # Santa Barbara stations from fixtures
        {
            "beach_id": "ca957734-santa-barbara-gaviota-state-beach-wp0000079",
            "name": "Gaviota State Beach",
            "beach_name": "Gaviota State Beach",
            "county": "Santa Barbara",
            "station_code": "WP0000079",
        },
        {
            "beach_id": "ca125649-santa-barbara-goleta-beach-wp0000037",
            "name": "Goleta Beach",
            "beach_name": "Goleta Beach",
            "county": "Santa Barbara",
            "station_code": "WP0000037",
        },
        {
            "beach_id": "ca337598-santa-barbara-hope-ranch-beach-wp0000072",
            "name": "Hope Ranch",
            "beach_name": "Hope Ranch",
            "county": "Santa Barbara",
            "station_code": "WP0000072",
        },
        {
            "beach_id": "ca120855-santa-barbara-arroyo-burro-wp0000147",
            "name": "Arroyo Burro",
            "beach_name": "Arroyo Burro",
            "county": "Santa Barbara",
            "station_code": "WP0000147",
        },
        {
            "beach_id": "ca576166-santa-barbara-leadbetter-wp0000007",
            "name": "Leadbetter",
            "beach_name": "Leadbetter",
            "county": "Santa Barbara",
            "station_code": "WP0000007",
        },
        {
            "beach_id": "ca218180-santa-barbara-east-beach-wp0000085",
            "name": "East Beach @ Mission Creek",
            "beach_name": "East Beach @ Mission Creek",
            "county": "Santa Barbara",
            "station_code": "WP0000085",
        },
        {
            "beach_id": "ca218180-santa-barbara-east-beach-wp0000083",
            "name": "East Beach @ Sycamore Creek",
            "beach_name": "East Beach @ Sycamore Creek",
            "county": "Santa Barbara",
            "station_code": "WP0000083",
        },
        {
            "beach_id": "ca797256-santa-barbara-butterfly-beach-wp0000023",
            "name": "Butterfly Beach",
            "beach_name": "Butterfly Beach",
            "county": "Santa Barbara",
            "station_code": "WP0000023",
        },
    ])
    return StationResolver(beaches_df)


# =========================================================================== #
# San Diego tests
# =========================================================================== #


def test_sd_parse_events_advisories_and_chronic_rule(test_resolver: StationResolver):
    """Test parsing of sd_events1.json (EventTypeId 1 - Advisories).
    Verify that postings older than 365 days become 'Chronic Posting'
    (EH-310 since 1997), while recent postings become 'Posting'.
    """
    path = FIXTURES_DIR / "sd_events1.json"
    data = json.loads(path.read_text())

    ref_date = pd.Timestamp("2026-10-02T18:00:00Z")
    advs, err = _parse_sd_events_payload(data, event_type_id=1, resolver=test_resolver, now=ref_date)
    assert err is None
    assert len(advs) == 5

    by_station = {a.station_code: a for a in advs}

    # EH-310: 1997-09-01 -> Chronic Posting
    eh310 = by_station["EH-310"]
    assert eh310.advisory_type == "Chronic Posting"
    assert eh310.area == "South Casa Beach S.D."
    assert eh310.beach_id == "ca273334-san-diego-south-casa-beach-s-d-eh-310"
    assert eh310.started_at == pd.Timestamp("1997-09-01 17:27:00")
    assert eh310.county == "San Diego"

    # MB-205: 2026-09-18 -> Posting
    mb205 = by_station["MB-205"]
    assert mb205.advisory_type == "Posting"
    assert mb205.beach_id == "ca211999-san-diego-mission-bay-vacation-isle-mb-205"

    # FM-070: 2026-09-30 -> Posting
    fm070 = by_station["FM-070"]
    assert fm070.advisory_type == "Posting"

    # EH-280: 2026-10-01 -> Posting
    eh280 = by_station["EH-280"]
    assert eh280.advisory_type == "Posting"

    # EH-010: 2026-10-02 -> Posting
    eh010 = by_station["EH-010"]
    assert eh010.advisory_type == "Posting"


def test_sd_parse_events_closures(test_resolver: StationResolver):
    """Test parsing of sd_events2.json (EventTypeId 2 - Closures).
    Verify that EventTypeId 2 always produces 'Closure'.
    """
    path = FIXTURES_DIR / "sd_events2.json"
    data = json.loads(path.read_text())

    ref_date = pd.Timestamp("2026-10-02T18:00:00Z")
    advs, err = _parse_sd_events_payload(data, event_type_id=2, resolver=test_resolver, now=ref_date)
    assert err is None
    assert len(advs) == 4

    for a in advs:
        assert a.advisory_type == "Closure"
        assert a.county == "San Diego"
        assert a.beach_id is not None
        assert a.cause in ("Bacterial Standards Violation", "Other - Tijuana River Associated")

    codes = [a.station_code for a in advs]
    assert codes == ["IB-010", "IB-020", "IB-030", "IB-040"]


def test_sd_api_version_regex():
    """Verify that regex extracts apiVersion from BlockNotification JS."""
    sample_js = '''
    some_code();
    OS.Screenservices.call("screenservices/CoSD_Beach_Water_CW/MainFlow/BlockNotification/ScreenDataSetGetEventsList", "7ZgLP6EfhAWhyK1_ilFFoA");
    other_code();
    '''
    m = _SD_API_VERSION_RE.search(sample_js)
    assert m is not None
    assert m.group(1) == "7ZgLP6EfhAWhyK1_ilFFoA"

    # Fallback when regex does not match
    assert _SD_API_VERSION_RE.search("no match here") is None


def test_sd_discover_api_version_fallback():
    """Verify _sd_discover_api_version falls back to SD_DEFAULT_API_VERSION on error."""
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    client = httpx.Client(transport=transport)
    ver = _sd_discover_api_version(client)
    assert ver == SD_DEFAULT_API_VERSION


def test_sd_api_version_changed_error():
    """Verify error flag when OutSystems indicates API version changed."""
    data = {
        "versionInfo": {"hasModuleVersionChanged": False, "hasApiVersionChanged": True},
        "data": {},
    }
    advs, err = _parse_sd_events_payload(data, event_type_id=1)
    assert advs == []
    assert err is not None
    assert "hasApiVersionChanged is True" in err


def test_sd_exception_error():
    """Verify error flag when OutSystems returns exception."""
    data = {
        "versionInfo": {"hasModuleVersionChanged": False, "hasApiVersionChanged": False},
        "exception": "Invalid request parameter",
    }
    advs, err = _parse_sd_events_payload(data, event_type_id=1)
    assert advs == []
    assert err is not None
    assert "Invalid request parameter" in err


def test_fetch_san_diego_advisories_offline(test_resolver: StationResolver):
    """End-to-end test of fetch_san_diego_advisories using mocked responses."""
    sd1_bytes = (FIXTURES_DIR / "sd_events1.json").read_bytes()
    sd2_bytes = (FIXTURES_DIR / "sd_events2.json").read_bytes()
    empty_bytes = json.dumps({"versionInfo": {}, "data": {"List": {"List": []}}}).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if url_str == SD_HOMEPAGE:
            return httpx.Response(200, text="<html><body>SD Beach Info</body></html>")
        if url_str == SD_MODULE_VERSION_URL:
            return httpx.Response(200, json={"versionToken": "tok_unit_test"})
        if "moduleservices/moduleinfo" in url_str:
            return httpx.Response(200, json={
                "manifest": {
                    "urlVersions": {
                        "/sdbeachinfo/scripts/CoSD_Beach_Water_CW.MainFlow.BlockNotification.mvc.js": "?v1",
                    }
                }
            })
        if "BlockNotification.mvc.js" in url_str:
            js = '"screenservices/CoSD_Beach_Water_CW/MainFlow/BlockNotification/ScreenDataSetGetEventsList", "7ZgLP6EfhAWhyK1_ilFFoA"'
            return httpx.Response(200, text=js)
        if url_str == SD_EVENTS_URL:
            body = json.loads(request.content.decode())
            event_type = body.get("screenData", {}).get("variables", {}).get("EventTypeId")
            if event_type == 1:
                return httpx.Response(200, content=sd1_bytes)
            if event_type == 2:
                return httpx.Response(200, content=sd2_bytes)
            return httpx.Response(200, content=empty_bytes)
        return httpx.Response(404)

    ref_date = pd.Timestamp("2026-10-02T18:00:00Z")
    # Both the raw client and the RetryingClient main() actually uses: the
    # OutSystems call posts a JSON body, which RetryingClient.post did not
    # accept until 2026-10-02 (every real run failed while this test passed).
    for client in (
        httpx.Client(transport=httpx.MockTransport(handler)),
        fca.RetryingClient(transport=httpx.MockTransport(handler)),
    ):
        advs, rpt = fetch_san_diego_advisories(client, test_resolver, now=ref_date)

        assert rpt.success is True
        assert rpt.error is None
        assert rpt.advisories_parsed == 9
        assert len(advs) == 9

        types = [a.advisory_type for a in advs]
        assert types.count("Chronic Posting") == 1
        assert types.count("Posting") == 4
        assert types.count("Closure") == 4


# =========================================================================== #
# Santa Barbara tests
# =========================================================================== #


def test_sb_parse_pts_fixture(test_resolver: StationResolver):
    """Test parsing of sb_pts.json (ArcGIS query result).
    Verify that 8 Open features are ignored and 8 Warning features become 'Posting'.
    """
    path = FIXTURES_DIR / "sb_pts.json"
    data = json.loads(path.read_text())

    advs, err = _parse_sb_arcgis_payload(data, resolver=test_resolver)
    assert err is None
    assert len(advs) == 8

    for a in advs:
        assert a.advisory_type == "Posting"
        assert a.county == "Santa Barbara"
        assert a.started_at == pd.Timestamp("2026-09-28 00:00:00")
        assert a.beach_id is not None
        assert a.cause == "Bacterial Standards Violation"

    stations = {a.station_code for a in advs}
    expected_stations = {
        "WP0000079", "WP0000037", "WP0000072", "WP0000147",
        "WP0000007", "WP0000085", "WP0000083", "WP0000023",
    }
    assert stations == expected_stations


def test_sb_status_mapping():
    """Verify Beach_status mapping: Open -> skip, Warning -> Posting, Closed -> Closure."""
    test_data = {
        "features": [
            {"attributes": {"Identifier": "S1", "Beach_Name": "Beach 1", "Beach_status": "Open"}},
            {"attributes": {"Identifier": "S2", "Beach_Name": "Beach 2", "Beach_status": "Warning"}},
            {"attributes": {"Identifier": "S3", "Beach_Name": "Beach 3", "Beach_status": "Closed"}},
            {"attributes": {"Identifier": "S4", "Beach_Name": "Beach 4", "Beach_status": "Closure active"}},
            {"attributes": {"Identifier": "S5", "Beach_Name": "Beach 5", "Beach_status": "Open with restrictions"}},
        ]
    }
    advs, err = _parse_sb_arcgis_payload(test_data)
    assert err is None
    assert len(advs) == 3

    by_id = {a.station_code: a.advisory_type for a in advs}
    assert by_id["S2"] == "Posting"
    assert by_id["S3"] == "Closure"
    assert by_id["S4"] == "Closure"


def test_sb_error_handling():
    """Verify error flag when ArcGIS endpoint returns error JSON."""
    data = {"error": {"code": 400, "message": "Invalid query"}}
    advs, err = _parse_sb_arcgis_payload(data)
    assert advs == []
    assert err is not None
    assert "ArcGIS error" in err


def test_fetch_santa_barbara_advisories_offline(test_resolver: StationResolver):
    """End-to-end test of fetch_santa_barbara_advisories using mocked responses."""
    sb_bytes = (FIXTURES_DIR / "sb_pts.json").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "FeatureServer/0/query" in url_str:
            return httpx.Response(200, content=sb_bytes)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    advs, rpt = fetch_santa_barbara_advisories(client, test_resolver)

    assert rpt.success is True
    assert rpt.error is None
    assert rpt.advisories_parsed == 8
    assert len(advs) == 8


# ---------- San Mateo ---------- #


@pytest.fixture
def sm_resolver() -> StationResolver:
    return StationResolver(pd.DataFrame([
        {"beach_id": "ca-sm-linda-mar-5", "name": "Linda Mar #5", "beach_name": "Pacifica State Beach",
         "county": "San Mateo", "station_code": "Linda Mar #5"},
        {"beach_id": "ca-sm-pillar-point-9", "name": "Pillar Point #9", "beach_name": "Pillar Point Harbor",
         "county": "San Mateo", "station_code": "Pillar Point #9"},
        {"beach_id": "ca-sm-rockaway", "name": "Rockaway Beach", "beach_name": "Rockaway Beach",
         "county": "San Mateo", "station_code": "RB-1"},
    ]))


def test_sm_color_mapping():
    assert _sm_color_is_posted("A52714")  # red = Posted
    assert _sm_color_is_posted("F4511E")  # orange = Not Sampled, Posted
    assert _sm_color_is_posted("EF6C00")
    assert not _sm_color_is_posted("0F9D58")  # green
    assert not _sm_color_is_posted("757575")  # gray
    assert not _sm_color_is_posted("zzzzzz")


def test_sm_kml_fixture_colours():
    marks = _parse_sm_kml((FIXTURES_DIR / "sm.kml").read_text())
    assert len(marks) == 41
    posted = [n for n, c in marks if _sm_color_is_posted(c)]
    assert len(posted) == 9
    assert "LINDA MAR #5 (at San Pedro Creek)" in posted
    assert "GAZOS CREEK" in posted
    assert "SHARP PARK #3" not in posted


def test_sm_notice_closures_from_fixture():
    names = _parse_sm_notices((FIXTURES_DIR / "sm2.html").read_text())
    assert names == ["Rockaway Beach", "Calera Creek"]


def test_sm_notice_absent_returns_nothing():
    assert _parse_sm_notices("<html><body>No notices today</body></html>") == []


def test_fetch_san_mateo_advisories_offline(sm_resolver: StationResolver):
    kml = (FIXTURES_DIR / "sm.kml").read_bytes()
    page = (FIXTURES_DIR / "sm2.html").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == SM_KML_URL:
            return httpx.Response(200, content=kml)
        if str(request.url) == SM_HOMEPAGE:
            return httpx.Response(200, content=page)
        return httpx.Response(404)

    advs, rpt = fetch_san_mateo_advisories(httpx.Client(transport=httpx.MockTransport(handler)), sm_resolver)
    assert rpt.success is True and rpt.error is None
    assert rpt.advisories_parsed == len(advs) == 9 + 2
    postings = [a for a in advs if a.advisory_type == "Posting"]
    closures = [a for a in advs if a.advisory_type == "Closure"]
    assert len(postings) == 9
    assert sorted(a.area for a in closures) == ["Calera Creek", "Rockaway Beach"]
    # Names are left to StationResolver rather than resolved inline.
    assert all(a.beach_id is None and a.station_code is None for a in advs)
    rpt2 = CountyReport(county="San Mateo", success=True, last_attempted_at="", source_url="")
    resolved = resolve_advisories(advs, sm_resolver, rpt2, unresolved_sink=[])
    by_area = {a.area: a for a in resolved}
    assert by_area["PILLAR POINT #9"].beach_id == "ca-sm-pillar-point-9"
    assert by_area["Rockaway Beach"].beach_id == "ca-sm-rockaway"


def test_fetch_san_mateo_kml_failure_sets_error(sm_resolver: StationResolver):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    advs, rpt = fetch_san_mateo_advisories(client, sm_resolver)
    assert advs == [] and rpt.success is False
    assert rpt.error and "KML" in rpt.error


# ---------- Orange County diagnostics ---------- #


@pytest.fixture
def oc_resolver() -> StationResolver:
    return StationResolver(pd.DataFrame([
        {"beach_id": "ca-oc-x", "name": "X", "beach_name": "X", "county": "Orange", "station_code": "X-1"},
    ]))


def test_oc_fixture_parses_three_postings(oc_resolver: StationResolver):
    page = (FIXTURES_DIR / "oc.html").read_bytes()
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=page)))
    advs, rpt = fetch_orange_county_advisories(client, oc_resolver)
    assert rpt.error is None and rpt.success is True
    assert len(advs) == 3


def test_oc_missing_markers_error_is_diagnostic(oc_resolver: StationResolver):
    challenge = (
        "<html><head><title>Just a moment...</title></head>"
        "<body><h1>Checking your browser before accessing the site</h1></body></html>"
    )
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=challenge)))
    advs, rpt = fetch_orange_county_advisories(client, oc_resolver)
    assert advs == [] and rpt.success is False
    assert "status=200" in rpt.error
    assert OC_HOMEPAGE in rpt.error
    assert "Just a moment" in rpt.error
    assert "Checking your browser" in rpt.error


# ---------- Ventura fragment rejection (C1) ---------- #


def test_ventura_rejects_prose_fragments():
    fragments = [
        "cate that water quality at the following beach",
        "on either side of each posted sign. This beach",
        "ducted once per week on Tuesdays. When a beach",
    ]
    html = "<p>" + " ".join(f"{f} is posted with a warning." for f in fragments) + "</p>"
    resolver = StationResolver(pd.DataFrame([
        {"beach_id": "ca-v", "name": "Beach", "beach_name": "Beach", "county": "Ventura", "station_code": "V-1"},
    ]))
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html)))
    advs, rpt = fetch_ventura_advisories(client, resolver)
    assert advs == []
    assert rpt.rejected_fragments >= 3


def test_ventura_keeps_real_beach_name():
    html = "<p>Silver Strand Beach is posted with a warning.</p>"
    resolver = StationResolver(pd.DataFrame([
        {"beach_id": "ca-v", "name": "Beach", "beach_name": "Beach", "county": "Ventura", "station_code": "V-1"},
    ]))
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html)))
    advs, rpt = fetch_ventura_advisories(client, resolver)
    assert [a.area for a in advs] == ["Silver Strand Beach"]
    assert rpt.rejected_fragments == 0


# ---------- Monterey ---------- #


def test_monterey_is_samples_only_not_no_source():
    import dataclasses
    import inspect

    import fetch_county_advisories as f

    assert "Monterey" not in NO_SOURCE_COUNTIES
    assert "Monterey" not in f.COUNTIES_FIRST_CLASS
    assert "Monterey" not in {name for name, _ in f.COUNTIES_FIRST_CLASS}

    assert "no_public_source" in {fld.name for fld in dataclasses.fields(f.CountyReport)}
    src = inspect.getsource(f.main)
    assert "no_public_source=reason" in src and "error=reason" not in src


# ---------- Orange County lab results (xlsx) ---------- #

OC_DATA_HTML = """
<a href="https://ocbeachinfo.com/wp-content/uploads/Orange-County-Beach-Monitoring-Data-2026-8.14.2026.xlsx">old</a>
<a href="https://ocbeachinfo.com/wp-content/uploads/Orange-County-Beach-Monitoring-Data-2026-9.15.2026.xlsx">new</a>
<a href="/wp-content/uploads/Orange-County-Beach-Monitoring-Data-2025-12.31.2025.xlsx">prior year</a>
"""


@pytest.fixture
def oc_samples_resolver() -> StationResolver:
    return StationResolver(pd.DataFrame([
        {"beach_id": "ca-oc-eh-010", "name": "Doheny", "beach_name": "Doheny State Beach",
         "county": "Orange", "station_code": "EH-010"},
        {"beach_id": "ca-oc-eh-280", "name": "Salt Creek", "beach_name": "Salt Creek Beach",
         "county": "Orange", "station_code": "EH-280"},
    ]))


def _oc_frame(rows: list[dict]) -> pd.DataFrame:
    cols = ["StationID", "SampleDate", "ParameterCode", "Result", "Qualifier"]
    return pd.DataFrame(rows, columns=cols)


def _oc_xlsx_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def test_oc_picks_newest_xlsx_by_filename_date():
    url = _oc_pick_newest_xlsx(OC_DATA_HTML)
    assert url == "https://ocbeachinfo.com/wp-content/uploads/Orange-County-Beach-Monitoring-Data-2026-9.15.2026.xlsx"
    assert _oc_pick_newest_xlsx("<a href='/x.pdf'>none</a>") is None


def test_oc_samples_nd_threshold_window_and_worst_of_day(oc_samples_resolver: StationResolver):
    now = pd.Timestamp("2026-09-20")
    df = _oc_frame([
        {"StationID": "EH-010", "SampleDate": "2026-09-10", "ParameterCode": "Enterococcus", "Result": float("nan"), "Qualifier": "ND"},
        {"StationID": "EH-280", "SampleDate": "2026-09-10", "ParameterCode": "Enterococcus", "Result": 105.0, "Qualifier": "="},
        {"StationID": "EH-280", "SampleDate": "2026-09-10", "ParameterCode": "Enterococcus", "Result": 20.0, "Qualifier": "="},
        {"StationID": "EH-280", "SampleDate": "2026-09-03", "ParameterCode": "Enterococcus", "Result": 104.0, "Qualifier": "="},
        {"StationID": "EH-010", "SampleDate": "2026-09-03", "ParameterCode": "Total Coliform", "Result": 5000.0, "Qualifier": "="},
        {"StationID": "EH-010", "SampleDate": "2026-01-05", "ParameterCode": "Enterococcus", "Result": 500.0, "Qualifier": "="},
        {"StationID": "ZZ-999", "SampleDate": "2026-09-10", "ParameterCode": "Enterococcus", "Result": 10.0, "Qualifier": "<"},
    ])
    out = _oc_samples_from_frame(df, oc_samples_resolver, "https://example/x.xlsx", now)
    by = {(s.station_code, s.sample_date.date().isoformat()): s for s in out}
    assert len(out) == 4  # old (Jan) and non-enterococcus rows dropped
    nd = by[("EH-010", "2026-09-10")]
    assert nd.value == 1.0 and not nd.exceeds_limit and nd.beach_id == "ca-oc-eh-010"
    assert nd.county == "Orange" and nd.analyte == "ENTEROCOCCUS" and nd.source_url == "https://example/x.xlsx"
    worst = by[("EH-280", "2026-09-10")]
    assert worst.value == 105.0 and worst.exceeds_limit
    assert not by[("EH-280", "2026-09-03")].exceeds_limit  # limit is strictly > 104
    assert by[("ZZ-999", "2026-09-10")].beach_id is None


def test_fetch_orange_county_samples_offline(oc_samples_resolver: StationResolver):
    recent = (pd.Timestamp.now() - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    xlsx = _oc_xlsx_bytes(_oc_frame([
        {"StationID": "EH-010", "SampleDate": recent, "ParameterCode": "Enterococcus", "Result": 300.0, "Qualifier": "="},
    ]))
    newest = "https://ocbeachinfo.com/wp-content/uploads/Orange-County-Beach-Monitoring-Data-2026-9.15.2026.xlsx"
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if str(request.url) == "https://ocbeachinfo.com/data/":
            return httpx.Response(200, text=OC_DATA_HTML)
        if str(request.url) == newest:
            return httpx.Response(200, content=xlsx)
        return httpx.Response(404)

    _COLLECTED_SAMPLES.clear()
    try:
        with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            n = fetch_orange_county_samples(client, oc_samples_resolver)
        assert n == 1 and len(_COLLECTED_SAMPLES) == 1
        assert _COLLECTED_SAMPLES[0].exceeds_limit and _COLLECTED_SAMPLES[0].beach_id == "ca-oc-eh-010"
        assert seen[-1] == newest

        _COLLECTED_SAMPLES.clear()
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as client:
            assert fetch_orange_county_samples(client, oc_samples_resolver) == 0  # never raises
        assert _COLLECTED_SAMPLES == []
    finally:
        _COLLECTED_SAMPLES.clear()


def test_fetch_orange_county_samples_finds_renamed_file_via_media_api(oc_samples_resolver: StationResolver):
    """Media library first, by contents: skips a newer unrelated sheet, survives a rename."""
    recent = (pd.Timestamp.now() - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    results = _oc_xlsx_bytes(_oc_frame([
        {"StationID": "EH-010", "SampleDate": recent, "ParameterCode": "Enterococcus", "Result": 30.0, "Qualifier": "="},
    ]))
    unrelated = _oc_xlsx_bytes(pd.DataFrame({"Site": ["x"], "Count": [1]}))
    other = "https://ocbeachinfo.com/wp-content/uploads/OC-Combined-Data.xlsx"
    renamed = "https://ocbeachinfo.com/wp-content/uploads/Some-New-Name-For-2026-Results.xlsx"
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if url.startswith("https://ocbeachinfo.com/wp-json/wp/v2/media"):
            return httpx.Response(200, json=[
                {"date": "2026-10-01T00:00:00", "source_url": other},
                {"date": "2026-09-30T00:00:00", "source_url": renamed},
            ])
        if url == other:
            return httpx.Response(200, content=unrelated)
        if url == renamed:
            return httpx.Response(200, content=results)
        return httpx.Response(404)

    _COLLECTED_SAMPLES.clear()
    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            assert fetch_orange_county_samples(client, oc_samples_resolver) == 1
        assert _COLLECTED_SAMPLES[0].source_url == renamed
        assert not any(u == "https://ocbeachinfo.com/data/" for u in seen)  # no fallback needed
    finally:
        _COLLECTED_SAMPLES.clear()


# ---------- Resolver layer kinds + --heuristic-mode ---------- #


@pytest.fixture
def layer_resolver(tmp_path) -> StationResolver:
    return StationResolver(pd.DataFrame([
        {"beach_id": "ca-x-doheny", "name": "Doheny Site", "beach_name": "Doheny", "county": "Layer",
         "station_code": "DH-1"},
        {"beach_id": "ca-x-site-only", "name": "Zuma Lifeguard Tower", "beach_name": "All_Layer_County",
         "county": "Layer", "station_code": "ZM-1"},
        {"beach_id": "ca-x-malibu-surf", "name": "Malibu Surf Site", "beach_name": "Malibu Surfrider",
         "county": "Layer", "station_code": "MS-1"},
    ]))


def test_resolver_returns_distinct_layer_kinds(layer_resolver: StationResolver):
    r = layer_resolver
    assert r.resolve_all_by_name("Layer", "Doheny") == (["ca-x-doheny"], "exact")
    assert r.resolve_all_by_name("Layer", "Zuma Lifeguard Tower") == (["ca-x-site-only"], "secondary")
    ids, kind = r.resolve_all_by_name("Layer", "Doheny - 100 feet up and down coast of the outlet")
    assert (ids, kind) == (["ca-x-doheny"], "substring")
    assert r.resolve_all_by_name("Layer", "Nowhere Cove") == ([], "miss")


def test_resolver_csv_kind(layer_resolver: StationResolver):
    layer_resolver._alias_lookup[("Layer", _normalize_name("Mystery Beach"))] = ["ca-x-doheny"]
    assert layer_resolver.resolve_all_by_name("Layer", "Mystery Beach") == (["ca-x-doheny"], "csv")


def _adv(area: str) -> CountyAdvisory:
    return CountyAdvisory(
        county="Layer", station_code=None, area=area, advisory_type="Posting",
        started_at=pd.Timestamp("2026-10-02"), advisory_website="", cause="",
    )


def _rpt() -> CountyReport:
    return CountyReport(county="Layer", success=True, last_attempted_at="", source_url="")


def test_report_counts_each_layer_and_lists_heuristic_hits(layer_resolver: StationResolver):
    rpt, sink = _rpt(), []
    advs = [
        _adv("Doheny"),
        _adv("Zuma Lifeguard Tower"),
        _adv("Doheny - 100 feet up and down coast of the outlet"),
        _adv("Nowhere Cove"),
    ]
    out = resolve_advisories(advs, layer_resolver, rpt, unresolved_sink=sink)
    assert len(out) == 3
    assert (rpt.matched_via_exact, rpt.matched_via_secondary, rpt.matched_via_substring) == (1, 1, 1)
    assert rpt.matched_via_live_list == 3  # back-compat: sum of the exact-identity layers
    assert rpt.heuristic_matches == [{
        "posted_name": "Doheny - 100 feet up and down coast of the outlet",
        "beach_id": "ca-x-doheny",
        "kind": "substring",
    }]
    assert [r["scraped_name"] for r in sink] == ["Nowhere Cove"]
    assert sink[0]["suggested_beach_id"] is None


def test_suggest_mode_moves_substring_hit_to_unresolved(layer_resolver: StationResolver):
    rpt, sink = _rpt(), []
    advs = [_adv("Doheny"), _adv("Doheny - 100 feet up and down coast of the outlet")]
    out = resolve_advisories(
        advs, layer_resolver, rpt, unresolved_sink=sink, heuristic_mode="suggest"
    )
    assert [a.beach_id for a in out] == ["ca-x-doheny"]
    assert rpt.matched_via_substring == 0
    assert rpt.unmatched_names == ["Doheny - 100 feet up and down coast of the outlet"]
    assert len(sink) == 1 and sink[0]["suggested_beach_id"] == "ca-x-doheny"
    assert len(rpt.heuristic_matches) == 1


def test_suggest_rows_count_toward_the_gate(layer_resolver: StationResolver):
    from fetch_county_advisories import evaluate_scraper_gate

    sink = []
    advs = [_adv(f"Doheny - decorated posting number {i}") for i in range(7)]
    resolve_advisories(advs, layer_resolver, _rpt(), unresolved_sink=sink, heuristic_mode="suggest")
    verdict = evaluate_scraper_gate(sink, len(advs), [], {})
    assert verdict["passed"] is False


def test_cli_heuristic_mode_defaults_to_suggest(monkeypatch, tmp_path):
    """UPDATE_PLAN 1.3.4: after the alias review, a new heuristic hit must surface for a human
    (unresolved + suggested_beach_id), not post silently."""
    import fetch_county_advisories as f

    captured = {}

    def fake_parse(self, args=None, namespace=None):
        ns = original(self, args=["--curated", str(tmp_path / "missing")], namespace=namespace)
        captured["mode"] = ns.heuristic_mode
        return ns

    import argparse

    original = argparse.ArgumentParser.parse_args
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", fake_parse)
    monkeypatch.setattr(sys, "argv", ["fetch_county_advisories.py"])
    assert f.main() == 1  # curated dir missing → exits right after parsing
    assert captured["mode"] == "suggest"
