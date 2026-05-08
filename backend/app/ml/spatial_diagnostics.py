from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score


LABEL_COLUMN = "label"
MODEL_PROBABILITY_COLUMN = "model_probability"
PERSISTENCE_PROBABILITY_COLUMN = "persistence_probability"


def _as_numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        raise ValueError(f"Missing required column '{column}'")
    return pd.to_numeric(frame[column], errors="coerce")


def _valid_prediction_frame(
    frame: pd.DataFrame,
    *,
    label_column: str = LABEL_COLUMN,
    model_probability_column: str = MODEL_PROBABILITY_COLUMN,
    persistence_probability_column: str = PERSISTENCE_PROBABILITY_COLUMN,
) -> pd.DataFrame:
    labels = _as_numeric_series(frame, label_column)
    model = _as_numeric_series(frame, model_probability_column)
    persistence = _as_numeric_series(frame, persistence_probability_column)
    valid = frame.loc[labels.notna() & model.notna() & persistence.notna()].copy()
    valid[label_column] = labels.loc[valid.index].astype(float)
    valid[model_probability_column] = model.loc[valid.index].astype(float).clip(0.0, 1.0)
    valid[persistence_probability_column] = persistence.loc[valid.index].astype(float).clip(0.0, 1.0)
    return valid


def _brier(labels: pd.Series | np.ndarray, probabilities: pd.Series | np.ndarray) -> float:
    labels_array = np.asarray(labels, dtype=float)
    probability_array = np.asarray(probabilities, dtype=float)
    if len(labels_array) == 0:
        return float("nan")
    return float(np.mean((probability_array - labels_array) ** 2))


def _aucpr(labels: pd.Series | np.ndarray, probabilities: pd.Series | np.ndarray) -> float:
    labels_array = np.asarray(labels, dtype=int)
    if len(np.unique(labels_array)) < 2:
        return float("nan")
    return float(average_precision_score(labels_array, np.asarray(probabilities, dtype=float)))


def _bucket_numeric(
    values: pd.Series,
    *,
    labels: list[str],
    edges: list[float],
    missing_label: str = "unknown",
) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    bucketed = pd.cut(numeric, bins=edges, labels=labels, include_lowest=True, right=False)
    result = bucketed.astype("object")
    result[numeric.isna()] = missing_label
    return result.astype(str)


def add_default_context_buckets(frame: pd.DataFrame) -> pd.DataFrame:
    enriched = frame.copy()
    if "precip_mm_24h" in enriched.columns:
        enriched["precip_24h_bucket"] = _bucket_numeric(
            enriched["precip_mm_24h"],
            labels=["dry", "light_rain", "rain", "heavy_rain"],
            edges=[0.0, 0.1, 2.54, 12.7, float("inf")],
        )
    if "rain_72h_inches" in enriched.columns:
        enriched["rain_72h_bucket"] = _bucket_numeric(
            enriched["rain_72h_inches"],
            labels=["dry", "wet"],
            edges=[0.0, 0.1, float("inf")],
        )
    wave_column = (
        "wave_height_m_last_obs"
        if "wave_height_m_last_obs" in enriched.columns
        else "wave_height_m"
    )
    if wave_column in enriched.columns:
        enriched["wave_height_bucket"] = _bucket_numeric(
            enriched[wave_column],
            labels=["calm", "moderate", "high"],
            edges=[0.0, 0.5, 1.5, float("inf")],
        )
    if "days_since_wave_height_m_obs" in enriched.columns:
        enriched["wave_recency_bucket"] = _bucket_numeric(
            enriched["days_since_wave_height_m_obs"],
            labels=["fresh", "recent", "stale"],
            edges=[0.0, 3.0, 7.0, float("inf")],
        )
    return enriched


def markdown_table(frame: pd.DataFrame, *, floatfmt: str = ".4f") -> str:
    if frame.empty:
        return ""
    headers = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in frame.iterrows():
        cells: list[str] = []
        for value in row.tolist():
            if isinstance(value, float):
                cells.append(format(value, floatfmt))
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _diagnostic_row(
    frame: pd.DataFrame,
    *,
    label_column: str = LABEL_COLUMN,
    model_probability_column: str = MODEL_PROBABILITY_COLUMN,
    persistence_probability_column: str = PERSISTENCE_PROBABILITY_COLUMN,
) -> dict[str, float]:
    labels = frame[label_column]
    model = frame[model_probability_column]
    persistence = frame[persistence_probability_column]
    model_brier = _brier(labels, model)
    persistence_brier = _brier(labels, persistence)
    actual_rate = float(labels.mean()) if len(labels) else float("nan")
    mean_model = float(model.mean()) if len(model) else float("nan")
    mean_persistence = float(persistence.mean()) if len(persistence) else float("nan")
    return {
        "n": int(len(frame)),
        "positives": int(labels.sum()),
        "actual_rate": actual_rate,
        "model_brier": model_brier,
        "persistence_brier": persistence_brier,
        "brier_delta": model_brier - persistence_brier,
        "mean_model_pred": mean_model,
        "mean_persistence_pred": mean_persistence,
        "model_bias": mean_model - actual_rate,
        "persistence_bias": mean_persistence - actual_rate,
    }


def group_brier_diagnostics(
    frame: pd.DataFrame,
    *,
    group_column: str,
    label_column: str = LABEL_COLUMN,
    model_probability_column: str = MODEL_PROBABILITY_COLUMN,
    persistence_probability_column: str = PERSISTENCE_PROBABILITY_COLUMN,
) -> pd.DataFrame:
    if group_column not in frame.columns:
        raise ValueError(f"Missing required column '{group_column}'")
    valid = _valid_prediction_frame(
        frame,
        label_column=label_column,
        model_probability_column=model_probability_column,
        persistence_probability_column=persistence_probability_column,
    )
    rows: list[dict[str, object]] = []
    for group_value, group in valid.dropna(subset=[group_column]).groupby(group_column, sort=False):
        rows.append(
            {
                group_column: group_value,
                **_diagnostic_row(
                    group,
                    label_column=label_column,
                    model_probability_column=model_probability_column,
                    persistence_probability_column=persistence_probability_column,
                ),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                group_column,
                "n",
                "positives",
                "actual_rate",
                "model_brier",
                "persistence_brier",
                "brier_delta",
                "mean_model_pred",
                "mean_persistence_pred",
                "model_bias",
                "persistence_bias",
            ]
        )
    return pd.DataFrame(rows).sort_values(
        ["brier_delta", "n"], ascending=[False, False]
    ).reset_index(drop=True)


def slice_brier_diagnostics(
    frame: pd.DataFrame,
    *,
    slice_column: str,
    label_column: str = LABEL_COLUMN,
    model_probability_column: str = MODEL_PROBABILITY_COLUMN,
    persistence_probability_column: str = PERSISTENCE_PROBABILITY_COLUMN,
) -> pd.DataFrame:
    return group_brier_diagnostics(
        frame,
        group_column=slice_column,
        label_column=label_column,
        model_probability_column=model_probability_column,
        persistence_probability_column=persistence_probability_column,
    )


def calibration_bins(
    frame: pd.DataFrame,
    *,
    probability_column: str,
    label_column: str = LABEL_COLUMN,
    bins: int = 10,
) -> pd.DataFrame:
    if bins < 1:
        raise ValueError("bins must be at least 1")
    labels = _as_numeric_series(frame, label_column)
    probabilities = _as_numeric_series(frame, probability_column).clip(0.0, 1.0)
    valid = pd.DataFrame({"label": labels, "probability": probabilities}).dropna()
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows: list[dict[str, object]] = []
    for idx, (lower, upper) in enumerate(zip(edges[:-1], edges[1:])):
        if idx == bins - 1:
            mask = (valid["probability"] >= lower) & (valid["probability"] <= upper)
            label = f"[{lower:.2f}, {upper:.2f}]"
        else:
            mask = (valid["probability"] >= lower) & (valid["probability"] < upper)
            label = f"[{lower:.2f}, {upper:.2f})"
        group = valid.loc[mask]
        if group.empty:
            continue
        actual_rate = float(group["label"].mean())
        mean_pred = float(group["probability"].mean())
        rows.append(
            {
                "bin": label,
                "bin_lower": float(lower),
                "bin_upper": float(upper),
                "n": int(len(group)),
                "positives": int(group["label"].sum()),
                "actual_rate": actual_rate,
                "mean_pred": mean_pred,
                "bias": mean_pred - actual_rate,
                "brier": _brier(group["label"], group["probability"]),
            }
        )
    return pd.DataFrame(rows)


def blend_alpha_sweep(
    frame: pd.DataFrame,
    *,
    alphas: Iterable[float] | None = None,
    label_column: str = LABEL_COLUMN,
    model_probability_column: str = MODEL_PROBABILITY_COLUMN,
    persistence_probability_column: str = PERSISTENCE_PROBABILITY_COLUMN,
) -> pd.DataFrame:
    valid = _valid_prediction_frame(
        frame,
        label_column=label_column,
        model_probability_column=model_probability_column,
        persistence_probability_column=persistence_probability_column,
    )
    if alphas is None:
        alphas = np.linspace(0.0, 1.0, 11)
    labels = valid[label_column]
    model = valid[model_probability_column]
    persistence = valid[persistence_probability_column]
    persistence_brier = _brier(labels, persistence)
    rows: list[dict[str, float | bool]] = []
    for raw_alpha in alphas:
        alpha = float(raw_alpha)
        if alpha < 0.0 or alpha > 1.0:
            raise ValueError("alphas must be between 0.0 and 1.0")
        probabilities = alpha * model + (1.0 - alpha) * persistence
        brier = _brier(labels, probabilities)
        rows.append(
            {
                "alpha": alpha,
                "brier": brier,
                "brier_delta_vs_persistence": brier - persistence_brier,
                "aucpr": _aucpr(labels, probabilities),
                "mean_pred": float(probabilities.mean()) if len(probabilities) else float("nan"),
                "beats_persistence": bool(brier < persistence_brier),
            }
        )
    return pd.DataFrame(rows).sort_values(["brier", "alpha"]).reset_index(drop=True)
