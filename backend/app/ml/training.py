from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
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
from app.data.pipeline.features import (
    STORMWATER_EXPERT_NUMERIC_COLUMNS,
    SlidingWindowDataset,
    build_inference_features,
    build_inference_windows,
    build_sliding_windows,
)
from app.ml.calibration import (
    HierarchicalProbabilityCalibrator,
    ProbabilityCalibrator,
    _VERY_HIGH_THRESHOLD as _CAL_VERY_HIGH,
    risk_band,
)
from app.ml.datasets import SequenceDataset
from app.ml.evaluation import classification_metrics, regression_metrics
from app.ml.models import (
    BeachCNN, 
    BeachTCN, 
    BeachLSTM, 
    BeachTransformer, 
    BeachPINN_MultiTask, 
    make_baselines
)

MIN_PLAUSIBLE_SAMPLE_TIME = pd.Timestamp("2000-01-01")
MAX_FUTURE_SAMPLE_LEEWAY_DAYS = 2
COASTAL_CELL_MIN_BEACHES_PER_CLUSTER = 24
COASTAL_CELL_MAX_CLUSTERS = 8
PRODUCTION_MODEL_NAMES = ("logistic", "logistic_coastal_cells", "logistic_hierarchical", "hist_gbm", "stacked_ensemble")
SEQUENCE_MODEL_NAMES = ("tcn", "cnn", "lstm", "transformer", "pinn")
SPATIAL_BACKTEST_STRATEGIES = ("shortlist", "requested", "quick")
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
        "distance_to_pour_point_km",
        "distance_to_gage_km",
        "watershed_area_km2",
        *STORMWATER_EXPERT_NUMERIC_COLUMNS,
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
            "distance_to_pour_point_km",
            "distance_to_gage_km",
            "watershed_area_km2",
            *STORMWATER_EXPERT_NUMERIC_COLUMNS,
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
    predicting the majority class. ``enterococcus_value_last_obs`` is explicitly
    constructed as the last observed value prior to the target row (forecast-safe),
    so thresholding it is the right "do what we did last time" comparator.
    """
    last_obs = pd.to_numeric(features.get("enterococcus_value_last_obs"), errors="coerce")
    if last_obs is None:
        return np.zeros(len(features), dtype=float)
    return last_obs.fillna(0.0).gt(stv_threshold).astype(float).to_numpy()


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
    raise ValueError(f"Unsupported classifier model '{model_name}'")


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
            try: aucs.append(average_precision_score(labels[inner_valid_rows], v))
            except: aucs.append(0.0)
        _aucs = np.array(aucs)
        _s = _aucs.sum()
        w = _aucs / _s if _s > 0 else np.full(4, 0.25)

        test_probabilities = log_test * w[0] + cc_test * w[1] + h_test * w[2] + gbm_test * w[3]
        return labels[test_rows], test_probabilities

    classifier = _fit_classifier_for_name(features, model_name)
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
    return labels[test_rows], test_probabilities


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
    for result in fold_results:
        if result is None:
            continue
        fold_labels, fold_probabilities = result
        heldout_labels.append(fold_labels)
        heldout_probabilities.append(fold_probabilities)
        used_groups += 1

    if not heldout_labels:
        return {
            "folds": 0.0,
            "eligible_groups": float(len(eligible_groups)),
            "heldout_rows": 0.0,
        }

    all_labels = np.concatenate(heldout_labels)
    all_probabilities = np.concatenate(heldout_probabilities)
    metrics = classification_metrics(all_labels, all_probabilities)
    metrics["folds"] = float(used_groups)
    metrics["eligible_groups"] = float(len(eligible_groups))
    metrics["heldout_rows"] = float(len(all_labels))
    metrics["positive_rate"] = float(all_labels.mean())
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
) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}
    selected_model_names = model_names_to_run
    if selected_model_names is None:
        selected_model_names = [*PRODUCTION_MODEL_NAMES]
        if model_types_to_run:
            selected_model_names.extend(
                model_name for model_name in model_types_to_run if model_name in SEQUENCE_MODEL_NAMES
            )

    normalized_model_names: list[str] = []
    for model_name in ["persistence", *selected_model_names]:
        if model_name != "persistence" and model_name not in PRODUCTION_MODEL_NAMES and model_name not in SEQUENCE_MODEL_NAMES:
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
    return StageTwoTrainingPlan(
        production_winner=production_winner,
        research_winner=research_winner,
        spatial_backtest_models=spatial_backtest_models,
    )


def _promotion_assessment(
    metrics: dict[str, dict[str, float]],
    winner: str,
) -> dict[str, object]:
    spatial_metrics = {name: value for name, value in metrics.items() if name.startswith("spatial_")}
    blockers: list[str] = []
    if not spatial_metrics:
        blockers.append("Spatial holdout metrics have not been run for this artifact.")
    else:
        if f"spatial_county_{winner}" not in metrics:
            blockers.append(f"Held-out county metrics are missing for {winner}.")
        if f"spatial_beach_{winner}" not in metrics:
            blockers.append(f"Held-out beach metrics are missing for {winner}.")
        county_model = metrics.get(f"spatial_county_{winner}", {})
        county_persistence = metrics.get("spatial_county_persistence", {})
        if county_model and county_persistence:
            model_aucpr = county_model.get("aucpr")
            baseline_aucpr = county_persistence.get("aucpr")
            if model_aucpr is not None and baseline_aucpr is not None and model_aucpr <= baseline_aucpr:
                blockers.append("Held-out county AUCPR does not beat persistence.")
            model_brier = county_model.get("brier")
            baseline_brier = county_persistence.get("brier")
            if model_brier is not None and baseline_brier is not None and model_brier >= baseline_brier:
                blockers.append("Held-out county Brier score does not beat persistence.")
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


def _forecast_model_version(model_name: str, scope: str = "global") -> str:
    if model_name == "logistic_hierarchical":
        return f"logistic-{scope}-curated-v0"
    return _registry_model_version(model_name)

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

    def _fmt(x: object) -> str:
        try:
            if x is None:
                return "—"
            return f"{float(x):.3f}"
        except (TypeError, ValueError):
            return "—"

    audit = health_payload.get("forecast_audit") or {}
    agreement = audit.get("agreement_rate")

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
            f"- **AUCPR**: {_fmt((all_metrics.get('hist_gbm_test_active_only') or {}).get('aucpr'))}",
            f"- **Brier**: {_fmt((all_metrics.get('hist_gbm_test_active_only') or {}).get('brier'))}",
            f"- **n_samples**: {int((all_metrics.get('hist_gbm_test_active_only') or {}).get('n_samples') or 0)}",
            "",
            "### Validation (calibration/training-time slice; not a public headline)",
            f"- **AUCPR**: {_fmt(valid.get('aucpr'))}",
            f"- **Brier**: {_fmt(valid.get('brier'))}",
            "",
            "### Spatial (holdouts)",
            f"- **Spatial county AUCPR**: {_fmt((spatial.get('spatial_county_hist_gbm') or {}).get('aucpr'))}",
            f"- **Spatial county persistence AUCPR**: {_fmt((spatial.get('spatial_county_persistence') or {}).get('aucpr'))}",
            "",
            "## Operational Agreement Check",
            f"- **Active-advisory agreement rate** (model flags High band on advised beaches): {_fmt(agreement)}",
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
    adv["ended_at_filled"] = adv["ended_at_ts"].fillna(pd.Timestamp("2099-01-01"))

    forecast_ts = pd.Timestamp(forecast_date)
    window_start = forecast_ts - pd.Timedelta(days=14)

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

    closed = adv[adv["ended_at_ts"].notna()].copy()
    closed["_days"] = (forecast_ts - closed["ended_at_ts"]).dt.days
    closed = closed[closed["_days"] >= 0]
    if not closed.empty:
        min_days = closed.groupby("beach_id")["_days"].min()
        candidates["days_since_advisory_closed"] = candidates["beach_id"].map(min_days)
    elif "days_since_advisory_closed" not in candidates.columns:
        candidates["days_since_advisory_closed"] = np.nan


def _build_forecast_candidates(
    frame: pd.DataFrame,
    stations: pd.DataFrame,
    uv_daily: pd.DataFrame,
    forecast_date: date,
    *,
    full_frame: pd.DataFrame | None = None,
    advisories: pd.DataFrame | None = None,
    min_sample_recency_days: int | None = None,
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
    (curated_dir / _PRODUCTION_MODEL_REGISTRY).write_text(json.dumps(data, indent=2))


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
    history, forecast_candidates = _build_forecast_candidates(
        frame,
        stations,
        uv_daily,
        forecast_date,
        full_frame=full_frame,
        advisories=advisories,
        min_sample_recency_days=min_sample_recency_days,
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
    else:
        raw_probabilities = classifier.predict_proba(baseline_forecast_features)[:, 1]
        probabilities = _apply_calibrator(calibrator, raw_probabilities, forecast_group_metadata)
        probability_lower, probability_upper = _calibration_interval(
            calibrator,
            raw_probabilities,
            forecast_group_metadata,
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
    settings = get_settings()
    forecasts = []
    forecast_lookup = (
        forecast_candidates.drop_duplicates(subset=["beach_id"], keep="last").set_index("beach_id")
        if not forecast_candidates.empty
        else pd.DataFrame()
    )
    uv_lookup = _build_uv_lookup(uv_daily, forecast_date)
    station_lookup = stations.set_index("beach_id")
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
            advisory_recent = _safe_float(feature_row.get("advisory_recent_active")) or 0.0
            p_raw = float(probability)
            p_final = max(p_raw, 0.20) if advisory_recent else p_raw
            p_lower = probability_lower[i] if i < len(probability_lower) else np.nan
            p_upper = probability_upper[i] if i < len(probability_upper) else np.nan
            p_lower_final = max(float(p_lower), 0.20) if advisory_recent and np.isfinite(p_lower) else (
                float(p_lower) if np.isfinite(p_lower) else None
            )
            p_upper_final = max(float(p_upper), p_final) if np.isfinite(p_upper) else None
            forecasts.append({
                "beach_id": beach_id,
                "forecast_date": forecast_date.isoformat(),
                "risk_band": risk_band(p_final),
                "p_exceed": p_final,
                "p_exceed_raw": p_raw,
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
                "forecast_generated_at": forecast_generated_at,
                "wave_height_m": _safe_float(latest_row.get("wave_height_m")) if latest_row is not None else None,
                "dominant_period_s": _safe_float(latest_row.get("dominant_period_s")) if latest_row is not None else None,
                "water_temperature_c": _safe_float(latest_row.get("water_temperature_c")) if latest_row is not None else None,
                "salinity_psu": _safe_float(latest_row.get("salinity_psu")) if latest_row is not None else None,
                "uv_index": uv_index,
                "uv_alert": uv_alert,
            })
    pd.DataFrame(forecasts).to_parquet(curated_dir / "forecasts.parquet", index=False)

    # Write latest_env.parquet — tiny lookup for the API server so it never has to
    # load the full 446 MB beach_day.parquet at runtime (Render free-tier OOM fix).
    _ENV_COLS = ["wave_height_m", "dominant_period_s", "water_temperature_c",
                 "salinity_psu", "uv_index", "wind_speed_mps", "wind_direction_deg"]
    _env_present = [c for c in _ENV_COLS if c in full_frame.columns]
    _latest_env = (
        full_frame[["beach_id", "sample_date"] + _env_present]
        .sort_values("sample_date")
        .groupby("beach_id", as_index=False)
        .last()
    )
    for _col in _ENV_COLS:
        if _col not in _latest_env.columns:
            _latest_env[_col] = float("nan")
    _latest_env[["beach_id"] + _ENV_COLS].to_parquet(curated_dir / "latest_env.parquet", index=False)

    health_path = curated_dir / "system_health.json"
    health_payload = json.loads(health_path.read_text()) if health_path.exists() else {}
    promotion = _promotion_assessment(metrics, winner)
    health_payload["model_registry"] = {
        "production_model": _registry_model_version(winner),
        "temporal_validation_winner": _registry_model_version(plan.research_winner),
        "candidate_models": [_registry_model_version(m) for m in PRODUCTION_MODEL_NAMES],
        "research_models": [_registry_model_version(m) for m in model_types_to_run],
        "spatial_backtest_models": [_registry_model_version(m) for m in spatial_backtest_models],
        "spatial_backtest_strategy": spatial_strategy if spatial_backtests else "disabled",
        "production_metrics": metrics.get(winner, {}),
        "validation_metrics": metrics.get(f"{winner}_valid", {}),
        "temporal_validation_metrics": metrics.get(f"{plan.research_winner}_valid", {}),
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
    health_payload["pipeline_freshness"] = datetime.now(UTC).isoformat()
    health_path.write_text(json.dumps(health_payload, indent=2))
    _write_model_card(curated_dir, health_payload)
    return TrainingArtifacts(winner=winner, metrics=metrics)


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

    valid_metadata = metadata.iloc[valid_idx].reset_index(drop=True)
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

    plan = StageTwoTrainingPlan(
        production_winner=winner, research_winner=winner, spatial_backtest_models=[winner],
    )

    if spatial_backtests:
        print(f"Running stage 2 spatial backtests for {winner.upper()}...", file=sys.stderr, flush=True)
        
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
                model_names_to_run=[winner],
            )
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
        ),
        plan=plan,
        metrics=metrics,
        model_types_to_run=[],
        spatial_backtests=spatial_backtests,
        spatial_backtest_models=["persistence", winner],
        spatial_strategy=spatial_strategy,
        min_sample_recency_days=min_sample_recency_days,
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
    training_window_days: int = 60,
    min_sample_recency_days: int | None = None,
    active_only_training: bool = False,
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
    spatial_backtest_models = [*PRODUCTION_MODEL_NAMES, *model_types_to_run]
    effective_beach_limit = spatial_beach_limit
    effective_county_limit = spatial_county_limit

    if spatial_strategy in ("shortlist", "quick"):
        spatial_backtest_models = plan.spatial_backtest_models
        if spatial_strategy == "quick":
            effective_beach_limit = spatial_beach_limit or 5
            effective_county_limit = spatial_county_limit or 3

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
            )
        )

    winner = plan.production_winner
    classifier = logistic if winner == "logistic" else tree_classifier
    calibrator = logistic_calibrator if winner == "logistic" else tree_calibrator
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
        ),
        plan=plan,
        metrics=metrics,
        model_types_to_run=model_types_to_run,
        spatial_backtests=spatial_backtests,
        spatial_backtest_models=spatial_backtest_models,
        spatial_strategy=spatial_strategy,
        min_sample_recency_days=min_sample_recency_days,
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
    training_window_days: int = 60,
    min_sample_recency_days: int | None = None,
    active_only_training: bool = False,
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
    parser.add_argument("--training-window-days", type=int, default=60,
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
    )
    print(json.dumps(asdict(artifacts), indent=2))


if __name__ == "__main__":
    main()
