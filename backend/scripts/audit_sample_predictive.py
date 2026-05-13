"""Quick retrospective sanity check: how well do today's model predictions
align with each beach's recent sample base rate?

This is NOT a proper temporal-validation audit (which needs predictions per
past forecast date). It's a sanity check: if the model says High right now,
that beach should have been exceeding lately. If it says Low, mostly clean.
"""
import pandas as pd

fc = pd.read_parquet("/Users/kylechoi/surf_health/data/curated/forecasts.parquet")
bd = pd.read_parquet("/Users/kylechoi/surf_health/data/curated/beach_day.parquet")
bd["sample_date"] = pd.to_datetime(bd["sample_date"])

THRESHOLD = 0.3
LOOKBACK_DAYS = 30
cutoff = bd["sample_date"].max() - pd.Timedelta(days=LOOKBACK_DAYS)
recent = bd[bd["sample_date"] >= cutoff].copy()

base = recent.groupby("beach_id").agg(
    n_samples=("exceeds_stv", "count"),
    exceed_rate=("exceeds_stv", "mean"),
).reset_index()

joined = fc[["beach_id", "p_exceed", "risk_band", "model_version"]].merge(
    base, on="beach_id", how="inner"
)
joined = joined[joined["n_samples"] >= 2]

joined["model_pred_high"] = joined["p_exceed"] >= THRESHOLD
joined["observed_exceeded"] = joined["exceed_rate"] >= 0.25  # ≥1 in 4 recent

tp = ((joined["model_pred_high"]) & (joined["observed_exceeded"])).sum()
tn = ((~joined["model_pred_high"]) & (~joined["observed_exceeded"])).sum()
fp = ((joined["model_pred_high"]) & (~joined["observed_exceeded"])).sum()
fn = ((~joined["model_pred_high"]) & (joined["observed_exceeded"])).sum()

n = len(joined)
print(f"=== sample-based predictive sanity check ===")
print(f"   model NOW vs samples last {LOOKBACK_DAYS}d")
print(f"   threshold p_exceed ≥ {THRESHOLD}; observed if recent exceed_rate ≥ 0.25")
print(f"   beaches with ≥2 recent samples: {n}")
print()
print(f"                  observed_exceeded")
print(f"                   Yes      No")
print(f"   model says High  {tp:4d}    {fp:4d}")
print(f"   model says Low   {fn:4d}    {tn:4d}")
print()
prec = tp / max(tp + fp, 1)
recall = tp / max(tp + fn, 1)
spec = tn / max(tn + fp, 1)
f1 = 2 * prec * recall / max(prec + recall, 1e-6)
print(f"   precision        {prec:.3f}    (of model-High, observed High)")
print(f"   recall           {recall:.3f}    (of observed-High, model High)")
print(f"   specificity      {spec:.3f}    (of observed-Low, model Low)")
print(f"   F1               {f1:.3f}")
print()
p_corr = joined["p_exceed"].corr(joined["exceed_rate"])
s_corr = joined["p_exceed"].corr(joined["exceed_rate"], method="spearman")
print(f"   p_exceed vs exceed_rate correlation:")
print(f"     pearson  {p_corr:.3f}")
print(f"     spearman {s_corr:.3f}")
