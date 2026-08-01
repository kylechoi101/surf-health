"""The single UV policy shared by the archive and forecast aggregators.

`solar_wind` (Open-Meteo ARCHIVE) feeds the model's `uv_index_24h_max`;
`forecast_weather` (Open-Meteo FORECAST) feeds the served `latest_env.uv_index`.
The archive returns uv_index null — measured 0 non-null across 172,512 cached
hourly rows — so every trained value is the shortwave proxy, while the served
value is real modelled UV, which is why they sit ~43% apart. The proxy rule used
to live in only one of the two modules; the other returned None instead.
"""

import numpy as np
import pytest

from app.data.pipeline.solar_wind import (
    UV_FROM_SHORTWAVE_DIVISOR,
    UV_INDEX_CEILING,
    uv_index_24h_max,
)


def test_prefers_real_uv_when_the_endpoint_supplies_it():
    value, is_proxy = uv_index_24h_max(
        np.array([3.0, 9.0, 5.0]), np.array([900.0, 300.0, 100.0])
    )
    assert value == 9.0
    assert is_proxy is False, "real UV present — must not fall back"


def test_falls_back_to_the_shortwave_proxy_when_uv_is_all_null():
    """The archive case: uv_index is null for every hour."""
    value, is_proxy = uv_index_24h_max(
        np.array([np.nan] * 3), np.array([900.0, 300.0, 100.0])
    )
    assert value == pytest.approx(900.0 / UV_FROM_SHORTWAVE_DIVISOR)
    assert is_proxy is True, "provenance must be explicit, not implied by a comment"


def test_proxy_is_clamped_to_the_ceiling_and_floor():
    assert uv_index_24h_max(None, np.array([5000.0])) == (UV_INDEX_CEILING, True)
    value, _ = uv_index_24h_max(None, np.array([-10.0]))
    assert value == 0.0


def test_returns_nan_when_neither_source_has_data():
    value, is_proxy = uv_index_24h_max(np.array([np.nan]), np.array([np.nan]))
    assert np.isnan(value)
    assert is_proxy is False
    assert np.isnan(uv_index_24h_max(None, None)[0])


def test_forecast_weather_uses_the_same_policy():
    """Previously forecast_weather returned None where solar_wind fell back, so
    an endpoint change would blank the served value while the trained feature
    kept a number."""
    from app.data.pipeline.forecast_weather import _uv_or_none

    assert _uv_or_none(np.array([3.0, 9.0]), np.array([900.0])) == 9.0
    assert _uv_or_none(np.array([np.nan, np.nan]), np.array([900.0])) == pytest.approx(11.25)
    assert _uv_or_none(np.array([np.nan]), np.array([np.nan])) is None
