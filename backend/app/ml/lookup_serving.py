from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
from typing import Any
import argparse

import numpy as np
import pandas as pd
from scipy.stats import beta

from app.core.json_safe import dumps_strict
from app.ml.calibration import _LOW_THRESHOLD, advisory_floored_probability, risk_band

LOOKUP_MODEL_VERSION = "lookup-365d-v1"


def compute_lookup(
    beach_day: pd.DataFrame,
    forecast_date: str | date | pd.Timestamp,
    beach_ids: Sequence[str] | pd.Series | Iterable[str],
    window_days: int = 365,
    prior_strength: float = 5.0,
) -> pd.DataFrame:
    """Compute per-beach empirical lookup estimates over a trailing window strictly before forecast_date.

    Pure function returning one row per requested beach_id with lookup statistics,
    persistence floor, and Beta credible interval.
    """
    forecast_dt = pd.to_datetime(forecast_date).normalize()
    cutoff_start = forecast_dt - pd.Timedelta(days=window_days)

    requested_beach_ids = list(beach_ids)

    if beach_day is None or len(beach_day) == 0:
        window_df = pd.DataFrame(columns=["beach_id", "sample_date", "exceeds_stv"])
        g = 0.0
    else:
        sample_dates = pd.to_datetime(beach_day["sample_date"], errors="coerce").dt.normalize()
        mask = (sample_dates >= cutoff_start) & (sample_dates < forecast_dt)
        window_df = beach_day.loc[mask]
        if len(window_df) == 0:
            g = 0.0
        else:
            g = float(window_df["exceeds_stv"].astype(bool).mean())

    if len(window_df) > 0:
        sort_cols = ["sample_date"]
        if "sample_time" in window_df.columns:
            sort_cols.append("sample_time")
        sorted_window = window_df.sort_values(sort_cols)
        grouped = sorted_window.groupby("beach_id")
        n_map: dict[str, int] = grouped.size().to_dict()
        pos_map: dict[str, int] = (
            grouped["exceeds_stv"].apply(lambda s: int(s.astype(bool).sum())).to_dict()
        )
        last_row = grouped.last()
        last_date_map: dict[str, Any] = last_row["sample_date"].to_dict()
        last_exc_map: dict[str, Any] = last_row["exceeds_stv"].to_dict()
    else:
        n_map = {}
        pos_map = {}
        last_date_map = {}
        last_exc_map = {}

    rows: list[dict[str, Any]] = []
    for bid in requested_beach_ids:
        n = int(n_map.get(bid, 0))
        pos = int(pos_map.get(bid, 0))
        p_lookup = float((pos + prior_strength * g) / (n + prior_strength))

        if n > 0 and bid in last_date_map:
            last_sample_date = pd.to_datetime(last_date_map[bid])
            last_exceeds: bool | None = bool(last_exc_map[bid])
        else:
            last_sample_date = None
            last_exceeds = None

        if last_exceeds is True:
            base = max(p_lookup, float(_LOW_THRESHOLD))
            persistence_floor_applied = p_lookup < float(_LOW_THRESHOLD)
        else:
            base = p_lookup
            persistence_floor_applied = False

        a_param = pos + prior_strength * g
        b_param = (n - pos) + prior_strength * (1.0 - g)
        if a_param <= 0.0:
            a_param = 1e-6
        if b_param <= 0.0:
            b_param = 1e-6

        p_exceed_lower = float(beta.ppf(0.05, a=a_param, b=b_param))
        p_exceed_upper = float(beta.ppf(0.95, a=a_param, b=b_param))
        p_exceed_upper = max(p_exceed_upper, base)
        p_exceed_lower = min(p_exceed_lower, base)

        rows.append(
            {
                "beach_id": bid,
                "n": n,
                "pos": pos,
                "g": g,
                "p_lookup": p_lookup,
                "last_sample_date": last_sample_date,
                "last_exceeds": last_exceeds,
                "base": base,
                "p_exceed_raw": base,
                "persistence_floor_applied": persistence_floor_applied,
                "p_exceed_lower": p_exceed_lower,
                "p_exceed_upper": p_exceed_upper,
            }
        )

    return pd.DataFrame(rows)


def apply_lookup_to_served(curated_dir: Path | str) -> dict[str, Any]:
    """Apply lookup baseline to served forecast and update downstream artifacts."""
    curated_path = Path(curated_dir)
    forecasts_path = curated_path / "forecasts.parquet"
    if not forecasts_path.exists():
        raise FileNotFoundError(f"Missing forecasts file: {forecasts_path}")

    forecasts = pd.read_parquet(forecasts_path)
    if forecasts.empty:
        raise ValueError(f"Empty forecasts file: {forecasts_path}")

    # a. reads forecasts.parquet; if its model_version is NOT already
    # LOOKUP_MODEL_VERSION, copies p_exceed->p_exceed_ml and
    # risk_band->risk_band_ml (idempotent: a second run must not
    # overwrite the ML copies with lookup values)
    is_already_lookup = (
        "model_version" in forecasts.columns
        and (forecasts["model_version"] == LOOKUP_MODEL_VERSION).all()
    )
    if not is_already_lookup:
        forecasts["p_exceed_ml"] = forecasts["p_exceed"].copy()
        forecasts["risk_band_ml"] = forecasts["risk_band"].copy()
    elif "p_exceed_ml" not in forecasts.columns:
        forecasts["p_exceed_ml"] = forecasts["p_exceed"].copy()
        forecasts["risk_band_ml"] = forecasts["risk_band"].copy()

    forecast_date = forecasts["forecast_date"].iloc[0]

    beach_day_path = curated_path / "beach_day.parquet"
    if beach_day_path.exists():
        beach_day = pd.read_parquet(beach_day_path)
    else:
        beach_day = pd.DataFrame(columns=["beach_id", "sample_date", "exceeds_stv"])

    beach_ids = forecasts["beach_id"].tolist()
    lookup_df = compute_lookup(
        beach_day=beach_day,
        forecast_date=forecast_date,
        beach_ids=beach_ids,
        window_days=365,
        prior_strength=5.0,
    )
    lookup_records = lookup_df.set_index("beach_id").to_dict("index")

    # Advisory floor (export time, same rule as today): a beach is posted if
    # advisories.parquet has a row for it with status == "active" and
    # started_at <= D.
    advisories_path = curated_path / "advisories.parquet"
    posted_beach_ids: set[str] = set()
    if advisories_path.exists():
        advisories = pd.read_parquet(advisories_path)
        if (
            not advisories.empty
            and "status" in advisories.columns
            and "beach_id" in advisories.columns
        ):
            active_adv = advisories[advisories["status"] == "active"]
            if not active_adv.empty:
                if "started_at" in active_adv.columns:
                    started = pd.to_datetime(active_adv["started_at"], errors="coerce")
                    if started.dt.tz is not None:
                        started = started.dt.tz_localize(None)
                    f_date_norm = pd.to_datetime(forecast_date).tz_localize(None).normalize()
                    active_adv = active_adv[started.dt.normalize() <= f_date_norm]
                posted_beach_ids = set(active_adv["beach_id"].dropna().unique())

    p_exceed_list: list[float] = []
    p_exceed_raw_list: list[float] = []
    p_exceed_lower_list: list[float] = []
    p_exceed_upper_list: list[float] = []
    risk_band_list: list[str] = []
    persistence_floor_applied_list: list[bool] = []
    advisory_floor_applied_list: list[bool] = []
    top_drivers_list: list[list[str]] = []

    for bid in beach_ids:
        lk = lookup_records[bid]
        base = float(lk["base"])
        p_raw = base
        p_lower = float(lk["p_exceed_lower"])
        p_upper = float(lk["p_exceed_upper"])
        p_floor = bool(lk["persistence_floor_applied"])

        is_posted = bid in posted_beach_ids
        if is_posted:
            p_exceed, adv_floor_applied = advisory_floored_probability(base, True)
        else:
            p_exceed = base
            adv_floor_applied = False

        r_band = risk_band(p_exceed)

        n = int(lk["n"])
        pos = int(lk["pos"])
        drivers: list[str] = []
        if n == 0:
            drivers.append("No lab tests in the past 12 months — using the statewide average")
        else:
            drivers.append(
                f"Above the safety limit in {pos} of {n} lab tests over the past 12 months"
            )

        last_date = lk["last_sample_date"]
        last_exc = lk["last_exceeds"]
        if pd.notna(last_date) and last_exc is not None:
            last_dt = pd.to_datetime(last_date)
            status_str = "above the limit" if last_exc else "within the limit"
            drivers.append(f"Last test {last_dt.strftime('%b')} {last_dt.day}: {status_str}")

        if 0 < n < 10:
            drivers.append("Few recent tests — estimate leans on the statewide average")

        p_exceed_list.append(p_exceed)
        p_exceed_raw_list.append(p_raw)
        p_exceed_lower_list.append(p_lower)
        p_exceed_upper_list.append(p_upper)
        risk_band_list.append(r_band)
        persistence_floor_applied_list.append(p_floor)
        advisory_floor_applied_list.append(adv_floor_applied)
        top_drivers_list.append(drivers)

    forecasts["p_exceed"] = p_exceed_list
    forecasts["p_exceed_raw"] = p_exceed_raw_list
    forecasts["p_exceed_lower"] = p_exceed_lower_list
    forecasts["p_exceed_upper"] = p_exceed_upper_list
    forecasts["risk_band"] = risk_band_list
    forecasts["persistence_floor_applied"] = persistence_floor_applied_list
    forecasts["advisory_floor_applied"] = advisory_floor_applied_list
    forecasts["model_version"] = LOOKUP_MODEL_VERSION
    forecasts["served_offset_weight"] = np.nan
    forecasts["predicted_log_enterococcus"] = np.nan
    forecasts["lower_prediction_interval"] = np.nan
    forecasts["upper_prediction_interval"] = np.nan
    forecasts["prediction_interval_level"] = np.nan
    forecasts["top_drivers"] = top_drivers_list

    # Atomic write for forecasts.parquet
    tmp_forecasts = forecasts_path.with_suffix(".parquet.tmp")
    forecasts.to_parquet(tmp_forecasts, index=False)
    os.replace(tmp_forecasts, forecasts_path)

    # c. updates forecast_history.parquet
    history_path = curated_path / "forecast_history.parquet"
    history_updated_count = 0
    if history_path.exists():
        history = pd.read_parquet(history_path)
        if not history.empty:
            if "p_exceed_ml" not in history.columns:
                history["p_exceed_ml"] = np.nan

            fc_keys = (
                forecasts["beach_id"].astype(str)
                + "||"
                + forecasts["forecast_date"].astype(str)
                + "||"
                + forecasts["forecast_generated_at"].astype(str)
            )
            hist_keys = (
                history["beach_id"].astype(str)
                + "||"
                + history["forecast_date"].astype(str)
                + "||"
                + history["forecast_generated_at"].astype(str)
            )

            fc_lookup = forecasts.set_index(fc_keys)
            matched_mask = hist_keys.isin(set(fc_keys))
            history_updated_count = int(matched_mask.sum())

            if history_updated_count > 0:
                prior_p_ml = history.loc[matched_mask, "p_exceed_ml"]
                prior_v = history.loc[matched_mask, "model_version"]
                needs_p_ml = prior_p_ml.isna() | (prior_v != LOOKUP_MODEL_VERSION)

                for col in [
                    "p_exceed",
                    "p_exceed_raw",
                    "risk_band",
                    "model_version",
                    "persistence_floor_applied",
                    "served_offset_weight",
                ]:
                    mapped = hist_keys[matched_mask].map(fc_lookup[col])
                    if col in ("p_exceed", "p_exceed_raw", "served_offset_weight"):
                        history.loc[matched_mask, col] = pd.to_numeric(
                            mapped, errors="coerce"
                        )
                    elif col == "persistence_floor_applied":
                        history.loc[matched_mask, col] = mapped.astype(bool)
                    else:
                        history.loc[matched_mask, col] = mapped

                matched_indices = history.index[matched_mask]
                update_ml_indices = matched_indices[needs_p_ml.to_numpy()]
                if len(update_ml_indices) > 0:
                    ml_mapped = hist_keys[update_ml_indices].map(
                        fc_lookup["p_exceed_ml"]
                    )
                    history.loc[update_ml_indices, "p_exceed_ml"] = pd.to_numeric(
                        ml_mapped, errors="coerce"
                    )

            # For all OTHER history rows where p_exceed_ml is null and model_version != LOOKUP_MODEL_VERSION,
            # backfill p_exceed_ml = p_exceed (those rows served the ML)
            other_mask = (
                (~matched_mask)
                & history["p_exceed_ml"].isna()
                & (history["model_version"] != LOOKUP_MODEL_VERSION)
            )
            history.loc[other_mask, "p_exceed_ml"] = pd.to_numeric(
                history.loc[other_mask, "p_exceed"], errors="coerce"
            )

            tmp_history = history_path.with_suffix(".parquet.tmp")
            history.to_parquet(tmp_history, index=False)
            os.replace(tmp_history, history_path)

    # e. writes system_health.json["serving_method"]
    health_path = curated_path / "system_health.json"
    health: dict[str, Any] = {}
    if health_path.exists():
        try:
            health = json.loads(health_path.read_text())
        except Exception:
            health = {}

    k = int(forecasts["beach_id"].isin(posted_beach_ids).sum())
    m = int(forecasts["persistence_floor_applied"].sum())
    n_rows = len(forecasts)
    applied_at = datetime.now(UTC).isoformat()

    health["serving_method"] = {
        "name": LOOKUP_MODEL_VERSION,
        "window_days": 365,
        "prior_strength": 5,
        "forecast_date": str(forecast_date),
        "rows": n_rows,
        "posted": k,
        "persistence_floored": m,
        "applied_at": applied_at,
    }

    tmp_health = health_path.with_suffix(".json.tmp")
    tmp_health.write_text(dumps_strict(health))
    os.replace(tmp_health, health_path)

    summary = {
        "serving_method": LOOKUP_MODEL_VERSION,
        "forecast_date": str(forecast_date),
        "rows": n_rows,
        "posted": k,
        "persistence_floored": m,
        "advisory_floored": int(forecasts["advisory_floor_applied"].sum()),
        "history_updated": history_updated_count,
        "applied_at": applied_at,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve lookup estimate")
    parser.add_argument("--curated", type=Path, required=True, help="Path to curated data directory")
    args = parser.parse_args()
    summary = apply_lookup_to_served(args.curated)
    print(dumps_strict(summary))


if __name__ == "__main__":
    main()

