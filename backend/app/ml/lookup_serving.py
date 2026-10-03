from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any
import argparse

import numpy as np
import pandas as pd
from scipy.stats import beta

from app.core.json_safe import dumps_strict
from app.ml import logit_challenger
from app.ml.calibration import _LOW_THRESHOLD, advisory_floored_probability, risk_band
from app.ml.served_metrics import served_performance_for_versions

LOOKUP_MODEL_VERSION = "lookup-365d-v1"

# What the served number is computed with. "logit" (default since 2026-09-28) is
# the logistic model on top of the lookup (``logit_challenger``); "lookup" is the
# plain lookup. The env var is the rollback switch: set it (e.g. as a repository
# variable the workflow passes through) to "lookup" and the next run serves the
# lookup with no code change.
SERVED_ESTIMATE_METHODS = ("logit", "lookup")
SERVED_ESTIMATE_ENV = "SHORELIFE_SERVED_ESTIMATE"
# Every version this module writes. A forecasts.parquet already carrying one of
# these was written by a previous run of this module, so its p_exceed is NOT the
# ML's and must not be copied into p_exceed_ml (the step runs twice per workflow).
SERVED_ESTIMATE_VERSIONS = frozenset(
    {LOOKUP_MODEL_VERSION, logit_challenger.LOGIT_CHALLENGER_VERSION}
)

# Drivers: the served number is compared with the beach's 12-month record (the
# lookup) and the difference is called out once it is at least this large on the
# logit scale (0.2 is ~a 22% change in the odds). A term is named as a reason only
# when it is that large AND pushes the same way as the net difference, so a driver
# can never say "raises" beside a number that went down.
_DRIVER_MIN_LOGIT = 0.2
_DRIVER_MIN_RAIN_INCHES = 0.1


def _departure_driver(
    shift: float, lab_logit: float, rain_logit: float, season_logit: float,
    last_log10_ratio: float, rain_inches: float, last_exceeds: bool | None,
    has_rain_row: bool,
) -> str | None:
    """One line saying which way today's estimate sits from the 12-month record, and why.

    Upward reasons are the terms that pushed it up. Downward reasons are
    conditions, not terms: the model's baseline is a dry day with an ordinary
    clean result, and the 12-month record averages over rainy and dirty weeks
    too, so on a dry day after a clean test most beaches sit below their record
    for exactly that reason and no single coefficient is "the" cause.
    """
    if abs(shift) < _DRIVER_MIN_LOGIT:
        return None
    reasons: list[str] = []
    if shift > 0:
        if lab_logit >= _DRIVER_MIN_LOGIT:
            if np.isfinite(last_log10_ratio) and last_log10_ratio >= 0:
                reasons.append("last test above the limit")
            else:
                reasons.append("last test close to the limit")
        if rain_inches >= _DRIVER_MIN_RAIN_INCHES and rain_logit >= _DRIVER_MIN_LOGIT:
            reasons.append(f"{rain_inches:.1f} in of rain in the past 3 days")
        if season_logit >= _DRIVER_MIN_LOGIT:
            reasons.append("the wet season")
        head = "Today's estimate is above this beach's 12-month record"
    else:
        if last_exceeds is False:
            reasons.append("last test within the limit")
        if has_rain_row and rain_inches < _DRIVER_MIN_RAIN_INCHES:
            reasons.append("no rain in the past 3 days")
        if season_logit <= -_DRIVER_MIN_LOGIT:
            reasons.append("the dry season")
        head = "Today's estimate is below this beach's 12-month record"
    return f"{head}: {', '.join(reasons)}" if reasons else head


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return float(np.log(p / (1 - p)))


def _expit(x: float) -> float:
    return float(1.0 / (1.0 + np.exp(-x)))


def _resolve_method(method: str | None) -> str:
    chosen = (method or os.environ.get(SERVED_ESTIMATE_ENV) or "logit").strip().lower()
    if chosen not in SERVED_ESTIMATE_METHODS:
        raise ValueError(f"unknown served-estimate method {chosen!r}; expected one of {SERVED_ESTIMATE_METHODS}")
    return chosen


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

        beta_lower = float(beta.ppf(0.05, a=a_param, b=b_param))
        beta_upper = float(beta.ppf(0.95, a=a_param, b=b_param))
        p_exceed_upper = max(beta_upper, base)
        p_exceed_lower = min(beta_lower, base)

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
                # The Beta quantiles before they are widened to contain the
                # (persistence-floored) base; the logistic path shifts these.
                "beta_lower": beta_lower,
                "beta_upper": beta_upper,
            }
        )

    return pd.DataFrame(rows)


def posted_beach_ids_for(curated_dir: Path | str, forecast_date) -> set[str]:
    """Beaches whose advisory floor applies on forecast_date.

    Advisory floor (export time, same rule as today): a beach is posted if
    advisories.parquet has a row for it with status == "active" and
    started_at <= D.
    """
    advisories_path = Path(curated_dir) / "advisories.parquet"
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
    return posted_beach_ids


def _logit_estimate(
    curated_path: Path, forecast_date, beach_ids: list[str], lookup_df: pd.DataFrame
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    """The logistic estimate indexed by beach_id, or (None, reason) to serve the lookup.

    Any failure here — a missing artifact, a guard in ``estimate_for_serving``, or
    the model's lookup term disagreeing with ``compute_lookup`` — falls back to the
    plain lookup rather than failing the daily run: the lookup is the incumbent and
    is always computable, so a broken challenger must never cost the day's forecast.
    """
    try:
        est = logit_challenger.estimate_for_serving(curated_path, forecast_date, beach_ids)
    except Exception as exc:  # noqa: BLE001 — any failure means "serve the lookup"
        return None, {"fallback_reason": f"{type(exc).__name__}: {exc}"}
    frame = est.frame.set_index("beach_id")
    # The model's offset must BE the served lookup, or its departures are measured
    # from the wrong baseline. Both are computed from the same rows by the same
    # rule; a disagreement means one of them changed without the other.
    ours = frame["lookup"].reindex(lookup_df["beach_id"]).to_numpy(float)
    theirs = lookup_df["p_lookup"].to_numpy(float)
    if not np.allclose(ours, theirs, rtol=0.0, atol=1e-9):
        worst = float(np.nanmax(np.abs(ours - theirs)))
        return None, {"fallback_reason": f"lookup term diverged from compute_lookup (max |diff| {worst:.3g})"}
    meta = {
        "coefficients": est.coefficients,
        "train_rows": est.train_rows,
        "rain_coverage": est.rain_coverage,
    }
    if est.rain_coverage < 0.5:
        print(
            f"lookup_serving: WARNING only {est.rain_coverage:.0%} of beaches have a rain row for "
            f"{forecast_date}; the rest are scored as dry",
            file=sys.stderr,
        )
    return frame, meta


# The committed walk-forward backtest (scripts/compare_logit_challenger.py).
# Its path is fixed relative to data/curated in both the repo and CI.
_BACKTEST_RESULTS = Path("..") / "experiments" / "logit_challenger" / "results.json"


def _backtest_summary(curated_path: Path) -> dict[str, Any] | None:
    """Headline forward-outcome numbers from the committed backtest, or None."""
    path = curated_path / _BACKTEST_RESULTS
    try:
        results = json.loads(path.read_text())
        overall = results["outcomes"]["forward_1_3d"]["all"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    keys = ("auroc", "aucpr", "brier", "within_beach_auroc")
    return {
        "source": "scripts/compare_logit_challenger.py (walk-forward, monthly refit)",
        "window": results.get("window"),
        "outcome": "first lab result 1-3 days after each forecast",
        "n": overall.get("n"),
        "base_rate": overall.get("base_rate"),
        "logit": {k: overall.get("challenger", {}).get(k) for k in keys},
        "lookup": {k: overall.get("lookup", {}).get(k) for k in keys},
        "same_rows": _same_rows_block(results),
    }


def _same_rows_block(results: dict[str, Any]) -> dict[str, Any] | None:
    """Logistic, lookup AND the ML that actually served, on identical forward rows.

    The backtest's "served-log overlap" slice: the forecast_history window where
    the ML challenger's served probability exists, scored with the same forward
    outcome. This is the only like-for-like ML comparison -- the ML's own
    production_metrics are a temporal test split on sample-days, a different
    population at a higher base rate, so its 0.79-ish AUCPR there is not
    comparable to these.
    """
    try:
        overlap = results["outcomes"]["forward_1_3d"]["served-log overlap"]
    except (KeyError, TypeError):
        return None
    keys = ("auroc", "aucpr", "brier", "within_beach_auroc")
    return {
        "window": overlap.get("window"),
        "n": overlap.get("n"),
        "base_rate": overlap.get("base_rate"),
        "logit": {k: overlap.get("challenger", {}).get(k) for k in keys},
        "lookup": {k: overlap.get("lookup", {}).get(k) for k in keys},
        "ml": {k: overlap.get("served_ml", {}).get(k) for k in keys},
    }


def apply_lookup_to_served(curated_dir: Path | str, method: str | None = None) -> dict[str, Any]:
    """Serve the per-beach estimate: the logistic model on the lookup, else the lookup.

    ``method`` is "logit" or "lookup"; None reads ``SHORELIFE_SERVED_ESTIMATE``
    and defaults to "logit". The lookup is always computed: it is the logistic
    model's offset, the fallback, and is kept as ``p_exceed_lookup``.
    """
    method = _resolve_method(method)
    curated_path = Path(curated_dir)
    forecasts_path = curated_path / "forecasts.parquet"
    if not forecasts_path.exists():
        raise FileNotFoundError(f"Missing forecasts file: {forecasts_path}")

    forecasts = pd.read_parquet(forecasts_path)
    if forecasts.empty:
        raise ValueError(f"Empty forecasts file: {forecasts_path}")

    # a. reads forecasts.parquet; unless a previous run of this module already
    # wrote it, copies p_exceed->p_exceed_ml and risk_band->risk_band_ml
    # (idempotent: a second run must not overwrite the ML copies with served
    # values — the workflow runs this step twice, and either run may have served
    # either method)
    is_already_served = (
        "model_version" in forecasts.columns
        and forecasts["model_version"].isin(SERVED_ESTIMATE_VERSIONS).all()
    )
    if not is_already_served or "p_exceed_ml" not in forecasts.columns:
        forecasts["p_exceed_ml"] = forecasts["p_exceed"].copy()
        forecasts["risk_band_ml"] = forecasts["risk_band"].copy()

    forecast_date = forecasts["forecast_date"].iloc[0]

    beach_day_path = curated_path / "beach_day.parquet"
    if beach_day_path.exists():
        beach_day = pd.read_parquet(beach_day_path)
    else:
        beach_day = pd.DataFrame(columns=["beach_id", "sample_date", "exceeds_stv"])

    most_recent_label_method: dict[str, str] = {}
    if not beach_day.empty and "beach_id" in beach_day.columns and "label_method" in beach_day.columns:
        sort_cols = ["sample_date"]
        if "sample_time" in beach_day.columns:
            sort_cols.append("sample_time")
        bd_sorted = beach_day.dropna(subset=["beach_id"]).sort_values(sort_cols)
        last_methods = bd_sorted.groupby("beach_id")["label_method"].last()
        most_recent_label_method = {
            str(k): str(v) for k, v in last_methods.items() if pd.notna(v)
        }

    beach_ids = forecasts["beach_id"].tolist()
    lookup_df = compute_lookup(
        beach_day=beach_day,
        forecast_date=forecast_date,
        beach_ids=beach_ids,
        window_days=365,
        prior_strength=5.0,
    )
    lookup_records = lookup_df.set_index("beach_id").to_dict("index")

    logit_frame: pd.DataFrame | None = None
    logit_meta: dict[str, Any] = {}
    if method == "logit":
        logit_frame, logit_meta = _logit_estimate(
            curated_path, forecast_date, [str(b) for b in beach_ids], lookup_df
        )
        if logit_frame is None:
            print(
                f"lookup_serving: logistic estimate unavailable, serving the lookup "
                f"({logit_meta['fallback_reason']})",
                file=sys.stderr,
            )
    served_version = (
        logit_challenger.LOGIT_CHALLENGER_VERSION if logit_frame is not None else LOOKUP_MODEL_VERSION
    )

    posted_beach_ids = posted_beach_ids_for(curated_path, forecast_date)

    p_exceed_list: list[float] = []
    p_exceed_raw_list: list[float] = []
    p_exceed_lookup_list: list[float] = []
    p_exceed_lower_list: list[float] = []
    p_exceed_upper_list: list[float] = []
    risk_band_list: list[str] = []
    persistence_floor_applied_list: list[bool] = []
    advisory_floor_applied_list: list[bool] = []
    top_drivers_list: list[list[str]] = []

    for bid in beach_ids:
        lk = lookup_records[bid]
        last_date = lk["last_sample_date"]
        last_exc = lk["last_exceeds"]
        p_lower = float(lk["p_exceed_lower"])
        p_upper = float(lk["p_exceed_upper"])
        terms: dict[str, Any] | None = None

        if logit_frame is None:
            base = float(lk["base"])
            p_floor = bool(lk["persistence_floor_applied"])
        else:
            row = logit_frame.loc[str(bid)]
            p_model = float(row["p_model"])
            # Same product rule as the lookup: a beach whose last test exceeded
            # is never Low.
            base = float(
                logit_challenger.apply_persistence_floor(
                    np.array([p_model]), np.array([1.0 if last_exc is True else 0.0])
                )[0]
            )
            p_floor = base > p_model
            # The lookup's Beta interval, carried through the model's departure
            # from the lookup on the logit scale. It still describes uncertainty
            # in the beach's rate (n tests), not in the four coefficients, which
            # are fit on ~117k rows and move by a few hundredths between refits.
            # Shift the raw quantiles, not the bounds compute_lookup already
            # widened to contain its own persistence floor.
            shift = _logit(p_model) - _logit(float(lk["p_lookup"]))
            p_lower = _expit(_logit(float(lk["beta_lower"])) + shift)
            p_upper = _expit(_logit(float(lk["beta_upper"])) + shift)
            terms = {
                "lab_logit": float(row["lab_logit"]),
                "rain_logit": float(row["rain_logit"]),
                "season_logit": float(row["season_logit"]),
                "last_log10_ratio": float(row["last_log10_ratio"]),
                "rain_inches": float(row["rain_inches_72h"]),
                "last_exceeds": last_exc,
                "has_rain_row": bool(row["has_rain_row"]),
            }
        p_upper = max(p_upper, base)
        p_lower = min(p_lower, base)
        p_raw = base

        is_posted = bid in posted_beach_ids
        if is_posted:
            p_exceed, adv_floor_applied = advisory_floored_probability(base, True)
        else:
            p_exceed = base
            adv_floor_applied = False

        r_band = risk_band(p_exceed)

        # Explain the number users see, so compare AFTER the floors: a posted
        # beach is explained by its advisory, not by the model, and a floored
        # beach must never read "below its record" beside a floored number.
        departure: str | None = None
        if terms is not None and not adv_floor_applied:
            departure = _departure_driver(
                _logit(base) - _logit(float(lk["base"])), **terms
            )

        n = int(lk["n"])
        pos = int(lk["pos"])
        drivers: list[str] = []
        if n == 0:
            drivers.append("No lab tests in the past 12 months — using the statewide average")
        else:
            drivers.append(
                f"Above the safety limit in {pos} of {n} lab tests over the past 12 months"
            )

        if pd.notna(last_date) and last_exc is not None:
            last_dt = pd.to_datetime(last_date)
            status_str = "above the limit" if last_exc else "within the limit"
            drivers.append(f"Last test {last_dt.strftime('%b')} {last_dt.day}: {status_str}")

        if departure is not None:
            drivers.append(departure)

        if 0 < n < 10:
            drivers.append("Few recent tests — estimate leans on the statewide average")

        p_exceed_list.append(p_exceed)
        p_exceed_raw_list.append(p_raw)
        p_exceed_lookup_list.append(float(lk["base"]))
        p_exceed_lower_list.append(p_lower)
        p_exceed_upper_list.append(p_upper)
        risk_band_list.append(r_band)
        persistence_floor_applied_list.append(p_floor)
        advisory_floor_applied_list.append(adv_floor_applied)
        top_drivers_list.append(drivers)

    forecasts["p_exceed"] = p_exceed_list
    forecasts["p_exceed_raw"] = p_exceed_raw_list
    # The plain lookup (persistence-floored, no advisory floor) on every row,
    # whichever method served, so the two can be compared on the served log.
    forecasts["p_exceed_lookup"] = p_exceed_lookup_list
    forecasts["p_exceed_lower"] = p_exceed_lower_list
    forecasts["p_exceed_upper"] = p_exceed_upper_list
    forecasts["risk_band"] = risk_band_list
    forecasts["persistence_floor_applied"] = persistence_floor_applied_list
    forecasts["advisory_floor_applied"] = advisory_floor_applied_list
    forecasts["model_version"] = served_version
    forecasts["served_offset_weight"] = np.nan
    forecasts["predicted_log_enterococcus"] = np.nan
    forecasts["lower_prediction_interval"] = np.nan
    forecasts["upper_prediction_interval"] = np.nan
    forecasts["prediction_interval_level"] = np.nan
    forecasts["top_drivers"] = top_drivers_list
    forecasts["label_method"] = [
        most_recent_label_method.get(str(bid)) for bid in beach_ids
    ]

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
            if "p_exceed_lookup" not in history.columns:
                history["p_exceed_lookup"] = np.nan
            if "persistence_floor_applied" not in history.columns:
                history["persistence_floor_applied"] = None
            if "label_method" not in history.columns:
                history["label_method"] = None

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
                needs_p_ml = prior_p_ml.isna() | ~prior_v.isin(SERVED_ESTIMATE_VERSIONS)

                for col in [
                    "p_exceed",
                    "p_exceed_raw",
                    "p_exceed_lookup",
                    "risk_band",
                    "model_version",
                    "persistence_floor_applied",
                    "served_offset_weight",
                    "label_method",
                ]:
                    mapped = hist_keys[matched_mask].map(fc_lookup[col])
                    if col in ("p_exceed", "p_exceed_raw", "p_exceed_lookup", "served_offset_weight"):
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

            # For all OTHER history rows where p_exceed_ml is null and this module
            # did not write the row, backfill p_exceed_ml = p_exceed (those rows
            # served the ML)
            other_mask = (
                (~matched_mask)
                & history["p_exceed_ml"].isna()
                & ~history["model_version"].isin(SERVED_ESTIMATE_VERSIONS)
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
        "name": served_version,
        "method_requested": method,
        # Set only when "logit" was requested and the lookup served instead.
        "fallback_reason": logit_meta.get("fallback_reason"),
        "lookup": {"name": LOOKUP_MODEL_VERSION, "window_days": 365, "prior_strength": 5},
        "window_days": 365,
        "prior_strength": 5,
        "forecast_date": str(forecast_date),
        "rows": n_rows,
        "posted": k,
        "persistence_floored": m,
        "applied_at": applied_at,
    }
    if logit_frame is not None:
        health["serving_method"]["logit"] = {
            "features": list(logit_challenger.FEATURE_COLUMNS),
            **logit_meta,
            # How far the served number moved from the lookup today, so a
            # drifting fit shows up in the health file before anyone reads a map.
            "mean_p_exceed_raw": float(np.mean(p_exceed_raw_list)),
            "mean_p_exceed_lookup": float(np.mean(p_exceed_lookup_list)),
            "band_changes_vs_lookup": int(
                sum(
                    risk_band(p) != risk_band(q)
                    for p, q in zip(p_exceed_raw_list, p_exceed_lookup_list)
                )
            ),
        }

    # How the logistic model has done on the forecasts it actually served, and
    # the walk-forward backtest that justified serving it — both on the record
    # the web's research page reads, so the served method shows results, not
    # just a name.
    try:
        live = served_performance_for_versions(
            curated_path,
            frozenset({logit_challenger.LOGIT_CHALLENGER_VERSION}),
            compare_columns=("p_exceed_lookup", "p_exceed_ml"),
        )
    except Exception as exc:  # noqa: BLE001 — a scoring failure must not cost the forecast
        print(f"lookup_serving: live scoring failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        live = None
    if live is not None:
        health["serving_method"]["live"] = live
    backtest = _backtest_summary(curated_path)
    if backtest is not None:
        health["serving_method"]["backtest"] = backtest

    tmp_health = health_path.with_suffix(".json.tmp")
    tmp_health.write_text(dumps_strict(health))
    os.replace(tmp_health, health_path)

    summary = {
        "serving_method": served_version,
        "method_requested": method,
        "fallback_reason": logit_meta.get("fallback_reason"),
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
    parser = argparse.ArgumentParser(description="Serve the per-beach estimate")
    parser.add_argument("--curated", type=Path, required=True, help="Path to curated data directory")
    parser.add_argument(
        "--method",
        choices=SERVED_ESTIMATE_METHODS,
        default=None,
        help=f"logit (default) or lookup; overrides ${SERVED_ESTIMATE_ENV}",
    )
    args = parser.parse_args()
    summary = apply_lookup_to_served(args.curated, method=args.method)
    print(dumps_strict(summary))


if __name__ == "__main__":
    main()

