import pandas as pd

from app.data.pipeline.ceden import (
    build_ceden_datastore_sql,
    build_ceden_station_crosswalk,
    fetch_ceden_datastore_subset,
    merge_ceden_into_beachwatch_bundle,
    normalize_ceden_results,
    normalize_ceden_sites,
)


def test_normalize_ceden_results_keeps_enterococcus_and_tracks_source():
    frame = pd.DataFrame(
        [
            {
                "StationName": "EH-060-Coronado north beach, San Diego",
                "StationCode": "EH-060",
                "Analyte": "Enterococcus",
                "MethodName": "EPA 1600",
                "Unit": "CFU/100 mL",
                "Result": "120",
                "ResultSub": "118",
                "DataSource": "CEDEN",
                "SampleDateTime": "2026-04-21T09:00:00",
                "TargetLatitude": "32.6855",
                "TargetLongitude": "-117.194",
            },
            {
                "StationName": "EH-060-Coronado north beach, San Diego",
                "StationCode": "EH-060",
                "Analyte": "E. Coli",
                "MethodName": "EPA 1600",
                "Unit": "CFU/100 mL",
                "Result": "80",
                "DataSource": "CEDEN",
                "SampleDateTime": "2026-04-21T09:00:00",
            },
        ]
    )

    normalized = normalize_ceden_results(frame, stv_threshold=104.0)

    assert len(normalized) == 1
    assert normalized.iloc[0]["station_code"] == "EH-060"
    assert normalized.iloc[0]["analyte"] == "enterococcus"
    assert normalized.iloc[0]["value"] == 118.0
    assert bool(normalized.iloc[0]["exceeds_stv"]) is True
    assert normalized.iloc[0]["data_source"] == "CEDEN.SafeToSwim"


def test_build_ceden_station_crosswalk_matches_station_code():
    ceden_sites = normalize_ceden_sites(
        pd.DataFrame(
            [
                {
                    "StationName": "EH-060-Coronado north beach, San Diego",
                    "StationCode": "EH-060",
                    "TargetLatitude": "32.6855",
                    "TargetLongitude": "-117.194",
                },
                {
                    "StationName": "Los Angeles River at Del Amo Bridge",
                    "StationCode": "412LARDAB",
                    "TargetLatitude": "33.846",
                    "TargetLongitude": "-118.210",
                },
            ]
        )
    )
    beachwatch_stations = pd.DataFrame(
        [
            {
                "beach_id": "ca604254-san-diego-coronado-north-beach-eh-060",
                "name": "EH-060",
                "county": "San Diego",
                "latitude": 32.6855,
                "longitude": -117.194,
            }
        ]
    )

    crosswalk = build_ceden_station_crosswalk(ceden_sites, beachwatch_stations)

    assert len(crosswalk) == 1
    assert crosswalk.iloc[0]["station_code"] == "EH-060"
    assert crosswalk.iloc[0]["beach_id"] == "ca604254-san-diego-coronado-north-beach-eh-060"
    assert crosswalk.iloc[0]["match_method"] == "station_code"


def test_merge_ceden_into_beachwatch_bundle_prefers_existing_beachwatch_duplicates():
    stations = pd.DataFrame(
        [
            {
                "beach_id": "ca604254-san-diego-coronado-north-beach-eh-060",
                "name": "EH-060",
                "county": "San Diego",
                "region": "San Diego",
                "support_status": "production",
                "latest_official_sample_at": pd.Timestamp("2026-04-20T09:00:00"),
                "latitude": 32.6855,
                "longitude": -117.194,
                "usepa_id": "CA604254",
                "station_code": "EH-060",
                "water_body_class": "Saltwater",
                "water_body_type": "Open Coast",
                "agency_name": "County Lab",
                "zip_code": "92118",
            }
        ]
    )
    observations = pd.DataFrame(
        [
            {
                "beach_id": "ca604254-san-diego-coronado-north-beach-eh-060",
                "sample_time": pd.Timestamp("2026-04-20T09:00:00"),
                "sample_date": pd.Timestamp("2026-04-20").date(),
                "analyte": "enterococcus",
                "method": "EPA 1600",
                "units": "CFU/100ml",
                "value": 80.0,
                "exceeds_stv": False,
                "county": "San Diego",
                "station_name": "EH-060",
                "beach_name": "Coronado north beach",
                "usepa_id": "CA604254",
                "station_code": "EH-060",
                "weather": "Sunny",
                "storm_drain_flow": "No",
                "tidal_height": 1.2,
                "surf_height_observed": 2.0,
                "turbidity_observed": 5.0,
                "odor": "None",
                "water_color": "Blue",
                "data_source": "BeachWatch",
            }
        ]
    )
    advisories = pd.DataFrame(columns=["beach_id", "advisory_type", "started_at", "ended_at", "status", "cause", "county"])
    ceden_results_raw = pd.DataFrame(
        [
            {
                "StationName": "EH-060-Coronado north beach, San Diego",
                "StationCode": "EH-060",
                "Analyte": "Enterococcus",
                "MethodName": "EPA 1600",
                "Unit": "CFU/100ml",
                "Result": "80",
                "ResultSub": "80",
                "DataSource": "BeachWatch",
                "SampleDateTime": "2026-04-20T09:00:00",
                "TargetLatitude": "32.6855",
                "TargetLongitude": "-117.194",
            },
            {
                "StationName": "EH-060-Coronado north beach, San Diego",
                "StationCode": "EH-060",
                "Analyte": "Enterococcus",
                "MethodName": "EPA 1600",
                "Unit": "CFU/100ml",
                "Result": "140",
                "ResultSub": "140",
                "DataSource": "CEDEN",
                "SampleDateTime": "2026-04-21T09:00:00",
                "TargetLatitude": "32.6855",
                "TargetLongitude": "-117.194",
            },
        ]
    )
    ceden_sites_raw = pd.DataFrame(
        [
            {
                "StationName": "EH-060-Coronado north beach, San Diego",
                "StationCode": "EH-060",
                "TargetLatitude": "32.6855",
                "TargetLongitude": "-117.194",
            }
        ]
    )

    bundle = merge_ceden_into_beachwatch_bundle(
        stations=stations,
        observations=observations,
        advisories=advisories,
        ceden_results_raw=ceden_results_raw,
        ceden_sites_raw=ceden_sites_raw,
        stv_threshold=104.0,
    )

    merged = bundle["observations"].sort_values("sample_time").reset_index(drop=True)
    assert len(merged) == 2
    assert list(merged["data_source"]) == ["BeachWatch", "CEDEN.SafeToSwim"]
    assert merged.iloc[-1]["value"] == 140.0
    assert bundle["stations"].iloc[0]["latest_official_sample_at"] == pd.Timestamp("2026-04-21T09:00:00")
    assert len(bundle["ceden_crosswalk"]) == 1
    assert len(bundle["beach_day"]) == 2


def test_merge_ceden_collapses_mirrored_safe_to_swim_rows_despite_unit_formatting():
    stations = pd.DataFrame(
        [
            {
                "beach_id": "ca400333-san-mateo-oyster-point-marina-oyster-point-marina",
                "name": "Oyster Point Marina",
                "county": "San Mateo",
                "region": "San Francisco Bay",
                "support_status": "production",
                "latest_official_sample_at": pd.Timestamp("2022-12-05T08:05:00"),
                "latitude": 37.665,
                "longitude": -122.386,
                "usepa_id": "CA400333",
                "station_code": "Oyster Point Marina",
                "water_body_class": "Saltwater",
                "water_body_type": "Bay",
                "agency_name": "County Lab",
                "zip_code": "94080",
            }
        ]
    )
    observations = pd.DataFrame(
        [
            {
                "beach_id": "ca400333-san-mateo-oyster-point-marina-oyster-point-marina",
                "sample_time": pd.Timestamp("2022-12-05T08:05:00"),
                "sample_date": pd.Timestamp("2022-12-05").date(),
                "analyte": "enterococcus",
                "method": "Enterolert",
                "units": "MPN/100ml",
                "value": 171.0,
                "exceeds_stv": True,
                "county": "San Mateo",
                "station_name": "Oyster Point Marina",
                "beach_name": "Oyster Point Marina",
                "usepa_id": "CA400333",
                "station_code": "Oyster Point Marina",
                "weather": None,
                "storm_drain_flow": None,
                "tidal_height": None,
                "surf_height_observed": None,
                "turbidity_observed": None,
                "odor": None,
                "water_color": None,
                "data_source": "BeachWatch",
            }
        ]
    )
    advisories = pd.DataFrame(columns=["beach_id", "advisory_type", "started_at", "ended_at", "status", "cause", "county"])
    ceden_results_raw = pd.DataFrame(
        [
            {
                "StationName": "Oyster Point Marina, San Mateo",
                "StationCode": "Oyster Point Marina",
                "Analyte": "Enterococcus",
                "MethodName": "Enterolert",
                "Unit": "MPN/100 mL",
                "Result": "171",
                "ResultSub": "171",
                "DataSource": "BeachWatch",
                "SampleDateTime": "2022-12-05T08:05:00",
                "TargetLatitude": "37.665",
                "TargetLongitude": "-122.386",
            }
        ]
    )
    ceden_sites_raw = pd.DataFrame(
        [
            {
                "StationName": "Oyster Point Marina, San Mateo",
                "StationCode": "Oyster Point Marina",
                "TargetLatitude": "37.665",
                "TargetLongitude": "-122.386",
            }
        ]
    )

    bundle = merge_ceden_into_beachwatch_bundle(
        stations=stations,
        observations=observations,
        advisories=advisories,
        ceden_results_raw=ceden_results_raw,
        ceden_sites_raw=ceden_sites_raw,
        stv_threshold=104.0,
    )

    assert len(bundle["observations"]) == 1
    assert bundle["observations"].iloc[0]["data_source"] == "BeachWatch"


def test_build_ceden_datastore_sql_filters_enterococcus_and_station_codes():
    sql = build_ceden_datastore_sql(
        resource_id="resource-id",
        station_codes=["EH-060", "0"],
        limit=100,
        offset=200,
    )

    assert 'FROM "resource-id"' in sql
    assert 'LOWER("Analyte") = \'enterococcus\'' in sql
    assert '"StationCode" IN (\'0\', \'EH-060\')' in sql
    assert 'LIMIT 100 OFFSET 200' in sql


class _DummyResponse:
    def __init__(self, records):
        self._records = records

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"result": {"records": self._records}}


class _DummyClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.queries = []

    def get(self, url, params, timeout):
        self.queries.append((url, params["sql"]))
        records = self.pages.pop(0) if self.pages else []
        return _DummyResponse(records)

    def close(self) -> None:
        return None


def test_fetch_ceden_datastore_subset_pages_and_caches(tmp_path):
    client = _DummyClient(
        pages=[
            [
                {
                    "StationName": "EH-060-Coronado north beach, San Diego",
                    "StationCode": "EH-060",
                    "Analyte": "Enterococcus",
                    "Result": "80",
                    "SampleDateTime": "2026-04-21T09:00:00",
                }
            ],
            [],
        ]
    )
    cache_path = tmp_path / "ceden_subset.csv"

    frame = fetch_ceden_datastore_subset(
        resource_id="resource-id",
        station_codes=["EH-060"],
        max_rows=100,
        batch_size=50,
        cache_path=cache_path,
        client=client,
    )

    assert len(frame) == 1
    assert cache_path.exists()
    assert len(client.queries) == 1
