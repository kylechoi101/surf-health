"""Compare-and-contrast: does marine/ocean signal help per region, and does
pooling CA+TX help? Standalone analysis — trains the XGB balanced-undersample
soft-ensemble in-memory and reports AUCPR; writes NO production model/registry.

    python scripts/compare_cohorts.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score
from xgboost import XGBClassifier

from app.data.pipeline.features import build_sliding_windows
from app.ml.training import _blocked_indices, _load_curated_training_frame

CA_DIR = Path("../data/curated")
TX_DIR = Path("../data/cohorts/tx")
WINDOW_DAYS = 365 * 3  # the cohorts span ~3y; use it all

MARINE = ("solar", "shortwave", "cloud", "uv_index_24h", "wind_speed_24h",
          "wind_direction_24h", "shore_normal", "days_since_sunny", "pier", "estuary")
OCEAN = ("wave_height", "wave_period", "dominant_period", "water_temperature", "salinity")


def _frame_from_beach_day(path: Path) -> pd.DataFrame:
    bd = pd.read_parquet(path)
    bd["sample_date"] = pd.to_datetime(bd["sample_date"], errors="coerce")
    bd = bd[bd.get("support_status", "production") != "unsupported"].copy()
    bd = bd[bd["sample_date"] > bd["sample_date"].max() - pd.Timedelta(days=WINDOW_DAYS)]
    return bd


def _matrix(X, y, tr, te, cols, n=20, ratio=2.0, seed=42):
    pos, neg = np.array(tr)[y[tr] == 1], np.array(tr)[y[tr] == 0]
    if len(pos) < 5 or len(np.unique(y[te])) < 2:
        return float("nan")
    rng = np.random.default_rng(seed)
    preds = []
    for i in range(n):
        k = min(int(len(pos) * ratio), len(neg))
        sub = np.concatenate([pos, rng.choice(neg, size=k, replace=False)])
        m = XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.05, subsample=0.8,
                          colsample_bytree=0.8, eval_metric="aucpr", tree_method="hist",
                          random_state=seed + i, n_jobs=4, verbosity=0)
        m.fit(X.iloc[sub][cols], y[sub])
        preds.append(m.predict_proba(X.iloc[te][cols])[:, 1])
    return average_precision_score(y[te], np.mean(preds, axis=0))


def _prep(frame):
    ds = build_sliding_windows(frame)
    X = ds.feature_frame.select_dtypes(include=["number"]).fillna(0.0).reset_index(drop=True)
    y = ds.targets_exceed.astype(int)
    tr, _, te = _blocked_indices(ds.metadata)
    return X, y, tr, te


def main() -> int:
    ca = _load_curated_training_frame(CA_DIR)
    ca = ca[ca["sample_date"] > ca["sample_date"].max() - pd.Timedelta(days=WINDOW_DAYS)].copy()
    cohorts = {"CA": ca}
    if (TX_DIR / "beach_day.parquet").exists():
        tx = _frame_from_beach_day(TX_DIR / "beach_day.parquet")
        cohorts["TX"] = tx
        common = [c for c in ca.columns if c in tx.columns]
        cohorts["CA+TX"] = pd.concat([ca[common], tx[common]], ignore_index=True)
    else:
        print("[compare] TX cohort not ready yet — CA-only")

    print(f"\n{'cohort':8s} {'base':>7s} {'+marine':>8s} {'+ocean':>8s} {'full':>7s}   (AUCPR)")
    for name, fr in cohorts.items():
        X, y, tr, te = _prep(fr)
        cols = list(X.columns)
        is_m = [c for c in cols if any(k in c for k in MARINE)]
        is_o = [c for c in cols if any(k in c for k in OCEAN)]
        base = [c for c in cols if c not in set(is_m) | set(is_o)]
        row = {
            "base": _matrix(X, y, tr, te, base),
            "+marine": _matrix(X, y, tr, te, base + is_m),
            "+ocean": _matrix(X, y, tr, te, base + is_o),
            "full": _matrix(X, y, tr, te, cols),
        }
        print(f"{name:8s} " + "  ".join(f"{row[k]:6.3f}" for k in ("base", "+marine", "+ocean", "full"))
              + f"   (n={len(X)}, test_pos={int(y[te].sum())})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
