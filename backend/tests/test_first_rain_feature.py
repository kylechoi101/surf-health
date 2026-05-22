"""Tests for the first-rain-after-dry-spell feature.

Council provenance: 5-Opus+Sonnet council voted 4-of-5 for Hermes' proposal
("First-Rain-After-Dry-Spell feature") as the top priority improvement
2026-05-19. Mechanism: dry-spell accumulation of fecal matter on impervious
surfaces mobilizes during the first rain event, producing disproportionate
bacterial loading vs equivalent rain on already-wet soil (Stenstrom et al.
1984; NRCS impervious surface runoff mechanics).

Formula (Hermes' literal spec):
    dry_72_to_168h = max(precip_72h_prior, precip_168h_prior) < 2.0
    first_rain_score = precip_24h_mm * dry_72_to_168h

Leakage guarantee under test: ``precip_72h_prior`` covers hours [24, 96] back
from cutoff (a 72h window that ENDS 24h ago); ``precip_168h_prior`` covers
hours [24, 192]. Today's rain (the same 24h being scored) cannot contaminate
the dry-spell boolean.
"""
from datetime import date

import pandas as pd
import pytest

from app.data.pipeline.features import HYDROLOGY_NUMERIC_COLUMNS, add_temporal_features
from app.data.pipeline.precipitation import (
    _forecast_cutoff_utc,
    aggregate_precip_windows,
    compute_first_rain_score,
)


def _row(station_id: str, time_utc, precip_mm: float) -> dict:
    return {
        "station_id": station_id,
        "time_utc": time_utc.isoformat() if hasattr(time_utc, "isoformat") else time_utc,
        "precip_mm_increment": precip_mm,
        "latitude": 33.0,
        "longitude": -117.3,
        "elevation_m": 5.0,
        "source_name": "test",
    }


class TestComputeFirstRainScore:
    """Unit tests against the formula in isolation."""

    def test_dry_spell_then_rain_scores_today_rain(self):
        # 8mm rain today, 0mm in both prior windows -> score == 8.0
        score = compute_first_rain_score(
            precip_24h=pd.Series([8.0]),
            precip_72h_prior=pd.Series([0.0]),
            precip_168h_prior=pd.Series([0.0]),
        )
        assert float(score.iloc[0]) == pytest.approx(8.0)

    def test_wet_prior_72h_zeroes_score(self):
        # 8mm today, 15mm in prior 72h window -> no first-flush condition
        score = compute_first_rain_score(
            precip_24h=pd.Series([8.0]),
            precip_72h_prior=pd.Series([15.0]),
            precip_168h_prior=pd.Series([15.0]),
        )
        assert float(score.iloc[0]) == pytest.approx(0.0)

    def test_wet_prior_168h_zeroes_score(self):
        # Even if the immediate prior 72h was dry, a wet 168h window also
        # disqualifies — the spec uses max() so both windows must be dry.
        score = compute_first_rain_score(
            precip_24h=pd.Series([8.0]),
            precip_72h_prior=pd.Series([0.0]),
            precip_168h_prior=pd.Series([20.0]),
        )
        assert float(score.iloc[0]) == pytest.approx(0.0)

    def test_no_rain_today_no_score(self):
        # No rain to score, even after a long dry spell
        score = compute_first_rain_score(
            precip_24h=pd.Series([0.0]),
            precip_72h_prior=pd.Series([0.0]),
            precip_168h_prior=pd.Series([0.0]),
        )
        assert float(score.iloc[0]) == pytest.approx(0.0)

    def test_threshold_sensitivity_just_above_zeroes(self):
        # Threshold is 2.0mm; 5mm prior (above threshold) must zero the score.
        score = compute_first_rain_score(
            precip_24h=pd.Series([10.0]),
            precip_72h_prior=pd.Series([5.0]),
            precip_168h_prior=pd.Series([5.0]),
        )
        assert float(score.iloc[0]) == pytest.approx(0.0)

    def test_threshold_sensitivity_just_below_scores(self):
        # 1.5mm prior (below 2.0 threshold) is still considered "essentially dry"
        score = compute_first_rain_score(
            precip_24h=pd.Series([10.0]),
            precip_72h_prior=pd.Series([1.5]),
            precip_168h_prior=pd.Series([1.5]),
        )
        assert float(score.iloc[0]) == pytest.approx(10.0)

    def test_nan_inputs_treated_as_dry(self):
        # NaNs in prior windows are filled with 0 — treated as "no recorded rain".
        # Today's NaN becomes 0, so the score is 0.
        score = compute_first_rain_score(
            precip_24h=pd.Series([float("nan")]),
            precip_72h_prior=pd.Series([float("nan")]),
            precip_168h_prior=pd.Series([float("nan")]),
        )
        assert float(score.iloc[0]) == pytest.approx(0.0)

    def test_negative_precip_clipped_to_zero(self):
        # Defensive: bad sensor values must not subtract from the score.
        score = compute_first_rain_score(
            precip_24h=pd.Series([-3.0]),
            precip_72h_prior=pd.Series([0.0]),
            precip_168h_prior=pd.Series([0.0]),
        )
        assert float(score.iloc[0]) == pytest.approx(0.0)


class TestAggregatePrecipWindowsFirstRain:
    """End-to-end through aggregate_precip_windows: leakage + column wiring."""

    def test_columns_present(self):
        result = aggregate_precip_windows(pd.DataFrame())
        # Empty input still produces the canonical schema
        for col in (
            "precip_mm_96h",
            "precip_mm_192h",
            "precip_72h_prior",
            "precip_168h_prior",
            "first_rain_score",
        ):
            assert col in result.columns, f"{col} missing from aggregate output"

    def test_first_rain_score_after_dry_week(self):
        """Synthetic case: 7 dry days, then 10mm rain in the 24h before cutoff."""
        test_date = date(2026, 1, 15)
        cutoff = _forecast_cutoff_utc(test_date)
        # 10mm in the 24h before cutoff
        rows = [
            _row("S", cutoff - pd.Timedelta(hours=2), 5.0),
            _row("S", cutoff - pd.Timedelta(hours=20), 5.0),
        ]
        # Add a single zero increment 7+ days back so the date range is wide enough
        rows.append(_row("S", cutoff - pd.Timedelta(hours=24 * 8), 0.0))
        result = aggregate_precip_windows(pd.DataFrame(rows))
        day = result[result["sample_date"] == test_date].iloc[0]

        assert day["precip_mm_24h"] == pytest.approx(10.0)
        # 96h - 24h windows: both prior windows should be 0 -> first-rain fires
        assert day["precip_72h_prior"] == pytest.approx(0.0)
        assert day["precip_168h_prior"] == pytest.approx(0.0)
        assert day["first_rain_score"] == pytest.approx(10.0)

    def test_first_rain_score_suppressed_by_prior_rain(self):
        """20mm rain 4 days ago + 10mm today -> dry boolean is false."""
        test_date = date(2026, 1, 20)
        cutoff = _forecast_cutoff_utc(test_date)
        rows = [
            # Today's rain (24h before cutoff)
            _row("S", cutoff - pd.Timedelta(hours=3), 10.0),
            # Heavy rain ~4 days ago — falls in [24, 192]h prior window
            _row("S", cutoff - pd.Timedelta(hours=96), 20.0),
        ]
        result = aggregate_precip_windows(pd.DataFrame(rows))
        day = result[result["sample_date"] == test_date].iloc[0]
        assert day["precip_mm_24h"] == pytest.approx(10.0)
        # The 20mm event lands in the 96h-but-not-24h window
        assert day["precip_168h_prior"] > 2.0
        assert day["first_rain_score"] == pytest.approx(0.0)

    def test_leakage_today_rain_excluded_from_prior_windows(self):
        """Hermes-flagged invariant: ``precip_72h_prior`` and ``precip_168h_prior``
        END 24h before forecast cutoff. Today's rain MUST NOT contribute to the
        dry-spell boolean — otherwise the feature self-cancels every time it would
        fire.
        """
        test_date = date(2026, 1, 25)
        cutoff = _forecast_cutoff_utc(test_date)
        # All the rain is in the past 24h; nothing in the [24, 192]h prior window
        rows = [
            _row("S", cutoff - pd.Timedelta(hours=h), 5.0)
            for h in (1, 6, 12, 18, 23)
        ]
        # Add zero markers further back so the daily series covers the date
        rows.append(_row("S", cutoff - pd.Timedelta(hours=24 * 10), 0.0))
        result = aggregate_precip_windows(pd.DataFrame(rows))
        day = result[result["sample_date"] == test_date].iloc[0]

        # 25mm total in the past 24h
        assert day["precip_mm_24h"] == pytest.approx(25.0)
        # Prior windows must be empty — none of today's 25mm can leak in
        assert day["precip_72h_prior"] == pytest.approx(0.0)
        assert day["precip_168h_prior"] == pytest.approx(0.0)
        # And therefore the feature fires at full strength
        assert day["first_rain_score"] == pytest.approx(25.0)


class TestFeatureReachesModel:
    """The new column must (a) be allowed by add_temporal_features as a known
    hydrology feature, and (b) survive into the model's view of the data.
    """

    def test_first_rain_score_in_hydrology_column_list(self):
        assert "first_rain_score" in HYDROLOGY_NUMERIC_COLUMNS

    def test_first_rain_score_preserved_through_add_temporal_features(self):
        # If a row already has first_rain_score, add_temporal_features must
        # carry it through (not blank it out).
        frame = pd.DataFrame(
            [
                {
                    "beach_id": "alpha",
                    "sample_date": "2026-04-01",
                    "sample_time": "2026-04-01T08:00:00-07:00",
                    "enterococcus_value": 25.0,
                    "exceeds_stv": 0,
                    "wave_height_m": 1.0,
                    "dominant_period_s": 10.0,
                    "wave_direction_deg": 200.0,
                    "water_temperature_c": 14.0,
                    "salinity_psu": 33.0,
                    "uv_index": 5.0,
                    "wind_speed_mps": 4.0,
                    "precip_mm_24h": 10.0,
                    "precip_72h_prior": 0.0,
                    "precip_168h_prior": 0.0,
                    "first_rain_score": 10.0,
                }
            ]
        )
        enriched = add_temporal_features(frame)
        assert "first_rain_score" in enriched.columns
        assert float(enriched.iloc[0]["first_rain_score"]) == pytest.approx(10.0)

    def test_first_rain_score_filled_when_missing(self):
        # Older fixtures without the column should get a NaN-filled placeholder,
        # not crash add_temporal_features.
        frame = pd.DataFrame(
            [
                {
                    "beach_id": "alpha",
                    "sample_date": "2026-04-01",
                    "sample_time": "2026-04-01T08:00:00-07:00",
                    "enterococcus_value": 25.0,
                    "exceeds_stv": 0,
                    "wave_height_m": 1.0,
                    "dominant_period_s": 10.0,
                    "wave_direction_deg": 200.0,
                    "water_temperature_c": 14.0,
                    "salinity_psu": 33.0,
                    "uv_index": 5.0,
                    "wind_speed_mps": 4.0,
                }
            ]
        )
        enriched = add_temporal_features(frame)
        assert "first_rain_score" in enriched.columns
