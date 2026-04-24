from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

_PACIFIC = ZoneInfo("America/Los_Angeles")


def _forecast_cutoff_utc(d: date) -> pd.Timestamp:
    """Return 5 AM PT in UTC for the given date, correctly accounting for PST vs PDT."""
    return pd.Timestamp(datetime(d.year, d.month, d.day, 5, 0, 0, tzinfo=_PACIFIC)).tz_convert("UTC")


def compute_antecedent_wetness_index(precip_series: pd.Series, decay_rate: float = 0.2) -> pd.Series:
    # Exponentially weighted accumulation of prior-day precipitation (forecast-safe: shift by 1)
    return precip_series.shift(1).fillna(0.0).ewm(alpha=decay_rate, adjust=False).mean()


def compute_first_flush_flag(
    precip_series: pd.Series,
    dry_days: int = 3,
    threshold_mm: float = 12.7,
) -> pd.Series:
    # 1 if: no rain in the prior N days AND today's precip exceeds threshold
    prior_sum = precip_series.shift(1).rolling(dry_days, min_periods=1).sum().fillna(0.0)
    dry_antecedent = prior_sum == 0
    return (dry_antecedent & (precip_series > threshold_mm)).astype(int)


def aggregate_precip_windows(raw_precip: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate sub-hourly precipitation increments into forecast-safe daily windows.

    Output is keyed by (station_id, sample_date) with lat/lon retained so that
    build_beach_hydrology_daily can do a spatial nearest-station join.
    """
    output_cols = [
        "station_id", "latitude", "longitude", "sample_date",
        "precip_mm_1h", "precip_mm_6h", "precip_mm_24h",
        "precip_mm_48h", "precip_mm_72h", "precip_mm_7d",
        "precip_awi", "first_flush_flag",
    ]
    if raw_precip.empty:
        return pd.DataFrame(columns=output_cols)

    df = raw_precip.copy()
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True, errors="coerce")
    df["precip_mm_increment"] = pd.to_numeric(df["precip_mm_increment"], errors="coerce").clip(lower=0)
    df = df.dropna(subset=["time_utc", "station_id"])
    df = df.drop_duplicates(subset=["station_id", "time_utc"], keep="last")
    if df.empty:
        return pd.DataFrame(columns=output_cols)

    rows = []
    for station_id, sdf in df.groupby("station_id"):
        series = sdf.set_index("time_utc")["precip_mm_increment"].sort_index().fillna(0.0)
        lat = float(sdf["latitude"].iloc[0]) if "latitude" in sdf.columns else np.nan
        lon = float(sdf["longitude"].iloc[0]) if "longitude" in sdf.columns else np.nan
        min_date = series.index.min().date()
        max_date = series.index.max().date()

        for d in pd.date_range(min_date, max_date, freq="D"):
            cutoff = _forecast_cutoff_utc(d.date())
            # Strictly before the forecast issue time (handles PST/PDT correctly)
            prior = series[series.index < cutoff]
            if prior.empty:
                continue

            def _window_sum(hours: int) -> float:
                w = prior[prior.index >= cutoff - pd.Timedelta(hours=hours)]
                return float(w.sum()) if not w.empty else 0.0

            rows.append({
                "station_id": station_id,
                "latitude": lat,
                "longitude": lon,
                "sample_date": d.date(),
                "precip_mm_1h": _window_sum(1),
                "precip_mm_6h": _window_sum(6),
                "precip_mm_24h": _window_sum(24),
                "precip_mm_48h": _window_sum(48),
                "precip_mm_72h": _window_sum(72),
                "precip_mm_7d": _window_sum(24 * 7),
            })

    if not rows:
        return pd.DataFrame(columns=output_cols)

    result = pd.DataFrame(rows).sort_values(["station_id", "sample_date"]).reset_index(drop=True)

    # Compute AWI and first-flush per station using daily 24h totals
    awi_parts: list[pd.Series] = []
    ff_parts: list[pd.Series] = []
    for _, grp in result.groupby("station_id", sort=False):
        daily_precip = grp["precip_mm_24h"].reset_index(drop=True)
        awi_parts.append(pd.Series(compute_antecedent_wetness_index(daily_precip).values, index=grp.index))
        ff_parts.append(pd.Series(compute_first_flush_flag(daily_precip).values, index=grp.index))

    result["precip_awi"] = pd.concat(awi_parts)
    result["first_flush_flag"] = pd.concat(ff_parts)

    return result.reset_index(drop=True)
