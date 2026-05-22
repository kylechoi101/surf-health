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


def compute_first_rain_score(
    precip_24h: pd.Series,
    precip_72h_prior: pd.Series,
    precip_168h_prior: pd.Series,
    dry_threshold_mm: float = 2.0,
) -> pd.Series:
    """First-rain-after-dry-spell score (Hermes, 5-Opus+Sonnet council winner 2026-05-19).

    Mechanism: dry-spell accumulation of fecal matter on impervious surfaces
    mobilizes during the first rain event, producing disproportionate bacterial
    loading vs equivalent rain on already-wet soil (Stenstrom et al. 1984; NRCS
    impervious surface runoff mechanics).

    Formula (Hermes' literal spec):
        dry_72_to_168h = max(precip_72h_prior, precip_168h_prior) < 2.0
        first_rain_score = precip_24h * dry_72_to_168h

    Leakage guarantee: ``precip_72h_prior`` and ``precip_168h_prior`` MUST
    cover hours [24, 96] and [24, 192] back from forecast cutoff respectively,
    i.e. windows that *end* 24h before forecast time. Today's rain (the same
    24h being scored) cannot enter the dryness boolean.
    """
    p24 = pd.to_numeric(precip_24h, errors="coerce").fillna(0.0).clip(lower=0.0)
    p72p = pd.to_numeric(precip_72h_prior, errors="coerce").fillna(0.0).clip(lower=0.0)
    p168p = pd.to_numeric(precip_168h_prior, errors="coerce").fillna(0.0).clip(lower=0.0)
    prior_max = np.maximum(p72p, p168p)
    dry_flag = (prior_max < dry_threshold_mm).astype(float)
    return (p24 * dry_flag).astype(float)


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
        "precip_mm_96h", "precip_mm_192h",
        "precip_72h_prior", "precip_168h_prior",
        "first_rain_score",
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

            p_24 = _window_sum(24)
            p_72 = _window_sum(72)
            p_7d = _window_sum(24 * 7)
            p_96 = _window_sum(96)
            p_192 = _window_sum(192)
            # Prior windows END 24h before cutoff — required so today's rain
            # does not contaminate the dry-spell boolean (leakage guarantee).
            p_72_prior = max(p_96 - p_24, 0.0)
            p_168_prior = max(p_192 - p_24, 0.0)

            rows.append({
                "station_id": station_id,
                "latitude": lat,
                "longitude": lon,
                "sample_date": d.date(),
                "precip_mm_1h": _window_sum(1),
                "precip_mm_6h": _window_sum(6),
                "precip_mm_24h": p_24,
                "precip_mm_48h": _window_sum(48),
                "precip_mm_72h": p_72,
                "precip_mm_7d": p_7d,
                "precip_mm_96h": p_96,
                "precip_mm_192h": p_192,
                "precip_72h_prior": p_72_prior,
                "precip_168h_prior": p_168_prior,
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
    result["first_rain_score"] = compute_first_rain_score(
        result["precip_mm_24h"],
        result["precip_72h_prior"],
        result["precip_168h_prior"],
    )

    return result.reset_index(drop=True)
