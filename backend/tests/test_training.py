from datetime import date

import numpy as np
import pandas as pd

from app.data.pipeline.features import build_sliding_windows
from app.ml.training import (
    _blocked_indices,
    _build_forecast_candidates,
    _compute_local_drivers,
    _fit_coastal_cell_logistic_artifacts,
    _fit_hierarchical_logistic_artifacts,
    _metadata_with_groups,
    _predict_coastal_cell_logistic_raw,
    _predict_hierarchical_logistic_raw,
    _promotion_assessment,
    _spatial_holdout_metrics,
    _spatial_backtest_metrics,
    _identity_or_calibrated,
    _split_conformal_half_width,
    _two_stage_training_plan,
    train_all,
)
from app.ml.calibration import HierarchicalProbabilityCalibrator


def test_blocked_indices_keep_same_dates_in_same_split():
    metadata = pd.DataFrame(
        {
            "sample_date": [
                "2026-04-01",
                "2026-04-01",
                "2026-04-02",
                "2026-04-03",
                "2026-04-03",
                "2026-04-04",
                "2026-04-05",
                "2026-04-06",
                "2026-04-07",
            ]
        }
    )

    train_idx, valid_idx, test_idx = _blocked_indices(metadata)
    sample_dates = pd.to_datetime(metadata["sample_date"]).dt.normalize()
    train_dates = set(sample_dates.iloc[train_idx])
    valid_dates = set(sample_dates.iloc[valid_idx])
    test_dates = set(sample_dates.iloc[test_idx])

    assert train_dates.isdisjoint(valid_dates)
    assert train_dates.isdisjoint(test_dates)
    assert valid_dates.isdisjoint(test_dates)
    assert train_dates | valid_dates | test_dates == set(sample_dates)


def test_blocked_indices_handles_timestamp_metadata_from_feature_builder():
    metadata = pd.DataFrame(
        {
            "sample_date": pd.to_datetime(
                [
                    "2026-04-01",
                    "2026-04-02",
                    "2026-04-03",
                    "2026-04-04",
                    "2026-04-05",
                    "2026-04-06",
                ]
            )
        }
    )

    train_idx, valid_idx, test_idx = _blocked_indices(metadata)

    assert len(train_idx) > 0
    assert len(valid_idx) > 0
    assert len(test_idx) > 0
    assert len(train_idx) + len(valid_idx) + len(test_idx) == len(metadata)


def test_compute_local_drivers_maps_stormwater_features():
    class StormwaterOnlyClassifier:
        def predict_proba(self, frame):
            probs = np.where(frame["nearest_stormwater_outfall_km"].to_numpy() > 0, 0.82, 0.12)
            return np.column_stack([1 - probs, probs])

    features = pd.DataFrame(
        {
            "nearest_stormwater_outfall_km": [0.4],
            "precip_mm_24h": [0.0],
        }
    )

    drivers = _compute_local_drivers(
        StormwaterOnlyClassifier(),
        features,
        baseline_probs=np.array([0.82]),
    )

    assert any("outfall" in driver for driver in drivers[0])


def test_identity_or_calibrated_uses_hierarchical_metadata():
    probabilities = np.array([0.2, 0.3, 0.4, 0.5, 0.2, 0.3, 0.4, 0.5])
    labels = np.array([1, 1, 0, 1, 0, 0, 0, 1])
    metadata = pd.DataFrame(
        {
            "county": ["high"] * 4 + ["low"] * 4,
            "beach_id": ["high-site"] * 4 + ["low-site"] * 4,
        }
    )

    calibrated, calibrator = _identity_or_calibrated(probabilities, labels, metadata)

    assert isinstance(calibrator, HierarchicalProbabilityCalibrator)
    assert len(calibrated) == len(probabilities)
    high_low = calibrator.transform(
        np.array([0.3, 0.3]),
        pd.DataFrame({"county": ["high", "low"], "beach_id": ["high-site", "low-site"]}),
    )
    assert high_low[0] > high_low[1]


def test_build_forecast_candidates_uses_only_prior_observations():
    frame = pd.DataFrame(
        [
            {
                "beach_id": "alpha",
                "sample_date": "2026-04-18",
                "sample_time": "2026-04-18T08:00:00-07:00",
                "enterococcus_value": 80.0,
                "exceeds_stv": 0,
                "wave_height_m": 1.2,
                "dominant_period_s": 9.0,
                "water_temperature_c": 14.0,
                "salinity_psu": 33.0,
                "uv_index": 4.0,
                "wind_speed_mps": 3.0,
                "tidal_height": 1.0,
                "surf_height_observed": 2.0,
                "turbidity_observed": 5.0,
            },
            {
                "beach_id": "alpha",
                "sample_date": "2026-04-19",
                "sample_time": "2026-04-19T08:00:00-07:00",
                "enterococcus_value": 95.0,
                "exceeds_stv": 0,
                "wave_height_m": 1.4,
                "dominant_period_s": 9.5,
                "water_temperature_c": 14.5,
                "salinity_psu": 33.1,
                "uv_index": 5.0,
                "wind_speed_mps": 3.5,
                "tidal_height": 1.1,
                "surf_height_observed": 2.2,
                "turbidity_observed": 5.5,
            },
            {
                "beach_id": "alpha",
                "sample_date": "2026-04-20",
                "sample_time": "2026-04-20T08:00:00-07:00",
                "enterococcus_value": 110.0,
                "exceeds_stv": 1,
                "wave_height_m": 1.7,
                "dominant_period_s": 10.0,
                "water_temperature_c": 15.0,
                "salinity_psu": 33.3,
                "uv_index": 6.0,
                "wind_speed_mps": 4.0,
                "tidal_height": 1.2,
                "surf_height_observed": 2.5,
                "turbidity_observed": 6.0,
            },
            {
                "beach_id": "alpha",
                "sample_date": "2026-04-21",
                "sample_time": "2026-04-21T08:00:00-07:00",
                "enterococcus_value": 150.0,
                "exceeds_stv": 1,
                "wave_height_m": 2.5,
                "dominant_period_s": 11.0,
                "water_temperature_c": 16.0,
                "salinity_psu": 34.0,
                "uv_index": 7.0,
                "wind_speed_mps": 4.5,
                "tidal_height": 1.3,
                "surf_height_observed": 3.0,
                "turbidity_observed": 6.5,
            },
        ]
    )
    stations = pd.DataFrame([{"beach_id": "alpha", "zip_code": "92037"}])
    uv_daily = pd.DataFrame(
        [{"zip_code": "92037", "forecast_date": "2026-04-21", "uv_index": 9.0, "uv_alert": "Very High"}]
    )

    history, candidates = _build_forecast_candidates(frame, stations, uv_daily, date(2026, 4, 21))

    assert str(history["sample_date"].max().date()) == "2026-04-20"
    assert len(candidates) == 1
    assert str(candidates.iloc[0]["sample_date"].date()) == "2026-04-21"
    assert pd.isna(candidates.iloc[0]["enterococcus_value"])
    assert candidates.iloc[0]["wave_height_m"] == 1.7
    assert candidates.iloc[0]["uv_index"] == 9.0


def test_spatial_backtests_emit_beach_and_county_metrics():
    rows = []
    for county, beach_id, offset in (
        ("San Diego", "alpha", 0),
        ("San Diego", "beta", 1),
        ("Orange", "gamma", 2),
        ("Orange", "delta", 3),
    ):
        for day in range(1, 21):
            enterococcus = 40 + day * 6 + offset * 5
            rows.append(
                {
                    "beach_id": beach_id,
                    "county": county,
                    "sample_date": f"2026-04-{day:02d}",
                    "sample_time": f"2026-04-{day:02d}T08:00:00-07:00",
                    "enterococcus_value": float(enterococcus),
                    "exceeds_stv": int(enterococcus > 90),
                    "wave_height_m": 1.0 + day * 0.05 + offset * 0.02,
                    "dominant_period_s": 9.0 + offset * 0.1,
                    "water_temperature_c": 14.0 + offset * 0.1,
                    "salinity_psu": 33.0 + offset * 0.05,
                    "uv_index": 5.0 + (day % 3),
                    "wind_speed_mps": 4.0 + offset * 0.1,
                    "tidal_height": 1.0 + day * 0.01,
                    "surf_height_observed": 2.0 + day * 0.03,
                    "turbidity_observed": 3.0 + offset * 0.2,
                }
            )

    frame = pd.DataFrame(rows)
    dataset = build_sliding_windows(frame)
    features = dataset.feature_frame.select_dtypes(include=["number"]).fillna(0.0)
    metadata = _metadata_with_groups(dataset.metadata, frame)

    metrics = _spatial_backtest_metrics(
        features,
        dataset.targets_exceed,
        metadata,
        stv_threshold=104.0,
        beach_group_limit=2,
        county_group_limit=2,
    )

    assert "spatial_beach_hist_gbm" in metrics
    assert "spatial_beach_logistic_coastal_cells" in metrics
    assert "spatial_county_hist_gbm" in metrics
    assert "spatial_county_logistic_coastal_cells" in metrics
    assert metrics["spatial_beach_hist_gbm"]["folds"] >= 1.0
    assert metrics["spatial_county_hist_gbm"]["folds"] >= 1.0
    assert 0.0 <= metrics["spatial_beach_hist_gbm"]["aucpr"] <= 1.0
    assert not np.isnan(metrics["spatial_county_logistic"]["brier"])


def test_spatial_backtests_can_limit_stage_two_models():
    rows = []
    for county, beach_id, offset in (
        ("San Diego", "alpha", 0),
        ("San Diego", "beta", 1),
        ("Orange", "gamma", 2),
        ("Orange", "delta", 3),
    ):
        for day in range(1, 21):
            enterococcus = 40 + day * 6 + offset * 5
            rows.append(
                {
                    "beach_id": beach_id,
                    "county": county,
                    "sample_date": f"2026-04-{day:02d}",
                    "sample_time": f"2026-04-{day:02d}T08:00:00-07:00",
                    "enterococcus_value": float(enterococcus),
                    "exceeds_stv": int(enterococcus > 90),
                    "wave_height_m": 1.0 + day * 0.05 + offset * 0.02,
                    "dominant_period_s": 9.0 + offset * 0.1,
                    "water_temperature_c": 14.0 + offset * 0.1,
                    "salinity_psu": 33.0 + offset * 0.05,
                    "uv_index": 5.0 + (day % 3),
                    "wind_speed_mps": 4.0 + offset * 0.1,
                    "tidal_height": 1.0 + day * 0.01,
                    "surf_height_observed": 2.0 + day * 0.03,
                    "turbidity_observed": 3.0 + offset * 0.2,
                }
            )

    frame = pd.DataFrame(rows)
    dataset = build_sliding_windows(frame)
    features = dataset.feature_frame.select_dtypes(include=["number"]).fillna(0.0)
    metadata = _metadata_with_groups(dataset.metadata, frame)

    metrics = _spatial_backtest_metrics(
        features,
        dataset.targets_exceed,
        metadata,
        stv_threshold=104.0,
        beach_group_limit=2,
        county_group_limit=2,
        dataset=dataset,
        model_names_to_run=["logistic", "transformer"],
        sequence_epochs=1,
    )

    assert "spatial_beach_persistence" in metrics
    assert "spatial_beach_logistic" in metrics
    assert "spatial_beach_transformer" in metrics
    assert "spatial_beach_hist_gbm" not in metrics
    assert "spatial_county_transformer" in metrics


def test_sequence_spatial_holdout_forces_serial_jobs(monkeypatch):
    rows = []
    for county, beach_id, offset in (
        ("San Diego", "alpha", 0),
        ("San Diego", "beta", 1),
        ("Orange", "gamma", 2),
        ("Orange", "delta", 3),
    ):
        for day in range(1, 12):
            enterococcus = 40 + day * 7 + offset * 4
            rows.append(
                {
                    "beach_id": beach_id,
                    "county": county,
                    "sample_date": f"2026-04-{day:02d}",
                    "sample_time": f"2026-04-{day:02d}T08:00:00-07:00",
                    "enterococcus_value": float(enterococcus),
                    "exceeds_stv": int(enterococcus > 90),
                    "wave_height_m": 1.0 + day * 0.04 + offset * 0.02,
                    "dominant_period_s": 9.0 + offset * 0.1,
                    "water_temperature_c": 14.0 + offset * 0.1,
                    "salinity_psu": 33.0 + offset * 0.05,
                    "uv_index": 5.0 + (day % 3),
                    "wind_speed_mps": 4.0 + offset * 0.1,
                    "tidal_height": 1.0 + day * 0.01,
                    "surf_height_observed": 2.0 + day * 0.03,
                    "turbidity_observed": 3.0 + offset * 0.2,
                }
            )

    frame = pd.DataFrame(rows)
    dataset = build_sliding_windows(frame)
    features = dataset.feature_frame.select_dtypes(include=["number"]).fillna(0.0)
    metadata = _metadata_with_groups(dataset.metadata, frame)

    def fail_parallel(*args, **kwargs):
        raise AssertionError("Sequence spatial backtests should not invoke joblib Parallel")

    monkeypatch.setattr("app.ml.training.Parallel", fail_parallel)

    metrics = _spatial_holdout_metrics(
        features,
        dataset.targets_exceed,
        metadata,
        model_name="tcn",
        group_column="beach_id",
        stv_threshold=104.0,
        min_rows=8,
        max_groups=2,
        spatial_jobs=2,
        dataset=dataset,
        sequence_epochs=1,
    )

    assert "folds" in metrics


def test_split_conformal_half_width_is_non_negative():
    width = _split_conformal_half_width(
        labels=np.array([1.0, 1.2, 1.4, 1.6]),
        predictions=np.array([0.9, 1.1, 1.5, 1.7]),
        coverage=0.9,
    )
    assert width is not None
    assert width >= 0.0


def test_fixture_training_keeps_neural_track_out_of_production():
    artifacts = train_all(sample_fixture=True)
    assert artifacts.winner in {"logistic", "hist_gbm"}


def test_two_stage_training_plan_shortlists_production_and_research_winners():
    metrics = {
        "logistic_valid": {"brier": 0.22},
        "logistic_coastal_cells_valid": {"brier": 0.24},
        "logistic_hierarchical_valid": {"brier": 0.23},
        "hist_gbm_valid": {"brier": 0.21},
        "tcn_valid": {"brier": 0.16},
        "transformer_valid": {"brier": 0.14},
        "pinn_valid": {"brier": 0.17},
    }

    plan = _two_stage_training_plan(metrics, ["tcn", "transformer", "pinn"])

    assert plan.production_winner == "hist_gbm"
    assert plan.research_winner == "transformer"
    assert plan.spatial_backtest_models == ["hist_gbm", "transformer"]


def test_hierarchical_logistic_falls_back_county_then_region_then_global():
    features = pd.DataFrame(
        {
            "enterococcus_value_lag_1": [20, 24, 28, 80, 84, 88, 30, 34, 38, 70, 74, 78],
            "wave_height_m_lag_1": [0.8, 0.9, 1.0, 1.8, 1.9, 2.0, 0.7, 0.8, 0.9, 1.7, 1.8, 1.9],
        }
    )
    labels = np.array([0, 0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1], dtype=np.float32)
    metadata = pd.DataFrame(
        {
            "county": ["alpha"] * 6 + ["beta"] * 3 + ["gamma"] * 3,
            "region": ["south"] * 9 + ["north"] * 3,
            "sample_date": pd.date_range("2026-04-01", periods=12, freq="D"),
        }
    )
    artifacts = _fit_hierarchical_logistic_artifacts(
        features,
        labels,
        metadata,
        np.arange(len(features)),
        county_min_rows=3,
        region_min_rows=3,
        min_positive_rows=1,
        min_negative_rows=1,
    )

    inference_features = features.iloc[[0, 6, 9]].reset_index(drop=True)
    inference_metadata = pd.DataFrame(
        {
            "county": ["alpha", "delta", "omega"],
            "region": ["south", "south", "far-north"],
        }
    )
    probabilities, scopes = _predict_hierarchical_logistic_raw(
        artifacts,
        inference_features,
        inference_metadata,
    )

    assert len(probabilities) == 3
    assert list(scopes) == ["county", "region", "global"]


def test_coastal_cell_logistic_uses_cell_models_and_global_fallback():
    features = pd.DataFrame(
        {
            "enterococcus_value_lag_1": [20, 24, 28, 80, 84, 88, 15, 18, 21, 24],
            "wave_height_m_lag_1": [0.8, 0.9, 1.0, 1.8, 1.9, 2.0, 0.5, 0.55, 0.6, 0.65],
        }
    )
    labels = np.array([0, 0, 0, 1, 1, 1, 0, 0, 0, 0], dtype=np.float32)
    metadata = pd.DataFrame(
        {
            "beach_id": ["south-a"] * 3 + ["south-b"] * 3 + ["north-a"] * 4,
            "sample_date": pd.date_range("2026-04-01", periods=10, freq="D"),
            "latitude": [32.7] * 6 + [41.2] * 4,
            "longitude": [-117.3] * 6 + [-124.1] * 4,
            "cdip_distance_km": [6.0] * 6 + [48.0] * 4,
            "erddap_distance_km": [2.0] * 6 + [30.0] * 4,
            "wave_direction_deg": [185.0] * 6 + [310.0] * 4,
        }
    )

    artifacts = _fit_coastal_cell_logistic_artifacts(
        features,
        labels,
        metadata,
        np.arange(len(features)),
        min_rows=3,
        min_positive_rows=1,
        min_negative_rows=1,
        min_beaches_per_cluster=2,
        max_clusters=2,
    )

    inference_features = pd.DataFrame(
        {
            "enterococcus_value_lag_1": [26, 19],
            "wave_height_m_lag_1": [0.95, 0.58],
        }
    )
    inference_metadata = pd.DataFrame(
        {
            "beach_id": ["south-c", "north-b"],
            "sample_date": pd.to_datetime(["2026-04-20", "2026-04-20"]),
            "latitude": [32.8, 41.3],
            "longitude": [-117.2, -124.2],
            "cdip_distance_km": [7.0, 50.0],
            "erddap_distance_km": [2.5, 31.0],
            "wave_direction_deg": [190.0, 315.0],
        }
    )

    probabilities, cells, scopes = _predict_coastal_cell_logistic_raw(
        artifacts,
        inference_features,
        inference_metadata,
    )

    assert len(probabilities) == 2
    assert cells[0] != cells[1]
    assert list(scopes) == ["coastal_cell", "global"]


def test_promotion_assessment_blocks_release_when_county_holdout_lags_persistence():
    promotion = _promotion_assessment(
        {
            "spatial_beach_persistence": {"aucpr": 0.6, "brier": 0.24},
            "spatial_beach_logistic": {"aucpr": 0.7, "brier": 0.2},
            "spatial_county_persistence": {"aucpr": 0.5, "brier": 0.25},
            "spatial_county_logistic": {"aucpr": 0.4, "brier": 0.24},
        },
        "logistic",
    )

    assert promotion["public_release_eligible"] is False
    assert "Held-out county AUCPR does not beat persistence." in promotion["promotion_blockers"]
