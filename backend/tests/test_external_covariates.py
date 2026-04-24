import asyncio

import pandas as pd

from app.data.pipeline.external_covariates import (
    assign_nearest_cdip_station,
    assign_nearest_erddap_source,
    fetch_epa_uv_daily,
    parse_cdip_summary,
)


class _DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _DummyClient:
    def __init__(self, payload):
        self.payload = payload
        self.urls: list[str] = []

    async def get(self, url: str, timeout: float):
        self.urls.append(url)
        return _DummyResponse(self.payload)


def test_parse_cdip_summary_and_assign_nearest_station_skips_missing_coordinates():
    summary = parse_cdip_summary(
        "\n".join(
            [
                "meta\t191\tTorrey Pines Outer, CA\t32.932\t-117.290\t10\t1.5\t12\t270\t16.1",
                "meta\t073\tSan Pedro South, CA\t33.650\t-118.230\t15\t0.8\t10\t240\t15.0",
            ]
        )
    )

    stations = pd.DataFrame(
        [
            {"beach_id": "near-torrey", "latitude": 32.93, "longitude": -117.29},
            {"beach_id": "missing-coords", "latitude": None, "longitude": -117.8},
        ]
    )

    assignments = assign_nearest_cdip_station(stations, summary, max_distance_km=20.0)

    assert list(assignments["beach_id"]) == ["near-torrey"]
    assert assignments.iloc[0]["cdip_station_id"] == "191"


def test_assign_nearest_erddap_source_skips_stations_without_coordinates():
    stations = pd.DataFrame(
        [
            {"beach_id": "del-mar", "latitude": 32.93, "longitude": -117.32},
            {"beach_id": "missing", "latitude": None, "longitude": None},
        ]
    )

    assignments = assign_nearest_erddap_source(stations)

    assert list(assignments["beach_id"]) == ["del-mar"]
    assert assignments.iloc[0]["erddap_source_name"] == "cencoos_del_mar_mooring"


def test_fetch_epa_uv_daily_uses_validated_endpoint_and_parses_payload():
    client = _DummyClient(
        [
            {
                "ZIP_CODE": "92037",
                "CITY": "San Diego",
                "STATE": "CA",
                "UV_INDEX": "9",
                "UV_ALERT": "0",
                "DATE": "Apr/20/2026",
            }
        ]
    )

    frame = asyncio.run(fetch_epa_uv_daily(client, ["92037"]))

    assert client.urls == ["https://data.epa.gov/efservice/getEnvirofactsUVDAILY/ZIP/92037/JSON"]
    assert len(frame) == 1
    assert frame.iloc[0]["zip_code"] == "92037"
    assert frame.iloc[0]["uv_index"] == 9.0
    assert frame.iloc[0]["forecast_date"] == "2026-04-20"
