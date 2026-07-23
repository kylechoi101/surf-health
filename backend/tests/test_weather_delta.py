import numpy as np
import pandas as pd

from app.ml.weather_delta import fit_smoothed_rate_prior, is_bacteria_history_feature


def test_is_bacteria_history_feature_matches_risk_history_columns():
    """Drives the live stale-censoring path (app/ml/stale_evaluation.py): these
    are exactly the columns zeroed on a stale between-sample serving row."""
    bacteria = [
        "enterococcus_value_last_obs",
        "days_since_enterococcus_value_obs",
        "enterococcus_value_lag_7",
        "enterococcus_geomean_42d_lagged",
        "geomean_30d_exceeds_35_lagged",
        "samples_in_geomean_30d_lagged",
        "log_enterococcus",
        "enterococcus_value",
    ]
    environmental = ["precip_mm_24h", "wave_height_m_last_obs", "coastal_x_km"]

    assert all(is_bacteria_history_feature(column) for column in bacteria)
    assert not any(is_bacteria_history_feature(column) for column in environmental)


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
