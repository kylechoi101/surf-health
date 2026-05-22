"""Tests for the NOAA CO-OPS tide service and the /tides API route."""
import math
import os
from unittest.mock import MagicMock

os.environ["PREFERRED_REPOSITORY"] = "fixture"

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import routes  # noqa: F401  (ensures app is wired)
from app.main import app
from app.services import tides as tides_service


client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_tide_cache():
    tides_service._CACHE.clear()
    yield
    tides_service._CACHE.clear()


def _sample_noaa_payload() -> dict:
    """A short, well-formed NOAA CO-OPS predictions response."""
    return {
        "predictions": [
            {"t": "2026-05-20 00:00", "v": "1.20"},
            {"t": "2026-05-20 01:00", "v": "2.40"},
            {"t": "2026-05-20 02:00", "v": "3.00"},  # local max
            {"t": "2026-05-20 03:00", "v": "2.10"},
            {"t": "2026-05-20 04:00", "v": "0.50"},  # local min
            {"t": "2026-05-20 05:00", "v": "1.10"},
            {"t": "2026-05-20 06:00", "v": "2.80"},  # local max
            {"t": "2026-05-20 07:00", "v": "2.10"},
        ]
    }


# -- nearest_station ---------------------------------------------------------


def test_nearest_station_picks_la_jolla_for_torrey_pines():
    """Torrey Pines State Beach is at ~32.93°N, -117.26°W. La Jolla (9410230)
    at 32.8669, -117.2571 is the closest station, much closer than San Diego
    or any other CA station."""
    sid, name, dist_km = tides_service.nearest_station(32.926, -117.261)
    assert sid == "9410230"
    assert "La Jolla" in name
    assert dist_km < 10  # La Jolla station is well within 10 km


def test_nearest_station_picks_san_francisco_for_ocean_beach_sf():
    """Ocean Beach SF (~37.76°N, -122.51°W) should pick the SF station."""
    sid, _, dist_km = tides_service.nearest_station(37.76, -122.51)
    # SF (9414290) or Alameda (9414750) are both candidates; either is
    # acceptable as long as the picked one is genuinely closest. SF is
    # closer for Ocean Beach by haversine.
    assert sid in {"9414290", "9414750"}
    assert dist_km < 25


# -- detect_extrema ---------------------------------------------------------


def test_detect_extrema_finds_expected_highs_and_lows():
    """The sample payload has 2 highs (02:00, 06:00) and 1 low (04:00)."""
    payload = _sample_noaa_payload()
    series = tides_service._parse_noaa_predictions(payload)
    extrema = tides_service.detect_extrema(series)
    highs = [e for e in extrema if e["type"] == "H"]
    lows = [e for e in extrema if e["type"] == "L"]
    assert len(highs) == 2
    assert len(lows) == 1
    # _parse_noaa_predictions normalizes to ISO-8601 UTC ("...Z") so JS
    # frontends parse the timestamps unambiguously instead of treating them
    # as local time. detect_extrema preserves the same format.
    assert highs[0]["t"] == "2026-05-20T02:00:00Z"
    assert lows[0]["t"] == "2026-05-20T04:00:00Z"


def test_detect_extrema_on_synthetic_sin_wave_returns_expected_count():
    """A sin wave over 48 hours with 12.42 h period (M2 tide) at 1-hour
    resolution should produce ~4 H and ~4 L crossings (semidiurnal tides
    give roughly 2 highs + 2 lows per 24 h)."""
    series = []
    for hour in range(48):
        # M2 semidiurnal period = ~12.42 h
        v = 2.5 * math.sin(2 * math.pi * hour / 12.42)
        series.append({"t": f"hour-{hour:02d}", "v": v})
    extrema = tides_service.detect_extrema(series)
    highs = [e for e in extrema if e["type"] == "H"]
    lows = [e for e in extrema if e["type"] == "L"]
    # 48h / 12.42h ≈ 3.86 cycles → expect 3-4 highs and 3-4 lows
    assert 3 <= len(highs) <= 4
    assert 3 <= len(lows) <= 4


# -- fetch_tides connector ---------------------------------------------------


def _mock_response(status_code: int, json_body: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body
    return resp


def test_fetch_tides_returns_standardized_payload(monkeypatch):
    """Mock NOAA response and verify shape + station resolution."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = _mock_response(200, _sample_noaa_payload())

    payload = tides_service.fetch_tides(32.926, -117.261, _client=mock_client)

    assert payload is not None
    assert payload["station_id"] == "9410230"
    assert "La Jolla" in payload["station_name"]
    assert payload["station_distance_km"] >= 0
    assert len(payload["predictions"]) == 8
    assert payload["predictions"][0] == {"t": "2026-05-20T00:00:00Z", "v": 1.20}
    assert len(payload["extrema"]) == 3  # 2 H + 1 L

    # Verify the NOAA URL + key params were used
    call = mock_client.get.call_args
    assert call.args[0] == tides_service._NOAA_DATAGETTER
    params = call.kwargs["params"]
    assert params["product"] == "predictions"
    assert params["datum"] == "MLLW"
    assert params["time_zone"] == "gmt"  # UTC end-to-end; frontend localizes via JS Date
    assert params["station"] == "9410230"
    assert params["format"] == "json"


def test_fetch_tides_returns_none_on_http_error(monkeypatch):
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = _mock_response(500, {})
    payload = tides_service.fetch_tides(32.7, -117.17, _client=mock_client)
    assert payload is None


def test_fetch_tides_caches_per_station(monkeypatch):
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = _mock_response(200, _sample_noaa_payload())

    first = tides_service.fetch_tides(32.7142, -117.1736, _client=mock_client)
    second = tides_service.fetch_tides(32.7142, -117.1736, _client=mock_client)
    assert first is second
    assert mock_client.get.call_count == 1  # second call served from cache


# -- /tides API route -------------------------------------------------------


def test_tides_endpoint_returns_payload(monkeypatch):
    """End-to-end: route looks up beach lat/lon and returns tide JSON."""
    def fake_fetch_tides(lat, lon):
        return {
            "station_id": "9410230",
            "station_name": "La Jolla",
            "station_distance_km": 2.5,
            "predictions": [{"t": "2026-05-20 00:00", "v": 1.2}],
            "extrema": [],
        }

    monkeypatch.setattr("app.services.tides.fetch_tides", fake_fetch_tides)

    response = client.get("/beaches/scripps-pier/tides")
    assert response.status_code == 200
    body = response.json()
    assert body["beach_id"] == "scripps-pier"
    assert body["station_id"] == "9410230"
    assert "predictions" in body
    assert "extrema" in body
    assert response.headers["cache-control"].startswith("public, max-age=21600")


def test_tides_endpoint_502_when_upstream_unavailable(monkeypatch):
    monkeypatch.setattr("app.services.tides.fetch_tides", lambda lat, lon: None)
    response = client.get("/beaches/scripps-pier/tides")
    assert response.status_code == 502
