"""Tests for San Diego County direct sample parsing and persistence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from fetch_county_advisories import (  # noqa: E402
    CountySample,
    StationResolver,
    _parse_sd_samples_payload,
    persist_samples,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "county_scrapers"


@pytest.fixture
def sd_samples_payload() -> dict:
    with open(FIXTURES_DIR / "sd_samples_sample.json") as f:
        return json.load(f)


@pytest.fixture
def sd_resolver() -> StationResolver:
    beaches_df = pd.DataFrame([
        {
            "beach_id": "ca068221-san-diego-imperial-beach-municipal-beach-other-ib-050",
            "name": "End of Seacoast Dr",
            "beach_name": "Imperial Beach municipal beach, other",
            "county": "San Diego",
            "station_code": "IB-050",
        },
        {
            "beach_id": "ca068221-san-diego-imperial-beach-municipal-beach-other-eh-010",
            "name": "Cortez Ave",
            "beach_name": "Imperial Beach municipal beach, other",
            "county": "San Diego",
            "station_code": "EH-010",
        },
        {
            "beach_id": "ca624767-san-diego-harbor-beach-oc-100",
            "name": "San Luis Rey River Outlet",
            "beach_name": "Harbor Beach",
            "county": "San Diego",
            "station_code": "OC-100",
        },
        {
            "beach_id": "ca506450-san-diego-san-diego-bay-eh-200",
            "name": "Shelter Island Shoreline Park",
            "beach_name": "San Diego Bay",
            "county": "San Diego",
            "station_code": "EH-200",
        },
        {
            "beach_id": "ca604254-san-diego-coronado-north-beach-eh-060",
            "name": "Coronado North Beach",
            "beach_name": "Coronado north beach",
            "county": "San Diego",
            "station_code": "EH-060",
        },
        {
            "beach_id": "ca606869-san-diego-south-carlsbad-state-beach-en-010",
            "name": "Poinsettia Lane",
            "beach_name": "South Carlsbad State Beach",
            "county": "San Diego",
            "station_code": "EN-010",
        },
    ])
    return StationResolver(beaches_df)


def test_parse_sd_samples_payload_enterococcus_only(sd_samples_payload: dict, sd_resolver: StationResolver):
    """Payload contains 8 items: 6 Enterococcus, 1 Total Coliforms, 1 Fecal Coliforms.
    Only the 6 Enterococcus items must be kept.
    """
    samples = _parse_sd_samples_payload(sd_samples_payload, resolver=sd_resolver)
    assert len(samples) == 6
    assert all(s.analyte == "ENTEROCOCCUS" for s in samples)
    assert all(s.county == "San Diego" for s in samples)


def test_parse_sd_samples_preserves_method_and_units_per_row(sd_samples_payload: dict, sd_resolver: StationResolver):
    samples = _parse_sd_samples_payload(sd_samples_payload, resolver=sd_resolver)
    by_station = {s.station_code: s for s in samples}

    assert by_station["IB-050"].method == "ddPCR"
    assert by_station["IB-050"].units == "Copies/100ml"

    assert by_station["EH-200"].method == "MTF"
    assert by_station["EH-200"].units == "MPN/100ml"

    assert by_station["EH-060"].method == "Enterolert"
    assert by_station["EH-060"].units == "MPN/100ml"

    assert by_station["EN-010"].method == "MF"
    assert by_station["EN-010"].units == "CFU/100ml"


def test_parse_sd_samples_less_than_qualifier_stores_reported_number(sd_samples_payload: dict, sd_resolver: StationResolver):
    """A '<' qualifier stores the reported number as the value."""
    samples = _parse_sd_samples_payload(sd_samples_payload, resolver=sd_resolver)
    by_station = {s.station_code: s for s in samples}

    # OC-100 was '< 195'
    assert by_station["OC-100"].value == 195.0
    # EH-060 was '< 10'
    assert by_station["EH-060"].value == 10.0
    # EN-010 was '< 1'
    assert by_station["EN-010"].value == 1.0


def test_parse_sd_samples_exceedance_limits(sd_samples_payload: dict, sd_resolver: StationResolver):
    """exceeds_limit: ddPCR (copies) > 1413, culture (CFU/MPN) > 104."""
    samples = _parse_sd_samples_payload(sd_samples_payload, resolver=sd_resolver)
    by_station = {s.station_code: s for s in samples}

    # IB-050: ddPCR 5099 > 1413 -> True
    assert by_station["IB-050"].exceeds_limit is True
    # EH-010: ddPCR 756 <= 1413 -> False
    assert by_station["EH-010"].exceeds_limit is False
    # OC-100: ddPCR 195 <= 1413 -> False
    assert by_station["OC-100"].exceeds_limit is False

    # EH-200: MTF (culture) 344 > 104 -> True
    assert by_station["EH-200"].exceeds_limit is True
    # EH-060: Enterolert (culture) 10 <= 104 -> False
    assert by_station["EH-060"].exceeds_limit is False
    # EN-010: MF (culture) 1 <= 104 -> False
    assert by_station["EN-010"].exceeds_limit is False


def test_parse_sd_samples_boundary_exceedances():
    """Verify exact 1413 and 104 boundaries."""
    payload = {
        "versionInfo": {"hasModuleVersionChanged": False, "hasApiVersionChanged": False},
        "data": {
            "List": {
                "List": [
                    {
                        "Parameter": {"Label": "Enterococcus"},
                        "AnalysisMethod": {"Label": "ddPCR"},
                        "Units": {"Label": "Copies/100ml"},
                        "Sample": {"SampleDate": "2026-10-01", "Result": "1413", "Qualifier": "="},
                        "Site": {"StationID": "TEST-1", "LocationName": "Test 1"},
                    },
                    {
                        "Parameter": {"Label": "Enterococcus"},
                        "AnalysisMethod": {"Label": "ddPCR"},
                        "Units": {"Label": "Copies/100ml"},
                        "Sample": {"SampleDate": "2026-10-01", "Result": "1413.1", "Qualifier": "="},
                        "Site": {"StationID": "TEST-2", "LocationName": "Test 2"},
                    },
                    {
                        "Parameter": {"Label": "Enterococcus"},
                        "AnalysisMethod": {"Label": "Enterolert"},
                        "Units": {"Label": "MPN/100ml"},
                        "Sample": {"SampleDate": "2026-10-01", "Result": "104", "Qualifier": "="},
                        "Site": {"StationID": "TEST-3", "LocationName": "Test 3"},
                    },
                    {
                        "Parameter": {"Label": "Enterococcus"},
                        "AnalysisMethod": {"Label": "Enterolert"},
                        "Units": {"Label": "MPN/100ml"},
                        "Sample": {"SampleDate": "2026-10-01", "Result": "104.1", "Qualifier": "="},
                        "Site": {"StationID": "TEST-4", "LocationName": "Test 4"},
                    },
                ]
            }
        },
    }
    samples = _parse_sd_samples_payload(payload)
    by_station = {s.station_code: s for s in samples}
    assert by_station["TEST-1"].exceeds_limit is False
    assert by_station["TEST-2"].exceeds_limit is True
    assert by_station["TEST-3"].exceeds_limit is False
    assert by_station["TEST-4"].exceeds_limit is True


def test_parse_sd_samples_resolver_resolves_beach_ids(sd_samples_payload: dict, sd_resolver: StationResolver):
    samples = _parse_sd_samples_payload(sd_samples_payload, resolver=sd_resolver)
    by_station = {s.station_code: s for s in samples}

    assert by_station["IB-050"].beach_id == "ca068221-san-diego-imperial-beach-municipal-beach-other-ib-050"
    assert by_station["EH-010"].beach_id == "ca068221-san-diego-imperial-beach-municipal-beach-other-eh-010"
    assert by_station["EH-200"].beach_id == "ca506450-san-diego-san-diego-bay-eh-200"

    # Per Correction 2026-10-12 20:10: must resolve by station code ONLY, no name fallback.
    # An item whose station code is missing or not in lookup keeps beach_id None even if name matches.
    payload_name_only = {
        "versionInfo": {"hasModuleVersionChanged": False, "hasApiVersionChanged": False},
        "data": {
            "List": {
                "List": [
                    {
                        "Parameter": {"Label": "Enterococcus"},
                        "AnalysisMethod": {"Label": "ddPCR"},
                        "Units": {"Label": "Copies/100ml"},
                        "Sample": {"SampleDate": "2026-10-01", "Result": "500", "Qualifier": "="},
                        "Site": {
                            "StationID": "UNKNOWN-999",
                            "BeachName": "Imperial Beach municipal beach, other",
                            "LocationName": "End of Seacoast Dr",
                        },
                    }
                ]
            }
        },
    }
    unmatched_samples = _parse_sd_samples_payload(payload_name_only, resolver=sd_resolver)
    assert len(unmatched_samples) == 1
    assert unmatched_samples[0].beach_id is None


def test_parse_sd_samples_api_version_changed_or_exception():
    data_changed = {
        "versionInfo": {"hasModuleVersionChanged": False, "hasApiVersionChanged": True},
        "data": {"List": {"List": [{"Parameter": {"Label": "Enterococcus"}}]}},
    }
    assert _parse_sd_samples_payload(data_changed) == []

    data_exception = {
        "versionInfo": {"hasModuleVersionChanged": False, "hasApiVersionChanged": False},
        "exception": "internal error",
        "data": {"List": {"List": [{"Parameter": {"Label": "Enterococcus"}}]}},
    }
    assert _parse_sd_samples_payload(data_exception) == []


def test_persist_samples_stores_method_and_units(tmp_path: Path):
    """persist_samples writes method and units columns to parquet, preserving nullable values."""
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()

    samples = [
        CountySample(
            county="San Diego",
            area="End of Seacoast Dr",
            sample_date=pd.Timestamp("2026-10-01"),
            analyte="ENTEROCOCCUS",
            value=2509.0,
            exceeds_limit=True,
            source_url="https://cosdapps.sandiegocounty.gov/sdbeachinfo/",
            station_code="IB-050",
            beach_id="ca-sd-ib-050",
            method="ddPCR",
            units="Copies/100ml",
        ),
        CountySample(
            county="San Francisco",
            area="Ocean Beach",
            sample_date=pd.Timestamp("2026-10-01"),
            analyte="ENTEROCOCCUS",
            value=10.0,
            exceeds_limit=False,
            source_url="https://data.sfgov.org/",
            station_code="OB-1",
            beach_id="ca-sf-ob-1",
            method=None,
            units=None,
        ),
    ]

    n_new, n_total = persist_samples(samples, curated_dir)
    assert n_new == 2
    assert n_total == 2

    df = pd.read_parquet(curated_dir / "county_direct_samples.parquet")
    assert "method" in df.columns
    assert "units" in df.columns
    assert len(df) == 2

    sd_row = df[df["county"] == "San Diego"].iloc[0]
    assert sd_row["method"] == "ddPCR"
    assert sd_row["units"] == "Copies/100ml"

    sf_row = df[df["county"] == "San Francisco"].iloc[0]
    assert pd.isna(sf_row["method"]) or sf_row["method"] is None
    assert pd.isna(sf_row["units"]) or sf_row["units"] is None


def test_persist_samples_preserves_existing_legacy_parquet_without_method_units(tmp_path: Path):
    """Old parquet files without method/units columns remain valid and can be appended to."""
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()

    # Create a legacy parquet without method/units
    legacy_df = pd.DataFrame([{
        "county": "Orange",
        "beach_id": "ca-oc-1",
        "area": "Doheny",
        "station_code": "DH-1",
        "sample_date": pd.Timestamp("2026-09-01"),
        "analyte": "ENTEROCOCCUS",
        "value": 10.0,
        "exceeds_limit": False,
        "source_url": "http://example.com",
    }])
    legacy_df.to_parquet(curated_dir / "county_direct_samples.parquet", index=False)

    new_samples = [
        CountySample(
            county="San Diego",
            area="End of Seacoast Dr",
            sample_date=pd.Timestamp("2026-10-01"),
            analyte="ENTEROCOCCUS",
            value=2509.0,
            exceeds_limit=True,
            source_url="https://cosdapps.sandiegocounty.gov/sdbeachinfo/",
            station_code="IB-050",
            beach_id="ca-sd-ib-050",
            method="ddPCR",
            units="Copies/100ml",
        )
    ]
    n_new, n_total = persist_samples(new_samples, curated_dir)
    assert n_new == 1
    assert n_total == 2

    df = pd.read_parquet(curated_dir / "county_direct_samples.parquet")
    assert "method" in df.columns
    assert "units" in df.columns
    assert len(df) == 2
    assert pd.isna(df.loc[df["county"] == "Orange", "method"].iloc[0])
    assert df.loc[df["county"] == "San Diego", "method"].iloc[0] == "ddPCR"
