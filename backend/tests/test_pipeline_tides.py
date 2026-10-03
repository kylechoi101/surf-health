"""``--with-tides``: one NOAA call per mapped station, offline via a fake NOAA response."""
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import httpx
import pandas as pd
import pytest

from app.data.pipeline import cli
from app.services import tides as tides_service

# La Jolla (9410230) and San Francisco (9414290) stations' neighbourhoods
BEACHES = pd.DataFrame(
    {
        "beach_id": ["torrey", "torrey2", "ocean-beach", "nowhere"],
        "latitude": [32.926, 32.926, 37.76, None],
        "longitude": [-117.261, -117.261, -122.51, None],
    }
)


def _noaa_response(hours: int) -> MagicMock:
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None) - timedelta(hours=10)
    preds = [
        {"t": (start + timedelta(hours=h)).strftime("%Y-%m-%d %H:%M"), "v": f"{2.5 * __import__('math').sin(h / 1.98):.3f}"}
        for h in range(hours)
    ]
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"predictions": preds}
    return resp


def _client(failing: set[str] = frozenset()) -> MagicMock:
    client = MagicMock(spec=httpx.Client)

    def get(url, params, timeout):
        if params["station"] in failing:
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 500
            return resp
        return _noaa_response(10 + 96 + 1)

    client.get.side_effect = get
    return client


@pytest.fixture(autouse=True)
def _clear_cache():
    tides_service._CACHE.clear()
    yield
    tides_service._CACHE.clear()


def test_one_call_per_mapped_station_and_covers_72h_ahead():
    client = _client()
    frame = cli.build_tides_frame(BEACHES, client=client)

    # 3 beaches with coordinates, 2 distinct stations -> exactly 2 NOAA calls
    assert client.get.call_count == 2
    assert {c.kwargs["params"]["station"] for c in client.get.call_args_list} == {"9410230", "9414290"}
    assert set(frame["station_id"]) == {"9410230", "9414290"}
    assert list(frame.columns) == [
        "station_id", "station_name", "station_lat", "station_lon",
        "kind", "timestamp", "height", "type",
    ]
    preds = frame[frame["kind"] == "prediction"]
    for _, group in preds.groupby("station_id"):
        assert group["timestamp"].max() >= pd.Timestamp(datetime.now(timezone.utc) + timedelta(hours=72))
    extrema = frame[frame["kind"] == "extremum"]
    assert set(extrema["type"]) == {"H", "L"} and preds["type"].isna().all()
    assert str(frame["timestamp"].dt.tz) == "UTC"


def test_requested_window_is_longer_than_the_routes_and_bypasses_its_cache():
    client = _client()
    cli.build_tides_frame(BEACHES, client=client)
    end = client.get.call_args.kwargs["params"]["end_date"]
    end_dt = datetime.strptime(end, "%Y%m%d %H:%M")
    assert end_dt - datetime.now(timezone.utc).replace(tzinfo=None) > timedelta(hours=90)
    assert tides_service._CACHE == {}


def test_failed_station_keeps_still_future_rows_from_the_previous_file():
    previous = cli.build_tides_frame(BEACHES, client=_client())
    frame = cli.build_tides_frame(BEACHES, previous=previous, client=_client(failing={"9414290"}))
    sf_new = frame[frame["station_id"] == "9414290"]
    assert not sf_new.empty
    assert (sf_new["timestamp"] >= pd.Timestamp(datetime.now(timezone.utc) - timedelta(hours=1))).all()
    assert len(frame[frame["station_id"] == "9410230"]) == len(previous[previous["station_id"] == "9410230"])


def test_all_stations_failing_with_no_previous_yields_an_empty_frame():
    frame = cli.build_tides_frame(BEACHES, client=_client(failing={"9410230", "9414290"}))
    assert frame.empty


def test_cli_writes_tides_parquet(tmp_path, monkeypatch):
    curated = tmp_path / "curated"
    curated.mkdir()
    BEACHES.to_parquet(curated / "beaches.parquet", index=False)
    monkeypatch.setattr(cli, "get_settings", lambda: MagicMock(curated_dir=curated))
    real = cli.build_tides_frame
    monkeypatch.setattr(cli, "build_tides_frame", lambda beaches, **kw: real(beaches, client=_client(), **kw))
    monkeypatch.setattr(sys, "argv", ["cli", "--with-tides"])

    cli.main()

    written = pd.read_parquet(curated / "tides.parquet")
    assert set(written["station_id"]) == {"9410230", "9414290"}
    assert not (curated / "tides.parquet.tmp").exists()


def test_workflow_passes_with_tides():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / ".github/workflows/daily-forecast.yml").read_text()
    assert "--with-tides" in text


def test_station_table_excludes_stations_without_hourly_predictions():
    """9410665 / 9415118 have no MLLW predictions and 9413745 is high/low-only (live NOAA
    check 2026-10-02); beaches near them must resolve to a working neighbour."""
    from app.services.tides import CA_TIDE_STATIONS, nearest_station

    ids = {sid for sid, *_ in CA_TIDE_STATIONS}
    assert not ids & {"9410665", "9415118", "9413745"}
    assert nearest_station(33.7158, -118.2706)[0] == "9410660"  # LA Pilot Station spot
    assert nearest_station(36.9583, -122.0167)[0] == "9413450"  # Santa Cruz spot
