import numpy as np
import pandas as pd

from app.ml.spatial_diagnostics import (
    add_default_context_buckets,
    blend_alpha_sweep,
    calibration_bins,
    fallback_audit,
    group_brier_diagnostics,
    markdown_table,
    slice_brier_diagnostics,
)


def test_group_brier_diagnostics_ranks_groups_by_model_minus_persistence_delta():
    frame = pd.DataFrame(
        {
            "county": ["A", "A", "B", "B"],
            "label": [1, 0, 1, 0],
            "model_probability": [0.9, 0.8, 0.8, 0.2],
            "persistence_probability": [0.6, 0.4, 0.7, 0.3],
        }
    )

    result = group_brier_diagnostics(frame, group_column="county")

    assert list(result["county"]) == ["A", "B"]
    first = result.iloc[0]
    assert first["n"] == 2
    assert first["positives"] == 1
    assert first["actual_rate"] == 0.5
    assert np.isclose(first["model_brier"], 0.325)
    assert np.isclose(first["persistence_brier"], 0.16)
    assert np.isclose(first["brier_delta"], 0.165)
    assert np.isclose(first["model_bias"], 0.35)


def test_calibration_bins_reports_mean_prediction_and_actual_rate():
    frame = pd.DataFrame(
        {
            "label": [0, 0, 1, 1],
            "model_probability": [0.05, 0.15, 0.65, 0.95],
        }
    )

    result = calibration_bins(frame, probability_column="model_probability", bins=2)

    assert list(result["bin"]) == ["[0.00, 0.50)", "[0.50, 1.00]"]
    assert list(result["n"]) == [2, 2]
    assert list(result["positives"]) == [0, 2]
    assert np.isclose(result.iloc[0]["mean_pred"], 0.1)
    assert np.isclose(result.iloc[1]["actual_rate"], 1.0)


def test_blend_alpha_sweep_identifies_conservative_probability_mix():
    frame = pd.DataFrame(
        {
            "label": [1, 1, 0, 0],
            "model_probability": [0.9, 0.8, 0.7, 0.2],
            "persistence_probability": [0.6, 0.6, 0.4, 0.4],
        }
    )

    result = blend_alpha_sweep(frame, alphas=[0.0, 0.5, 1.0])

    best = result.sort_values("brier").iloc[0]
    assert best["alpha"] == 0.5
    assert bool(best["beats_persistence"]) is True
    assert np.isclose(result.loc[result["alpha"] == 0.0, "brier"].iloc[0], 0.16)


def test_slice_brier_diagnostics_compares_storm_and_dry_periods():
    frame = pd.DataFrame(
        {
            "storm_bucket": ["dry", "dry", "storm", "storm"],
            "label": [0, 1, 1, 0],
            "model_probability": [0.1, 0.4, 0.9, 0.7],
            "persistence_probability": [0.2, 0.5, 0.6, 0.4],
        }
    )

    result = slice_brier_diagnostics(frame, slice_column="storm_bucket")

    assert list(result["storm_bucket"]) == ["storm", "dry"]
    assert result.iloc[0]["n"] == 2
    assert result.iloc[0]["brier_delta"] > 0.0


def test_add_default_context_buckets_marks_weather_and_missingness():
    frame = pd.DataFrame(
        {
            "precip_mm_24h": [0.0, 4.0, np.nan],
            "rain_72h_inches": [0.0, 0.2, np.nan],
            "wave_height_m_last_obs": [0.3, 1.8, np.nan],
            "days_since_wave_height_m_obs": [1.0, 10.0, np.nan],
            "days_since_enterococcus_value_obs": [5.0, 55.0, np.nan],
        }
    )

    result = add_default_context_buckets(frame)

    assert list(result["precip_24h_bucket"]) == ["dry", "rain", "unknown"]
    assert list(result["rain_72h_bucket"]) == ["dry", "wet", "unknown"]
    assert list(result["wave_height_bucket"]) == ["calm", "high", "unknown"]
    assert list(result["wave_recency_bucket"]) == ["fresh", "stale", "unknown"]
    assert list(result["sample_recency_bucket"]) == ["fresh", "very_stale", "unknown"]


def test_fallback_audit_marks_routes_that_fail_to_beat_baseline():
    frame = pd.DataFrame(
        {
            "label": [1, 0],
            "model_probability": [0.2, 0.8],
            "prior_probability": [0.6, 0.4],
        }
    )

    result = fallback_audit(frame, baseline_probability_column="prior_probability")

    assert result["eligible"] is True
    assert result["route_beats_baseline"] is False
    assert result["failed_closed"] is True
    assert result["model_brier"] > result["baseline_brier"]


def test_markdown_table_does_not_require_optional_tabulate_dependency():
    frame = pd.DataFrame({"county": ["A"], "brier_delta": [0.123456]})

    result = markdown_table(frame, floatfmt=".3f")

    assert result == (
        "| county | brier_delta |\n"
        "| --- | --- |\n"
        "| A | 0.123 |"
    )
