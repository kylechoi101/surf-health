"""A/B: raw mixed-unit bacteria-history features vs action-value-normalized ones.

Reproduces every number in ``docs/ACTION_VALUE_NORMALIZATION.md``.

``beach_day.enterococcus_value`` mixes culture MPN/CFU (action value 104) with
San Diego ddPCR copies/100mL (action value 1413) in one numeric column, and 14
model features carried its magnitude. This branch derives them from
``enterococcus_action_ratio`` (value / that row's own action value) instead.
This script measures whether that changes model skill.

    backend/.venv/bin/python scripts/ab_action_value_normalization.py

Arm A is the pre-change derivation, reconstructed from a git revision of
``features.py`` (``--baseline-rev``, default ``origin/main``) loaded as an
independent module, so the comparison is against real prior code rather than a
re-implementation of it. Same rows, same labels, same covariates, same model,
same folds, same seed; the only difference is which column the bacteria-history
features derive from. Evaluation is on held-out BEACHES, not held-out days.

Expect a null result. The change touches 2.38% of rows directly, and on a
pure-culture beach it is a monotone rescale of individual features, which
gradient-boosted trees are invariant to. A large measured gain here would be
evidence of a leak rather than of skill.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

# macOS: xgboost must be imported before torch (duplicate-libomp segfault).
import xgboost  # noqa: F401
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from app.core.config import get_settings
from app.data.pipeline import features as features_normalized
from app.data.pipeline.exceedance import (
    PCR_ENTEROCOCCUS_THRESHOLD_COPIES,
    is_pcr_measurement,
)
from app.ml.evaluation import sensitivity_at_specificity
from app.ml.models import XGBUndersampleEnsemble
from app.ml.two_tier import within_beach_auroc

FEATURES_PATH_IN_REPO = "backend/app/data/pipeline/features.py"

# Never a model feature in EITHER arm.
#   - The two current-row readings are the label in disguise. The baseline
#     module's `_model_feature_columns` drops `enterococcus_value` but knows
#     nothing about `enterococcus_action_ratio`, so without this it would
#     receive today's reading directly and "win" on a leak.
#   - `is_pcr` / `assay_switch` are this script's analysis columns. Handing the
#     model an assay flag is exactly the intervention this change argues cannot
#     repair the features, so it must not enter through the harness.
NEVER_A_FEATURE = frozenset(
    {
        "enterococcus_value",
        "enterococcus_action_ratio",
        "log_enterococcus",
        "is_pcr",
        "assay_switch",
        "support_status",
    }
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_baseline_features(rev: str):
    """Load a git revision of features.py as an independent module (arm A)."""
    blob = subprocess.run(
        ["git", "show", f"{rev}:{FEATURES_PATH_IN_REPO}"],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    tmp = Path(tempfile.mkdtemp()) / "features_baseline.py"
    tmp.write_text(blob)
    spec = importlib.util.spec_from_file_location("features_baseline", tmp)
    module = importlib.util.module_from_spec(spec)
    sys.modules["features_baseline"] = module
    spec.loader.exec_module(module)
    return module


def load_frame(curated_dir: Path, stv: float) -> pd.DataFrame:
    """beach_day plus the per-row assay, recovered from observations."""
    beach_day = pd.read_parquet(curated_dir / "beach_day.parquet")
    beach_day = beach_day[beach_day["support_status"].astype(str) != "unsupported"].copy()
    beach_day["sample_date"] = pd.to_datetime(beach_day["sample_date"], errors="coerce")
    beach_day["sample_time"] = pd.to_datetime(beach_day["sample_time"], errors="coerce")
    beach_day["enterococcus_value"] = pd.to_numeric(
        beach_day["enterococcus_value"], errors="coerce"
    )
    beach_day["exceeds_stv"] = beach_day["exceeds_stv"].astype(int)

    # Reproduce build_beach_day_frame's worst-sample day collapse so the assay
    # attributed to a beach-day is the assay of the sample it actually kept.
    observations = pd.read_parquet(curated_dir / "observations.parquet")
    ranked = observations.copy()
    ranked["_exceed_rank"] = ranked["exceeds_stv"].fillna(False).astype(bool).astype(int)
    ranked["_value_rank"] = pd.to_numeric(ranked["value"], errors="coerce").fillna(
        float("-inf")
    )
    kept = (
        ranked.sort_values(["_exceed_rank", "_value_rank", "sample_time"])
        .groupby(["beach_id", "sample_date"], as_index=False)
        .tail(1)
    )[["beach_id", "sample_date", "method", "units"]]
    kept["is_pcr"] = is_pcr_measurement(kept["method"], kept["units"]).to_numpy()
    kept["sample_date"] = pd.to_datetime(kept["sample_date"])

    frame = beach_day.merge(
        kept[["beach_id", "sample_date", "is_pcr"]], on=["beach_id", "sample_date"], how="left"
    )
    frame["is_pcr"] = frame["is_pcr"].fillna(False).astype(bool)
    frame["enterococcus_action_ratio"] = frame["enterococcus_value"] / np.where(
        frame["is_pcr"], PCR_ENTEROCOCCUS_THRESHOLD_COPIES, stv
    )
    frame = frame.sort_values(["beach_id", "sample_date"]).reset_index(drop=True)
    previous = frame.groupby("beach_id")["is_pcr"].shift(1)
    frame["assay_switch"] = previous.notna() & (
        previous.fillna(False).astype(bool) != frame["is_pcr"]
    )
    return frame


def build_arm(frame: pd.DataFrame, module) -> tuple[pd.DataFrame, pd.DataFrame]:
    enriched = module.add_temporal_features(frame)
    columns = [
        column
        for column in module._model_feature_columns(enriched)
        if column not in NEVER_A_FEATURE
    ]
    labeled = enriched.loc[enriched["exceeds_stv"].notna()].copy()
    return labeled[columns], labeled


def operating_point(labels, probabilities, target: float = 0.87) -> dict:
    """Searcy-convention operating point, with PPV — AUROC alone hides precision."""
    point = sensitivity_at_specificity(np.asarray(labels), np.asarray(probabilities), target)
    labels = np.asarray(labels).astype(int)
    flagged = np.asarray(probabilities) >= point["threshold"]
    true_positive = int((flagged & (labels == 1)).sum())
    false_positive = int((flagged & (labels == 0)).sum())
    denominator = true_positive + false_positive
    return {
        "sensitivity": point["sensitivity"],
        "specificity": point["specificity"],
        "ppv": (true_positive / denominator) if denominator else float("nan"),
        "threshold": point["threshold"],
    }


def stratum_metrics(labels, probabilities, beaches, name: str, global_base: float) -> dict:
    labels = np.asarray(labels).astype(int)
    probabilities = np.asarray(probabilities, dtype=float)
    if len(labels) == 0 or labels.sum() in (0, len(labels)):
        return {"stratum": name, "n": int(len(labels)), "positives": int(labels.sum())}
    auroc, n_beaches, n_rows = within_beach_auroc(labels, probabilities, beaches, min_samples=20)
    point = operating_point(labels, probabilities)
    base = float(labels.mean())
    return {
        "stratum": name,
        "n": int(len(labels)),
        "positives": int(labels.sum()),
        "base_rate": base,
        "within_beach_auroc": auroc,
        "wba_beaches": n_beaches,
        "wba_rows": n_rows,
        "sens_at_spec87": point["sensitivity"],
        "ppv_at_spec87": point["ppv"],
        "spec_achieved": point["specificity"],
        "brier": float(np.mean((probabilities - labels) ** 2)),
        # Two reference constants: the population-wide rate, and the rate a
        # forecaster who knew only the stratum would quote.
        "brier_flat_global": float(np.mean((global_base - labels) ** 2)),
        "brier_flat_stratum": float(np.mean((base - labels) ** 2)),
    }


def cluster_bootstrap(labels, p_a, p_b, beaches, draws: int, rng) -> dict:
    """Paired bootstrap over BEACHES — the unit repeated measurements cluster in.

    Per-beach summaries are computed once and the draws only re-weight them,
    which is what a cluster bootstrap does and avoids recomputing every ROC
    curve per draw.
    """
    unique = np.unique(beaches)
    counts, sq_a, sq_b, auc_a, auc_b, scorable = [], [], [], [], [], []
    for beach in unique:
        index = np.flatnonzero(beaches == beach)
        y = labels[index]
        counts.append(len(index))
        sq_a.append(float(np.sum((p_a[index] - y) ** 2)))
        sq_b.append(float(np.sum((p_b[index] - y) ** 2)))
        if len(index) >= 20 and 0 < y.sum() < len(y):
            auc_a.append(float(roc_auc_score(y, p_a[index])))
            auc_b.append(float(roc_auc_score(y, p_b[index])))
            scorable.append(True)
        else:
            auc_a.append(np.nan)
            auc_b.append(np.nan)
            scorable.append(False)
    counts = np.asarray(counts, dtype=float)
    sq_a, sq_b = np.asarray(sq_a), np.asarray(sq_b)
    auc_a, auc_b = np.asarray(auc_a), np.asarray(auc_b)
    scorable = np.asarray(scorable, dtype=bool)

    brier_gaps, auroc_gaps = [], []
    for _ in range(draws):
        pick = rng.integers(0, len(unique), size=len(unique))
        total = counts[pick].sum()
        if total == 0:
            continue
        brier_gaps.append(float((sq_a[pick].sum() - sq_b[pick].sum()) / total))
        mask = scorable[pick]
        if mask.any():
            weights = counts[pick][mask]
            auroc_gaps.append(
                float(
                    np.average(auc_b[pick][mask], weights=weights)
                    - np.average(auc_a[pick][mask], weights=weights)
                )
            )

    def summarize(values: list[float]) -> dict:
        if not values:
            return {"mean": float("nan"), "ci_low": float("nan"), "ci_high": float("nan")}
        array = np.asarray(values)
        return {
            "mean": float(array.mean()),
            "ci_low": float(np.percentile(array, 2.5)),
            "ci_high": float(np.percentile(array, 97.5)),
        }

    return {
        "n_beaches": int(len(unique)),
        # Positive means arm B (normalized) is better on both.
        "brier_gain_A_minus_B": summarize(brier_gaps),
        "within_beach_auroc_gain_B_minus_A": summarize(auroc_gaps),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-rev", default="origin/main")
    parser.add_argument("--window-days", type=int, default=1095)
    parser.add_argument("--warmup-days", type=int, default=60)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--bootstrap-draws", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260810)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    curated_dir = Path(settings.curated_dir)
    stv = settings.epa_marine_enterococcus_stv
    output = args.output or (_repo_root() / "data" / "experiments" / "action_value_normalization")
    output.mkdir(parents=True, exist_ok=True)

    features_raw = load_baseline_features(args.baseline_rev)

    frame = load_frame(curated_dir, stv)
    max_date = frame["sample_date"].max()
    window_start = max_date - pd.Timedelta(days=args.window_days)
    build_frame = frame[
        frame["sample_date"] >= window_start - pd.Timedelta(days=args.warmup_days)
    ].copy()
    print(
        f"[data] {len(build_frame)} rows built, evaluated from {window_start.date()}",
        flush=True,
    )

    arms = {}
    for name, module in (("A_raw", features_raw), ("B_ratio", features_normalized)):
        X, meta = build_arm(build_frame, module)
        arms[name] = (X.reset_index(drop=True), meta.reset_index(drop=True))
        print(f"[{name}] features {X.shape}", flush=True)

    only_a = sorted(set(arms["A_raw"][0].columns) - set(arms["B_ratio"][0].columns))
    only_b = sorted(set(arms["B_ratio"][0].columns) - set(arms["A_raw"][0].columns))
    print(f"[diff] only in A ({len(only_a)}): {only_a}")
    print(f"[diff] only in B ({len(only_b)}): {only_b}")
    for name, (X, _) in arms.items():
        leaked = sorted(set(X.columns) & NEVER_A_FEATURE)
        assert not leaked, f"{name} leaked {leaked}"
    assert len(arms["A_raw"][0].columns) == len(arms["B_ratio"][0].columns)

    meta = arms["A_raw"][1]
    other = arms["B_ratio"][1]
    assert (meta["beach_id"].to_numpy() == other["beach_id"].to_numpy()).all()
    assert (meta["exceeds_stv"].to_numpy() == other["exceeds_stv"].to_numpy()).all()

    labels = meta["exceeds_stv"].astype(int).to_numpy()
    beaches = meta["beach_id"].astype(str).to_numpy()
    in_window = (meta["sample_date"] >= window_start).to_numpy()

    # ------------------------------------------------ latitude residual check
    latitude = pd.to_numeric(meta["latitude"], errors="coerce")
    latitude_rows: dict[str, dict] = {}
    for arm, template in (
        ("A_raw", "enterococcus_value_lag_{}"),
        ("B_ratio", "enterococcus_action_ratio_lag_{}"),
    ):
        X = arms[arm][0]
        for lag in (1, 2, 3, 7):
            column = template.format(lag)
            if column not in X.columns:
                continue
            values = pd.to_numeric(X[column], errors="coerce")
            usable = values.notna() & latitude.notna() & pd.Series(in_window)
            latitude_rows.setdefault(f"lag_{lag}", {})[arm] = float(
                values[usable].corr(latitude[usable], method="spearman")
            )
            latitude_rows[f"lag_{lag}"]["n"] = int(usable.sum())
    print("\n=== |Spearman| of the short lags against latitude (window rows) ===")
    for key, value in latitude_rows.items():
        print(
            f"  {key}: A_raw {value['A_raw']:+.4f}  B_ratio {value['B_ratio']:+.4f}"
            f"  (n={value['n']})"
        )

    # ------------------------------------------------------ held-out beaches
    splits = list(GroupKFold(n_splits=args.folds).split(np.zeros(len(meta)), labels, beaches))
    predictions = {name: np.full(len(meta), np.nan) for name in arms}
    rng = np.random.default_rng(args.seed)
    for fold, (train_idx, test_idx) in enumerate(splits):
        # Inner BEACH split for the isotonic calibrator — identical across arms,
        # so the Brier comparison is not an artefact of one arm's calibration.
        train_beaches = rng.permutation(np.unique(beaches[train_idx]))
        calibration_beaches = set(train_beaches[: max(1, int(0.2 * len(train_beaches)))])
        is_calibration = np.isin(beaches[train_idx], list(calibration_beaches))
        fit_idx = train_idx[~is_calibration]
        calibration_idx = train_idx[is_calibration]
        for name, (X, _) in arms.items():
            model = XGBUndersampleEnsemble(random_state=args.seed)
            model.fit(X.iloc[fit_idx], labels[fit_idx])
            calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            calibrator.fit(
                model.predict_proba(X.iloc[calibration_idx])[:, 1], labels[calibration_idx]
            )
            predictions[name][test_idx] = calibrator.predict(
                model.predict_proba(X.iloc[test_idx])[:, 1]
            )
        print(
            f"[fold {fold}] train={len(fit_idx)} calib={len(calibration_idx)} "
            f"test={len(test_idx)} test_beaches={len(np.unique(beaches[test_idx]))}",
            flush=True,
        )

    scored = (
        in_window & ~np.isnan(predictions["A_raw"]) & ~np.isnan(predictions["B_ratio"])
    )
    y = labels[scored]
    beach = beaches[scored]
    is_pcr = meta["is_pcr"].to_numpy()[scored]
    switch = meta["assay_switch"].fillna(False).to_numpy().astype(bool)[scored]
    global_base = float(y.mean())

    strata = {
        "ALL": np.ones(len(y), dtype=bool),
        "culture": ~is_pcr,
        "ddPCR": is_pcr,
        "assay_switch_rows": switch,
    }
    table = []
    for name, mask in strata.items():
        for arm in ("A_raw", "B_ratio"):
            row = stratum_metrics(
                y[mask], predictions[arm][scored][mask], beach[mask], name, global_base
            )
            row["arm"] = arm
            table.append(row)
    results = pd.DataFrame(table)
    print("\n=== A/B, held-out beaches, isotonic-calibrated ===")
    with pd.option_context("display.width", 220, "display.max_columns", 40):
        print(
            results[
                [
                    "stratum", "arm", "n", "positives", "base_rate", "within_beach_auroc",
                    "sens_at_spec87", "ppv_at_spec87", "brier", "brier_flat_global",
                    "brier_flat_stratum",
                ]
            ].to_string(index=False)
        )

    pd.DataFrame(
        {
            "beach_id": beach,
            "sample_date": meta["sample_date"].to_numpy()[scored],
            "y": y,
            "p_A_raw": predictions["A_raw"][scored],
            "p_B_ratio": predictions["B_ratio"][scored],
            "is_pcr": is_pcr,
            "assay_switch": switch,
        }
    ).to_parquet(output / "ab_predictions.parquet", index=False)

    print("\n=== paired cluster bootstrap over beaches ===")
    boot_rng = np.random.default_rng(args.seed + 1)
    bootstrap = {}
    for name, mask in strata.items():
        if mask.sum() == 0 or y[mask].sum() == 0:
            continue
        summary = cluster_bootstrap(
            y[mask],
            predictions["A_raw"][scored][mask],
            predictions["B_ratio"][scored][mask],
            beach[mask],
            args.bootstrap_draws,
            boot_rng,
        )
        bootstrap[name] = summary
        brier = summary["brier_gain_A_minus_B"]
        auroc = summary["within_beach_auroc_gain_B_minus_A"]
        print(
            f"  {name:20s} beaches={summary['n_beaches']:4d}  "
            f"Brier(A)-Brier(B) = {brier['mean']:+.5f} "
            f"[{brier['ci_low']:+.5f}, {brier['ci_high']:+.5f}]  "
            f"withinAUROC(B)-(A) = {auroc['mean']:+.5f} "
            f"[{auroc['ci_low']:+.5f}, {auroc['ci_high']:+.5f}]"
        )

    payload = {
        "config": {
            "baseline_rev": args.baseline_rev,
            "seed": args.seed,
            "folds": args.folds,
            "window_days": args.window_days,
            "eval_window_start": str(window_start.date()),
            "max_sample_date": str(max_date.date()),
            "model": "XGBUndersampleEnsemble(defaults)",
            "calibration": "isotonic fitted on held-out training beaches",
            "n_features_per_arm": int(arms["A_raw"][0].shape[1]),
            "columns_only_in_A": only_a,
            "columns_only_in_B": only_b,
        },
        "latitude_spearman": latitude_rows,
        "ab": table,
        "bootstrap": bootstrap,
    }
    (output / "ab_results.json").write_text(json.dumps(payload, indent=2, default=float))
    print(f"\nwrote {output / 'ab_results.json'}")


if __name__ == "__main__":
    main()
