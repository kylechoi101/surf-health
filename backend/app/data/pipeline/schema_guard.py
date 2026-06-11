"""Lightweight output-schema guard for the curated ``beach_day`` training artifact.

The primary ML training artifact ``beach_day.parquet`` is written daily by the
production pipeline with no schema check. A silent column drop, an empty frame,
or a missing primary key would corrupt every downstream retrain without an
obvious error. ``validate_beach_day`` is a cheap, conservative gate run right
before the parquet write.

Design contract (intentionally asymmetric):

* **HARD-raise** only on structural breakage that makes the artifact unusable:
  an empty frame, a missing primary key, or a missing label column. These are
  never legitimate on real data and should fail the run loudly.
* **WARN-and-continue** for expected *feature* columns that are absent or
  entirely NaN. A connector outage (Open-Meteo / USGS down for a day) legitimately
  yields an all-NaN feature column; we must not break the daily run for that —
  the model tolerates NaN features. We only surface a warning so the outage is
  visible in the logs.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# True primary keys — every beach_day row is identified by (beach_id, sample_date).
PRIMARY_KEY_COLUMNS: tuple[str, ...] = ("beach_id", "sample_date")

# The training label.
LABEL_COLUMNS: tuple[str, ...] = ("exceeds_stv",)

# Feature columns we *expect* to be populated on a healthy run. Their absence or
# all-NaN state is a connector/feature-build smell worth a warning, but NOT a
# hard failure (a single-day connector outage produces a legitimate all-NaN
# column and must not break the live daily job).
EXPECTED_FEATURE_COLUMNS: tuple[str, ...] = (
    # 11 marine-microbiology features (--with-solar-wind)
    "shore_normal_wind_ms",
    "solar_inactivation_index",
    "cloud_cover_24h_mean",
    "shortwave_24h_sum",
    "uv_index_24h_max",
    "wind_speed_24h_max",
    "days_since_sunny",
    "dist_to_pier_km",
    "is_near_pier",
    "dist_to_estuary_km",
    "is_near_estuary_mouth",
    # key precip features (--with-hydrology)
    "precip_mm_24h",
    "precip_mm_72h",
    "first_rain_score",
    # key streamflow features (--with-hydrology)
    "streamflow_cfs_latest",
    "streamflow_cfs_mean_24h",
)


class BeachDaySchemaError(ValueError):
    """Raised when the curated beach_day artifact is structurally unusable."""


def validate_beach_day(frame: pd.DataFrame) -> None:
    """Validate the curated ``beach_day`` frame before it is persisted.

    Raises :class:`BeachDaySchemaError` on structural breakage (empty frame,
    missing primary key, or missing label column). Logs a warning — but does not
    raise — when an expected feature column is absent or entirely NaN.
    """
    if frame is None or frame.empty:
        raise BeachDaySchemaError(
            "beach_day frame is empty — refusing to write a degenerate training artifact"
        )

    missing_keys = [c for c in PRIMARY_KEY_COLUMNS if c not in frame.columns]
    if missing_keys:
        raise BeachDaySchemaError(
            f"beach_day is missing primary key column(s): {missing_keys}"
        )

    missing_label = [c for c in LABEL_COLUMNS if c not in frame.columns]
    if missing_label:
        raise BeachDaySchemaError(
            f"beach_day is missing label column(s): {missing_label}"
        )

    # Feature columns: warn (do not raise) on absent or all-NaN.
    absent = [c for c in EXPECTED_FEATURE_COLUMNS if c not in frame.columns]
    if absent:
        logger.warning(
            "beach_day is missing %d expected feature column(s): %s "
            "(continuing — likely a connector outage or a skipped pipeline stage)",
            len(absent),
            absent,
        )

    present = [c for c in EXPECTED_FEATURE_COLUMNS if c in frame.columns]
    all_nan = [c for c in present if frame[c].isna().all()]
    if all_nan:
        logger.warning(
            "beach_day has %d expected feature column(s) that are entirely NaN: %s "
            "(continuing — likely a connector outage for this run)",
            len(all_nan),
            all_nan,
        )
