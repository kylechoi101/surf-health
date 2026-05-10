from datetime import date

import numpy as np
import pandas as pd

from app.data.pipeline.features import build_sliding_windows
from app.ml.training import (
    StageTwoTrainingPlan,
    _TrainedModels,
    _best_valid_aucpr_model,
    _blocked_indices,
    _build_forecast_candidates,
    _calibration_split,
    _compute_local_drivers,
    _fit_coastal_cell_logistic_artifacts,
    _fit_hierarchical_logistic_artifacts,
    _metadata_with_groups,
    _predict_coastal_cell_logistic_raw,
    _predict_hierarchical_logistic_raw,
    _positive_persistence_guarded_blend_probabilities,
    _export_forecasts,
    _promotion_assessment,
    _select_persistence_blend_alpha,
    _spatial_holdout_metrics,
    _spatial_backtest_metrics,
    _spatially_qualified_production_winner,
    _spatial_holdout_fold_result,
    _identity_or_calibrated,
    _split_conformal_half_width,
    _two_stage_training_plan,
    _write_model_card,
    SPATIAL_BACKTEST_MODEL_NAMES,
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


def test_select_persistence_blend_alpha_minimizes_validation_brier_conservatively():
    labels = np.array([1, 1, 0, 0], dtype=float)
    model_probs = np.array([0.9, 0.8, 0.7, 0.2], dtype=float)
    persistence_probs = np.array([0.6, 0.6, 0.4, 0.4], dtype=float)

    alpha = _select_persistence_blend_alpha(
        labels,
        model_probs,
        persistence_probs,
        alphas=[0.0, 0.5, 1.0],
    )

    assert alpha == 0.5


def test_select_persistence_blend_alpha_respects_model_weight_cap():
    alpha = _select_persistence_blend_alpha(
        np.array([1, 0], dtype=float),
        np.array([1, 0], dtype=float),
        np.array([0, 1], dtype=float),
        alphas=[0.0, 0.6, 1.0],
        max_alpha=0.6,
    )

    assert alpha == 0.6


def test_positive_persistence_guarded_blend_keeps_prior_exceedances_at_one():
    model_probs = np.array([0.2, 0.8, 0.4, 0.9], dtype=float)
    persistence_probs = np.array([1.0, 0.0, 1.0, 0.0], dtype=float)

    guarded = _positive_persistence_guarded_blend_probabilities(
        model_probs,
        persistence_probs,
        alpha=0.5,
    )

    assert guarded.tolist() == [1.0, 0.4, 1.0, 0.45]


def test_export_forecasts_uses_guarded_probabilities_for_beta_serving_candidate(
    monkeypatch, tmp_path
):
    class FixedClassifier:
        def predict_proba(self, frame):
            return np.column_stack(
                [np.full(len(frame), 0.8, dtype=float), np.full(len(frame), 0.2, dtype=float)]
            )

    class FixedRegressor:
        def predict(self, frame):
            return np.full(len(frame), 1.7, dtype=float)

    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()
    (curated_dir / "system_health.json").write_text("{}")
    frame = pd.DataFrame(
        [
            {
                "beach_id": "alpha",
                "sample_date": f"2026-04-{day:02d}",
                "sample_time": f"2026-04-{day:02d}T08:00:00+00:00",
                "enterococcus_value": 180.0,
                "exceeds_stv": 1,
                "wave_height_m": 1.0,
                "dominant_period_s": 8.0,
                "water_temperature_c": 16.0,
                "salinity_psu": 33.0,
                "uv_index": 5.0,
                "wind_speed_mps": 3.0,
                "tidal_height": 1.0,
                "surf_height_observed": 2.0,
                "turbidity_observed": 5.0,
            }
            for day in (17, 18, 19)
        ]
    )
    features = pd.DataFrame({"enterococcus_value_last_obs": [80.0, 180.0, 180.0]})
    forecast_features = pd.DataFrame({"enterococcus_value_last_obs": [180.0]})
    forecast_metadata = pd.DataFrame({"beach_id": ["alpha"], "sample_date": [pd.Timestamp("2026-04-20")]})

    monkeypatch.setattr(
        "app.ml.training.build_inference_features",
        lambda inference_input: type(
            "Inference",
            (),
            {"feature_frame": forecast_features, "metadata": forecast_metadata},
        )(),
    )
    monkeypatch.setattr("app.ml.training._inject_agent_features", lambda features, *args: features)
    monkeypatch.setattr(
        "app.ml.training._compute_local_drivers",
        lambda *args, **kwargs: [["elevated bacteria in recent sample"]],
    )
    monkeypatch.setattr("app.ml.training._split_conformal_half_width", lambda *args: None)
    monkeypatch.setattr("app.ml.training._write_model_card", lambda *args: None)

    _export_forecasts(
        curated_dir=curated_dir,
        forecast_date=date(2026, 4, 20),
        frame=frame,
        full_frame=frame,
        features=features,
        densities=np.array([1.0, 1.1, 1.2]),
        valid_idx=np.array([0, 1]),
        test_idx=np.array([2]),
        stations=pd.DataFrame(
            [
                {
                    "beach_id": "alpha",
                    "county": "Orange",
                    "region": "South Coast",
                    "latitude": 33.0,
                    "longitude": -117.0,
                    "zip_code": "92651",
                }
            ]
        ),
        uv_daily=pd.DataFrame(),
        advisories=pd.DataFrame(),
        models=_TrainedModels(
            winner="hist_gbm_positive_persistence_guard",
            tree_classifier=FixedClassifier(),
            tree_calibrator=None,
            classifier=FixedClassifier(),
            calibrator=None,
            logistic=None,
            logistic_calibrator=None,
            coastal_cell_logistic=None,
            hierarchical_logistic=None,
            ensemble_weights=None,
            regressor=FixedRegressor(),
            regressor_valid_predictions=np.array([1.0, 1.1]),
        ),
        plan=StageTwoTrainingPlan(
            production_winner="hist_gbm_positive_persistence_guard",
            research_winner="hist_gbm_positive_persistence_guard",
            spatial_backtest_models=["hist_gbm_positive_persistence_guard"],
        ),
        metrics={"hist_gbm_positive_persistence_guard": {}, "hist_gbm_positive_persistence_guard_valid": {}},
        model_types_to_run=[],
        spatial_backtests=False,
        spatial_backtest_models=["hist_gbm_positive_persistence_guard"],
        spatial_strategy="shortlist",
    )

    forecasts = pd.read_parquet(curated_dir / "forecasts.parquet")

    assert forecasts.loc[0, "p_exceed"] == 1.0
    assert forecasts.loc[0, "risk_band"] == "Very High"
    assert forecasts.loc[0, "forecast_label_mode"] == "model"
    assert bool(forecasts.loc[0, "is_beta_forecast"]) is True


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


def test_build_forecast_candidates_drops_stations_with_stale_samples():
    """California beach monitoring funding has been cut multiple times since 2020,
    leaving many stations silent for months. Publishing a forecast for a station
    whose last sample is 6 months old is misleading — the env covariates are
    stale, the geomean features can't be computed, and downstream agreement
    metrics get inflated by these zombie stations.
    """
    rows = []
    # alpha: actively monitored — most recent sample 5 days before forecast.
    for offset in range(0, 30, 2):  # 15 samples spaced 2 days apart, latest = forecast - 5d
        sample_dt = pd.Timestamp("2026-04-20") - pd.Timedelta(days=offset + 5)
        rows.append({
            "beach_id": "alpha", "sample_date": sample_dt.strftime("%Y-%m-%d"),
            "sample_time": sample_dt.strftime("%Y-%m-%dT08:00:00-07:00"),
            "enterococcus_value": 50.0, "exceeds_stv": 0,
            "wave_height_m": 1.0, "dominant_period_s": 10.0,
            "water_temperature_c": 14.0, "salinity_psu": 33.0,
            "uv_index": 5.0, "wind_speed_mps": 3.0,
            "tidal_height": 1.0, "surf_height_observed": 2.0, "turbidity_observed": 5.0,
        })
    # bravo: discontinued monitoring — last sample 60 days before forecast.
    for offset in range(0, 60, 5):  # samples 60-115 days before forecast
        sample_dt = pd.Timestamp("2026-04-20") - pd.Timedelta(days=offset + 60)
        rows.append({
            "beach_id": "bravo", "sample_date": sample_dt.strftime("%Y-%m-%d"),
            "sample_time": sample_dt.strftime("%Y-%m-%dT08:00:00-07:00"),
            "enterococcus_value": 50.0, "exceeds_stv": 0,
            "wave_height_m": 1.0, "dominant_period_s": 10.0,
            "water_temperature_c": 14.0, "salinity_psu": 33.0,
            "uv_index": 5.0, "wind_speed_mps": 3.0,
            "tidal_height": 1.0, "surf_height_observed": 2.0, "turbidity_observed": 5.0,
        })
    frame = pd.DataFrame(rows)
    stations = pd.DataFrame([
        {"beach_id": "alpha", "zip_code": "92037"},
        {"beach_id": "bravo", "zip_code": "92038"},
    ])
    uv_daily = pd.DataFrame()

    # Without recency filter: both beaches get forecast rows.
    _, all_candidates = _build_forecast_candidates(frame, stations, uv_daily, date(2026, 4, 21))
    assert set(all_candidates["beach_id"]) == {"alpha", "bravo"}

    # With 20-day recency cutoff: only alpha (5d old) survives; bravo (60d old) drops.
    _, fresh_candidates = _build_forecast_candidates(
        frame, stations, uv_daily, date(2026, 4, 21), min_sample_recency_days=20,
    )
    assert set(fresh_candidates["beach_id"]) == {"alpha"}

    # Tight cutoff: alpha (5d old) also drops if we require <=3 days.
    _, very_fresh = _build_forecast_candidates(
        frame, stations, uv_daily, date(2026, 4, 21), min_sample_recency_days=3,
    )
    assert len(very_fresh) == 0


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
    assert "spatial_beach_hist_gbm_persistence_blend" in metrics
    assert "spatial_beach_hist_gbm_positive_persistence_guard" in metrics
    assert "spatial_beach_hist_gbm_no_bacteria_weather_delta" in metrics
    assert "spatial_beach_logistic_coastal_cells" in metrics
    assert "spatial_county_hist_gbm" in metrics
    assert "spatial_county_hist_gbm_persistence_blend" in metrics
    assert "spatial_county_hist_gbm_positive_persistence_guard" in metrics
    assert "spatial_county_hist_gbm_no_bacteria_weather_delta" in metrics
    assert "spatial_county_logistic_coastal_cells" in metrics
    assert metrics["spatial_beach_hist_gbm"]["folds"] >= 1.0
    assert metrics["spatial_county_hist_gbm"]["folds"] >= 1.0
    assert 0.0 <= metrics["spatial_beach_hist_gbm"]["aucpr"] <= 1.0
    assert not np.isnan(metrics["spatial_county_logistic"]["brier"])


def test_no_bacteria_weather_delta_fold_excludes_bacteria_history(monkeypatch):
    rows = []
    for county, beach_id, offset in (
        ("San Diego", "alpha", 0),
        ("San Diego", "beta", 1),
        ("Orange", "gamma", 2),
        ("Orange", "delta", 3),
    ):
        for day in range(1, 13):
            rows.append(
                {
                    "county": county,
                    "beach_id": beach_id,
                    "sample_date": pd.Timestamp(f"2026-04-{day:02d}"),
                    "enterococcus_value_last_obs": float(40 + day + offset),
                    "enterococcus_geomean_42d_lagged": float(30 + day + offset),
                    "precip_mm_24h": float(day % 4),
                    "wave_height_m_last_obs": float(0.5 + offset * 0.1),
                }
            )
    metadata = pd.DataFrame(rows)
    features = metadata[
        [
            "enterococcus_value_last_obs",
            "enterococcus_geomean_42d_lagged",
            "precip_mm_24h",
            "wave_height_m_last_obs",
        ]
    ]
    labels = np.array([(idx % 5) == 0 for idx in range(len(features))], dtype=float)
    seen_columns: list[list[str]] = []

    class RecordingClassifier:
        def fit(self, frame, labels):
            seen_columns.append(list(frame.columns))
            return self

        def predict_proba(self, frame):
            seen_columns.append(list(frame.columns))
            probabilities = np.clip(0.2 + frame["precip_mm_24h"].to_numpy(dtype=float) * 0.05, 0.05, 0.95)
            return np.column_stack([1.0 - probabilities, probabilities])

    monkeypatch.setattr(
        "app.ml.training._fit_classifier_for_name",
        lambda frame, model_name: RecordingClassifier(),
    )

    result = _spatial_holdout_fold_result(
        features,
        labels,
        metadata,
        model_name="hist_gbm_no_bacteria_weather_delta",
        group_column="beach_id",
        group_value="alpha",
        stv_threshold=104.0,
        min_rows=3,
    )

    assert result is not None
    assert seen_columns
    for columns in seen_columns:
        assert "enterococcus_value_last_obs" not in columns
        assert "enterococcus_geomean_42d_lagged" not in columns


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
        "logistic_valid": {"brier": 0.22, "aucpr": 0.55},
        "logistic_coastal_cells_valid": {"brier": 0.24, "aucpr": 0.50},
        "logistic_hierarchical_valid": {"brier": 0.23, "aucpr": 0.58},
        "hist_gbm_valid": {"brier": 0.21, "aucpr": 0.62},
        "tcn_valid": {"brier": 0.16, "aucpr": 0.71},
        "transformer_valid": {"brier": 0.14, "aucpr": 0.78},
        "pinn_valid": {"brier": 0.17, "aucpr": 0.69},
    }

    plan = _two_stage_training_plan(metrics, ["tcn", "transformer", "pinn"])

    assert plan.production_winner == "hist_gbm"
    assert plan.research_winner == "transformer"
    assert plan.spatial_backtest_models == [
        "hist_gbm",
        "transformer",
        "hist_gbm_positive_persistence_guard",
        "hist_gbm_persistence_blend",
        "hist_gbm_no_bacteria_weather_delta",
    ]


def test_two_stage_training_plan_picks_by_aucpr_not_brier():
    """The selector now prefers higher AUCPR even when Brier favors a different model.

    Brier is calibration-sensitive; the calibrator runs *after* selection, so
    selection on Brier rewards models that are well-calibrated-but-flat.
    Selecting on AUCPR rewards genuine rank quality, which is what we actually
    want before the calibration stage.
    """
    metrics = {
        "logistic_valid": {"brier": 0.10, "aucpr": 0.40},   # lowest Brier...
        "hist_gbm_valid": {"brier": 0.18, "aucpr": 0.65},   # ...but worst rank quality
        "logistic_hierarchical_valid": {"brier": 0.15, "aucpr": 0.58},
        "logistic_coastal_cells_valid": {"brier": 0.13, "aucpr": 0.50},
    }
    plan = _two_stage_training_plan(metrics, [])
    assert plan.production_winner == "hist_gbm"


def test_two_stage_training_plan_breaks_aucpr_ties_with_lower_brier():
    metrics = {
        "logistic_valid": {"brier": 0.22, "aucpr": 0.60},
        "hist_gbm_valid": {"brier": 0.18, "aucpr": 0.60},   # same AUCPR, lower Brier
        "logistic_hierarchical_valid": {"brier": 0.20, "aucpr": 0.60},
    }
    plan = _two_stage_training_plan(metrics, [])
    assert plan.production_winner == "hist_gbm"


def test_best_valid_aucpr_model_falls_back_when_no_metrics():
    metrics = {
        "logistic_valid": {"brier": 0.20},  # missing aucpr
    }
    assert _best_valid_aucpr_model(metrics, ["logistic"], fallback="hist_gbm") == "hist_gbm"


def test_calibration_split_produces_disjoint_halves_balanced_by_county():
    valid_idx = np.arange(40, dtype=int)
    metadata = pd.DataFrame({
        "county": ["alpha"] * 12 + ["beta"] * 12 + ["gamma"] * 16,
        "sample_date": pd.date_range("2026-04-01", periods=40, freq="D"),
    })
    cal_idx, val_metric_idx = _calibration_split(valid_idx, metadata)

    # Halves are disjoint.
    assert len(set(cal_idx).intersection(val_metric_idx)) == 0
    # Halves cover all valid rows.
    assert sorted(set(cal_idx).union(val_metric_idx)) == list(valid_idx)

    # Each county is represented in both halves.
    cal_counties = set(metadata.loc[cal_idx, "county"])
    metric_counties = set(metadata.loc[val_metric_idx, "county"])
    assert cal_counties == {"alpha", "beta", "gamma"}
    assert metric_counties == {"alpha", "beta", "gamma"}


def test_calibration_split_keeps_singleton_county_in_calibrator_half():
    """If a county has only one valid sample, the calibrator must still see it
    (otherwise the hierarchical calibrator falls back to a global intercept for
    that county). The metric half drops the singleton.
    """
    valid_idx = np.arange(11, dtype=int)
    metadata = pd.DataFrame({
        "county": ["alpha"] * 5 + ["beta"] * 5 + ["solo_county"],
        "sample_date": pd.date_range("2026-04-01", periods=11, freq="D"),
    })
    cal_idx, val_metric_idx = _calibration_split(valid_idx, metadata)

    cal_counties = list(metadata.loc[cal_idx, "county"])
    metric_counties = list(metadata.loc[val_metric_idx, "county"])

    assert "solo_county" in cal_counties
    assert "solo_county" not in metric_counties


def test_calibration_split_is_deterministic_for_same_seed():
    valid_idx = np.arange(20, dtype=int)
    metadata = pd.DataFrame({
        "county": ["alpha"] * 10 + ["beta"] * 10,
        "sample_date": pd.date_range("2026-04-01", periods=20, freq="D"),
    })
    cal_a, metric_a = _calibration_split(valid_idx, metadata, seed=17)
    cal_b, metric_b = _calibration_split(valid_idx, metadata, seed=17)
    np.testing.assert_array_equal(cal_a, cal_b)
    np.testing.assert_array_equal(metric_a, metric_b)


def test_calibration_split_falls_back_to_full_slice_when_too_small():
    valid_idx = np.array([0, 1, 2], dtype=int)
    metadata = pd.DataFrame({
        "county": ["alpha", "beta", "gamma"],
        "sample_date": pd.date_range("2026-04-01", periods=3, freq="D"),
    })
    cal_idx, val_metric_idx = _calibration_split(valid_idx, metadata)
    np.testing.assert_array_equal(cal_idx, valid_idx)
    np.testing.assert_array_equal(val_metric_idx, valid_idx)


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


def test_spatially_qualified_winner_vetoes_temporal_winner_for_guard_candidate():
    metrics = {
        "hist_gbm_valid": {"aucpr": 0.85, "brier": 0.12},
        "hist_gbm_positive_persistence_guard_valid": {"aucpr": 0.63, "brier": 0.17},
        "spatial_county_persistence": {"aucpr": 0.57, "brier": 0.138},
        "spatial_beach_persistence": {"aucpr": 0.72, "brier": 0.201},
        "spatial_county_hist_gbm": {"aucpr": 0.60, "brier": 0.142},
        "spatial_beach_hist_gbm": {"aucpr": 0.90, "brier": 0.109},
        "spatial_county_hist_gbm_positive_persistence_guard": {
            "aucpr": 0.65,
            "brier": 0.126,
        },
        "spatial_beach_hist_gbm_positive_persistence_guard": {
            "aucpr": 0.78,
            "brier": 0.159,
        },
    }

    winner = _spatially_qualified_production_winner(
        metrics,
        preferred="hist_gbm",
        candidates=("hist_gbm", "hist_gbm_positive_persistence_guard"),
    )

    assert winner == "hist_gbm_positive_persistence_guard"


def test_spatial_backtest_models_do_not_duplicate_production_guard_candidate():
    assert len(SPATIAL_BACKTEST_MODEL_NAMES) == len(set(SPATIAL_BACKTEST_MODEL_NAMES))


def test_model_card_reports_spatial_metrics_for_production_model(tmp_path):
    _write_model_card(
        tmp_path,
        {
            "pipeline_freshness": "2026-05-10T16:47:37+00:00",
            "model_registry": {
                "production_model": "hist-gbm-positive-persistence-guard-curated-v0",
                "deployment_stage": "candidate_ready",
                "public_release_eligible": True,
                "promotion_blockers": [],
                "production_metrics": {"aucpr": 0.25, "brier": 0.13},
                "validation_metrics": {"aucpr": 0.63, "brier": 0.17},
                "spatial_metrics": {
                    "spatial_county_hist_gbm": {"aucpr": 0.59, "brier": 0.142},
                    "spatial_county_hist_gbm_positive_persistence_guard": {
                        "aucpr": 0.655,
                        "brier": 0.127,
                    },
                    "spatial_county_persistence": {"aucpr": 0.574, "brier": 0.139},
                },
                "metrics": {},
            },
        },
    )

    card = (tmp_path / "model_card.md").read_text()

    assert "**Spatial county AUCPR**: 0.655" in card
