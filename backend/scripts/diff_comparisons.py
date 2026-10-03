"""Diff two compare_all_models.py runs (before/after data snapshots) into a markdown report.

    python scripts/diff_comparisons.py --before DIR --after DIR --out docs/MODEL_COMPARISON_<day>.md

Reads ``predictions.parquet`` (forward_1_3d rows) from each run directory and reports, per arm
and slice, within-beach AUROC, AUROC, AUCPR, Brier and sensitivity at specificity 0.87 three
ways: common pairs (beach, date, outcome present in both), full (each run on its own) and new
beaches only (after pairs whose beach has no pair in before). Deltas carry a beach-cluster
bootstrap CI on common pairs. Then the realized exceedance rate per risk band, and a mechanical
application of ``app/ml/PROMOTION.md`` to the after/full pairs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score, roc_curve

OUTCOME = "forward_1_3d"
SERVED_ARM = "logit"
# PROMOTION.md rule 5, simplest first.
SIMPLICITY: tuple[str, ...] = (
    "pooled",
    "persistence",
    "lookup",
    "logit",
    "logit_method",
    "xgb_ensemble",
    "xgb_offset",
)
METRICS: tuple[str, ...] = ("within_beach_auroc", "auroc", "aucpr", "brier", "sens_at_spec_0.87")
SLICE_NAMES: tuple[str, ...] = ("all", "not San Diego", "culture", "ddpcr", "wet", "dry")
VERDICT_SLICES: tuple[str, str] = ("all", "not San Diego")
MIN_PROMOTION_REPS = 300  # PROMOTION.md rule 3
TARGET_SPECIFICITY = 0.87
WET_MONTHS = {11, 12, 1, 2, 3, 4}
# Served risk bands (calibration.py): Low < 0.20 <= Moderate < 0.30 <= High < 0.70 <= Very High.
BAND_EDGES = (0.20, 0.30, 0.70)
BAND_NAMES = ("Low", "Moderate", "High", "Very High")


# --------------------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------------------
def _beach_auroc_stats(y: np.ndarray, p: np.ndarray, beach: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-beach (weight n1*n0, AUROC), beaches with both outcomes only (others weight 0)."""
    groups = pd.Series(np.arange(len(y))).groupby(beach).indices
    weights = np.zeros(len(groups))
    aucs = np.zeros(len(groups))
    for i, idx in enumerate(groups.values()):
        yy = y[idx]
        n1 = int(yy.sum())
        n0 = len(yy) - n1
        if n1 and n0:
            weights[i] = n1 * n0
            aucs[i] = roc_auc_score(yy, p[idx])
    return weights, aucs


def within_beach_auroc(y: np.ndarray, p: np.ndarray, beach: np.ndarray) -> float:
    w, a = _beach_auroc_stats(y, p, beach)
    return float((w * a).sum() / w.sum()) if w.sum() else float("nan")


def sensitivity_at_specificity(y: np.ndarray, p: np.ndarray, target: float = TARGET_SPECIFICITY) -> float:
    """Best sensitivity among thresholds whose specificity >= target (ties count positive)."""
    fpr, tpr, _ = roc_curve(y, p, drop_intermediate=False)
    ok = fpr <= (1.0 - target) + 1e-12
    return float(tpr[ok].max()) if ok.any() else float("nan")


def metric_values(y: np.ndarray, p: np.ndarray, beach: np.ndarray) -> dict[str, float]:
    valid = ~np.isnan(p)
    y, p, beach = y[valid], p[valid], beach[valid]
    if len(y) == 0 or len(np.unique(y)) < 2:
        return {m: float("nan") for m in METRICS}
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return {
        "within_beach_auroc": within_beach_auroc(y, p, beach),
        "auroc": float(roc_auc_score(y, p)),
        "aucpr": float(average_precision_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "sens_at_spec_0.87": sensitivity_at_specificity(y, p),
    }


def bootstrap_delta(
    y: np.ndarray,
    p_new: np.ndarray,
    p_old: np.ndarray,
    beach: np.ndarray,
    reps: int,
    seed: int = 0,
    metrics: Sequence[str] = METRICS,
    y_old: np.ndarray | None = None,
) -> dict[str, list[float]]:
    """95% beach-cluster bootstrap CI of metric(p_new) - metric(p_old) on identical rows.

    ``y`` labels ``p_new``; ``y_old`` (default ``y``) labels ``p_old``. They differ on
    before/after common pairs when the data fix corrected a label: each side is scored
    against its own labels, while the resampled beaches are shared. Rows where either
    probability is NaN are dropped. Identical predictions and labels give exactly [0, 0].
    ``within_beach_auroc`` uses per-beach AUROCs computed once per side (a duplicated
    beach has the same AUROC, only a larger count), so each replicate is a weighted mean.
    """
    y_old = y if y_old is None else y_old
    nan_ci = {m: [float("nan"), float("nan")] for m in metrics}
    valid = ~np.isnan(p_new) & ~np.isnan(p_old)
    y, y_old, p_new, p_old, beach = y[valid], y_old[valid], p_new[valid], p_old[valid], beach[valid]
    if len(y) == 0 or len(np.unique(y)) < 2 or len(np.unique(y_old)) < 2 or reps <= 0:
        return nan_ci
    if np.array_equal(p_new, p_old) and np.array_equal(y, y_old):
        return {m: [0.0, 0.0] for m in metrics}
    p_new, p_old = np.clip(p_new, 1e-4, 1 - 1e-4), np.clip(p_old, 1e-4, 1 - 1e-4)

    rng = np.random.default_rng(seed)
    groups = list(pd.Series(np.arange(len(y))).groupby(beach).indices.values())
    n_g = len(groups)
    w_new, a_new = _beach_auroc_stats(y, p_new, beach)
    w_old, a_old = _beach_auroc_stats(y_old, p_old, beach)
    draws: dict[str, list[float]] = {m: [] for m in metrics}
    for _ in range(reps):
        pick = rng.choice(n_g, n_g, replace=True)
        counts = np.bincount(pick, minlength=n_g)
        idx = np.concatenate([groups[i] for i in pick])
        yy, yo = y[idx], y_old[idx]
        if yy.min() == yy.max() or yo.min() == yo.max():
            continue
        for m in metrics:
            if m == "within_beach_auroc":
                den_new, den_old = float((counts * w_new).sum()), float((counts * w_old).sum())
                if den_new == 0 or den_old == 0:
                    continue
                val = float((counts * w_new * a_new).sum() / den_new - (counts * w_old * a_old).sum() / den_old)
            elif m == "auroc":
                val = roc_auc_score(yy, p_new[idx]) - roc_auc_score(yo, p_old[idx])
            elif m == "aucpr":
                val = average_precision_score(yy, p_new[idx]) - average_precision_score(yo, p_old[idx])
            elif m == "brier":
                val = brier_score_loss(yy, p_new[idx]) - brier_score_loss(yo, p_old[idx])
            else:
                val = sensitivity_at_specificity(yy, p_new[idx]) - sensitivity_at_specificity(yo, p_old[idx])
            draws[m].append(float(val))
    return {
        m: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if v else [float("nan"), float("nan")]
        for m, v in draws.items()
    }


# --------------------------------------------------------------------------------------
# loading and splitting
# --------------------------------------------------------------------------------------
def load_run(run_dir: Path) -> tuple[pd.DataFrame, list[str], dict]:
    """Forward pairs, arm names (simplicity order) and the run's results.json header."""
    pairs = pd.read_parquet(run_dir / "predictions.parquet")
    pairs = pairs[pairs["outcome"] == OUTCOME].copy()
    pairs["date"] = pd.to_datetime(pairs["date"]).dt.normalize()
    arms = [a for a in SIMPLICITY if f"p_{a}" in pairs.columns]
    info: dict = {}
    rp = run_dir / "results.json"
    if rp.exists():
        raw = json.loads(rp.read_text())
        info = {k: raw.get(k) for k in ("window", "arms", "cost_control")}
    return pairs.reset_index(drop=True), arms, info


def slice_mask(pairs: pd.DataFrame, name: str) -> np.ndarray:
    if name == "all":
        return np.ones(len(pairs), bool)
    sd = pairs["county"].eq("San Diego").to_numpy()
    wet = pairs["date"].dt.month.isin(WET_MONTHS).to_numpy()
    if name == "not San Diego":
        return ~sd
    if name == "culture":
        return (pairs["assay"] == "culture").to_numpy()
    if name == "ddpcr":
        return (pairs["assay"] == "ddpcr").to_numpy()
    if name == "wet":
        return wet
    if name == "dry":
        return ~wet
    raise KeyError(name)


def split_pairs(before: pd.DataFrame, after: pd.DataFrame) -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
    """Return {way: (before_rows, after_rows)} for common / full / new beaches only.

    common: pairs keyed (beach_id, date, outcome) present in both, row-aligned.
    full: each run on its own pairs.
    new_beaches: after pairs whose beach has no pair in before (before side is empty).
    """
    key = ["beach_id", "date", "outcome"]
    b = before.drop_duplicates(key).set_index(key)
    a = after.drop_duplicates(key).set_index(key)
    common_idx = b.index.intersection(a.index)
    common_b = b.loc[common_idx].reset_index()
    common_a = a.loc[common_idx].reset_index()
    new_mask = ~after["beach_id"].isin(set(before["beach_id"]))
    return {
        "common": (common_b, common_a),
        "full": (before, after),
        "new_beaches": (before.iloc[0:0], after[new_mask].reset_index(drop=True)),
    }


# --------------------------------------------------------------------------------------
# promotion rule (app/ml/PROMOTION.md)
# --------------------------------------------------------------------------------------
DeltaFn = Callable[[str, str, str], Mapping[str, Sequence[float]]]


def passes_condition_3(deltas: Mapping[str, Mapping[str, Sequence[float]]]) -> tuple[bool, dict[str, bool]]:
    """Conditions 3+4: on every verdict slice, within-beach AUROC delta CI entirely above 0
    AND Brier delta CI entirely below 0. ``deltas[slice][metric] = [lo, hi]``."""
    per_slice: dict[str, bool] = {}
    for s in VERDICT_SLICES:
        d = deltas.get(s)
        ok = False
        if d is not None:
            wb, br = d["within_beach_auroc"], d["brier"]
            ok = bool(wb[0] > 0 and br[1] < 0)  # NaN compares False
        per_slice[s] = ok
    return all(per_slice.values()), per_slice


def promotion_verdict(arms: Sequence[str], delta_fn: DeltaFn, served: str = SERVED_ARM) -> dict:
    """Apply PROMOTION.md mechanically.

    ``delta_fn(arm, ref, slice)`` -> {"within_beach_auroc": [lo, hi], "brier": [lo, hi]}, the
    bootstrap CI of (arm - ref). Every non-served arm is a challenger. Rule 5: of the passers,
    the simplest is promoted unless a more complex passer also passes condition 3 against it.
    """
    out: dict = {"challengers": {}, "promoted": None}
    passers: list[str] = []
    for arm in arms:
        if arm == served:
            continue
        deltas = {s: delta_fn(arm, served, s) for s in VERDICT_SLICES}
        ok, per_slice = passes_condition_3(deltas)
        out["challengers"][arm] = {"verdict": "PASS" if ok else "FAIL", "slices": per_slice, "deltas": deltas}
        if ok:
            passers.append(arm)
    passers.sort(key=SIMPLICITY.index)
    if passers:
        current = passers[0]
        for nxt in passers[1:]:
            vs_current, _ = passes_condition_3({s: delta_fn(nxt, current, s) for s in VERDICT_SLICES})
            if vs_current:
                current = nxt
        out["promoted"] = current
    return out


# --------------------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------------------
def _f(v: float, signed: bool = False) -> str:
    if v is None or np.isnan(v):
        return "n/a"
    return f"{v:+.3f}" if signed else f"{v:.3f}"


def _ci(ci: Sequence[float] | None) -> str:
    return "" if ci is None else f" [{_f(ci[0], True)}, {_f(ci[1], True)}]"


def _arm_arrays(df: pd.DataFrame, mask: np.ndarray, arm: str):
    s = df[mask]
    return s["y"].to_numpy().astype(int), s[f"p_{arm}"].to_numpy(dtype=float), s["beach_id"].to_numpy()


def _metric_table(
    arms: Sequence[str], mask_name: str, way: str, b_df: pd.DataFrame, a_df: pd.DataFrame, reps: int
) -> list[str]:
    am = slice_mask(a_df, mask_name)
    # Common pairs are row-aligned: one mask for both sides, taken from the after run, so a
    # slice whose membership the data fix changed (assay, county) still pairs the same rows.
    bm = am if way == "common" else slice_mask(b_df, mask_name)
    lines = [
        "| arm | n before / after | " + " | ".join(METRICS) + " |",
        "|---|---|" + "---|" * len(METRICS),
    ]
    for arm in arms:
        yb, pb, bb = _arm_arrays(b_df, bm, arm)
        ya, pa, ba = _arm_arrays(a_df, am, arm)
        mb = metric_values(yb, pb, bb) if len(yb) else {m: float("nan") for m in METRICS}
        ma = metric_values(ya, pa, ba)
        ci = None
        if way == "common" and len(yb):
            ci = bootstrap_delta(ya, pa, pb, ba, reps=reps, seed=0, y_old=yb)
        cells = []
        for m in METRICS:
            if way == "new_beaches":
                cells.append(_f(ma[m]))
            else:
                cells.append(f"{_f(mb[m])} → {_f(ma[m])} (Δ {_f(ma[m] - mb[m], True)}{_ci(ci[m] if ci else None)})")
        n_b = int((~np.isnan(pb)).sum())
        n_a = int((~np.isnan(pa)).sum())
        lines.append(f"| {arm} | {n_b} / {n_a} | " + " | ".join(cells) + " |")
    return lines


def band_rates(df: pd.DataFrame, arm: str) -> list[tuple[str, int, float]]:
    p = df[f"p_{arm}"].to_numpy(dtype=float)
    y = df["y"].to_numpy()
    valid = ~np.isnan(p)
    band = np.digitize(p[valid], BAND_EDGES)
    out = []
    for i, name in enumerate(BAND_NAMES):
        sel = band == i
        out.append((name, int(sel.sum()), float(y[valid][sel].mean()) if sel.any() else float("nan")))
    return out


def _band_table(arms: Sequence[str], df: pd.DataFrame) -> list[str]:
    lines = ["| arm | " + " | ".join(BAND_NAMES) + " |", "|---|" + "---|" * len(BAND_NAMES)]
    for arm in arms:
        cells = [f"{_f(r)} (n={n})" for _, n, r in band_rates(df, arm)]
        lines.append(f"| {arm} | " + " | ".join(cells) + " |")
    return lines


def _make_delta_fn(df: pd.DataFrame, reps: int) -> DeltaFn:
    cache: dict[tuple[str, str, str], dict] = {}

    def fn(arm: str, ref: str, slice_name: str):
        k = (arm, ref, slice_name)
        if k not in cache:
            s = df[slice_mask(df, slice_name)]
            cache[k] = bootstrap_delta(
                s["y"].to_numpy().astype(int),
                s[f"p_{arm}"].to_numpy(dtype=float),
                s[f"p_{ref}"].to_numpy(dtype=float),
                s["beach_id"].to_numpy(),
                reps=reps,
                seed=0,
                metrics=("within_beach_auroc", "brier"),
            )
        return cache[k]

    return fn


def _verdict_lines(title: str, verdict: dict, reps: int) -> list[str]:
    lines = [f"**{title}**", ""]
    if reps < MIN_PROMOTION_REPS:
        lines += [
            f"> INDICATIVE ONLY: {reps} bootstrap replicates < {MIN_PROMOTION_REPS} required by PROMOTION.md rule 3.",
            "",
        ]
    lines += [
        "| challenger | verdict | slice | within-beach AUROC Δ vs logit | Brier Δ vs logit | slice passes |",
        "|---|---|---|---|---|---|",
    ]
    for arm, v in verdict["challengers"].items():
        for i, s in enumerate(VERDICT_SLICES):
            d = v["deltas"][s]
            lines.append(
                f"| {arm if i == 0 else ''} | {v['verdict'] if i == 0 else ''} | {s} | "
                f"{_ci(d['within_beach_auroc']).strip()} | {_ci(d['brier']).strip()} | {'yes' if v['slices'][s] else 'no'} |"
            )
    lines += ["", f"Promoted under rule 5: **{verdict['promoted'] or 'none (served estimate unchanged)'}**", ""]
    return lines


def build_report(before: Path, after: Path, reps: int) -> tuple[str, dict]:
    b_df, b_arms, b_info = load_run(before)
    a_df, a_arms, a_info = load_run(after)
    arms = [a for a in a_arms if a in b_arms]
    ways = split_pairs(b_df, a_df)
    common_b, common_a = ways["common"]

    lines = [
        "# Model comparison: before vs after data snapshot",
        "",
        f"- before: `{before}` window {b_info.get('window')}, {len(b_df)} forward pairs, {b_df['beach_id'].nunique()} beaches",
        f"- after: `{after}` window {a_info.get('window')}, {len(a_df)} forward pairs, {a_df['beach_id'].nunique()} beaches",
        f"- common pairs: {len(common_a)}; new-beach pairs (after only): {len(ways['new_beaches'][1])} "
        f"across {ways['new_beaches'][1]['beach_id'].nunique()} beaches",
        f"- bootstrap: {reps} beach-cluster replicates, seed 0 (Δ = after − before; CI on common pairs only)",
        "- sensitivity is the best sensitivity at specificity ≥ 0.87; decision rule: `backend/app/ml/PROMOTION.md`",
        "- the new-beaches slice is the **new beaches only** way below (before side is empty by definition)",
        "",
    ]
    titles = {
        "common": "Common pairs (beach, date, outcome in both runs)",
        "full": "Full pairs (each run on its own)",
        "new_beaches": "New beaches only (after pairs whose beach has no pair in before)",
    }
    for way, (bd, ad) in ways.items():
        lines += [f"## {titles[way]}", ""]
        if ad.empty:
            lines += ["_no pairs_", ""]
            continue
        for sname in SLICE_NAMES:
            if not slice_mask(ad, sname).any():
                continue
            lines += [f"### {way}: {sname}", ""]
            lines += _metric_table(arms, sname, way, bd, ad, reps)
            lines.append("")

    lines += ["## Realized exceedance rate per served risk band", ""]
    for title, df in (("before (full)", b_df), ("after (full)", a_df)):
        lines += [f"**{title}** — Low < 0.20 ≤ Moderate < 0.30 ≤ High < 0.70 ≤ Very High", ""]
        lines += _band_table(arms, df) + [""]

    lines += ["## PROMOTION.md verdict", ""]
    full_verdict = promotion_verdict(arms, _make_delta_fn(a_df, reps))
    lines += _verdict_lines("After snapshot, full pairs (decides)", full_verdict, reps)
    common_verdict = promotion_verdict(arms, _make_delta_fn(common_a, reps))
    lines += _verdict_lines("After snapshot, common pairs (must not reverse the decision)", common_verdict, reps)
    reversed_ = {
        arm: (full_verdict["challengers"][arm]["verdict"], common_verdict["challengers"][arm]["verdict"])
        for arm in full_verdict["challengers"]
        if full_verdict["challengers"][arm]["verdict"] != common_verdict["challengers"][arm]["verdict"]
    }
    if reversed_ or full_verdict["promoted"] != common_verdict["promoted"]:
        lines.append(
            "**WARNING: the decision differs on common pairs** "
            + ", ".join(f"{a}: full {f} / common {c}" for a, (f, c) in reversed_.items())
            + f"; promoted full={full_verdict['promoted']} common={common_verdict['promoted']}"
        )
    else:
        lines.append("Decision is the same on full and common pairs.")
    lines.append("")
    return "\n".join(lines), {"full": full_verdict, "common": common_verdict}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--before", type=Path, required=True)
    ap.add_argument("--after", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--bootstrap", type=int, default=300)
    args = ap.parse_args()

    report, verdicts = build_report(args.before, args.after, args.bootstrap)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    for arm, v in verdicts["full"]["challengers"].items():
        print(f"{arm}: {v['verdict']}  {json.dumps(v['deltas'], default=str)}")
    print(f"promoted: {verdicts['full']['promoted']}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
