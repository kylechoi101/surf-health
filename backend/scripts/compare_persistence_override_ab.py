"""A/B: persistence override ON (production) vs OFF (model probability flows through).

Evidence behind the 2026-08-06 "override -> FLOOR" change (see CLAUDE.md). Kept in
the repo because a rerun costs a full retrain (~25 min on 8 cores, plus a torch
install) and the numbers gate a safety-relevant decision. Outputs are committed to
`data/experiments/persistence_override_ab_{predictions.parquet,results.json}` so any
additional cut is a recompute rather than a retrain.

Run:  python -m scripts.compare_persistence_override_ab      (from backend/, py3.12)

⚠️ READ THIS BEFORE CITING THE OUTPUT. This script refits the serving isotonic
SEPARATELY PER ARM, which production cannot do — production reuses one calibrator
fitted on a trailing 120 days of `forecast_history.parquet`. Under the pre-change
code, `p_exceed_precal` on persistence-positive rows WAS the pin (1.0), so that
calibrator is fitted on pin artifacts and its top step caps output at y=0.45.
Pushing this script's arm-B probabilities through the LIVE calibrator instead of a
per-arm refit gives Moderate 999 / High 1120 / Very High 0 (mean 0.344) against an
actual exceedance rate of 0.632 -- NOT the arm-B numbers below. The arm-B figures
are the ceiling this change reaches only once the calibration history is clean.


Both arms share ONE trained model. They differ only in post-processing:

  arm A (production today):  p_model -> pin(persist>=0.5 -> 1.0) -> serving isotonic -> Low floor
  arm B (no override):       p_model ------------------------->  serving isotonic -> Low floor

The serving isotonic is refit SEPARATELY per arm on a held-out slice the model
never trained on, because that is what production would do after the change --
reusing arm A's calibrator on arm B would rig the comparison.

Scored on the temporal test split (later dates, unseen), against the lab result
that defines each row.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/surf-health/backend")

from sklearn.isotonic import IsotonicRegression  # noqa: E402
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score  # noqa: E402

from app.data.pipeline.features import build_sliding_windows  # noqa: E402
from app.ml.calibration import (  # noqa: E402
    _HIGH_THRESHOLD,
    _LOW_THRESHOLD,
    _VERY_HIGH_THRESHOLD,
)
from app.ml.evaluation import sensitivity_at_specificity  # noqa: E402
from app.ml.training import (  # noqa: E402
    _STV_THRESHOLD,
    _apply_stale_censoring,
    _blocked_indices,
    _calibration_split,
    _fit_classifier,
    _fit_classifier_for_name,
    _identity_or_calibrated,
    _load_curated_training_frame,
    _metadata_with_groups,
    _persistence_probabilities,
    _predict_pos,
)
from app.ml.two_tier import within_beach_auroc  # noqa: E402

CURATED = Path("/home/user/surf-health/data/curated")
WINDOW_DAYS = 1095
MODEL = "xgb_undersample_ensemble"
OUT = Path(__file__).with_name("override_ab_results.json")


def banner(msg: str) -> None:
    print(f"\n{'=' * 78}\n{msg}\n{'=' * 78}", flush=True)


def build() -> dict:
    banner("LOAD")
    full = _load_curated_training_frame(CURATED)
    max_date = full["sample_date"].max()
    frame = full.loc[full["sample_date"] > (max_date - pd.Timedelta(days=WINDOW_DAYS))].copy()
    print(f"curated rows in {WINDOW_DAYS}d window: {len(frame)}  (max date {max_date.date()})")

    dataset = build_sliding_windows(frame)
    features = dataset.feature_frame.select_dtypes(include=["number"]).fillna(0.0)
    features = _apply_stale_censoring(features)
    labels = dataset.targets_exceed.astype(int)
    stations = pd.read_parquet(CURATED / "beaches.parquet")
    metadata = _metadata_with_groups(dataset.metadata, frame, stations=stations)

    train_idx, valid_idx, test_idx = _blocked_indices(dataset.metadata)
    cal_idx, val_metric_idx = _calibration_split(valid_idx, metadata)
    print(
        f"rows {len(features)} | train {len(train_idx)} | cal {len(cal_idx)} "
        f"| serving-fit {len(val_metric_idx)} | test {len(test_idx)}"
    )
    print(f"test base rate: {labels[test_idx].mean():.4f}")
    return dict(
        features=features,
        labels=labels,
        metadata=metadata,
        train_idx=train_idx,
        cal_idx=cal_idx,
        val_metric_idx=val_metric_idx,
        test_idx=test_idx,
    )


def fit_model(d: dict) -> dict:
    banner(f"FIT {MODEL}")
    X, y = d["features"], d["labels"]
    tr = d["train_idx"]
    clf = _fit_classifier_for_name(X.iloc[tr], MODEL)
    beach_ids = d["metadata"]["beach_id"].astype(str).to_numpy()
    _fit_classifier(clf, X.iloc[tr], y[tr], beach_ids=beach_ids[tr])
    print("fitted.")

    raw = {k: _predict_pos(clf, X.iloc[d[k]], beach_ids[d[k]]) for k in
           ("cal_idx", "val_metric_idx", "test_idx")}
    # production's own model calibrator: fit on cal_idx, apply forward
    _, calibrator = _identity_or_calibrated(
        raw["cal_idx"], y[d["cal_idx"]], d["metadata"].iloc[d["cal_idx"]].reset_index(drop=True)
    )

    def apply_cal(p, idx):
        if calibrator is None:
            return p
        md = d["metadata"].iloc[idx].reset_index(drop=True)
        try:
            return calibrator.transform(p, md)
        except TypeError:
            return calibrator.transform(p)

    p_model = {k: np.clip(apply_cal(raw[k], d[k]), 0.0, 1.0) for k in raw}
    print(f"model p on test: mean {p_model['test_idx'].mean():.4f} "
          f"| unique {len(np.unique(np.round(p_model['test_idx'], 6)))}")
    return p_model


def arm(p_model_fit, y_fit, p_model_test, persist_fit, persist_test, *, override: bool):
    """One arm: optional pin -> serving isotonic (fit on the fit slice) -> Low floor."""
    if override:
        p_fit = np.where(persist_fit >= 0.5, 1.0, p_model_fit)
        p_test = np.where(persist_test >= 0.5, 1.0, p_model_test)
    else:
        p_fit, p_test = p_model_fit.copy(), p_model_test.copy()

    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(p_fit, y_fit)
    served = np.clip(iso.predict(p_test), 0.0, 1.0)

    # positive-persistence floor survives recalibration in BOTH arms (production
    # training.py:3678-3683) -- this is the safety property, kept either way.
    served = np.where(persist_test >= 0.5, np.maximum(served, _LOW_THRESHOLD), served)
    return served


def band(p: np.ndarray) -> np.ndarray:
    out = np.full(len(p), "Low", dtype=object)
    out[p >= _LOW_THRESHOLD] = "Moderate"
    out[p >= _HIGH_THRESHOLD] = "High"
    out[p >= _VERY_HIGH_THRESHOLD] = "Very High"
    return out


def score(name, y, p, beach_ids) -> dict:
    m = {
        "n": int(len(y)),
        "base_rate": float(y.mean()),
        "mean_p": float(p.mean()),
        "brier": float(brier_score_loss(y, p)),
        "unique_values": int(len(np.unique(np.round(p, 6)))),
    }
    m["brier_flat_baserate"] = float(brier_score_loss(y, np.full(len(y), y.mean())))
    if len(np.unique(y)) > 1:
        m["auroc"] = float(roc_auc_score(y, p))
        m["aucpr"] = float(average_precision_score(y, p))
        # returns a dict (sensitivity/specificity/threshold), not a scalar
        try:
            op = sensitivity_at_specificity(y, p, 0.87)
            m["sens_at_spec_0.87"] = {
                k: (None if v is None or not np.isfinite(v) else float(v))
                for k, v in op.items()
            }
        except Exception as exc:  # noqa: BLE001
            m["sens_at_spec_0.87"] = {"error": repr(exc)}
        wb, nb, nr = within_beach_auroc(y, p, beach_ids)
        m["within_beach_auroc"] = None if not np.isfinite(wb) else float(wb)
        m["within_beach_n_beaches"] = int(nb)
    bands = band(p)
    m["bands"] = {b: int((bands == b).sum()) for b in ("Low", "Moderate", "High", "Very High")}
    return m


def main() -> None:
    d = build()
    p_model = fit_model(d)
    y = d["labels"]
    X = d["features"]
    beach_ids = d["metadata"]["beach_id"].astype(str).to_numpy()

    persist = {k: _persistence_probabilities(X.iloc[d[k]], _STV_THRESHOLD)
               for k in ("val_metric_idx", "test_idx")}
    te, fi = d["test_idx"], d["val_metric_idx"]
    print(f"\npersistence-positive share: serving-fit {persist['val_metric_idx'].mean():.3f} "
          f"| test {persist['test_idx'].mean():.3f}")

    arms = {}
    for label, override in (("A_override_production", True), ("B_no_override", False)):
        arms[label] = arm(
            p_model["val_metric_idx"], y[fi], p_model["test_idx"],
            persist["val_metric_idx"], persist["test_idx"], override=override,
        )

    results = {"config": {"model": MODEL, "window_days": WINDOW_DAYS,
                          "n_test": int(len(te)), "test_base_rate": float(y[te].mean())}}

    banner("OVERALL (temporal test split)")
    for label, p in arms.items():
        results[label] = {"overall": score(label, y[te], p, beach_ids[te])}
        print(f"\n{label}: {json.dumps(results[label]['overall'], indent=2)}")

    banner("THE ROWS THE OVERRIDE TOUCHES (last sample exceeded)")
    mask = persist["test_idx"] >= 0.5
    print(f"n = {int(mask.sum())} of {len(te)} test rows ({mask.mean():.1%}), "
          f"actual exceedance rate {y[te][mask].mean():.4f}")
    for label, p in arms.items():
        results[label]["persistence_positive"] = score(
            label, y[te][mask], p[mask], beach_ids[te][mask]
        )
        print(f"\n{label}: {json.dumps(results[label]['persistence_positive'], indent=2)}")

    banner("ROWS THE OVERRIDE DOES NOT TOUCH (control -- must be ~identical)")
    for label, p in arms.items():
        results[label]["persistence_negative"] = score(
            label, y[te][~mask], p[~mask], beach_ids[te][~mask]
        )
    for label in arms:
        print(f"{label}: brier {results[label]['persistence_negative']['brier']:.5f} "
              f"auroc {results[label]['persistence_negative'].get('auroc')}")

    # Persist the raw held-out arrays so ANY other operating point / metric can
    # be recomputed with no retrain (same pattern as holdout_predictions_*.parquet).
    preds = pd.DataFrame({
        "beach_id": beach_ids[te],
        "sample_date": pd.to_datetime(d["metadata"].iloc[te]["sample_date"].to_numpy()),
        "county": d["metadata"].iloc[te].get("county", pd.Series(index=range(len(te)))).to_numpy(),
        "label": y[te],
        "p_model": p_model["test_idx"],
        "persistence_positive": (persist["test_idx"] >= 0.5).astype(int),
        "p_arm_A_override": arms["A_override_production"],
        "p_arm_B_no_override": arms["B_no_override"],
    })
    pred_path = OUT.with_name("override_ab_predictions.parquet")
    preds.to_parquet(pred_path, index=False)

    OUT.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nwrote {OUT}")
    print(f"wrote {pred_path}  ({len(preds)} held-out rows)")


if __name__ == "__main__":
    main()
