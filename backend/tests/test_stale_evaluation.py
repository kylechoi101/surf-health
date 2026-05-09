import numpy as np
import pandas as pd

from app.ml.stale_evaluation import (
    build_stale_prior_router,
    build_serving_stale_sample_set,
    build_stale_censoring_variants,
    censor_bacteria_history_for_cutoff,
    filter_stale_rows,
    stale_cutoff_label,
    stale_row_label,
    stale_row_mask,
)


def test_censor_bacteria_history_for_cutoff_hides_direct_biology_features():
    features = pd.DataFrame(
        {
            "enterococcus_value_last_obs": [120.0, 40.0],
            "enterococcus_geomean_42d_lagged": [80.0, 12.0],
            "geomean_30d_exceeds_35_lagged": [1.0, 0.0],
            "days_since_enterococcus_value_obs": [5.0, 75.0],
            "precip_mm_24h": [4.0, 0.0],
            "coastal_x_km": [-1000.0, -900.0],
        }
    )

    censored = censor_bacteria_history_for_cutoff(features, cutoff_days=45)

    assert censored["enterococcus_value_last_obs"].tolist() == [0.0, 0.0]
    assert censored["enterococcus_geomean_42d_lagged"].tolist() == [0.0, 0.0]
    assert censored["geomean_30d_exceeds_35_lagged"].tolist() == [0.0, 0.0]
    assert censored["days_since_enterococcus_value_obs"].tolist() == [45.0, 75.0]
    assert censored["precip_mm_24h"].tolist() == [4.0, 0.0]
    assert censored["coastal_x_km"].tolist() == [-1000.0, -900.0]


def test_build_stale_censoring_variants_labels_each_cutoff():
    features = pd.DataFrame(
        {
            "enterococcus_value_last_obs": [120.0],
            "days_since_enterococcus_value_obs": [7.0],
            "precip_mm_24h": [3.0],
        }
    )

    variants = build_stale_censoring_variants(features, cutoffs=[30, 60])

    assert list(variants) == ["censored_30d", "censored_60d"]
    assert variants["censored_30d"]["days_since_enterococcus_value_obs"].iloc[0] == 30.0
    assert variants["censored_60d"]["days_since_enterococcus_value_obs"].iloc[0] == 60.0
    assert np.allclose(variants["censored_30d"]["enterococcus_value_last_obs"], 0.0)


def test_filter_stale_rows_selects_rows_with_stale_latest_sample():
    frame = pd.DataFrame(
        {
            "beach_id": ["fresh", "cutoff", "stale", "unknown"],
            "days_since_enterococcus_value_obs": [12.0, 45.0, 90.0, np.nan],
            "label": [0, 1, 0, 1],
        }
    )

    mask = stale_row_mask(frame, cutoff_days=45)
    stale = filter_stale_rows(frame, cutoff_days=45)

    assert mask.tolist() == [False, True, True, False]
    assert stale["beach_id"].tolist() == ["cutoff", "stale"]
    assert stale_row_label(45) == "stale_45d"


def test_build_serving_stale_sample_set_filters_history_and_sample_age():
    beaches = pd.DataFrame(
        {
            "beach_id": ["eligible", "too_few_positives", "fresh"],
            "name": ["Eligible Beach", "Quiet Beach", "Fresh Beach"],
            "county": ["A", "A", "B"],
            "latest_official_sample_at": ["2026-02-01", "2026-01-01", "2026-04-20"],
        }
    )
    observations = pd.DataFrame(
        {
            "beach_id": ["eligible"] * 120 + ["too_few_positives"] * 120 + ["fresh"] * 120,
            "sample_date": pd.date_range("2025-01-01", periods=120).tolist() * 3,
            "exceeds_stv": [1] * 15
            + [0] * 105
            + [1] * 5
            + [0] * 115
            + [1] * 20
            + [0] * 100,
        }
    )
    forecasts = pd.DataFrame(
        {
            "beach_id": ["eligible", "fresh"],
            "forecast_date": ["2026-05-08", "2026-05-08"],
            "risk_band": ["Moderate", "Low"],
            "p_exceed": [0.2, 0.05],
            "model_version": ["hist-gbm", "hist-gbm"],
        }
    )

    result = build_serving_stale_sample_set(
        beaches,
        observations,
        forecasts=forecasts,
        reference_date="2026-05-09",
        stale_cutoff_days=50,
        min_samples=100,
        min_positives=10,
    )

    assert result["beach_id"].tolist() == ["eligible"]
    assert result["days_since_latest_sample"].iloc[0] == 97
    assert result["sample_count"].iloc[0] == 120
    assert result["positive_count"].iloc[0] == 15
    assert bool(result["forecast_available"].iloc[0]) is True
    assert result["risk_band"].iloc[0] == "Moderate"


def test_build_stale_prior_router_fails_closed_to_smoothed_beach_prior():
    candidates = pd.DataFrame(
        {
            "beach_id": ["eligible"],
            "name": ["Eligible Beach"],
            "county": ["A"],
            "sample_count": [120],
            "positive_count": [15],
        }
    )
    observations = pd.DataFrame(
        {
            "beach_id": ["eligible"] * 120 + ["county-peer"] * 80,
            "county": ["A"] * 200,
            "sample_date": pd.date_range("2025-01-01", periods=200),
            "exceeds_stv": [1] * 15 + [0] * 105 + [1] * 5 + [0] * 75,
        }
    )

    result = build_stale_prior_router(
        candidates,
        observations,
        min_beach_samples=100,
        min_beach_positives=10,
    )

    assert result["stale_route"].tolist() == ["beach_prior"]
    assert bool(result["failed_closed"].iloc[0]) is True
    assert result["stale_probability"].iloc[0] > 0.0
    assert result["stale_probability"].iloc[0] < 0.2
    assert result["stale_risk_band"].iloc[0] == "Low"
    assert "historical" in result["stale_route_basis"].iloc[0]


def test_build_stale_prior_router_falls_back_to_county_then_global_prior():
    candidates = pd.DataFrame(
        {
            "beach_id": ["sparse", "unknown-county"],
            "name": ["Sparse Beach", "Unknown County Beach"],
            "county": ["A", "Missing"],
            "sample_count": [12, 0],
            "positive_count": [1, 0],
        }
    )
    observations = pd.DataFrame(
        {
            "beach_id": ["county-peer"] * 80 + ["other"] * 20,
            "county": ["A"] * 80 + ["B"] * 20,
            "sample_date": pd.date_range("2025-01-01", periods=100),
            "exceeds_stv": [1] * 20 + [0] * 60 + [1] * 2 + [0] * 18,
        }
    )

    result = build_stale_prior_router(
        candidates,
        observations,
        min_beach_samples=100,
        min_beach_positives=10,
        min_county_samples=50,
        min_county_positives=5,
    )

    assert result["stale_route"].tolist() == ["county_prior", "global_prior"]
    assert result.loc[result["beach_id"] == "sparse", "stale_probability"].iloc[0] > result.loc[
        result["beach_id"] == "unknown-county", "stale_probability"
    ].iloc[0]
    assert bool(result["failed_closed"].all()) is True


def test_stale_cutoff_label_rejects_nonpositive_cutoff():
    try:
        stale_cutoff_label(0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
