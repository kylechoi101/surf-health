"""Per-county and per-beach effectiveness of the Shorelife exceedance model.

Two evaluation regimes, kept strictly separate because they answer different
questions and are NOT comparable to each other:

  BACKTEST  — leave-one-group-out spatial holdouts (holdout_predictions_spatial).
              Scored on sample-days only (fresh lagged features). This is the
              "can it generalise to a place it never trained on" number.

  SERVED    — forecast_history.parquet (what the product actually published)
              joined to observations.parquet (what the lab later found).
              This is the deployment-truth number.

Writes a single JSON blob consumed by the visualization.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)

CURATED = Path("data/curated")
OUT = Path("data/curated/model_effectiveness_by_geography.json")

FORWARD_MATCH_DAYS = 3
# Router went live 2026-07-22 (commit 00612cae); served_offset_weight only
# started being persisted later, so we split the served window on the date.
ROUTER_LIVE_DATE = pd.Timestamp("2026-07-22")


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def sensitivity_at_spec(labels: np.ndarray, probs: np.ndarray, target: float = 0.87):
    """Same operating-point rule as app/ml/evaluation.sensitivity_at_specificity."""
    labels = np.asarray(labels).astype(int)
    probs = np.asarray(probs, dtype=float)
    pos, neg = labels == 1, labels == 0
    n_pos, n_neg = int(pos.sum()), int(neg.sum())
    if n_pos == 0 or n_neg == 0:
        return None
    best_sens, best_spec = 0.0, -1.0
    for t in np.concatenate([np.unique(probs), [np.inf]]):
        pred = probs >= t
        fp = int(np.sum(pred & neg))
        spec = (n_neg - fp) / n_neg
        sens = int(np.sum(pred & pos)) / n_pos
        if spec >= target and sens >= best_sens:
            best_sens, best_spec = sens, spec
    return None if best_spec < 0 else round(float(best_sens), 4)


def score(labels, probs, *, min_rows=25):
    """Full metric bundle for one group. Returns None when not scoreable."""
    labels = np.asarray(labels).astype(int)
    probs = np.asarray(probs, dtype=float)
    ok = np.isfinite(probs)
    labels, probs = labels[ok], probs[ok]
    n = len(labels)
    if n < min_rows or labels.sum() == 0 or labels.sum() == n:
        return None
    base = float(labels.mean())
    return {
        "n": int(n),
        "n_pos": int(labels.sum()),
        "base_rate": round(base, 4),
        # AUROC — the population-invariant ranking metric. Comparable ACROSS
        # groups with different base rates. This is the headline.
        "auroc": round(float(roc_auc_score(labels, probs)), 4),
        # AUCPR — base-rate dependent. Only meaningful next to `lift`.
        "aucpr": round(float(average_precision_score(labels, probs)), 4),
        # AUCPR divided by the no-skill floor (= base rate). 1.0 = no skill.
        "aucpr_lift": round(float(average_precision_score(labels, probs)) / base, 3),
        "brier": round(float(brier_score_loss(labels, probs)), 4),
        "brier_flat": round(float(np.mean((base - labels) ** 2)), 4),
        # Beats a constant "always predict the base rate" forecast?
        "beats_flat": bool(brier_score_loss(labels, probs) < np.mean((base - labels) ** 2)),
        "mean_pred": round(float(probs.mean()), 4),
        # Positive => model over-predicts risk; negative => it under-warns.
        "bias": round(float(probs.mean() - base), 4),
        "sens_at_spec_87": sensitivity_at_spec(labels, probs),
    }


# ---------------------------------------------------------------------------
# 1. BACKTEST regime — leave-one-out spatial holdouts
# ---------------------------------------------------------------------------

def backtest_blocks() -> dict:
    sp = pd.read_parquet(CURATED / "holdout_predictions_spatial.parquet")
    out: dict = {}
    for kind, key in (("county", "by_county"), ("beach_id", "by_beach")):
        block: dict = {}
        sub = sp[sp.holdout_kind == kind]
        for model, mg in sub.groupby("model", observed=True):
            rows = []
            for group, g in mg.groupby("group", observed=True):
                s = score(g.label, g.probability, min_rows=25)
                if s:
                    rows.append({"group": str(group), **s})
            pooled = score(mg.label, mg.probability, min_rows=25)
            block[str(model)] = {"pooled": pooled, "groups": rows}
        out[key] = block
    return out


# ---------------------------------------------------------------------------
# 2. SERVED regime — published forecast vs the lab result that followed
# ---------------------------------------------------------------------------

def served_matched() -> pd.DataFrame:
    history = pd.read_parquet(CURATED / "forecast_history.parquet")
    obs = pd.read_parquet(
        CURATED / "observations.parquet", columns=["beach_id", "sample_date", "exceeds_stv"]
    )
    beaches = pd.read_parquet(CURATED / "beaches.parquet", columns=["beach_id", "name", "county"])

    # Worst lab outcome per beach-day (mirrors served_metrics.daily_outcomes).
    o = obs[obs.exceeds_stv.notna()].copy()
    o["date"] = pd.to_datetime(o.sample_date, errors="coerce").dt.normalize()
    o = o.dropna(subset=["date"])
    outcomes = o.groupby(["beach_id", "date"], as_index=False).exceeds_stv.max()
    outcomes["exceeded"] = outcomes.exceeds_stv.astype(bool).astype(int)
    outcomes = outcomes[["beach_id", "date", "exceeded"]]

    # Last-issued forecast per beach-day == what a user actually saw.
    f = history.copy()
    f["date"] = pd.to_datetime(f.forecast_date, errors="coerce").dt.normalize()
    f = f.dropna(subset=["date"])
    f["_issued"] = f.forecast_generated_at.astype(str)
    f = (
        f.sort_values(["beach_id", "date", "_issued"])
        .drop_duplicates(subset=["beach_id", "date"], keep="last")
        .drop(columns="_issued")
    )

    m = f.merge(
        outcomes.rename(columns={"exceeded": "outcome_same_day"}),
        on=["beach_id", "date"], how="left",
    )
    m["outcome_forward"] = np.nan
    for off in range(1, FORWARD_MATCH_DAYS + 1):
        sh = outcomes.copy()
        sh["date"] = sh["date"] - pd.Timedelta(days=off)
        m = m.merge(sh.rename(columns={"exceeded": f"_f{off}"}), on=["beach_id", "date"], how="left")
        m["outcome_forward"] = m.outcome_forward.fillna(m[f"_f{off}"])
        m = m.drop(columns=f"_f{off}")
    m["outcome_matched"] = m.outcome_same_day.fillna(m.outcome_forward)
    return m.merge(beaches, on="beach_id", how="left")


def served_blocks(m: pd.DataFrame) -> dict:
    scored = m.dropna(subset=["outcome_matched", "p_exceed"]).copy()
    scored["y"] = scored.outcome_matched.astype(int)

    def group_rows(frame, by, name_map=None, min_rows=25):
        rows = []
        for group, g in frame.groupby(by, observed=True):
            if pd.isna(group):
                continue
            s = score(g.y, g.p_exceed, min_rows=min_rows)
            if s:
                entry = {"group": str(group), **s}
                if name_map is not None:
                    entry["name"] = name_map.get(group, str(group))
                    entry["county"] = g["county"].dropna().iloc[0] if g.county.notna().any() else None
                rows.append(entry)
        return rows

    names = dict(zip(scored.beach_id, scored["name"].astype(str)))

    post = scored[scored.date >= ROUTER_LIVE_DATE]
    pre = scored[scored.date < ROUTER_LIVE_DATE]

    return {
        "window": {
            "start": str(scored.date.min().date()),
            "end": str(scored.date.max().date()),
            "router_live": str(ROUTER_LIVE_DATE.date()),
            "published_rows": int(len(m)),
            "scoreable_rows": int(len(scored)),
            "verifiable_fraction": round(float(len(scored) / len(m)), 4),
            "beaches_published": int(m.beach_id.nunique()),
            "beaches_scoreable": int(scored.beach_id.nunique()),
        },
        "pooled": score(scored.y, scored.p_exceed),
        "pooled_pre_router": score(pre.y, pre.p_exceed) if len(pre) else None,
        "pooled_post_router": score(post.y, post.p_exceed) if len(post) else None,
        "by_county": group_rows(scored, "county", min_rows=30),
        "by_county_post_router": group_rows(post, "county", min_rows=20),
        "by_beach": group_rows(scored, "beach_id", name_map=names, min_rows=25),
    }


# ---------------------------------------------------------------------------
# 3. Within-beach daily skill — the metric global AUCPR is blind to
# ---------------------------------------------------------------------------

def within_beach(m: pd.DataFrame, min_samples: int = 20) -> dict:
    s = m.dropna(subset=["outcome_matched", "p_exceed"]).copy()
    s["y"] = s.outcome_matched.astype(int)
    scores, weights, per_county = [], [], {}
    for bid, g in s.groupby("beach_id", observed=True):
        if len(g) < min_samples or g.y.nunique() < 2:
            continue
        a = roc_auc_score(g.y, g.p_exceed)
        scores.append(a)
        weights.append(len(g))
        c = g.county.dropna().iloc[0] if g.county.notna().any() else "Unknown"
        per_county.setdefault(c, []).append((a, len(g)))
    overall = (
        round(float(np.average(scores, weights=weights)), 4) if scores else None
    )
    county_rows = []
    for c, vals in per_county.items():
        a = np.array([v[0] for v in vals])
        w = np.array([v[1] for v in vals], dtype=float)
        county_rows.append(
            {
                "group": c,
                "within_beach_auroc": round(float(np.average(a, weights=w)), 4),
                "n_beaches": len(vals),
                "n_rows": int(w.sum()),
            }
        )
    return {
        "overall": overall,
        "n_beaches": len(scores),
        "n_rows": int(sum(weights)),
        "by_county": sorted(county_rows, key=lambda r: -r["n_rows"]),
    }


# ---------------------------------------------------------------------------
# 4. Reliability curve (served)
# ---------------------------------------------------------------------------

def reliability(m: pd.DataFrame) -> list[dict]:
    s = m.dropna(subset=["outcome_matched", "p_exceed"])
    edges = [0.0, 0.02, 0.05, 0.10, 0.20, 0.30, 0.50, 0.70, 1.0001]
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (s.p_exceed >= lo) & (s.p_exceed < hi)
        if mask.sum() < 10:
            continue
        out.append(
            {
                "lo": lo,
                "hi": min(hi, 1.0),
                "n": int(mask.sum()),
                "predicted": round(float(s.p_exceed[mask].mean()), 4),
                "actual": round(float(s.outcome_matched[mask].mean()), 4),
            }
        )
    return out


# ---------------------------------------------------------------------------
# 5. Skill vs staleness — the central train/serve gap
# ---------------------------------------------------------------------------

def by_sample_age(m: pd.DataFrame) -> list[dict]:
    s = m.dropna(subset=["outcome_matched", "p_exceed", "sample_age_days"]).copy()
    s["y"] = s.outcome_matched.astype(int)
    bins = [(0, 1), (2, 3), (4, 7), (8, 14), (15, 30), (31, 400)]
    out = []
    for lo, hi in bins:
        g = s[(s.sample_age_days >= lo) & (s.sample_age_days <= hi)]
        sc = score(g.y, g.p_exceed, min_rows=30)
        if sc:
            out.append({"bin": f"{lo}-{hi}d" if hi < 400 else f"{lo}d+", **sc})
    return out


def main() -> None:
    m = served_matched()
    payload = {
        "backtest": backtest_blocks(),
        "served": served_blocks(m),
        "within_beach_served": within_beach(m),
        "reliability_served": reliability(m),
        "by_sample_age": by_sample_age(m),
    }
    with open(CURATED / "system_health.json") as fh:
        payload["system_health"] = json.load(fh)
    OUT.write_text(json.dumps(payload, indent=1, default=str))
    print(f"wrote {OUT} ({OUT.stat().st_size/1024:.0f} KB)")

    # Console summary
    print("\n=== SERVED (deployment truth) ===")
    print(json.dumps(payload["served"]["window"], indent=1))
    print("pooled:", json.dumps(payload["served"]["pooled"]))
    print("pre-router :", json.dumps(payload["served"]["pooled_pre_router"]))
    print("post-router:", json.dumps(payload["served"]["pooled_post_router"]))
    print("\n--- served by county ---")
    print(pd.DataFrame(payload["served"]["by_county"]).to_string(index=False))
    print("\n--- within-beach daily skill (served) ---")
    print("overall:", payload["within_beach_served"]["overall"],
          "over", payload["within_beach_served"]["n_beaches"], "beaches")
    print(pd.DataFrame(payload["within_beach_served"]["by_county"]).to_string(index=False))
    print("\n--- skill vs sample age ---")
    print(pd.DataFrame(payload["by_sample_age"]).to_string(index=False))
    print("\n=== BACKTEST: county holdout, winner ===")
    print(pd.DataFrame(
        payload["backtest"]["by_county"]["xgb_undersample_ensemble"]["groups"]
    ).to_string(index=False))
    print("\n=== BACKTEST: beach holdout, winner ===")
    print(pd.DataFrame(
        payload["backtest"]["by_beach"]["xgb_undersample_ensemble"]["groups"]
    ).to_string(index=False))
    print("\n--- served by beach (top 25 by n) ---")
    bb = pd.DataFrame(payload["served"]["by_beach"]).sort_values("n", ascending=False)
    print(bb.head(25).to_string(index=False))
    print(f"\n({len(bb)} beaches scoreable)")


if __name__ == "__main__":
    main()
