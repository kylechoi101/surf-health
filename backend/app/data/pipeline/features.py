from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


WINDOW_DAYS = 30
LAGS = (1, 2, 3, 7, 14, 21, 28)
BASE_NUMERIC_COLUMNS = [
    "enterococcus_value",
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

HYDROLOGY_NUMERIC_COLUMNS = [
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
]

PROSPECTIVE_EXOGENOUS_COLUMNS = [
    column for column in BASE_NUMERIC_COLUMNS if column != "enterococcus_value"
]

ROLLING_COLUMNS = [
    "wave_height_m",
    "salinity_psu",
    "water_temperature_c",
    "uv_index",
    "tidal_height",
    "surf_height_observed",
    "turbidity_observed",
]

SPATIAL_NUMERIC_COLUMNS = [
    "latitude",
    "longitude",
    "historical_advisory_count",
    "cdip_distance_km",
    "erddap_distance_km",
    "distance_to_pour_point_km",
    "distance_to_gage_km",
    "watershed_area_km2",
]


@dataclass
class SlidingWindowDataset:
    feature_frame: pd.DataFrame
    sequence_array: np.ndarray
    targets_exceed: np.ndarray
    targets_log_density: np.ndarray
    metadata: pd.DataFrame


@dataclass
class InferenceWindowDataset:
    feature_frame: pd.DataFrame
    sequence_array: np.ndarray
    metadata: pd.DataFrame


@dataclass
class InferenceFeatureDataset:
    feature_frame: pd.DataFrame
    metadata: pd.DataFrame


def _spatial_context_features(enriched: pd.DataFrame) -> pd.DataFrame:
    frame = pd.DataFrame(index=enriched.index)
    latitude = pd.to_numeric(enriched.get("latitude"), errors="coerce")
    longitude = pd.to_numeric(enriched.get("longitude"), errors="coerce")
    historical_advisories = pd.to_numeric(enriched.get("historical_advisory_count"), errors="coerce")
    cdip_distance = pd.to_numeric(enriched.get("cdip_distance_km"), errors="coerce")
    erddap_distance = pd.to_numeric(enriched.get("erddap_distance_km"), errors="coerce")

    frame["coastal_x_km"] = longitude * np.cos(np.radians(latitude)) * 111.32
    frame["coastal_y_km"] = latitude * 110.57
    frame["historical_advisory_count_log1p"] = np.log1p(historical_advisories.clip(lower=0))
    frame["cdip_distance_km_log1p"] = np.log1p(cdip_distance.clip(lower=0))
    frame["erddap_distance_km_log1p"] = np.log1p(erddap_distance.clip(lower=0))
    frame["has_cdip_sensor"] = enriched.get("cdip_station_id").notna().astype(int)
    frame["has_erddap_sensor"] = enriched.get("erddap_source_name").notna().astype(int)
    return frame


def _exact_lag_features(enriched: pd.DataFrame) -> pd.DataFrame:
    lag_source = enriched[["beach_id", "sample_date", *BASE_NUMERIC_COLUMNS]].copy()
    feature_frame = enriched[["beach_id", "sample_date"]].copy()
    for lag in LAGS:
        shifted = lag_source.copy()
        shifted["sample_date"] = shifted["sample_date"] + pd.to_timedelta(lag, unit="D")
        shifted = shifted.rename(
            columns={column: f"{column}_lag_{lag}" for column in BASE_NUMERIC_COLUMNS}
        )
        feature_frame = feature_frame.merge(shifted, on=["beach_id", "sample_date"], how="left")
    return feature_frame.drop(columns=["beach_id", "sample_date"])


def _rolling_and_spacing_features(enriched: pd.DataFrame) -> pd.DataFrame:
    feature_frames: list[pd.DataFrame] = []
    for _, group in enriched.groupby("beach_id", sort=False):
        group = group.sort_values("sample_date").copy()
        sample_dates = pd.DatetimeIndex(pd.to_datetime(group["sample_date"], errors="coerce"))
        sample_date_series = pd.Series(sample_dates, index=group.index)

        feature_map: dict[str, pd.Series] = {
            "days_since_previous_sample": sample_date_series.diff().dt.days
        }
        for column in ROLLING_COLUMNS:
            values = pd.to_numeric(group[column], errors="coerce")
            time_series = pd.Series(values.to_numpy(), index=sample_dates, dtype=float)
            mean_7d = time_series.rolling("7D", min_periods=1, closed="left").mean()
            feature_map[f"{column}_mean_7d"] = pd.Series(mean_7d.to_numpy(), index=group.index)
            feature_map[f"{column}_std_7d"] = pd.Series(
                time_series.rolling("7D", min_periods=2, closed="left").std().to_numpy(),
                index=group.index,
            )
            mean_30d = time_series.rolling("30D", min_periods=1, closed="left").mean()
            feature_map[f"{column}_mean_30d"] = pd.Series(mean_30d.to_numpy(), index=group.index)
            feature_map[f"{column}_trend_7d"] = pd.Series(
                (mean_7d - mean_30d).to_numpy(),
                index=group.index,
            )

        for column in BASE_NUMERIC_COLUMNS:
            col_values = pd.to_numeric(group[column], errors="coerce")
            observed_dates = (
                sample_date_series.where(col_values.notna())
                .shift(1)
                .ffill()
            )
            feature_map[f"days_since_{column}_obs"] = (
                sample_date_series - observed_dates
            ).dt.days
            # Last observed value before this row (avoids leaking current reading).
            # Non-null for any beach with at least one prior sample.
            feature_map[f"{column}_last_obs"] = col_values.shift(1).ffill()

        feature_frames.append(pd.DataFrame(feature_map, index=group.index))

    return pd.concat(feature_frames).reindex(enriched.index) if feature_frames else pd.DataFrame()


def add_temporal_features(frame: pd.DataFrame) -> pd.DataFrame:
    enriched = frame.copy()
    missing_base_columns = {
        column: np.nan for column in BASE_NUMERIC_COLUMNS if column not in enriched.columns
    }
    if missing_base_columns:
        enriched = enriched.assign(**missing_base_columns)
    missing_spatial_columns = {
        column: np.nan for column in SPATIAL_NUMERIC_COLUMNS if column not in enriched.columns
    }
    if missing_spatial_columns:
        enriched = enriched.assign(**missing_spatial_columns)
    missing_hydro = {
        column: np.nan for column in HYDROLOGY_NUMERIC_COLUMNS if column not in enriched.columns
    }
    if missing_hydro:
        enriched = enriched.assign(**missing_hydro)

    for column in ("county", "region", "cdip_station_id", "erddap_source_name"):
        if column not in enriched.columns:
            enriched[column] = pd.Series([None] * len(enriched), index=enriched.index, dtype="object")
    enriched["sample_date"] = pd.to_datetime(enriched["sample_date"])

    seasonal_features = pd.DataFrame(
        {
            "day_of_year": enriched["sample_date"].dt.dayofyear,
            "sin_doy": np.sin(2 * np.pi * enriched["sample_date"].dt.dayofyear / 365.25),
            "cos_doy": np.cos(2 * np.pi * enriched["sample_date"].dt.dayofyear / 365.25),
            "log_enterococcus": np.log10(enriched["enterococcus_value"].clip(lower=1)),
        },
        index=enriched.index,
    )

    lagged_features = _exact_lag_features(enriched)
    rolling_features = _rolling_and_spacing_features(enriched)

    missing_indicators = pd.DataFrame(
        {f"{column}_missing": enriched[column].isna().astype(int) for column in BASE_NUMERIC_COLUMNS},
        index=enriched.index,
    )

    return pd.concat(
        [
            enriched,
            seasonal_features,
            lagged_features,
            rolling_features,
            missing_indicators,
        ],
        axis=1,
    )


def _model_feature_columns(enriched: pd.DataFrame) -> list[str]:
    feature_columns = [
        column
        for column in enriched.columns
        if column
        not in {
            "beach_id",
            "county",
            "region",
            "sample_date",
            "sample_time",
            "exceeds_stv",
            "wave_direction_deg",
            "latitude",
            "longitude",
            "historical_advisory_count",
            "cdip_distance_km",
            "erddap_distance_km",
            "cdip_station_id",
            "erddap_source_name",
        }
    ]
    raw_current_columns = set(PROSPECTIVE_EXOGENOUS_COLUMNS)
    feature_columns = [column for column in feature_columns if column not in raw_current_columns]
    feature_columns = [column for column in feature_columns if not column.endswith("_missing")]
    for leaked_target_column in ("enterococcus_value", "log_enterococcus"):
        if leaked_target_column in feature_columns:
            feature_columns.remove(leaked_target_column)
    return feature_columns


def _calendar_aligned_history(
    history: pd.DataFrame,
    target_date: pd.Timestamp,
) -> np.ndarray | None:
    if history.empty:
        return None
    day_offsets = (target_date - history["sample_date"]).dt.days
    recent_history = history.loc[day_offsets.between(1, WINDOW_DAYS)].copy()
    if len(recent_history) < min(3, WINDOW_DAYS):
        return None
    offsets = (target_date - recent_history["sample_date"]).dt.days.astype(int).to_numpy()
    numeric_slice = (
        recent_history[BASE_NUMERIC_COLUMNS].fillna(0.0).to_numpy(dtype=np.float32, copy=True)
    )
    padded = np.zeros((WINDOW_DAYS, len(BASE_NUMERIC_COLUMNS)), dtype=np.float32)
    for offset, values in zip(offsets, numeric_slice, strict=False):
        padded[WINDOW_DAYS - offset] = values
    return padded


def build_sliding_windows(frame: pd.DataFrame) -> SlidingWindowDataset:
    enriched = add_temporal_features(frame)
    feature_columns = _model_feature_columns(enriched)
    sequences: list[np.ndarray] = []
    rows: list[pd.Series] = []
    targets_exceed: list[float] = []
    targets_log_density: list[float] = []
    metadata_rows: list[dict] = []

    for beach_id, beach_frame in enriched.groupby("beach_id"):
        beach_frame = beach_frame.sort_values("sample_date").reset_index(drop=True)
        for idx in range(len(beach_frame)):
            if pd.isna(beach_frame.loc[idx, "exceeds_stv"]):
                continue
            target_date = pd.to_datetime(beach_frame.loc[idx, "sample_date"])
            history = beach_frame.iloc[:idx]
            padded = _calendar_aligned_history(history, target_date)
            if padded is None:
                continue
            sequences.append(padded)
            rows.append(beach_frame.loc[idx, feature_columns])
            metadata_rows.append(
                {
                    "beach_id": beach_id,
                    "sample_date": beach_frame.loc[idx, "sample_date"],
                }
            )
            targets_exceed.append(float(beach_frame.loc[idx, "exceeds_stv"]))
            targets_log_density.append(float(beach_frame.loc[idx, "log_enterococcus"]))

    feature_frame = pd.DataFrame(rows).reset_index(drop=True)
    metadata = pd.DataFrame(metadata_rows)
    return SlidingWindowDataset(
        feature_frame=feature_frame,
        sequence_array=np.stack(sequences) if sequences else np.empty((0, WINDOW_DAYS, 0)),
        targets_exceed=np.array(targets_exceed, dtype=np.float32),
        targets_log_density=np.array(targets_log_density, dtype=np.float32),
        metadata=metadata,
    )


def build_inference_windows(frame: pd.DataFrame) -> InferenceWindowDataset:
    enriched = add_temporal_features(frame)
    feature_columns = _model_feature_columns(enriched)
    sequences: list[np.ndarray] = []
    rows: list[pd.Series] = []
    metadata_rows: list[dict] = []

    for beach_id, beach_frame in enriched.groupby("beach_id"):
        beach_frame = beach_frame.sort_values("sample_date").reset_index(drop=True)
        for idx in range(len(beach_frame)):
            if pd.notna(beach_frame.loc[idx, "exceeds_stv"]):
                continue
            target_date = pd.to_datetime(beach_frame.loc[idx, "sample_date"])
            history = beach_frame.iloc[:idx]
            padded = _calendar_aligned_history(history, target_date)
            if padded is None:
                continue
            sequences.append(padded)
            rows.append(beach_frame.loc[idx, feature_columns])
            metadata_rows.append(
                {
                    "beach_id": beach_id,
                    "sample_date": beach_frame.loc[idx, "sample_date"],
                }
            )

    feature_frame = pd.DataFrame(rows).reset_index(drop=True)
    metadata = pd.DataFrame(metadata_rows)
    return InferenceWindowDataset(
        feature_frame=feature_frame,
        sequence_array=np.stack(sequences) if sequences else np.empty((0, WINDOW_DAYS, 0)),
        metadata=metadata,
    )


def build_inference_features(frame: pd.DataFrame) -> InferenceFeatureDataset:
    enriched = add_temporal_features(frame)
    feature_columns = _model_feature_columns(enriched)
    unlabeled = enriched.loc[enriched["exceeds_stv"].isna()].copy()
    return InferenceFeatureDataset(
        feature_frame=unlabeled[feature_columns].reset_index(drop=True),
        metadata=unlabeled[["beach_id", "sample_date"]].reset_index(drop=True),
    )
