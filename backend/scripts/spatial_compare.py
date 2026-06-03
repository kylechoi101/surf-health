"""Spatial validation of the cohort winner: leave-one-CA-county-out.

The temporal-split numbers (compare_cohorts.py) are optimistic — the same
beaches sit in train AND test, so the model can memorize per-beach base rates.
This script answers the only question that gates a production flip: when a whole
county is held out (never seen in training), how well does the XGB
balanced-undersample ensemble actually generalize — and does pooling all of
Texas into the training set lift the held-out CA county?

Our product serves California, so the TEST set is always CA counties. The two
training regimes are:
  * CA-only  : train on the other CA counties.
  * CA+TX    : train on the other CA counties + ALL of Texas.

Predictions from every held-out fold are pooled, then one AUCPR is computed per
feature-set (the standard leave-one-group-out spatial metric). Writes NO
production model.

    python scripts/spatial_compare.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss
from xgboost import XGBClassifier

from app.data.pipeline.features import build_sliding_windows
from app.ml.training import _load_curated_training_frame

CA_DIR = Path("../data/curated")
TX_DIR = Path("../data/cohorts/tx")
WINDOW_DAYS = 365 * 3
MIN_TEST_POS = 20      # skip counties too sparse to score
MAX_COUNTIES = 12      # cap by positives for runtime
ENSEMBLE_N = 12
RATIO = 2.0

MARINE = ("solar", "shortwave", "cloud", "uv_index_24h", "wind_speed_24h",
          "wind_direction_24h", "shore_normal", "days_since_sunny", "pier", "estuary")
OCEAN = ("wave_height", "wave_period", "dominant_period", "water_temperature", "salinity")


def _frame_from_beach_day(path: Path) -> pd.DataFrame:
    bd = pd.read_parquet(path)
    bd["sample_date"] = pd.to_datetime(bd["sample_date"], errors="coerce")
    bd = bd[bd.get("support_status", "production") != "unsupported"].copy()
    bd = bd[bd["sample_date"] > bd["sample_date"].max() - pd.Timedelta(days=WINDOW_DAYS)]
    return bd


def _windows_with_group(frame: pd.DataFrame, group_col: str) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Build sliding windows and attach the spatial group (county) per row by
    joining through beach_id (beaches never span counties)."""
    ds = build_sliding_windows(frame)
    X = ds.feature_frame.select_dtypes(include=["number"]).fillna(0.0).reset_index(drop=True)
    y = ds.targets_exceed.astype(int)
    bmap = frame.drop_duplicates("beach_id").set_index("beach_id")[group_col]
    groups = ds.metadata["beach_id"].map(bmap).fillna("__unknown__").to_numpy()
    return X, y, groups


def _ensemble_predict(Xtr, ytr, Xte, cols, seed=42):
    """XGB balanced-undersample soft-ensemble — fit on train, predict test."""
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


def _pooled_metric(Xca, yca, gca, Xtx, ytx, cols, pool_tx: bool):
    """Leave-one-CA-county-out; pool predictions across folds -> AUCPR + Brier."""
    counties = pd.Series(gca).value_counts()
    pos_by_c = {c: int(yca[gca == c].sum()) for c in counties.index}
    chosen = [c for c, _ in sorted(pos_by_c.items(), key=lambda kv: -kv[1])
              if pos_by_c[c] >= MIN_TEST_POS and c != "__unknown__"][:MAX_COUNTIES]
    yt_all, p_all = [], []
    for c in chosen:
        te = gca == c
        tr = ~te
        Xtr, ytr = Xca[tr], yca[tr]
        if pool_tx and Xtx is not None:
            Xtr = pd.concat([Xtr[cols], Xtx[cols]], ignore_index=True)
            ytr = np.concatenate([ytr, ytx])
        else:
            Xtr = Xtr[cols].reset_index(drop=True)
        pred = _ensemble_predict(Xtr, ytr, Xca[te], cols)
        if pred is None:
            continue
        yt_all.append(yca[te])
        p_all.append(pred)
    if not yt_all:
        return float("nan"), float("nan")
    yt = np.concatenate(yt_all)
    p = np.concatenate(p_all)
    return average_precision_score(yt, p), brier_score_loss(yt, p)


def main() -> int:
    ca = _load_curated_training_frame(CA_DIR)
    ca["sample_date"] = pd.to_datetime(ca["sample_date"])
    ca = ca[ca["sample_date"] > ca["sample_date"].max() - pd.Timedelta(days=WINDOW_DAYS)].copy()
    Xca, yca, gca = _windows_with_group(ca, "county")

    Xtx = ytx = None
    common = list(Xca.columns)
    if (TX_DIR / "beach_day.parquet").exists():
        tx = _frame_from_beach_day(TX_DIR / "beach_day.parquet")
        Xtx, ytx, _ = _windows_with_group(tx, "region")
        common = [c for c in Xca.columns if c in Xtx.columns]
        print(f"[spatial] common cols CA∩TX = {len(common)} / CA {len(Xca.columns)}")

    is_m = [c for c in common if any(k in c for k in MARINE)]
    is_o = [c for c in common if any(k in c for k in OCEAN)]
    base = [c for c in common if c not in set(is_m) | set(is_o)]
    feature_sets = {
        "base": base,
        "+marine": base + is_m,
        "+ocean": base + is_o,
        "full": common,
    }
    print(f"[spatial] base={len(base)} marine={len(is_m)} ocean={len(is_o)} | "
          f"CA rows {len(Xca)} pos {int(yca.sum())}")

    print(f"\n{'regime':10s} {'base':>14s} {'+marine':>14s} {'+ocean':>14s} {'full':>14s}   (AUCPR / Brier)")
    for label, pool in [("CA-only", False), ("CA+TX", True)]:
        if pool and Xtx is None:
            continue
        cells = {}
        for name, cols in feature_sets.items():
            ap, br = _pooled_metric(Xca, yca, gca, Xtx, ytx, cols, pool)
            cells[name] = f"{ap:.3f}/{br:.3f}"
        print(f"{label:10s} " + "  ".join(f"{cells[k]:>14s}" for k in ("base", "+marine", "+ocean", "full")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
