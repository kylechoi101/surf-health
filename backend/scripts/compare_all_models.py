"""Walk-forward backtest: compare all candidate models on forward forecasts.

Evaluates candidate models against the served logistic estimate on the same forward
pairs, applying the same persistence floor and strictly-prior feature rules.

Arms:
  pooled        statewide base rate of labels in the 365 d before D (strictly < D)
  persistence   1.0 if the beach's last label before D exceeded, else pooled
  lookup        per-beach historical lookup with Bayesian shrinkage toward pooled
  logit         monthly-refit logistic model with offset L (served baseline)
  logit_method  logit + ddpcr indicator term and its interaction with R
  xgb_ensemble  app.ml.models.XGBUndersampleEnsemble
  xgb_offset    app.ml.models.XGBUndersampleOffsetEnsemble
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.json_safe import dumps_strict  # noqa: E402
from app.data.pipeline.features import (  # noqa: E402
    build_inference_features,
    build_sliding_windows,
)
from app.data.pipeline.sample_key import assay_kind  # noqa: E402
from app.ml.logit_challenger import (  # noqa: E402
    FEATURE_COLUMNS,
    apply_persistence_floor,
    build_features,
    load_inputs,
)
from app.ml.models import (  # noqa: E402
    XGBUndersampleEnsemble,
    XGBUndersampleOffsetEnsemble,
)
from app.ml.training import (  # noqa: E402
    _build_forecast_candidates,
    _load_curated_training_frame,
    _read_optional_parquet,
)

WET_MONTHS = {11, 12, 1, 2, 3, 4}
ALL_ARMS = (
    "pooled",
    "persistence",
    "lookup",
    "logit",
    "logit_method",
    "xgb_ensemble",
    "xgb_offset",
)
LOGIT_METHOD_FEATURE_COLUMNS: tuple[str, ...] = ("R", "RF", "W", "S", "ddpcr", "R_ddpcr")


SERVED_LOG_AUROC_BAR = 0.02


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


def metrics(y: np.ndarray, p: np.ndarray, beach: np.ndarray) -> dict[str, float]:
    valid = ~np.isnan(p)
    if not valid.any() or len(np.unique(y[valid])) < 2:
        return {
            "auroc": float("nan"),
            "aucpr": float("nan"),
            "brier": float("nan"),
            "log_loss": float("nan"),
            "within_beach_auroc": float("nan"),
        }
    y, p, beach = y[valid], p[valid], beach[valid]
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


def derive_label_method_from_observations(curated_dir: Path, beach_day: pd.DataFrame) -> pd.DataFrame:
    """Derive beach_day['label_method'] from observations.parquet if missing."""
    if "label_method" in beach_day.columns:
        return beach_day
    obs_path = curated_dir / "observations.parquet"
    if not obs_path.exists():
        bd = beach_day.copy()
        bd["label_method"] = "culture"
        return bd
    obs = pd.read_parquet(obs_path)
    obs = obs.copy()
    obs["sample_date"] = pd.to_datetime(obs["sample_date"]).dt.normalize()
    obs["_exceed_rank"] = obs["exceeds_stv"].fillna(False).astype(bool).astype(int)
    obs["_value_rank"] = pd.to_numeric(obs["value"], errors="coerce").fillna(float("-inf"))
    sort_cols = ["_exceed_rank", "_value_rank"]
    if "sample_time" in obs.columns:
        sort_cols.append("sample_time")

    worst = (
        obs.sort_values(sort_cols)
        .groupby(["beach_id", "sample_date"], as_index=False)
        .tail(1)
    )
    method_col = worst["method"] if "method" in worst.columns else pd.Series("", index=worst.index)
    units_col = worst["units"] if "units" in worst.columns else pd.Series("", index=worst.index)
    worst["label_method"] = assay_kind(method_col, units_col)

    bd = beach_day.copy()
    bd["sample_date"] = pd.to_datetime(bd["sample_date"]).dt.normalize()
    bd = bd.merge(worst[["beach_id", "sample_date", "label_method"]], on=["beach_id", "sample_date"], how="left")
    bd["label_method"] = bd["label_method"].fillna("culture")
    return bd


def compute_assays(beach_day: pd.DataFrame, beach_ids: Sequence[str], dates: Sequence) -> np.ndarray:
    """The beach's assay = its most recent beach_day.label_method before D (strictly < D)."""
    bids = np.asarray(list(beach_ids), dtype=object)
    qd = pd.to_datetime(pd.Series(dates)).dt.normalize().to_numpy().astype("datetime64[D]")
    n_rows = len(bids)
    assays = np.full(n_rows, "culture", dtype=object)

    bd = beach_day.sort_values(["beach_id", "sample_date"])
    by_beach = {b: grp for b, grp in bd.groupby("beach_id", sort=False)}
    order = pd.Series(np.arange(n_rows)).groupby(bids)

    for b, idx in order:
        grp = by_beach.get(b)
        if grp is None:
            continue
        idx = idx.to_numpy()
        d = pd.to_datetime(grp["sample_date"]).dt.normalize().to_numpy().astype("datetime64[D]")
        m = grp["label_method"].to_numpy()
        q = qd[idx]
        h = np.searchsorted(d, q, "left")
        has = h > 0
        last = np.where(has, h - 1, 0)
        assays[idx] = np.where(has, m[last], "culture")
    return assays


def fit_coefficients_custom(
    features: pd.DataFrame,
    y: Sequence,
    feature_columns: Sequence[str],
    ridge: float = 1e-4,
    max_iter: int = 50,
) -> dict[str, float]:
    """Logistic regression with ``L`` as a fixed offset (Newton / IRLS)."""
    X = np.column_stack([np.ones(len(features))] + [features[c].to_numpy(float) for c in feature_columns])
    off = features["L"].to_numpy(float)
    yy = np.asarray(y, dtype=float)
    beta = np.zeros(X.shape[1])
    penalty = ridge * np.eye(X.shape[1])
    penalty[0, 0] = 0.0
    for _ in range(max_iter):
        p = 1.0 / (1.0 + np.exp(-(off + X @ beta)))
        w = p * (1 - p)
        grad = X.T @ (yy - p) - penalty @ beta
        hess = (X * w[:, None]).T @ X + penalty
        step = np.linalg.solve(hess, grad)
        beta += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return dict(zip(("intercept",) + tuple(feature_columns), map(float, beta)))


def predict_custom(
    features: pd.DataFrame, coefs: Mapping[str, float], feature_columns: Sequence[str]
) -> np.ndarray:
    eta = features["L"].to_numpy(float) + coefs["intercept"]
    for c in feature_columns:
        eta = eta + coefs[c] * features[c].to_numpy(float)
    return 1.0 / (1.0 + np.exp(-eta))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--curated", type=Path, default=Path("../data/curated"))
    ap.add_argument("--out", type=Path, default=Path("../data/experiments/compare_all_models"))
    ap.add_argument("--start", default="2025-09-01")
    ap.add_argument("--end", default=None, help="last forecast date (default: last sample - 3d)")
    ap.add_argument("--train-years", type=int, default=4)
    ap.add_argument("--bootstrap", type=int, default=300)
    ap.add_argument("--arms", default="all", help="comma list of arms (default: all)")
    ap.add_argument("--xgb-grid-days", type=int, default=1, help="grid spacing for XGB arms (default: 1)")
    args = ap.parse_args()

    if args.arms == "all":
        active_arms = list(ALL_ARMS)
    else:
        active_arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    for arm in active_arms:
        if arm not in ALL_ARMS:
            raise ValueError(f"Unknown arm: {arm}. Must be one of {ALL_ARMS}")

    inputs = load_inputs(args.curated)
    pr = inputs.precip_daily
    bd = derive_label_method_from_observations(args.curated, inputs.beach_day)
    bd["sample_date"] = pd.to_datetime(bd["sample_date"]).dt.normalize()
    bd = bd[bd["exceeds_stv"].notna()].sort_values(["beach_id", "sample_date"])
    bd["y"] = bd["exceeds_stv"].astype(int)
    county = bd.drop_duplicates("beach_id").set_index("beach_id")["county"]

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end) if args.end else bd["sample_date"].max() - pd.Timedelta(days=3)
    precip_start = pd.to_datetime(pr["sample_date"]).min()
    train_start = max(start - pd.DateOffset(years=args.train_years), precip_start)

    # ---- training rows for logit arms: every sample-day, features as of its own date ----
    tr = bd[(bd["sample_date"] >= train_start) & (bd["sample_date"] < start + pd.DateOffset(years=2))]
    tr_feats = build_features(inputs, tr["beach_id"].tolist(), tr["sample_date"].tolist())
    tr_feats["y"] = tr["y"].to_numpy()

    needs_method = "logit_method" in active_arms
    if needs_method:
        tr_feats["assay"] = compute_assays(bd, tr["beach_id"].tolist(), tr["sample_date"].tolist())
        tr_feats["ddpcr"] = (tr_feats["assay"] == "ddpcr").astype(float)
        tr_feats["R_ddpcr"] = tr_feats["R"] * tr_feats["ddpcr"]

    # ---- evaluation pairs ----
    same = bd[(bd["sample_date"] >= start) & (bd["sample_date"] <= end)][["beach_id", "sample_date", "y"]]
    same = same.rename(columns={"sample_date": "date"}).assign(outcome="same_day")
    fwd = forward_pairs(bd[["beach_id", "sample_date", "y"]], start, end).assign(outcome="forward_1_3d")
    pairs = pd.concat([same, fwd], ignore_index=True)
    feats = build_features(inputs, pairs["beach_id"].tolist(), pairs["date"].tolist())
    pairs = pd.concat([pairs.reset_index(drop=True), feats.drop(columns=["beach_id", "date"])], axis=1)

    pairs["county"] = pairs["beach_id"].map(county)
    pairs["wet"] = pairs["date"].dt.month.isin(WET_MONTHS)
    pairs["san_diego"] = pairs["county"].eq("San Diego")

    # Beach assay at D (strictly < D)
    pairs["assay"] = compute_assays(bd, pairs["beach_id"].tolist(), pairs["date"].tolist())
    pairs["ddpcr"] = (pairs["assay"] == "ddpcr").astype(float)
    pairs["R_ddpcr"] = pairs["R"] * pairs["ddpcr"]

    # ---- Arm scoring ----
    # 1. pooled: statewide base rate of labels in the 365 d before D (strictly < D)
    if "pooled" in active_arms:
        pairs["p_pooled_raw"] = pairs["g"]
        pairs["p_pooled"] = apply_persistence_floor(pairs["p_pooled_raw"], pairs["last_exceeds"])

    # 2. persistence: 1.0 if the beach's last label before D exceeded, else pooled
    if "persistence" in active_arms:
        pairs["p_persistence_raw"] = np.where(pairs["last_exceeds"] == 1, 1.0, pairs["g"])
        pairs["p_persistence"] = apply_persistence_floor(pairs["p_persistence_raw"], pairs["last_exceeds"])

    # 3. lookup: pairs["lookup"]
    if "lookup" in active_arms:
        pairs["p_lookup"] = apply_persistence_floor(pairs["lookup"], pairs["last_exceeds"])

    # 4 & 5. logit and logit_method monthly walk-forward refit
    pairs["refit_month"] = pairs["date"].dt.to_period("M").dt.to_timestamp()
    coef_rows_logit = []
    coef_rows_method = []
    if "logit" in active_arms:
        pairs["p_logit_raw"] = np.nan
    if "logit_method" in active_arms:
        pairs["p_logit_method_raw"] = np.nan

    if "logit" in active_arms or "logit_method" in active_arms:
        for month, idx in pairs.groupby("refit_month").groups.items():
            window = (tr_feats["date"] < month) & (tr_feats["date"] >= month - pd.DateOffset(years=args.train_years))
            w_feats = tr_feats.loc[window]
            w_y = tr_feats.loc[window, "y"]

            if "logit" in active_arms:
                coefs_l = fit_coefficients_custom(w_feats, w_y, FEATURE_COLUMNS)
                coef_rows_logit.append({"refit_month": str(month.date()), "train_rows": int(window.sum()), **coefs_l})
                pairs.loc[idx, "p_logit_raw"] = predict_custom(pairs.loc[idx], coefs_l, FEATURE_COLUMNS)

            if "logit_method" in active_arms:
                coefs_m = fit_coefficients_custom(w_feats, w_y, LOGIT_METHOD_FEATURE_COLUMNS)
                coef_rows_method.append({"refit_month": str(month.date()), "train_rows": int(window.sum()), **coefs_m})
                pairs.loc[idx, "p_logit_method_raw"] = predict_custom(pairs.loc[idx], coefs_m, LOGIT_METHOD_FEATURE_COLUMNS)

    if "logit" in active_arms:
        pairs["p_logit"] = apply_persistence_floor(pairs["p_logit_raw"], pairs["last_exceeds"])
    if "logit_method" in active_arms:
        pairs["p_logit_method"] = apply_persistence_floor(pairs["p_logit_method_raw"], pairs["last_exceeds"])

    # ---- 6 & 7. XGB arms (xgb_ensemble, xgb_offset) ----
    has_xgb = "xgb_ensemble" in active_arms or "xgb_offset" in active_arms
    chosen_grid_days = args.xgb_grid_days
    per_d_time = 0.0
    grid_day_set: set = set()

    if has_xgb:
        print("[compare_all_models] Preparing XGB training and served-regime scoring...", file=sys.stderr, flush=True)
        training_frame = _load_curated_training_frame(args.curated)
        training_frame["sample_date"] = pd.to_datetime(training_frame["sample_date"]).dt.normalize()

        # Load candidate scoring parquet inputs once (as in training.py:3525)
        stations = pd.read_parquet(args.curated / "beaches.parquet")
        uv_daily = _read_optional_parquet(args.curated / "uv_daily.parquet")
        if uv_daily is None:
            uv_daily = pd.DataFrame()
        advisories = _read_optional_parquet(args.curated / "advisories.parquet")
        precip_daily_all = _read_optional_parquet(args.curated / "precip_daily.parquet")
        streamflow_daily_all = _read_optional_parquet(args.curated / "streamflow_daily.parquet")
        hydrologic_links_all = _read_optional_parquet(args.curated / "hydrologic_beach_links.parquet")

        # Step 4: Cost control — time one forecast date D before the full loop
        sample_D = start.date()
        frame_before_sample_D = training_frame.loc[training_frame["sample_date"] < pd.Timestamp(sample_D)]
        t0 = time.time()
        hist_sample, cands_sample = _build_forecast_candidates(
            frame_before_sample_D,
            stations,
            uv_daily,
            sample_D,
            full_frame=frame_before_sample_D,
            advisories=advisories,
            min_sample_recency_days=None,
            precip_daily=precip_daily_all,
            streamflow_daily=streamflow_daily_all,
            hydrologic_links=hydrologic_links_all,
        )
        if not cands_sample.empty:
            inf_in = pd.concat([hist_sample, cands_sample], ignore_index=True)
            _ = build_inference_features(inf_in)
        per_d_time = time.time() - t0
        print(f"[compare_all_models] One day candidate build took: {per_d_time:.2f}s", file=sys.stderr, flush=True)

        if args.xgb_grid_days == 1 and per_d_time > 15.0:
            chosen_grid_days = 7
            print(f"[compare_all_models] Setting default xgb_grid_days to {chosen_grid_days} (> 15s/day)", file=sys.stderr, flush=True)

        all_days = pd.date_range(start, end, freq="D")
        grid_days = all_days[::chosen_grid_days]
        grid_day_set = set(grid_days.date)

        # Train quarterly models
        quarterly_quarters = sorted({d.to_period("Q") for d in grid_days})
        quarterly_models_ens = {}
        quarterly_models_off = {}
        quarterly_feat_cols = {}

        for q in quarterly_quarters:
            refit = q.to_timestamp()
            q_train_start = refit - pd.DateOffset(years=args.train_years)
            tr_q = training_frame.loc[
                (training_frame["sample_date"] >= q_train_start) & (training_frame["sample_date"] < refit)
            ].copy()
            # Same construction as training.py's _run_winner_only: sliding-window
            # dataset -> numeric feature frame, labels and beach ids aligned to it.
            dataset_q = build_sliding_windows(tr_q)
            X_q = dataset_q.feature_frame.select_dtypes(include=["number"]).fillna(0.0)
            y_q = dataset_q.targets_exceed.astype(int)
            b_q = dataset_q.metadata["beach_id"].to_numpy()
            feat_names = list(X_q.columns)
            quarterly_feat_cols[q] = feat_names

            if "xgb_ensemble" in active_arms:
                print(f"[compare_all_models] Fitting XGBUndersampleEnsemble for quarter {q} (rows={len(X_q)})...", file=sys.stderr, flush=True)
                quarterly_models_ens[q] = XGBUndersampleEnsemble().fit(X_q, y_q)

            if "xgb_offset" in active_arms:
                print(f"[compare_all_models] Fitting XGBUndersampleOffsetEnsemble for quarter {q} (rows={len(X_q)})...", file=sys.stderr, flush=True)
                quarterly_models_off[q] = XGBUndersampleOffsetEnsemble().fit(X_q, y_q, beach_ids=b_q)

        # Score candidates for each forecast day D on the grid
        if "xgb_ensemble" in active_arms:
            pairs["p_xgb_ensemble_raw"] = np.nan
        if "xgb_offset" in active_arms:
            pairs["p_xgb_offset_raw"] = np.nan

        for D_ts in grid_days:
            D = D_ts.date()
            q = D_ts.to_period("Q")
            feat_names = quarterly_feat_cols[q]
            frame_before_D = training_frame.loc[training_frame["sample_date"] < D_ts]
            hist_d, cands_d = _build_forecast_candidates(
                frame_before_D,
                stations,
                uv_daily,
                D,
                full_frame=frame_before_D,
                advisories=advisories,
                min_sample_recency_days=None,
                precip_daily=precip_daily_all,
                streamflow_daily=streamflow_daily_all,
                hydrologic_links=hydrologic_links_all,
            )
            if cands_d.empty:
                continue
            inf_in = pd.concat([hist_d, cands_d], ignore_index=True)
            inf_ds = build_inference_features(inf_in)
            cand_feats = inf_ds.feature_frame
            cand_meta = inf_ds.metadata
            X_cand = cand_feats.select_dtypes(include=["number"]).fillna(0.0).reindex(columns=feat_names, fill_value=0.0)
            bids_cand = cand_meta["beach_id"].to_numpy()

            d_mask = pairs["date"].dt.date == D

            if "xgb_ensemble" in active_arms:
                p_ens = quarterly_models_ens[q].predict_proba(X_cand)[:, 1]
                mapping_ens = dict(zip(bids_cand, p_ens))
                preds_ens_series = pairs.loc[d_mask, "beach_id"].map(mapping_ens)
                pairs.loc[d_mask, "p_xgb_ensemble_raw"] = preds_ens_series

            if "xgb_offset" in active_arms:
                p_off = quarterly_models_off[q].predict_proba(X_cand, beach_ids=bids_cand)[:, 1]
                mapping_off = dict(zip(bids_cand, p_off))
                preds_off_series = pairs.loc[d_mask, "beach_id"].map(mapping_off)
                pairs.loc[d_mask, "p_xgb_offset_raw"] = preds_off_series

        if "xgb_ensemble" in active_arms:
            pairs["p_xgb_ensemble"] = apply_persistence_floor(pairs["p_xgb_ensemble_raw"], pairs["last_exceeds"])
        if "xgb_offset" in active_arms:
            pairs["p_xgb_offset"] = apply_persistence_floor(pairs["p_xgb_offset_raw"], pairs["last_exceeds"])

    # ---- the ML that actually served, where the log overlaps ----
    fh_path = args.curated / "forecast_history.parquet"
    if fh_path.exists():
        fh = pd.read_parquet(fh_path)
        fh["date"] = pd.to_datetime(fh["forecast_date"]).dt.normalize()
        fh = fh.sort_values("forecast_generated_at").drop_duplicates(["beach_id", "date"], keep="last")
        fh_cols = [
            c
            for c in ("p_exceed_ml", "p_exceed_precal", "p_exceed_raw", "served_offset_weight")
            if c in fh.columns
        ]
        pairs = pairs.merge(fh[["beach_id", "date", *fh_cols]], on=["beach_id", "date"], how="left")

    slices = {
        "all": np.ones(len(pairs), bool),
        "wet (Nov-Apr)": pairs["wet"].to_numpy(),
        "dry (May-Oct)": ~pairs["wet"].to_numpy(),
        "San Diego": pairs["san_diego"].to_numpy(),
        "not San Diego": ~pairs["san_diego"].to_numpy(),
        "not SD, wet": (~pairs["san_diego"] & pairs["wet"]).to_numpy(),
        "not SD, dry": (~pairs["san_diego"] & ~pairs["wet"]).to_numpy(),
        "culture": (pairs["assay"] == "culture").to_numpy(),
        "ddpcr": (pairs["assay"] == "ddpcr").to_numpy(),
    }
    if has_xgb:
        # Every arm scored on the SAME pairs: grid days where all arms produced a
        # probability. Compare XGB against other arms on this slice, never on "all".
        scored = pairs[[f"p_{a}" for a in active_arms]].notna().all(axis=1)
        slices["xgb-grid"] = (scored & pairs["date"].dt.date.isin(grid_day_set)).to_numpy()

    results: dict = {
        "model": "compare_all_models",
        "arms": active_arms,
        "window": [str(start.date()), str(end.date())],
        "coefficients": {
            **({"logit": coef_rows_logit} if "logit" in active_arms else {}),
            **({"logit_method": coef_rows_method} if "logit_method" in active_arms else {}),
        },
        "cost_control": {
            "time_per_d_seconds": round(per_d_time, 2),
            "xgb_grid_days": chosen_grid_days,
            "grid_threshold_seconds": 15.0,
            "grid_days_scored": len(grid_day_set) if has_xgb else 0,
        },
        "outcomes": {},
    }

    # Step 5: Served-log check. What served was the two-tier router's blend of the
    # ensemble and offset models (weight logged per row), BEFORE the serving isotonic
    # and floors, so reconstruct that blend and compare it with the logged
    # pre-calibration probability, not with the plain ensemble.
    needed = {"p_xgb_ensemble_raw", "p_xgb_offset_raw", "p_exceed_precal", "served_offset_weight"}
    if needed <= set(pairs.columns):
        fwd = pairs[(pairs["outcome"] == "forward_1_3d") & pairs["p_exceed_precal"].notna()]
        scored = fwd["p_xgb_ensemble_raw"].notna() & fwd["p_xgb_offset_raw"].notna()
        has_w = fwd["served_offset_weight"].notna()
        s_log = fwd[scored & has_w].copy()
        w = s_log["served_offset_weight"].to_numpy(dtype=float)
        s_log["p_router"] = (1 - w) * s_log["p_xgb_ensemble_raw"].to_numpy() + w * s_log["p_xgb_offset_raw"].to_numpy()
        check = {
            "n": int(len(s_log)),
            "excluded_null_weight": int((scored & ~has_w).sum()),
            "excluded_unscored": int((~scored).sum()),
            "bar": SERVED_LOG_AUROC_BAR,
        }
        if len(s_log):
            check["beaches"] = int(s_log["beach_id"].nunique())
            check["window"] = [str(s_log["date"].min().date()), str(s_log["date"].max().date())]
            check["mean_served_offset_weight"] = float(w.mean())
        if len(s_log) and s_log["y"].nunique() == 2:
            y_l = s_log["y"].to_numpy()
            p_r = s_log["p_router"].to_numpy()
            for ref in ("p_exceed_precal", "p_exceed_raw"):
                if ref not in s_log.columns or s_log[ref].isna().all():
                    continue
                ok = s_log[ref].notna().to_numpy()
                p_ref = s_log[ref].to_numpy()[ok]
                au_r, au_ref = float(roc_auc_score(y_l[ok], p_r[ok])), float(roc_auc_score(y_l[ok], p_ref))
                check[ref] = {
                    "n": int(ok.sum()),
                    "router_auroc": au_r,
                    "logged_auroc": au_ref,
                    "auroc_gap": abs(au_r - au_ref),
                    "pearson": float(np.corrcoef(p_r[ok], p_ref)[0, 1]),
                    "spearman": float(pd.Series(p_r[ok]).corr(pd.Series(p_ref), method="spearman")),
                    "passes_bar": bool(abs(au_r - au_ref) <= SERVED_LOG_AUROC_BAR),
                }
            check["passes_bar"] = bool(check.get("p_exceed_precal", {}).get("passes_bar", False))
        results["served_log_check"] = check

    for outcome in ("same_day", "forward_1_3d"):
        o = pairs[pairs["outcome"] == outcome]
        res = {}
        for name, mask in slices.items():
            m = mask[pairs["outcome"].to_numpy() == outcome]
            s = o[m]
            if s["y"].nunique() < 2:
                continue
            y, b = s["y"].to_numpy(), s["beach_id"].to_numpy()
            slice_res = {
                "n": int(len(s)),
                "beaches": int(s["beach_id"].nunique()),
                "base_rate": float(y.mean()),
            }
            for arm in active_arms:
                slice_res[arm] = metrics(y, s[f"p_{arm}"].to_numpy(), b)

            # Deltas vs logit (the served model) on slices "all" and "not San Diego"
            if name in ("all", "not San Diego") and args.bootstrap and "logit" in active_arms:
                slice_res["delta_ci95"] = {}
                for arm in active_arms:
                    slice_res["delta_ci95"][arm] = cluster_bootstrap_delta(
                        y, s[f"p_{arm}"].to_numpy(), s["p_logit"].to_numpy(), b, reps=args.bootstrap, seed=0
                    )
            res[name] = slice_res

        if "p_exceed_ml" in o.columns:
            s = o[o["p_exceed_ml"].notna()]
            if len(s) and s["y"].nunique() == 2:
                y, b = s["y"].to_numpy(), s["beach_id"].to_numpy()
                overlap_res = {
                    "n": int(len(s)),
                    "beaches": int(s["beach_id"].nunique()),
                    "base_rate": float(y.mean()),
                    "window": [str(s["date"].min().date()), str(s["date"].max().date())],
                }
                for arm in active_arms:
                    overlap_res[arm] = metrics(y, s[f"p_{arm}"].to_numpy(), b)
                overlap_res["served_ml"] = metrics(y, s["p_exceed_ml"].to_numpy(), b)
                res["served-log overlap"] = overlap_res
        results["outcomes"][outcome] = res

    # Calibration of the forward forecast, by predicted-probability bin
    o = pairs[pairs["outcome"] == "forward_1_3d"]
    bins = [0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]
    results["calibration_forward"] = {
        f"p_{arm}": [
            {
                "p_range": [lo, hi],
                "n": int(len(g)),
                "predicted_mean": float(g[f"p_{arm}"].mean()),
                "actual_rate": float(g["y"].mean()),
            }
            for (lo, hi), g in (
                ((bins[i], bins[i + 1]), o[(o[f"p_{arm}"] >= bins[i]) & (o[f"p_{arm}"] < bins[i + 1] + (i == len(bins) - 2))])
                for i in range(len(bins) - 1)
            )
            if len(g)
        ]
        for arm in active_arms
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(dumps_strict(results))

    keep = ["beach_id", "county", "date", "outcome", "y", "last_exceeds", "assay"]
    for arm in active_arms:
        keep.append(f"p_{arm}")
    if "p_exceed_ml" in pairs.columns:
        keep.append("p_exceed_ml")
    pairs[keep].to_parquet(args.out / "predictions.parquet", index=False)
    print(json.dumps(results, indent=1, default=str))


if __name__ == "__main__":
    main()
