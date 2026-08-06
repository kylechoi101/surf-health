from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

# macOS only: torch and xgboost each bundle their own libomp. Loading both in one
# process makes their OpenMP thread pools deadlock during torch training (hang at
# 0% CPU). Pinning OpenMP to a single thread breaks the deadlock. Set before any
# libomp-loading import. Not set on Linux/CI → full multithreaded performance.
if sys.platform == "darwin":
    os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import pandas as pd
# Import xgboost before torch (duplicate-libomp segfault on macOS; see models.py).
import xgboost  # noqa: F401
import torch
from sklearn.cluster import KMeans
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

if not os.getenv("LOKY_MAX_CPU_COUNT"):
    os.environ["LOKY_MAX_CPU_COUNT"] = str(os.cpu_count() or 8)

from joblib import Parallel, delayed, parallel_backend
from torch import nn
from torch.utils.data import DataLoader, Subset

from app.core.config import get_settings
from app.core.json_safe import write_json
from app.data.pipeline.beachwatch import (
    ADVISORY_OPEN_ENDED_MAX_DAYS,
    fill_open_ended_advisory_end,
)
from app.data.pipeline.features import (
    MARINE_MICROBIOLOGY_NUMERIC_COLUMNS,
    STORMWATER_EXPERT_NUMERIC_COLUMNS,
    SlidingWindowDataset,
    build_inference_features,
    build_sliding_windows,
)
from app.ml.calibration import (
    HierarchicalProbabilityCalibrator,
    ProbabilityCalibrator,
    _LOW_THRESHOLD,
    _HIGH_THRESHOLD,
    _VERY_HIGH_THRESHOLD as _CAL_VERY_HIGH,
    confidence_capped_risk_band,
)
from app.ml.datasets import SequenceDataset
from app.ml.evaluation import (
    classification_metrics,
    cluster_bootstrap_aucpr_ci,
    holdout_frame,
    paired_cluster_bootstrap_aucpr_gap_ci,
    persist_holdout_predictions,
    regression_metrics,
    sensitivity_at_specificity_record,
)
from app.ml.models import (
    BeachCNN, 
    BeachTCN, 
    BeachLSTM, 
    BeachTransformer, 
    BeachPINN_MultiTask,
    XGBUndersampleEnsemble,
    XGBUndersampleOffsetEnsemble,
    make_baselines
)
from app.ml.served_metrics import (
    append_forecast_history,
    apply_serving_calibration,
    fit_serving_calibration,
    save_serving_calibration,
    served_performance,
)
from app.ml.stale_evaluation import (
    RECENCY_COLUMN as _STALE_RECENCY_COL,
    censor_bacteria_history_for_cutoff,
)
from app.schemas.domain import sample_recency_band

MIN_PLAUSIBLE_SAMPLE_TIME = pd.Timestamp("2000-01-01")
MAX_FUTURE_SAMPLE_LEEWAY_DAYS = 2
COASTAL_CELL_MIN_BEACHES_PER_CLUSTER = 24
COASTAL_CELL_MAX_CLUSTERS = 8
PRODUCTION_MODEL_NAMES = (
    "logistic",
    "logistic_coastal_cells",
    "logistic_hierarchical",
    "hist_gbm",
    "hist_gbm_positive_persistence_guard",
    "xgb_undersample_ensemble",
    "stacked_ensemble",
)
SEQUENCE_MODEL_NAMES = ("tcn", "cnn", "lstm", "transformer", "pinn")
SPATIAL_DIAGNOSTIC_MODEL_NAMES = (
    "hist_gbm_persistence_blend",
    # Two-tier (level+deviation) challenger: per-beach base_margin offset +
    # staleness augmentation. Spatially backtested against the incumbent so the
    # retrain reports its held-out within-beach skill; not force-trained
    # temporally every run until it proves out on the served-regime metrics.
    "xgb_undersample_offset",
)
SPATIAL_BACKTEST_MODEL_NAMES = (*PRODUCTION_MODEL_NAMES, *SPATIAL_DIAGNOSTIC_MODEL_NAMES)
SPATIAL_BACKTEST_STRATEGIES = ("shortlist", "requested", "quick")
# Median served sample age (model_truth.md Test 3). Spatial folds re-score the
# held-out rows with the anchor censored to this age so the within-beach metric
# reflects the between-sample regime the product serves — the leave-one-beach-out
# rows are otherwise fresh sample-days (lag ~7) where the served ~0.50 failure is
# invisible. This is the regime on which the two-tier offset model is judged.
_SERVING_STALE_CUTOFF_DAYS: int = 14
# Point-estimate floor: minimum held-out county-AUCPR gain a challenger must show
# over the passing incumbent before the gate even considers a swap (hysteresis vs
# daily churn). A gap below this is treated as pure backtest noise.
_WINNER_SWAP_MARGIN = 0.01
# Conservative no-evidence fallback: when per-row holdout predictions are NOT
# available to run the paired cluster bootstrap (e.g. an offline/metrics-only
# evaluation), require a county-AUCPR gap above this before swapping. ~ the
# measured 6-fold cluster-bootstrap half-width of the pooled spatial AUCPR
# (~0.136 full width on [0.32, 0.59]); a gap inside that band is indistinguishable
# from noise without the paired test, so we do not churn the production winner.
_WINNER_SWAP_LARGE_GAP_MARGIN = 0.07
# Deterministic seed for every spatial cluster bootstrap so the daily gate is
# reproducible run-to-run (the winner must not flip on RNG state alone).
_SPATIAL_BOOTSTRAP_SEED = 20260611
PERSISTENCE_BLEND_ALPHAS = tuple(float(alpha) for alpha in np.linspace(0.0, 1.0, 11))
PERSISTENCE_BLEND_MAX_MODEL_ALPHA = 0.6
COASTAL_CELL_FEATURE_COLUMNS = [
    "coastal_x_km",
    "coastal_y_km",
    "cdip_distance_km_log1p",
    "erddap_distance_km_log1p",
    "wave_direction_sin",
    "wave_direction_cos",
]


@dataclass
class TrainingArtifacts:
    winner: str
    metrics: dict[str, dict[str, float]]


@dataclass
class SequenceTrainingArtifacts:
    valid_metrics: dict[str, float]
    test_metrics: dict[str, float]
    model: nn.Module | None
    calibrator: ProbabilityCalibrator | None
    site_lookup: dict[str, int]
    static_feature_columns: list[str]
    test_probabilities: np.ndarray | None = None


@dataclass(frozen=True)
class StageTwoTrainingPlan:
    production_winner: str
    research_winner: str
    spatial_backtest_models: list[str]


@dataclass
class _TrainedModels:
    winner: str
    tree_classifier: object
    tree_calibrator: object
    classifier: object        # winner classifier; None for coastal/hierarchical/ensemble
    calibrator: object        # winner calibrator; None when classifier is None
    logistic: object          # None unless winner is logistic or stacked_ensemble
    logistic_calibrator: object
    coastal_cell_logistic: object  # None unless winner is coastal or stacked_ensemble
    hierarchical_logistic: object  # None unless winner is hierarchical or stacked_ensemble
    ensemble_weights: object  # np.ndarray or None
    regressor: object
    regressor_valid_predictions: object  # np.ndarray
    # Two-tier offset model + its calibrator, trained alongside the winner for
    # regime routing at serve time (fresh beaches → winner, stale → offset). None
    # when the two-tier router is not wired for this run.
    offset_classifier: object = None
    offset_calibrator: object = None


@dataclass
class HierarchicalLogisticArtifacts:
    global_model: object
    calibrator: ProbabilityCalibrator | None
    county_models: dict[str, object]
    region_models: dict[str, object]


@dataclass
class CoastalCellAssigner:
    imputer: SimpleImputer
    scaler: StandardScaler
    kmeans: KMeans
    feature_columns: list[str]
    beach_cells: dict[str, str]


@dataclass
class CoastalCellLogisticArtifacts:
    global_model: object
    calibrator: ProbabilityCalibrator | None
    cell_models: dict[str, object]
    assigner: CoastalCellAssigner | None


def _safe_float(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _filter_plausible_training_rows(frame: pd.DataFrame) -> pd.DataFrame:
    filtered = frame.copy()
    filtered["sample_time"] = pd.to_datetime(filtered["sample_time"], errors="coerce")
    if getattr(filtered["sample_time"].dt, "tz", None) is not None:
        filtered["sample_time"] = filtered["sample_time"].dt.tz_convert("UTC").dt.tz_localize(None)
    if "sample_date" in filtered.columns:
        filtered["sample_date"] = pd.to_datetime(filtered["sample_date"], errors="coerce")
    max_plausible_time = pd.Timestamp.now(tz="UTC").tz_localize(None) + pd.Timedelta(
        days=MAX_FUTURE_SAMPLE_LEEWAY_DAYS
    )
    plausible_mask = filtered["sample_time"].between(MIN_PLAUSIBLE_SAMPLE_TIME, max_plausible_time)
    return filtered.loc[plausible_mask].copy()


def _build_uv_lookup(uv_daily: pd.DataFrame, forecast_date: date) -> pd.DataFrame:
    if uv_daily.empty or "zip_code" not in uv_daily.columns or "forecast_date" not in uv_daily.columns:
        return pd.DataFrame()
    matched = uv_daily.copy()
    matched["forecast_date"] = pd.to_datetime(matched["forecast_date"], errors="coerce").dt.date
    matched = matched.loc[matched["forecast_date"] == forecast_date].copy()
    if matched.empty:
        return pd.DataFrame()
    matched["zip_code"] = matched["zip_code"].astype(str).str.zfill(5)
    return matched.drop_duplicates(subset=["zip_code"], keep="last").set_index("zip_code")


def _prepare_observation_training_frame(observations: pd.DataFrame) -> pd.DataFrame:
    frame = observations.copy()
    frame["sample_time"] = pd.to_datetime(frame["sample_time"], errors="coerce")
    frame["sample_date"] = pd.to_datetime(frame["sample_date"], errors="coerce")
    frame["enterococcus_value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["exceeds_stv"] = frame["exceeds_stv"].astype(int)
    for column in (
        "county",
        "region",
        "latitude",
        "longitude",
        "historical_advisory_count",
        "cdip_distance_km",
        "erddap_distance_km",
        "cdip_station_id",
        "erddap_source_name",
        "wave_height_m",
        "dominant_period_s",
        "wave_direction_deg",
        "water_temperature_c",
        "salinity_psu",
        "uv_index",
        "wind_speed_mps",
        "tidal_height",
        "surf_height_observed",
        "turbidity_observed",
    ):
        if column not in frame.columns:
            frame[column] = np.nan
    filtered = frame[
        [
            "beach_id",
            "county",
            "region",
            "sample_date",
            "sample_time",
            "enterococcus_value",
            "exceeds_stv",
            "latitude",
            "longitude",
            "historical_advisory_count",
            "cdip_distance_km",
            "erddap_distance_km",
            "cdip_station_id",
            "erddap_source_name",
            "wave_height_m",
            "dominant_period_s",
            "water_temperature_c",
            "salinity_psu",
            "uv_index",
            "wind_speed_mps",
            "tidal_height",
            "surf_height_observed",
            "turbidity_observed",
        ]
    ].dropna(subset=["sample_time", "enterococcus_value"])
    return _filter_plausible_training_rows(filtered)


def _load_fixture_training_frame() -> pd.DataFrame:
    settings = get_settings()
    payload = json.loads(Path(settings.fixture_data_path).read_text())
    rows: list[dict] = []
    for beach_id, entry in payload["observations"].items():
        for observation in entry["observations"]:
            rows.append(
                {
                    "beach_id": beach_id,
                    "county": "Fixture County",
                    "region": "Fixture Region",
                    "sample_date": observation["sample_time"][:10],
                    "sample_time": observation["sample_time"],
                    "enterococcus_value": observation["value"],
                    "exceeds_stv": int(observation["exceeds_stv"]),
                    "latitude": 32.9,
                    "longitude": -117.25,
                    "historical_advisory_count": 5,
                    "cdip_distance_km": 8.0,
                    "erddap_distance_km": 4.0,
                    "cdip_station_id": "191",
                    "erddap_source_name": "cencoos_del_mar_mooring",
                    "wave_height_m": entry["recent_environment"][-1]["wave_height_m"],
                    "dominant_period_s": 10.0,
                    "wave_direction_deg": np.nan,
                    "water_temperature_c": 15.0,
                    "salinity_psu": entry["recent_environment"][-1]["salinity_psu"],
                    "uv_index": entry["recent_environment"][-1]["uv_index"],
                    "wind_speed_mps": 4.0,
                    "streamflow_cfs_latest": np.nan,
                    "streamflow_cfs_mean_24h": np.nan,
                    "streamflow_cfs_max_24h": np.nan,
                    "streamflow_rising_flag": np.nan,
                    "precip_mm_6h": np.nan,
                    "precip_mm_24h": np.nan,
                    "precip_mm_48h": np.nan,
                    "precip_mm_72h": np.nan,
                    "precip_mm_7d": np.nan,
                    "precip_awi": np.nan,
                    "first_flush_flag": np.nan,
                    "distance_to_pour_point_km": np.nan,
                    "distance_to_gage_km": np.nan,
                    "watershed_area_km2": np.nan,
                }
    )
    return _filter_plausible_training_rows(pd.DataFrame(rows))


def _load_curated_training_frame(curated_dir: Path) -> pd.DataFrame:
    beach_day = pd.read_parquet(curated_dir / "beach_day.parquet")
    frame = beach_day.copy()
    # Exclude one-time-incident / unsupported stations: their sampling history
    # is too short to model and they'd inject noise (see station_quality).
    if "support_status" in frame.columns:
        frame = frame[frame["support_status"].astype(str) != "unsupported"].copy()
    frame["sample_time"] = pd.to_datetime(frame["sample_time"], errors="coerce")
    frame["sample_date"] = pd.to_datetime(frame["sample_date"], errors="coerce")
    frame["enterococcus_value"] = pd.to_numeric(frame["enterococcus_value"], errors="coerce")
    frame["exceeds_stv"] = frame["exceeds_stv"].astype(int)
    for column in (
        "county",
        "region",
        "latitude",
        "longitude",
        "historical_advisory_count",
        "cdip_distance_km",
        "erddap_distance_km",
        "cdip_station_id",
        "erddap_source_name",
        "wave_height_m",
        "dominant_period_s",
        "wave_direction_deg",
        "water_temperature_c",
        "salinity_psu",
        "uv_index",
        "wind_speed_mps",
        "tidal_height",
        "surf_height_observed",
        "turbidity_observed",
        "streamflow_cfs_latest",
        "streamflow_cfs_mean_24h",
        "streamflow_cfs_max_24h",
        "streamflow_rising_flag",
        "precip_mm_6h",
        "precip_mm_24h",
        "precip_mm_48h",
        "precip_mm_72h",
        "precip_mm_7d",
        "precip_awi",
        "first_flush_flag",
        "first_rain_score",
        "distance_to_pour_point_km",
        "distance_to_gage_km",
        "watershed_area_km2",
        *STORMWATER_EXPERT_NUMERIC_COLUMNS,
        *MARINE_MICROBIOLOGY_NUMERIC_COLUMNS,
    ):
        if column not in frame.columns:
            frame[column] = np.nan
    filtered = frame[
        [
            "beach_id",
            "county",
            "region",
            "sample_date",
            "sample_time",
            "enterococcus_value",
            "exceeds_stv",
            "latitude",
            "longitude",
            "historical_advisory_count",
            "cdip_distance_km",
            "erddap_distance_km",
            "cdip_station_id",
            "erddap_source_name",
            "wave_height_m",
            "dominant_period_s",
            "wave_direction_deg",
            "water_temperature_c",
            "salinity_psu",
            "uv_index",
            "wind_speed_mps",
            "tidal_height",
            "surf_height_observed",
            "turbidity_observed",
            "streamflow_cfs_latest",
            "streamflow_cfs_mean_24h",
            "streamflow_cfs_max_24h",
            "streamflow_rising_flag",
            "precip_mm_6h",
            "precip_mm_24h",
            "precip_mm_48h",
            "precip_mm_72h",
            "precip_mm_7d",
            "precip_awi",
            "first_flush_flag",
            "first_rain_score",
            "distance_to_pour_point_km",
            "distance_to_gage_km",
            "watershed_area_km2",
            *STORMWATER_EXPERT_NUMERIC_COLUMNS,
            *MARINE_MICROBIOLOGY_NUMERIC_COLUMNS,
        ]
    ].dropna(subset=["sample_time", "enterococcus_value"])
    return _filter_plausible_training_rows(filtered)


def train_baselines(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    dataset = build_sliding_windows(frame)
    features = dataset.feature_frame.select_dtypes(include=["number"]).fillna(0.0)
    labels = dataset.targets_exceed
    densities = dataset.targets_log_density

    metrics: dict[str, dict[str, float]] = {}
    if len(features) < 3:
        return {"warning": {"samples": float(len(features))}}

    baselines = make_baselines(features)

    persistence_probs = _persistence_probabilities(features, get_settings().epa_marine_enterococcus_stv)
    metrics["persistence"] = classification_metrics(labels, persistence_probs)

    baselines.logistic.fit(features, labels)
    logistic_probs = baselines.logistic.predict_proba(features)[:, 1]
    metrics["logistic"] = classification_metrics(labels, logistic_probs)

    baselines.linear.fit(features, densities)
    linear_preds = baselines.linear.predict(features)
    metrics["elastic_net"] = regression_metrics(densities, linear_preds)

    baselines.tree_classifier.fit(features, labels)
    tree_probs = baselines.tree_classifier.predict_proba(features)[:, 1]
    calibrator = ProbabilityCalibrator().fit(tree_probs, labels)
    metrics["hist_gbm"] = classification_metrics(labels, calibrator.transform(tree_probs))

    baselines.tree_regressor.fit(features, densities)
    tree_regression = baselines.tree_regressor.predict(features)
    metrics["hist_gbm_regressor"] = regression_metrics(densities, tree_regression)
    return metrics


def _persistence_probabilities(features: pd.DataFrame, stv_threshold: float) -> np.ndarray:
    """A fair persistence baseline: use the most-recent prior official observation.

    BeachWatch sampling is often weekly, so a strict lag-1 baseline degenerates into
    predicting the majority class. ``exceeds_stv_last_obs`` is the last observed
    exceedance prior to the target row (forecast-safe), so carrying it forward is
    the right "do what we did last time" comparator.

    It replaces the old ``enterococcus_value_last_obs > stv_threshold`` rule, which
    was method-blind: San Diego ddPCR rows report copies/100mL and must be judged
    against 1413 (see pipeline.exceedance), but this compared them against the 104
    culture STV and flagged clean water as an exceedance. At the time the serve
    path hard-pinned any persistence positive to 1.0, so that put 34 of the 74
    "High" bands served on 2026-07-30 on beaches whose most recent lab result was
    clean. ``exceeds_stv_last_obs`` carries the already-method-aware decision
    instead of re-deriving it.

    The serve path no longer pins (2026-08-06) — this now drives a post-
    calibration FLOOR at ``_LOW_THRESHOLD`` instead, so a wrong persistence
    positive costs a Moderate band rather than a certainty. The blast radius of
    getting this function wrong is correspondingly smaller, but it is still the
    input to that floor AND the persistence baseline every promotion gate scores
    against, so it must stay method-aware.

    ⚠️ ``exceeds_stv`` is not one label: culture rows are judged against 104
    MPN/CFU and San Diego ddPCR rows against 1413 copies, and on 1,175 paired
    same-day samples those two rules disagree on ~49% of pairs (PCR flags 0.603
    vs culture 0.122). So "the last sample exceeded" means a materially different
    event depending on which lab ran it. That is a labelling problem upstream of
    this function, not something it can fix.

    ``stv_threshold`` is retained only for the legacy fallback below, which applies
    to frames built before ``exceeds_stv_last_obs`` existed.
    """
    last_exceedance = features.get("exceeds_stv_last_obs")
    if last_exceedance is not None:
        exceeded = pd.to_numeric(last_exceedance, errors="coerce")
        return exceeded.fillna(0.0).gt(0.0).astype(float).to_numpy()

    last_obs = features.get("enterococcus_value_last_obs")
    if last_obs is None:
        return np.zeros(len(features), dtype=float)
    return (
        pd.to_numeric(last_obs, errors="coerce")
        .fillna(0.0)
        .gt(stv_threshold)
        .astype(float)
        .to_numpy()
    )


def _blend_probabilities(
    model_probabilities: np.ndarray,
    persistence_probabilities: np.ndarray,
    alpha: float,
) -> np.ndarray:
    return alpha * np.asarray(model_probabilities, dtype=float) + (1.0 - alpha) * np.asarray(
        persistence_probabilities, dtype=float
    )


def _positive_persistence_guarded_blend_probabilities(
    model_probabilities: np.ndarray,
    persistence_probabilities: np.ndarray,
    alpha: float,
) -> np.ndarray:
    """Blend, then OVERRIDE persistence positives to 1.0.

    This is the definition of the ``hist_gbm_positive_persistence_guard`` model
    candidate — the pin is the model, not a serving policy — so it must keep
    these exact semantics or the promotion gate silently rescores a different
    estimator against its own history.

    It is NOT the general serve-time behaviour any more. As of 2026-08-06 every
    other winner gets a post-calibration floor at ``_LOW_THRESHOLD`` instead;
    see the note in ``_export_forecasts``. (If this guard variant ever won
    promotion it would still pin, and would reintroduce the flattening the floor
    was adopted to fix — that is a known and accepted property of the candidate,
    not an oversight.)
    """
    blended = _blend_probabilities(model_probabilities, persistence_probabilities, alpha)
    persistence = np.asarray(persistence_probabilities, dtype=float)
    return np.where(persistence >= 0.5, 1.0, blended)


def _select_persistence_blend_alpha(
    labels: np.ndarray,
    model_probabilities: np.ndarray,
    persistence_probabilities: np.ndarray,
    *,
    alphas: list[float] | tuple[float, ...] = PERSISTENCE_BLEND_ALPHAS,
    max_alpha: float | None = None,
) -> float:
    labels = np.asarray(labels, dtype=float)
    candidate_alphas = [
        float(alpha)
        for alpha in alphas
        if max_alpha is None or float(alpha) <= max_alpha
    ]
    if not candidate_alphas:
        candidate_alphas = [float(max_alpha or 0.0)]

    def score(alpha: float) -> tuple[float, float]:
        blended = _blend_probabilities(model_probabilities, persistence_probabilities, alpha)
        brier = float(np.mean((blended - labels) ** 2))
        return brier, alpha

    return min(candidate_alphas, key=score)


def _metadata_with_groups(
    metadata: pd.DataFrame,
    frame: pd.DataFrame,
    *,
    stations: pd.DataFrame | None = None,
) -> pd.DataFrame:
    enriched = metadata.copy()
    if "sample_date" in enriched.columns:
        enriched["sample_date"] = pd.to_datetime(enriched["sample_date"], errors="coerce")
    static_lookup_columns = [
        column
        for column in (
            "county",
            "region",
            "latitude",
            "longitude",
            "cdip_distance_km",
            "erddap_distance_km",
        )
        if column in frame.columns
    ]
    if static_lookup_columns:
        group_lookup = (
            frame[["beach_id", *static_lookup_columns]]
            .dropna(subset=["beach_id"])
            .drop_duplicates(subset=["beach_id"])
        )
        enriched = enriched.merge(group_lookup, on="beach_id", how="left")
    if stations is not None and not stations.empty and "station_code" in stations.columns:
        station_lookup = (
            stations[["beach_id", "station_code"]]
            .dropna(subset=["beach_id"])
            .drop_duplicates(subset=["beach_id"])
        )
        enriched = enriched.merge(station_lookup, on="beach_id", how="left")
    if "wave_direction_deg" in frame.columns and "sample_date" in frame.columns and "sample_date" in enriched.columns:
        wave_lookup = frame[["beach_id", "sample_date", "wave_direction_deg"]].copy()
        wave_lookup["sample_date"] = pd.to_datetime(wave_lookup["sample_date"], errors="coerce")
        wave_lookup = wave_lookup.drop_duplicates(subset=["beach_id", "sample_date"], keep="last")
        enriched = enriched.merge(wave_lookup, on=["beach_id", "sample_date"], how="left")
    return enriched


def _coastal_cell_count(
    num_beaches: int,
    *,
    min_beaches_per_cluster: int = COASTAL_CELL_MIN_BEACHES_PER_CLUSTER,
    max_clusters: int = COASTAL_CELL_MAX_CLUSTERS,
) -> int:
    if num_beaches < 3:
        return 0
    return min(max_clusters, max(2, num_beaches // min_beaches_per_cluster))


def _coastal_cell_feature_frame(metadata: pd.DataFrame) -> pd.DataFrame:
    if metadata.empty or "beach_id" not in metadata.columns:
        return pd.DataFrame(columns=COASTAL_CELL_FEATURE_COLUMNS)

    rows: list[dict[str, float | str]] = []
    for beach_id, group in metadata.groupby("beach_id", sort=False):
        latitude_values = (
            pd.to_numeric(group["latitude"], errors="coerce")
            if "latitude" in group.columns
            else pd.Series(dtype=float)
        )
        longitude_values = (
            pd.to_numeric(group["longitude"], errors="coerce")
            if "longitude" in group.columns
            else pd.Series(dtype=float)
        )
        cdip_values = (
            pd.to_numeric(group["cdip_distance_km"], errors="coerce")
            if "cdip_distance_km" in group.columns
            else pd.Series(dtype=float)
        )
        erddap_values = (
            pd.to_numeric(group["erddap_distance_km"], errors="coerce")
            if "erddap_distance_km" in group.columns
            else pd.Series(dtype=float)
        )
        wave_direction = (
            pd.to_numeric(group["wave_direction_deg"], errors="coerce").dropna()
            if "wave_direction_deg" in group.columns
            else pd.Series(dtype=float)
        )
        latitude = latitude_values.median()
        longitude = longitude_values.median()
        cdip_distance = cdip_values.median()
        erddap_distance = erddap_values.median()
        if wave_direction.empty:
            wave_direction_sin = np.nan
            wave_direction_cos = np.nan
        else:
            radians = np.deg2rad(np.mod(wave_direction.to_numpy(dtype=float), 360.0))
            wave_direction_sin = float(np.sin(radians).mean())
            wave_direction_cos = float(np.cos(radians).mean())
        coastal_x_km = (
            float(longitude * np.cos(np.radians(latitude)) * 111.32)
            if pd.notna(latitude) and pd.notna(longitude)
            else np.nan
        )
        coastal_y_km = float(latitude * 110.57) if pd.notna(latitude) else np.nan
        rows.append(
            {
                "beach_id": beach_id,
                "coastal_x_km": coastal_x_km,
                "coastal_y_km": coastal_y_km,
                "cdip_distance_km_log1p": (
                    float(np.log1p(max(float(cdip_distance), 0.0))) if pd.notna(cdip_distance) else np.nan
                ),
                "erddap_distance_km_log1p": (
                    float(np.log1p(max(float(erddap_distance), 0.0))) if pd.notna(erddap_distance) else np.nan
                ),
                "wave_direction_sin": wave_direction_sin,
                "wave_direction_cos": wave_direction_cos,
            }
        )

    feature_frame = pd.DataFrame(rows)
    if feature_frame.empty:
        return pd.DataFrame(columns=COASTAL_CELL_FEATURE_COLUMNS)
    feature_frame = feature_frame.set_index("beach_id").reindex(columns=COASTAL_CELL_FEATURE_COLUMNS)
    for column in feature_frame.columns:
        if feature_frame[column].notna().sum() == 0:
            feature_frame[column] = 0.0
    return feature_frame


def _fit_coastal_cell_assigner(
    metadata: pd.DataFrame,
    train_rows: np.ndarray,
    *,
    min_beaches_per_cluster: int = COASTAL_CELL_MIN_BEACHES_PER_CLUSTER,
    max_clusters: int = COASTAL_CELL_MAX_CLUSTERS,
) -> CoastalCellAssigner | None:
    if len(train_rows) == 0:
        return None

    train_metadata = metadata.iloc[train_rows].reset_index(drop=True)
    beach_features = _coastal_cell_feature_frame(train_metadata)
    if beach_features.empty:
        return None

    requested_clusters = _coastal_cell_count(
        len(beach_features),
        min_beaches_per_cluster=min_beaches_per_cluster,
        max_clusters=max_clusters,
    )
    if requested_clusters < 2:
        return None

    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    imputed = imputer.fit_transform(beach_features)
    scaled = scaler.fit_transform(imputed)
    distinct_rows = pd.DataFrame(scaled).round(6).drop_duplicates()
    n_clusters = min(requested_clusters, len(distinct_rows))
    if n_clusters < 2:
        return None

    kmeans = KMeans(n_clusters=n_clusters, n_init=20, random_state=42)
    labels = kmeans.fit_predict(scaled)
    beach_cells = {
        beach_id: f"cell_{int(label)}"
        for beach_id, label in zip(beach_features.index.tolist(), labels, strict=False)
    }
    return CoastalCellAssigner(
        imputer=imputer,
        scaler=scaler,
        kmeans=kmeans,
        feature_columns=list(beach_features.columns),
        beach_cells=beach_cells,
    )


def _assign_coastal_cells(
    metadata: pd.DataFrame,
    assigner: CoastalCellAssigner | None,
) -> pd.Series:
    if assigner is None or metadata.empty or "beach_id" not in metadata.columns:
        return pd.Series([None] * len(metadata), index=metadata.index, dtype="object")

    beach_features = _coastal_cell_feature_frame(metadata).reindex(columns=assigner.feature_columns)
    if beach_features.empty:
        return pd.Series([None] * len(metadata), index=metadata.index, dtype="object")

    beach_cells: dict[str, str] = {}
    unknown_features = []
    unknown_beaches = []
    for beach_id, row in beach_features.iterrows():
        known_cell = assigner.beach_cells.get(beach_id)
        if known_cell is not None:
            beach_cells[str(beach_id)] = known_cell
            continue
        unknown_features.append(row.to_numpy(dtype=float))
        unknown_beaches.append(str(beach_id))

    if unknown_features:
        unknown_frame = pd.DataFrame(unknown_features, columns=assigner.feature_columns, dtype=float)
        transformed = assigner.imputer.transform(unknown_frame)
        scaled = assigner.scaler.transform(transformed)
        predicted = assigner.kmeans.predict(scaled)
        for beach_id, label in zip(unknown_beaches, predicted, strict=False):
            beach_cells[beach_id] = f"cell_{int(label)}"

    return metadata["beach_id"].astype(str).map(beach_cells)


def _eligible_holdout_groups(
    metadata: pd.DataFrame,
    group_column: str,
    min_rows: int,
    max_groups: int | None,
) -> pd.Series:
    if group_column not in metadata.columns:
        return pd.Series(dtype="int64")
    counts = metadata[group_column].dropna().value_counts()
    eligible = counts.loc[counts >= min_rows]
    if max_groups is not None:
        eligible = eligible.iloc[:max_groups]
    return eligible


def _fit_classifier_for_name(features: pd.DataFrame, model_name: str):
    baselines = make_baselines(features)
    if model_name == "logistic":
        return baselines.logistic
    if model_name == "hist_gbm":
        return baselines.tree_classifier
    if model_name == "xgb_undersample_ensemble":
        return XGBUndersampleEnsemble()
    if model_name == "xgb_undersample_offset":
        return XGBUndersampleOffsetEnsemble()
    raise ValueError(f"Unsupported classifier model '{model_name}'")


def _fit_classifier(classifier, X, y, beach_ids=None):
    """Fit, passing beach_ids only to classifiers that accept them (the two-tier
    offset model). Everything else keeps the plain sklearn ``fit(X, y)``."""
    if getattr(classifier, "accepts_beach_ids", False):
        classifier.fit(X, y, beach_ids=beach_ids)
    else:
        classifier.fit(X, y)
    return classifier


def _predict_pos(classifier, X, beach_ids=None):
    """predict_proba positive column, threading beach_ids to offset-aware models."""
    if getattr(classifier, "accepts_beach_ids", False):
        return classifier.predict_proba(X, beach_ids=beach_ids)[:, 1]
    return classifier.predict_proba(X)[:, 1]


def _fit_group_logistic_models(
    features: pd.DataFrame,
    labels: np.ndarray,
    metadata: pd.DataFrame,
    train_rows: np.ndarray,
    *,
    group_column: str,
    min_rows: int,
    min_positive_rows: int = 8,
    min_negative_rows: int = 8,
) -> dict[str, object]:
    if group_column not in metadata.columns or len(train_rows) == 0:
        return {}

    train_metadata = metadata.iloc[train_rows].reset_index(drop=True)
    group_counts = train_metadata[group_column].dropna().value_counts()
    models: dict[str, object] = {}

    for group_value, count in group_counts.items():
        if int(count) < min_rows:
            continue
        mask = train_metadata[group_column].eq(group_value).to_numpy()
        group_rows = train_rows[mask]
        group_labels = labels[group_rows]
        positives = int(group_labels.sum())
        negatives = int(len(group_rows) - positives)
        if positives < min_positive_rows or negatives < min_negative_rows:
            continue
        model = _fit_classifier_for_name(features, "logistic")
        model.fit(features.iloc[group_rows], group_labels)
        models[str(group_value)] = model

    return models


def _fit_hierarchical_logistic_artifacts(
    features: pd.DataFrame,
    labels: np.ndarray,
    metadata: pd.DataFrame,
    train_rows: np.ndarray,
    *,
    county_min_rows: int = 96,
    region_min_rows: int = 192,
    min_positive_rows: int = 8,
    min_negative_rows: int = 8,
) -> HierarchicalLogisticArtifacts:
    global_model = _fit_classifier_for_name(features, "logistic")
    global_model.fit(features.iloc[train_rows], labels[train_rows])
    county_models = _fit_group_logistic_models(
        features,
        labels,
        metadata,
        train_rows,
        group_column="county",
        min_rows=county_min_rows,
        min_positive_rows=min_positive_rows,
        min_negative_rows=min_negative_rows,
    )
    region_models = _fit_group_logistic_models(
        features,
        labels,
        metadata,
        train_rows,
        group_column="region",
        min_rows=region_min_rows,
        min_positive_rows=min_positive_rows,
        min_negative_rows=min_negative_rows,
    )
    return HierarchicalLogisticArtifacts(
        global_model=global_model,
        calibrator=None,
        county_models=county_models,
        region_models=region_models,
    )


def _predict_hierarchical_logistic_raw(
    artifacts: HierarchicalLogisticArtifacts,
    features: pd.DataFrame,
    metadata: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    if features.empty:
        return np.array([], dtype=float), np.array([], dtype=object)

    probabilities = artifacts.global_model.predict_proba(features)[:, 1]
    scopes = np.full(len(features), "global", dtype=object)

    for region, model in artifacts.region_models.items():
        mask = metadata.get("region", pd.Series(index=metadata.index, dtype="object")).eq(region).to_numpy()
        if not mask.any():
            continue
        row_idx = np.flatnonzero(mask)
        probabilities[row_idx] = model.predict_proba(features.iloc[row_idx])[:, 1]
        scopes[row_idx] = "region"

    for county, model in artifacts.county_models.items():
        mask = metadata.get("county", pd.Series(index=metadata.index, dtype="object")).eq(county).to_numpy()
        if not mask.any():
            continue
        row_idx = np.flatnonzero(mask)
        probabilities[row_idx] = model.predict_proba(features.iloc[row_idx])[:, 1]
        scopes[row_idx] = "county"

    return probabilities, scopes


def _fit_coastal_cell_logistic_artifacts(
    features: pd.DataFrame,
    labels: np.ndarray,
    metadata: pd.DataFrame,
    train_rows: np.ndarray,
    *,
    min_rows: int = 128,
    min_positive_rows: int = 8,
    min_negative_rows: int = 8,
    min_beaches_per_cluster: int = COASTAL_CELL_MIN_BEACHES_PER_CLUSTER,
    max_clusters: int = COASTAL_CELL_MAX_CLUSTERS,
) -> CoastalCellLogisticArtifacts:
    global_model = _fit_classifier_for_name(features, "logistic")
    global_model.fit(features.iloc[train_rows], labels[train_rows])
    assigner = _fit_coastal_cell_assigner(
        metadata,
        train_rows,
        min_beaches_per_cluster=min_beaches_per_cluster,
        max_clusters=max_clusters,
    )
    if assigner is None:
        return CoastalCellLogisticArtifacts(
            global_model=global_model,
            calibrator=None,
            cell_models={},
            assigner=None,
        )

    cell_metadata = metadata.copy()
    cell_metadata["coastal_cell"] = _assign_coastal_cells(cell_metadata, assigner)
    cell_models = _fit_group_logistic_models(
        features,
        labels,
        cell_metadata,
        train_rows,
        group_column="coastal_cell",
        min_rows=min_rows,
        min_positive_rows=min_positive_rows,
        min_negative_rows=min_negative_rows,
    )
    return CoastalCellLogisticArtifacts(
        global_model=global_model,
        calibrator=None,
        cell_models=cell_models,
        assigner=assigner,
    )


def _predict_coastal_cell_logistic_raw(
    artifacts: CoastalCellLogisticArtifacts,
    features: pd.DataFrame,
    metadata: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if features.empty:
        empty = np.array([], dtype=object)
        return np.array([], dtype=float), empty, empty

    probabilities = artifacts.global_model.predict_proba(features)[:, 1]
    assigned_cells = _assign_coastal_cells(metadata, artifacts.assigner)
    scopes = np.full(len(features), "global", dtype=object)

    if artifacts.cell_models:
        for cell, model in artifacts.cell_models.items():
            mask = assigned_cells.eq(cell).to_numpy()
            if not mask.any():
                continue
            row_idx = np.flatnonzero(mask)
            probabilities[row_idx] = model.predict_proba(features.iloc[row_idx])[:, 1]
            scopes[row_idx] = "coastal_cell"

    return probabilities, assigned_cells.fillna("unknown").to_numpy(dtype=object), scopes


def _default_spatial_jobs() -> int:
    logical_cores = os.cpu_count() or 8
    return max(1, min(8, logical_cores - 2))


def _spatial_holdout_fold_result(
    features: pd.DataFrame,
    labels: np.ndarray,
    metadata: pd.DataFrame,
    *,
    model_name: str,
    group_column: str,
    group_value: object,
    stv_threshold: float,
    min_rows: int,
    dataset: SlidingWindowDataset | None = None,
    sequence_epochs: int = 4,
) -> tuple[np.ndarray, np.ndarray] | None:
    test_mask = metadata[group_column].eq(group_value).to_numpy()
    train_mask = ~test_mask
    test_rows = np.flatnonzero(test_mask)
    train_rows = np.flatnonzero(train_mask)
    if len(test_rows) < min_rows or len(train_rows) < max(min_rows, 10):
        return None

    if model_name == "persistence":
        persistence = _persistence_probabilities(features, stv_threshold)
        return labels[test_rows], persistence[test_rows]

    train_metadata = metadata.iloc[train_rows][["sample_date"]].reset_index(drop=True)
    inner_train_idx, inner_valid_idx, _ = _blocked_indices(train_metadata)
    if len(inner_train_idx) == 0 or len(inner_valid_idx) == 0:
        return None

    inner_train_rows = train_rows[inner_train_idx]
    inner_valid_rows = train_rows[inner_valid_idx]
    if len(np.unique(labels[inner_train_rows])) < 2:
        return None

    # In spatial holdout folds the held-out county is never in the calibrator's
    # training data. HierarchicalProbabilityCalibrator falls back to global params
    # for unseen counties, causing calibration slope ≈ 0.18.  Force simple
    # ProbabilityCalibrator (isotonic) by omitting metadata from all calibrator
    # fits in this scope; _apply_calibrator routes correctly via isinstance check.
    def _identity_or_calibrated(p, labels, m=None):  # type: ignore[misc]
        from app.ml.training import _identity_or_calibrated as _orig  # noqa: F811
        return _orig(p, labels)  # metadata deliberately excluded

    if model_name in ["tcn", "cnn", "lstm", "transformer", "pinn"]:
        if dataset is None:
            return None
        artifacts = train_sequence_model(
            pd.DataFrame(),
            dataset=dataset,
            train_idx=inner_train_rows,
            valid_idx=inner_valid_rows,
            test_idx=test_rows,
            epochs=sequence_epochs,
            model_type=model_name,
        )
        if artifacts.test_probabilities is None:
            return None
        return labels[test_rows], artifacts.test_probabilities

    if model_name == "logistic_coastal_cells":
        artifacts = _fit_coastal_cell_logistic_artifacts(
            features,
            labels,
            metadata,
            inner_train_rows,
        )
        valid_raw, _, _ = _predict_coastal_cell_logistic_raw(
            artifacts,
            features.iloc[inner_valid_rows],
            metadata.iloc[inner_valid_rows].reset_index(drop=True),
        )
        _, calibrator = _identity_or_calibrated(
            valid_raw,
            labels[inner_valid_rows],
            metadata.iloc[inner_valid_rows].reset_index(drop=True),
        )
        test_probabilities, _, _ = _predict_coastal_cell_logistic_raw(
            artifacts,
            features.iloc[test_rows],
            metadata.iloc[test_rows].reset_index(drop=True),
        )
        test_probabilities = _apply_calibrator(
            calibrator,
            test_probabilities,
            metadata.iloc[test_rows].reset_index(drop=True),
        )
        return labels[test_rows], test_probabilities

    if model_name == "logistic_hierarchical":
        artifacts = _fit_hierarchical_logistic_artifacts(
            features,
            labels,
            metadata,
            inner_train_rows,
        )
        valid_raw, _ = _predict_hierarchical_logistic_raw(
            artifacts,
            features.iloc[inner_valid_rows],
            metadata.iloc[inner_valid_rows].reset_index(drop=True),
        )
        _, calibrator = _identity_or_calibrated(
            valid_raw,
            labels[inner_valid_rows],
            metadata.iloc[inner_valid_rows].reset_index(drop=True),
        )
        test_probabilities, _ = _predict_hierarchical_logistic_raw(
            artifacts,
            features.iloc[test_rows],
            metadata.iloc[test_rows].reset_index(drop=True),
        )
        test_probabilities = _apply_calibrator(
            calibrator,
            test_probabilities,
            metadata.iloc[test_rows].reset_index(drop=True),
        )
        return labels[test_rows], test_probabilities

    if model_name == "stacked_ensemble":
        # Logistic
        log_clf = make_baselines(features).logistic.fit(features.iloc[inner_train_rows], labels[inner_train_rows])
        log_val = log_clf.predict_proba(features.iloc[inner_valid_rows])[:, 1]
        _, log_cal = _identity_or_calibrated(log_val, labels[inner_valid_rows], metadata.iloc[inner_valid_rows].reset_index(drop=True))
        log_test = log_clf.predict_proba(features.iloc[test_rows])[:, 1]
        if log_cal is not None:
            log_val = _apply_calibrator(log_cal, log_val, metadata.iloc[inner_valid_rows].reset_index(drop=True))
            log_test = _apply_calibrator(log_cal, log_test, metadata.iloc[test_rows].reset_index(drop=True))
        
        # Coastal
        cc_art = _fit_coastal_cell_logistic_artifacts(features, labels, metadata, inner_train_rows)
        cc_val, _, _ = _predict_coastal_cell_logistic_raw(cc_art, features.iloc[inner_valid_rows], metadata.iloc[inner_valid_rows].reset_index(drop=True))
        _, cc_cal = _identity_or_calibrated(cc_val, labels[inner_valid_rows], metadata.iloc[inner_valid_rows].reset_index(drop=True))
        cc_test, _, _ = _predict_coastal_cell_logistic_raw(cc_art, features.iloc[test_rows], metadata.iloc[test_rows].reset_index(drop=True))
        if cc_cal is not None:
            cc_val = _apply_calibrator(cc_cal, cc_val, metadata.iloc[inner_valid_rows].reset_index(drop=True))
            cc_test = _apply_calibrator(cc_cal, cc_test, metadata.iloc[test_rows].reset_index(drop=True))

        # Hierarchical
        h_art = _fit_hierarchical_logistic_artifacts(features, labels, metadata, inner_train_rows)
        h_val, _ = _predict_hierarchical_logistic_raw(h_art, features.iloc[inner_valid_rows], metadata.iloc[inner_valid_rows].reset_index(drop=True))
        _, h_cal = _identity_or_calibrated(h_val, labels[inner_valid_rows], metadata.iloc[inner_valid_rows].reset_index(drop=True))
        h_test, _ = _predict_hierarchical_logistic_raw(h_art, features.iloc[test_rows], metadata.iloc[test_rows].reset_index(drop=True))
        if h_cal is not None:
            h_val = _apply_calibrator(h_cal, h_val, metadata.iloc[inner_valid_rows].reset_index(drop=True))
            h_test = _apply_calibrator(h_cal, h_test, metadata.iloc[test_rows].reset_index(drop=True))

        # GBM
        gbm_clf = make_baselines(features).tree_classifier.fit(features.iloc[inner_train_rows], labels[inner_train_rows])
        gbm_val = gbm_clf.predict_proba(features.iloc[inner_valid_rows])[:, 1]
        _, gbm_cal = _identity_or_calibrated(gbm_val, labels[inner_valid_rows], metadata.iloc[inner_valid_rows].reset_index(drop=True))
        gbm_test = gbm_clf.predict_proba(features.iloc[test_rows])[:, 1]
        if gbm_cal is not None:
            gbm_val = _apply_calibrator(gbm_cal, gbm_val, metadata.iloc[inner_valid_rows].reset_index(drop=True))
            gbm_test = _apply_calibrator(gbm_cal, gbm_test, metadata.iloc[test_rows].reset_index(drop=True))

        # ensemble weights based on AUCPR
        from sklearn.metrics import average_precision_score
        aucs = []
        for v in [log_val, cc_val, h_val, gbm_val]:
            try:
                aucs.append(average_precision_score(labels[inner_valid_rows], v))
            except ValueError:
                aucs.append(0.0)
        _aucs = np.array(aucs)
        _s = _aucs.sum()
        w = _aucs / _s if _s > 0 else np.full(4, 0.25)

        test_probabilities = log_test * w[0] + cc_test * w[1] + h_test * w[2] + gbm_test * w[3]
        return labels[test_rows], test_probabilities

    if model_name == "hist_gbm_persistence_blend":
        classifier = _fit_classifier_for_name(features, "hist_gbm")
        classifier.fit(features.iloc[inner_train_rows], labels[inner_train_rows])
        valid_raw = classifier.predict_proba(features.iloc[inner_valid_rows])[:, 1]
        _, calibrator = _identity_or_calibrated(
            valid_raw,
            labels[inner_valid_rows],
            metadata.iloc[inner_valid_rows].reset_index(drop=True),
        )
        valid_probabilities = _apply_calibrator(
            calibrator,
            valid_raw,
            metadata.iloc[inner_valid_rows].reset_index(drop=True),
        )
        test_probabilities = classifier.predict_proba(features.iloc[test_rows])[:, 1]
        test_probabilities = _apply_calibrator(
            calibrator,
            test_probabilities,
            metadata.iloc[test_rows].reset_index(drop=True),
        )
        persistence = _persistence_probabilities(features, stv_threshold)
        alpha = _select_persistence_blend_alpha(
            labels[inner_valid_rows],
            valid_probabilities,
            persistence[inner_valid_rows],
            max_alpha=PERSISTENCE_BLEND_MAX_MODEL_ALPHA,
        )
        return labels[test_rows], _blend_probabilities(test_probabilities, persistence[test_rows], alpha)

    if model_name == "hist_gbm_positive_persistence_guard":
        classifier = _fit_classifier_for_name(features, "hist_gbm")
        classifier.fit(features.iloc[inner_train_rows], labels[inner_train_rows])
        valid_raw = classifier.predict_proba(features.iloc[inner_valid_rows])[:, 1]
        _, calibrator = _identity_or_calibrated(
            valid_raw,
            labels[inner_valid_rows],
            metadata.iloc[inner_valid_rows].reset_index(drop=True),
        )
        test_probabilities = classifier.predict_proba(features.iloc[test_rows])[:, 1]
        test_probabilities = _apply_calibrator(
            calibrator,
            test_probabilities,
            metadata.iloc[test_rows].reset_index(drop=True),
        )
        persistence = _persistence_probabilities(features, stv_threshold)
        return labels[test_rows], _positive_persistence_guarded_blend_probabilities(
            test_probabilities,
            persistence[test_rows],
            PERSISTENCE_BLEND_MAX_MODEL_ALPHA,
        )

    classifier = _fit_classifier_for_name(features, model_name)
    _beach = metadata["beach_id"].to_numpy() if "beach_id" in metadata.columns else None
    _fit_classifier(
        classifier,
        features.iloc[inner_train_rows],
        labels[inner_train_rows],
        beach_ids=_beach[inner_train_rows] if _beach is not None else None,
    )
    valid_raw = _predict_pos(
        classifier,
        features.iloc[inner_valid_rows],
        beach_ids=_beach[inner_valid_rows] if _beach is not None else None,
    )
    _, calibrator = _identity_or_calibrated(
        valid_raw,
        labels[inner_valid_rows],
        metadata.iloc[inner_valid_rows].reset_index(drop=True),
    )
    _test_meta = metadata.iloc[test_rows].reset_index(drop=True)
    _test_beach = _beach[test_rows] if _beach is not None else None
    test_probabilities = _predict_pos(classifier, features.iloc[test_rows], beach_ids=_test_beach)
    test_probabilities = _apply_calibrator(calibrator, test_probabilities, _test_meta)
    # Stale-regime (served-day) eval: re-score the SAME held-out rows with the
    # anchor censored to serving age, so the pooled within-beach metric reflects
    # the between-sample regime the product serves (model_truth.md) rather than the
    # fresh sample-day the leave-one-out backtest otherwise measures. Calibration is
    # monotonic, so within-beach AUROC is unaffected by reusing the fresh calibrator.
    test_stale = censor_bacteria_history_for_cutoff(
        features.iloc[test_rows], cutoff_days=_SERVING_STALE_CUTOFF_DAYS
    )
    test_probabilities_stale = _predict_pos(classifier, test_stale, beach_ids=_test_beach)
    test_probabilities_stale = _apply_calibrator(calibrator, test_probabilities_stale, _test_meta)
    return labels[test_rows], test_probabilities, test_probabilities_stale


def _spatial_holdout_metrics(
    features: pd.DataFrame,
    labels: np.ndarray,
    metadata: pd.DataFrame,
    *,
    model_name: str,
    group_column: str,
    stv_threshold: float,
    min_rows: int,
    max_groups: int | None = None,
    spatial_jobs: int = 1,
    dataset: SlidingWindowDataset | None = None,
    sequence_epochs: int = 4,
    predictions_sink: dict | None = None,
) -> dict[str, float]:
    eligible_groups = _eligible_holdout_groups(metadata, group_column, min_rows=min_rows, max_groups=max_groups)
    if eligible_groups.empty:
        return {"folds": 0.0, "eligible_groups": 0.0, "heldout_rows": 0.0}

    heldout_labels: list[np.ndarray] = []
    heldout_probabilities: list[np.ndarray] = []
    group_values = eligible_groups.index.tolist()
    # PyTorch sequence-model backtests retrain per fold and do not serialize
    # cleanly through joblib/loky worker processes on this stack.
    effective_spatial_jobs = 1
    if effective_spatial_jobs > 1 and len(group_values) > 1:
        with parallel_backend("loky", inner_max_num_threads=1):
            fold_results = Parallel(n_jobs=min(effective_spatial_jobs, len(group_values)))(
                delayed(_spatial_holdout_fold_result)(
                    features,
                    labels,
                    metadata,
                    model_name=model_name,
                    group_column=group_column,
                    group_value=group_value,
                    stv_threshold=stv_threshold,
                    min_rows=min_rows,
                    dataset=dataset,
                    sequence_epochs=sequence_epochs,
                )
                for group_value in group_values
            )
    else:
        fold_results = [
            _spatial_holdout_fold_result(
                features,
                labels,
                metadata,
                model_name=model_name,
                group_column=group_column,
                group_value=group_value,
                stv_threshold=stv_threshold,
                min_rows=min_rows,
                dataset=dataset,
                sequence_epochs=sequence_epochs,
            )
            for group_value in group_values
        ]

    used_groups = 0
    heldout_groups: list[np.ndarray] = []
    heldout_probabilities_stale: list[np.ndarray] = []
    all_folds_have_stale = True
    for group_value, result in zip(group_values, fold_results):
        if result is None:
            continue
        fold_labels, fold_probabilities = result[0], result[1]
        heldout_labels.append(fold_labels)
        heldout_probabilities.append(fold_probabilities)
        heldout_groups.append(np.full(len(fold_labels), group_value))
        # 3rd element (present on the generic-classifier path) is the same rows
        # re-scored with the anchor censored to serving age — the served regime.
        fold_stale = result[2] if len(result) > 2 else None
        if fold_stale is not None:
            heldout_probabilities_stale.append(fold_stale)
        else:
            all_folds_have_stale = False
        used_groups += 1

    if not heldout_labels:
        return {
            "folds": 0.0,
            "eligible_groups": float(len(eligible_groups)),
            "heldout_rows": 0.0,
        }

    all_labels = np.concatenate(heldout_labels)
    all_probabilities = np.concatenate(heldout_probabilities)
    all_groups = np.concatenate(heldout_groups) if heldout_groups else np.array([])
    # Stash the pooled per-row holdout predictions so the caller can persist them
    # (a single retrain re-derives them, but nothing on disk does today). Keyed by
    # model+group_column so the production winner's pairs can be selected later.
    if predictions_sink is not None:
        sink_entry = {
            "labels": all_labels,
            "probabilities": all_probabilities,
            "groups": all_groups,
        }
        if heldout_probabilities_stale and all_folds_have_stale:
            stale_pooled = np.concatenate(heldout_probabilities_stale)
            if len(stale_pooled) == len(all_labels):
                sink_entry["probabilities_stale"] = stale_pooled
        predictions_sink[(model_name, group_column)] = sink_entry
    metrics = classification_metrics(all_labels, all_probabilities)
    metrics["folds"] = float(used_groups)
    metrics["eligible_groups"] = float(len(eligible_groups))
    metrics["heldout_rows"] = float(len(all_labels))
    metrics["positive_rate"] = float(all_labels.mean())
    # Cluster-bootstrap CI for the pooled AUCPR (resampling unit = the fold). The
    # point AUCPR over only 6 county / 15 beach folds is noisy run-to-run; shipping
    # the CI into system_health.json makes that uncertainty visible to consumers.
    ci_low, ci_high = cluster_bootstrap_aucpr_ci(
        all_labels,
        all_probabilities,
        all_groups,
        n_resamples=500,
        seed=_SPATIAL_BOOTSTRAP_SEED,
    )
    metrics["aucpr_ci_low"] = ci_low
    metrics["aucpr_ci_high"] = ci_high
    return metrics


def _spatial_backtest_metrics(
    features: pd.DataFrame,
    labels: np.ndarray,
    metadata: pd.DataFrame,
    *,
    stv_threshold: float,
    beach_group_limit: int | None = None,
    county_group_limit: int | None = None,
    spatial_jobs: int = 1,
    dataset: SlidingWindowDataset | None = None,
    model_types_to_run: list[str] | None = None,
    model_names_to_run: list[str] | None = None,
    sequence_epochs: int = 4,
    predictions_sink: dict | None = None,
) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}
    selected_model_names = model_names_to_run
    if selected_model_names is None:
        selected_model_names = [*SPATIAL_BACKTEST_MODEL_NAMES]
        if model_types_to_run:
            selected_model_names.extend(
                model_name for model_name in model_types_to_run if model_name in SEQUENCE_MODEL_NAMES
            )

    normalized_model_names: list[str] = []
    for model_name in ["persistence", *selected_model_names]:
        is_supported_spatial_model = (
            model_name in SPATIAL_BACKTEST_MODEL_NAMES or model_name in SEQUENCE_MODEL_NAMES
        )
        if model_name != "persistence" and not is_supported_spatial_model:
            continue
        if model_name not in normalized_model_names:
            normalized_model_names.append(model_name)

    county_backtests_enabled = "county" in metadata.columns and metadata["county"].notna().any()
    for model_name in normalized_model_names:
        sequence_dataset = dataset if model_name in SEQUENCE_MODEL_NAMES else None
        metrics[f"spatial_beach_{model_name}"] = _spatial_holdout_metrics(
            features,
            labels,
            metadata,
            model_name=model_name,
            group_column="beach_id",
            stv_threshold=stv_threshold,
            min_rows=8,
            max_groups=beach_group_limit,
            spatial_jobs=spatial_jobs,
            dataset=sequence_dataset,
            sequence_epochs=sequence_epochs,
            predictions_sink=predictions_sink,
        )
        if county_backtests_enabled:
            metrics[f"spatial_county_{model_name}"] = _spatial_holdout_metrics(
                features,
                labels,
                metadata,
                model_name=model_name,
                group_column="county",
                stv_threshold=stv_threshold,
                min_rows=32,
                max_groups=county_group_limit,
                spatial_jobs=spatial_jobs,
                dataset=sequence_dataset,
                sequence_epochs=sequence_epochs,
                predictions_sink=predictions_sink,
            )
    return metrics


def _build_sequence_dataset(dataset) -> tuple[pd.DataFrame, SequenceDataset, dict[str, int]]:
    features = dataset.feature_frame.select_dtypes(include=["number"]).fillna(0.0)
    site_lookup = {site: idx for idx, site in enumerate(sorted(dataset.metadata["beach_id"].unique()))}
    site_indices = dataset.metadata["beach_id"].map(site_lookup).to_numpy(dtype=np.int64)
    sequence_dataset = SequenceDataset(
        sequences=dataset.sequence_array,
        static_features=features.to_numpy(dtype=np.float32),
        site_indices=site_indices,
        exceed_targets=dataset.targets_exceed,
        density_targets=dataset.targets_log_density,
    )
    return features, sequence_dataset, site_lookup


def _training_device() -> torch.device:
    if torch.backends.mps.is_available():
        torch.set_float32_matmul_precision("high")
        return torch.device("mps")
    return torch.device("cpu")


def _predict_sequence_subset(
    model: nn.Module,
    sequence_dataset: SequenceDataset,
    indices: np.ndarray,
    device: torch.device,
) -> tuple[np.ndarray, np.ndarray]:
    if len(indices) == 0:
        return np.array([], dtype=float), np.array([], dtype=float)
    sequence = sequence_dataset.sequences[indices].to(device)
    static = sequence_dataset.static_features[indices].to(device)
    site_index = sequence_dataset.site_indices[indices].to(device)
    with torch.no_grad():
        outputs = model(sequence, static, site_index)
        logits = outputs[0]
        density = outputs[1]
    probabilities = torch.sigmoid(logits).cpu().numpy()
    density_predictions = density.cpu().numpy()
    return probabilities, density_predictions


def train_sequence_model(
    frame: pd.DataFrame,
    *,
    dataset: SlidingWindowDataset | None = None,
    train_idx: np.ndarray | None = None,
    valid_idx: np.ndarray | None = None,
    test_idx: np.ndarray | None = None,
    epochs: int = 8,
    model_type: str = "tcn",
) -> SequenceTrainingArtifacts:
    if dataset is None:
        dataset = build_sliding_windows(frame)
    if dataset.feature_frame.empty or dataset.metadata.empty or len(dataset.sequence_array) == 0:
        warning = {"warning": 0.0}
        return SequenceTrainingArtifacts(
            valid_metrics=warning,
            test_metrics=warning,
            model=None,
            calibrator=None,
            site_lookup={},
            static_feature_columns=[],
        )
    features, sequence_dataset, site_lookup = _build_sequence_dataset(dataset)
    if len(features) < 3:
        warning = {"warning": float(len(features))}
        return SequenceTrainingArtifacts(
            valid_metrics=warning,
            test_metrics=warning,
            model=None,
            calibrator=None,
            site_lookup={},
            static_feature_columns=[],
        )

    if train_idx is None or valid_idx is None or test_idx is None:
        train_idx, valid_idx, test_idx = _blocked_indices(dataset.metadata)
    if len(train_idx) == 0 or len(valid_idx) == 0:
        warning = {"warning": float(len(features))}
        return SequenceTrainingArtifacts(
            valid_metrics=warning,
            test_metrics=warning,
            model=None,
            calibrator=None,
            site_lookup=site_lookup,
            static_feature_columns=list(features.columns),
        )

    loader = DataLoader(
        Subset(sequence_dataset, train_idx.tolist()),
        batch_size=min(128, len(train_idx)),
        shuffle=True,
    )
    if model_type == "cnn":
        model = BeachCNN(
            sequence_features=dataset.sequence_array.shape[-1],
            static_features=features.shape[1],
            num_sites=len(site_lookup),
        )
    elif model_type == "lstm":
        model = BeachLSTM(
            sequence_features=dataset.sequence_array.shape[-1],
            static_features=features.shape[1],
            num_sites=len(site_lookup),
        )
    elif model_type == "transformer":
        model = BeachTransformer(
            sequence_features=dataset.sequence_array.shape[-1],
            static_features=features.shape[1],
            num_sites=len(site_lookup),
        )
    elif model_type == "pinn":
        model = BeachPINN_MultiTask(
            sequence_features=dataset.sequence_array.shape[-1],
            static_features=features.shape[1],
            num_sites=len(site_lookup),
        )
    else:
        model = BeachTCN(
            sequence_features=dataset.sequence_array.shape[-1],
            static_features=features.shape[1],
            num_sites=len(site_lookup),
        )
    device = _training_device()
    model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    bce = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([3.0], device=device))
    mse = nn.MSELoss()

    for _ in range(epochs):
        model.train()
        for batch in loader:
            optimizer.zero_grad()
            outputs = model(
                batch["sequence"].to(device),
                batch["static"].to(device),
                batch["site_index"].to(device),
            )
            logits = outputs[0]
            density = outputs[1]
            loss = bce(logits, batch["target_exceed"].to(device)) + mse(
                density, batch["target_density"].to(device)
            )
            if model_type == "pinn" and len(outputs) > 2:
                # Force shared layers to learn physics representation
                # by predicting the first exogenous covariate (e.g., UV or streamflow)
                physics_pred = outputs[2]
                physics_target = batch["static"][:, 0].to(device)
                loss += mse(physics_pred, physics_target)

            loss.backward()
            optimizer.step()

    valid_probabilities, valid_density = _predict_sequence_subset(model, sequence_dataset, valid_idx, device)
    valid_metrics = classification_metrics(dataset.targets_exceed[valid_idx], valid_probabilities)
    valid_metrics.update(regression_metrics(dataset.targets_log_density[valid_idx], valid_density))
    _, calibrator = _identity_or_calibrated(
        valid_probabilities,
        dataset.targets_exceed[valid_idx],
        dataset.metadata.iloc[valid_idx].reset_index(drop=True),
    )

    if len(test_idx):
        test_probabilities, test_density = _predict_sequence_subset(model, sequence_dataset, test_idx, device)
        test_probabilities = _apply_calibrator(
            calibrator,
            test_probabilities,
            dataset.metadata.iloc[test_idx].reset_index(drop=True),
        )
        test_metrics = classification_metrics(dataset.targets_exceed[test_idx], test_probabilities)
        test_metrics.update(regression_metrics(dataset.targets_log_density[test_idx], test_density))
    else:
        test_metrics = dict(valid_metrics)

    return SequenceTrainingArtifacts(
        valid_metrics=valid_metrics,
        test_metrics=test_metrics,
        model=model,
        calibrator=calibrator,
        site_lookup=site_lookup,
        static_feature_columns=list(features.columns),
        test_probabilities=test_probabilities if len(test_idx) else None,
    )


def _blocked_indices(metadata: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sample_dates = pd.to_datetime(metadata["sample_date"], errors="coerce").dt.normalize()
    unique_dates = (
        pd.DatetimeIndex(sample_dates.dropna().unique())
        .sort_values()
        .to_numpy(dtype="datetime64[ns]")
    )
    if len(unique_dates) == 0:
        empty = np.array([], dtype=int)
        return empty, empty, empty

    if len(unique_dates) == 1:
        train_dates = unique_dates
        valid_dates = np.array([], dtype="datetime64[ns]")
        test_dates = np.array([], dtype="datetime64[ns]")
    elif len(unique_dates) == 2:
        train_dates = unique_dates[:1]
        valid_dates = unique_dates[1:]
        test_dates = np.array([], dtype="datetime64[ns]")
    else:
        train_end = max(int(len(unique_dates) * 0.7), 1)
        valid_end = max(int(len(unique_dates) * 0.85), train_end + 1)
        valid_end = min(valid_end, len(unique_dates) - 1)
        train_dates = unique_dates[:train_end]
        valid_dates = unique_dates[train_end:valid_end]
        test_dates = unique_dates[valid_end:]

    sample_dates_array = sample_dates.to_numpy(dtype="datetime64[ns]")
    train_idx = np.flatnonzero(np.isin(sample_dates_array, train_dates))
    valid_idx = np.flatnonzero(np.isin(sample_dates_array, valid_dates))
    test_idx = np.flatnonzero(np.isin(sample_dates_array, test_dates))
    return train_idx, valid_idx, test_idx


def _active_beach_ids(
    full_frame: pd.DataFrame,
    forecast_date: date,
    min_sample_recency_days: int,
) -> set[str]:
    """Return the set of beach_ids whose most-recent sample is within N days of forecast_date.

    "Active" here means "currently being monitored" — the deployment-relevant
    population. California beach monitoring funding has been cut multiple times
    since 2020 and many stations have gone silent. Holdout metrics restricted
    to this set answer the question "how good is the model for the beaches users
    actually see in the app today" — not "how good is it across the historical
    population including stations that no longer report data."
    """
    if full_frame.empty:
        return set()
    sample_dates = pd.to_datetime(full_frame["sample_date"], errors="coerce")
    cutoff = pd.Timestamp(forecast_date) - pd.Timedelta(days=min_sample_recency_days)
    most_recent = full_frame.assign(_sd=sample_dates).groupby("beach_id")["_sd"].max()
    return set(most_recent[most_recent >= cutoff].index.astype(str))


def _classification_metrics_on_subset(
    labels_full: np.ndarray,
    probs_full: np.ndarray,
    metadata_full: pd.DataFrame,
    keep_beach_ids: set[str],
) -> dict[str, float] | None:
    """Compute classification metrics on the rows whose beach_id is in keep_beach_ids."""
    if not keep_beach_ids or len(metadata_full) == 0:
        return None
    mask = metadata_full["beach_id"].astype(str).isin(keep_beach_ids).to_numpy()
    if not mask.any() or labels_full[mask].size == 0:
        return None
    return classification_metrics(labels_full[mask], probs_full[mask])


def _calibration_split(
    valid_idx: np.ndarray,
    metadata: pd.DataFrame,
    *,
    seed: int = 17,
) -> tuple[np.ndarray, np.ndarray]:
    """Split valid_idx into a calibrator-fit half and a metrics-reporting half.

    The hierarchical calibrator is currently fit on the same valid_idx slice
    that is then used to report validation AUCPR/Brier. That makes the published
    "valid_metrics" partially in-sample for calibration, which inflates them.
    Splitting forces the reported numbers to be honest out-of-sample on the
    calibration step.

    Stratifies by county where possible to keep both halves balanced. Counties
    with only one valid sample go entirely into the calibration half (so the
    calibrator sees every county at least once); the metrics half loses that row.
    """
    valid_idx = np.asarray(valid_idx, dtype=int)
    if valid_idx.size < 4:
        # Too small to split; fall back to using the whole slice for both.
        return valid_idx, valid_idx

    rng = np.random.default_rng(seed)
    counties = metadata["county"].fillna("__unknown__").to_numpy()[valid_idx]
    cal_pieces: list[np.ndarray] = []
    metric_pieces: list[np.ndarray] = []

    for county in np.unique(counties):
        county_mask = counties == county
        county_idx = valid_idx[county_mask]
        permuted = rng.permutation(county_idx)
        if permuted.size <= 1:
            cal_pieces.append(permuted)
            continue
        half = max(permuted.size // 2, 1)
        cal_pieces.append(permuted[:half])
        metric_pieces.append(permuted[half:])

    cal_idx = (
        np.sort(np.concatenate(cal_pieces))
        if cal_pieces
        else np.array([], dtype=int)
    )
    metric_idx = (
        np.sort(np.concatenate(metric_pieces))
        if metric_pieces
        else np.array([], dtype=int)
    )
    if metric_idx.size == 0:
        # Degenerate case: every county had only one sample. Use cal for metrics too.
        return cal_idx, cal_idx
    return cal_idx, metric_idx


def _identity_or_calibrated(
    probabilities: np.ndarray,
    labels: np.ndarray,
    metadata: pd.DataFrame | None = None,
) -> tuple[np.ndarray, ProbabilityCalibrator | HierarchicalProbabilityCalibrator | None]:
    labels = np.asarray(labels)
    if len(probabilities) == 0 or len(labels) == 0 or len(np.unique(labels)) < 2:
        return probabilities, None
    if metadata is not None and not metadata.empty and {"county", "beach_id"}.issubset(metadata.columns):
        calibrator = HierarchicalProbabilityCalibrator(min_county_rows=4, min_site_rows=4).fit(
            probabilities, labels, metadata.reset_index(drop=True)
        )
        return calibrator.transform(probabilities, metadata.reset_index(drop=True)), calibrator
    calibrator = ProbabilityCalibrator().fit(probabilities, labels)
    return calibrator.transform(probabilities), calibrator


def _apply_calibrator(
    calibrator: ProbabilityCalibrator | HierarchicalProbabilityCalibrator | None,
    probabilities: np.ndarray,
    metadata: pd.DataFrame | None = None,
) -> np.ndarray:
    if calibrator is None:
        return probabilities
    if isinstance(calibrator, HierarchicalProbabilityCalibrator):
        return calibrator.transform(probabilities, metadata)
    return calibrator.transform(probabilities)


def _calibration_interval(
    calibrator: ProbabilityCalibrator | HierarchicalProbabilityCalibrator | None,
    probabilities: np.ndarray,
    metadata: pd.DataFrame | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(calibrator, HierarchicalProbabilityCalibrator):
        return calibrator.predict_interval(probabilities, metadata)
    return np.full(len(probabilities), np.nan), np.full(len(probabilities), np.nan)


def _split_conformal_half_width(
    labels: np.ndarray,
    predictions: np.ndarray,
    coverage: float = 0.9,
) -> float | None:
    if len(labels) == 0 or len(predictions) == 0:
        return None
    residuals = np.abs(np.asarray(labels, dtype=float) - np.asarray(predictions, dtype=float))
    residuals = residuals[~np.isnan(residuals)]
    if len(residuals) == 0:
        return None
    quantile = min(1.0, np.ceil((len(residuals) + 1) * coverage) / len(residuals))
    return float(np.quantile(residuals, quantile, method="higher"))


def _best_valid_brier_model(
    metrics: dict[str, dict[str, float]],
    model_names: list[str] | tuple[str, ...],
    *,
    fallback: str | None = None,
) -> str | None:
    candidates = [
        model_name
        for model_name in model_names
        if "brier" in metrics.get(f"{model_name}_valid", {})
    ]
    if not candidates:
        return fallback
    return min(candidates, key=lambda model_name: metrics[f"{model_name}_valid"]["brier"])


def _best_valid_aucpr_model(
    metrics: dict[str, dict[str, float]],
    model_names: list[str] | tuple[str, ...],
    *,
    fallback: str | None = None,
) -> str | None:
    """Pick the model with the highest validation AUCPR; break ties by lower Brier.

    AUCPR is a rank-only metric: it is invariant to monotonic recalibration, so
    selecting on AUCPR rewards genuine discrimination rather than calibration.
    The earlier selector minimized validation Brier, which favored well-calibrated
    but flat models — a worse criterion when calibration is a downstream stage.
    """
    candidates = [
        model_name
        for model_name in model_names
        if "aucpr" in metrics.get(f"{model_name}_valid", {})
    ]
    if not candidates:
        return fallback

    def _key(model_name: str) -> tuple[float, float]:
        valid = metrics[f"{model_name}_valid"]
        # max AUCPR (negate for min-key), tiebreak by min Brier.
        return (-float(valid.get("aucpr", 0.0)), float(valid.get("brier", 0.0)))

    return min(candidates, key=_key)


def _two_stage_training_plan(
    metrics: dict[str, dict[str, float]],
    model_types_to_run: list[str],
) -> StageTwoTrainingPlan:
    production_winner = _best_valid_aucpr_model(
        metrics,
        PRODUCTION_MODEL_NAMES,
        fallback="logistic",
    ) or "logistic"
    research_candidates = [
        *PRODUCTION_MODEL_NAMES,
        *[model_name for model_name in model_types_to_run if model_name in SEQUENCE_MODEL_NAMES],
    ]
    research_winner = _best_valid_aucpr_model(
        metrics,
        research_candidates,
        fallback=production_winner,
    ) or production_winner
    spatial_backtest_models: list[str] = []
    for model_name in (production_winner, research_winner):
        if model_name not in spatial_backtest_models:
            spatial_backtest_models.append(model_name)
    if "hist_gbm_positive_persistence_guard" not in spatial_backtest_models:
        spatial_backtest_models.append("hist_gbm_positive_persistence_guard")
    if "hist_gbm_persistence_blend" not in spatial_backtest_models:
        spatial_backtest_models.append("hist_gbm_persistence_blend")
    # Spatially-validated challenger: must be backtested so the gate can swap it
    # in over the temporal winner on held-out counties (+0.069 AUCPR vs hist_gbm).
    if "xgb_undersample_ensemble" not in spatial_backtest_models:
        spatial_backtest_models.append("xgb_undersample_ensemble")
    return StageTwoTrainingPlan(
        production_winner=production_winner,
        research_winner=research_winner,
        spatial_backtest_models=spatial_backtest_models,
    )


def _paired_county_aucpr_gap_ci(
    challenger: str,
    incumbent: str,
    predictions_sink: dict | None,
) -> tuple[float, float] | None:
    """90% paired cluster-bootstrap CI of the held-out county-AUCPR gap.

    Returns ``(low, high)`` for (challenger - incumbent) over resampled county
    folds, or ``None`` when the per-row holdout predictions are unavailable for
    either model (the caller then uses the conservative large-gap fallback).
    """
    if not predictions_sink:
        return None
    challenger_preds = predictions_sink.get((challenger, "county"))
    incumbent_preds = predictions_sink.get((incumbent, "county"))
    if not challenger_preds or not incumbent_preds:
        return None
    challenger_groups = challenger_preds.get("groups")
    incumbent_groups = incumbent_preds.get("groups")
    if (
        challenger_groups is None
        or incumbent_groups is None
        or len(challenger_preds.get("labels", [])) == 0
        or len(incumbent_preds.get("labels", [])) == 0
    ):
        return None
    return paired_cluster_bootstrap_aucpr_gap_ci(
        challenger_preds["labels"],
        challenger_preds["probabilities"],
        challenger_groups,
        incumbent_preds["labels"],
        incumbent_preds["probabilities"],
        incumbent_groups,
        n_resamples=500,
        seed=_SPATIAL_BOOTSTRAP_SEED,
        alpha=0.10,
    )


def _spatially_qualified_production_winner(
    metrics: dict[str, dict[str, float]],
    *,
    preferred: str,
    candidates: list[str] | tuple[str, ...] = PRODUCTION_MODEL_NAMES,
    predictions_sink: dict | None = None,
) -> str:
    """Pick the best spatially-qualified model for production.

    First filter to candidates that clear the held-out county + beach persistence
    gates (AUCPR + Brier beat persistence, spatial calibration plausible) — serving
    probabilities must generalize, not just win the temporal split. Among the
    *passing* set, pick the best by held-out SPATIAL AUCPR (county first — the most
    honest generalization signal; beach holdout carries per-beach self-persistence
    and a high base rate — then beach, then lower spatial Brier).

    Ranking on the SPATIAL metric (not the temporal-valid AUCPR the earlier version
    used) is the point: the gate FILTERS on spatial generalization, so it must also
    SELECT on it. The prior temporal-AUCPR key meant a challenger that generalized
    materially better to unseen counties/beaches was rejected unless it also beat
    the incumbent on the in-distribution temporal split — so spatial improvements
    could never drive a swap. Hysteresis (`_WINNER_SWAP_MARGIN`) is likewise on the
    held-out county AUCPR, so the daily retrain doesn't churn on backtest noise.

    This replaces an earlier veto that returned the incumbent whenever it merely
    *passed* — which kept a passing-but-inferior model in production even when a
    sibling was decisively better (the 1095d ensemble case, 2026-06-08).
    """
    if not any(name.startswith("spatial_") for name in metrics):
        return preferred

    passing = [
        model_name
        for model_name in candidates
        if _promotion_assessment(metrics, model_name)["public_release_eligible"]
    ]
    if not passing:
        return preferred

    def _county_aucpr(model_name: str) -> float:
        return float(metrics.get(f"spatial_county_{model_name}", {}).get("aucpr") or 0.0)

    def _key(model_name: str) -> tuple[float, float, float]:
        county = metrics.get(f"spatial_county_{model_name}", {})
        beach = metrics.get(f"spatial_beach_{model_name}", {})
        beach_aucpr = float(beach.get("aucpr") or 0.0)
        spatial_brier = float(county.get("brier", 1.0)) + float(beach.get("brier", 1.0))
        # Maximize county AUCPR, then beach AUCPR, then minimize spatial Brier.
        return (-_county_aucpr(model_name), -beach_aucpr, spatial_brier)

    best = min(passing, key=_key)
    # Noise-aware hysteresis: a challenger displaces a passing incumbent only when
    # the county-AUCPR improvement survives both a point-estimate floor AND a
    # paired cluster bootstrap. The pooled spatial AUCPR over 6 county folds has a
    # cluster-bootstrap 95% half-width ~0.136 — ~14x the 0.01 floor — so the floor
    # alone would churn the production winner on backtest noise.
    if preferred in passing and best != preferred:
        gap = _county_aucpr(best) - _county_aucpr(preferred)
        # (a) Point-estimate floor: never act on a sub-noise-floor gap.
        if gap <= _WINNER_SWAP_MARGIN:
            return preferred
        # (b) Paired cluster bootstrap of the gap (challenger - incumbent): swap
        # only when its 90% lower bound clears 0. Without per-row predictions we
        # cannot run it, so fall back to a conservative large-gap rule.
        gap_ci = _paired_county_aucpr_gap_ci(best, preferred, predictions_sink)
        if gap_ci is None:
            if gap <= _WINNER_SWAP_LARGE_GAP_MARGIN:
                return preferred
        elif not (gap_ci[0] > 0.0):
            return preferred
    return best


def _promotion_assessment(
    metrics: dict[str, dict[str, float]],
    winner: str,
) -> dict[str, object]:
    spatial_metrics = {name: value for name, value in metrics.items() if name.startswith("spatial_")}
    blockers: list[str] = []

    # Gate: production test metrics must be populated.
    base_key = _metrics_base_key(winner)
    prod_metrics = metrics.get(base_key) or {}
    if not prod_metrics or not prod_metrics.get("aucpr"):
        blockers.append(
            f"Production test metrics are missing or empty for metrics key '{base_key}'. "
            "Check that _metrics_base_key() maps the winner correctly."
        )

    if not spatial_metrics:
        blockers.append("Spatial holdout metrics have not been run for this artifact.")
    else:
        if f"spatial_county_{winner}" not in metrics:
            blockers.append(f"Held-out county metrics are missing for {winner}.")
        if f"spatial_beach_{winner}" not in metrics:
            blockers.append(f"Held-out beach metrics are missing for {winner}.")
        county_model = metrics.get(f"spatial_county_{winner}", {})
        county_persistence = metrics.get("spatial_county_persistence", {})
        beach_model_present = metrics.get(f"spatial_beach_{winner}", {})
        # Fail-CLOSED on zero-fold / empty backtests. _spatial_holdout_metrics
        # ALWAYS sets the spatial_{county,beach}_{winner} key, but when no fold
        # was usable (too few rows per group at the trimmed CI limits, or
        # single-class inner splits) it returns {"folds": 0.0, ...} with NO
        # aucpr/brier/calibration_slope. The persistence comparisons below are
        # all `is not None`-guarded, so without this gate every comparison is
        # silently skipped and an UNVALIDATED model passes by default. A model
        # with zero real spatial validation must never be publicly releasable.
        for scope, scope_metrics in (
            ("county", county_model),
            ("beach", beach_model_present),
        ):
            if not scope_metrics:
                continue  # absence already blocked above
            folds = scope_metrics.get("folds")
            if scope_metrics.get("aucpr") is None or (folds is not None and folds < 1):
                blockers.append(
                    f"Held-out {scope} backtest produced no usable folds "
                    f"(folds={folds!r}); the model has no spatial validation."
                )
        if county_model and county_persistence:
            model_aucpr = county_model.get("aucpr")
            baseline_aucpr = county_persistence.get("aucpr")
            if model_aucpr is not None and baseline_aucpr is not None and model_aucpr <= baseline_aucpr:
                blockers.append("Held-out county AUCPR does not beat persistence.")
            model_brier = county_model.get("brier")
            baseline_brier = county_persistence.get("brier")
            if model_brier is not None and baseline_brier is not None and model_brier >= baseline_brier:
                blockers.append("Held-out county Brier score does not beat persistence.")
            # Gate: spatial calibration slope must be plausibly calibrated.
            county_slope = county_model.get("calibration_slope")
            if county_slope is not None and county_slope < 0.4:
                blockers.append(
                    f"Spatial county calibration slope {county_slope:.3f} is below 0.4. "
                    "Probabilities are not trustworthy on held-out counties."
                )
        beach_model = metrics.get(f"spatial_beach_{winner}", {})
        beach_persistence = metrics.get("spatial_beach_persistence", {})
        if beach_model and beach_persistence:
            model_aucpr = beach_model.get("aucpr")
            baseline_aucpr = beach_persistence.get("aucpr")
            if model_aucpr is not None and baseline_aucpr is not None and model_aucpr <= baseline_aucpr:
                blockers.append("Held-out beach AUCPR does not beat persistence.")
            model_brier = beach_model.get("brier")
            baseline_brier = beach_persistence.get("brier")
            if model_brier is not None and baseline_brier is not None and model_brier >= baseline_brier:
                blockers.append("Held-out beach Brier score does not beat persistence.")
            # Gate: spatial calibration slope must be plausibly calibrated.
            # Symmetric to the county-slope gate above; same 0.4 threshold —
            # held-out-beach probabilities are no more trustworthy than
            # held-out-county ones when the calibration slope is degenerate.
            beach_slope = beach_model.get("calibration_slope")
            if beach_slope is not None and beach_slope < 0.4:
                blockers.append(
                    f"Spatial beach calibration slope {beach_slope:.3f} is below 0.4. "
                    "Probabilities are not trustworthy on held-out beaches."
                )

    return {
        "public_release_eligible": not blockers,
        "deployment_stage": "candidate_ready" if not blockers else "research_prototype",
        "promotion_blockers": blockers,
        "spatial_metrics": spatial_metrics,
    }


def _latest_numeric(history: pd.DataFrame, column: str) -> float | None:
    if column not in history.columns:
        return None
    valid = pd.to_numeric(history[column], errors="coerce").dropna()
    if valid.empty:
        return None
    return float(valid.iloc[-1])


def _registry_model_version(model_name: str) -> str:
    return f"{model_name.replace('_', '-')}-curated-v0"


def _model_key_from_registry_version(model_version: object) -> str:
    model_key = str(model_version or "")
    suffix = "-curated-v0"
    if model_key.endswith(suffix):
        model_key = model_key[: -len(suffix)]
    return model_key.replace("-", "_")


_WINNER_TO_METRICS_KEY: dict[str, str] = {
    # All hist_gbm variants share the underlying HistGBM classifier — the
    # differences are post-processing applied at inference. Temporal test
    # metrics are computed once on the base classifier and shared.
    "hist_gbm_positive_persistence_guard": "hist_gbm",
    "hist_gbm_persistence_blend": "hist_gbm",
}


def _metrics_base_key(model_name: str) -> str:
    """Return the metrics-dict key that stores training/test results for model_name.

    Some model variants (e.g., the persistence guard) wrap a base model at
    inference time but share its training path and therefore its metrics key.
    """
    return _WINNER_TO_METRICS_KEY.get(model_name, model_name)


def _forecast_model_version(model_name: str, scope: str = "global") -> str:
    if model_name == "logistic_hierarchical":
        return f"logistic-{scope}-curated-v0"
    return _registry_model_version(model_name)


_HOLDOUT_TEMPORAL_ARTIFACT = "holdout_predictions_temporal.parquet"
_HOLDOUT_SPATIAL_ARTIFACT = "holdout_predictions_spatial.parquet"
_SEARCY_TARGET_SPECIFICITY = 0.87
_SENSITIVITY_AT_SPEC_KEY = f"sensitivity_at_spec_{_SEARCY_TARGET_SPECIFICITY:.2f}"


def _persist_holdout_artifacts(
    curated_dir: Path,
    *,
    winner: str,
    metrics: dict,
    temporal_labels: np.ndarray | None = None,
    temporal_probs: np.ndarray | None = None,
    temporal_dates: np.ndarray | None = None,
    temporal_beach_ids: np.ndarray | None = None,
    temporal_lags: np.ndarray | None = None,
    predictions_sink: dict | None = None,
) -> None:
    """Persist held-out (label, probability) pairs and record sensitivity@spec.

    Closes the metrics-honesty gap: ``training.py`` previously concatenated the
    held-out arrays only to feed ``classification_metrics`` and then discarded
    them, so the Searcy et al. 2018 ``sensitivity @ specificity 0.87`` benchmark
    could not be recomputed without a retrain. This writes:

      * ``holdout_predictions_temporal.parquet`` — the production winner's
        temporal-test (label, probability[, date]) rows.
      * ``holdout_predictions_spatial.parquet`` — the production winner's pooled
        leave-one-out (label, probability, group) rows for county and beach
        holdouts.

    and records the sensitivity@spec operating point under the winner's metrics
    base key (``production_metrics`` in the registry) plus the spatial keys, so
    the number ships in ``system_health.json``. Every step is best-effort:
    a missing/empty array logs and is skipped, never crashing the build.
    """
    base_key = _metrics_base_key(winner)

    # --- Temporal-test pairs (the production / temporal-test eval slice) ---
    if temporal_labels is not None and temporal_probs is not None and len(temporal_labels):
        written = persist_holdout_predictions(
            curated_dir / _HOLDOUT_TEMPORAL_ARTIFACT,
            temporal_labels,
            temporal_probs,
            model=winner,
            date=temporal_dates,
            beach_id=temporal_beach_ids,
            lag=temporal_lags,
        )
        if written is None:
            print(
                "WARN: temporal holdout predictions not persisted (empty/unwritable)",
                file=sys.stderr,
                flush=True,
            )
        record = sensitivity_at_specificity_record(
            temporal_labels, temporal_probs, _SEARCY_TARGET_SPECIFICITY
        )
        metrics.setdefault(base_key, {})[_SENSITIVITY_AT_SPEC_KEY] = record

    # --- Spatial pooled pairs (leave-one-county-out / leave-one-beach-out) ---
    if predictions_sink:
        # Record the sensitivity@spec operating point for the WINNER only — it is
        # the production-shipped number consumers read from system_health.json.
        for group_column in ("county", "beach_id"):
            pooled = predictions_sink.get((winner, group_column))
            if pooled is None or len(pooled.get("labels", [])) == 0:
                continue
            # Spatial backtest metric keys use the FULL model name (variants
            # included); fall back to the base key for hist_gbm-family aliasing.
            prefix = "spatial_county_" if group_column == "county" else "spatial_beach_"
            spatial_key = next(
                (f"{prefix}{name}" for name in (winner, base_key) if f"{prefix}{name}" in metrics),
                None,
            )
            if spatial_key is not None:
                metrics[spatial_key][_SENSITIVITY_AT_SPEC_KEY] = (
                    sensitivity_at_specificity_record(
                        pooled["labels"], pooled["probabilities"], _SEARCY_TARGET_SPECIFICITY
                    )
                )

        # Persist per-row holdout pairs for EVERY backtested candidate (tagged by
        # `model`), not just the winner, so model gaps can be paired-tested offline
        # without a retrain. The winner's rows are still present (it is one of the
        # sink keys), so existing winner-only consumers keep working by filtering
        # `model == winner`. Sink keys are (model_name, group_column) tuples.
        spatial_frames: list[pd.DataFrame] = []
        for sink_key, pooled in predictions_sink.items():
            if not (isinstance(sink_key, tuple) and len(sink_key) == 2):
                continue
            model_name, group_column = sink_key
            if pooled is None or len(pooled.get("labels", [])) == 0:
                continue
            groups_arr = pooled.get("groups")
            spatial_frames.append(
                holdout_frame(
                    pooled["labels"],
                    pooled["probabilities"],
                    model=model_name,
                    holdout_kind=group_column,
                    group=groups_arr if groups_arr is not None and len(groups_arr) else None,
                )
            )
        if spatial_frames:
            try:
                combined = pd.concat(spatial_frames, ignore_index=True)
                (curated_dir / _HOLDOUT_SPATIAL_ARTIFACT).parent.mkdir(
                    parents=True, exist_ok=True
                )
                combined.to_parquet(curated_dir / _HOLDOUT_SPATIAL_ARTIFACT, index=False)
            except Exception:  # pragma: no cover - artifact write must not crash training
                print(
                    "WARN: spatial holdout predictions not persisted",
                    file=sys.stderr,
                    flush=True,
                )


def _record_within_beach_diagnostics(
    metrics: dict,
    *,
    winner: str,
    temporal_labels: np.ndarray | None = None,
    temporal_probs: np.ndarray | None = None,
    temporal_beach_ids: np.ndarray | None = None,
    temporal_lags: np.ndarray | None = None,
    predictions_sink: dict | None = None,
) -> None:
    """Record within-beach AUROC — the daily-skill metric global AUCPR is blind to.

    model_truth.md (2026-07-23) proved the shipped model's *served* within-beach
    AUROC is ~0.50: it ranks dirty beaches over clean ones (global AUROC ~0.82)
    but cannot tell a bad day from a normal day at the *same* beach. Global
    AUCPR/AUROC are dominated by between-beach variance and never surfaced this.
    This writes the number — temporal-test (same beaches, future dates) and
    leave-one-beach-out (a genuinely new beach) — plus its lag/staleness
    breakdown into ``metrics["two_tier_diagnostics"]`` so it ships in
    system_health.json. Best-effort: any failure logs nothing and is skipped,
    never crashing the build.
    """
    try:
        from app.ml.two_tier import within_beach_auroc, within_beach_auroc_by_lag
    except Exception:  # pragma: no cover - diagnostics must never break training
        return

    diagnostics: dict = {}
    if (
        temporal_labels is not None
        and temporal_probs is not None
        and temporal_beach_ids is not None
        and len(temporal_labels)
    ):
        try:
            auroc, n_beaches, n_rows = within_beach_auroc(
                temporal_labels, temporal_probs, temporal_beach_ids
            )
            block = {
                "within_beach_auroc": auroc,
                "n_beaches": float(n_beaches),
                "n_rows": float(n_rows),
            }
            if temporal_lags is not None:
                block["by_lag"] = within_beach_auroc_by_lag(
                    temporal_labels, temporal_probs, temporal_beach_ids, temporal_lags
                )
            diagnostics["temporal"] = block
        except Exception:  # pragma: no cover
            pass

    # Leave-one-beach-out: the pooled beach-holdout sink's `groups` ARE beach_ids,
    # so within-beach skill for an UNSEEN beach is computable per candidate. Record
    # EVERY backtested model so the two-tier offset challenger can be compared
    # head-to-head with the incumbent in system_health.json.
    if predictions_sink:
        base_key = _metrics_base_key(winner)
        by_model: dict = {}
        by_model_stale: dict = {}
        for sink_key, pooled in predictions_sink.items():
            if not (isinstance(sink_key, tuple) and len(sink_key) == 2):
                continue
            model_name, group_column = sink_key
            if group_column != "beach_id":
                continue
            if not (
                pooled
                and len(pooled.get("labels", []))
                and pooled.get("groups") is not None
                and len(pooled.get("groups", []))
            ):
                continue
            try:
                auroc, n_beaches, n_rows = within_beach_auroc(
                    pooled["labels"], pooled["probabilities"], pooled["groups"]
                )
                by_model[model_name] = {
                    "within_beach_auroc": auroc,
                    "n_beaches": float(n_beaches),
                    "n_rows": float(n_rows),
                }
            except Exception:  # pragma: no cover
                pass
            # Served-regime within-beach (anchor censored to serving age) — the
            # regime the two-tier offset model targets; the fresh number above is
            # blind to it (leave-one-out rows are fresh sample-days).
            stale = pooled.get("probabilities_stale")
            if stale is not None and len(stale) == len(pooled["labels"]):
                try:
                    s_auroc, s_beaches, s_rows = within_beach_auroc(
                        pooled["labels"], stale, pooled["groups"]
                    )
                    by_model_stale[model_name] = {
                        "within_beach_auroc": s_auroc,
                        "n_beaches": float(s_beaches),
                        "n_rows": float(s_rows),
                    }
                except Exception:  # pragma: no cover
                    pass
        if by_model:
            diagnostics["spatial_beach_by_model"] = by_model
            winner_block = by_model.get(winner) or by_model.get(base_key)
            if winner_block is not None:
                diagnostics["spatial_beach"] = winner_block
        if by_model_stale:
            diagnostics["spatial_beach_stale_by_model"] = by_model_stale
            winner_stale = by_model_stale.get(winner) or by_model_stale.get(base_key)
            if winner_stale is not None:
                diagnostics["spatial_beach_stale"] = winner_stale

    if diagnostics:
        metrics["two_tier_diagnostics"] = diagnostics


def _temporal_stale_offset_comparison(
    features: pd.DataFrame,
    labels: np.ndarray,
    metadata: pd.DataFrame,
    *,
    train_idx: np.ndarray,
    valid_idx: np.ndarray,
    eval_idx: np.ndarray,
    cutoff_days: int = _SERVING_STALE_CUTOFF_DAYS,
    min_samples: int = 15,
) -> dict:
    """Deployment-accurate CA comparison: incumbent vs two-tier offset on KNOWN
    beaches over FUTURE dates, in the FRESH and SERVED (anchor-censored) regimes.

    Unlike leave-one-beach-out, every eval beach is in training, so the offset
    holds its OWN historical baseline — the real deployment condition for a fixed
    CA beach set. Reports within-beach AUROC (the "which day" skill) plus AUCPR /
    Brier / mean-prediction (the "level correct + calibrated" skill, where keeping
    the per-beach level fresh — the offset's structural advantage over a stale
    lagged-geomean — actually shows). Both models are calibrated identically
    (isotonic on the valid slice) so Brier/bias are comparable.
    """
    from sklearn.metrics import average_precision_score

    from app.ml.two_tier import within_beach_auroc

    if "beach_id" not in metadata.columns:
        return {}
    beach = metadata["beach_id"].to_numpy()
    y = labels[eval_idx]
    b_eval = beach[eval_idx]
    eval_meta = metadata.iloc[eval_idx].reset_index(drop=True)
    valid_meta = metadata.iloc[valid_idx].reset_index(drop=True)
    x_eval = features.iloc[eval_idx]
    x_eval_stale = censor_bacteria_history_for_cutoff(x_eval, cutoff_days=cutoff_days)

    out: dict = {"actual_exceedance_rate": float(np.mean(y)) if len(y) else float("nan")}
    for name in ("xgb_undersample_ensemble", "xgb_undersample_offset"):
        classifier = _fit_classifier_for_name(features, name)
        _fit_classifier(
            classifier, features.iloc[train_idx], labels[train_idx], beach_ids=beach[train_idx]
        )
        valid_p = _predict_pos(classifier, features.iloc[valid_idx], beach_ids=beach[valid_idx])
        _, calibrator = _identity_or_calibrated(valid_p, labels[valid_idx], valid_meta)
        regimes: dict = {}
        for regime, frame in (("fresh", x_eval), ("stale", x_eval_stale)):
            p = _predict_pos(classifier, frame, beach_ids=b_eval)
            p = np.asarray(_apply_calibrator(calibrator, p, eval_meta), dtype=float)
            wb_auroc, wb_beaches, wb_rows = within_beach_auroc(y, p, b_eval, min_samples=min_samples)
            regimes[regime] = {
                "within_beach_auroc": wb_auroc,
                "aucpr": float(average_precision_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
                "brier": float(np.mean((p - y) ** 2)),
                "mean_pred": float(np.mean(p)),
                "n_beaches": float(wb_beaches),
                "n_rows": float(wb_rows),
            }
        out[name] = regimes
    return out


def _persist_and_diagnose_holdouts(
    curated_dir: Path,
    *,
    winner: str,
    metrics: dict,
    temporal_probs: np.ndarray | None,
    labels: np.ndarray,
    eval_idx: np.ndarray,
    eval_metadata: pd.DataFrame,
    features: pd.DataFrame,
    predictions_sink: dict | None,
) -> None:
    """Persist holdout artifacts (now carrying beach_id + lag) and record the
    within-beach diagnostics. Shared by the winner-only and full training paths so
    the two never drift. beach_id + the staleness feature (days-since-sample) are
    threaded onto the temporal holdout rows so within-beach skill is computable on
    disk without a retrain (previously the artifacts carried neither)."""
    temporal_labels = labels[eval_idx] if temporal_probs is not None else None
    temporal_dates = None
    temporal_beach_ids = None
    temporal_lags = None
    if temporal_probs is not None:
        if "sample_date" in eval_metadata.columns:
            temporal_dates = (
                pd.to_datetime(eval_metadata["sample_date"], errors="coerce")
                .dt.strftime("%Y-%m-%d")
                .to_numpy()
            )
        if "beach_id" in eval_metadata.columns:
            temporal_beach_ids = eval_metadata["beach_id"].to_numpy()
        if _STALE_RECENCY_COL in features.columns:
            try:
                temporal_lags = pd.to_numeric(
                    features.iloc[eval_idx][_STALE_RECENCY_COL], errors="coerce"
                ).to_numpy()
            except Exception:  # pragma: no cover - lag is best-effort
                temporal_lags = None
    _persist_holdout_artifacts(
        curated_dir,
        winner=winner,
        metrics=metrics,
        temporal_labels=temporal_labels,
        temporal_probs=temporal_probs,
        temporal_dates=temporal_dates,
        temporal_beach_ids=temporal_beach_ids,
        temporal_lags=temporal_lags,
        predictions_sink=predictions_sink,
    )
    _record_within_beach_diagnostics(
        metrics,
        winner=winner,
        temporal_labels=temporal_labels,
        temporal_probs=temporal_probs,
        temporal_beach_ids=temporal_beach_ids,
        temporal_lags=temporal_lags,
        predictions_sink=predictions_sink,
    )


_STALE_CUTOFF_DAYS: int = 45


def _apply_stale_censoring(features: pd.DataFrame) -> pd.DataFrame:
    """Zero bacteria-history features on rows whose sample age exceeds the stale threshold.

    Trains the model on the same censored view it sees at serve-time for stale
    beaches, so the serve-time stale-prior router and the training distribution
    are consistent. Non-stale rows are unchanged.
    """
    if _STALE_RECENCY_COL not in features.columns:
        return features
    stale_mask = features[_STALE_RECENCY_COL] >= _STALE_CUTOFF_DAYS
    if not stale_mask.any():
        return features
    features = features.copy()
    censored_rows = censor_bacteria_history_for_cutoff(
        features.loc[stale_mask], cutoff_days=_STALE_CUTOFF_DAYS
    )
    features.loc[stale_mask, censored_rows.columns] = censored_rows
    return features


def _write_model_card(curated_dir: Path, health_payload: dict) -> None:
    """Write a model card that cannot drift from system_health.json."""
    model_registry = health_payload.get("model_registry") or {}
    production_model = model_registry.get("production_model", "unknown")
    deployment_stage = model_registry.get("deployment_stage", "unknown")
    public_release_eligible = bool(model_registry.get("public_release_eligible", False))
    blockers = model_registry.get("promotion_blockers") or []
    blocker_line = str(blockers[-1]) if blockers else "None"

    prod = model_registry.get("production_metrics") or {}
    valid = model_registry.get("validation_metrics") or {}
    spatial = model_registry.get("spatial_metrics") or {}
    all_metrics = model_registry.get("metrics") or {}
    production_model_key = _model_key_from_registry_version(production_model)
    active_only = all_metrics.get(f"{_metrics_base_key(production_model_key)}_test_active_only") or {}
    county_spatial = spatial.get(f"spatial_county_{production_model_key}") or {}

    def _fmt(x: object) -> str:
        try:
            if x is None:
                return "—"
            return f"{float(x):.3f}"
        except (TypeError, ValueError):
            return "—"

    audit = health_payload.get("forecast_audit") or {}
    agreement = audit.get("agreement_rate")
    acute_agreement = audit.get("acute_agreement_rate")
    chronic_agreement = audit.get("chronic_agreement_rate")
    stale_agreement = audit.get("stale_agreement_rate")
    acute_advised = audit.get("acute_advised_beaches")

    content = "\n".join(
        [
            f"# Model Card: Shorelife `{production_model}`",
            "",
            "## Deployment Status",
            f"- **Generated at**: {health_payload.get('pipeline_freshness', 'unknown')}",
            f"- **Deployment stage**: {deployment_stage}",
            f"- **Public release eligible**: {str(public_release_eligible).lower()}",
            f"- **Promotion blocker (latest)**: {blocker_line}",
            "",
            "## Headline Metrics (from `system_health.json`)",
            "",
            "### Temporal (held-out time slice)",
            f"- **AUCPR**: {_fmt(prod.get('aucpr'))}",
            f"- **Brier**: {_fmt(prod.get('brier'))}",
            f"- **Log loss**: {_fmt(prod.get('log_loss'))}",
            f"- **Calibration slope**: {_fmt(prod.get('calibration_slope'))}",
            "",
            "### Deployment (active stations only; recency-filtered roster)",
            f"- **AUCPR**: {_fmt(active_only.get('aucpr'))}",
            f"- **Brier**: {_fmt(active_only.get('brier'))}",
            f"- **n_samples**: {int(active_only.get('n_samples') or 0)}",
            "",
            "### Validation (calibration/training-time slice; not a public headline)",
            f"- **AUCPR**: {_fmt(valid.get('aucpr'))}",
            f"- **Brier**: {_fmt(valid.get('brier'))}",
            "",
            "### Spatial (holdouts)",
            f"- **Spatial county AUCPR**: {_fmt(county_spatial.get('aucpr'))}",
            f"- **Spatial county persistence AUCPR**: {_fmt((spatial.get('spatial_county_persistence') or {}).get('aucpr'))}",
            "",
            "## Operational Agreement Check",
            "Active advisories are decomposed into three pools by age. The overall "
            "agreement rate below is dominated by the stale pool (administrative "
            "postings the model is not designed to flag), so per-pool numbers are "
            "the honest model-quality signal.",
            "",
            f"- **Acute** (started ≤14 d, real outbreaks): {acute_advised or 0} advised → agreement {_fmt(acute_agreement)}",
            f"- **Chronic** (15-365 d, geomean postings): agreement {_fmt(chronic_agreement)}",
            f"- **Stale** (>365 d, admin zombies the model is not expected to flag): agreement {_fmt(stale_agreement)}",
            "",
            f"- **Active-advisory agreement rate** (legacy overall metric, dominated by stale pool): {_fmt(agreement)}",
            "",
            "## Notes",
            "- Forecasts are decision support and are not official lab results.",
            "- Active official advisories override displayed risk in consumer surfaces.",
            "",
        ]
    )
    (Path(curated_dir) / "model_card.md").write_text(content)


def _inject_agent_features(
    features: pd.DataFrame,
    meta: pd.DataFrame,
    source_df: pd.DataFrame,
    advisories: pd.DataFrame,
    stations: pd.DataFrame,
) -> pd.DataFrame:
    """Run all accepted agent-discovered feature builders and join their output
    into the feature matrix.  Silently skips any builder that fails so a buggy
    persisted feature can't break the whole training run.

    ``meta`` must be aligned (by integer position) with ``features`` and contain
    'beach_id' and 'sample_date' columns.
    """
    try:
        from app.ml.feature_agent.agent_features import AGENT_BUILDERS
    except ImportError:
        return features

    if not AGENT_BUILDERS:
        return features

    result = features.copy()
    for builder in AGENT_BUILDERS:
        try:
            agent_df = builder(beach_day_df=source_df, advisories_df=advisories, stations_df=stations)
            new_cols = [c for c in agent_df.columns if c not in ("beach_id", "sample_date")]
            if not new_cols:
                continue
            feat_col = new_cols[0]
            merged = meta[["beach_id", "sample_date"]].merge(
                agent_df[["beach_id", "sample_date", feat_col]],
                on=["beach_id", "sample_date"],
                how="left",
            )
            result[feat_col] = merged[feat_col].fillna(0.0).to_numpy()
        except Exception as exc:
            import sys
            print(f"[agent] {getattr(builder, '__name__', repr(builder))} failed: {exc}", file=sys.stderr)
    return result


def _refresh_candidate_advisory_features(
    candidates: pd.DataFrame,
    advisories: pd.DataFrame,
    forecast_date: date,
) -> None:
    """Recompute advisory activity features for synthetic forecast rows.

    The candidates were cloned from the most-recent historical row per beach.
    That row's advisory features reflect the state on the observation date, not
    on the forecast date — so we recompute them here from current advisory state.
    """
    adv = advisories[["beach_id", "started_at", "ended_at", "cause"]].copy()
    adv["started_at"] = pd.to_datetime(adv["started_at"])
    adv["ended_at_ts"] = pd.to_datetime(adv["ended_at"])
    # One open-ended-advisory rule, shared with beachwatch._advisory_temporal_features
    # (which builds the same feature into the training labels frame). The old code
    # here special-cased "started within the last 14d -> fill 2099"; capping every
    # open-ended row at started_at + 14d is equivalent for the as-of-forecast_date
    # test below (a row started after forecast_ts - 14d caps to a date at or beyond
    # forecast_ts, so it still reads active) and, unlike the 2099 sentinel, is
    # correct per-row when swept across history.
    forecast_ts = pd.Timestamp(forecast_date)
    window_start = forecast_ts - pd.Timedelta(days=ADVISORY_OPEN_ENDED_MAX_DAYS)
    adv["ended_at_filled"] = fill_open_ended_advisory_end(
        adv["started_at"], adv["ended_at_ts"]
    )

    active_adv = adv[
        (adv["started_at"] < forecast_ts) & (adv["ended_at_filled"] > window_start)
    ].copy()
    active_ids = set(active_adv["beach_id"].tolist())
    candidates["advisory_active_prev_14d"] = candidates["beach_id"].isin(active_ids).astype(int)

    # Recent advisories: started within 365 days OR Tijuana River (genuinely chronic).
    # Used to gate the Moderate floor — stale bookkeeping advisories don't trigger it.
    cutoff_365 = forecast_ts - pd.Timedelta(days=365)
    is_recent = (active_adv["started_at"] >= cutoff_365) | (
        active_adv["cause"].str.contains("Tijuana River", case=False, na=False)
    )
    recent_ids = set(active_adv.loc[is_recent, "beach_id"].tolist())
    candidates["advisory_recent_active"] = candidates["beach_id"].isin(recent_ids).astype(int)

    # ended_at_FILLED, not ended_at_ts: reading the raw column meant `.isna()`
    # treated a never-closed advisory as active FOREVER — the 2099-sentinel bug in a
    # third guise, and the one that floored Dillon Beach to High off a Posting from
    # 2026-07-13 and Malibu Lagoon off one from 2026-03-02. Genuinely chronic
    # sources keep the exemption they already had in the clause below, so capping
    # open-ended rows here cannot drop the Tijuana River closure.
    is_chronic = active_adv["cause"].str.contains("Tijuana River", case=False, na=False)
    is_currently_active = is_chronic | (active_adv["ended_at_filled"] >= forecast_ts)
    is_recent_active_floor = is_currently_active & (
        (active_adv["started_at"] >= cutoff_365) | (active_adv["cause"].str.contains("Tijuana River", case=False, na=False))
    )
    floor_ids = set(active_adv.loc[is_recent_active_floor, "beach_id"].tolist())
    candidates["advisory_active_recent_for_floor"] = candidates["beach_id"].isin(floor_ids).astype(int)

    closed = adv[adv["ended_at_ts"].notna()].copy()
    closed["_days"] = (forecast_ts - closed["ended_at_ts"]).dt.days
    closed = closed[closed["_days"] >= 0]
    if not closed.empty:
        min_days = closed.groupby("beach_id")["_days"].min()
        candidates["days_since_advisory_closed"] = candidates["beach_id"].map(min_days)
    elif "days_since_advisory_closed" not in candidates.columns:
        candidates["days_since_advisory_closed"] = np.nan


# Base precip columns that the curation pipeline refreshes daily through the
# forecast date in precip_daily.parquet and that the model consumes. We overwrite
# whichever of these are present in BOTH the candidate frame and precip_daily.
# (precip_mm_96h/192h and the *_prior columns are not in the curated training
# allowlist today, so they simply don't intersect; listed for forward-compat.)
_REFRESHABLE_PRECIP_COLUMNS: tuple[str, ...] = (
    "precip_mm_1h",
    "precip_mm_6h",
    "precip_mm_24h",
    "precip_mm_48h",
    "precip_mm_72h",
    "precip_mm_7d",
    "precip_mm_96h",
    "precip_mm_192h",
    "precip_awi",
    "first_flush_flag",
    "first_rain_score",
    "precip_72h_prior",
    "precip_168h_prior",
)

# Streamflow base columns carried through the forecast date in
# streamflow_daily.parquet and consumed by the model (the lag kernel that derives
# from them is recomputed downstream in features._distributed_lag_hydrology_features).
_REFRESHABLE_STREAMFLOW_COLUMNS: tuple[str, ...] = (
    "streamflow_cfs_latest",
    "streamflow_cfs_mean_6h",
    "streamflow_cfs_mean_24h",
    "streamflow_cfs_max_24h",
    "streamflow_cfs_mean_72h",
    "streamflow_rising_flag",
)


def _read_optional_parquet(path: Path) -> pd.DataFrame:
    """Read a curated parquet, returning an empty frame if absent/unreadable.

    Forecast-time hydrology refresh is best-effort: a missing artifact must leave
    the candidate precip/streamflow features frozen rather than crash the build.
    """
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:  # pragma: no cover - defensive: a corrupt cache must not crash training
        print(f"[forecast-precip] WARN: could not read {path.name}; features left frozen.", file=sys.stderr, flush=True)
        return pd.DataFrame()


def _candidate_nearest_precip_station(
    candidates: pd.DataFrame,
    precip_daily: pd.DataFrame,
    hydrologic_links: pd.DataFrame | None,
) -> dict[str, str]:
    """Map each candidate beach_id to its nearest precip grid station_id.

    Reuses the SAME rule the curation pipeline applied to build the historical
    precip features in beach_day (``app.data.pipeline.hydrology.
    build_beach_hydrology_daily``): nearest precip station to the beach's
    hydrologic pour point by haversine distance. Beaches with no pour-point link
    fall back to their own display lat/lon, which rounds to the same 0.1° precip
    grid cell — so a forecast row can still be refreshed rather than left stale.
    """
    from app.data.pipeline.external_covariates import haversine_km

    if precip_daily.empty or "station_id" not in precip_daily.columns:
        return {}
    station_coords = (
        precip_daily[["station_id", "latitude", "longitude"]]
        .dropna(subset=["latitude", "longitude"])
        .drop_duplicates("station_id")
    )
    if station_coords.empty:
        return {}

    coords_by_beach: dict[str, tuple[float, float]] = {}
    if (
        hydrologic_links is not None
        and not hydrologic_links.empty
        and {"beach_id", "pour_point_latitude", "pour_point_longitude"}.issubset(hydrologic_links.columns)
    ):
        pour = (
            hydrologic_links[["beach_id", "pour_point_latitude", "pour_point_longitude"]]
            .dropna(subset=["pour_point_latitude", "pour_point_longitude"])
            .drop_duplicates("beach_id")
        )
        for _, row in pour.iterrows():
            coords_by_beach[str(row["beach_id"])] = (
                float(row["pour_point_latitude"]),
                float(row["pour_point_longitude"]),
            )
    if {"beach_id", "latitude", "longitude"}.issubset(candidates.columns):
        for _, row in candidates[["beach_id", "latitude", "longitude"]].drop_duplicates("beach_id").iterrows():
            bid = str(row["beach_id"])
            if bid in coords_by_beach:
                continue
            if pd.notna(row["latitude"]) and pd.notna(row["longitude"]):
                coords_by_beach[bid] = (float(row["latitude"]), float(row["longitude"]))

    st_ids = station_coords["station_id"].astype(str).to_numpy()
    st_lat = station_coords["latitude"].to_numpy(dtype=float)
    st_lon = station_coords["longitude"].to_numpy(dtype=float)
    mapping: dict[str, str] = {}
    for bid, (blat, blon) in coords_by_beach.items():
        best_d = float("inf")
        best_station: str | None = None
        for sid, slat, slon in zip(st_ids, st_lat, st_lon, strict=False):
            d = haversine_km(blat, blon, float(slat), float(slon))
            if d < best_d:
                best_d = d
                best_station = str(sid)
        if best_station is not None:
            mapping[bid] = best_station
    return mapping


def _refresh_candidate_precip_features(
    candidates: pd.DataFrame,
    precip_daily: pd.DataFrame,
    hydrologic_links: pd.DataFrame | None,
    forecast_date: date,
) -> None:
    """Refresh precip-derived features on each forecast candidate to forecast-date values.

    Forecast candidates are cloned from the beach's most-recent LAB sample row,
    whose precip columns are the rainfall windows AS OF that sample day — 12-37
    days stale by forecast time. ``precip_daily.parquet`` already carries the live
    rainfall windows for the forecast date keyed by precip grid station, so here we
    (1) join each candidate to its station via the same beach->station rule the
    curation pipeline used, (2) overwrite every base precip column present in both
    frames, and (3) recompute the rain-policy flags from the refreshed
    ``precip_mm_72h`` via the canonical ``add_rain_policy_features``. The distributed
    rain-lag kernel and the SD-boundary ``*_rain_interaction`` features are NOT
    touched here: they are recomputed downstream from the refreshed bases inside
    ``features.add_temporal_features``. Beaches/dates with no matching precip_daily
    row keep their frozen value (env-persistence); the count is logged once. Mutates
    ``candidates`` in place, matching ``_refresh_candidate_advisory_features``.
    """
    if candidates.empty or precip_daily is None or precip_daily.empty:
        return
    if "station_id" not in precip_daily.columns or "sample_date" not in precip_daily.columns:
        return
    forecast_ts = pd.Timestamp(forecast_date).normalize()
    pr = precip_daily.copy()
    pr["sample_date"] = pd.to_datetime(pr["sample_date"], errors="coerce")
    pr_fc = pr.loc[pr["sample_date"].dt.normalize() == forecast_ts].copy()
    if pr_fc.empty:
        print(
            f"[forecast-precip] no precip_daily rows for forecast date {forecast_date}; "
            f"left precip features frozen for all {len(candidates)} candidates.",
            file=sys.stderr,
            flush=True,
        )
        return
    pr_fc["station_id"] = pr_fc["station_id"].astype(str)
    pr_fc = pr_fc.drop_duplicates("station_id", keep="last").set_index("station_id")

    station_map = _candidate_nearest_precip_station(candidates, precip_daily, hydrologic_links)
    refresh_cols = [
        column
        for column in _REFRESHABLE_PRECIP_COLUMNS
        if column in candidates.columns and column in pr_fc.columns
    ]
    if not refresh_cols:
        return

    missing = 0
    refreshed = 0
    for idx in candidates.index:
        bid = str(candidates.at[idx, "beach_id"])
        station_id = station_map.get(bid)
        if station_id is None or station_id not in pr_fc.index:
            missing += 1
            continue
        prow = pr_fc.loc[station_id]
        for column in refresh_cols:
            value = prow.get(column)
            if pd.notna(value):
                candidates.at[idx, column] = value
        refreshed += 1

    # Recompute the regulatory rain-policy flags from the refreshed precip_mm_72h
    # using the canonical definition so the served forecast and the training-time
    # feature share ONE formula (no drift).
    if "precip_mm_72h" in candidates.columns:
        from app.data.pipeline.stormwater import add_rain_policy_features

        recomputed = add_rain_policy_features(candidates)
        for column in (
            "rain_72h_inches",
            "rain_72h_monitoring_pause_flag",
            "rain_72h_general_advisory_flag",
        ):
            if column in candidates.columns and column in recomputed.columns:
                candidates[column] = recomputed[column].to_numpy()

    if missing:
        print(
            f"[forecast-precip] refreshed precip features for {refreshed} candidate(s); "
            f"{missing} had no precip_daily row for {forecast_date} (kept frozen).",
            file=sys.stderr,
            flush=True,
        )


def _refresh_candidate_streamflow_features(
    candidates: pd.DataFrame,
    streamflow_daily: pd.DataFrame,
    hydrologic_links: pd.DataFrame | None,
    forecast_date: date,
) -> None:
    """Refresh streamflow_* features on each candidate to forecast-date values.

    ``streamflow_daily.parquet`` carries discharge windows through the forecast
    date keyed by USGS gage id. The curation pipeline joins it to beaches via the
    precomputed ``nearest_stream_gage_id`` link in ``hydrologic_beach_links``
    (``build_beach_hydrology_daily``); we reuse that exact link rather than a new
    spatial match. Base columns are overwritten; the streamflow lag kernel derived
    from them is recomputed downstream in ``add_temporal_features``. No-match rows
    keep their frozen value. Mutates ``candidates`` in place.
    """
    if candidates.empty or streamflow_daily is None or streamflow_daily.empty:
        return
    if "gage_id" not in streamflow_daily.columns or "sample_date" not in streamflow_daily.columns:
        return
    if (
        hydrologic_links is None
        or hydrologic_links.empty
        or not {"beach_id", "nearest_stream_gage_id"}.issubset(hydrologic_links.columns)
    ):
        return
    forecast_ts = pd.Timestamp(forecast_date).normalize()
    sf = streamflow_daily.copy()
    sf["sample_date"] = pd.to_datetime(sf["sample_date"], errors="coerce")
    sf_fc = sf.loc[sf["sample_date"].dt.normalize() == forecast_ts].copy()
    if sf_fc.empty:
        return
    sf_fc["gage_id"] = sf_fc["gage_id"].astype(str)
    sf_fc = sf_fc.drop_duplicates("gage_id", keep="last").set_index("gage_id")

    gage_map = {
        str(row["beach_id"]): str(row["nearest_stream_gage_id"])
        for _, row in hydrologic_links[["beach_id", "nearest_stream_gage_id"]]
        .dropna(subset=["nearest_stream_gage_id"])
        .drop_duplicates("beach_id")
        .iterrows()
    }
    refresh_cols = [
        column
        for column in _REFRESHABLE_STREAMFLOW_COLUMNS
        if column in candidates.columns and column in sf_fc.columns
    ]
    if not refresh_cols:
        return

    for idx in candidates.index:
        bid = str(candidates.at[idx, "beach_id"])
        gage_id = gage_map.get(bid)
        if gage_id is None or gage_id not in sf_fc.index:
            continue
        srow = sf_fc.loc[gage_id]
        for column in refresh_cols:
            value = srow.get(column)
            if pd.notna(value):
                candidates.at[idx, column] = value


def _build_forecast_candidates(
    frame: pd.DataFrame,
    stations: pd.DataFrame,
    uv_daily: pd.DataFrame,
    forecast_date: date,
    *,
    full_frame: pd.DataFrame | None = None,
    advisories: pd.DataFrame | None = None,
    min_sample_recency_days: int | None = None,
    precip_daily: pd.DataFrame | None = None,
    streamflow_daily: pd.DataFrame | None = None,
    hydrologic_links: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build one synthetic forecast row per beach.

    ``frame`` is the recent training window (typically 60 days).  When a
    covariate is missing from that window (e.g. because the upstream ingest
    dropped the column for a period), we fall back to the most-recent non-null
    value from ``full_frame`` — the complete unfiltered history.  This gives
    us env-persistence rather than all-null inputs, which keeps the calibrated
    probability meaningful even when the ingest pipeline has schema drift.

    ``min_sample_recency_days``, when set, drops any beach whose most-recent
    sample is older than that many days before ``forecast_date``. California
    beach monitoring funding has been cut multiple times since 2020 and many
    stations have gone silent. Publishing a forecast for a station that has
    not been sampled in months is misleading — the environmental covariates
    are stale, the model has no recent label signal, and downstream agreement
    metrics are inflated by these zombie stations. Use ``min_sample_recency_days=20``
    to mirror California's typical AB411 weekly monitoring cadence (one missed
    week is normal; three+ missed weeks is "the funding stopped").
    """
    history = frame.copy()
    history["sample_date"] = pd.to_datetime(history["sample_date"], errors="coerce")
    history["sample_time"] = pd.to_datetime(history["sample_time"], errors="coerce")
    history = history.loc[history["sample_date"].dt.date < forecast_date].copy()
    if history.empty:
        return history, pd.DataFrame()
    recency_cutoff = (
        pd.Timestamp(forecast_date) - pd.Timedelta(days=min_sample_recency_days)
        if min_sample_recency_days is not None
        else None
    )

    # Build a per-beach lookup from the full history for covariate fallback.
    full_history_by_beach: dict[str, pd.DataFrame] = {}
    if full_frame is not None and not full_frame.empty:
        full_copy = full_frame.copy()
        full_copy["sample_date"] = pd.to_datetime(full_copy["sample_date"], errors="coerce")
        full_copy["sample_time"] = pd.to_datetime(full_copy["sample_time"], errors="coerce")
        full_copy = full_copy.loc[full_copy["sample_date"].dt.date < forecast_date].copy()
        for beach_id, grp in full_copy.groupby("beach_id", sort=False):
            full_history_by_beach[str(beach_id)] = grp.sort_values("sample_time")

    station_lookup = stations.set_index("beach_id") if not stations.empty else pd.DataFrame()
    uv_lookup = _build_uv_lookup(uv_daily, forecast_date)
    candidate_rows: list[dict[str, object]] = []
    forecast_timestamp = datetime(
        forecast_date.year, forecast_date.month, forecast_date.day, 5, 0, tzinfo=UTC
    )
    covariate_columns = (
        "wave_height_m",
        "dominant_period_s",
        "water_temperature_c",
        "salinity_psu",
        "uv_index",
        "wind_speed_mps",
        "tidal_height",
        "surf_height_observed",
        "turbidity_observed",
    )

    for beach_id, beach_history in history.groupby("beach_id", sort=False):
        beach_history = beach_history.sort_values("sample_time")
        if len(beach_history) < 3:
            continue
        latest_row = beach_history.iloc[-1]
        if recency_cutoff is not None:
            latest_sample_date = pd.to_datetime(latest_row.get("sample_date"), errors="coerce")
            if pd.isna(latest_sample_date) or latest_sample_date < recency_cutoff:
                continue
        candidate = {column: latest_row.get(column) for column in history.columns}
        candidate["beach_id"] = beach_id
        latest_sample_date = pd.to_datetime(latest_row.get("sample_date"), errors="coerce")
        sample_age_days = (
            int((pd.Timestamp(forecast_date).normalize() - latest_sample_date.normalize()).days)
            if pd.notna(latest_sample_date)
            else None
        )
        if sample_age_days is not None:
            sample_age_days = max(0, sample_age_days)
        candidate["latest_sample_date"] = (
            latest_sample_date.date().isoformat() if pd.notna(latest_sample_date) else None
        )
        candidate["sample_age_days"] = sample_age_days
        candidate["sample_recency_band"] = sample_recency_band(sample_age_days)
        candidate["sample_date"] = pd.Timestamp(forecast_date)
        candidate["sample_time"] = pd.Timestamp(forecast_timestamp)
        candidate["enterococcus_value"] = np.nan
        candidate["exceeds_stv"] = np.nan
        for column in covariate_columns:
            # Primary: use the windowed beach history (recent 60 days).
            val = _latest_numeric(beach_history, column)
            # Fallback: if the recent window has no data for this covariate,
            # pull the most-recent non-null value from the full history so we
            # use env-persistence rather than feeding the model a null.
            if val is None and str(beach_id) in full_history_by_beach:
                val = _latest_numeric(full_history_by_beach[str(beach_id)], column)
            candidate[column] = val
        if not station_lookup.empty and beach_id in station_lookup.index and not uv_lookup.empty:
            zip_code = station_lookup.loc[beach_id].get("zip_code")
            if pd.notna(zip_code):
                zip_key = str(zip_code).zfill(5)
                if zip_key in uv_lookup.index:
                    candidate["uv_index"] = _safe_float(uv_lookup.loc[zip_key].get("uv_index"))
        candidate_rows.append(candidate)

    candidates = pd.DataFrame(candidate_rows)
    if not candidates.empty:
        # Refresh the rain/streamflow features (frozen at the stale sample-day
        # values when the candidate was cloned) to the forecast date BEFORE the
        # advisory refresh — the SD-boundary advisory interactions downstream read
        # the refreshed precip windows.
        _refresh_candidate_precip_features(candidates, precip_daily, hydrologic_links, forecast_date)
        _refresh_candidate_streamflow_features(candidates, streamflow_daily, hydrologic_links, forecast_date)
    if advisories is not None and not advisories.empty and not candidates.empty:
        _refresh_candidate_advisory_features(candidates, advisories, forecast_date)
    return history, candidates


def _predict_sequence_inference(
    artifacts: SequenceTrainingArtifacts,
    inference_dataset,
) -> tuple[np.ndarray, np.ndarray]:
    if artifacts.model is None or inference_dataset.feature_frame.empty:
        return np.array([], dtype=float), np.array([], dtype=float)
    static_features = (
        inference_dataset.feature_frame.select_dtypes(include=["number"])
        .fillna(0.0)
        .reindex(columns=artifacts.static_feature_columns, fill_value=0.0)
    )
    site_indices = (
        inference_dataset.metadata["beach_id"].map(artifacts.site_lookup).fillna(0).to_numpy(dtype=np.int64)
    )
    inference_sequence_dataset = SequenceDataset(
        sequences=inference_dataset.sequence_array,
        static_features=static_features.to_numpy(dtype=np.float32),
        site_indices=site_indices,
        exceed_targets=np.zeros(len(static_features), dtype=np.float32),
        density_targets=np.zeros(len(static_features), dtype=np.float32),
    )
    device = next(artifacts.model.parameters()).device
    probabilities, density_predictions = _predict_sequence_subset(
        artifacts.model,
        inference_sequence_dataset,
        np.arange(len(static_features)),
        device,
    )
    probabilities = _apply_calibrator(
        artifacts.calibrator,
        probabilities,
        inference_dataset.metadata.reset_index(drop=True),
    )
    return probabilities, density_predictions


_STV_THRESHOLD = 104.0  # CFU/100mL — CA marine single-sample action value

# Seasonal/cyclical encoding features are not actionable for end users and tend
# to dominate permutation importance when env data is missing.  Always exclude
# them from the driver computation so they can never surface as top-driver text.
_SEASONAL_FEATURE_PREFIXES: frozenset[str] = frozenset(
    (
        "day_of_year",
        "sin_doy",
        "cos_doy",
        "sin_week",
        "cos_week",
    )
)


def _compute_local_drivers(
    tree_classifier,
    features: pd.DataFrame,
    baseline_probs: np.ndarray,
) -> list[list[str]]:
    all_drivers = []
    if not hasattr(tree_classifier, "predict_proba"):
        return [["stable recent conditions with no strong environmental signal"]] * len(features)

    for i in range(len(features)):
        row = features.iloc[[i]]
        base_prob = baseline_probs[i]

        candidates = []
        cols_to_check = []
        for col in features.columns:
            # Never surface seasonal/cyclical features to end users — they are
            # not actionable and would expose raw internal names.
            if any(col == prefix or col.startswith(prefix + "_") for prefix in _SEASONAL_FEATURE_PREFIXES):
                continue
            val = float(row[col].iloc[0])
            if val != 0.0:
                cols_to_check.append((col, val))

        if cols_to_check:
            perturbed_df = pd.concat([row] * len(cols_to_check), ignore_index=True)
            for j, (col, _) in enumerate(cols_to_check):
                perturbed_df.at[j, col] = 0.0

            try:
                pert_probs = tree_classifier.predict_proba(perturbed_df)[:, 1]
                for j, (col, val) in enumerate(cols_to_check):
                    diff = base_prob - pert_probs[j]
                    if diff > 0.01:
                        candidates.append((diff, col, val))
            except Exception:
                pass

        candidates.sort(key=lambda x: x[0], reverse=True)

        driver_strings = []
        for diff, col, val in candidates[:3]:
            if col == "first_flush_flag":
                driver_strings.append("first-flush runoff after an extended dry spell")
            elif col == "streamflow_rising_flag":
                driver_strings.append("rising stream discharge near the beach")
            elif col == "precip_mm_24h":
                driver_strings.append(f"recent rainfall ({val:.0f} mm in 24 h)")
            elif col == "precip_awi":
                driver_strings.append(f"saturated watershed after sustained rain (AWI {val:.0f})")
            elif col == "precip_mm_7d":
                driver_strings.append(f"high 7-day cumulative rainfall ({val:.0f} mm)")
            elif col == "precip_runoff_lag_kernel_7d":
                driver_strings.append(f"distributed-lag runoff signal ({val:.1f} weighted mm)")
            elif col == "streamflow_cfs_latest":
                driver_strings.append(f"elevated stream discharge ({val:.0f} cfs)")
            elif col == "streamflow_lag_kernel_24h":
                driver_strings.append(f"distributed-lag streamflow signal ({val:.0f} cfs)")
            elif col == "wave_height_m" or col.startswith("wave_height_m_lag_"):
                driver_strings.append(f"elevated surf ({val:.1f} m)")
            elif col.startswith("wave_height_m_mean_"):
                driver_strings.append(f"persistently elevated swell ({val:.1f} m avg)")
            elif col.startswith("enterococcus_value_lag_"):
                driver_strings.append(f"elevated bacteria in recent sample ({val:.0f} CFU/100 mL)")
            elif col.startswith("turbidity_observed_lag_"):
                driver_strings.append("recent turbidity noted in field observations")
            elif col.startswith("salinity_psu_lag_") and val < 25:
                driver_strings.append(f"freshwater input detected (low salinity {val:.0f} psu)")
            elif col == "nearest_stormwater_outfall_km":
                driver_strings.append(f"mapped stormwater outfall nearby ({val:.1f} km)")
            elif col == "nearest_stormwater_asset_km":
                driver_strings.append(f"mapped stormwater infrastructure nearby ({val:.1f} km)")
            elif col == "nearest_tmdl_stormwater_site_km":
                driver_strings.append(f"TMDL/WQIP stormwater site nearby ({val:.1f} km)")
            elif col.startswith("stormwater_outfall_count_"):
                distance = col.removeprefix("stormwater_outfall_count_")
                driver_strings.append(f"multiple mapped stormwater outfalls within {distance}")
            elif col.startswith("stormwater_asset_count_"):
                distance = col.removeprefix("stormwater_asset_count_").replace("_", ".")
                driver_strings.append(f"dense mapped stormwater infrastructure within {distance}")
            elif col == "stormwater_tmdl_site_count_2km":
                driver_strings.append("mapped TMDL/WQIP stormwater sites within 2 km")
            elif col == "rain_72h_general_advisory_flag":
                driver_strings.append("72-hour rainfall exceeds the 0.2 inch advisory threshold")
            elif col == "rain_72h_monitoring_pause_flag":
                driver_strings.append("72-hour rainfall exceeds the 0.1 inch monitoring threshold")
            elif col == "rain_72h_inches":
                driver_strings.append(f"recent rainfall ({val:.2f} in over 72 h)")
            # else: feature has no human-readable mapping — skip it rather than
            # leaking internal names like "day of year (114.0)" to end users.

        if not driver_strings:
            driver_strings = ["stable recent conditions with no strong environmental signal"]

        all_drivers.append(driver_strings)

    return all_drivers


_PRODUCTION_MODEL_REGISTRY = "production_model.json"


def _read_production_model_registry(curated_dir: Path) -> dict | None:
    path = curated_dir / _PRODUCTION_MODEL_REGISTRY
    return json.loads(path.read_text()) if path.exists() else None


def _write_production_model_registry(
    curated_dir: Path,
    winner: str,
    regressor: str,
    ensemble_weights: list | None = None,
) -> None:
    data: dict[str, object] = {"winner": winner, "regressor": regressor}
    if ensemble_weights is not None:
        data["ensemble_weights"] = ensemble_weights
    write_json(curated_dir / _PRODUCTION_MODEL_REGISTRY, data)


def _publish_forecasts_unless_blocked(
    curated_dir: Path,
    forecasts: list[dict],
    *,
    release_blocked: bool,
    blockers: list[str] | None = None,
) -> bool:
    """Write forecasts.parquet unless the release gate blocked publication.

    Returns True when the fresh forecast was written, False when the write was
    skipped (the previous, last-validated forecasts.parquet is left on disk and
    keeps serving). The blockers are logged loudly so the run is auditable.
    """
    if release_blocked:
        loud = blockers or ["unspecified release blocker"]
        print(
            "RELEASE GATE BLOCKED publication: public_release_eligible=False — "
            "NOT overwriting forecasts.parquet (the last-validated forecast keeps "
            "serving). Blockers:",
            file=sys.stderr,
            flush=True,
        )
        for blocker in loud:
            print(f"  - {blocker}", file=sys.stderr, flush=True)
        return False
    pd.DataFrame(forecasts).to_parquet(curated_dir / "forecasts.parquet", index=False)
    return True


# Serve-time regime router cutoff: beaches whose last lab sample is this many days
# old or fresher keep the ensemble (it wins at low lag, where the anchor is live);
# staler beaches get the offset (it holds each beach's never-stale baseline and
# degrades gracefully). 3d matches the measured fresh/stale crossover; the served
# population is almost entirely staler (min age ~4d), so the offset serves most rows.
_FRESH_ROUTE_CUTOFF_DAYS: int = 3
# End of the fresh→stale blend ramp. Between the cutoff and here the served
# probability is a linear mix of ensemble→offset, so a beach crossing the boundary
# as its sample ages doesn't jump bands in a single day (the hard switch moved the
# probability ~0.07 mean / 0.19 p90). Short by design (days 3→5).
_ROUTE_BLEND_END_DAYS: int = 5


def _route_offset_weight(
    age: np.ndarray,
    fresh_cutoff_days: int = _FRESH_ROUTE_CUTOFF_DAYS,
    blend_end_days: int = _ROUTE_BLEND_END_DAYS,
) -> np.ndarray:
    """Offset blend weight from sample age: 0 (pure ensemble) at/below the fresh
    cutoff, ramping linearly to 1 (pure offset) by ``blend_end_days``. Unknown age
    (no prior sample) → 1, so the offset's per-beach level holds rather than the
    ensemble leaning on an absent fresh anchor."""
    age = np.asarray(age, dtype=float)
    span = max(blend_end_days - fresh_cutoff_days, 1)
    weight = np.clip((age - fresh_cutoff_days) / span, 0.0, 1.0)
    return np.where(np.isfinite(age), weight, 1.0)


def _route_fresh_stale_probabilities(
    ensemble_probabilities: np.ndarray,
    ensemble_lower: np.ndarray,
    ensemble_upper: np.ndarray,
    *,
    offset_classifier: object,
    offset_calibrator: object,
    features: pd.DataFrame,
    metadata: pd.DataFrame,
    fresh_cutoff_days: int = _FRESH_ROUTE_CUTOFF_DAYS,
    blend_end_days: int = _ROUTE_BLEND_END_DAYS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Two-tier serve-time router. Fresh beaches (last sample ≤ cutoff days) keep
    the ensemble; stale beaches get the offset; a short age-based ramp blends the
    two across the boundary so no beach jumps bands in a single day. Returns the
    routed (probability, lower, upper) arrays plus a diagnostic dict — the
    fresh/blended/stale split and the raw handoff delta (how far the two models
    disagree on the same rows, i.e. the un-blended jump the ramp smooths) — and the
    per-row blend weight, logged as ``served_offset_weight`` so served_metrics can
    attribute each prediction to the model that actually made it."""
    beach_ids = metadata["beach_id"].to_numpy() if "beach_id" in metadata.columns else None
    offset_raw = offset_classifier.predict_proba(features, beach_ids=beach_ids)[:, 1]
    offset_probs = np.asarray(_apply_calibrator(offset_calibrator, offset_raw, metadata), dtype=float)
    offset_lower, offset_upper = _calibration_interval(offset_calibrator, offset_raw, metadata)

    if _STALE_RECENCY_COL in features.columns:
        age = pd.to_numeric(features[_STALE_RECENCY_COL], errors="coerce").to_numpy()
    else:
        age = np.full(len(features), np.inf)
    w = _route_offset_weight(age, fresh_cutoff_days, blend_end_days)

    ensemble_probabilities = np.asarray(ensemble_probabilities, dtype=float)
    routed = (1.0 - w) * ensemble_probabilities + w * offset_probs
    routed_lower = (1.0 - w) * np.asarray(ensemble_lower, dtype=float) + w * np.asarray(offset_lower, dtype=float)
    routed_upper = (1.0 - w) * np.asarray(ensemble_upper, dtype=float) + w * np.asarray(offset_upper, dtype=float)

    delta = np.abs(ensemble_probabilities - offset_probs)
    diagnostics = {
        "fresh_beaches": int((w <= 0.0).sum()),
        "blended_beaches": int(((w > 0.0) & (w < 1.0)).sum()),
        "stale_beaches": int((w >= 1.0).sum()),
        "fresh_cutoff_days": int(fresh_cutoff_days),
        "blend_end_days": int(blend_end_days),
        "handoff_mean_abs_delta": float(np.nanmean(delta)) if len(delta) else float("nan"),
        "handoff_p90_abs_delta": float(np.nanpercentile(delta, 90)) if len(delta) else float("nan"),
    }
    return routed, routed_lower, routed_upper, diagnostics, w


def _export_forecasts(
    curated_dir: Path,
    forecast_date: date,
    frame: pd.DataFrame,
    full_frame: pd.DataFrame,
    features: pd.DataFrame,
    densities: np.ndarray,
    valid_idx: np.ndarray,
    test_idx: np.ndarray,
    stations: pd.DataFrame,
    uv_daily: pd.DataFrame,
    advisories: pd.DataFrame,
    models: _TrainedModels,
    plan: StageTwoTrainingPlan,
    metrics: dict,
    model_types_to_run: list,
    spatial_backtests: bool,
    spatial_backtest_models: list,
    spatial_strategy: str,
    *,
    min_sample_recency_days: int | None = None,
    enforce_release_gate: bool = False,
) -> "TrainingArtifacts":
    import sys
    winner = models.winner
    tree_classifier = models.tree_classifier
    tree_calibrator = models.tree_calibrator
    classifier = models.classifier
    calibrator = models.calibrator
    logistic = models.logistic
    logistic_calibrator = models.logistic_calibrator
    coastal_cell_logistic = models.coastal_cell_logistic
    hierarchical_logistic = models.hierarchical_logistic
    ensemble_weights = models.ensemble_weights
    regressor = models.regressor
    regression_interval_half_width = _split_conformal_half_width(
        densities[valid_idx], models.regressor_valid_predictions,
    )
    # Forecast-time hydrology refresh: precip_daily / streamflow_daily are
    # regenerated through the forecast date by the curation pipeline, but the
    # cloned candidate rows freeze the rain/streamflow windows at the (12-37 day
    # stale) sample day. Load them here so _build_forecast_candidates can overwrite
    # those columns with the live forecast-date values. Best-effort: a missing
    # artifact leaves the precip features frozen (current behavior).
    precip_daily = _read_optional_parquet(curated_dir / "precip_daily.parquet")
    streamflow_daily = _read_optional_parquet(curated_dir / "streamflow_daily.parquet")
    hydrologic_links = _read_optional_parquet(curated_dir / "hydrologic_beach_links.parquet")
    history, forecast_candidates = _build_forecast_candidates(
        frame,
        stations,
        uv_daily,
        forecast_date,
        full_frame=full_frame,
        advisories=advisories,
        min_sample_recency_days=min_sample_recency_days,
        precip_daily=precip_daily,
        streamflow_daily=streamflow_daily,
        hydrologic_links=hydrologic_links,
    )
    inference_input = (
        pd.concat([history, forecast_candidates], ignore_index=True)
        if not forecast_candidates.empty
        else pd.DataFrame()
    )
    baseline_inference = build_inference_features(inference_input) if not inference_input.empty else None
    baseline_feature_frame = (
        baseline_inference.feature_frame
        if baseline_inference is not None and not baseline_inference.feature_frame.empty
        else pd.DataFrame()
    )
    baseline_forecast_features = (
        baseline_feature_frame.select_dtypes(include=["number"]).fillna(0.0)
        if not baseline_feature_frame.empty
        else pd.DataFrame()
    )
    forecast_metadata = baseline_inference.metadata if baseline_inference is not None else pd.DataFrame()
    forecast_feature_frame = baseline_feature_frame
    baseline_forecast_features = baseline_forecast_features.reindex(columns=features.columns, fill_value=0.0)
    baseline_forecast_features = _inject_agent_features(
        baseline_forecast_features, forecast_metadata, inference_input, advisories, stations
    )
    forecast_group_metadata = forecast_metadata.merge(
        stations.reindex(
            columns=[
                "beach_id",
                "county",
                "region",
                "latitude",
                "longitude",
                "cdip_distance_km",
                "erddap_distance_km",
                "station_code",
            ]
        ),
        on="beach_id",
        how="left",
    ) if not forecast_metadata.empty else pd.DataFrame()
    scopes = np.full(len(baseline_forecast_features), "global", dtype=object)
    assigned_cells = np.full(len(baseline_forecast_features), "unknown", dtype=object)
    probability_lower = np.full(len(baseline_forecast_features), np.nan, dtype=float)
    probability_upper = np.full(len(baseline_forecast_features), np.nan, dtype=float)
    # Per-row two-tier provenance: 0 = the ensemble served this beach, 1 = the
    # offset model did, in between = the age ramp blended them. Stays None on
    # every non-routed path so `served_offset_weight` is null rather than a
    # misleading 0.0 when no router ran.
    route_offset_weights: np.ndarray | None = None
    if winner == "stacked_ensemble":
        _ens_logistic = logistic.predict_proba(baseline_forecast_features)[:, 1]
        if logistic_calibrator is not None:
            _ens_logistic = _apply_calibrator(logistic_calibrator, _ens_logistic, forecast_group_metadata)
        _ens_coastal, _, _ens_coastal_scopes = _predict_coastal_cell_logistic_raw(
            coastal_cell_logistic, baseline_forecast_features, forecast_group_metadata,
        )
        if coastal_cell_logistic.calibrator is not None:
            _ens_coastal = _apply_calibrator(
                coastal_cell_logistic.calibrator,
                _ens_coastal,
                forecast_group_metadata,
            )
        _ens_hier, _ens_hier_scopes = _predict_hierarchical_logistic_raw(
            hierarchical_logistic, baseline_forecast_features, forecast_group_metadata,
        )
        if hierarchical_logistic.calibrator is not None:
            _ens_hier = _apply_calibrator(
                hierarchical_logistic.calibrator,
                _ens_hier,
                forecast_group_metadata,
            )
        _ens_tree = tree_classifier.predict_proba(baseline_forecast_features)[:, 1]
        if tree_calibrator is not None:
            _ens_tree = _apply_calibrator(tree_calibrator, _ens_tree, forecast_group_metadata)
        probabilities = (
            np.stack([_ens_logistic, _ens_coastal, _ens_hier, _ens_tree], axis=1)
            @ ensemble_weights
        )
        scopes = _ens_hier_scopes
    elif winner == "logistic_coastal_cells":
        raw_probabilities, assigned_cells, scopes = _predict_coastal_cell_logistic_raw(
            coastal_cell_logistic, baseline_forecast_features, forecast_group_metadata,
        )
        probabilities = _apply_calibrator(
            coastal_cell_logistic.calibrator,
            raw_probabilities,
            forecast_group_metadata,
        )
        probability_lower, probability_upper = _calibration_interval(
            coastal_cell_logistic.calibrator,
            raw_probabilities,
            forecast_group_metadata,
        )
    elif winner == "logistic_hierarchical":
        raw_probabilities, scopes = _predict_hierarchical_logistic_raw(
            hierarchical_logistic, baseline_forecast_features, forecast_group_metadata,
        )
        probabilities = _apply_calibrator(
            hierarchical_logistic.calibrator,
            raw_probabilities,
            forecast_group_metadata,
        )
        probability_lower, probability_upper = _calibration_interval(
            hierarchical_logistic.calibrator,
            raw_probabilities,
            forecast_group_metadata,
        )
    elif winner == "hist_gbm_positive_persistence_guard":
        raw_probabilities = tree_classifier.predict_proba(baseline_forecast_features)[:, 1]
        calibrated_tree_probabilities = _apply_calibrator(
            tree_calibrator,
            raw_probabilities,
            forecast_group_metadata,
        )
        persistence_probabilities = _persistence_probabilities(
            baseline_forecast_features,
            _STV_THRESHOLD,
        )
        probabilities = _positive_persistence_guarded_blend_probabilities(
            calibrated_tree_probabilities,
            persistence_probabilities,
            PERSISTENCE_BLEND_MAX_MODEL_ALPHA,
        )
    else:
        raw_probabilities = classifier.predict_proba(baseline_forecast_features)[:, 1]
        probabilities = _apply_calibrator(calibrator, raw_probabilities, forecast_group_metadata)
        probability_lower, probability_upper = _calibration_interval(
            calibrator,
            raw_probabilities,
            forecast_group_metadata,
        )
        # Two-tier router: hand stale (between-sample) beaches to the offset model;
        # fresh beaches keep the ensemble. Only when the offset was trained this run
        # and the winner is the ensemble (this generic branch). Health/anomaly/
        # release gates downstream still guard the routed output.
        if (
            winner == "xgb_undersample_ensemble"
            and models.offset_classifier is not None
            and models.offset_calibrator is not None
            and not baseline_forecast_features.empty
        ):
            probabilities, probability_lower, probability_upper, _route_diag, route_offset_weights = (
                _route_fresh_stale_probabilities(
                    probabilities,
                    probability_lower,
                    probability_upper,
                    offset_classifier=models.offset_classifier,
                    offset_calibrator=models.offset_calibrator,
                    features=baseline_forecast_features,
                    metadata=forecast_group_metadata,
                )
            )
            metrics.setdefault("two_tier_diagnostics", {})["serving_router"] = _route_diag
            print(
                f"[two-tier router] {_route_diag['stale_beaches']} stale→offset, "
                f"{_route_diag['blended_beaches']} blended, "
                f"{_route_diag['fresh_beaches']} fresh→ensemble; raw handoff Δ mean "
                f"{_route_diag['handoff_mean_abs_delta']:.3f} "
                f"(p90 {_route_diag['handoff_p90_abs_delta']:.3f}), smoothed over "
                f"days {_route_diag['fresh_cutoff_days']}–{_route_diag['blend_end_days']}.",
                file=sys.stderr, flush=True,
            )

    # --- Runtime serving guards (apply to EVERY winner) ----------------------
    # The deployed xgb_undersample_ensemble (and most other branches) do NOT
    # apply the positive-persistence floor that the dedicated guard variant
    # does. At serve time we never want the model to underperform "yesterday
    # exceeded → today still elevated": where the last official observation
    # exceeded the STV, the served probability must not collapse to Low.
    probabilities = np.asarray(probabilities, dtype=float)
    persistence_probabilities = _persistence_probabilities(
        baseline_forecast_features,
        _STV_THRESHOLD,
    )
    # NaN/inf guard: a non-finite served probability is meaningless. Fall back
    # to the positive-persistence signal for that row when one exists, else a
    # safe Moderate-band default (0.20 = Low/Moderate cut), and warn loudly.
    nonfinite_mask = ~np.isfinite(probabilities)
    if nonfinite_mask.any():
        n_bad = int(nonfinite_mask.sum())
        fallback = np.where(persistence_probabilities >= 0.5, 1.0, _LOW_THRESHOLD)
        probabilities = np.where(nonfinite_mask, fallback, probabilities)
        print(
            f"[serving guard] WARNING: {n_bad} forecast probabilit"
            f"{'y' if n_bad == 1 else 'ies'} were NaN/inf; fell back to "
            "persistence/safe default.",
            file=sys.stderr, flush=True,
        )
    probabilities = np.clip(probabilities, 0.0, 1.0)
    # NOTE (2026-08-06): the serve path used to OVERRIDE the model here —
    # `_positive_persistence_guarded_blend_probabilities(..., alpha=1.0)`, i.e.
    # `where(persistence >= 0.5, 1.0, p)` — hard-pinning every beach whose last
    # official sample exceeded to 1.0 and discarding the model's own answer.
    # That is now a post-calibration FLOOR only (see below). The override was a
    # safety belt from a weaker model, and it had stopped protecting anything:
    #   * `exceeds_stv_last_obs` is ALREADY a model feature (features.py:412 —
    #     it is not in `_model_feature_columns`'s exclusion set), so the model
    #     had learned what a prior exceedance is worth *in context*. The pin
    #     replaced a learned, context-sensitive estimate with a constant.
    #   * Downstream, the serving isotonic squashed that constant back down,
    #     so every pinned beach landed on ONE plateau value regardless of its
    #     own risk — on the shipped 2026-08-05 forecast, 17 beaches with lab
    #     readings spanning 107..6628 all served exactly 0.45.
    # Measured A/B on the 1095d window, temporal test split (11,973 held-out
    # sample-days), one shared model, serving isotonic refit per arm:
    #   overall            Brier 0.0846 -> 0.0640, AUCPR 0.573 -> 0.791,
    #                      within-beach AUROC 0.616 -> 0.651
    #   pinned rows only   Brier 0.2330 -> 0.1171, AUROC 0.500 -> 0.910,
    #   (n=2119)           distinct served values 1 -> 43
    #                      (Brier gap 0.1159, cluster-bootstrap 95% CI over 285
    #                       beaches [0.0989, 0.1323])
    # The pinned arm scored WORSE than the flat base rate (0.2330 vs 0.2325):
    # it was not merely uninformative, it was a miscalibrated constant. Control
    # rows (persistence-negative) moved 0.05269 -> 0.05260, i.e. untouched.
    # The guard MODEL variant keeps the old semantics — it is a scored backtest
    # candidate whose definition must not shift under the promotion gate.

    # --- Serving-regime recalibration (model_truth.md audit, 2026-07-23) -----
    # The calibrators above are fit on sample-days (fresh risk history); the
    # served regime is between-sample days, where those probabilities ran hot
    # up top (served ~0.98 -> ~0.36 realized — largely the persistence floor
    # just above) and lost to a flat base rate on Brier. Refit daily: isotonic
    # map from what the product previously served (forecast_history.parquet)
    # to the lab outcomes that followed. Monotone, so rank order (the part
    # that held up forward, AUROC ~0.8) is untouched. Falls back to the
    # uncalibrated probabilities whenever served history is too thin.
    probabilities_precal = probabilities.copy()
    serving_calibration = None
    try:
        serving_calibration = fit_serving_calibration(curated_dir)
    except Exception as exc:  # noqa: BLE001 — accountability layer must never kill the run
        print(
            f"[serving calibration] WARNING: fit failed ({exc!r}); serving "
            "uncalibrated probabilities.",
            file=sys.stderr, flush=True,
        )
    if serving_calibration is not None:
        probabilities = apply_serving_calibration(probabilities, serving_calibration)
        # Same probability-scale map keeps the served interval bounds coherent.
        probability_lower = apply_serving_calibration(probability_lower, serving_calibration)
        probability_upper = apply_serving_calibration(probability_upper, serving_calibration)
        save_serving_calibration(curated_dir, serving_calibration)
        print(
            "[serving calibration] active: "
            f"{serving_calibration['n_pairs']} pairs / "
            f"{serving_calibration['n_positive']} positives over "
            f"{serving_calibration['window_days']}d, Brier "
            f"{serving_calibration['brier_before']:.4f} -> "
            f"{serving_calibration['brier_after']:.4f}.",
            file=sys.stderr, flush=True,
        )

    # Positive-persistence FLOOR — the safety property the old override was
    # really there for: a beach whose last official sample exceeded the STV is
    # never displayed Low. Applied AFTER recalibration (a floor set before the
    # isotonic would just be squashed by it), and applied UNCONDITIONALLY —
    # it used to live inside the `serving_calibration is not None` branch, so a
    # run with too little served history to fit a calibrator got no floor at
    # all. That was masked while the pre-calibration pin existed; with the pin
    # gone it would be a live hole, so the floor moves out here.
    # Unlike the pin, this only RAISES rows that fall below the cut: every
    # persistence-positive beach keeps its own model-driven probability above
    # `_LOW_THRESHOLD`, so they stay distinguishable from one another.
    persistence_floor_mask = persistence_probabilities >= 0.5
    # Recorded per row below. With the pin gone, `p_exceed_precal` is genuinely
    # the model's own pre-calibration probability (it used to be captured AFTER
    # the pin, so on pinned rows it was a constant 1.0 and the model's answer
    # was unrecoverable from any shipped artifact). This flag plus that column
    # makes the full chain model -> calibration -> floor -> advisory auditable.
    persistence_floor_applied_flags = persistence_floor_mask & (probabilities < _LOW_THRESHOLD)
    probabilities = np.where(
        persistence_floor_mask,
        np.maximum(probabilities, _LOW_THRESHOLD),
        probabilities,
    )

    density_predictions = regressor.predict(baseline_forecast_features)
    _VERY_HIGH_THRESHOLD = _CAL_VERY_HIGH
    _DEGENERATE_VERY_HIGH_FRACTION = 0.30
    if len(probabilities) > 0:
        very_high_fraction = float((probabilities >= _VERY_HIGH_THRESHOLD).mean())
        if very_high_fraction > _DEGENERATE_VERY_HIGH_FRACTION:
            print(
                f"[sanity guard] WARNING: {very_high_fraction:.1%} of beaches at Very High "
                f"(>{_DEGENERATE_VERY_HIGH_FRACTION:.0%} threshold). "
                "Possible degenerate calibrator — check env feature fill rates.",
                file=sys.stderr, flush=True,
            )
    if not baseline_forecast_features.empty and hasattr(tree_classifier, "predict_proba"):
        driver_baseline_probs = tree_classifier.predict_proba(baseline_forecast_features)[:, 1]
    else:
        driver_baseline_probs = probabilities
    computed_drivers = _compute_local_drivers(tree_classifier, baseline_forecast_features, driver_baseline_probs)
    forecasts = []
    forecast_lookup = (
        forecast_candidates.drop_duplicates(subset=["beach_id"], keep="last").set_index("beach_id")
        if not forecast_candidates.empty
        else pd.DataFrame()
    )
    uv_lookup = _build_uv_lookup(uv_daily, forecast_date)
    station_lookup = stations.set_index("beach_id")
    # Beaches the SERVE path considers posted. The feature column below
    # (advisory_active_recent_for_floor) answers a different question -- it gates on
    # "started within 365d OR Tijuana River" to keep stale bookkeeping advisories out
    # of a MODEL feature -- while display authority is filter_currently_active
    # ("closure, OR posted within 14d"). Those two legitimately disagree, and when
    # they do the parquet shipped a band the serve layer then floored, so
    # forecasts.parquet (and forecast_history, and the served_metrics computed from
    # it) disagreed with what users actually saw. Measured 2026-07-30: 5 posted
    # beaches carried Low/Moderate in the parquet while every read path served High.
    _display_active_advisory_ids: set[str] = set()
    try:
        from app.repositories.curated_repository import filter_currently_active

        if advisories is not None and not advisories.empty:
            _display_active_advisory_ids = set(
                filter_currently_active(advisories)["beach_id"].astype(str).tolist()
            )
    except Exception as exc:  # noqa: BLE001 - never let this sink a training run
        print(f"[forecast] display-advisory floor unavailable ({exc}); feature gate only",
              file=sys.stderr, flush=True)
    if not forecast_metadata.empty:
        forecast_generated_at = datetime.now(UTC).isoformat()
        for i, (idx, probability, density_prediction, scope) in enumerate(zip(
            forecast_metadata.index, probabilities, density_predictions, scopes, strict=False,
        )):
            meta_row = forecast_metadata.iloc[idx]
            feature_row = forecast_feature_frame.iloc[idx]
            beach_id = meta_row["beach_id"]
            latest_row = forecast_lookup.loc[beach_id] if beach_id in forecast_lookup.index else None
            station_row = station_lookup.loc[beach_id] if beach_id in station_lookup.index else None
            uv_index = _safe_float(latest_row.get("uv_index")) if latest_row is not None else None
            uv_alert = None
            if station_row is not None and not uv_lookup.empty:
                zip_code = station_row.get("zip_code")
                if pd.notna(zip_code):
                    zip_key = str(zip_code).zfill(5)
                    if zip_key in uv_lookup.index:
                        uv_index = _safe_float(uv_lookup.loc[zip_key].get("uv_index"))
                        uv_alert = uv_lookup.loc[zip_key].get("uv_alert")
            # Floor on EITHER signal: the model-feature gate, or the display gate the
            # serve path uses. Whichever fires, the written band matches what the API
            # and the web bake will render, so the artifact at rest, the served
            # response, and served_metrics all agree.
            advisory_floor_trigger = (
                (_safe_float(feature_row.get("advisory_active_recent_for_floor")) or 0.0)
                or (str(beach_id) in _display_active_advisory_ids)
            )
            p_raw = float(probability)
            served_p_exceed = max(p_raw, _HIGH_THRESHOLD) if advisory_floor_trigger else p_raw
            advisory_floor_applied = bool(advisory_floor_trigger and p_raw < _HIGH_THRESHOLD)
            p_lower = probability_lower[i] if i < len(probability_lower) else np.nan
            p_upper = probability_upper[i] if i < len(probability_upper) else np.nan
            p_lower_final = float(p_lower) if np.isfinite(p_lower) else None
            p_upper_final = max(float(p_upper), served_p_exceed) if np.isfinite(p_upper) else None
            sample_age_value = _safe_float(latest_row.get("sample_age_days")) if latest_row is not None else None
            sample_age_days = int(sample_age_value) if sample_age_value is not None else None
            row_recency_band = (
                str(latest_row.get("sample_recency_band")) if latest_row is not None else "unknown"
            )
            # False-alarm gate (does NOT touch the public band cutpoints): a
            # strong (High/Very High) MODEL band fired off a very-stale sample
            # with no active advisory is low-confidence — cap the *displayed*
            # band at Moderate. p_exceed/p_exceed_raw stay honest; an active
            # advisory always wins (advisory_floor_trigger).
            served_risk_band = confidence_capped_risk_band(
                served_p_exceed,
                sample_recency_band=row_recency_band,
                advisory_active=bool(advisory_floor_trigger),
            )
            forecasts.append({
                "beach_id": beach_id,
                "forecast_date": forecast_date.isoformat(),
                "risk_band": served_risk_band,
                "forecast_label_mode": "model",
                "sample_age_days": sample_age_days,
                "sample_recency_band": row_recency_band,
                "is_beta_forecast": True,
                "advisory_floor_applied": advisory_floor_applied,
                "persistence_floor_applied": bool(
                    persistence_floor_applied_flags[i]
                    if i < len(persistence_floor_applied_flags) else False
                ),
                "p_exceed": served_p_exceed,
                "p_exceed_raw": p_raw,
                "p_exceed_precal": float(probabilities_precal[i]),
                "p_exceed_lower": p_lower_final,
                "p_exceed_upper": p_upper_final,
                "predicted_log_enterococcus": float(density_prediction),
                "lower_prediction_interval": (
                    float(density_prediction - regression_interval_half_width)
                    if regression_interval_half_width is not None else None
                ),
                "upper_prediction_interval": (
                    float(density_prediction + regression_interval_half_width)
                    if regression_interval_half_width is not None else None
                ),
                "prediction_interval_level": (0.9 if regression_interval_half_width is not None else None),
                "top_drivers": computed_drivers[i],
                "model_version": _forecast_model_version(winner, str(scope)),
                # Which tier actually produced p_exceed. model_version records the
                # registry winner, which is the ensemble even on rows the offset
                # model served — without this the log cannot attribute a prediction.
                "served_offset_weight": (
                    float(route_offset_weights[i])
                    if route_offset_weights is not None and i < len(route_offset_weights)
                    else None
                ),
                "forecast_generated_at": forecast_generated_at,
                "wave_height_m": _safe_float(latest_row.get("wave_height_m")) if latest_row is not None else None,
                "dominant_period_s": _safe_float(latest_row.get("dominant_period_s")) if latest_row is not None else None,
                "water_temperature_c": _safe_float(latest_row.get("water_temperature_c")) if latest_row is not None else None,
                "salinity_psu": _safe_float(latest_row.get("salinity_psu")) if latest_row is not None else None,
                "uv_index": uv_index,
                "wind_speed_mps": _safe_float(latest_row.get("wind_speed_mps")) if latest_row is not None else None,
                "uv_alert": uv_alert,
            })

    # Release gate: when --enforce-release-gate is set and the promotion
    # assessment finds the model ineligible for public release, DO NOT overwrite
    # forecasts.parquet — the previous (last-validated) forecast keeps serving and
    # the serve-time staleness machinery + failure alerting take over. We still
    # write system_health.json below (with the blockers) so the gate is auditable
    # and the verify_release_gate.py CI step can fail the job loudly.
    promotion = _promotion_assessment(metrics, winner)
    release_blocked = enforce_release_gate and not promotion["public_release_eligible"]
    _publish_forecasts_unless_blocked(
        curated_dir,
        forecasts,
        release_blocked=release_blocked,
        blockers=promotion.get("promotion_blockers"),
    )

    # Append-only log of what is actually serving (the fresh forecast, or the
    # release-gate-frozen previous one — whose rows are already logged, so the
    # append de-dupes to a no-op). served_performance scores this log against
    # subsequent lab results: the audit's Test-4 loop, run daily.
    try:
        appended_rows = append_forecast_history(curated_dir)
        print(
            f"[served metrics] forecast history +{appended_rows} rows.",
            file=sys.stderr, flush=True,
        )
    except Exception as exc:  # noqa: BLE001 — accountability layer must never kill the run
        print(
            f"[served metrics] WARNING: history append failed ({exc!r}).",
            file=sys.stderr, flush=True,
        )

    # Write latest_env.parquet — tiny lookup for the API server so it never has to
    # load the full 446 MB beach_day.parquet at runtime (Render free-tier OOM fix).
    _ENV_COLS = ["wave_height_m", "dominant_period_s", "water_temperature_c",
                 "salinity_psu", "uv_index", "wind_speed_mps", "wind_direction_deg"]

    # Prefer forecast_candidates: one synthetic row per beach with the dynamically
    # joined uv_index and env-persistence fallbacks already applied. Fall back to
    # the latest row per beach in full_frame when no candidates were generated.
    if not forecast_candidates.empty:
        _latest_env_source = forecast_candidates.drop_duplicates(
            subset=["beach_id"], keep="last"
        )
        _env_present = [c for c in _ENV_COLS if c in _latest_env_source.columns]
        _latest_env = _latest_env_source[["beach_id"] + _env_present].copy()
        # Map 24h-window aggregates from the data pipeline → API field names.
        # Force-overwrite when the column either doesn't exist or is all-null,
        # since the forecast-candidate stage explicitly nulls these via
        # covariate_columns even when 24h-aggregated data is available.
        def _map(target: str, source: str) -> None:
            if source not in _latest_env_source.columns:
                return
            has_target = target in _latest_env.columns
            if not has_target or _latest_env[target].isna().all():
                _latest_env[target] = _latest_env_source[source].to_numpy()

        _map("wind_speed_mps", "wind_speed_24h_max")
        _map("uv_index", "uv_index_24h_max")
        _map("wind_direction_deg", "wind_direction_24h_mean")
    else:
        _env_present = [c for c in _ENV_COLS if c in full_frame.columns]
        _latest_env = (
            full_frame[["beach_id", "sample_date"] + _env_present]
            .sort_values("sample_date")
            .groupby("beach_id", as_index=False)
            .last()
            .drop(columns=["sample_date"])
        )

    for _col in _ENV_COLS:
        if _col not in _latest_env.columns:
            _latest_env[_col] = float("nan")
    _latest_env[["beach_id"] + _ENV_COLS].to_parquet(curated_dir / "latest_env.parquet", index=False)

    health_path = curated_dir / "system_health.json"
    health_payload = json.loads(health_path.read_text()) if health_path.exists() else {}
    # `promotion` was computed above for the release-gate decision; reuse it so the
    # gate verdict and the persisted system_health.json can never disagree.
    health_payload["model_registry"] = {
        "production_model": _registry_model_version(winner),
        "temporal_validation_winner": _registry_model_version(plan.research_winner),
        "candidate_models": [_registry_model_version(m) for m in PRODUCTION_MODEL_NAMES],
        "research_models": [_registry_model_version(m) for m in model_types_to_run],
        "spatial_backtest_models": [_registry_model_version(m) for m in spatial_backtest_models],
        "spatial_backtest_strategy": spatial_strategy if spatial_backtests else "disabled",
        "production_metrics": metrics.get(_metrics_base_key(winner), {}),
        "validation_metrics": (
            metrics.get(f"{_metrics_base_key(winner)}_valid_calibrated")
            or metrics.get(f"{_metrics_base_key(winner)}_valid")
            or {}
        ),
        "temporal_validation_metrics": (
            metrics.get(f"{_metrics_base_key(plan.research_winner)}_valid_calibrated")
            or metrics.get(f"{_metrics_base_key(plan.research_winner)}_valid")
            or {}
        ),
        "spatial_metrics": promotion["spatial_metrics"],
        "deployment_stage": promotion["deployment_stage"],
        "public_release_eligible": promotion["public_release_eligible"],
        "promotion_blockers": promotion["promotion_blockers"],
        "promotion_policy": {
            "production_models": list(PRODUCTION_MODEL_NAMES),
            "neural_model_status": "research_only",
            "spatial_backtests_present": bool(promotion["spatial_metrics"]),
            "spatial_backtest_strategy": spatial_strategy,
            "fallback_order": ["coastal_cell", "county", "region", "global"],
        },
        "metrics": metrics,
    }
    # Served-regime accountability (model_truth.md follow-up #1): the REAL
    # forecast-vs-outcome numbers for what shipped, next to the backtest
    # metrics above. Consumers should treat these as the deployment truth —
    # the backtest figures describe fresh sample-days the product never serves.
    try:
        served_metrics_payload = served_performance(curated_dir)
    except Exception as exc:  # noqa: BLE001 — accountability layer must never kill the run
        served_metrics_payload = None
        print(
            f"[served metrics] WARNING: scoring failed ({exc!r}).",
            file=sys.stderr, flush=True,
        )
    health_payload["served_metrics"] = served_metrics_payload or {
        "status": "insufficient_served_history"
    }
    health_payload["serving_calibration"] = (
        {"active": True, **{k: v for k, v in serving_calibration.items() if k not in ("x", "y")}}
        if serving_calibration is not None
        else {"active": False, "reason": "insufficient_served_history"}
    )
    # Record the release-gate verdict so the verify_release_gate.py CI step and
    # human auditors can see whether this run actually published a fresh forecast.
    health_payload["release_gate"] = {
        "enforced": bool(enforce_release_gate),
        "public_release_eligible": promotion["public_release_eligible"],
        "forecast_published": not release_blocked,
        "blockers": promotion["promotion_blockers"],
    }
    health_payload["pipeline_freshness"] = datetime.now(UTC).isoformat()
    # dumps_strict, not json.dumps: a NaN metric (e.g. an AUROC over a bucket
    # where no beach qualified) serialises as a bare `NaN` token, which is not
    # valid JSON and breaks every non-Python consumer — it failed the
    # shorelife-web static export outright on 2026-07-24.
    write_json(health_path, health_payload)
    _write_model_card(curated_dir, health_payload)
    return TrainingArtifacts(winner=winner, metrics=metrics)


def _train_offset_model(
    features: pd.DataFrame,
    labels: np.ndarray,
    metadata: pd.DataFrame,
    train_idx: np.ndarray,
    cal_idx: np.ndarray,
    cal_metadata: pd.DataFrame,
) -> tuple[object, object]:
    """Fit the two-tier offset model and its calibrator.

    The offset model holds each beach's never-stale historical baseline as an
    XGBoost ``base_margin``, so the serve-time router can hand it the stale
    (between-sample) beaches the plain ensemble collapses on — CA deployment
    eval: served AUCPR 0.38 -> 0.62, and the under-warning bias is fixed. See
    two_tier.py.

    Shared by BOTH training entrypoints on purpose. This block used to live only
    inside _run_winner_only, so ``train_curated_and_export`` — the
    ``full_comparison=true`` winner-re-selection path — passed no offset model to
    _export_forecasts, the router's ``offset_classifier is not None`` gate went
    false, and that run published plain-ensemble forecasts with the two-tier
    router silently off. Nothing caught it: the offset->ensemble mean shift is
    ~1.43x, well under validate_forecast's 4x anomaly trip.
    """
    print("Training XGB undersample offset model (two-tier)...", file=sys.stderr, flush=True)
    beach_all = metadata["beach_id"].to_numpy() if "beach_id" in metadata.columns else None
    classifier = XGBUndersampleOffsetEnsemble().fit(
        features.iloc[train_idx],
        labels[train_idx],
        beach_ids=beach_all[train_idx] if beach_all is not None else None,
    )
    cal_raw = _predict_pos(
        classifier,
        features.iloc[cal_idx],
        beach_ids=beach_all[cal_idx] if beach_all is not None else None,
    )
    _, calibrator = _identity_or_calibrated(cal_raw, labels[cal_idx], cal_metadata)
    return classifier, calibrator


def _run_winner_only(
    curated_dir: Path,
    forecast_date: date,
    training_window_days: int,
    spatial_strategy: str,
    spatial_backtests: bool,
    spatial_beach_limit: int | None,
    spatial_county_limit: int | None,
    spatial_jobs: int | None,
    registry: dict,
    *,
    min_sample_recency_days: int | None = None,
    active_only_training: bool = False,
    enforce_release_gate: bool = False,
) -> "TrainingArtifacts":
    import sys
    settings = get_settings()
    full_frame = _load_curated_training_frame(curated_dir)
    full_frame["sample_date"] = pd.to_datetime(full_frame["sample_date"])
    max_date = full_frame["sample_date"].max()
    frame = full_frame.loc[
        full_frame["sample_date"] > (max_date - pd.Timedelta(days=training_window_days))
    ].copy()
    stations = pd.read_parquet(curated_dir / "beaches.parquet")
    uv_daily_path = curated_dir / "uv_daily.parquet"
    uv_daily = pd.read_parquet(uv_daily_path) if uv_daily_path.exists() else pd.DataFrame()
    advisories_path = curated_dir / "advisories.parquet"
    advisories = pd.read_parquet(advisories_path) if advisories_path.exists() else pd.DataFrame()
    dataset = build_sliding_windows(frame)
    features = dataset.feature_frame.select_dtypes(include=["number"]).fillna(0.0)
    features = _inject_agent_features(features, dataset.metadata, full_frame, advisories, stations)
    features = _apply_stale_censoring(features)
    labels = dataset.targets_exceed
    densities = dataset.targets_log_density
    metadata = _metadata_with_groups(dataset.metadata, frame, stations=stations)
    if len(features) < 20:
        return TrainingArtifacts(winner="insufficient-data", metrics={"warning": {"samples": float(len(features))}})
    train_idx, valid_idx, test_idx = _blocked_indices(dataset.metadata)
    cal_idx, val_metric_idx = _calibration_split(valid_idx, metadata)
    eval_idx = test_idx if len(test_idx) else valid_idx
    baselines = make_baselines(features)
    metrics: dict[str, dict[str, float]] = {}

    winner = registry["winner"]
    regressor_type = registry.get("regressor", "elastic_net")
    print(f"Winner-only mode: retraining {winner} + {regressor_type}", file=sys.stderr, flush=True)
    print(
        f"Calibration holdout: cal={len(cal_idx)} fit / val_metric={len(val_metric_idx)} report",
        file=sys.stderr,
        flush=True,
    )

    # Active-station subset for the deployment-relevant test metric. This is the
    # population the user actually sees in the app — stations sampled within the
    # last N days. Reporting AUCPR/Brier on this subset answers the right question
    # ("how good is the model for the beaches we forecast?") rather than the wrong
    # question ("how good is it averaged across stations including ones whose env
    # covariates are months stale because the funding stopped").
    active_ids: set[str] = set()
    if min_sample_recency_days is not None:
        active_ids = _active_beach_ids(full_frame, forecast_date, min_sample_recency_days)
        print(
            f"Active stations (sampled within {min_sample_recency_days}d of {forecast_date}): "
            f"{len(active_ids)} beaches",
            file=sys.stderr,
            flush=True,
        )

    # A/B ablation hook: optionally restrict the training set to active stations
    # only. Validation and test slices are NOT filtered — both ablation arms
    # evaluate on the same held-out samples for a clean apples-to-apples
    # comparison. If active-only training improves the deployment metric, it
    # means zombie history was net-negative for global generalization on the
    # currently-active population. If it doesn't, more data wins.
    if active_only_training and active_ids:
        meta_beach_ids = metadata["beach_id"].astype(str).to_numpy()
        active_mask = np.isin(meta_beach_ids, list(active_ids))
        train_idx = train_idx[active_mask[train_idx]]
        print(
            f"Active-only training: train_idx filtered to {len(train_idx)} samples "
            f"from {len(active_ids)} active stations",
            file=sys.stderr,
            flush=True,
        )

    cal_metadata = metadata.iloc[cal_idx].reset_index(drop=True)
    val_metric_metadata = metadata.iloc[val_metric_idx].reset_index(drop=True)
    eval_metadata = metadata.iloc[eval_idx].reset_index(drop=True)

    def _record_valid_metrics(model_key: str, raw_probs_metric: np.ndarray, calibrator) -> None:
        """Report validation metrics on the held-out half (val_metric_idx).

        Always records the raw-probability metrics under {model}_valid for
        backward compatibility with the AUCPR-based selector. Also records a
        {model}_valid_calibrated record so downstream consumers can compare
        post-calibration Brier/log-loss honestly (the calibrator was fit on
        cal_idx, so val_metric_idx is genuinely out-of-sample for it).
        """
        metrics[f"{model_key}_valid"] = classification_metrics(
            labels[val_metric_idx], raw_probs_metric
        )
        if calibrator is not None and len(val_metric_idx) > 0:
            calibrated_probs = _apply_calibrator(
                calibrator, raw_probs_metric, val_metric_metadata
            )
            metrics[f"{model_key}_valid_calibrated"] = classification_metrics(
                labels[val_metric_idx], calibrated_probs
            )

    # hist_gbm is always trained — local drivers always use it
    print("Training hist GBM model...", file=sys.stderr, flush=True)
    tree_classifier = baselines.tree_classifier.fit(features.iloc[train_idx], labels[train_idx])
    tree_cal_raw = tree_classifier.predict_proba(features.iloc[cal_idx])[:, 1]
    tree_metric_raw = tree_classifier.predict_proba(features.iloc[val_metric_idx])[:, 1]
    _, tree_calibrator = _identity_or_calibrated(tree_cal_raw, labels[cal_idx], cal_metadata)
    _record_valid_metrics("hist_gbm", tree_metric_raw, tree_calibrator)
    tree_eval = tree_classifier.predict_proba(features.iloc[eval_idx])[:, 1]
    if len(test_idx):
        tree_eval = _apply_calibrator(tree_calibrator, tree_eval, eval_metadata)
    metrics["hist_gbm"] = classification_metrics(labels[eval_idx], tree_eval)
    if active_ids:
        active_subset = _classification_metrics_on_subset(
            labels[eval_idx], tree_eval, eval_metadata, active_ids,
        )
        if active_subset is not None:
            metrics["hist_gbm_test_active_only"] = active_subset
            metrics["hist_gbm_test_active_only"]["n_samples"] = float(
                eval_metadata["beach_id"].astype(str).isin(active_ids).sum()
            )
            metrics["hist_gbm_test_active_only"]["n_total_test"] = float(len(eval_idx))

    # xgb_undersample_ensemble is always trained so the spatial gate can swap it
    # in as the production winner without retraining. Leave-one-CA-county-out
    # validation selected it over hist_gbm (+0.069 AUCPR / 0.100 vs 0.114 Brier
    # on held-out counties); see scripts/spatial_compare.py + spatial_incumbent.py.
    print("Training XGB undersample ensemble model...", file=sys.stderr, flush=True)
    ensemble_classifier = XGBUndersampleEnsemble().fit(features.iloc[train_idx], labels[train_idx])
    ens_cal_raw = ensemble_classifier.predict_proba(features.iloc[cal_idx])[:, 1]
    ens_metric_raw = ensemble_classifier.predict_proba(features.iloc[val_metric_idx])[:, 1]
    _, ensemble_calibrator = _identity_or_calibrated(ens_cal_raw, labels[cal_idx], cal_metadata)
    _record_valid_metrics("xgb_undersample_ensemble", ens_metric_raw, ensemble_calibrator)

    offset_classifier, offset_calibrator = _train_offset_model(
        features, labels, metadata, train_idx, cal_idx, cal_metadata
    )
    _beach_all = metadata["beach_id"].to_numpy() if "beach_id" in metadata.columns else None
    _record_valid_metrics(
        "xgb_undersample_offset",
        _predict_pos(
            offset_classifier,
            features.iloc[val_metric_idx],
            beach_ids=_beach_all[val_metric_idx] if _beach_all is not None else None,
        ),
        offset_calibrator,
    )

    ens_eval = ensemble_classifier.predict_proba(features.iloc[eval_idx])[:, 1]
    if len(test_idx):
        ens_eval = _apply_calibrator(ensemble_calibrator, ens_eval, eval_metadata)
    metrics["xgb_undersample_ensemble"] = classification_metrics(labels[eval_idx], ens_eval)

    logistic = logistic_calibrator = None
    coastal_cell_logistic = hierarchical_logistic = None
    ensemble_weights: np.ndarray | None = None
    classifier = calibrator = None

    if winner == "logistic":
        print("Training global logistic model...", file=sys.stderr, flush=True)
        logistic = baselines.logistic.fit(features.iloc[train_idx], labels[train_idx])
        logistic_cal_raw = logistic.predict_proba(features.iloc[cal_idx])[:, 1]
        logistic_metric_raw = logistic.predict_proba(features.iloc[val_metric_idx])[:, 1]
        _, logistic_calibrator = _identity_or_calibrated(
            logistic_cal_raw, labels[cal_idx], cal_metadata
        )
        _record_valid_metrics("logistic", logistic_metric_raw, logistic_calibrator)
        logistic_eval = logistic.predict_proba(features.iloc[eval_idx])[:, 1]
        if len(test_idx):
            logistic_eval = _apply_calibrator(logistic_calibrator, logistic_eval, eval_metadata)
        metrics["logistic"] = classification_metrics(labels[eval_idx], logistic_eval)
        classifier, calibrator = logistic, logistic_calibrator

    elif winner == "logistic_coastal_cells":
        print("Training coastal cells logistic model...", file=sys.stderr, flush=True)
        coastal_cell_logistic = _fit_coastal_cell_logistic_artifacts(features, labels, metadata, train_idx)
        coastal_cal_raw, _, _ = _predict_coastal_cell_logistic_raw(
            coastal_cell_logistic, features.iloc[cal_idx], cal_metadata,
        )
        coastal_metric_raw, _, _ = _predict_coastal_cell_logistic_raw(
            coastal_cell_logistic, features.iloc[val_metric_idx], val_metric_metadata,
        )
        _, coastal_calibrator = _identity_or_calibrated(
            coastal_cal_raw, labels[cal_idx], cal_metadata
        )
        _record_valid_metrics("logistic_coastal_cells", coastal_metric_raw, coastal_calibrator)
        coastal_cell_logistic.calibrator = coastal_calibrator

    elif winner == "logistic_hierarchical":
        print("Training hierarchical logistic model...", file=sys.stderr, flush=True)
        hierarchical_logistic = _fit_hierarchical_logistic_artifacts(features, labels, metadata, train_idx)
        hier_cal_raw, _ = _predict_hierarchical_logistic_raw(
            hierarchical_logistic, features.iloc[cal_idx], cal_metadata,
        )
        hier_metric_raw, _ = _predict_hierarchical_logistic_raw(
            hierarchical_logistic, features.iloc[val_metric_idx], val_metric_metadata,
        )
        _, hierarchical_calibrator = _identity_or_calibrated(
            hier_cal_raw, labels[cal_idx], cal_metadata
        )
        _record_valid_metrics("logistic_hierarchical", hier_metric_raw, hierarchical_calibrator)
        hierarchical_logistic.calibrator = hierarchical_calibrator

    elif winner == "stacked_ensemble":
        print("Training all base classifiers for stacked ensemble...", file=sys.stderr, flush=True)
        logistic = baselines.logistic.fit(features.iloc[train_idx], labels[train_idx])
        logistic_cal_raw = logistic.predict_proba(features.iloc[cal_idx])[:, 1]
        logistic_metric_raw = logistic.predict_proba(features.iloc[val_metric_idx])[:, 1]
        _, logistic_calibrator = _identity_or_calibrated(
            logistic_cal_raw, labels[cal_idx], cal_metadata
        )
        _record_valid_metrics("logistic", logistic_metric_raw, logistic_calibrator)

        coastal_cell_logistic = _fit_coastal_cell_logistic_artifacts(features, labels, metadata, train_idx)
        coastal_cal_raw, _, _ = _predict_coastal_cell_logistic_raw(
            coastal_cell_logistic, features.iloc[cal_idx], cal_metadata,
        )
        coastal_metric_raw, _, _ = _predict_coastal_cell_logistic_raw(
            coastal_cell_logistic, features.iloc[val_metric_idx], val_metric_metadata,
        )
        _, coastal_calibrator = _identity_or_calibrated(
            coastal_cal_raw, labels[cal_idx], cal_metadata
        )
        _record_valid_metrics("logistic_coastal_cells", coastal_metric_raw, coastal_calibrator)
        coastal_cell_logistic.calibrator = coastal_calibrator

        hierarchical_logistic = _fit_hierarchical_logistic_artifacts(features, labels, metadata, train_idx)
        hier_cal_raw, _ = _predict_hierarchical_logistic_raw(
            hierarchical_logistic, features.iloc[cal_idx], cal_metadata,
        )
        hier_metric_raw, _ = _predict_hierarchical_logistic_raw(
            hierarchical_logistic, features.iloc[val_metric_idx], val_metric_metadata,
        )
        _, hierarchical_calibrator = _identity_or_calibrated(
            hier_cal_raw, labels[cal_idx], cal_metadata
        )
        _record_valid_metrics("logistic_hierarchical", hier_metric_raw, hierarchical_calibrator)
        hierarchical_logistic.calibrator = hierarchical_calibrator

        persisted_ew = registry.get("ensemble_weights")
        if persisted_ew is not None:
            ensemble_weights = np.array(persisted_ew)
        else:
            _aucs = np.array([
                metrics.get("logistic_valid", {}).get("aucpr", 0.0),
                metrics.get("logistic_coastal_cells_valid", {}).get("aucpr", 0.0),
                metrics.get("logistic_hierarchical_valid", {}).get("aucpr", 0.0),
                metrics.get("hist_gbm_valid", {}).get("aucpr", 0.0),
            ])
            _s = _aucs.sum()
            ensemble_weights = _aucs / _s if _s > 0 else np.full(4, 0.25)

    elif winner == "xgb_undersample_ensemble":
        classifier, calibrator = ensemble_classifier, ensemble_calibrator

    else:  # hist_gbm (default)
        classifier, calibrator = tree_classifier, tree_calibrator

    if regressor_type == "elastic_net":
        print("Training elastic net model...", file=sys.stderr, flush=True)
        baselines.linear.fit(features.iloc[train_idx], densities[train_idx])
        regressor = baselines.linear
        regressor_valid_predictions = baselines.linear.predict(features.iloc[valid_idx])
        metrics["elastic_net_valid"] = regression_metrics(densities[valid_idx], regressor_valid_predictions)
    else:
        print("Training hist GBM regressor model...", file=sys.stderr, flush=True)
        baselines.tree_regressor.fit(features.iloc[train_idx], densities[train_idx])
        regressor = baselines.tree_regressor
        regressor_valid_predictions = baselines.tree_regressor.predict(features.iloc[valid_idx])
        metrics["hist_gbm_regressor_valid"] = regression_metrics(densities[valid_idx], regressor_valid_predictions)

    # In shortlist mode, backtest the full hist_gbm family so the spatially-
    # qualified winner selection has alternatives to swap in if the current
    # winner fails the slope/AUCPR/Brier gates. Same trained classifier under
    # the hood; the variants differ only in post-processing.
    if spatial_strategy == "shortlist":
        # Always backtest the full hist_gbm family (plus the temporal winner) so
        # the spatially-qualified selection has robust alternatives to swap in —
        # even when the temporal winner is a non-hist_gbm model (e.g. logistic)
        # that overfits the temporal split but fails spatial generalization.
        backtest_models = list(dict.fromkeys([
            winner,
            "hist_gbm",
            "hist_gbm_positive_persistence_guard",
            "hist_gbm_persistence_blend",
            # The spatially-validated challenger — must be backtested so the gate
            # can swap it in over the temporal winner on held-out counties.
            "xgb_undersample_ensemble",
            # Two-tier level+deviation challenger (base_margin offset + staleness
            # augmentation) — backtested to compare its held-out within-beach skill
            # against the incumbent on the served regime.
            "xgb_undersample_offset",
        ]))
    else:
        backtest_models = [winner]

    plan = StageTwoTrainingPlan(
        production_winner=winner, research_winner=winner, spatial_backtest_models=backtest_models,
    )

    spatial_predictions_sink: dict = {}
    if spatial_backtests:
        print(
            f"Running stage 2 spatial backtests for {', '.join(m.upper() for m in backtest_models)}...",
            file=sys.stderr, flush=True,
        )

        effective_beach_limit = spatial_beach_limit
        effective_county_limit = spatial_county_limit
        if spatial_strategy == "quick":
            effective_beach_limit = spatial_beach_limit or 5
            effective_county_limit = spatial_county_limit or 3

        resolved_spatial_jobs = spatial_jobs or _default_spatial_jobs()
        metrics.update(
            _spatial_backtest_metrics(
                features,
                labels,
                metadata,
                stv_threshold=settings.epa_marine_enterococcus_stv,
                beach_group_limit=effective_beach_limit,
                county_group_limit=effective_county_limit,
                spatial_jobs=resolved_spatial_jobs,
                dataset=dataset,
                model_names_to_run=backtest_models,
                predictions_sink=spatial_predictions_sink,
            )
        )

    # Swap winner if the registry's choice fails spatial gates and an
    # alternative passes. Same classifier + calibrator under the hood for
    # hist_gbm variants, so we don't need to retrain.
    if spatial_backtests:
        new_winner = _spatially_qualified_production_winner(
            metrics,
            preferred=winner,
            candidates=tuple(backtest_models),
            predictions_sink=spatial_predictions_sink,
        )
        if new_winner != winner:
            print(
                f"Spatial gates: swapping production winner {winner} → {new_winner}",
                file=sys.stderr, flush=True,
            )
            winner = new_winner

    # Persist the FINAL winner's held-out (label, probability) pairs + record the
    # Searcy sensitivity@spec operating point. The temporal-test eval predictions
    # for the two always-trained candidates are captured above (tree_eval /
    # ens_eval); other winners fall back to spatial-only persistence.
    _winner_temporal_eval = {
        "hist_gbm": tree_eval,
        "xgb_undersample_ensemble": ens_eval,
    }.get(_metrics_base_key(winner))
    _persist_and_diagnose_holdouts(
        curated_dir,
        winner=winner,
        metrics=metrics,
        temporal_probs=_winner_temporal_eval,
        labels=labels,
        eval_idx=eval_idx,
        eval_metadata=eval_metadata,
        features=features,
        predictions_sink=spatial_predictions_sink,
    )

    # Deployment-accurate CA comparison (known beaches, future dates, fresh + served
    # regimes) where the offset holds each beach's real baseline. Gated to spatial
    # runs so fast dev retrains skip the extra offset fit; guarded so it can never
    # break the build. Lands in system_health.json two_tier_diagnostics.
    if spatial_backtests:
        try:
            metrics.setdefault("two_tier_diagnostics", {})["temporal_ca_by_model"] = (
                _temporal_stale_offset_comparison(
                    features,
                    labels,
                    metadata,
                    train_idx=train_idx,
                    valid_idx=valid_idx,
                    eval_idx=eval_idx,
                )
            )
        except Exception as _ca_exc:  # pragma: no cover - diagnostic must not crash
            print(
                f"WARN: temporal_ca offset comparison skipped: {_ca_exc}",
                file=sys.stderr,
                flush=True,
            )

    # Repoint the export classifier/calibrator to the FINAL winner. The export's
    # generic branch reads models.classifier, so after a spatial swap into (or
    # out of) the ensemble these must match. hist_gbm variants are special-cased
    # in export via tree_classifier, so they need no repoint here.
    if winner == "xgb_undersample_ensemble":
        classifier, calibrator = ensemble_classifier, ensemble_calibrator
    elif winner == "hist_gbm":
        classifier, calibrator = tree_classifier, tree_calibrator

    return _export_forecasts(
        curated_dir=curated_dir,
        forecast_date=forecast_date,
        frame=frame,
        full_frame=full_frame,
        features=features,
        densities=densities,
        valid_idx=valid_idx,
        test_idx=test_idx,
        stations=stations,
        uv_daily=uv_daily,
        advisories=advisories,
        models=_TrainedModels(
            winner=winner,
            tree_classifier=tree_classifier,
            tree_calibrator=tree_calibrator,
            classifier=classifier,
            calibrator=calibrator,
            logistic=logistic,
            logistic_calibrator=logistic_calibrator,
            coastal_cell_logistic=coastal_cell_logistic,
            hierarchical_logistic=hierarchical_logistic,
            ensemble_weights=ensemble_weights,
            regressor=regressor,
            regressor_valid_predictions=regressor_valid_predictions,
            offset_classifier=offset_classifier,
            offset_calibrator=offset_calibrator,
        ),
        plan=plan,
        metrics=metrics,
        model_types_to_run=[],
        spatial_backtests=spatial_backtests,
        spatial_backtest_models=["persistence", winner],
        spatial_strategy=spatial_strategy,
        min_sample_recency_days=min_sample_recency_days,
        enforce_release_gate=enforce_release_gate,
    )


def train_curated_and_export(
    curated_dir: Path,
    forecast_date: date,
    sequence_epochs: int = 4,
    spatial_backtests: bool = False,
    spatial_beach_limit: int | None = None,
    spatial_county_limit: int | None = None,
    spatial_jobs: int | None = None,
    model_type: str = "tcn",
    spatial_strategy: str = "shortlist",
    winner_only: bool = False,
    training_window_days: int = 365,
    min_sample_recency_days: int | None = None,
    active_only_training: bool = False,
    enforce_release_gate: bool = False,
) -> TrainingArtifacts:
    import sys
    if spatial_strategy not in SPATIAL_BACKTEST_STRATEGIES:
        raise ValueError(
            f"Unsupported spatial strategy '{spatial_strategy}'. "
            f"Expected one of {', '.join(SPATIAL_BACKTEST_STRATEGIES)}."
        )
    print("Loading datasets...", file=sys.stderr, flush=True)
    settings = get_settings()
    full_frame = _load_curated_training_frame(curated_dir)
    full_frame["sample_date"] = pd.to_datetime(full_frame["sample_date"])
    max_date = full_frame["sample_date"].max()
    # Keep the full history available for env-covariate persistence fallback
    # in _build_forecast_candidates.  Marine-micro features are 100% covered
    # only post-2020; widen with care so older zero-coverage rows don't dilute.
    frame = full_frame.loc[full_frame["sample_date"] > (max_date - pd.Timedelta(days=training_window_days))].copy()
    print(f"Training window: {training_window_days}d, rows={len(frame)}", file=sys.stderr, flush=True)
    stations = pd.read_parquet(curated_dir / "beaches.parquet")
    uv_daily_path = curated_dir / "uv_daily.parquet"
    uv_daily = pd.read_parquet(uv_daily_path) if uv_daily_path.exists() else pd.DataFrame()
    advisories_path = curated_dir / "advisories.parquet"
    advisories = pd.read_parquet(advisories_path) if advisories_path.exists() else pd.DataFrame()
    dataset = build_sliding_windows(frame)
    features = dataset.feature_frame.select_dtypes(include=["number"]).fillna(0.0)
    features = _inject_agent_features(features, dataset.metadata, full_frame, advisories, stations)
    features = _apply_stale_censoring(features)
    labels = dataset.targets_exceed
    densities = dataset.targets_log_density
    metadata = _metadata_with_groups(dataset.metadata, frame, stations=stations)

    if len(features) < 20:
        artifacts = TrainingArtifacts(winner="insufficient-data", metrics={"warning": {"samples": float(len(features))}})
        return artifacts

    train_idx, valid_idx, test_idx = _blocked_indices(dataset.metadata)
    baselines = make_baselines(features)
    metrics: dict[str, dict[str, float]] = {}
    eval_idx = test_idx if len(test_idx) else valid_idx
    valid_metadata = metadata.iloc[valid_idx].reset_index(drop=True)
    eval_metadata = metadata.iloc[eval_idx].reset_index(drop=True)

    if winner_only:
        registry = _read_production_model_registry(curated_dir)
        if registry is not None:
            return _run_winner_only(
                curated_dir=curated_dir,
                forecast_date=forecast_date,
                training_window_days=training_window_days,
                spatial_strategy=spatial_strategy,
                spatial_backtests=spatial_backtests,
                spatial_beach_limit=spatial_beach_limit,
                spatial_county_limit=spatial_county_limit,
                spatial_jobs=spatial_jobs,
                registry=registry,
                min_sample_recency_days=min_sample_recency_days,
                active_only_training=active_only_training,
                enforce_release_gate=enforce_release_gate,
            )
        print("production_model.json not found — running full comparison", file=sys.stderr, flush=True)

    print("Evaluating persistence baseline...", file=sys.stderr, flush=True)
    persistence = _persistence_probabilities(features, settings.epa_marine_enterococcus_stv)
    if len(valid_idx):
        metrics["persistence_valid"] = classification_metrics(labels[valid_idx], persistence[valid_idx])
    metrics["persistence"] = classification_metrics(labels[eval_idx], persistence[eval_idx])

    print("Training global logistic model...", file=sys.stderr, flush=True)
    logistic = baselines.logistic.fit(features.iloc[train_idx], labels[train_idx])
    logistic_valid_raw = logistic.predict_proba(features.iloc[valid_idx])[:, 1]
    metrics["logistic_valid"] = classification_metrics(labels[valid_idx], logistic_valid_raw)
    _, logistic_calibrator = _identity_or_calibrated(
        logistic_valid_raw, labels[valid_idx], valid_metadata
    )
    logistic_eval = logistic.predict_proba(features.iloc[eval_idx])[:, 1]
    if len(test_idx):
        logistic_eval = _apply_calibrator(logistic_calibrator, logistic_eval, eval_metadata)
    metrics["logistic"] = classification_metrics(labels[eval_idx], logistic_eval)

    print("Training coastal cells logistic model...", file=sys.stderr, flush=True)
    coastal_cell_logistic = _fit_coastal_cell_logistic_artifacts(features, labels, metadata, train_idx)
    coastal_valid_raw, _, _ = _predict_coastal_cell_logistic_raw(
        coastal_cell_logistic,
        features.iloc[valid_idx],
        metadata.iloc[valid_idx].reset_index(drop=True),
    )
    metrics["logistic_coastal_cells_valid"] = classification_metrics(labels[valid_idx], coastal_valid_raw)
    _, coastal_calibrator = _identity_or_calibrated(
        coastal_valid_raw, labels[valid_idx], valid_metadata
    )
    coastal_cell_logistic.calibrator = coastal_calibrator
    coastal_eval_raw, _, _ = _predict_coastal_cell_logistic_raw(
        coastal_cell_logistic,
        features.iloc[eval_idx],
        metadata.iloc[eval_idx].reset_index(drop=True),
    )
    coastal_eval = coastal_eval_raw.copy()
    if len(test_idx):
        coastal_eval = _apply_calibrator(coastal_calibrator, coastal_eval, eval_metadata)
    metrics["logistic_coastal_cells"] = classification_metrics(labels[eval_idx], coastal_eval)

    print("Training hierarchical logistic model...", file=sys.stderr, flush=True)
    hierarchical_logistic = _fit_hierarchical_logistic_artifacts(features, labels, metadata, train_idx)
    hierarchical_valid_raw, _ = _predict_hierarchical_logistic_raw(
        hierarchical_logistic,
        features.iloc[valid_idx],
        metadata.iloc[valid_idx].reset_index(drop=True),
    )
    metrics["logistic_hierarchical_valid"] = classification_metrics(labels[valid_idx], hierarchical_valid_raw)
    _, hierarchical_calibrator = _identity_or_calibrated(
        hierarchical_valid_raw, labels[valid_idx], valid_metadata
    )
    hierarchical_logistic.calibrator = hierarchical_calibrator
    hierarchical_eval_raw, _ = _predict_hierarchical_logistic_raw(
        hierarchical_logistic,
        features.iloc[eval_idx],
        metadata.iloc[eval_idx].reset_index(drop=True),
    )
    hierarchical_eval = hierarchical_eval_raw.copy()
    if len(test_idx):
        hierarchical_eval = _apply_calibrator(hierarchical_calibrator, hierarchical_eval, eval_metadata)
    metrics["logistic_hierarchical"] = classification_metrics(labels[eval_idx], hierarchical_eval)

    print("Training hist GBM model...", file=sys.stderr, flush=True)
    tree_classifier = baselines.tree_classifier.fit(features.iloc[train_idx], labels[train_idx])
    tree_valid_raw = tree_classifier.predict_proba(features.iloc[valid_idx])[:, 1]
    metrics["hist_gbm_valid"] = classification_metrics(labels[valid_idx], tree_valid_raw)
    _, tree_calibrator = _identity_or_calibrated(tree_valid_raw, labels[valid_idx], valid_metadata)
    tree_eval = tree_classifier.predict_proba(features.iloc[eval_idx])[:, 1]
    if len(test_idx):
        tree_eval = _apply_calibrator(tree_calibrator, tree_eval, eval_metadata)
    metrics["hist_gbm"] = classification_metrics(labels[eval_idx], tree_eval)

    # xgb_undersample_ensemble — always trained so the spatial gate can promote
    # it as production winner without a retrain. Leave-one-CA-county-out spatial
    # validation selected it over hist_gbm (+0.069 AUCPR / 0.100 vs 0.114 Brier);
    # see scripts/spatial_compare.py + scripts/spatial_incumbent.py.
    print("Training XGB undersample ensemble model...", file=sys.stderr, flush=True)
    xgb_ens_classifier = XGBUndersampleEnsemble().fit(features.iloc[train_idx], labels[train_idx])
    xgb_ens_valid_raw = xgb_ens_classifier.predict_proba(features.iloc[valid_idx])[:, 1]
    metrics["xgb_undersample_ensemble_valid"] = classification_metrics(labels[valid_idx], xgb_ens_valid_raw)
    _, xgb_ens_calibrator = _identity_or_calibrated(xgb_ens_valid_raw, labels[valid_idx], valid_metadata)
    xgb_ens_eval = xgb_ens_classifier.predict_proba(features.iloc[eval_idx])[:, 1]
    if len(test_idx):
        xgb_ens_eval = _apply_calibrator(xgb_ens_calibrator, xgb_ens_eval, eval_metadata)
    metrics["xgb_undersample_ensemble"] = classification_metrics(labels[eval_idx], xgb_ens_eval)

    # Compute validation + eval metrics for the positive persistence guard so it
    # can participate in production winner selection via _two_stage_training_plan.
    guard_valid = _positive_persistence_guarded_blend_probabilities(
        tree_valid_raw, persistence[valid_idx], PERSISTENCE_BLEND_MAX_MODEL_ALPHA,
    )
    metrics["hist_gbm_positive_persistence_guard_valid"] = classification_metrics(
        labels[valid_idx], guard_valid,
    )
    guard_eval = _positive_persistence_guarded_blend_probabilities(
        tree_eval, persistence[eval_idx], PERSISTENCE_BLEND_MAX_MODEL_ALPHA,
    )
    metrics["hist_gbm_positive_persistence_guard"] = classification_metrics(
        labels[eval_idx], guard_eval,
    )

    print("Computing stacked ensemble...", file=sys.stderr, flush=True)
    # Weighted-average blend of the four base classifiers.
    # Weights: AUCPR-proportional from the validation set.
    # valid metrics: raw (uncalibrated) predictions for fair model comparison —
    #   calibrators are fitted on valid, so applying them would inflate the score.
    # eval/inference: calibrated predictions so all components are on the same scale.
    _ensemble_valid_aucs = np.array([
        metrics.get("logistic_valid", {}).get("aucpr", 0.0),
        metrics.get("logistic_coastal_cells_valid", {}).get("aucpr", 0.0),
        metrics.get("logistic_hierarchical_valid", {}).get("aucpr", 0.0),
        metrics.get("hist_gbm_valid", {}).get("aucpr", 0.0),
    ])
    _auc_sum = _ensemble_valid_aucs.sum()
    ensemble_weights = _ensemble_valid_aucs / _auc_sum if _auc_sum > 0 else np.full(4, 0.25)
    # raw valid preds — no calibration leakage
    ensemble_valid = (
        np.stack([logistic_valid_raw, coastal_valid_raw, hierarchical_valid_raw, tree_valid_raw], axis=1)
        @ ensemble_weights
    )
    metrics["stacked_ensemble_valid"] = classification_metrics(labels[valid_idx], ensemble_valid)
    # calibrated eval preds — used for the test score and for production forecasts
    ensemble_eval = (
        np.stack([
            logistic_eval,
            coastal_eval,
            hierarchical_eval,
            tree_eval,
        ], axis=1)
        @ ensemble_weights
    )
    metrics["stacked_ensemble"] = classification_metrics(labels[eval_idx], ensemble_eval)

    print("Training elastic net model...", file=sys.stderr, flush=True)
    baselines.linear.fit(features.iloc[train_idx], densities[train_idx])
    linear_valid = baselines.linear.predict(features.iloc[valid_idx])
    metrics["elastic_net_valid"] = regression_metrics(densities[valid_idx], linear_valid)
    linear_eval = baselines.linear.predict(features.iloc[eval_idx])
    metrics["elastic_net"] = regression_metrics(densities[eval_idx], linear_eval)

    print("Training hist GBM regressor model...", file=sys.stderr, flush=True)
    baselines.tree_regressor.fit(features.iloc[train_idx], densities[train_idx])
    tree_reg_valid = baselines.tree_regressor.predict(features.iloc[valid_idx])
    metrics["hist_gbm_regressor_valid"] = regression_metrics(densities[valid_idx], tree_reg_valid)
    tree_reg_eval = baselines.tree_regressor.predict(features.iloc[eval_idx])
    metrics["hist_gbm_regressor"] = regression_metrics(densities[eval_idx], tree_reg_eval)

    model_types_to_run = list(SEQUENCE_MODEL_NAMES) if model_type == "all" else ([] if model_type == "none" else [model_type])
    for mt in model_types_to_run:
        print(f"Training {mt.upper()} sequence model...", file=sys.stderr, flush=True)
        artifacts = train_sequence_model(
            frame,
            train_idx=train_idx,
            valid_idx=valid_idx,
            test_idx=test_idx,
            epochs=sequence_epochs,
            model_type=mt,
        )
        metrics[f"{mt}_valid"] = artifacts.valid_metrics
        metrics[mt] = artifacts.test_metrics

    plan = _two_stage_training_plan(metrics, model_types_to_run)
    spatial_backtest_models = [*SPATIAL_BACKTEST_MODEL_NAMES, *model_types_to_run]
    effective_beach_limit = spatial_beach_limit
    effective_county_limit = spatial_county_limit

    if spatial_strategy in ("shortlist", "quick"):
        spatial_backtest_models = plan.spatial_backtest_models
        if spatial_strategy == "quick":
            effective_beach_limit = spatial_beach_limit or 5
            effective_county_limit = spatial_county_limit or 3

    spatial_predictions_sink: dict = {}
    if spatial_backtests:
        print(
            "Running stage 2 spatial backtests for "
            + ", ".join(model_name.upper() for model_name in spatial_backtest_models)
            + "...",
            file=sys.stderr,
            flush=True,
        )
        resolved_spatial_jobs = spatial_jobs or _default_spatial_jobs()
        metrics.update(
            _spatial_backtest_metrics(
                features,
                labels,
                metadata,
                stv_threshold=settings.epa_marine_enterococcus_stv,
                beach_group_limit=effective_beach_limit,
                county_group_limit=effective_county_limit,
                spatial_jobs=resolved_spatial_jobs,
                dataset=dataset,
                model_names_to_run=spatial_backtest_models,
                sequence_epochs=sequence_epochs,
                predictions_sink=spatial_predictions_sink,
            )
        )

    winner = _spatially_qualified_production_winner(
        metrics,
        preferred=plan.production_winner,
        candidates=PRODUCTION_MODEL_NAMES,
        predictions_sink=spatial_predictions_sink,
    )
    if winner != plan.production_winner:
        plan = StageTwoTrainingPlan(
            production_winner=winner,
            research_winner=plan.research_winner,
            spatial_backtest_models=plan.spatial_backtest_models,
        )

    # Persist the FINAL winner's held-out (label, probability) pairs + record the
    # Searcy sensitivity@spec operating point (temporal-test + spatial pooled).
    _winner_temporal_eval = {
        "hist_gbm": tree_eval,
        "xgb_undersample_ensemble": xgb_ens_eval,
        "logistic": logistic_eval,
    }.get(_metrics_base_key(winner))
    _persist_and_diagnose_holdouts(
        curated_dir,
        winner=winner,
        metrics=metrics,
        temporal_probs=_winner_temporal_eval,
        labels=labels,
        eval_idx=eval_idx,
        eval_metadata=eval_metadata,
        features=features,
        predictions_sink=spatial_predictions_sink,
    )

    if winner == "logistic":
        classifier, calibrator = logistic, logistic_calibrator
    elif winner == "xgb_undersample_ensemble":
        classifier, calibrator = xgb_ens_classifier, xgb_ens_calibrator
    else:
        classifier, calibrator = tree_classifier, tree_calibrator
    if metrics["elastic_net_valid"]["rmse"] <= metrics["hist_gbm_regressor_valid"]["rmse"]:
        regressor = baselines.linear
        regressor_valid_predictions = linear_valid
    else:
        regressor = baselines.tree_regressor
        regressor_valid_predictions = tree_reg_valid

    _write_production_model_registry(
        curated_dir,
        winner=winner,
        regressor="elastic_net" if regressor is baselines.linear else "hist_gbm_regressor",
        ensemble_weights=ensemble_weights.tolist() if winner == "stacked_ensemble" and ensemble_weights is not None else None,
    )
    # The serve-time router needs the offset model regardless of which entrypoint
    # produced the winner — see _train_offset_model. This path calibrates on
    # valid_idx, matching the calibrator fit used for every other model here.
    offset_classifier, offset_calibrator = _train_offset_model(
        features, labels, metadata, train_idx, valid_idx, valid_metadata
    )
    return _export_forecasts(
        curated_dir=curated_dir,
        forecast_date=forecast_date,
        frame=frame,
        full_frame=full_frame,
        features=features,
        densities=densities,
        valid_idx=valid_idx,
        test_idx=test_idx,
        stations=stations,
        uv_daily=uv_daily,
        advisories=advisories,
        models=_TrainedModels(
            winner=winner,
            tree_classifier=tree_classifier,
            tree_calibrator=tree_calibrator,
            classifier=classifier,
            calibrator=calibrator,
            logistic=logistic,
            logistic_calibrator=logistic_calibrator,
            coastal_cell_logistic=coastal_cell_logistic,
            hierarchical_logistic=hierarchical_logistic,
            ensemble_weights=ensemble_weights,
            regressor=regressor,
            regressor_valid_predictions=regressor_valid_predictions,
            offset_classifier=offset_classifier,
            offset_calibrator=offset_calibrator,
        ),
        plan=plan,
        metrics=metrics,
        model_types_to_run=model_types_to_run,
        spatial_backtests=spatial_backtests,
        spatial_backtest_models=spatial_backtest_models,
        spatial_strategy=spatial_strategy,
        min_sample_recency_days=min_sample_recency_days,
        enforce_release_gate=enforce_release_gate,
    )



def train_all(
    sample_fixture: bool = False,
    curated: bool = False,
    forecast_date: date | None = None,
    spatial_backtests: bool = False,
    spatial_beach_limit: int | None = None,
    spatial_county_limit: int | None = None,
    spatial_jobs: int | None = None,
    model_type: str = "tcn",
    spatial_strategy: str = "shortlist",
    winner_only: bool = False,
    training_window_days: int = 365,
    min_sample_recency_days: int | None = None,
    active_only_training: bool = False,
    enforce_release_gate: bool = False,
) -> TrainingArtifacts:
    settings = get_settings()
    if curated:
        return train_curated_and_export(
            Path(settings.curated_dir),
            forecast_date=forecast_date or datetime.now(UTC).date(),
            spatial_backtests=spatial_backtests,
            spatial_beach_limit=spatial_beach_limit,
            spatial_county_limit=spatial_county_limit,
            spatial_jobs=spatial_jobs,
            model_type=model_type,
            spatial_strategy=spatial_strategy,
            winner_only=winner_only,
            training_window_days=training_window_days,
            min_sample_recency_days=min_sample_recency_days,
            active_only_training=active_only_training,
            enforce_release_gate=enforce_release_gate,
        )
    if not sample_fixture:
        raise NotImplementedError("Training currently expects fixture-backed development data.")

    frame = _load_fixture_training_frame()
    baseline_metrics = train_baselines(frame)
    metrics = {**baseline_metrics}
    
    model_types_to_run = list(SEQUENCE_MODEL_NAMES) if model_type == "all" else [model_type]
    for mt in model_types_to_run:
        sequence_artifacts = train_sequence_model(frame, model_type=mt)
        metrics[f"{mt}_valid"] = sequence_artifacts.valid_metrics
        metrics[mt] = sequence_artifacts.test_metrics

    winner = min(
        ("logistic", "hist_gbm"),
        key=lambda model_name: baseline_metrics.get(model_name, {}).get("brier", float("inf")),
    )
    return TrainingArtifacts(winner=winner, metrics=metrics)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Surf Health forecasting models")
    parser.add_argument("--sample-fixture", action="store_true")
    parser.add_argument("--curated", action="store_true")
    parser.add_argument("--forecast-date", type=str, default=None)
    parser.add_argument("--spatial-backtests", action="store_true")
    parser.add_argument("--spatial-beach-limit", type=int, default=None)
    parser.add_argument("--spatial-county-limit", type=int, default=None)
    parser.add_argument("--spatial-jobs", type=int, default=None)
    parser.add_argument(
        "--spatial-strategy",
        type=str,
        default="shortlist",
        choices=list(SPATIAL_BACKTEST_STRATEGIES),
    )
    parser.add_argument("--model", type=str, default="tcn", choices=["tcn", "cnn", "lstm", "transformer", "pinn", "all", "none"])
    parser.add_argument("--winner-only", action="store_true",
                        help="Retrain only the persisted backtest winner (reads production_model.json). "
                             "Falls back to full comparison if no registry exists.")
    parser.add_argument("--training-window-days", type=int, default=365,
                        help="Days of recent beach_day rows to train on. Default 60. "
                             "Set higher (e.g. 365) once marine-micro coverage is uniform.")
    parser.add_argument("--forecast-min-recency-days", type=int, default=None,
                        help="Drop beaches whose most-recent sample is older than this many "
                             "days before the forecast date. California beach monitoring funding "
                             "has been cut multiple times since 2020 and many stations have gone "
                             "silent; publishing a forecast for one of those stations is "
                             "misleading. Recommended value: 20 (one missed AB411 weekly cycle "
                             "is normal; three+ missed weeks indicates discontinued monitoring).")
    parser.add_argument("--active-only-training", action="store_true",
                        help="A/B ablation: filter the training set to only beaches active as "
                             "of forecast_date (per --forecast-min-recency-days). Validation "
                             "and test slices are NOT filtered, so this can be compared head-to-"
                             "head against the full-training-set run on the same held-out samples.")
    parser.add_argument("--enforce-release-gate", action="store_true",
                        help="Block publication when the promotion assessment finds the model "
                             "ineligible for public release: skip overwriting forecasts.parquet "
                             "(the last-validated forecast keeps serving) while still writing "
                             "system_health.json with the blockers. Off by default so local/"
                             "exploratory runs always emit a forecast; CI passes it.")
    args = parser.parse_args()
    forecast_date = date.fromisoformat(args.forecast_date) if args.forecast_date else None
    artifacts = train_all(
        sample_fixture=args.sample_fixture,
        curated=args.curated,
        forecast_date=forecast_date,
        spatial_backtests=args.spatial_backtests,
        spatial_beach_limit=args.spatial_beach_limit,
        spatial_county_limit=args.spatial_county_limit,
        spatial_jobs=args.spatial_jobs,
        model_type=args.model,
        spatial_strategy=args.spatial_strategy,
        winner_only=args.winner_only,
        training_window_days=args.training_window_days,
        min_sample_recency_days=args.forecast_min_recency_days,
        active_only_training=args.active_only_training,
        enforce_release_gate=args.enforce_release_gate,
    )
    print(json.dumps(asdict(artifacts), indent=2))


if __name__ == "__main__":
    main()
