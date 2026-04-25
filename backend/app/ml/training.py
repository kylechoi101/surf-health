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
    SlidingWindowDataset,
    build_inference_features,
    build_inference_windows,
    build_sliding_windows,
)
from app.ml.calibration import ProbabilityCalibrator, risk_band
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
SPATIAL_BACKTEST_STRATEGIES = ("shortlist", "requested")
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
    lag_1 = pd.to_numeric(features.get("enterococcus_value_lag_1"), errors="coerce")
    if lag_1 is None:
        return np.zeros(len(features), dtype=float)
    return lag_1.fillna(0.0).gt(stv_threshold).astype(float).to_numpy()


def _metadata_with_groups(metadata: pd.DataFrame, frame: pd.DataFrame) -> pd.DataFrame:
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
        _, calibrator = _identity_or_calibrated(valid_raw, labels[inner_valid_rows])
        test_probabilities, _, _ = _predict_coastal_cell_logistic_raw(
            artifacts,
            features.iloc[test_rows],
            metadata.iloc[test_rows].reset_index(drop=True),
        )
        if calibrator is not None:
            test_probabilities = calibrator.transform(test_probabilities)
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
        _, calibrator = _identity_or_calibrated(valid_raw, labels[inner_valid_rows])
        test_probabilities, _ = _predict_hierarchical_logistic_raw(
            artifacts,
            features.iloc[test_rows],
            metadata.iloc[test_rows].reset_index(drop=True),
        )
        if calibrator is not None:
            test_probabilities = calibrator.transform(test_probabilities)
        return labels[test_rows], test_probabilities

    classifier = _fit_classifier_for_name(features, model_name)
    classifier.fit(features.iloc[inner_train_rows], labels[inner_train_rows])
    valid_raw = classifier.predict_proba(features.iloc[inner_valid_rows])[:, 1]
    _, calibrator = _identity_or_calibrated(valid_raw, labels[inner_valid_rows])
    test_probabilities = classifier.predict_proba(features.iloc[test_rows])[:, 1]
    if calibrator is not None:
        test_probabilities = calibrator.transform(test_probabilities)
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
    effective_spatial_jobs = 1 if model_name in SEQUENCE_MODEL_NAMES else spatial_jobs
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
    _, calibrator = _identity_or_calibrated(valid_probabilities, dataset.targets_exceed[valid_idx])

    if len(test_idx):
        test_probabilities, test_density = _predict_sequence_subset(model, sequence_dataset, test_idx, device)
        if calibrator is not None:
            test_probabilities = calibrator.transform(test_probabilities)
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
    unique_dates = np.array(sorted(sample_dates.dropna().unique()))
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

    sample_dates_array = sample_dates.to_numpy()
    train_idx = np.flatnonzero(np.isin(sample_dates_array, train_dates))
    valid_idx = np.flatnonzero(np.isin(sample_dates_array, valid_dates))
    test_idx = np.flatnonzero(np.isin(sample_dates_array, test_dates))
    return train_idx, valid_idx, test_idx


def _identity_or_calibrated(
    probabilities: np.ndarray, labels: np.ndarray
) -> tuple[np.ndarray, ProbabilityCalibrator | None]:
    labels = np.asarray(labels)
    if len(probabilities) == 0 or len(labels) == 0 or len(np.unique(labels)) < 2:
        return probabilities, None
    calibrator = ProbabilityCalibrator().fit(probabilities, labels)
    return calibrator.transform(probabilities), calibrator


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


def _two_stage_training_plan(
    metrics: dict[str, dict[str, float]],
    model_types_to_run: list[str],
) -> StageTwoTrainingPlan:
    production_winner = _best_valid_brier_model(
        metrics,
        PRODUCTION_MODEL_NAMES,
        fallback="logistic",
    ) or "logistic"
    research_candidates = [
        *PRODUCTION_MODEL_NAMES,
        *[model_name for model_name in model_types_to_run if model_name in SEQUENCE_MODEL_NAMES],
    ]
    research_winner = _best_valid_brier_model(
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


def _build_forecast_candidates(
    frame: pd.DataFrame,
    stations: pd.DataFrame,
    uv_daily: pd.DataFrame,
    forecast_date: date,
    *,
    full_frame: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build one synthetic forecast row per beach.

    ``frame`` is the recent training window (typically 60 days).  When a
    covariate is missing from that window (e.g. because the upstream ingest
    dropped the column for a period), we fall back to the most-recent non-null
    value from ``full_frame`` — the complete unfiltered history.  This gives
    us env-persistence rather than all-null inputs, which keeps the calibrated
    probability meaningful even when the ingest pipeline has schema drift.
    """
    history = frame.copy()
    history["sample_date"] = pd.to_datetime(history["sample_date"], errors="coerce")
    history["sample_time"] = pd.to_datetime(history["sample_time"], errors="coerce")
    history = history.loc[history["sample_date"].dt.date < forecast_date].copy()
    if history.empty:
        return history, pd.DataFrame()

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
    if artifacts.calibrator is not None:
        probabilities = artifacts.calibrator.transform(probabilities)
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
            elif col == "streamflow_cfs_latest":
                driver_strings.append(f"elevated stream discharge ({val:.0f} cfs)")
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
            # else: feature has no human-readable mapping — skip it rather than
            # leaking internal names like "day of year (114.0)" to end users.

        if not driver_strings:
            driver_strings = ["stable recent conditions with no strong environmental signal"]

        all_drivers.append(driver_strings)

    return all_drivers


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
    # in _build_forecast_candidates.  The training window is still capped at
    # 60 days so the model doesn't over-weight stale bacterial data.
    frame = full_frame.loc[full_frame["sample_date"] > (max_date - pd.Timedelta(days=60))].copy()
    stations = pd.read_parquet(curated_dir / "beaches.parquet")
    uv_daily_path = curated_dir / "uv_daily.parquet"
    uv_daily = pd.read_parquet(uv_daily_path) if uv_daily_path.exists() else pd.DataFrame()
    dataset = build_sliding_windows(frame)
    features = dataset.feature_frame.select_dtypes(include=["number"]).fillna(0.0)
    labels = dataset.targets_exceed
    densities = dataset.targets_log_density
    metadata = _metadata_with_groups(dataset.metadata, frame)

    if len(features) < 20:
        artifacts = TrainingArtifacts(winner="insufficient-data", metrics={"warning": {"samples": float(len(features))}})
        return artifacts

    train_idx, valid_idx, test_idx = _blocked_indices(dataset.metadata)
    baselines = make_baselines(features)
    metrics: dict[str, dict[str, float]] = {}
    eval_idx = test_idx if len(test_idx) else valid_idx

    print("Evaluating persistence baseline...", file=sys.stderr, flush=True)
    persistence = _persistence_probabilities(features, settings.epa_marine_enterococcus_stv)
    if len(valid_idx):
        metrics["persistence_valid"] = classification_metrics(labels[valid_idx], persistence[valid_idx])
    metrics["persistence"] = classification_metrics(labels[eval_idx], persistence[eval_idx])

    print("Training global logistic model...", file=sys.stderr, flush=True)
    logistic = baselines.logistic.fit(features.iloc[train_idx], labels[train_idx])
    logistic_valid_raw = logistic.predict_proba(features.iloc[valid_idx])[:, 1]
    metrics["logistic_valid"] = classification_metrics(labels[valid_idx], logistic_valid_raw)
    _, logistic_calibrator = _identity_or_calibrated(logistic_valid_raw, labels[valid_idx])
    logistic_eval = logistic.predict_proba(features.iloc[eval_idx])[:, 1]
    if logistic_calibrator is not None and len(test_idx):
        logistic_eval = logistic_calibrator.transform(logistic_eval)
    metrics["logistic"] = classification_metrics(labels[eval_idx], logistic_eval)

    print("Training coastal cells logistic model...", file=sys.stderr, flush=True)
    coastal_cell_logistic = _fit_coastal_cell_logistic_artifacts(features, labels, metadata, train_idx)
    coastal_valid_raw, _, _ = _predict_coastal_cell_logistic_raw(
        coastal_cell_logistic,
        features.iloc[valid_idx],
        metadata.iloc[valid_idx].reset_index(drop=True),
    )
    metrics["logistic_coastal_cells_valid"] = classification_metrics(labels[valid_idx], coastal_valid_raw)
    _, coastal_calibrator = _identity_or_calibrated(coastal_valid_raw, labels[valid_idx])
    coastal_cell_logistic.calibrator = coastal_calibrator
    coastal_eval_raw, _, _ = _predict_coastal_cell_logistic_raw(
        coastal_cell_logistic,
        features.iloc[eval_idx],
        metadata.iloc[eval_idx].reset_index(drop=True),
    )
    coastal_eval = coastal_eval_raw.copy()
    if coastal_calibrator is not None and len(test_idx):
        coastal_eval = coastal_calibrator.transform(coastal_eval)
    metrics["logistic_coastal_cells"] = classification_metrics(labels[eval_idx], coastal_eval)

    print("Training hierarchical logistic model...", file=sys.stderr, flush=True)
    hierarchical_logistic = _fit_hierarchical_logistic_artifacts(features, labels, metadata, train_idx)
    hierarchical_valid_raw, _ = _predict_hierarchical_logistic_raw(
        hierarchical_logistic,
        features.iloc[valid_idx],
        metadata.iloc[valid_idx].reset_index(drop=True),
    )
    metrics["logistic_hierarchical_valid"] = classification_metrics(labels[valid_idx], hierarchical_valid_raw)
    _, hierarchical_calibrator = _identity_or_calibrated(hierarchical_valid_raw, labels[valid_idx])
    hierarchical_logistic.calibrator = hierarchical_calibrator
    hierarchical_eval_raw, _ = _predict_hierarchical_logistic_raw(
        hierarchical_logistic,
        features.iloc[eval_idx],
        metadata.iloc[eval_idx].reset_index(drop=True),
    )
    hierarchical_eval = hierarchical_eval_raw.copy()
    if hierarchical_calibrator is not None and len(test_idx):
        hierarchical_eval = hierarchical_calibrator.transform(hierarchical_eval)
    metrics["logistic_hierarchical"] = classification_metrics(labels[eval_idx], hierarchical_eval)

    print("Training hist GBM model...", file=sys.stderr, flush=True)
    tree_classifier = baselines.tree_classifier.fit(features.iloc[train_idx], labels[train_idx])
    tree_valid_raw = tree_classifier.predict_proba(features.iloc[valid_idx])[:, 1]
    metrics["hist_gbm_valid"] = classification_metrics(labels[valid_idx], tree_valid_raw)
    _, tree_calibrator = _identity_or_calibrated(tree_valid_raw, labels[valid_idx])
    tree_eval = tree_classifier.predict_proba(features.iloc[eval_idx])[:, 1]
    if tree_calibrator is not None and len(test_idx):
        tree_eval = tree_calibrator.transform(tree_eval)
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
    _cal = lambda raw, cal: cal.transform(raw) if cal is not None else raw  # noqa: E731
    ensemble_eval = (
        np.stack([
            _cal(logistic_eval, logistic_calibrator if len(test_idx) else None),
            _cal(coastal_eval, coastal_calibrator if len(test_idx) else None),
            _cal(hierarchical_eval, hierarchical_calibrator if len(test_idx) else None),
            _cal(tree_eval, tree_calibrator if len(test_idx) else None),
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

    model_types_to_run = list(SEQUENCE_MODEL_NAMES) if model_type == "all" else [model_type]
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
    if spatial_strategy == "shortlist":
        spatial_backtest_models = plan.spatial_backtest_models

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
                beach_group_limit=spatial_beach_limit,
                county_group_limit=spatial_county_limit,
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
    regression_interval_half_width = _split_conformal_half_width(
        densities[valid_idx],
        regressor_valid_predictions,
    )

    history, forecast_candidates = _build_forecast_candidates(
        frame, stations, uv_daily, forecast_date, full_frame=full_frame
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
            ]
        ),
        on="beach_id",
        how="left",
    ) if not forecast_metadata.empty else pd.DataFrame()
    scopes = np.full(len(baseline_forecast_features), "global", dtype=object)
    assigned_cells = np.full(len(baseline_forecast_features), "unknown", dtype=object)
    if winner == "stacked_ensemble":
        _ens_logistic = logistic.predict_proba(baseline_forecast_features)[:, 1]
        if logistic_calibrator is not None:
            _ens_logistic = logistic_calibrator.transform(_ens_logistic)
        _ens_coastal, _, _ens_coastal_scopes = _predict_coastal_cell_logistic_raw(
            coastal_cell_logistic, baseline_forecast_features, forecast_group_metadata,
        )
        if coastal_cell_logistic.calibrator is not None:
            _ens_coastal = coastal_cell_logistic.calibrator.transform(_ens_coastal)
        _ens_hier, _ens_hier_scopes = _predict_hierarchical_logistic_raw(
            hierarchical_logistic, baseline_forecast_features, forecast_group_metadata,
        )
        if hierarchical_logistic.calibrator is not None:
            _ens_hier = hierarchical_logistic.calibrator.transform(_ens_hier)
        _ens_tree = tree_classifier.predict_proba(baseline_forecast_features)[:, 1]
        if tree_calibrator is not None:
            _ens_tree = tree_calibrator.transform(_ens_tree)
        probabilities = (
            np.stack([_ens_logistic, _ens_coastal, _ens_hier, _ens_tree], axis=1)
            @ ensemble_weights
        )
        scopes = _ens_hier_scopes
    elif winner == "logistic_coastal_cells":
        probabilities, assigned_cells, scopes = _predict_coastal_cell_logistic_raw(
            coastal_cell_logistic,
            baseline_forecast_features,
            forecast_group_metadata,
        )
        if coastal_cell_logistic.calibrator is not None:
            probabilities = coastal_cell_logistic.calibrator.transform(probabilities)
    elif winner == "logistic_hierarchical":
        probabilities, scopes = _predict_hierarchical_logistic_raw(
            hierarchical_logistic,
            baseline_forecast_features,
            forecast_group_metadata,
        )
        if hierarchical_logistic.calibrator is not None:
            probabilities = hierarchical_logistic.calibrator.transform(probabilities)
    else:
        probabilities = classifier.predict_proba(baseline_forecast_features)[:, 1]
        if calibrator is not None:
            probabilities = calibrator.transform(probabilities)
    density_predictions = regressor.predict(baseline_forecast_features)
    # ── Risk-distribution sanity guard ──────────────────────────────────────
    # A degenerate calibrator (e.g. trained on all-null env features) can push
    # p_exceed to exactly 1.00 for most beaches, producing an implausible
    # distribution like 41% Very High.  risk_band() maps p >= 0.70 → Very High,
    # so we clamp to 0.69 — the highest value still in the High band — which
    # redistributes the hard-1.0 mass while preserving relative ranking.
    _VERY_HIGH_THRESHOLD = 0.70  # must match risk_band() definition
    _MAX_VERY_HIGH_FRACTION = 0.30
    if len(probabilities) > 0:
        very_high_fraction = float((probabilities >= _VERY_HIGH_THRESHOLD).mean())
        if very_high_fraction > _MAX_VERY_HIGH_FRACTION:
            print(
                f"[sanity guard] {very_high_fraction:.1%} of beaches at Very High "
                f"(threshold {_MAX_VERY_HIGH_FRACTION:.0%}); clamping p_exceed to 0.69.",
                file=sys.stderr,
                flush=True,
            )
            probabilities = np.clip(probabilities, 0.0, 0.69)
    # ─────────────────────────────────────────────────────────────────────────
    # Driver computation always uses hist_gbm (individual-beach sensitivity).
    # logistic_hierarchical outputs cluster-level probs — zeroing one beach's
    # features barely moves it, so drivers would all be the stub fallback if
    # we used the hierarchical probs as the baseline.  Using hist_gbm probs for
    # BOTH baseline and perturbation gives a self-consistent diff.
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
    if not forecast_metadata.empty:
        forecast_generated_at = datetime.now(UTC).isoformat()
        for i, (idx, probability, density_prediction, scope) in enumerate(zip(
            forecast_metadata.index,
            probabilities,
            density_predictions,
            scopes,
            strict=False,
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
            forecasts.append(
                {
                    "beach_id": beach_id,
                    "forecast_date": forecast_date.isoformat(),
                    "risk_band": risk_band(float(probability)),
                    "p_exceed": float(probability),
                    "predicted_log_enterococcus": float(density_prediction),
                    "lower_prediction_interval": (
                        float(density_prediction - regression_interval_half_width)
                        if regression_interval_half_width is not None
                        else None
                    ),
                    "upper_prediction_interval": (
                        float(density_prediction + regression_interval_half_width)
                        if regression_interval_half_width is not None
                        else None
                    ),
                    "prediction_interval_level": (
                        0.9 if regression_interval_half_width is not None else None
                    ),
                    "top_drivers": computed_drivers[i],
                    "model_version": _forecast_model_version(winner, str(scope)),
                    "forecast_generated_at": forecast_generated_at,
                    "wave_height_m": _safe_float(latest_row.get("wave_height_m")) if latest_row is not None else None,
                    "dominant_period_s": _safe_float(latest_row.get("dominant_period_s")) if latest_row is not None else None,
                    "water_temperature_c": _safe_float(latest_row.get("water_temperature_c")) if latest_row is not None else None,
                    "salinity_psu": _safe_float(latest_row.get("salinity_psu")) if latest_row is not None else None,
                    "uv_index": uv_index,
                    "uv_alert": uv_alert,
                }
            )

    pd.DataFrame(forecasts).to_parquet(curated_dir / "forecasts.parquet", index=False)

    health_path = curated_dir / "system_health.json"
    health_payload = json.loads(health_path.read_text()) if health_path.exists() else {}
    promotion = _promotion_assessment(metrics, winner)
    health_payload["model_registry"] = {
        "production_model": _registry_model_version(winner),
        "temporal_validation_winner": _registry_model_version(plan.research_winner),
        "candidate_models": [
            _registry_model_version(model_name) for model_name in PRODUCTION_MODEL_NAMES
        ],
        "research_models": [_registry_model_version(model_name) for model_name in model_types_to_run],
        "spatial_backtest_models": [_registry_model_version(model_name) for model_name in spatial_backtest_models],
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
    return TrainingArtifacts(winner=winner, metrics=metrics)


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
    parser.add_argument("--model", type=str, default="tcn", choices=["tcn", "cnn", "lstm", "transformer", "pinn", "all"])
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
    )
    print(json.dumps(asdict(artifacts), indent=2))


if __name__ == "__main__":
    main()
