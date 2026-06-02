import numpy as np
import pandas as pd
import pytest

from app.data.pipeline.surf_conditions import (
    degrees_to_cardinal,
    build_surf_now,
    build_surf_daily_forecast,
)


def test_degrees_to_cardinal_principal_points():
    assert degrees_to_cardinal(0) == "N"
    assert degrees_to_cardinal(90) == "E"
    assert degrees_to_cardinal(180) == "S"
    assert degrees_to_cardinal(270) == "W"
    assert degrees_to_cardinal(360) == "N"


def test_degrees_to_cardinal_intercardinal():
    assert degrees_to_cardinal(247.5) == "WSW"
    assert degrees_to_cardinal(202.5) == "SSW"
    assert degrees_to_cardinal(45) == "NE"


def test_degrees_to_cardinal_handles_nan():
    assert degrees_to_cardinal(np.nan) is None


def _hourly():
    times = pd.to_datetime(
        ["2026-06-01T00:00", "2026-06-01T01:00", "2026-06-01T02:00"], utc=True
    )
    return pd.DataFrame(
        {
            "station_id": ["32.9_-117.3"] * 3,
            "latitude": [32.9] * 3,
            "longitude": [-117.3] * 3,
            "time_utc": times,
            "wave_height": [1.0, 1.5, 2.0],
            "wave_period": [12.0, 13.0, 14.0],
            "wave_direction": [250.0, 251.0, 252.0],
            "swell_wave_height": [0.8, 0.9, 1.0],
            "swell_wave_period": [16.0, 16.0, 16.0],
            "swell_wave_direction": [205.0, 205.0, 205.0],
            "secondary_swell_wave_height": [0.6, 0.6, 0.6],
            "secondary_swell_wave_period": [7.0, 7.0, 7.0],
            "secondary_swell_wave_direction": [290.0, 290.0, 290.0],
            "wind_wave_height": [0.2, 0.2, 0.2],
        }
    )


def test_build_surf_now_picks_hour_nearest_as_of():
    raw = _hourly()
    as_of = pd.Timestamp("2026-06-01T01:10", tz="UTC")
    now = build_surf_now(raw, as_of=as_of)
    assert len(now) == 1
    row = now.iloc[0]
    # 01:00 is nearest to 01:10
    assert row["wave_height_m"] == pytest.approx(1.5)
    assert row["primary_swell_height_m"] == pytest.approx(0.9)


def test_build_surf_now_adds_cardinal_and_feet():
    raw = _hourly()
    now = build_surf_now(raw, as_of=pd.Timestamp("2026-06-01T01:00", tz="UTC"))
    row = now.iloc[0]
    assert row["primary_swell_direction_cardinal"] == "SSW"
    assert row["secondary_swell_direction_cardinal"] == "WNW"
    # 1.5 m -> ~4.9 ft; min/max bracket it.
    assert row["wave_height_ft_min"] <= 4.92 <= row["wave_height_ft_max"]
    assert row["wave_height_ft_min"] < row["wave_height_ft_max"]


def test_build_surf_now_one_row_per_station():
    raw = pd.concat([_hourly(), _hourly().assign(station_id="33.6_-118.0", latitude=33.6, longitude=-118.0)])
    now = build_surf_now(raw, as_of=pd.Timestamp("2026-06-01T01:00", tz="UTC"))
    assert set(now["station_id"]) == {"32.9_-117.3", "33.6_-118.0"}
    assert len(now) == 2


def test_daily_forecast_summarizes_per_day():
    raw = _hourly()
    daily = build_surf_daily_forecast(raw)
    assert len(daily) == 1  # 00:00-02:00 UTC all fall on 2026-05-31 in Pacific time
    row = daily.iloc[0]
    assert str(row["forecast_date"]) == "2026-05-31"
    assert row["wave_height_m_max"] == pytest.approx(2.0)
    assert row["wave_height_m_mean"] == pytest.approx(1.5)
    # dominant swell direction reported as cardinal
    assert row["primary_swell_direction_cardinal"] == "SSW"


def test_empty_input_returns_empty_with_schema():
    now = build_surf_now(pd.DataFrame(), as_of=pd.Timestamp("2026-06-01", tz="UTC"))
    assert now.empty
    assert "wave_height_m" in now.columns
    daily = build_surf_daily_forecast(pd.DataFrame())
    assert daily.empty
    assert "wave_height_m_max" in daily.columns
