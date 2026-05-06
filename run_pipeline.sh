#!/bin/bash
set -ex

cd /Users/kylechoi/surf_health/backend

echo "Downloading BeachWatch CSVs..."
curl -fsSL -o /tmp/bw_stations.csv 'https://data.ca.gov/dataset/b9c8ce91-40ff-4ad3-8164-bc17c46afb44/resource/98e628ff-d012-4982-ad32-b9f9ad8ab524/download/beach-monitoring-stations.csv'
curl -fsSL -o /tmp/bw_results.csv 'https://data.ca.gov/dataset/b9c8ce91-40ff-4ad3-8164-bc17c46afb44/resource/7bd961cf-abe4-433b-8033-378161237ff3/download/beach-monitoring-results.csv'
curl -fsSL -o /tmp/bw_advisories.csv 'https://data.ca.gov/dataset/b9c8ce91-40ff-4ad3-8164-bc17c46afb44/resource/d5cd6a23-829c-426d-a63e-689a55a3db9c/download/beach-advisories.csv'

echo "Running data pipeline..."
python3 -m app.data.pipeline.cli \
  --normalize-beachwatch \
  --stations-csv /tmp/bw_stations.csv \
  --results-csv /tmp/bw_results.csv \
  --advisories-csv /tmp/bw_advisories.csv \
  --merge-ceden \
  --max-ceden-rows 50000 \
  --force-ceden-fetch \
  --with-external-covariates \
  --with-hydrology \
  --with-solar-wind

echo "Running stormwater extraction..."
python3 -m app.data.pipeline.stormwater \
  --curated-dir ../data/curated \
  --raw-dir ../data/raw/stormwater \
  --download \
  --ceden-results-csv ../data/raw/safetoswim_geomeans_2020-present.csv

echo "Running FULL ML training (no --winner-only)..."
FORECAST_DATE=$(TZ=America/Los_Angeles date +%Y-%m-%d)
python3 -m app.ml.training \
  --curated \
  --forecast-date "$FORECAST_DATE" \
  --spatial-backtests \
  --spatial-strategy requested \
  --spatial-beach-limit 50 \
  --spatial-county-limit 12 \
  --training-window-days 365

echo "Auditing forecasts and building API snapshot..."
python3 scripts/audit_forecasts_vs_advisories.py --curated ../data/curated/
python3 -m app.data.pipeline.serving_snapshot --curated ../data/curated/

echo "Baking static data for legacy UI..."
cd /Users/kylechoi/surf_health
python3 scripts/bake_static_data.py

echo "Committing..."
rtk git add data/curated/ web/public/data/
rtk git commit -m "chore: manual pipeline run and model re-evaluation" || echo "No changes to commit"

echo "DONE! Pipeline complete."
