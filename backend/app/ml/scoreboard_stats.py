"""Statistics shared by the offline model comparison and the live served scoreboard.

``within_beach_auroc`` is the daily-skill headline (global AUROC is dominated by
between-beach variance); ``cluster_bootstrap_delta`` resamples whole beaches, the
unit that carries the dependence between rows.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


def within_beach_auroc(y: np.ndarray, p: np.ndarray, beach: np.ndarray) -> float:
    """Row-weighted mean of per-beach AUROC, beaches with both outcomes only."""
    num = den = 0.0
    for _, idx in pd.Series(np.arange(len(y))).groupby(beach):
        yy, pp = y[idx.to_numpy()], p[idx.to_numpy()]
        n1 = yy.sum()
        n0 = len(yy) - n1
        if n1 and n0:
            num += n1 * n0 * roc_auc_score(yy, pp)
            den += n1 * n0
    return num / den if den else float("nan")


def cluster_bootstrap_delta(
    y: np.ndarray, p_new: np.ndarray, p_old: np.ndarray, beach: np.ndarray, reps: int, seed: int = 0
) -> dict[str, list[float]]:
    """95% CI of (challenger - served), resampling whole beaches."""
    if reps <= 0:
        return {k: [float("nan"), float("nan")] for k in ("within_beach_auroc", "auroc", "aucpr", "brier")}

    valid = ~np.isnan(p_new) & ~np.isnan(p_old)
    if not valid.any() or len(np.unique(y[valid])) < 2:
        return {k: [float("nan"), float("nan")] for k in ("within_beach_auroc", "auroc", "aucpr", "brier")}
    y, p_new, p_old, beach = y[valid], p_new[valid], p_old[valid], beach[valid]

    if np.array_equal(p_new, p_old):
        return {k: [0.0, 0.0] for k in ("within_beach_auroc", "auroc", "aucpr", "brier")}

    rng = np.random.default_rng(seed)
    groups = pd.Series(np.arange(len(y))).groupby(beach).indices
    keys = list(groups)
    if not keys:
        return {k: [float("nan"), float("nan")] for k in ("within_beach_auroc", "auroc", "aucpr", "brier")}

    # Precompute per-beach AUROCs and weights for fast within_beach_auroc bootstrap
    weights = np.zeros(len(keys))
    auc_new = np.zeros(len(keys))
    auc_old = np.zeros(len(keys))
    for i, k in enumerate(keys):
        idx_k = groups[k]
        yk = y[idx_k]
        n1 = yk.sum()
        n0 = len(yk) - n1
        if n1 and n0:
            w = n1 * n0
            weights[i] = w
            auc_new[i] = roc_auc_score(yk, p_new[idx_k])
            auc_old[i] = roc_auc_score(yk, p_old[idx_k])

    out: dict[str, list[float]] = {"within_beach_auroc": [], "auroc": [], "aucpr": [], "brier": []}
    for _ in range(reps):
        sampled = rng.choice(len(keys), len(keys), replace=True)
        counts = np.bincount(sampled, minlength=len(keys))

        den = np.sum(counts * weights)
        if den > 0:
            wb_new = np.sum(counts * weights * auc_new) / den
            wb_old = np.sum(counts * weights * auc_old) / den
            wb_delta = wb_new - wb_old
        else:
            wb_delta = float("nan")

        idx = np.concatenate([groups[keys[i]] for i in sampled])
        yy = y[idx]
        if yy.min() == yy.max():
            continue

        if not np.isnan(wb_delta):
            out["within_beach_auroc"].append(wb_delta)
        out["auroc"].append(roc_auc_score(yy, p_new[idx]) - roc_auc_score(yy, p_old[idx]))
        out["aucpr"].append(
            average_precision_score(yy, p_new[idx]) - average_precision_score(yy, p_old[idx])
        )
        out["brier"].append(
            brier_score_loss(yy, p_new[idx]) - brier_score_loss(yy, p_old[idx])
        )

    return {
        k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if len(v) else [float("nan"), float("nan")]
        for k, v in out.items()
    }
