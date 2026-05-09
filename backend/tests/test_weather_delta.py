import numpy as np
import pandas as pd

from app.ml.weather_delta import (
    clip_weather_delta,
    fit_smoothed_rate_prior,
    select_delta_cap,
    select_no_bacteria_features,
)


def test_select_no_bacteria_features_removes_bacteria_history_columns():
    features = pd.DataFrame(
        {
            "enterococcus_value_last_obs": [120.0],
            "days_since_enterococcus_value_obs": [12.0],
            "enterococcus_value_lag_7": [80.0],
            "enterococcus_geomean_42d_lagged": [55.0],
            "geomean_30d_exceeds_35_lagged": [1.0],
            "samples_in_geomean_30d_lagged": [5.0],
            "log_enterococcus": [2.0],
            "enterococcus_value": [100.0],
            "precip_mm_24h": [3.0],
            "wave_height_m_last_obs": [1.2],
            "coastal_x_km": [-1000.0],
        }
    )

    result = select_no_bacteria_features(features)

    assert list(result.columns) == ["precip_mm_24h", "wave_height_m_last_obs", "coastal_x_km"]


def test_smoothed_prior_shrinks_sparse_beaches_toward_county_and_global_rates():
    labels = np.array([1, 0, 0, 0, 1, 1], dtype=float)
    metadata = pd.DataFrame(
        {
            "beach_id": ["a", "a", "b", "c", "c", "c"],
            "county": ["x", "x", "x", "y", "y", "y"],
        }
    )

    prior = fit_smoothed_rate_prior(labels, metadata, np.array([0, 1, 2, 3, 4, 5]))
    predictions = prior.predict(
        pd.DataFrame({"beach_id": ["a", "b", "unknown"], "county": ["x", "x", "z"]})
    )

    assert predictions[0] > predictions[1]
    assert 0.0 < predictions[2] < 1.0
    assert abs(predictions[2] - labels.mean()) < 1e-9


def test_clip_weather_delta_limits_probability_adjustment():
    result = clip_weather_delta(
        np.array([0.9, 0.1, 0.4]),
        np.array([0.4, 0.6, 0.5]),
        max_delta=0.2,
    )

    assert np.allclose(result, np.array([0.6, 0.4, 0.4]))


def test_select_delta_cap_minimizes_validation_brier_conservatively():
    labels = np.array([1, 0], dtype=float)
    weather = np.array([0.9, 0.1], dtype=float)
    prior = np.array([0.5, 0.5], dtype=float)

    cap = select_delta_cap(labels, weather, prior, caps=[0.1, 0.2, 0.4])

    assert cap == 0.4
