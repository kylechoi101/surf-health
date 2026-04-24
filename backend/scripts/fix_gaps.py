import sys
import asyncio
import pandas as pd
import numpy as np
from pathlib import Path

# Add backend to sys.path so we can import
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.data.pipeline.external_covariates import enrich_beach_day_with_external_covariates

curated_dir = Path("/Users/kylechoi/surf_health/data/curated")

print("Loading curated data...")
beaches = pd.read_parquet(curated_dir / "beaches.parquet")
beach_day = pd.read_parquet(curated_dir / "beach_day.parquet")

# 1. Fill NA for streamflow
print("Filling streamflow gaps...")
for col in ["streamflow_cfs_latest", "streamflow_cfs_mean_24h", "streamflow_cfs_max_24h", "streamflow_rising_flag"]:
    if col in beach_day.columns:
        beach_day[col] = beach_day[col].fillna(0.0)

# 2. Add tidal harmonic proxy
print("Generating harmonic tide proxy...")
days_since_epoch = (pd.to_datetime(beach_day["sample_date"]) - pd.Timestamp("2000-01-06")).dt.days
phase = (days_since_epoch % 29.530588) / 29.530588
beach_day["tidal_height"] = np.cos(phase * 2 * np.pi) * 1.5

# 3. Enrich external covariates (water temp) again since we increased max_distance_km
# But wait! The beach_day dataframe already has water_temperature_c from the *old* logic.
# If we re-merge, it might duplicate columns.
# We should drop the old external covariate columns first!
drop_cols = [
    "cdip_station_id", "cdip_distance_km", "wave_height_m", "dominant_period_s",
    "wave_direction_deg", "erddap_source_name", "erddap_distance_km",
    "salinity_psu", "water_temperature_c"
]
existing_drops = [c for c in drop_cols if c in beach_day.columns]
if existing_drops:
    beach_day = beach_day.drop(columns=existing_drops)

print("Re-fetching and merging external covariates with 400km radius...")
_, updated_beach_day, _ = asyncio.run(enrich_beach_day_with_external_covariates(beaches, beach_day))

# Check coverage:
print("--- Coverage Check ---")
total = len(updated_beach_day)
for c in ["tidal_height", "water_temperature_c", "streamflow_cfs_latest"]:
    valid = updated_beach_day[c].notna().sum() if c in updated_beach_day.columns else 0
    print(f"{c}: {valid/total*100:.1f}%")

print("Saving updated beach_day.parquet...")
updated_beach_day.to_parquet(curated_dir / "beach_day.parquet", index=False)
print("Done.")
