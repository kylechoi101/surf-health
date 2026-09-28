"""Walk-forward backtest: logistic challenger vs the served per-beach lookup.

Both models are scored the way the product serves: a forecast issued at 5 AM on
day D knows only lab rows strictly before D and rain to 5 AM on D. Two outcome
definitions, matching ``served_metrics``:

  same_day      a lab sample taken ON D
  forward_1_3d  the first lab sample in D+1..D+3 (every calendar D in the window)

The challenger's coefficients are refit at the start of each month on sample-days
from the preceding ``--train-years`` (features as of each sample date), so no
prediction ever uses a coefficient fit on its own outcome. The persistence floor
(last sample exceeded -> p >= 0.20) is applied to BOTH, as it is in serving. The
advisory floor is not: advisory history is not reliable back in time.

Where the served log overlaps (forecast_history.parquet, 2026-04-23 onward), the
ML that actually served (``p_exceed_ml``) is scored on the same forward pairs.

    python scripts/compare_logit_challenger.py --curated ../data/curated \
        --out ../data/experiments/logit_challenger
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.json_safe import dumps_strict  # noqa: E402
from app.ml.logit_challenger import (  # noqa: E402
    FEATURE_COLUMNS,
    LOGIT_CHALLENGER_VERSION,
    apply_persistence_floor,
    build_features,
    fit_coefficients,
    load_inputs,
    predict,
)

WET_MONTHS = {11, 12, 1, 2, 3, 4}


def within_beach_auroc(y: np.ndarray, p: np.ndarray, beach: np.ndarray) -> float:
    num = den = 0.0
    for _, idx in pd.Series(np.arange(len(y))).groupby(beach):
        yy, pp = y[idx.to_numpy()], p[idx.to_numpy()]
        n1 = yy.sum()
        n0 = len(yy) - n1
        if n1 and n0:
            num += n1 * n0 * roc_auc_score(yy, pp)
            den += n1 * n0
    return num / den if den else float("nan")


def metrics(y: np.ndarray, p: np.ndarray, beach: np.ndarray) -> dict[str, float]:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return {
        "auroc": roc_auc_score(y, p),
        "aucpr": average_precision_score(y, p),
        "brier": brier_score_loss(y, p),
        "log_loss": log_loss(y, p, labels=[0, 1]),
        "within_beach_auroc": within_beach_auroc(y, p, beach),
    }


def cluster_bootstrap_delta(
    y: np.ndarray, p_new: np.ndarray, p_old: np.ndarray, beach: np.ndarray, reps: int, seed: int = 0
) -> dict[str, list[float]]:
    """95% CI of (challenger - lookup), resampling whole beaches."""
    rng = np.random.default_rng(seed)
    groups = pd.Series(np.arange(len(y))).groupby(beach).indices
    keys = list(groups)
    out: dict[str, list[float]] = {"auroc": [], "aucpr": [], "brier": []}
    for _ in range(reps):
        idx = np.concatenate([groups[k] for k in rng.choice(keys, len(keys), replace=True)])
        yy = y[idx]
        if yy.min() == yy.max():
            continue
        out["auroc"].append(roc_auc_score(yy, p_new[idx]) - roc_auc_score(yy, p_old[idx]))
        out["aucpr"].append(
            average_precision_score(yy, p_new[idx]) - average_precision_score(yy, p_old[idx])
        )
        out["brier"].append(
            brier_score_loss(yy, p_new[idx]) - brier_score_loss(yy, p_old[idx])
        )
    return {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] for k, v in out.items()}


def forward_pairs(obs: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """(beach, D, outcome) for every D in [start, end] with a first sample in D+1..D+3."""
    days = pd.date_range(start, end, freq="D").to_numpy().astype("datetime64[D]")
    rows = []
    for b, grp in obs.groupby("beach_id", sort=False):
        d = grp["sample_date"].to_numpy().astype("datetime64[D]")
        y = grp["y"].to_numpy()
        nxt = np.searchsorted(d, days, "right")  # first sample strictly after D
        ok = nxt < len(d)
        gap = np.full(len(days), 99)
        gap[ok] = (d[nxt[ok]] - days[ok]) / np.timedelta64(1, "D")
        keep = ok & (gap <= 3)
        if keep.any():
            rows.append(pd.DataFrame({"beach_id": b, "date": days[keep], "y": y[nxt[keep]]}))
    return pd.concat(rows, ignore_index=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--curated", type=Path, default=Path("../data/curated"))
    ap.add_argument("--out", type=Path, default=Path("../data/experiments/logit_challenger"))
    ap.add_argument("--start", default="2025-09-01")
    ap.add_argument("--end", default=None, help="last forecast date (default: last sample - 3d)")
    ap.add_argument("--train-years", type=int, default=4)
    ap.add_argument("--bootstrap", type=int, default=300)
    args = ap.parse_args()

    # Same curated artifacts, same loader, same beach->rain-station rule as the
    # daily workflow's serving step (lookup_serving -> estimate_for_serving).
    inputs = load_inputs(args.curated)
    pr = inputs.precip_daily
    bd = inputs.beach_day.copy()
    bd["sample_date"] = pd.to_datetime(bd["sample_date"]).dt.normalize()
    bd = bd[bd["exceeds_stv"].notna()].sort_values(["beach_id", "sample_date"])
    bd["y"] = bd["exceeds_stv"].astype(int)
    county = bd.drop_duplicates("beach_id").set_index("beach_id")["county"]

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end) if args.end else bd["sample_date"].max() - pd.Timedelta(days=3)
    precip_start = pd.to_datetime(pr["sample_date"]).min()
    train_start = max(start - pd.DateOffset(years=args.train_years), precip_start)

    # ---- training rows: every sample-day, features as of its own date ----
    tr = bd[(bd["sample_date"] >= train_start) & (bd["sample_date"] < start + pd.DateOffset(years=2))]
    tr_feats = build_features(inputs, tr["beach_id"].tolist(), tr["sample_date"].tolist())
    tr_feats["y"] = tr["y"].to_numpy()

    # ---- evaluation pairs ----
    same = bd[(bd["sample_date"] >= start) & (bd["sample_date"] <= end)][["beach_id", "sample_date", "y"]]
    same = same.rename(columns={"sample_date": "date"}).assign(outcome="same_day")
    fwd = forward_pairs(bd[["beach_id", "sample_date", "y"]], start, end).assign(outcome="forward_1_3d")
    pairs = pd.concat([same, fwd], ignore_index=True)
    feats = build_features(inputs, pairs["beach_id"].tolist(), pairs["date"].tolist())
    pairs = pd.concat([pairs.reset_index(drop=True), feats.drop(columns=["beach_id", "date"])], axis=1)

    # ---- monthly walk-forward refit ----
    pairs["refit_month"] = pairs["date"].dt.to_period("M").dt.to_timestamp()
    coef_rows = []
    pairs["p_challenger_raw"] = np.nan
    for month, idx in pairs.groupby("refit_month").groups.items():
        window = (tr_feats["date"] < month) & (tr_feats["date"] >= month - pd.DateOffset(years=args.train_years))
        coefs = fit_coefficients(tr_feats.loc[window], tr_feats.loc[window, "y"])
        coef_rows.append({"refit_month": str(month.date()), "train_rows": int(window.sum()), **coefs})
        pairs.loc[idx, "p_challenger_raw"] = predict(pairs.loc[idx], coefs)
    pairs["p_lookup"] = apply_persistence_floor(pairs["lookup"], pairs["last_exceeds"])
    pairs["p_challenger"] = apply_persistence_floor(pairs["p_challenger_raw"], pairs["last_exceeds"])
    pairs["county"] = pairs["beach_id"].map(county)
    pairs["wet"] = pairs["date"].dt.month.isin(WET_MONTHS)
    pairs["san_diego"] = pairs["county"].eq("San Diego")

    # ---- the ML that actually served, where the log overlaps ----
    fh_path = args.curated / "forecast_history.parquet"
    if fh_path.exists():
        fh = pd.read_parquet(fh_path)
        fh["date"] = pd.to_datetime(fh["forecast_date"]).dt.normalize()
        fh = fh.sort_values("forecast_generated_at").drop_duplicates(["beach_id", "date"], keep="last")
        pairs = pairs.merge(fh[["beach_id", "date", "p_exceed_ml"]], on=["beach_id", "date"], how="left")

    slices = {
        "all": np.ones(len(pairs), bool),
        "wet (Nov-Apr)": pairs["wet"].to_numpy(),
        "dry (May-Oct)": ~pairs["wet"].to_numpy(),
        "San Diego": pairs["san_diego"].to_numpy(),
        "not San Diego": ~pairs["san_diego"].to_numpy(),
        "not SD, wet": (~pairs["san_diego"] & pairs["wet"]).to_numpy(),
        "not SD, dry": (~pairs["san_diego"] & ~pairs["wet"]).to_numpy(),
    }
    results: dict = {"model": LOGIT_CHALLENGER_VERSION, "features": list(FEATURE_COLUMNS),
                     "window": [str(start.date()), str(end.date())], "coefficients": coef_rows,
                     "outcomes": {}}
    for outcome in ("same_day", "forward_1_3d"):
        o = pairs[pairs["outcome"] == outcome]
        res = {}
        for name, mask in slices.items():
            m = mask[pairs["outcome"].to_numpy() == outcome]
            s = o[m]
            if s["y"].nunique() < 2:
                continue
            y, b = s["y"].to_numpy(), s["beach_id"].to_numpy()
            res[name] = {
                "n": int(len(s)), "beaches": int(s["beach_id"].nunique()), "base_rate": float(y.mean()),
                "lookup": metrics(y, s["p_lookup"].to_numpy(), b),
                "challenger": metrics(y, s["p_challenger"].to_numpy(), b),
            }
            if name in ("all", "not San Diego", "wet (Nov-Apr)", "dry (May-Oct)") and args.bootstrap:
                res[name]["delta_ci95"] = cluster_bootstrap_delta(
                    y, s["p_challenger"].to_numpy(), s["p_lookup"].to_numpy(), b, args.bootstrap
                )
        if "p_exceed_ml" in o.columns:
            s = o[o["p_exceed_ml"].notna()]
            if len(s) and s["y"].nunique() == 2:
                y, b = s["y"].to_numpy(), s["beach_id"].to_numpy()
                res["served-log overlap"] = {
                    "n": int(len(s)), "beaches": int(s["beach_id"].nunique()), "base_rate": float(y.mean()),
                    "window": [str(s["date"].min().date()), str(s["date"].max().date())],
                    "lookup": metrics(y, s["p_lookup"].to_numpy(), b),
                    "challenger": metrics(y, s["p_challenger"].to_numpy(), b),
                    "served_ml": metrics(y, s["p_exceed_ml"].to_numpy(), b),
                }
        results["outcomes"][outcome] = res

    # Calibration of the forward forecast, by predicted-probability bin.
    o = pairs[pairs["outcome"] == "forward_1_3d"]
    bins = [0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]
    results["calibration_forward"] = {
        col: [
            {"p_range": [lo, hi], "n": int(len(g)), "predicted_mean": float(g[col].mean()),
             "actual_rate": float(g["y"].mean())}
            for (lo, hi), g in (
                ((bins[i], bins[i + 1]), o[(o[col] >= bins[i]) & (o[col] < bins[i + 1] + (i == len(bins) - 2))])
                for i in range(len(bins) - 1)
            ) if len(g)
        ]
        for col in ("p_lookup", "p_challenger")
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(dumps_strict(results))
    keep = ["beach_id", "county", "date", "outcome", "y", "lookup", "p_lookup", "p_challenger",
            "p_challenger_raw", "R", "F", "W", "S", "age_days", "last_exceeds"]
    keep += ["p_exceed_ml"] if "p_exceed_ml" in pairs.columns else []
    pairs[keep].to_parquet(args.out / "predictions.parquet", index=False)
    print(json.dumps(results, indent=1, default=str))


if __name__ == "__main__":
    main()
