from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.core.timewindows import forecast_cutoff_utc as _forecast_cutoff_utc


_PACIFIC = ZoneInfo("America/Los_Angeles")


def aggregate_streamflow_windows(raw_streamflow: pd.DataFrame) -> pd.DataFrame:
    output_cols = [
        "gage_id", "sample_date", "streamflow_cfs_latest",
        "streamflow_cfs_mean_6h", "streamflow_cfs_mean_24h",
        "streamflow_cfs_max_24h", "streamflow_cfs_mean_72h",
        "streamflow_rising_flag",
    ]
    if raw_streamflow.empty:
        return pd.DataFrame(columns=output_cols)

    df = raw_streamflow.copy()
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True, errors="coerce")
    df["discharge_cfs"] = pd.to_numeric(df["discharge_cfs"], errors="coerce")
    df = df.dropna(subset=["time_utc", "discharge_cfs", "gage_id"])
    # Remove duplicate gage/timestamp rows (keep last, matching USGS precedence)
    df = df.drop_duplicates(subset=["gage_id", "time_utc"], keep="last")
    if df.empty:
        return pd.DataFrame(columns=output_cols)

    rows = []
    for gage_id, gdf in df.groupby("gage_id"):
        series = gdf.set_index("time_utc")["discharge_cfs"].sort_index()
        min_date = series.index.min().date()
        max_date = series.index.max().date()

        for d in pd.date_range(min_date, max_date, freq="D"):
            cutoff = _forecast_cutoff_utc(d.date())
            # Strictly before the forecast issue cutoff (handles PST/PDT correctly)
            prior = series[series.index < cutoff]
            if prior.empty:
                continue

            latest = float(prior.iloc[-1])
            w6 = prior[prior.index >= cutoff - pd.Timedelta(hours=6)]
            w24 = prior[prior.index >= cutoff - pd.Timedelta(hours=24)]
            w72 = prior[prior.index >= cutoff - pd.Timedelta(hours=72)]

            mean_6h = float(w6.mean()) if not w6.empty else np.nan
            mean_24h = float(w24.mean()) if not w24.empty else np.nan
            max_24h = float(w24.max()) if not w24.empty else np.nan
            mean_72h = float(w72.mean()) if not w72.empty else np.nan

            # Rising: latest reading exceeds the 24h mean (stream accelerating)
            rising = int(latest > mean_24h) if not np.isnan(mean_24h) else 0

            rows.append({
                "gage_id": gage_id,
                "sample_date": d.date(),
                "streamflow_cfs_latest": latest,
                "streamflow_cfs_mean_6h": mean_6h,
                "streamflow_cfs_mean_24h": mean_24h,
                "streamflow_cfs_max_24h": max_24h,
                "streamflow_cfs_mean_72h": mean_72h,
                "streamflow_rising_flag": rising,
            })

    if not rows:
        return pd.DataFrame(columns=output_cols)
    return pd.DataFrame(rows)


def build_beach_hydrology_daily(
    hydrologic_links: pd.DataFrame,
    streamflow_daily: pd.DataFrame,
    precip_daily: pd.DataFrame,
) -> pd.DataFrame:
    from app.data.pipeline.external_covariates import haversine_km

    columns = [
        "beach_id", "sample_date", "hydrologic_unit_id", "pour_point_id",
        "nearest_stream_gage_id", "distance_to_pour_point_km", "distance_to_gage_km",
        "streamflow_cfs_latest", "streamflow_cfs_mean_24h", "streamflow_cfs_max_24h",
        "streamflow_rising_flag", "precip_mm_6h", "precip_mm_24h", "precip_mm_48h",
        "precip_mm_72h", "precip_mm_7d",
        "precip_mm_96h", "precip_mm_192h",
        "precip_72h_prior", "precip_168h_prior",
        "first_rain_score",
        "precip_awi", "first_flush_flag",
    ]

    if hydrologic_links.empty:
        return pd.DataFrame(columns=columns)

    # Collect all unique sample dates from both sources
    dates: set = set()
    if not streamflow_daily.empty and "sample_date" in streamflow_daily.columns:
        dates.update(pd.to_datetime(streamflow_daily["sample_date"]).dt.date.tolist())
    if not precip_daily.empty and "sample_date" in precip_daily.columns:
        dates.update(pd.to_datetime(precip_daily["sample_date"]).dt.date.tolist())

    if not dates:
        return pd.DataFrame(columns=columns)

    # Cross beach links with all dates
    dates_df = pd.DataFrame({"sample_date": sorted(dates)})
    beach_dates = (
        hydrologic_links.assign(_key=1)
        .merge(dates_df.assign(_key=1), on="_key")
        .drop(columns="_key")
    )
    beach_dates["sample_date"] = pd.to_datetime(beach_dates["sample_date"]).dt.date

    # Join streamflow via nearest_stream_gage_id
    if not streamflow_daily.empty and "nearest_stream_gage_id" in beach_dates.columns:
        sf = streamflow_daily.copy()
        sf["sample_date"] = pd.to_datetime(sf["sample_date"]).dt.date
        sf = sf.rename(columns={"gage_id": "nearest_stream_gage_id"})
        sf_keep = ["nearest_stream_gage_id", "sample_date", "streamflow_cfs_latest",
                   "streamflow_cfs_mean_24h", "streamflow_cfs_max_24h", "streamflow_rising_flag"]
        sf = sf[[c for c in sf_keep if c in sf.columns]]
        beach_dates = beach_dates.merge(sf, on=["nearest_stream_gage_id", "sample_date"], how="left")

    # Join precip by nearest station (spatial match once, then merge on date)
    if not precip_daily.empty and "pour_point_latitude" in beach_dates.columns:
        station_coords = (
            precip_daily[["station_id", "latitude", "longitude"]]
            .dropna(subset=["latitude", "longitude"])
            .drop_duplicates("station_id")
        )
        beach_coords = (
            hydrologic_links[["beach_id", "pour_point_latitude", "pour_point_longitude"]]
            .dropna(subset=["pour_point_latitude", "pour_point_longitude"])
            .drop_duplicates("beach_id")
        )
        beach_to_station: dict[str, str] = {}
        for _, brow in beach_coords.iterrows():
            min_d = float("inf")
            nearest_st: str | None = None
            for _, srow in station_coords.iterrows():
                d = haversine_km(
                    float(brow["pour_point_latitude"]),
                    float(brow["pour_point_longitude"]),
                    float(srow["latitude"]),
                    float(srow["longitude"]),
                )
                if d < min_d:
                    min_d = d
                    nearest_st = str(srow["station_id"])
            if nearest_st is not None:
                beach_to_station[str(brow["beach_id"])] = nearest_st

        beach_dates["_station_id"] = beach_dates["beach_id"].astype(str).map(beach_to_station)
        precip_cols = [
            c for c in precip_daily.columns
            if c.startswith("precip_") or c in ("first_flush_flag", "first_rain_score")
        ]
        pjoin = precip_daily[["station_id", "sample_date", *precip_cols]].copy()
        pjoin["sample_date"] = pd.to_datetime(pjoin["sample_date"]).dt.date
        pjoin = pjoin.rename(columns={"station_id": "_station_id"})
        beach_dates = beach_dates.merge(pjoin, on=["_station_id", "sample_date"], how="left")
        beach_dates = beach_dates.drop(columns=["_station_id"])

    out_cols = [c for c in columns if c in beach_dates.columns]
    return beach_dates[out_cols].reset_index(drop=True)
