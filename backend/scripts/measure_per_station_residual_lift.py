"""Measure AUCPR/Brier lift from Phase B per-station residual GBM correction.

Two passes:
  1. Baseline: global hist-GBM (matches today's production setup) + calibrator.
  2. With Phase B: global hist-GBM → per-station residual correction → calibrator.

Both use identical temporal train/val/test splits and feature engineering.
Report delta + per-station diagnostics so we know whether to ship.

Designed to run on the M4 Pro locally. ~3-5 min wall time at --spatial-jobs 12.

Usage:
    cd backend && .venv/bin/python scripts/measure_per_station_residual_lift.py
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ml.training import (
    _apply_calibrator,
    _blocked_indices,
    _calibration_split,
    _identity_or_calibrated,
    _inject_agent_features,
    _apply_stale_censoring,
    _metadata_with_groups,
    _load_curated_training_frame,
    build_sliding_windows,
    make_baselines,
)
from app.ml.per_station_residual import PerStationResidualEnsemble


def _aucpr(y, p):
    return float(average_precision_score(y, p))


def _brier(y, p):
    return float(brier_score_loss(y, p))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--curated", default="../data/curated")
    ap.add_argument("--training-window-days", type=int, default=365)
    ap.add_argument("--forecast-date", default=date.today().isoformat())
    ap.add_argument("--n-jobs", type=int, default=12)
    args = ap.parse_args()

    curated = Path(args.curated)
    fc_date = date.fromisoformat(args.forecast_date)

    t0 = time.time()
    print(f"Loading curated data from {curated}...")
    full_frame = _load_curated_training_frame(curated)
    full_frame["sample_date"] = pd.to_datetime(full_frame["sample_date"])
    max_date = full_frame["sample_date"].max()
    frame = full_frame.loc[
        full_frame["sample_date"] > (max_date - pd.Timedelta(days=args.training_window_days))
    ].copy()
    stations = pd.read_parquet(curated / "beaches.parquet")
    advisories_path = curated / "advisories.parquet"
    advisories = pd.read_parquet(advisories_path) if advisories_path.exists() else pd.DataFrame()
    print(f"  training window: {args.training_window_days}d, rows={len(frame)}")

    dataset = build_sliding_windows(frame)
    features = dataset.feature_frame.select_dtypes(include=["number"]).fillna(0.0)
    features = _inject_agent_features(features, dataset.metadata, full_frame, advisories, stations)
    features = _apply_stale_censoring(features)
    labels = dataset.targets_exceed.astype(int)
    metadata = _metadata_with_groups(dataset.metadata, frame, stations=stations)

    train_idx, valid_idx, test_idx = _blocked_indices(dataset.metadata)
    cal_idx, val_metric_idx = _calibration_split(valid_idx, metadata)
    eval_idx = test_idx if len(test_idx) else valid_idx

    print(f"  splits: train={len(train_idx)}  val={len(valid_idx)}  test={len(test_idx)}")
    print(f"  test exceedance rate: {labels[eval_idx].mean():.1%}")
    print()

    # --- Train global hist-GBM (the production winner's backbone) ---
    print("Training global hist-GBM classifier...")
    baselines = make_baselines(features)
    classifier = baselines.tree_classifier
    classifier.fit(features.iloc[train_idx], labels[train_idx])

    p_train = classifier.predict_proba(features.iloc[train_idx])[:, 1]
    p_cal = classifier.predict_proba(features.iloc[cal_idx])[:, 1]
    p_eval = classifier.predict_proba(features.iloc[eval_idx])[:, 1]

    cal_meta = metadata.iloc[cal_idx].reset_index(drop=True)
    eval_meta = metadata.iloc[eval_idx].reset_index(drop=True)

    # --- Path 1: Baseline (global + hierarchical calibrator) ---
    print("\nPath 1: Global classifier + hierarchical calibrator (baseline)")
    _, cal_baseline = _identity_or_calibrated(p_cal, labels[cal_idx], cal_meta)
    p_eval_baseline = _apply_calibrator(cal_baseline, p_eval, eval_meta)
    aucpr_baseline = _aucpr(labels[eval_idx], p_eval_baseline)
    brier_baseline = _brier(labels[eval_idx], p_eval_baseline)
    print(f"  AUCPR: {aucpr_baseline:.4f}")
    print(f"  Brier: {brier_baseline:.4f}")

    # --- Path 2: Global → per-station residual → hierarchical calibrator ---
    print("\nPath 2: Global + per-station residual GBM + hierarchical calibrator")
    train_meta = metadata.iloc[train_idx].reset_index(drop=True)
    ensemble = PerStationResidualEnsemble(n_jobs=args.n_jobs).fit(
        global_probabilities=p_train,
        features=features.iloc[train_idx].reset_index(drop=True),
        labels=labels[train_idx],
        station_ids=train_meta["station_code"],
    )
    print(f"  Per-station regressors fit: {len(ensemble.regressors_)}")
    print(f"  Coverage summary: {ensemble.coverage_summary(train_meta['station_code'])}")

    # Apply correction on cal + eval probabilities BEFORE the calibrator fits/applies.
    # Calibrator then learns offsets on top of the corrected probs.
    p_cal_corr = ensemble.predict(
        p_cal,
        features.iloc[cal_idx].reset_index(drop=True),
        cal_meta["station_code"],
    )
    p_eval_corr = ensemble.predict(
        p_eval,
        features.iloc[eval_idx].reset_index(drop=True),
        eval_meta["station_code"],
    )

    _, cal_corrected = _identity_or_calibrated(p_cal_corr, labels[cal_idx], cal_meta)
    p_eval_final = _apply_calibrator(cal_corrected, p_eval_corr, eval_meta)
    aucpr_corrected = _aucpr(labels[eval_idx], p_eval_final)
    brier_corrected = _brier(labels[eval_idx], p_eval_final)
    print(f"  AUCPR: {aucpr_corrected:.4f}")
    print(f"  Brier: {brier_corrected:.4f}")

    # --- Delta ---
    print("\n" + "=" * 60)
    print("LIFT MEASUREMENT")
    print("=" * 60)
    print(f"  AUCPR delta: {aucpr_corrected - aucpr_baseline:+.4f} ({(aucpr_corrected - aucpr_baseline) / aucpr_baseline * 100:+.1f}%)")
    print(f"  Brier delta: {brier_corrected - brier_baseline:+.4f} ({(brier_corrected - brier_baseline) / brier_baseline * 100:+.1f}%) (lower is better)")
    print()
    print(f"  Decision threshold from plan: AUCPR delta ≥ +0.025")
    verdict = "SHIP IT" if (aucpr_corrected - aucpr_baseline) >= 0.025 else "MARGINAL — consider not shipping"
    print(f"  Verdict: {verdict}")
    print()

    # --- Per-station residual error breakdown ---
    df = pd.DataFrame({
        "station_code": eval_meta["station_code"].astype(str).to_numpy(),
        "y": labels[eval_idx],
        "p_baseline": p_eval_baseline,
        "p_corrected": p_eval_final,
    })
    df["err_baseline"] = (df["y"] - df["p_baseline"]) ** 2
    df["err_corrected"] = (df["y"] - df["p_corrected"]) ** 2
    by_station = df.groupby("station_code").agg(
        n=("y", "count"),
        mse_baseline=("err_baseline", "mean"),
        mse_corrected=("err_corrected", "mean"),
    )
    by_station = by_station[by_station["n"] >= 5]  # noisy below 5 samples
    by_station["mse_delta"] = by_station["mse_corrected"] - by_station["mse_baseline"]

    print(f"Top 10 stations BENEFITING most (largest MSE reduction):")
    for sc, row in by_station.nsmallest(10, "mse_delta").iterrows():
        print(f"  {sc[:40]:40s}  n={int(row['n']):3d}  Δmse={row['mse_delta']:+.4f}")
    print()
    print(f"Top 10 stations HURT most (largest MSE increase):")
    for sc, row in by_station.nlargest(10, "mse_delta").iterrows():
        print(f"  {sc[:40]:40s}  n={int(row['n']):3d}  Δmse={row['mse_delta']:+.4f}")

    print(f"\nDone in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
