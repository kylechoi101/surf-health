#!/usr/bin/env python3
"""County spatial holdout: leave-one-county-out AUCPR for HistGBM vs persistence.

Run from backend/:
    python scripts/county_holdout.py
"""
import sys
sys.path.insert(0, ".")

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score

CURATED = "/Users/kylechoi/surf_health/data/curated"

FEATURES = [
    "wave_height_m", "dominant_period_s", "wave_direction_deg",
    "water_temperature_c", "salinity_psu", "uv_index", "wind_speed_mps",
    "tidal_height", "historical_advisory_count",
    "streamflow_cfs_latest", "streamflow_cfs_mean_24h", "streamflow_cfs_max_24h",
    "streamflow_rising_flag", "precip_mm_6h", "precip_mm_24h", "precip_mm_48h",
    "precip_mm_72h", "precip_mm_7d", "precip_awi", "first_flush_flag",
    "distance_to_pour_point_km", "distance_to_gage_km",
]
TARGET = "exceeds_stv"

bd = pd.read_parquet(f"{CURATED}/beach_day.parquet")
bd = bd.dropna(subset=[TARGET, "county"])
feat_cols = [f for f in FEATURES if f in bd.columns]

counties = bd["county"].value_counts()
eval_counties = counties[counties >= 50].index.tolist()
print(f"Evaluating {len(eval_counties)} counties ({counties[eval_counties].sum()} rows)")

results = []
for county in eval_counties:
    test_mask = bd["county"] == county
    train_mask = ~test_mask

    X_train = bd.loc[train_mask, feat_cols]
    y_train = bd.loc[train_mask, TARGET].astype(int)
    X_test  = bd.loc[test_mask,  feat_cols]
    y_test  = bd.loc[test_mask,  TARGET].astype(int)

    if y_test.sum() < 5:
        continue

    beach_rates = bd.loc[train_mask].groupby("beach_id")[TARGET].mean()
    persistence_scores = bd.loc[test_mask, "beach_id"].map(beach_rates).fillna(y_train.mean())
    persistence_aucpr = average_precision_score(y_test, persistence_scores)

    model = HistGradientBoostingClassifier(max_iter=200, random_state=42)
    model.fit(X_train, y_train)
    model_scores = model.predict_proba(X_test)[:, 1]
    model_aucpr = average_precision_score(y_test, model_scores)

    results.append({
        "county": county,
        "test_rows": int(test_mask.sum()),
        "positive_rate": float(y_test.mean()),
        "persistence_aucpr": round(persistence_aucpr, 4),
        "hist_gbm_aucpr": round(model_aucpr, 4),
        "delta": round(model_aucpr - persistence_aucpr, 4),
    })
    print(f"  {county:<30} hist_gbm={model_aucpr:.4f}  persistence={persistence_aucpr:.4f}  Δ={model_aucpr-persistence_aucpr:+.4f}")

df = pd.DataFrame(results).sort_values("delta")
print()
print("=== Summary ===")
print(f"Counties above persistence : {(df['delta'] > 0).sum()} / {len(df)}")
print(f"Mean hist_gbm AUCPR        : {df['hist_gbm_aucpr'].mean():.4f}")
print(f"Mean persistence AUCPR     : {df['persistence_aucpr'].mean():.4f}")
print(f"Mean delta                 : {df['delta'].mean():+.4f}")
print()
print(df.to_string(index=False))
