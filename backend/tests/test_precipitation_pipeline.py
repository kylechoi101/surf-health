"""Tests for precipitation aggregation: cutoff safety, AWI, first-flush."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.data.pipeline.precipitation import (
    _forecast_cutoff_utc,
    aggregate_precip_windows,
    compute_antecedent_wetness_index,
    compute_first_flush_flag,
)


def _make_precip_row(station_id: str, time_utc: str, precip_mm: float) -> dict:
    return {
        "station_id": station_id,
        "time_utc": time_utc,
        "precip_mm_increment": precip_mm,
        "latitude": 33.0,
        "longitude": -117.3,
        "elevation_m": 5.0,
        "source_name": "noaa_nws",
    }


class TestAggregatePrecipWindows:
    def test_empty_input_returns_correct_columns(self):
        result = aggregate_precip_windows(pd.DataFrame())
        assert "station_id" in result.columns
        assert "precip_mm_24h" in result.columns
        assert "precip_awi" in result.columns
        assert "first_flush_flag" in result.columns
        assert len(result) == 0

    def test_post_cutoff_increments_excluded(self):
        """Precipitation at or after 5 AM PT cutoff must not enter any window.

        January date used so PST applies (5 AM PST = 13:00 UTC, unambiguous).
        """
        test_date = date(2026, 1, 10)
        cutoff = _forecast_cutoff_utc(test_date)  # 13:00 UTC
        rows = [
            _make_precip_row("KLAX", (cutoff - pd.Timedelta(hours=2)).isoformat(), 5.0),
            _make_precip_row("KLAX", (cutoff - pd.Timedelta(hours=1)).isoformat(), 5.0),
            _make_precip_row("KLAX", cutoff.isoformat(), 999.0),                          # at cutoff
            _make_precip_row("KLAX", (cutoff + pd.Timedelta(hours=2)).isoformat(), 999.0), # after
        ]
        result = aggregate_precip_windows(pd.DataFrame(rows))
        day_row = result[result["sample_date"] == test_date]
        assert len(day_row) == 1
        assert day_row.iloc[0]["precip_mm_24h"] == pytest.approx(10.0)

    def test_window_sums_accumulate_correctly(self):
        # January (PST): cutoff = 13:00 UTC; use 10/11/12 UTC (3h/2h/1h before cutoff)
        rows = [
            _make_precip_row("KLAX", "2026-01-10T10:00:00+00:00", 2.0),
            _make_precip_row("KLAX", "2026-01-10T11:00:00+00:00", 3.0),
            _make_precip_row("KLAX", "2026-01-10T12:00:00+00:00", 4.0),
        ]
        result = aggregate_precip_windows(pd.DataFrame(rows))
        day_row = result[result["sample_date"] == date(2026, 1, 10)].iloc[0]
        assert day_row["precip_mm_1h"] == pytest.approx(4.0)
        assert day_row["precip_mm_6h"] == pytest.approx(9.0)
        assert day_row["precip_mm_24h"] == pytest.approx(9.0)

    def test_duplicate_station_timestamp_removed(self):
        rows = [
            _make_precip_row("KLAX", "2026-01-10T10:00:00+00:00", 5.0),
            _make_precip_row("KLAX", "2026-01-10T10:00:00+00:00", 10.0),  # duplicate
        ]
        result = aggregate_precip_windows(pd.DataFrame(rows))
        day_row = result[result["sample_date"] == date(2026, 1, 10)]
        assert len(day_row) == 1
        assert day_row.iloc[0]["precip_mm_24h"] == pytest.approx(10.0)  # keep-last


class TestComputeAntecedentWetnessIndex:
    def test_awi_increases_monotonically_with_sustained_rain(self):
        rain = pd.Series([10.0, 10.0, 10.0, 10.0, 10.0])
        awi = compute_antecedent_wetness_index(rain)
        # AWI is based on prior rainfall; should increase each day with sustained input
        assert awi.iloc[2] > awi.iloc[1]
        assert awi.iloc[3] > awi.iloc[2]

    def test_awi_uses_prior_day_not_current(self):
        # First row of prior-shifted series is 0; AWI[0] should be 0
        rain = pd.Series([100.0, 0.0, 0.0])
        awi = compute_antecedent_wetness_index(rain)
        assert awi.iloc[0] == pytest.approx(0.0)

    def test_awi_decays_after_no_rain(self):
        rain = pd.Series([20.0, 0.0, 0.0, 0.0, 0.0])
        awi = compute_antecedent_wetness_index(rain)
        # After initial rain, values should decay toward zero
        assert awi.iloc[2] < awi.iloc[1]
        assert awi.iloc[3] < awi.iloc[2]


class TestComputeFirstFlushFlag:
    def test_first_flush_triggered_after_dry_spell(self):
        # 3 dry days then heavy rain
        rain = pd.Series([0.0, 0.0, 0.0, 25.0])
        flags = compute_first_flush_flag(rain, dry_days=3, threshold_mm=12.7)
        assert flags.iloc[3] == 1

    def test_no_flush_if_recent_rain(self):
        # Rain on day 1 prevents first-flush trigger on day 3
        rain = pd.Series([5.0, 0.0, 25.0])
        flags = compute_first_flush_flag(rain, dry_days=3, threshold_mm=12.7)
        assert flags.iloc[2] == 0

    def test_no_flush_if_below_threshold(self):
        rain = pd.Series([0.0, 0.0, 0.0, 5.0])  # below 12.7 mm
        flags = compute_first_flush_flag(rain, dry_days=3, threshold_mm=12.7)
        assert flags.iloc[3] == 0

    def test_no_flush_on_dry_day(self):
        rain = pd.Series([0.0, 0.0, 0.0, 0.0])
        flags = compute_first_flush_flag(rain, dry_days=3, threshold_mm=12.7)
        assert flags.sum() == 0
