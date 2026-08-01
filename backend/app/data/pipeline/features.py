from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.data.pipeline.stormwater import STORMWATER_NUMERIC_COLUMNS


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
    # First-rain-after-dry-spell feature (Hermes, 5-Opus+Sonnet council winner
    # 2026-05-19): captures disproportionate bacterial loading from impervious-
    # surface accumulation flushed by the first rain event after a dry spell.
    # Computed in app.data.pipeline.precipitation.compute_first_rain_score.
    "first_rain_score",
]

# Marine-microbiology features — captures UV inactivation, plume transport,
# point-source proximity. Populated by --with-solar-wind in the curation CLI.
MARINE_MICROBIOLOGY_NUMERIC_COLUMNS = [
    "shore_normal_wind_ms",         # +ve = onshore, compresses plume; -ve = offshore, disperses
    "solar_inactivation_index",     # shortwave × (1 - cloud%) — UV decay strength
    "cloud_cover_24h_mean",
    "shortwave_24h_sum",
    "uv_index_24h_max",
    "wind_speed_24h_max",
    "days_since_sunny",              # capped at 30
    "dist_to_pier_km",
    "dist_to_estuary_km",
    "is_near_pier",
    "is_near_estuary_mouth",
]

# Explicit storm-drain/outfall and expert rain-policy features populated by
# app.data.pipeline.stormwater.
STORMWATER_EXPERT_NUMERIC_COLUMNS = STORMWATER_NUMERIC_COLUMNS

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

# Regulatory geomean features. California Health & Safety Code §115880 issues a
# Bacterial Standards Violation posting when the rolling 30-day geometric mean
# of enterococcus exceeds 35 MPN/100mL, or any single sample exceeds 104.
# Computing the agency's own posting trigger as a feature is the most directly
# causally-correct signal we can give the model for the chronic-advisory pool.
# All columns are strictly lagged (closed='left') — the same-day sample is
# never in the rolling window, so there is no leakage of the prediction target.
REGULATORY_GEOMEAN_COLUMNS = [
    "enterococcus_geomean_30d_lagged",
    "enterococcus_geomean_42d_lagged",
    "geomean_30d_exceeds_35_lagged",
    "geomean_30d_exceeds_104_lagged",
    "geomean_42d_exceeds_35_lagged",
    "samples_in_geomean_30d_lagged",
]
_GEOMEAN_THRESHOLD_LOG10 = {
    35: float(np.log10(35)),
    104: float(np.log10(104)),
}


# ---------------------------------------------------------------------------
# San Diego boundary-condition cohort flags.
#
# Research lineage:
#   docs/superpowers/plans/2026-05-09-unstable-beaches-action-plan.md
#   docs/superpowers/plans/2026-05-10-san-diego-boundary-features.md
#
# Static, explicit beach-id mapping. We intentionally avoid loose name-matching
# because the model is allowed to learn a per-cohort prior and we must not
# accidentally flag beaches outside the documented research footprint.
#
# Cohort definitions:
#   SOUTH_SD: Imperial Beach, Coronado, Silver Strand — chronic Tijuana River /
#     Punta Bandera transboundary sewage exposure; northward summer transport
#     from south swells; daily-testing surveillance bias; dry-weather dominant
#     contamination. (IBWC + SCCOOS, ref: 2026-05-09 unstable-beaches plan §1.A.)
#   OCEANSIDE_PROTECTED: Oceanside municipal + Buccaneer — Loma Alta Creek UV
#     treatment facility (~700 gpm dry-weather sterilization) + 4.5-mile deep
#     ocean outfall. (Ref: 2026-05-09 unstable-beaches plan §1.B Oceanside.)
#   CARDIFF_LAGOON_BARRIER: Cardiff State Beach — San Elijo Lagoon inlet
#     frequently closes from sand accumulation, severing the rain → coast
#     pollution chain. (Ref: 2026-05-09 unstable-beaches plan §1.B Cardiff.)
# ---------------------------------------------------------------------------
_SOUTH_SD_BEACH_ID_PREFIXES: tuple[str, ...] = (
    "ca068221-san-diego-imperial-beach",          # Imperial Beach municipal beach
    "ca432983-san-diego-imperial-beach-pier-area",
    "ca134387-san-diego-north-imperial-beach",
    "ca204955-san-diego-coronado-city-beaches",
    "ca604254-san-diego-coronado-north-beach",
    "ca125172-san-diego-coronado-cays",
    "ca801475-san-diego-silver-strand-state-beach",
)

_OCEANSIDE_PROTECTED_BEACH_ID_PREFIXES: tuple[str, ...] = (
    "ca333308-san-diego-oceanside-municipal-beach",
    "ca976061-san-diego-buccaneer-beach",
)

_CARDIFF_LAGOON_BEACH_ID_PREFIXES: tuple[str, ...] = (
    "ca152716-san-diego-cardiff-state-beach",
)

SD_BOUNDARY_FLAG_COLUMNS: list[str] = [
    # Group A — south SD, Tijuana plume cohort.
    "transboundary_sewage_exposure_flag",   # IBWC transboundary sewage exposure
    "south_swell_sensitive_flag",            # SCCOOS south-swell northward transport
    "dry_weather_contamination_zone_flag",   # chronic Punta Bandera dry-weather flow
    # Group B — engineered north-county protection cohort.
    "engineered_runoff_protection_flag",     # Loma Alta UV facility + deep outfall
    "uv_treatment_protected_flag",           # Loma Alta Creek UV plant
    "lagoon_mouth_barrier_flag",             # San Elijo Lagoon inlet closure
]

SD_BOUNDARY_INTERACTION_COLUMNS: list[str] = [
    # Dry-weather sewage dominance: high when sewage exposure is on AND it has
    # NOT rained. Captures the Punta Bandera continuous-discharge regime.
    "south_sewage_dry_weather_interaction",
    # Diagnostic proxy: month is a transparent stand-in for true south-swell
    # direction telemetry. May–Oct (NH summer) tags the peak south-swell window
    # documented by SCCOOS HFR. Not a physical observation.
    "south_swell_season_interaction",
    # Softens rain-driven risk inflation at engineered/UV-protected beaches.
    "protected_north_rain_interaction",
    # Decouples Cardiff from rain when the inlet is closed. True inlet telemetry
    # is not available, so this is a proxy keyed off the static cohort flag.
    "cardiff_lagoon_rain_interaction",
    # ---- Regime-resolved south-SD plume features ------------------------------
    # Source: Kim, Terrill & Cornuelle, "Assessing Coastal Plumes in a Region of
    # Multiple Discharges: The U.S.-Mexico Border", Environ. Sci. Technol. 2009,
    # 43, 7450-7457. The hindcast separates three discharges with distinct
    # triggers; we encode each as its own signal so the model no longer sees
    # three identical static flags for one collapsed regime.
    #
    # Alongshore (upcoast/northward) wind for the south cohort. +ve pushes plume
    # water toward Imperial Beach / Coronado — the paper's dominant advection
    # mechanism (currents head north in 80%+ of rain events). Wind-derived proxy
    # for the HF-radar surface currents the paper used; we don't have those.
    "south_alongshore_wind_ms",
    # TJR (Tijuana River) regime: rain-driven, wet-season, multi-day plume tail
    # (source active ~7 days post-rain). Distinct from the dry-weather term below.
    "tjr_wet_plume_interaction",
    # SBO (South Bay Ocean Outfall) regime: the submerged plume only contaminates
    # the coast when weak stratification lets it surface — a winter (418 days)
    # vs summer (2 days) phenomenon driven by wind mixing. Diagnostic proxy.
    "sbo_weak_stratification_interaction",
]


def _starts_with_any(value: str, prefixes: tuple[str, ...]) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return value.startswith(prefixes)


def _sd_boundary_features(enriched: pd.DataFrame) -> pd.DataFrame:
    """Apply the static SD boundary-cohort flags and the documented physical
    interactions. Returns a frame indexed like ``enriched``.
    """
    beach_ids = enriched["beach_id"].astype("string").fillna("")
    is_south = beach_ids.map(lambda v: _starts_with_any(v, _SOUTH_SD_BEACH_ID_PREFIXES))
    is_oceanside_protected = beach_ids.map(
        lambda v: _starts_with_any(v, _OCEANSIDE_PROTECTED_BEACH_ID_PREFIXES)
    )
    is_cardiff = beach_ids.map(lambda v: _starts_with_any(v, _CARDIFF_LAGOON_BEACH_ID_PREFIXES))

    south_flag = is_south.astype(int)
    protected_flag = is_oceanside_protected.astype(int)
    cardiff_flag = is_cardiff.astype(int)

    # Dry-weather normalization: 1 - clip(precip_24h / 50mm, 0, 1). A 50mm/24h
    # day is treated as the "definitely a storm" anchor; lower-than-50mm rainfall
    # still has some dry-weather residual. Tuning is intentionally coarse — the
    # signal is "is this a dry day or not?" rather than a fine-grained dose.
    precip_24h = pd.to_numeric(enriched.get("precip_mm_24h"), errors="coerce").fillna(0.0).clip(lower=0.0)
    dryness = (1.0 - (precip_24h / 50.0)).clip(lower=0.0, upper=1.0)

    sample_dates = pd.to_datetime(enriched["sample_date"], errors="coerce")
    month = sample_dates.dt.month.fillna(0).astype(int)
    is_summer = month.between(5, 10).astype(int)
    # Wet (rainy) season is the complement of the south-swell summer window —
    # Nov-Apr in SoCal, when the Tijuana River runs and the SBO plume surfaces.
    is_wet_season = (1 - is_summer).astype(int)

    def _num(col: str) -> pd.Series:
        """Numeric column coerced to a 0-filled float Series. Returns all-zeros
        when the column is absent so the feature degrades gracefully on frames
        (or non-SD rows) that lack the upstream solar-wind covariates."""
        if col in enriched:
            return pd.to_numeric(enriched[col], errors="coerce").fillna(0.0)
        return pd.Series(0.0, index=enriched.index)

    # Northward (upcoast) wind component, m/s. Met convention: wind_direction is
    # the direction the wind blows FROM, so the toward-vector's north component
    # is -speed * cos(dir). A southerly wind (FROM 180°) yields +ve = transport
    # toward Imperial Beach / Coronado.
    wind_speed = _num("wind_speed_24h_max")
    wind_dir_rad = np.deg2rad(_num("wind_direction_24h_mean"))
    northward_wind = -wind_speed * np.cos(wind_dir_rad)

    # TJR rain-driven plume: normalize a multi-day rain accumulation (3-day
    # window approximates the post-rain plume tail). 100 mm / 72 h anchors a
    # major storm.
    precip_72h = _num("precip_mm_72h")
    rain_norm = (precip_72h / 100.0).clip(lower=0.0, upper=1.0)

    # Weak-stratification proxy for SBO surfacing: wind mixing breaks down the
    # density trap. 10 m/s anchors strong mixing.
    mixing_norm = (wind_speed / 10.0).clip(lower=0.0, upper=1.0)

    south_float = south_flag.astype(float)

    frame = pd.DataFrame(
        {
            "transboundary_sewage_exposure_flag": south_flag,
            "south_swell_sensitive_flag": south_flag,
            "dry_weather_contamination_zone_flag": south_flag,
            "engineered_runoff_protection_flag": protected_flag,
            "uv_treatment_protected_flag": protected_flag,
            "lagoon_mouth_barrier_flag": cardiff_flag,
            "south_sewage_dry_weather_interaction": (south_flag.astype(float) * dryness).astype(float),
            "south_swell_season_interaction": (south_flag * is_summer).astype(int),
            "protected_north_rain_interaction": (protected_flag.astype(float) * precip_24h).astype(float),
            "cardiff_lagoon_rain_interaction": (cardiff_flag.astype(float) * precip_24h).astype(float),
            "south_alongshore_wind_ms": (south_float * northward_wind).astype(float),
            "tjr_wet_plume_interaction": (south_float * is_wet_season * rain_norm).astype(float),
            "sbo_weak_stratification_interaction": (
                south_float * is_wet_season * mixing_norm
            ).astype(float),
        },
        index=enriched.index,
    )
    return frame


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

    # Tijuana River plume zone (San Diego County).
    #
    # The CalState advisory feed includes multi-year administrative postings
    # around the Tijuana River estuary. A simple geographic indicator helps the
    # model learn a chronic-source prior without leaking advisories.
    #
    # Bounding box is intentionally coarse (south SD coast).
    tj_zone = (
        latitude.notna()
        & longitude.notna()
        & (latitude <= 32.66)
        & (longitude >= -117.30)
        & (longitude <= -116.90)
    )
    frame["is_tijuana_plume_zone"] = tj_zone.astype(int)
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
    # .merge() discards the caller's index for a fresh RangeIndex.  add_temporal_features
    # combines this block with `enriched` via pd.concat(axis=1), which aligns on index —
    # so whenever `enriched` has a non-contiguous index (any .loc[mask] filter, e.g. the
    # training-window cut in training.py) the two UNION instead of aligning and every
    # *_lag_* column silently lands on the wrong row.  Restore the caller's index, the
    # same guard _rolling_and_spacing_features and _regulatory_geomean_features already use.
    return feature_frame.drop(columns=["beach_id", "sample_date"]).set_index(enriched.index)


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

        # Last observed EXCEEDANCE before this row. Same shift(1).ffill() rule as
        # the *_last_obs values above, so it is forecast-safe in the identical way.
        #
        # This exists because `enterococcus_value` is not comparable across rows:
        # San Diego ddPCR reports copies/100mL (threshold 1413) while culture
        # methods report MPN/CFU (threshold 104), and beach_day carries no
        # method/units column to tell them apart — 84 beaches report BOTH ways.
        # `exceeds_stv` was already decided per-sample by the method-aware
        # exceedance.compute_exceeds_stv, so carrying the decision forward is the
        # only correct "what did we see last time" signal. Re-thresholding the raw
        # value (the old persistence baseline) judged copy counts against 104.
        exceedance = pd.to_numeric(group["exceeds_stv"], errors="coerce")
        feature_map["exceeds_stv_last_obs"] = exceedance.shift(1).ffill()

        feature_frames.append(pd.DataFrame(feature_map, index=group.index))

    return pd.concat(feature_frames).reindex(enriched.index) if feature_frames else pd.DataFrame()


def _regulatory_geomean_features(enriched: pd.DataFrame) -> pd.DataFrame:
    """Per-station rolling 30/42-day geometric means of enterococcus, strictly lagged.

    California's Bacterial Standards Violation posting trigger is the regulator-defined
    operational signal we want the model to mirror. Each row gets the geomean of all
    *prior* samples (closed='left'), so the same-day sample is never in the window —
    no leakage of the prediction target.

    Sub-detection samples are clipped to 1 MPN/100mL (== log10 = 0) before averaging,
    matching the convention used for `log_enterococcus` elsewhere in the pipeline.
    """
    feature_frames: list[pd.DataFrame] = []
    threshold_35 = _GEOMEAN_THRESHOLD_LOG10[35]
    threshold_104 = _GEOMEAN_THRESHOLD_LOG10[104]

    for _, group in enriched.groupby("beach_id", sort=False):
        group = group.sort_values("sample_date").copy()
        sample_dates = pd.DatetimeIndex(pd.to_datetime(group["sample_date"], errors="coerce"))
        ent_values = pd.to_numeric(group["enterococcus_value"], errors="coerce")
        log_ent = np.log10(ent_values.clip(lower=1.0))
        log_ent_series = pd.Series(log_ent.to_numpy(), index=sample_dates, dtype=float)

        feature_map: dict[str, pd.Series] = {}

        log_mean_30d = log_ent_series.rolling("30D", min_periods=2, closed="left").mean()
        sample_count_30d = log_ent_series.rolling("30D", min_periods=1, closed="left").count()
        log_mean_42d = log_ent_series.rolling("42D", min_periods=2, closed="left").mean()

        feature_map["enterococcus_geomean_30d_lagged"] = pd.Series(
            (10.0 ** log_mean_30d).to_numpy(), index=group.index
        )
        feature_map["enterococcus_geomean_42d_lagged"] = pd.Series(
            (10.0 ** log_mean_42d).to_numpy(), index=group.index
        )
        feature_map["geomean_30d_exceeds_35_lagged"] = pd.Series(
            (log_mean_30d >= threshold_35).astype(float).to_numpy(), index=group.index
        )
        feature_map["geomean_30d_exceeds_104_lagged"] = pd.Series(
            (log_mean_30d >= threshold_104).astype(float).to_numpy(), index=group.index
        )
        feature_map["geomean_42d_exceeds_35_lagged"] = pd.Series(
            (log_mean_42d >= threshold_35).astype(float).to_numpy(), index=group.index
        )
        feature_map["samples_in_geomean_30d_lagged"] = pd.Series(
            sample_count_30d.to_numpy(), index=group.index
        )

        feature_frames.append(pd.DataFrame(feature_map, index=group.index))

    if not feature_frames:
        return pd.DataFrame(index=enriched.index, columns=REGULATORY_GEOMEAN_COLUMNS, dtype=float)

    result = pd.concat(feature_frames).reindex(enriched.index)
    # NaN means "not enough prior samples to compute a geomean". Treat that as "no
    # historical exceedance signal" rather than a feature-imputation surprise.
    for column in REGULATORY_GEOMEAN_COLUMNS:
        if column not in result.columns:
            result[column] = 0.0
    return result


def _distributed_lag_hydrology_features(enriched: pd.DataFrame) -> pd.DataFrame:
    frame = pd.DataFrame(index=enriched.index)
    precip_6h = pd.to_numeric(enriched["precip_mm_6h"], errors="coerce").fillna(0.0).clip(lower=0)
    precip_24h = pd.to_numeric(enriched["precip_mm_24h"], errors="coerce").fillna(0.0).clip(lower=0)
    precip_48h = pd.to_numeric(enriched["precip_mm_48h"], errors="coerce").fillna(0.0).clip(lower=0)
    precip_72h = pd.to_numeric(enriched["precip_mm_72h"], errors="coerce").fillna(0.0).clip(lower=0)
    precip_7d = pd.to_numeric(enriched["precip_mm_7d"], errors="coerce").fillna(0.0).clip(lower=0)

    increment_0_6h = precip_6h
    increment_6_24h = (precip_24h - precip_6h).clip(lower=0)
    increment_24_48h = (precip_48h - precip_24h).clip(lower=0)
    increment_48_72h = (precip_72h - precip_48h).clip(lower=0)
    increment_72h_7d = (precip_7d - precip_72h).clip(lower=0)
    frame["precip_runoff_lag_kernel_7d"] = (
        increment_0_6h
        + 0.70 * increment_6_24h
        + 0.45 * increment_24_48h
        + 0.25 * increment_48_72h
        + 0.10 * increment_72h_7d
    )

    latest = pd.to_numeric(enriched["streamflow_cfs_latest"], errors="coerce").fillna(0.0).clip(lower=0)
    mean_24h = pd.to_numeric(enriched["streamflow_cfs_mean_24h"], errors="coerce").fillna(0.0).clip(lower=0)
    max_24h = pd.to_numeric(enriched["streamflow_cfs_max_24h"], errors="coerce").fillna(0.0).clip(lower=0)
    frame["streamflow_lag_kernel_24h"] = 0.60 * latest + 0.30 * mean_24h + 0.10 * max_24h
    return frame


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
    missing_mmb = {
        column: np.nan for column in MARINE_MICROBIOLOGY_NUMERIC_COLUMNS if column not in enriched.columns
    }
    if missing_mmb:
        enriched = enriched.assign(**missing_mmb)
    missing_stormwater = {
        column: np.nan for column in STORMWATER_EXPERT_NUMERIC_COLUMNS if column not in enriched.columns
    }
    if missing_stormwater:
        enriched = enriched.assign(**missing_stormwater)

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

    spatial_features = _spatial_context_features(enriched)
    # Chronic-source interactions: Tijuana plume risk increases under onshore wind
    # (positive shore-normal component), which compresses nearshore plumes.
    shore_normal_wind = pd.to_numeric(enriched.get("shore_normal_wind_ms"), errors="coerce").fillna(0.0)
    zone_features = pd.DataFrame(
        {
            "tijuana_plume_onshore_flag": (
                (spatial_features["is_tijuana_plume_zone"] == 1) & (shore_normal_wind >= 0.5)
            ).astype(int),
            "tijuana_plume_wind_interaction": spatial_features["is_tijuana_plume_zone"].to_numpy(dtype=float)
            * shore_normal_wind.to_numpy(dtype=float),
        },
        index=enriched.index,
    )
    lagged_features = _exact_lag_features(enriched)
    rolling_features = _rolling_and_spacing_features(enriched)
    distributed_lag_features = _distributed_lag_hydrology_features(enriched)
    regulatory_geomean_features = _regulatory_geomean_features(enriched)
    sd_boundary_features = _sd_boundary_features(enriched)

    missing_indicators = pd.DataFrame(
        {f"{column}_missing": enriched[column].isna().astype(int) for column in BASE_NUMERIC_COLUMNS},
        index=enriched.index,
    )

    return pd.concat(
        [
            enriched,
            seasonal_features,
            spatial_features,
            zone_features,
            lagged_features,
            rolling_features,
            distributed_lag_features,
            regulatory_geomean_features,
            sd_boundary_features,
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
            # Leaky: this is the beach's ALL-TIME advisory total (no date bound),
            # broadcast onto every dated row, so a 2021 row carries advisories
            # posted through 2026 — future, target-correlated information. Its
            # log1p transform was slipping into the model via _spatial_context_
            # features and, in leave-one-beach-out folds, leaked the held-out
            # beach's own future advisory count into its features (inflating the
            # reported spatial AUCPR). Dropped from the model feature set.
            "historical_advisory_count_log1p",
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
