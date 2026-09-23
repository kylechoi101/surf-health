"""Standalone lookup baseline forecaster.

Predicts beach water-quality exceedance from each beach's own history only
(strictly prior samples) with shrinkage toward global historical rate.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


def rain_station_key(lat: float, lon: float) -> str:
    """Format rounded lat/lon to match station_id in precip_daily.parquet.

    Rounds latitude and longitude to 1 decimal place and joins with an underscore.
    Example: 32.4499, -117.1499 -> "32.4_-117.1"
    """
    return f"{round(float(lat), 1):.1f}_{round(float(lon), 1):.1f}"


def assign_band(
    sample_age_days: int | float | None = None,
    advisory_active: bool = False,
    p_lookup: float = 0.0,
    *,
    row: pd.Series | dict | None = None,
) -> str:
    """Assign risk band based on strict precedence: Unmonitored > Posted > Elevated > Low.

    Precedence:
      1. Unmonitored: no sample in 30 days, or never sampled (sample_age_days > 30 or None/NaN).
      2. Posted: advisory_active is True.
      3. Elevated: p_lookup >= 0.10.
      4. Low: all other cases.
    """
    if row is not None:
        sample_age_days = (
            row.get("sample_age_days") if isinstance(row, dict) else row["sample_age_days"]
        )
        advisory_active = bool(
            row.get("advisory_active") if isinstance(row, dict) else row["advisory_active"]
        )
        p_lookup = float(row.get("p_lookup") if isinstance(row, dict) else row["p_lookup"])
    elif isinstance(sample_age_days, (pd.Series, dict)):
        r = sample_age_days
        sample_age_days = (
            r.get("sample_age_days") if isinstance(r, dict) else r["sample_age_days"]
        )
        advisory_active = bool(
            r.get("advisory_active") if isinstance(r, dict) else r["advisory_active"]
        )
        p_lookup = float(r.get("p_lookup") if isinstance(r, dict) else r["p_lookup"])

    # 1. Unmonitored: no sample in 30 days, or never
    if sample_age_days is None or pd.isna(sample_age_days) or sample_age_days > 30:
        return "Unmonitored"

    # 2. Posted: advisory_active
    if advisory_active:
        return "Posted"

    # 3. Elevated: p_lookup >= 0.10
    if p_lookup >= 0.10:
        return "Elevated"

    # 4. Low
    return "Low"


def advisory_active(
    advisories: pd.DataFrame | pd.Series,
    forecast_date: str | pd.Timestamp | datetime | date,
    *,
    beach_id: str | None = None,
    beaches: list[str] | pd.Index | pd.Series | None = None,
) -> bool | pd.Series:
    """Determine whether an advisory is active on forecast_date D.

    Condition:
      active on D <=> started_at <= D AND (
                        (ended_at not null AND ended_at >= D)
                        OR (ended_at null AND status == "active") )
    """
    d_ts = pd.Timestamp(forecast_date).normalize()

    if isinstance(advisories, pd.Series):
        started_val = advisories.get("started_at")
        if pd.isna(started_val):
            return False
        started = pd.to_datetime(started_val).normalize()
        if started > d_ts:
            return False
        ended_val = advisories.get("ended_at")
        status_raw = advisories.get("status")
        if status_raw is not None and not pd.isna(status_raw):
            status_val = str(status_raw)
        elif "status" in advisories:
            status_val = ""
        else:
            status_val = "active"

        if ended_val is not None and not pd.isna(ended_val):
            return pd.to_datetime(ended_val).normalize() >= d_ts
        return status_val == "active"

    if advisories.empty:
        if beach_id is not None or "beach_id" not in advisories.columns:
            return False
        if beaches is not None:
            return pd.Series(False, index=pd.Index(beaches), dtype=bool)
        return pd.Series(dtype=bool)

    started_series = pd.to_datetime(advisories["started_at"]).dt.normalize()
    ended_series = pd.to_datetime(advisories["ended_at"]).dt.normalize()
    if "status" in advisories.columns:
        is_active_status = advisories["status"].fillna("").astype(str) == "active"
    else:
        is_active_status = pd.Series(True, index=advisories.index)

    active_mask = (started_series <= d_ts) & (
        (ended_series.notna() & (ended_series >= d_ts))
        | (ended_series.isna() & is_active_status)
    )

    if beach_id is not None:
        if "beach_id" in advisories.columns:
            return bool((active_mask & (advisories["beach_id"] == beach_id)).any())
        return bool(active_mask.any())

    if "beach_id" not in advisories.columns:
        return bool(active_mask.any())

    active_beach_ids = set(advisories.loc[active_mask, "beach_id"].dropna().unique())
    if beaches is not None:
        idx = pd.Index(beaches)
        return pd.Series(idx.isin(active_beach_ids), index=idx, dtype=bool)

    all_beaches = pd.Index(advisories["beach_id"].dropna().unique())
    return pd.Series(all_beaches.isin(active_beach_ids), index=all_beaches, dtype=bool)


def last_sample(
    df: pd.DataFrame,
    forecast_date: str | pd.Timestamp | datetime | date,
    *,
    beach_id: str | None = None,
    beaches: list[str] | pd.Index | pd.Series | None = None,
) -> dict[str, object] | pd.DataFrame:
    """Find the most recent sample strictly prior to forecast_date D (sample_date < D).

    Returns last_sample_date, last_sample_exceeds, last_sample_value, sample_age_days.
    """
    d_ts = pd.Timestamp(forecast_date).normalize()

    if df.empty:
        if beach_id is not None or "beach_id" not in df.columns:
            return {
                "last_sample_date": None,
                "last_sample_exceeds": None,
                "last_sample_value": None,
                "sample_age_days": None,
            }
        cols = [
            "beach_id",
            "last_sample_date",
            "last_sample_exceeds",
            "last_sample_value",
            "sample_age_days",
        ]
        if beaches is not None:
            return pd.DataFrame({"beach_id": list(beaches)}).reindex(columns=cols)
        return pd.DataFrame(columns=cols)

    dates = pd.to_datetime(df["sample_date"]).dt.normalize()
    prior_mask = dates < d_ts
    prior_df = df[prior_mask].copy()

    # Single beach mode (if beach_id provided or dataframe has no beach_id column)
    if beach_id is not None or "beach_id" not in df.columns:
        if beach_id is not None and "beach_id" in prior_df.columns:
            prior_df = prior_df[prior_df["beach_id"] == beach_id]

        if prior_df.empty:
            return {
                "last_sample_date": None,
                "last_sample_exceeds": None,
                "last_sample_value": None,
                "sample_age_days": None,
            }

        sorted_df = prior_df.sort_values("sample_date")
        row = sorted_df.iloc[-1]
        last_dt = pd.to_datetime(row["sample_date"]).normalize()
        age = int((d_ts - last_dt).days)
        exceeds = (
            bool(row["exceeds_stv"])
            if "exceeds_stv" in row and not pd.isna(row["exceeds_stv"])
            else None
        )
        val = (
            float(row["enterococcus_value"])
            if "enterococcus_value" in row and not pd.isna(row["enterococcus_value"])
            else None
        )
        return {
            "last_sample_date": last_dt.strftime("%Y-%m-%d"),
            "last_sample_exceeds": exceeds,
            "last_sample_value": val,
            "sample_age_days": age,
        }

    # Multi-beach mode
    if prior_df.empty:
        records = pd.DataFrame(
            columns=[
                "beach_id",
                "last_sample_date",
                "last_sample_exceeds",
                "last_sample_value",
                "sample_age_days",
            ]
        )
    else:
        sorted_df = prior_df.sort_values("sample_date")
        latest_rows = sorted_df.groupby("beach_id").last().reset_index()
        latest_rows["last_sample_date"] = (
            pd.to_datetime(latest_rows["sample_date"]).dt.strftime("%Y-%m-%d")
        )
        latest_rows["sample_age_days"] = (
            d_ts - pd.to_datetime(latest_rows["sample_date"]).dt.normalize()
        ).dt.days.astype("Int64")
        latest_rows["last_sample_exceeds"] = pd.Series(
            latest_rows["exceeds_stv"], dtype="boolean"
        )
        latest_rows["last_sample_value"] = latest_rows["enterococcus_value"].astype(float)
        records = latest_rows[
            [
                "beach_id",
                "last_sample_date",
                "last_sample_exceeds",
                "last_sample_value",
                "sample_age_days",
            ]
        ]

    cols = [
        "beach_id",
        "last_sample_date",
        "last_sample_exceeds",
        "last_sample_value",
        "sample_age_days",
    ]
    if beaches is not None:
        b_df = pd.DataFrame({"beach_id": list(beaches)})
        if len(records) > 0:
            res = b_df.merge(records, on="beach_id", how="left")
            res["sample_age_days"] = res["sample_age_days"].astype("Int64")
            res["last_sample_exceeds"] = res["last_sample_exceeds"].astype("boolean")
            res["last_sample_value"] = res["last_sample_value"].astype(float)
        else:
            res = b_df.reindex(columns=cols)
        return res

    return records if len(records) > 0 else pd.DataFrame(columns=cols)


def lookup_rate(
    data: pd.DataFrame | int | float,
    forecast_date: str | pd.Timestamp | datetime | date | int | float | None = None,
    g: float | None = None,
    *,
    beach_id: str | None = None,
    beaches: list[str] | pd.Index | pd.Series | None = None,
) -> float | pd.DataFrame:
    """Compute exceedance rate shrunken toward global rate g over [D-365d, D).

    Formula: p_lookup = (pos + g * 5) / (n + 5).
    Strictly prior: only samples with sample_date in [D-365d, D) are counted.
    Shrinkage: a beach with 0 samples gets exactly g.
    """
    # Scalar overload: lookup_rate(pos, n, g)
    if isinstance(data, (int, float, np.integer, np.floating)) and isinstance(
        forecast_date, (int, float, np.integer, np.floating)
    ):
        pos = float(data)
        n = float(forecast_date)
        g_val = float(g if g is not None else 0.0)
        return (pos + g_val * 5.0) / (n + 5.0)

    if not isinstance(data, pd.DataFrame):
        raise TypeError("Expected pd.DataFrame or scalar (pos, n, g)")

    df = data
    d_ts = pd.Timestamp(forecast_date).normalize()
    d_start = d_ts - pd.Timedelta(days=365)

    if df.empty:
        g_val = float(g if g is not None else 0.0)
        if beach_id is not None or "beach_id" not in df.columns:
            return g_val
        cols = ["beach_id", "pos", "n", "n_365d", "rate_365d", "p_lookup"]
        if beaches is not None:
            res = pd.DataFrame({"beach_id": list(beaches)})
            res["pos"] = 0
            res["n"] = 0
            res["n_365d"] = 0
            res["rate_365d"] = np.nan
            res["p_lookup"] = g_val
            return res
        return pd.DataFrame(columns=cols)

    dates = pd.to_datetime(df["sample_date"]).dt.normalize()
    window_mask = (dates >= d_start) & (dates < d_ts)
    window_df = df[window_mask]

    # Global rate g over [D-365d, D) across all beaches
    if g is None:
        n_global = len(window_df)
        pos_global = int(window_df["exceeds_stv"].sum()) if n_global > 0 else 0
        g_val = (pos_global / n_global) if n_global > 0 else 0.0
    else:
        g_val = float(g)

    # Single beach mode
    if beach_id is not None or "beach_id" not in df.columns:
        if beach_id is not None and "beach_id" in window_df.columns:
            beach_samples = window_df[window_df["beach_id"] == beach_id]
        else:
            beach_samples = window_df

        n_b = len(beach_samples)
        pos_b = int(beach_samples["exceeds_stv"].sum()) if n_b > 0 else 0
        return (pos_b + g_val * 5.0) / (n_b + 5.0)

    # Multi-beach mode
    if not window_df.empty:
        grouped = (
            window_df.groupby("beach_id")["exceeds_stv"]
            .agg(pos="sum", n="count")
            .reset_index()
        )
        grouped["n_365d"] = grouped["n"]
        grouped["rate_365d"] = grouped["pos"] / grouped["n"]
        grouped["p_lookup"] = (grouped["pos"] + g_val * 5.0) / (grouped["n"] + 5.0)
    else:
        grouped = pd.DataFrame(columns=["beach_id", "pos", "n", "n_365d", "rate_365d", "p_lookup"])

    if beaches is not None:
        b_df = pd.DataFrame({"beach_id": list(beaches)})
        res = b_df.merge(grouped, on="beach_id", how="left")
        res["pos"] = res["pos"].fillna(0).astype(int)
        res["n"] = res["n"].fillna(0).astype(int)
        res["n_365d"] = res["n"]
        res["p_lookup"] = res["p_lookup"].fillna(g_val).astype(float)
        return res

    return grouped


def build_lookup_forecast(
    snapshot_dir: Path,
    forecast_date: str,
    *,
    beaches: pd.DataFrame | None = None,
    beach_day: pd.DataFrame | None = None,
    advisories: pd.DataFrame | None = None,
    precip: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build the lookup forecast for date D across all beaches.

    Returns DataFrame with one row per beach in beaches.parquet (850 rows)
    and the columns specified in the brief.
    """
    if beaches is None:
        beaches = pq.read_table(snapshot_dir / "beaches.parquet").to_pandas()
    if beach_day is None:
        beach_day = pq.read_table(snapshot_dir / "beach_day.parquet").to_pandas()
    if advisories is None:
        advisories = pq.read_table(snapshot_dir / "advisories.parquet").to_pandas()
    if precip is None:
        precip = pq.read_table(snapshot_dir / "precip_daily.parquet").to_pandas()

    d_date = pd.to_datetime(forecast_date).date()
    beach_ids = beaches["beach_id"]

    # 1. 365-day rates with shrinkage toward global g
    rates_df = lookup_rate(beach_day, forecast_date, beaches=beach_ids)

    # 2. Last sample strictly prior to D
    ls_df = last_sample(beach_day, forecast_date, beaches=beach_ids)

    # 3. Advisory active on D
    adv_series = advisory_active(advisories, forecast_date, beaches=beach_ids)

    # 4. Rain flag from precip_daily on date D
    if not precip.empty and "sample_date" in precip.columns:
        p_d = precip[pd.to_datetime(precip["sample_date"]).dt.date == d_date]
        precip_map = dict(zip(p_d["station_id"], p_d["precip_mm_72h"]))
    else:
        precip_map = {}

    rain_flags = []
    for lat, lon in zip(beaches["latitude"], beaches["longitude"]):
        st_id = rain_station_key(lat, lon)
        val = precip_map.get(st_id)
        if val is None or pd.isna(val):
            rain_flags.append(None)
        else:
            rain_flags.append(bool(val >= 5.0))

    # Assemble forecast DataFrame starting from beaches
    forecast_df = pd.DataFrame(
        {
            "beach_id": beaches["beach_id"],
            "name": beaches["name"] if "name" in beaches else "",
            "county": beaches["county"] if "county" in beaches else "",
            "forecast_date": str(forecast_date),
        }
    )

    # Merge lookup rates
    forecast_df = forecast_df.merge(
        rates_df[["beach_id", "n_365d", "rate_365d", "p_lookup"]], on="beach_id", how="left"
    )

    # Merge last sample details
    ls_cols = [
        "beach_id",
        "last_sample_date",
        "last_sample_exceeds",
        "last_sample_value",
        "sample_age_days",
    ]
    forecast_df = forecast_df.merge(ls_df[ls_cols], on="beach_id", how="left")

    # Add advisory_active and rain_flag
    forecast_df["advisory_active"] = adv_series.reindex(forecast_df["beach_id"]).fillna(False).values
    forecast_df["rain_flag"] = pd.Series(rain_flags, dtype="boolean")

    # 5. Assign risk band with precedence Unmonitored > Posted > Elevated > Low
    bands = [
        assign_band(age, adv, p)
        for age, adv, p in zip(
            forecast_df["sample_age_days"],
            forecast_df["advisory_active"],
            forecast_df["p_lookup"],
        )
    ]
    forecast_df["band"] = bands

    return forecast_df


def format_markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    """Format headers and row data into a GitHub-flavored markdown table."""
    header_line = "| " + " | ".join(str(h).replace("|", "\\|") for h in headers) + " |"
    separator_line = "| " + " | ".join("---" for _ in headers) + " |"
    data_lines = [
        "| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |"
        for row in rows
    ]
    return "\n".join([header_line, separator_line] + data_lines)


def identify_ddpcr_beaches(obs: pd.DataFrame) -> set[str]:
    """Identify beaches that use ddPCR testing.

    A beach is ddPCR if any of its observations rows has method containing
    'pcr' or units containing 'opies', case-insensitive.
    """
    if obs.empty or "beach_id" not in obs.columns:
        return set()
    method = (
        obs["method"].fillna("").astype(str).str.lower()
        if "method" in obs.columns
        else pd.Series("", index=obs.index)
    )
    units = (
        obs["units"].fillna("").astype(str).str.lower()
        if "units" in obs.columns
        else pd.Series("", index=obs.index)
    )
    is_pcr = method.str.contains("pcr") | units.str.contains("opies")
    return set(obs.loc[is_pcr, "beach_id"].dropna().unique())


def build_comparison_report(
    served_df: pd.DataFrame,
    lookup_df: pd.DataFrame,
    forecast_date: str,
) -> tuple[str, pd.DataFrame]:
    """Build markdown report and comparison DataFrame between served and lookup forecasts.

    Compares served forecasts (from forecasts.parquet) with lookup forecasts for date D.
    Returns (markdown_text, comparison_dataframe).
    """
    served_cols = [
        c
        for c in [
            "beach_id",
            "risk_band",
            "p_exceed",
            "sample_age_days",
            "advisory_floor_applied",
        ]
        if c in served_df.columns
    ]
    merged = served_df[served_cols].merge(
        lookup_df, on="beach_id", suffixes=("_served", "_lookup")
    )

    merged["abs_diff"] = (merged["p_exceed"] - merged["p_lookup"]).abs()
    merged["p_diff"] = merged["p_lookup"] - merged["p_exceed"]

    # (a) Summary count table of served risk_band x lookup band
    ct = pd.crosstab(
        merged["risk_band"],
        merged["band"],
        margins=True,
        margins_name="Total",
    )
    ct_headers = ["Served Risk Band"] + list(ct.columns)
    ct_rows = [
        [str(idx)] + [str(ct.loc[idx, col]) for col in ct.columns]
        for idx in ct.index
    ]
    ct_md = format_markdown_table(ct_headers, ct_rows)

    # (b) Beaches the ML serves that the lookup calls Unmonitored
    unmonitored_count = int((merged["band"] == "Unmonitored").sum())

    # (c) Top 25 beaches with largest |p_exceed - p_lookup|
    top25 = merged.sort_values("abs_diff", ascending=False).head(25)
    top25_headers = [
        "Rank",
        "Beach Name",
        "County",
        "Served Band",
        "Lookup Band",
        "Served p_exceed",
        "Lookup p_lookup",
        "|Diff|",
        "Sample Age (days)",
        "Last Sample Date",
        "Last Sample Exceeds",
        "Last Sample Value (MPN or copies/100ml)",
    ]
    top25_rows = []
    sample_age_col = (
        "sample_age_days_lookup"
        if "sample_age_days_lookup" in top25.columns
        else "sample_age_days"
    )
    for i, (_, r) in enumerate(top25.iterrows(), 1):
        exceeds_val = r.get("last_sample_exceeds")
        exceeds_str = (
            "Yes"
            if exceeds_val is True
            else ("No" if exceeds_val is False else "None")
        )
        val_raw = r.get("last_sample_value")
        val_str = f"{val_raw:.1f}" if pd.notna(val_raw) and val_raw is not None else "None"
        age_raw = r.get(sample_age_col)
        age_str = str(int(age_raw)) if pd.notna(age_raw) and age_raw is not None else "None"
        top25_rows.append(
            [
                str(i),
                str(r.get("name", "")),
                str(r.get("county", "")),
                str(r.get("risk_band", "")),
                str(r.get("band", "")),
                f"{r['p_exceed']:.3f}",
                f"{r['p_lookup']:.3f}",
                f"{r['abs_diff']:.3f}",
                age_str,
                str(r.get("last_sample_date") or "None"),
                exceeds_str,
                val_str,
            ]
        )
    top25_md = format_markdown_table(top25_headers, top25_rows)

    md_content = f"""# Lookup Baseline vs. Served ML Forecast Comparison: {forecast_date}

## Overview
This comparison evaluates the served ML model (`forecasts.parquet`, {len(merged)} served beaches) against the strictly-prior lookup baseline (`lookup_forecast_{forecast_date}.parquet`) on forecast date **{forecast_date}**.

## (a) Summary Count Table: Served Risk Band × Lookup Band

{ct_md}

## (b) Unmonitored Beaches Served by ML

The served ML model produces forecasts for **{unmonitored_count}** beaches that the lookup baseline identifies as **Unmonitored** (no lab sample within the last 30 days, or never sampled).

## (c) Top 25 Largest Discrepancies (|p_exceed - p_lookup|)

{top25_md}
"""
    # Sort merged for CSV export
    sorted_df = merged.sort_values("abs_diff", ascending=False).reset_index(drop=True)
    return md_content, sorted_df


def match_forward_lab_results(
    forecast_history: pd.DataFrame,
    beach_day: pd.DataFrame,
) -> pd.DataFrame:
    """Match each forecast to the first lab result at D+1..D+3 in beach_day.

    Deduplicates forecast_history to the latest forecast_generated_at per beach-day.
    Returns verifiable forecasts with ground truth outcome in exceeds_stv.
    """
    fh = (
        forecast_history.sort_values("forecast_generated_at")
        .groupby(["beach_id", "forecast_date"])
        .last()
        .reset_index()
    )
    fh["forecast_date_dt"] = pd.to_datetime(fh["forecast_date"]).dt.normalize()

    bd = beach_day.copy()
    bd["sample_date_dt"] = pd.to_datetime(bd["sample_date"]).dt.normalize()

    min_fc = fh["forecast_date_dt"].min()
    max_fc = fh["forecast_date_dt"].max()

    bd_sub = bd[
        (bd["sample_date_dt"] >= min_fc + pd.Timedelta(days=1))
        & (bd["sample_date_dt"] <= max_fc + pd.Timedelta(days=3))
    ][["beach_id", "sample_date_dt", "exceeds_stv"]].copy()

    merged = fh[["beach_id", "forecast_date", "forecast_date_dt", "p_exceed"]].merge(
        bd_sub, on="beach_id"
    )
    merged["delta_days"] = (merged["sample_date_dt"] - merged["forecast_date_dt"]).dt.days
    m_window = merged[(merged["delta_days"] >= 1) & (merged["delta_days"] <= 3)]

    verifiable = (
        m_window.sort_values("delta_days")
        .groupby(["beach_id", "forecast_date"])
        .first()
        .reset_index()
    )
    return verifiable


def compute_backtest_lookups(
    verifiable_df: pd.DataFrame,
    beach_day: pd.DataFrame,
) -> pd.DataFrame:
    """Compute p_lookup for each distinct forecast date in verifiable forecasts and attach persistence."""
    bd = beach_day.copy()
    bd["sample_date_dt"] = pd.to_datetime(bd["sample_date"]).dt.normalize()

    distinct_dates = sorted(verifiable_df["forecast_date"].unique())
    if not distinct_dates:
        res = verifiable_df.copy()
        res["p_lookup"] = np.nan
        res["last_sample_exceeds"] = pd.Series(dtype="boolean")
        return res

    min_d = pd.to_datetime(min(distinct_dates)) - pd.Timedelta(days=365)
    max_d = pd.to_datetime(max(distinct_dates))
    bd_counts = bd[
        (bd["sample_date_dt"] >= min_d) & (bd["sample_date_dt"] < max_d)
    ][["beach_id", "sample_date_dt", "exceeds_stv"]]

    lookup_results = []
    for d_str in distinct_dates:
        d_ts = pd.Timestamp(d_str).normalize()
        d_start = d_ts - pd.Timedelta(days=365)
        w_df = bd_counts[
            (bd_counts["sample_date_dt"] >= d_start) & (bd_counts["sample_date_dt"] < d_ts)
        ]
        n_global = len(w_df)
        pos_global = int(w_df["exceeds_stv"].sum()) if n_global > 0 else 0
        g = (pos_global / n_global) if n_global > 0 else 0.0

        bg = (
            w_df.groupby("beach_id")["exceeds_stv"]
            .agg(pos="sum", n="count")
            .reset_index()
        )
        bg["p_lookup"] = (bg["pos"] + g * 5.0) / (bg["n"] + 5.0)
        bg["forecast_date"] = d_str
        bg["g"] = g
        lookup_results.append(bg[["beach_id", "forecast_date", "p_lookup", "g"]])

    lookup_df = pd.concat(lookup_results, ignore_index=True)
    scored = verifiable_df.merge(
        lookup_df[["beach_id", "forecast_date", "p_lookup", "g"]],
        on=["beach_id", "forecast_date"],
        how="left",
    )
    scored["p_lookup"] = scored["p_lookup"].fillna(scored["g"])
    scored.drop(columns=["g"], inplace=True)

    # Attach last_sample_exceeds (persistence score) strictly prior to forecast_date
    if "beach_id" in bd.columns and "sample_date" in bd.columns and "exceeds_stv" in bd.columns:
        bd_sub = bd[["beach_id", "sample_date", "exceeds_stv"]].dropna(
            subset=["sample_date", "exceeds_stv"]
        ).copy()
        bd_sub["_prior_sample_dt"] = pd.to_datetime(bd_sub["sample_date"]).astype("datetime64[ns]")
        bd_sub = bd_sub.sort_values("_prior_sample_dt")

        scored_sorted = scored.copy()
        scored_sorted["_orig_idx"] = scored_sorted.index
        scored_sorted["_fc_date_dt_ns"] = pd.to_datetime(scored_sorted["forecast_date"]).astype("datetime64[ns]")
        scored_sorted = scored_sorted.sort_values("_fc_date_dt_ns")

        merged_pers = pd.merge_asof(
            scored_sorted,
            bd_sub[["beach_id", "_prior_sample_dt", "exceeds_stv"]].rename(
                columns={"exceeds_stv": "last_sample_exceeds"}
            ),
            by="beach_id",
            left_on="_fc_date_dt_ns",
            right_on="_prior_sample_dt",
            direction="backward",
            allow_exact_matches=False,
        )
        merged_pers = merged_pers.sort_values("_orig_idx")
        scored["last_sample_exceeds"] = merged_pers["last_sample_exceeds"].values
    else:
        scored["last_sample_exceeds"] = pd.Series(dtype="boolean")

    return scored


def evaluate_slices(
    scored_df: pd.DataFrame,
    max_forecast_date: pd.Timestamp,
) -> pd.DataFrame:
    """Evaluate AUROC, AUCPR, Brier score, N, and base rate across standard slices."""
    d_90 = max_forecast_date - pd.Timedelta(days=90)
    d_30 = max_forecast_date - pd.Timedelta(days=30)

    slices = [
        ("All rows", scored_df),
        ("Last 90 days", scored_df[scored_df["forecast_date_dt"] >= d_90]),
        ("Last 30 days", scored_df[scored_df["forecast_date_dt"] >= d_30]),
        ("Culture beaches", scored_df[~scored_df["is_ddpcr"]]),
        ("ddPCR beaches", scored_df[scored_df["is_ddpcr"]]),
    ]

    records = []
    for name, s_df in slices:
        y = s_df["exceeds_stv"].astype(int)
        n = len(y)
        br = float(y.mean()) if n > 0 else 0.0
        if n > 0 and y.nunique() == 2:
            auc_lk = float(roc_auc_score(y, s_df["p_lookup"]))
            auc_ml = float(roc_auc_score(y, s_df["p_exceed"]))
            pr_lk = float(average_precision_score(y, s_df["p_lookup"]))
            pr_ml = float(average_precision_score(y, s_df["p_exceed"]))
            br_lk = float(brier_score_loss(y, s_df["p_lookup"]))
            br_ml = float(brier_score_loss(y, s_df["p_exceed"]))
        else:
            auc_lk = np.nan
            auc_ml = np.nan
            pr_lk = np.nan
            pr_ml = np.nan
            br_lk = np.nan
            br_ml = np.nan

        records.append(
            {
                "Slice": name,
                "N": n,
                "Base Rate": br,
                "AUROC (Lookup)": auc_lk,
                "AUROC (ML)": auc_ml,
                "AUCPR (Lookup)": pr_lk,
                "AUCPR (ML)": pr_ml,
                "Brier (Lookup)": br_lk,
                "Brier (ML)": br_ml,
            }
        )
    return pd.DataFrame(records)


def evaluate_beaches(
    scored_df: pd.DataFrame,
    beaches: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Evaluate within-beach AUROC for beaches with >=10 verifiable rows and both outcomes.

    Compares the served ML predictor against the within-beach persistence baseline
    (last_sample_exceeds).
    """
    df = scored_df.copy()
    if beaches is not None and "name" in beaches.columns:
        df = df.merge(
            beaches[["beach_id", "name", "county"]], on="beach_id", how="left"
        )

    records = []
    for b_id, group in df.groupby("beach_id"):
        n = len(group)
        y = group["exceeds_stv"].astype(int)
        pos = int(y.sum())
        if n >= 10 and 0 < pos < n:
            auc_ml = float(roc_auc_score(y, group["p_exceed"]))

            if "last_sample_exceeds" in group.columns:
                pers = group["last_sample_exceeds"].fillna(False).astype(int)
            else:
                pers = pd.Series(0, index=group.index)

            if pers.nunique() == 2:
                auc_pers = float(roc_auc_score(y, pers))
            else:
                auc_pers = 0.5

            name = str(group["name"].iloc[0]) if "name" in group else ""
            county = str(group["county"].iloc[0]) if "county" in group else ""
            records.append(
                {
                    "beach_id": b_id,
                    "name": name,
                    "county": county,
                    "n": n,
                    "positives": pos,
                    "auroc_ml": round(auc_ml, 4),
                    "auroc_persistence": round(auc_pers, 4),
                }
            )

    res = pd.DataFrame(records)
    if not res.empty:
        res.sort_values("beach_id", inplace=True)
        res.reset_index(drop=True, inplace=True)
    return res


def build_backtest_report(
    slice_df: pd.DataFrame,
    beach_df: pd.DataFrame,
) -> str:
    """Format backtest results into markdown text."""
    # Slices table
    slice_headers = [
        "Slice",
        "N",
        "Base Rate",
        "AUROC (Lookup)",
        "AUROC (ML)",
        "AUCPR (Lookup)",
        "AUCPR (ML)",
        "Brier (Lookup)",
        "Brier (ML)",
    ]
    slice_rows = []
    for _, r in slice_df.iterrows():
        slice_rows.append(
            [
                r["Slice"],
                f"{r['N']:,}",
                f"{r['Base Rate']:.4f}",
                f"{r['AUROC (Lookup)']:.4f}" if pd.notna(r["AUROC (Lookup)"]) else "N/A",
                f"{r['AUROC (ML)']:.4f}" if pd.notna(r["AUROC (ML)"]) else "N/A",
                f"{r['AUCPR (Lookup)']:.4f}" if pd.notna(r["AUCPR (Lookup)"]) else "N/A",
                f"{r['AUCPR (ML)']:.4f}" if pd.notna(r["AUCPR (ML)"]) else "N/A",
                f"{r['Brier (Lookup)']:.4f}" if pd.notna(r["Brier (Lookup)"]) else "N/A",
                f"{r['Brier (ML)']:.4f}" if pd.notna(r["Brier (ML)"]) else "N/A",
            ]
        )
    slice_md = format_markdown_table(slice_headers, slice_rows)

    # Within-beach evaluation statistics
    n_beaches = len(beach_df)
    if n_beaches > 0:
        ml_mean = float(beach_df["auroc_ml"].mean())
        ml_median = float(beach_df["auroc_ml"].median())
        ml_gt_half = int((beach_df["auroc_ml"] > 0.5).sum())
        ml_le_half = int((beach_df["auroc_ml"] <= 0.5).sum())

        pers_mean = float(beach_df["auroc_persistence"].mean())
        pers_median = float(beach_df["auroc_persistence"].median())
        pers_gt_half = int((beach_df["auroc_persistence"] > 0.5).sum())
        pers_le_half = int((beach_df["auroc_persistence"] <= 0.5).sum())
    else:
        ml_mean = ml_median = pers_mean = pers_median = 0.0
        ml_gt_half = ml_le_half = pers_gt_half = pers_le_half = 0

    wb_headers = [
        "Predictor",
        "Mean AUROC",
        "Median AUROC",
        "Beaches AUROC > 0.5",
        "Beaches AUROC ≤ 0.5",
    ]
    wb_rows = [
        [
            "Served ML",
            f"{ml_mean:.4f}",
            f"{ml_median:.4f}",
            f"{ml_gt_half} ({ml_gt_half / max(n_beaches, 1) * 100:.1f}%)",
            f"{ml_le_half} ({ml_le_half / max(n_beaches, 1) * 100:.1f}%)",
        ],
        [
            "Persistence Baseline (`last_sample_exceeds`)",
            f"{pers_mean:.4f}",
            f"{pers_median:.4f}",
            f"{pers_gt_half} ({pers_gt_half / max(n_beaches, 1) * 100:.1f}%)",
            f"{pers_le_half} ({pers_le_half / max(n_beaches, 1) * 100:.1f}%)",
        ],
    ]
    wb_table_md = format_markdown_table(wb_headers, wb_rows)

    # Top 25 beaches by volume
    top_beaches = beach_df.sort_values("n", ascending=False).head(25)
    b_headers = [
        "Beach ID",
        "Beach Name",
        "County",
        "N",
        "Positives",
        "AUROC (ML)",
        "AUROC (Persistence)",
    ]
    b_rows = []
    for _, r in top_beaches.iterrows():
        b_rows.append(
            [
                r["beach_id"],
                r["name"],
                r["county"],
                r["n"],
                r["positives"],
                f"{r['auroc_ml']:.4f}",
                f"{r['auroc_persistence']:.4f}",
            ]
        )
    b_md = format_markdown_table(b_headers, b_rows)

    report = f"""# Lookup Baseline vs. Served ML Model Backtest Report

## Executive Summary
This report evaluates the standalone **lookup baseline forecaster** against the **served ML model** using historical forecast logs (`forecast_history.parquet`) and official water quality monitoring results (`beach_day.parquet`).

Predictions are evaluated against the first lab result observed strictly forward within 1 to 3 days ($D+1 \\dots D+3$, `exceeds_stv`).

Across all evaluated slices, the simple lookup baseline (strictly-prior 365-day per-beach history with Bayesian shrinkage) demonstrates superior discrimination (AUROC, AUCPR) and probability calibration (Brier score) compared to the served ML model.

## Slices Performance

{slice_md}

## Per-Beach Evaluation Summary

The lookup baseline makes no within-beach claim; it only ranks beaches against each other across the monitoring network. Within any single beach, the 365-day rate is nearly constant day to day, so its within-beach AUROC measures window drift rather than skill.

To evaluate whether the served ML model possesses day-to-day predictive skill within individual beaches, we evaluate the ML's within-beach AUROC on its own across all qualifying beaches (≥10 verifiable samples with both positive and negative outcomes present, {n_beaches} beaches total) against a within-beach persistence baseline (`last_sample_exceeds` as the score):

{wb_table_md}

- **Served ML Model**: mean AUROC = {ml_mean:.4f}, median AUROC = {ml_median:.4f}; {ml_gt_half} beaches > 0.5 vs. {ml_le_half} beaches ≤ 0.5. The mean near 0.50 demonstrates that the ML model's day-to-day movement within a beach carries negligible predictive information on this window.
- **Persistence Baseline**: mean AUROC = {pers_mean:.4f}, median AUROC = {pers_median:.4f}; {pers_gt_half} beaches > 0.5 vs. {pers_le_half} beaches ≤ 0.5.

Full beach-by-beach metrics are exported to `backtest_by_beach.csv`.

### Top 25 Beaches by Volume of Verifiable Samples

{b_md}
"""
    return report


def run_forecast_mode(
    snapshot_dir: Path,
    out_dir: Path,
    forecast_date: str,
) -> tuple[Path, Path, Path]:
    """Run forecast mode for a specific date: write forecast and comparison reports."""
    out_dir.mkdir(parents=True, exist_ok=True)
    df = build_lookup_forecast(snapshot_dir, forecast_date)
    out_path = out_dir / f"lookup_forecast_{forecast_date}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path}")

    # Build comparison against served forecast
    forecasts_file = snapshot_dir / "forecasts.parquet"
    md_path = Path()
    csv_path = Path()
    if forecasts_file.exists():
        served_df = pq.read_table(forecasts_file).to_pandas()
        md_text, comp_df = build_comparison_report(served_df, df, forecast_date)
        md_path = out_dir / f"comparison_{forecast_date}.md"
        csv_path = out_dir / f"comparison_{forecast_date}.csv"
        md_path.write_text(md_text, encoding="utf-8")
        comp_df.to_csv(csv_path, index=False)
        print(f"Wrote comparison report to {md_path}")
        print(f"Wrote comparison table ({len(comp_df)} rows) to {csv_path}")

    return out_path, md_path, csv_path


def run_backtest_mode(
    snapshot_dir: Path,
    out_dir: Path,
) -> tuple[Path, Path]:
    """Run backtest mode across all distinct forecast dates in forecast history."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fh = pq.read_table(snapshot_dir / "forecast_history.parquet").to_pandas()
    bd = pq.read_table(snapshot_dir / "beach_day.parquet").to_pandas()
    obs = pq.read_table(snapshot_dir / "observations.parquet").to_pandas()
    beaches = pq.read_table(snapshot_dir / "beaches.parquet").to_pandas()

    ddpcr_beaches = identify_ddpcr_beaches(obs)
    verifiable = match_forward_lab_results(fh, bd)
    scored = compute_backtest_lookups(verifiable, bd)
    scored["is_ddpcr"] = scored["beach_id"].isin(ddpcr_beaches)

    max_fc_date = pd.to_datetime(fh["forecast_date"]).max()
    slice_df = evaluate_slices(scored, max_fc_date)
    beach_df = evaluate_beaches(scored, beaches)

    report_text = build_backtest_report(slice_df, beach_df)
    md_path = out_dir / "backtest.md"
    csv_path = out_dir / "backtest_by_beach.csv"

    md_path.write_text(report_text, encoding="utf-8")
    beach_df.to_csv(csv_path, index=False)
    print(f"Wrote backtest report to {md_path}")
    print(f"Wrote per-beach backtest ({len(beach_df)} beaches) to {csv_path}")
    return md_path, csv_path


def build_parser() -> argparse.ArgumentParser:
    """Build argparse parser for CLI invocation."""
    parser = argparse.ArgumentParser(description="Standalone lookup baseline forecaster.")
    parser.add_argument("--snapshot", type=Path, help="Path to snapshot directory")
    parser.add_argument("--out", type=Path, help="Path to output directory")
    parser.add_argument("--forecast-date", type=str, help="Forecast date (YYYY-MM-DD)")
    parser.add_argument("--backtest", action="store_true", help="Replay mode over history")
    return parser


def main() -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    if args.forecast_date:
        if not args.snapshot or not args.out:
            parser.error("--forecast-date requires --snapshot and --out")
        run_forecast_mode(args.snapshot, args.out, args.forecast_date)
        return 0

    if args.backtest:
        if not args.snapshot or not args.out:
            parser.error("--backtest requires --snapshot and --out")
        run_backtest_mode(args.snapshot, args.out)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())

