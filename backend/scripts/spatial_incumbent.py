"""Final flip gate: on the winning scope (CA-only, +marine), does the XGB
balanced-undersample soft-ensemble actually beat the incumbent single balanced
GBM on the SAME leave-one-CA-county-out folds? Confirms the architecture flip,
not just the feature/scope flip. Writes NO production model.

    python scripts/spatial_incumbent.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, brier_score_loss
from xgboost import XGBClassifier

from app.data.pipeline.features import build_sliding_windows
from app.ml.training import _load_curated_training_frame

CA_DIR = Path("../data/curated")
WINDOW_DAYS = 365 * 3
MIN_TEST_POS, MAX_COUNTIES = 20, 12
ENSEMBLE_N, RATIO = 12, 2.0

MARINE = ("solar", "shortwave", "cloud", "uv_index_24h", "wind_speed_24h",
          "wind_direction_24h", "shore_normal", "days_since_sunny", "pier", "estuary")
OCEAN = ("wave_height", "wave_period", "dominant_period", "water_temperature", "salinity")


def _windows(frame):
    ds = build_sliding_windows(frame)
    X = ds.feature_frame.select_dtypes(include=["number"]).fillna(0.0).reset_index(drop=True)
    y = ds.targets_exceed.astype(int)
    bmap = frame.drop_duplicates("beach_id").set_index("beach_id")["county"]
    groups = ds.metadata["beach_id"].map(bmap).fillna("__unknown__").to_numpy()
    return X, y, groups


def _ensemble(Xtr, ytr, Xte, cols, seed=42):
    tr = np.arange(len(ytr))
    pos, neg = tr[ytr == 1], tr[ytr == 0]
    if len(pos) < 5:
        return None
    rng = np.random.default_rng(seed)
    preds = []
    for i in range(ENSEMBLE_N):
        k = min(int(len(pos) * RATIO), len(neg))
        sub = np.concatenate([pos, rng.choice(neg, size=k, replace=False)])
        m = XGBClassifier(n_estimators=250, max_depth=6, learning_rate=0.05, subsample=0.8,
                          colsample_bytree=0.8, eval_metric="aucpr", tree_method="hist",
                          random_state=seed + i, n_jobs=12, verbosity=0)
        m.fit(Xtr.iloc[sub][cols], ytr[sub])
        preds.append(m.predict_proba(Xte[cols])[:, 1])
    return np.mean(preds, axis=0)


def _incumbent(Xtr, ytr, Xte, cols):
    """Single balanced GBM — the production hist_gbm architecture."""
    if ytr.sum() < 5:
        return None
    w = np.where(ytr == 1, (ytr == 0).sum() / max(1, (ytr == 1).sum()), 1.0)
    m = HistGradientBoostingClassifier(max_iter=300, max_depth=6, learning_rate=0.05,
                                       random_state=42)
    m.fit(Xtr[cols], ytr, sample_weight=w)
    return m.predict_proba(Xte[cols])[:, 1]


def _spatial(X, y, g, cols, fit_fn):
    counties = {c: int(y[g == c].sum()) for c in pd.unique(g)}
    chosen = [c for c in sorted(counties, key=lambda k: -counties[k])
              if counties[c] >= MIN_TEST_POS and c != "__unknown__"][:MAX_COUNTIES]
    yt, pr = [], []
    for c in chosen:
        te = g == c
        pred = fit_fn(X[~te].reset_index(drop=True), y[~te], X[te], cols)
        if pred is None:
            continue
        yt.append(y[te])
        pr.append(pred)
    yt, pr = np.concatenate(yt), np.concatenate(pr)
    return average_precision_score(yt, pr), brier_score_loss(yt, pr)


def main() -> int:
    ca = _load_curated_training_frame(CA_DIR)
    ca["sample_date"] = pd.to_datetime(ca["sample_date"])
    ca = ca[ca["sample_date"] > ca["sample_date"].max() - pd.Timedelta(days=WINDOW_DAYS)].copy()
    X, y, g = _windows(ca)
    cols = list(X.columns)
    is_m = [c for c in cols if any(k in c for k in MARINE)]
    is_o = [c for c in cols if any(k in c for k in OCEAN)]
    base = [c for c in cols if c not in set(is_m) | set(is_o)]
    sets = {"base": base, "+marine": base + is_m}

    print(f"\n{'model':28s} {'base':>14s} {'+marine':>14s}   (AUCPR / Brier, CA-only spatial)")
    for label, fn in [("incumbent single balanced GBM", _incumbent),
                      ("XGB undersample ensemble", _ensemble)]:
        cells = {}
        for name, c in sets.items():
            ap, br = _spatial(X, y, g, c, fn)
            cells[name] = f"{ap:.3f}/{br:.3f}"
        print(f"{label:28s} {cells['base']:>14s} {cells['+marine']:>14s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
