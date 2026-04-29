import pandas as pd
import os

path = 'data/curated/beach_day.parquet'
if not os.path.exists(path):
    print(f"File {path} not found")
else:
    df = pd.read_parquet(path)
    cols = [
        'shore_normal_wind_ms',
        'solar_inactivation_index',
        'is_near_pier',
        'is_near_estuary_mouth',
        'days_since_sunny'
    ]
    for c in cols:
        if c in df.columns:
            pct = df[c].notna().mean() * 100
            print(f"{c}: {pct:.1f}%")
        else:
            print(f"{c}: MISSING")
