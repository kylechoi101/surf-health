"""Accountability loop for the *served* forecast (model_truth.md audit, 2026-07-23).

The shipped backtests score sample-days — rows where a lab sample was taken that
morning, so the lagged risk-history features are fresh. The product serves every
beach every day, where the last sample is a median ~9 days old. Scored against
what actually followed, the served regime ran AUCPR ~0.24 (vs 0.63-0.70 claimed)
and the top of the probability scale was ~3x hot (served ~0.98 -> ~0.36
realized). This module closes that loop:

- ``append_forecast_history``: append-only log of what ``forecasts.parquet``
  actually served (post release-gate), keyed by beach/forecast-day/issue-time.
- ``served_performance``: score that log against the lab results that followed
  (same-day and strictly-forward D+1..D+3) -> ``system_health.json
  ["served_metrics"]`` — the deployment-regime truth, refreshed daily.
- ``fit_serving_calibration`` / ``apply_serving_calibration``: daily isotonic
  refit of served probability -> realized exceedance rate, applied at forecast
  export so the published ``p_exceed`` means what it says where it is served.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from app.core.json_safe import write_json
from app.ml.evaluation import sensitivity_at_specificity

HISTORY_FILE = "forecast_history.parquet"
CALIBRATION_FILE = "serving_calibration.json"

# Columns persisted per served forecast row. ``p_exceed`` is what the apps
# banded on (post every floor + serving calibration); ``p_exceed_precal`` is the
# pre-serving-calibration probability the daily isotonic refit trains on. For
# legacy rows (before the calibration layer existed) ``p_exceed_raw`` is that
# same quantity, so the fit falls back precal -> raw -> p_exceed.
_HISTORY_COLUMNS = [
    "beach_id",
    "forecast_date",
    "p_exceed",
    "p_exceed_raw",
    "p_exceed_precal",
    "risk_band",
    "sample_age_days",
    "model_version",
    "forecast_generated_at",
]
_PROBABILITY_COLUMNS = ("p_exceed", "p_exceed_raw", "p_exceed_precal")

# Lab results trail the forecast by days. A forecast row is matched to its
# same-day result when one exists, else the first result in D+1..D+3 — near
# enough for the daily risk statement, provably not visible to the forecast.
FORWARD_MATCH_DAYS = 3
# Trailing window for the isotonic refit: long enough for ~100+ positives at
# the ~6% served base rate, short enough to track model/regime drift.
_FIT_WINDOW_DAYS = 120
# Below these the fitted map is noise — serve the uncalibrated probability.
_MIN_FIT_PAIRS = 500
_MIN_FIT_POSITIVES = 25

# Fixed reliability-bin edges aligned with the public risk bands.
_BIN_EDGES = (0.0, 0.05, 0.10, 0.20, 0.30, 0.70, 1.0001)


def daily_outcomes(observations: pd.DataFrame) -> pd.DataFrame:
    """Worst lab outcome per (beach_id, day): did ANY sample exceed the STV."""
    frame = observations.loc[
        observations["exceeds_stv"].notna(), ["beach_id", "sample_date", "exceeds_stv"]
    ].copy()
    frame["date"] = pd.to_datetime(frame["sample_date"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["date"])
    grouped = frame.groupby(["beach_id", "date"], as_index=False)["exceeds_stv"].max()
    grouped["exceeded"] = grouped["exceeds_stv"].astype(bool).astype(int)
    return grouped[["beach_id", "date", "exceeded"]]


def append_forecast_history(curated_dir: Path) -> int:
    """Append the on-disk forecasts.parquet to the served-forecast log.

    Reads the file AFTER the release-gate decision, so the log records what is
    actually serving — the fresh forecast, or the gate-frozen previous one
    (whose rows are already logged, making the append a no-op). Idempotent:
    rows are keyed by (beach_id, forecast_date, forecast_generated_at).
    Returns the number of rows added.
    """
    forecast_path = curated_dir / "forecasts.parquet"
    if not forecast_path.exists():
        return 0
    current = pd.read_parquet(forecast_path)
    if current.empty:
        return 0
    for column in _HISTORY_COLUMNS:
        if column not in current.columns:
            current[column] = None
    current = current[_HISTORY_COLUMNS].copy()
    for column in _PROBABILITY_COLUMNS:
        current[column] = pd.to_numeric(current[column], errors="coerce")
    current["sample_age_days"] = pd.to_numeric(current["sample_age_days"], errors="coerce")

    history_path = curated_dir / HISTORY_FILE
    prior_rows = 0
    if history_path.exists():
        history = pd.read_parquet(history_path)
        prior_rows = len(history)
        combined = pd.concat([history, current], ignore_index=True)
    else:
        combined = current
    combined = combined.drop_duplicates(
        subset=["beach_id", "forecast_date", "forecast_generated_at"], keep="last"
    )
    # Atomic write — a crash mid-write must not corrupt the accountability log.
    tmp_path = history_path.with_suffix(".parquet.tmp")
    combined.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, history_path)
    return len(combined) - prior_rows


def _final_per_beach_day(history: pd.DataFrame) -> pd.DataFrame:
    """The last-issued forecast per (beach_id, day) — what a user last saw."""
    frame = history.copy()
    frame["date"] = pd.to_datetime(frame["forecast_date"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["date"])
    frame["_issued"] = frame["forecast_generated_at"].astype(str)
    frame = (
        frame.sort_values(["beach_id", "date", "_issued"])
        .drop_duplicates(subset=["beach_id", "date"], keep="last")
        .drop(columns="_issued")
    )
    fit_input = pd.to_numeric(frame.get("p_exceed_precal"), errors="coerce")
    for fallback in ("p_exceed_raw", "p_exceed"):
        fit_input = fit_input.fillna(pd.to_numeric(frame.get(fallback), errors="coerce"))
    frame["p_fit"] = fit_input
    return frame


def _with_outcomes(final: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    """Join realized outcomes: same-day, first strictly-forward, and matched."""
    merged = final.merge(
        outcomes.rename(columns={"exceeded": "outcome_same_day"}),
        on=["beach_id", "date"],
        how="left",
    )
    merged["outcome_forward"] = np.nan
    for offset in range(1, FORWARD_MATCH_DAYS + 1):
        shifted = outcomes.copy()
        shifted["date"] = shifted["date"] - pd.Timedelta(days=offset)
        merged = merged.merge(
            shifted.rename(columns={"exceeded": f"_fwd_{offset}"}),
            on=["beach_id", "date"],
            how="left",
        )
        merged["outcome_forward"] = merged["outcome_forward"].fillna(merged[f"_fwd_{offset}"])
        merged = merged.drop(columns=f"_fwd_{offset}")
    merged["outcome_matched"] = merged["outcome_same_day"].fillna(merged["outcome_forward"])
    return merged


def _matched_from_disk(
    curated_dir: Path,
) -> tuple[pd.DataFrame, int, pd.Timestamp] | None:
    """(final forecasts joined to outcomes, history rows, max outcome date)."""
    history_path = curated_dir / HISTORY_FILE
    observations_path = curated_dir / "observations.parquet"
    if not history_path.exists() or not observations_path.exists():
        return None
    history = pd.read_parquet(history_path)
    if history.empty:
        return None
    observations = pd.read_parquet(
        observations_path, columns=["beach_id", "sample_date", "exceeds_stv"]
    )
    outcomes = daily_outcomes(observations)
    matched = _with_outcomes(_final_per_beach_day(history), outcomes)
    return matched, len(history), outcomes["date"].max() if len(outcomes) else pd.NaT


def _score(pairs: pd.DataFrame, outcome_column: str) -> dict | None:
    """Probability-quality metrics of served p_exceed against one outcome column."""
    subset = pairs.dropna(subset=["p_exceed", outcome_column])
    if subset.empty:
        return None
    labels = subset[outcome_column].astype(int).to_numpy()
    probabilities = subset["p_exceed"].astype(float).to_numpy()
    base_rate = float(labels.mean())
    record: dict[str, float | int] = {
        "n_pairs": int(len(subset)),
        "n_positive": int(labels.sum()),
        "base_rate": round(base_rate, 4),
        "brier": round(float(brier_score_loss(labels, probabilities)), 4),
        # The bar an uninformative flat constant sets — the audit found the
        # served probabilities losing to it, so it ships alongside every day.
        "brier_flat_base_rate": round(float(np.mean((base_rate - labels) ** 2)), 4),
    }
    if 0 < labels.sum() < len(labels):
        record["aucpr"] = round(float(average_precision_score(labels, probabilities)), 4)
        record["auroc"] = round(float(roc_auc_score(labels, probabilities)), 4)
        operating = sensitivity_at_specificity(labels, probabilities, 0.87)
        record["sensitivity_at_spec_0_87"] = round(float(operating["sensitivity"]), 4)
    return record


def _band_operating(pairs: pd.DataFrame) -> dict | None:
    """How the public Low-vs-warning banding performed against same-day truth."""
    subset = pairs.dropna(subset=["outcome_same_day"])
    subset = subset[subset["risk_band"].notna()]
    if subset.empty:
        return None
    labels = subset["outcome_same_day"].astype(int)
    warned = subset["risk_band"].astype(str) != "Low"
    positives = labels == 1
    negatives = labels == 0
    return {
        "n_pairs": int(len(subset)),
        "exceedances": int(positives.sum()),
        "sensitivity": (
            round(float((warned & positives).sum() / positives.sum()), 4)
            if positives.any()
            else None
        ),
        "specificity": (
            round(float((~warned & negatives).sum() / negatives.sum()), 4)
            if negatives.any()
            else None
        ),
        "exceedances_shown_low": int((~warned & positives).sum()),
        "false_alarms": int((warned & negatives).sum()),
    }


def _calibration_bins(pairs: pd.DataFrame) -> list[dict]:
    """Reliability table: served p_exceed vs realized rate, band-aligned bins."""
    subset = pairs.dropna(subset=["p_exceed", "outcome_matched"])
    probabilities = subset["p_exceed"].astype(float)
    labels = subset["outcome_matched"].astype(int)
    bins: list[dict] = []
    for low, high in zip(_BIN_EDGES[:-1], _BIN_EDGES[1:], strict=False):
        mask = (probabilities >= low) & (probabilities < high)
        if int(mask.sum()) == 0:
            continue
        bins.append(
            {
                "p_range": [low, min(high, 1.0)],
                "n": int(mask.sum()),
                "predicted_mean": round(float(probabilities[mask].mean()), 4),
                "actual_rate": round(float(labels[mask].mean()), 4),
            }
        )
    return bins


def served_performance(
    curated_dir: Path, windows: tuple[int, ...] = (90, 30)
) -> dict | None:
    """Score every served forecast against the lab results that followed.

    This is the audit's Test 4 (real forecast vs ground truth) wired into the
    daily pipeline: the numbers describe the product as deployed — stale
    between-sample rows included — not the fresh-sample backtest regime.
    """
    loaded = _matched_from_disk(curated_dir)
    if loaded is None:
        return None
    matched, history_rows, max_outcome_date = loaded
    if matched.empty:
        return None
    latest = matched["date"].max()
    payload: dict[str, object] = {
        "definition": (
            "Served p_exceed from forecast_history.parquet (final issue per "
            "beach-day) scored against observations.parquet worst-sample-per-day; "
            "same_day = outcome on the forecast day, forward = first outcome in "
            f"D+1..D+{FORWARD_MATCH_DAYS} (provably unseen by the forecast)."
        ),
        "history_rows": int(history_rows),
        "final_forecast_rows": int(len(matched)),
        "history_span_days": int((latest - matched["date"].min()).days) + 1,
    }
    # Falsifiability: of forecasts old enough that a result COULD have arrived
    # (the observation feed extends past their match window), how many ever got
    # one (audit measured ~10% — most published output is never checkable).
    checkable = matched[
        matched["date"] <= max_outcome_date - pd.Timedelta(days=FORWARD_MATCH_DAYS)
    ]
    if len(checkable):
        payload["verifiable_fraction"] = round(
            float(checkable["outcome_matched"].notna().mean()), 4
        )
    for window in windows:
        recent = matched[matched["date"] > latest - pd.Timedelta(days=window)]
        entry: dict[str, object] = {}
        same_day = _score(recent, "outcome_same_day")
        if same_day:
            band = _band_operating(recent)
            if band:
                same_day["band_operating"] = band
            entry["same_day"] = same_day
        forward = _score(recent, "outcome_forward")
        if forward:
            entry[f"forward_1_{FORWARD_MATCH_DAYS}d"] = forward
        reliability = _calibration_bins(recent)
        if reliability:
            entry["calibration_bins"] = reliability
        if entry:
            payload[f"window_{window}d"] = entry
    payload["generated_at"] = datetime.now(UTC).isoformat()
    return payload


def fit_serving_calibration(
    curated_dir: Path,
    *,
    window_days: int = _FIT_WINDOW_DAYS,
    min_pairs: int = _MIN_FIT_PAIRS,
    min_positives: int = _MIN_FIT_POSITIVES,
) -> dict | None:
    """Isotonic map: served (pre-calibration) probability -> realized rate.

    Fit on the trailing ``window_days`` of matched served-forecast/lab pairs.
    Returns None when history is too thin to beat noise — callers then serve
    the uncalibrated probability (exactly the pre-audit behavior).
    """
    loaded = _matched_from_disk(curated_dir)
    if loaded is None:
        return None
    matched = loaded[0]
    pairs = matched.dropna(subset=["p_fit", "outcome_matched"])
    if pairs.empty:
        return None
    latest = pairs["date"].max()
    pairs = pairs[pairs["date"] > latest - pd.Timedelta(days=window_days)]
    labels = pairs["outcome_matched"].astype(int).to_numpy()
    probabilities = pairs["p_fit"].astype(float).to_numpy()
    n_positive = int(labels.sum())
    if len(pairs) < min_pairs or n_positive < min_positives or n_positive == len(pairs):
        return None
    model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    model.fit(probabilities, labels)
    calibrated = model.predict(probabilities)
    base_rate = float(labels.mean())
    return {
        "x": [round(float(v), 6) for v in model.X_thresholds_],
        "y": [round(float(v), 6) for v in model.y_thresholds_],
        "fitted_at": datetime.now(UTC).isoformat(),
        "window_days": int(window_days),
        "n_pairs": int(len(pairs)),
        "n_positive": n_positive,
        "brier_before": round(float(brier_score_loss(labels, probabilities)), 4),
        "brier_after": round(float(brier_score_loss(labels, calibrated)), 4),
        "brier_flat_base_rate": round(float(np.mean((base_rate - labels) ** 2)), 4),
    }


def apply_serving_calibration(probabilities: np.ndarray, mapping: dict) -> np.ndarray:
    """Piecewise-linear interpolation through the isotonic knots (monotone, so
    rank order — the part of the model that held up forward — is preserved).
    NaN passes through; a degenerate mapping is a no-op."""
    values = np.asarray(probabilities, dtype=float)
    knots_x = np.asarray(mapping.get("x", []), dtype=float)
    knots_y = np.asarray(mapping.get("y", []), dtype=float)
    if len(knots_x) < 2 or len(knots_x) != len(knots_y):
        return values
    return np.clip(np.interp(values, knots_x, knots_y), 0.0, 1.0)


def save_serving_calibration(curated_dir: Path, mapping: dict) -> None:
    write_json(curated_dir / CALIBRATION_FILE, mapping)
