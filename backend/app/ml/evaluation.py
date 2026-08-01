from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from app.ml.calibration import logit
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    mean_squared_error,
    precision_recall_curve,
)


# Guard against log(0) in log_loss ONLY. Deliberately NOT the calibration clip:
# this one exists to keep the metric finite, so it stays tight; LOGIT_EPSILON
# exists to mirror the transform the pipeline applies. Conflating them would
# make log_loss quietly more forgiving of confident-wrong predictions.
_EPSILON = 1e-6


def _calibration_slope(labels: np.ndarray, probabilities: np.ndarray) -> float:
    """Slope of the label on the model's log-odds. 1.0 = perfectly calibrated
    spread; < 0.4 blocks publication (training._promotion_assessment).

    Clips at calibration.LOGIT_EPSILON so this measures the model on the same
    log-odds range the pipeline's own calibrator fits on. ``C=1e6`` is
    deliberately looser than the calibrator's ``C=1.0``: this is a diagnostic
    that wants the unpenalised slope estimate, whereas the fitted transform
    wants regularisation so the calibration map does not overfit.
    """
    if len(np.unique(labels)) < 2:
        return float("nan")
    logits = logit(probabilities).reshape(-1, 1)
    model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000)
    model.fit(logits, labels.astype(int))
    return float(model.coef_[0][0])


def _precision_at_recall(
    labels: np.ndarray,
    probabilities: np.ndarray,
    target_recall: float = 0.8,
) -> float:
    precision, recall, _ = precision_recall_curve(labels, probabilities)
    eligible = precision[recall >= target_recall]
    if len(eligible) == 0:
        return 0.0
    return float(np.max(eligible))


def sensitivity_at_specificity(
    labels: np.ndarray,
    probabilities: np.ndarray,
    target_specificity: float = 0.87,
) -> dict[str, float]:
    """Sensitivity (recall on positives) at a fixed specificity operating point.

    Mirrors the operational benchmark used by public beach-warning systems, e.g.
    Searcy et al. 2018 ("Mining nowcast environmental data..."), which reports a
    median sensitivity of 0.50 at specificity 0.87 across 10 CA oceanic beaches.
    To compare honestly we must pick the decision threshold that delivers (at
    least) the target specificity, then read off the sensitivity there.

    Returns sensitivity, the achieved specificity, and the probability threshold.
    Sweeping the candidate thresholds (the unique predicted probabilities) we pick
    the threshold whose true-negative rate is closest to — but not below — the
    target; if none reaches the target (e.g. degenerate probabilities) we fall
    back to the threshold with the highest achievable specificity.

        specificity = TN / (TN + FP)        on the negatives
        sensitivity = TP / (TP + FN)        on the positives

    A "predict positive when p >= threshold" rule; ties at the threshold count as
    positive (so a very low threshold yields specificity 0, sensitivity 1).
    """
    labels = np.asarray(labels).astype(int)
    probabilities = np.asarray(probabilities, dtype=float)
    positives = labels == 1
    negatives = ~positives
    n_pos = int(positives.sum())
    n_neg = int(negatives.sum())
    if n_pos == 0 or n_neg == 0:
        return {
            "sensitivity": float("nan"),
            "specificity": float("nan"),
            "threshold": float("nan"),
        }

    # Candidate thresholds: one just above each distinct score, plus +inf (predict
    # all-negative -> specificity 1). Using distinct scores keeps this O(unique).
    candidates = np.unique(probabilities)
    thresholds = np.concatenate([candidates, [np.inf]])

    best_sens = 0.0
    best_spec = -1.0
    best_threshold = float("inf")
    # Track the highest specificity we ever see, as a fallback when the target is
    # unreachable (e.g. all negatives share the top score).
    fallback_sens = 0.0
    fallback_spec = -1.0
    fallback_threshold = float("inf")

    for threshold in thresholds:
        predicted_positive = probabilities >= threshold
        tp = int(np.sum(predicted_positive & positives))
        fp = int(np.sum(predicted_positive & negatives))
        specificity = (n_neg - fp) / n_neg
        sensitivity = tp / n_pos
        if specificity > fallback_spec or (
            specificity == fallback_spec and sensitivity > fallback_sens
        ):
            fallback_spec = specificity
            fallback_sens = sensitivity
            fallback_threshold = float(threshold)
        if specificity >= target_specificity and sensitivity >= best_sens:
            # Among thresholds that clear the target specificity, keep the one
            # with the highest sensitivity (the most useful warning rule).
            best_sens = sensitivity
            best_spec = specificity
            best_threshold = float(threshold)

    if best_spec < 0:
        # No threshold reached the target specificity; report the best attainable.
        return {
            "sensitivity": float(fallback_sens),
            "specificity": float(fallback_spec),
            "threshold": fallback_threshold,
        }
    return {
        "sensitivity": float(best_sens),
        "specificity": float(best_spec),
        "threshold": best_threshold,
    }


def cluster_bootstrap_aucpr_ci(
    labels: np.ndarray,
    probabilities: np.ndarray,
    groups: np.ndarray,
    *,
    n_resamples: int = 500,
    seed: int = 12345,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Cluster (group) bootstrap confidence interval for the pooled AUCPR.

    Spatial holdout AUCPR is pooled across leave-one-out folds, so the rows are
    NOT independent — every row in a held-out county/beach shares that fold's
    draw. A naive row bootstrap would badly understate the uncertainty. The honest
    resampling unit is the *group* (the fold id): draw the unique groups with
    replacement, pool all rows of the drawn groups, recompute AUCPR, and read the
    central (1 - ``alpha``) quantile interval off the bootstrap distribution.

    Single-class resamples (no positives or no negatives pooled) are skipped —
    ``average_precision_score`` is undefined there. Deterministic for a given
    ``seed``. Returns ``(nan, nan)`` when there are fewer than two groups, the
    inputs are empty/misaligned, or every resample degenerates.
    """
    labels = np.asarray(labels).astype(int)
    probabilities = np.asarray(probabilities, dtype=float)
    groups = np.asarray(groups)
    n_rows = labels.shape[0]
    if n_rows == 0 or probabilities.shape[0] != n_rows or groups.shape[0] != n_rows:
        return (float("nan"), float("nan"))
    unique_groups = np.unique(groups)
    n_groups = len(unique_groups)
    if n_groups < 2:
        return (float("nan"), float("nan"))
    group_to_rows = {g: np.flatnonzero(groups == g) for g in unique_groups}
    rng = np.random.default_rng(seed)
    samples: list[float] = []
    for _ in range(n_resamples):
        drawn = rng.choice(n_groups, size=n_groups, replace=True)
        idx = np.concatenate([group_to_rows[unique_groups[g]] for g in drawn])
        pooled_labels = labels[idx]
        if len(np.unique(pooled_labels)) < 2:
            continue
        samples.append(float(average_precision_score(pooled_labels, probabilities[idx])))
    if not samples:
        return (float("nan"), float("nan"))
    low = float(np.quantile(samples, alpha / 2.0))
    high = float(np.quantile(samples, 1.0 - alpha / 2.0))
    return (low, high)


def paired_cluster_bootstrap_aucpr_gap_ci(
    labels_a: np.ndarray,
    probabilities_a: np.ndarray,
    groups_a: np.ndarray,
    labels_b: np.ndarray,
    probabilities_b: np.ndarray,
    groups_b: np.ndarray,
    *,
    n_resamples: int = 500,
    seed: int = 12345,
    alpha: float = 0.10,
) -> tuple[float, float]:
    """Paired cluster bootstrap CI for the pooled AUCPR gap (model A - model B).

    Both models are scored on the SAME held-out folds (counties/beaches); they
    differ only in their per-row probabilities. To test whether challenger A
    *decisively* beats incumbent B we resample the shared folds with replacement
    and, on each resample, compute each model's pooled AUCPR from its own
    per-row predictions, then the gap A - B. The pairing is at the fold level —
    the same drawn folds feed both models — which removes the between-fold
    variance that dominates the 6-fold spatial sweep. A positive lower bound of
    the central (1 - ``alpha``) interval means A beats B beyond resampling noise.

    Resamples where either model's pooled labels are single-class are skipped.
    Deterministic for a given ``seed``. Returns ``(nan, nan)`` when fewer than two
    shared groups exist or every resample degenerates.
    """
    labels_a = np.asarray(labels_a).astype(int)
    probabilities_a = np.asarray(probabilities_a, dtype=float)
    groups_a = np.asarray(groups_a)
    labels_b = np.asarray(labels_b).astype(int)
    probabilities_b = np.asarray(probabilities_b, dtype=float)
    groups_b = np.asarray(groups_b)
    if labels_a.shape[0] == 0 or labels_b.shape[0] == 0:
        return (float("nan"), float("nan"))
    if groups_a.shape[0] != labels_a.shape[0] or groups_b.shape[0] != labels_b.shape[0]:
        return (float("nan"), float("nan"))
    shared_groups = np.intersect1d(np.unique(groups_a), np.unique(groups_b))
    n_groups = len(shared_groups)
    if n_groups < 2:
        return (float("nan"), float("nan"))
    a_rows = {g: np.flatnonzero(groups_a == g) for g in shared_groups}
    b_rows = {g: np.flatnonzero(groups_b == g) for g in shared_groups}
    rng = np.random.default_rng(seed)
    gaps: list[float] = []
    for _ in range(n_resamples):
        drawn = rng.choice(n_groups, size=n_groups, replace=True)
        idx_a = np.concatenate([a_rows[shared_groups[g]] for g in drawn])
        idx_b = np.concatenate([b_rows[shared_groups[g]] for g in drawn])
        ya = labels_a[idx_a]
        yb = labels_b[idx_b]
        if len(np.unique(ya)) < 2 or len(np.unique(yb)) < 2:
            continue
        aucpr_a = average_precision_score(ya, probabilities_a[idx_a])
        aucpr_b = average_precision_score(yb, probabilities_b[idx_b])
        gaps.append(float(aucpr_a - aucpr_b))
    if not gaps:
        return (float("nan"), float("nan"))
    low = float(np.quantile(gaps, alpha / 2.0))
    high = float(np.quantile(gaps, 1.0 - alpha / 2.0))
    return (low, high)


def classification_metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    labels = np.asarray(labels)
    probabilities = np.asarray(probabilities, dtype=float)
    return {
        "aucpr": float(average_precision_score(labels, probabilities)),
        "brier": float(brier_score_loss(labels, probabilities)),
        "log_loss": float(log_loss(labels, np.clip(probabilities, _EPSILON, 1.0 - _EPSILON), labels=[0, 1])),
        "calibration_slope": _calibration_slope(labels, probabilities),
        "precision_at_80_recall": _precision_at_recall(labels, probabilities),
    }


def regression_metrics(labels: np.ndarray, predictions: np.ndarray) -> dict[str, float]:
    rmse = mean_squared_error(labels, predictions) ** 0.5
    return {"rmse": float(rmse)}


def holdout_frame(
    labels: np.ndarray,
    probabilities: np.ndarray,
    **id_columns: object,
) -> pd.DataFrame:
    """Build a tidy (label, probability [, identifier...]) holdout-prediction frame.

    This is the per-row artifact that lets us recompute *any* threshold-based
    operating point — sensitivity@specificity for the Searcy et al. 2018
    benchmark, precision@recall, a custom warning rule — without retraining the
    model. ``training.py`` concatenates these held-out arrays only to feed
    ``classification_metrics`` and then discards them; this helper turns them
    into a persistable frame so they survive.

    ``label`` is coerced to int and ``probability`` to float. Each keyword in
    ``id_columns`` becomes a column (e.g. ``model="xgb_undersample_ensemble"``,
    ``county=...``, ``beach_id=...``, ``date=...``); scalars are broadcast,
    array-likes must match the number of rows.
    """
    labels = np.asarray(labels)
    probabilities = np.asarray(probabilities, dtype=float)
    if labels.shape[0] != probabilities.shape[0]:
        raise ValueError(
            f"labels ({labels.shape[0]}) and probabilities "
            f"({probabilities.shape[0]}) must have the same length"
        )
    n_rows = labels.shape[0]
    data: dict[str, object] = {
        "label": labels.astype(int),
        "probability": probabilities,
    }
    for name, value in id_columns.items():
        if value is None:
            continue
        if np.isscalar(value) or isinstance(value, (str, bytes)):
            data[name] = [value] * n_rows
        else:
            arr = np.asarray(value)
            if arr.shape[0] != n_rows:
                raise ValueError(
                    f"id column '{name}' has length {arr.shape[0]} but expected {n_rows}"
                )
            data[name] = arr
    return pd.DataFrame(data)


def persist_holdout_predictions(
    path: str | Path,
    labels: np.ndarray,
    probabilities: np.ndarray,
    **id_columns: object,
) -> Path | None:
    """Write holdout (label, probability) pairs to ``path`` as parquet.

    Guarded so a missing/empty array never crashes a training run: returns
    ``None`` (and writes nothing) when there are no rows or the inputs are
    unusable, and ``Path`` on a successful write. Any unexpected error is
    swallowed and reported via return value rather than propagated, because
    persisting an evaluation artifact must never take down the model build.
    """
    try:
        if labels is None or probabilities is None:
            return None
        if len(labels) == 0 or len(probabilities) == 0:
            return None
        frame = holdout_frame(labels, probabilities, **id_columns)
        if frame.empty:
            return None
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(out, index=False)
        return out
    except Exception:  # pragma: no cover - defensive: artifact write must not crash training
        return None


def _json_safe_operating_point(point: dict[str, float]) -> dict[str, float | None]:
    """Convert a sensitivity_at_specificity() result to a JSON-safe dict.

    NaN (the degenerate single-class result) becomes ``None`` so it round-trips
    through ``json.dumps`` cleanly instead of serializing to a bare ``NaN`` token.
    """
    safe: dict[str, float | None] = {}
    for key, value in point.items():
        if value is None or (isinstance(value, float) and not np.isfinite(value)):
            safe[key] = None
        else:
            safe[key] = float(value)
    return safe


def sensitivity_at_specificity_record(
    labels: np.ndarray,
    probabilities: np.ndarray,
    target_specificity: float = 0.87,
) -> dict[str, float | None]:
    """sensitivity_at_specificity() wrapped to a JSON-safe payload.

    Convenience for embedding the Searcy-benchmark operating point into
    ``system_health.json``: same computation, but NaN -> None so the result is
    safe to serialize and store under e.g. ``production_metrics``.
    """
    return _json_safe_operating_point(
        sensitivity_at_specificity(labels, probabilities, target_specificity)
    )
