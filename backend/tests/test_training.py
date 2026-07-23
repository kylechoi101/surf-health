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
    assert "spatial_beach_logistic_coastal_cells" in metrics
    assert "spatial_county_hist_gbm" in metrics
    assert "spatial_county_hist_gbm_persistence_blend" in metrics
    assert "spatial_county_hist_gbm_positive_persistence_guard" in metrics
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
        "xgb_undersample_ensemble",
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


def test_promotion_assessment_blocks_release_on_degenerate_beach_calibration_slope():
    # Beach holdout beats persistence on AUCPR + Brier but its calibration slope
    # is degenerate (< 0.4): the symmetric beach-slope gate must block release,
    # just like the county-slope gate does.
    promotion = _promotion_assessment(
        {
            "logistic": {"aucpr": 0.5, "brier": 0.1},
            "spatial_county_persistence": {"aucpr": 0.40, "brier": 0.18},
            "spatial_beach_persistence": {"aucpr": 0.63, "brier": 0.22},
            "spatial_county_logistic": {"aucpr": 0.55, "brier": 0.12, "calibration_slope": 1.0},
            "spatial_beach_logistic": {"aucpr": 0.86, "brier": 0.14, "calibration_slope": 0.20},
        },
        "logistic",
    )

    assert promotion["public_release_eligible"] is False
    assert any(
        "beach calibration slope" in blocker for blocker in promotion["promotion_blockers"]
    )


def test_promotion_assessment_passes_with_plausible_beach_calibration_slope():
    promotion = _promotion_assessment(
        {
            "logistic": {"aucpr": 0.5, "brier": 0.1},
            "spatial_county_persistence": {"aucpr": 0.40, "brier": 0.18},
            "spatial_beach_persistence": {"aucpr": 0.63, "brier": 0.22},
            "spatial_county_logistic": {"aucpr": 0.55, "brier": 0.12, "calibration_slope": 1.0},
            "spatial_beach_logistic": {"aucpr": 0.86, "brier": 0.14, "calibration_slope": 1.1},
        },
        "logistic",
    )

    assert promotion["public_release_eligible"] is True
    assert not any(
        "beach calibration slope" in blocker for blocker in promotion["promotion_blockers"]
    )


def test_spatially_qualified_winner_vetoes_temporal_winner_for_guard_candidate():
    # hist_gbm_positive_persistence_guard shares hist_gbm's training path so
    # the test-set metrics live under the "hist_gbm" key (see _metrics_base_key).
    # Calibration slope omitted → no slope blocker expected.
    metrics = {
        "hist_gbm": {"aucpr": 0.62, "brier": 0.085},
        "hist_gbm_valid": {"aucpr": 0.85, "brier": 0.12},
        "hist_gbm_valid_calibrated": {"aucpr": 0.85, "brier": 0.10},
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


def _passing_pair_metrics(
    incumbent_valid_aucpr: float,
    challenger_valid_aucpr: float,
    *,
    incumbent_county_aucpr: float = 0.50,
    challenger_county_aucpr: float = 0.59,
) -> dict:
    """Both hist_gbm and the ensemble clear every spatial gate (AUCPR + Brier beat
    persistence on county and beach). The swap rule ranks on held-out COUNTY AUCPR,
    so the county figures are the levers; the temporal-valid AUCPRs are kept for
    callers that still set them but no longer drive the decision."""
    return {
        # production test metrics (required by _promotion_assessment's first gate)
        "hist_gbm": {"aucpr": 0.62, "brier": 0.10},
        "xgb_undersample_ensemble": {"aucpr": 0.64, "brier": 0.10},
        "hist_gbm_valid": {"aucpr": incumbent_valid_aucpr, "brier": 0.12},
        "xgb_undersample_ensemble_valid": {"aucpr": challenger_valid_aucpr, "brier": 0.11},
        "spatial_county_persistence": {"aucpr": 0.40, "brier": 0.18},
        "spatial_beach_persistence": {"aucpr": 0.63, "brier": 0.22},
        "spatial_county_hist_gbm": {"aucpr": incumbent_county_aucpr, "brier": 0.12},
        "spatial_beach_hist_gbm": {"aucpr": 0.86, "brier": 0.14},
        "spatial_county_xgb_undersample_ensemble": {"aucpr": challenger_county_aucpr, "brier": 0.11},
        "spatial_beach_xgb_undersample_ensemble": {"aucpr": 0.90, "brier": 0.13},
    }


def _county_fold_sink(model_to_fold_preds: dict[str, dict[str, tuple]]) -> dict:
    """Build a predictions_sink keyed by (model, "county").

    ``model_to_fold_preds`` maps model_name -> {county: (labels, probs)}. Pools the
    per-fold arrays into the (labels, probabilities, groups) layout that
    _spatial_holdout_metrics stashes and the gate's paired bootstrap consumes.
    """
    sink: dict = {}
    for model_name, fold_preds in model_to_fold_preds.items():
        labels: list = []
        probs: list = []
        groups: list = []
        for county, (fold_labels, fold_probs) in fold_preds.items():
            labels.extend(list(fold_labels))
            probs.extend(list(fold_probs))
            groups.extend([county] * len(fold_labels))
        sink[(model_name, "county")] = {
            "labels": np.array(labels),
            "probabilities": np.array(probs, dtype=float),
            "groups": np.array(groups),
        }
    return sink


def _ranked_fold(rng, n, base_rate, signal):
    """A single county fold: ``signal`` controls how cleanly probs rank labels."""
    labels = (rng.random(n) < base_rate).astype(int)
    probs = np.clip(signal * labels + rng.normal(0.0, 0.2, size=n) + 0.2, 0.0, 1.0)
    return labels, probs


def test_spatially_qualified_winner_picks_best_passing_challenger():
    # Both pass the gate; the challenger's held-out county AUCPR clears the incumbent
    # by 0.09 (>> the 0.07 no-predictions fallback margin). With no per-fold
    # predictions the conservative large-gap rule still swaps to the better model.
    winner = _spatially_qualified_production_winner(
        _passing_pair_metrics(0.70, 0.75),
        preferred="hist_gbm",
        candidates=("hist_gbm", "xgb_undersample_ensemble"),
    )
    assert winner == "xgb_undersample_ensemble"


def test_spatially_qualified_winner_keeps_incumbent_within_margin():
    # Both pass; the challenger's county AUCPR edge (0.595 vs 0.59) is below the
    # 0.01 point-estimate floor. Hysteresis keeps the incumbent — the gate must not
    # churn the production winner on sub-noise-floor backtest jitter.
    winner = _spatially_qualified_production_winner(
        _passing_pair_metrics(
            0.745, 0.750,
            incumbent_county_aucpr=0.590,
            challenger_county_aucpr=0.595,
        ),
        preferred="hist_gbm",
        candidates=("hist_gbm", "xgb_undersample_ensemble"),
    )
    assert winner == "hist_gbm"


def test_spatially_qualified_winner_no_swap_when_paired_bootstrap_straddles_zero():
    # County point gap clears the 0.01 floor (0.55 vs 0.50), but the per-fold
    # predictions are noisy: in some counties the challenger wins, in others the
    # incumbent does, so the paired cluster bootstrap of the gap straddles 0.
    # No swap — the improvement is not distinguishable from resampling noise.
    rng = np.random.default_rng(7)
    counties = ["LA", "OC", "SD", "SB", "VEN", "MON"]
    challenger_folds = {}
    incumbent_folds = {}
    for i, county in enumerate(counties):
        labels, strong = _ranked_fold(rng, 40, 0.35, 0.6)
        _, weak = _ranked_fold(rng, 40, 0.35, 0.6)
        # Alternate which model gets the cleanly-ranked probabilities per fold so
        # the pooled gap has near-zero mean and wide between-fold variance.
        if i % 2 == 0:
            challenger_folds[county] = (labels, strong)
            incumbent_folds[county] = (labels, weak)
        else:
            challenger_folds[county] = (labels, weak)
            incumbent_folds[county] = (labels, strong)
    sink = _county_fold_sink({
        "xgb_undersample_ensemble": challenger_folds,
        "hist_gbm": incumbent_folds,
    })
    winner = _spatially_qualified_production_winner(
        _passing_pair_metrics(
            0.70, 0.75,
            incumbent_county_aucpr=0.50,
            challenger_county_aucpr=0.55,
        ),
        preferred="hist_gbm",
        candidates=("hist_gbm", "xgb_undersample_ensemble"),
        predictions_sink=sink,
    )
    assert winner == "hist_gbm"


def test_spatially_qualified_winner_swaps_on_decisive_paired_bootstrap():
    # County point gap clears the floor AND the challenger ranks labels better in
    # EVERY county fold, so the paired cluster bootstrap of the gap has a lower
    # bound well above 0 — a decisive, noise-robust improvement. Swap.
    rng = np.random.default_rng(11)
    counties = ["LA", "OC", "SD", "SB", "VEN", "MON"]
    challenger_folds = {}
    incumbent_folds = {}
    for county in counties:
        labels, strong = _ranked_fold(rng, 40, 0.35, 1.2)
        # Incumbent probabilities are pure noise (uninformative ranking).
        weak = np.clip(rng.normal(0.4, 0.15, size=len(labels)), 0.0, 1.0)
        challenger_folds[county] = (labels, strong)
        incumbent_folds[county] = (labels, weak)
    sink = _county_fold_sink({
        "xgb_undersample_ensemble": challenger_folds,
        "hist_gbm": incumbent_folds,
    })
    winner = _spatially_qualified_production_winner(
        _passing_pair_metrics(
            0.70, 0.75,
            incumbent_county_aucpr=0.50,
            challenger_county_aucpr=0.62,
        ),
        preferred="hist_gbm",
        candidates=("hist_gbm", "xgb_undersample_ensemble"),
        predictions_sink=sink,
    )
    assert winner == "xgb_undersample_ensemble"


def test_spatially_qualified_winner_large_gap_fallback_without_predictions():
    # No per-fold predictions available -> the paired bootstrap can't run, so the
    # conservative large-gap fallback applies: a 0.05 county gap (between the 0.01
    # floor and the 0.07 no-evidence margin) does NOT swap, but a 0.10 gap does.
    keep = _spatially_qualified_production_winner(
        _passing_pair_metrics(
            0.70, 0.75,
            incumbent_county_aucpr=0.50,
            challenger_county_aucpr=0.55,
        ),
        preferred="hist_gbm",
        candidates=("hist_gbm", "xgb_undersample_ensemble"),
        predictions_sink=None,
    )
    assert keep == "hist_gbm"

    swap = _spatially_qualified_production_winner(
        _passing_pair_metrics(
            0.70, 0.75,
            incumbent_county_aucpr=0.50,
            challenger_county_aucpr=0.60,
        ),
        preferred="hist_gbm",
        candidates=("hist_gbm", "xgb_undersample_ensemble"),
        predictions_sink=None,
    )
    assert swap == "xgb_undersample_ensemble"


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


def test_export_forecasts_applies_advisory_safety_floor(monkeypatch, tmp_path):
    from app.ml.training import _export_forecasts, _TrainedModels, StageTwoTrainingPlan
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
    
    candidates = pd.DataFrame([
        {"beach_id": "acute_active", "advisory_active_recent_for_floor": 1},
        {"beach_id": "chronic_active", "advisory_active_recent_for_floor": 1},
        {"beach_id": "stale_active", "advisory_active_recent_for_floor": 0},
    ])
    monkeypatch.setattr("app.ml.training._build_forecast_candidates", lambda *args, **kwargs: (pd.DataFrame(), candidates))
    
    # Prior observations are BELOW the STV (104) so this test isolates the
    # advisory-floor override: a prior exceedance would (correctly) trip the
    # serve-time positive-persistence floor and force p_exceed to 1.0, which is
    # covered separately by the guarded-blend test above.
    features = pd.DataFrame({"enterococcus_value_last_obs": [80.0, 80.0, 80.0]})
    forecast_features = pd.DataFrame({"enterococcus_value_last_obs": [80.0, 80.0, 80.0], "advisory_active_recent_for_floor": [1, 1, 0]})
    forecast_metadata = pd.DataFrame({"beach_id": ["acute_active", "chronic_active", "stale_active"], "sample_date": [pd.Timestamp("2026-04-20")]*3})

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
        lambda *args, **kwargs: [["mock driver"]]*3,
    )
    monkeypatch.setattr("app.ml.training._split_conformal_half_width", lambda *args: None)
    monkeypatch.setattr("app.ml.training._write_model_card", lambda *args: None)

    _export_forecasts(
        curated_dir=curated_dir,
        forecast_date=date(2026, 4, 20),
        frame=pd.DataFrame(),
        full_frame=pd.DataFrame(),
        features=features,
        densities=np.array([1.0, 1.1, 1.2]),
        valid_idx=np.array([0, 1]),
        test_idx=np.array([2]),
        stations=pd.DataFrame(
            [
                {
                    "beach_id": bid,
                    "county": "Orange",
                    "region": "South Coast",
                    "latitude": 33.0,
                    "longitude": -117.0,
                    "zip_code": "92651",
                } for bid in ["acute_active", "chronic_active", "stale_active"]
            ]
        ),
        uv_daily=pd.DataFrame(),
        advisories=pd.DataFrame(),
        models=_TrainedModels(
            winner="baseline",
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
            production_winner="baseline",
            research_winner="baseline",
            spatial_backtest_models=[],
        ),
        metrics={"baseline": {}},
        model_types_to_run=[],
        spatial_backtests=False,
        spatial_backtest_models=[],
        spatial_strategy="shortlist",
    )

    forecasts = pd.read_parquet(curated_dir / "forecasts.parquet")

    assert forecasts.loc[forecasts["beach_id"] == "acute_active", "p_exceed"].iloc[0] == 0.3
    assert forecasts.loc[forecasts["beach_id"] == "acute_active", "p_exceed_raw"].iloc[0] == 0.2
    assert bool(forecasts.loc[forecasts["beach_id"] == "acute_active", "advisory_floor_applied"].iloc[0]) is True
    
    assert forecasts.loc[forecasts["beach_id"] == "chronic_active", "p_exceed"].iloc[0] == 0.3
    assert forecasts.loc[forecasts["beach_id"] == "chronic_active", "p_exceed_raw"].iloc[0] == 0.2
    assert bool(forecasts.loc[forecasts["beach_id"] == "chronic_active", "advisory_floor_applied"].iloc[0]) is True
    
    assert forecasts.loc[forecasts["beach_id"] == "stale_active", "p_exceed"].iloc[0] == 0.2
    assert forecasts.loc[forecasts["beach_id"] == "stale_active", "p_exceed_raw"].iloc[0] == 0.2
    assert bool(forecasts.loc[forecasts["beach_id"] == "stale_active", "advisory_floor_applied"].iloc[0]) is False


def _run_export_single_beach(
    tmp_path,
    monkeypatch,
    *,
    winner: str,
    model_prob: float,
    last_obs: float,
    sample_recency_band: str,
    advisory_floor: int,
    raw_proba_override=None,
):
    """Drive _export_forecasts for one synthetic beach and return its forecast row."""
    from app.ml.training import _export_forecasts, _TrainedModels, StageTwoTrainingPlan

    class FixedClassifier:
        def predict_proba(self, frame):
            pos = (
                np.full(len(frame), model_prob, dtype=float)
                if raw_proba_override is None
                else np.asarray(raw_proba_override, dtype=float)
            )
            return np.column_stack([1.0 - pos, pos])

    class FixedRegressor:
        def predict(self, frame):
            return np.full(len(frame), 1.7, dtype=float)

    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()
    (curated_dir / "system_health.json").write_text("{}")

    candidates = pd.DataFrame([
        {
            "beach_id": "beach",
            "advisory_active_recent_for_floor": advisory_floor,
            "sample_recency_band": sample_recency_band,
            "sample_age_days": 90 if sample_recency_band == "very_stale" else 1,
        }
    ])
    monkeypatch.setattr(
        "app.ml.training._build_forecast_candidates",
        lambda *args, **kwargs: (pd.DataFrame(), candidates),
    )
    forecast_features = pd.DataFrame(
        {"enterococcus_value_last_obs": [last_obs], "advisory_active_recent_for_floor": [advisory_floor]}
    )
    forecast_metadata = pd.DataFrame(
        {"beach_id": ["beach"], "sample_date": [pd.Timestamp("2026-04-20")]}
    )
    monkeypatch.setattr(
        "app.ml.training.build_inference_features",
        lambda inference_input: type(
            "Inference", (), {"feature_frame": forecast_features, "metadata": forecast_metadata}
        )(),
    )
    monkeypatch.setattr("app.ml.training._inject_agent_features", lambda features, *args: features)
    monkeypatch.setattr("app.ml.training._compute_local_drivers", lambda *args, **kwargs: [["mock"]])
    monkeypatch.setattr("app.ml.training._split_conformal_half_width", lambda *args: None)
    monkeypatch.setattr("app.ml.training._write_model_card", lambda *args: None)

    _export_forecasts(
        curated_dir=curated_dir,
        forecast_date=date(2026, 4, 20),
        frame=pd.DataFrame(),
        full_frame=pd.DataFrame(),
        features=pd.DataFrame({"enterococcus_value_last_obs": [last_obs]}),
        densities=np.array([1.0]),
        valid_idx=np.array([0]),
        test_idx=np.array([0]),
        stations=pd.DataFrame(
            [{"beach_id": "beach", "county": "Orange", "region": "South Coast",
              "latitude": 33.0, "longitude": -117.0, "zip_code": "92651"}]
        ),
        uv_daily=pd.DataFrame(),
        advisories=pd.DataFrame(),
        models=_TrainedModels(
            winner=winner,
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
            regressor_valid_predictions=np.array([1.0]),
        ),
        plan=StageTwoTrainingPlan(
            production_winner=winner, research_winner=winner, spatial_backtest_models=[]
        ),
        metrics={winner: {}},
        model_types_to_run=[],
        spatial_backtests=False,
        spatial_backtest_models=[],
        spatial_strategy="shortlist",
    )
    forecasts = pd.read_parquet(curated_dir / "forecasts.parquet")
    return forecasts.iloc[0]


def test_export_positive_persistence_floor_applies_to_non_guard_winner(monkeypatch, tmp_path):
    # Deployed-ensemble shape: a non-guard winner whose model says Low (0.05),
    # but the prior official observation exceeded the STV (180 > 104). The
    # serve-time positive-persistence floor must keep it from collapsing to Low.
    row = _run_export_single_beach(
        tmp_path, monkeypatch,
        winner="baseline", model_prob=0.05, last_obs=180.0,
        sample_recency_band="recent", advisory_floor=0,
    )
    assert row["p_exceed"] == 1.0
    assert row["p_exceed_raw"] == 1.0  # guard runs before p_raw is read
    assert row["risk_band"] == "Very High"


def test_export_does_not_floor_non_guard_winner_when_prior_below_stv(monkeypatch, tmp_path):
    row = _run_export_single_beach(
        tmp_path, monkeypatch,
        winner="baseline", model_prob=0.05, last_obs=20.0,
        sample_recency_band="recent", advisory_floor=0,
    )
    assert row["p_exceed"] == 0.05
    assert row["risk_band"] == "Low"


def test_export_nan_probability_falls_back_to_safe_default(monkeypatch, tmp_path):
    # A non-finite served probability with no prior exceedance must fall back to
    # the safe Low/Moderate default (0.20), never NaN, in the parquet.
    row = _run_export_single_beach(
        tmp_path, monkeypatch,
        winner="baseline", model_prob=0.0, last_obs=20.0,
        sample_recency_band="recent", advisory_floor=0,
        raw_proba_override=[np.nan],
    )
    assert np.isfinite(row["p_exceed"])
    assert row["p_exceed"] == 0.20


def test_export_confidence_cap_downgrades_strong_band_on_very_stale_no_advisory(
    monkeypatch, tmp_path
):
    # Strong model band (High) off a very-stale sample with no advisory: the
    # displayed band is capped at Moderate, but the numeric p_exceed stays honest.
    row = _run_export_single_beach(
        tmp_path, monkeypatch,
        winner="baseline", model_prob=0.45, last_obs=20.0,
        sample_recency_band="very_stale", advisory_floor=0,
    )
    assert row["risk_band"] == "Moderate"
    assert abs(float(row["p_exceed"]) - 0.45) < 1e-9  # p_exceed unchanged


def test_export_confidence_cap_does_not_fire_with_active_advisory(monkeypatch, tmp_path):
    # Same very-stale sample, but an advisory is active: the cap must NOT
    # suppress (advisory floor raises to >= High and the band stands).
    row = _run_export_single_beach(
        tmp_path, monkeypatch,
        winner="baseline", model_prob=0.45, last_obs=20.0,
        sample_recency_band="very_stale", advisory_floor=1,
    )
    assert row["risk_band"] in ("High", "Very High")


def test_export_confidence_cap_does_not_fire_on_fresh_sample(monkeypatch, tmp_path):
    # Fresh sample with a strong band: never capped — a true recent exceedance
    # signal must still surface (no added false negatives on fresh data).
    row = _run_export_single_beach(
        tmp_path, monkeypatch,
        winner="baseline", model_prob=0.45, last_obs=20.0,
        sample_recency_band="fresh", advisory_floor=0,
    )
    assert row["risk_band"] == "High"
