#!/usr/bin/env bash
# Daily forecast refresh. Run from backend/:
#   bash scripts/daily_forecast.sh [YYYY-MM-DD]
#
# Uses cached curated data + hydrology — no re-download.
# Fetches fresh USGS/Open-Meteo data for the last 7 days, then re-trains
# and bakes today's forecasts into forecasts.parquet.

set -euo pipefail

FORECAST_DATE="${1:-$(date +%Y-%m-%d)}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"

cd "$BACKEND_DIR"

echo "[daily_forecast] forecast_date=$FORECAST_DATE"

# Re-run the full curated pipeline with a 7-day hydrology window ending today
# (skips re-downloading BeachWatch CSVs — uses existing curated parquets as base)
.venv/bin/python -m app.data.pipeline.cli \
    --normalize-beachwatch \
    --stations-csv /tmp/beach-monitoring-stations.csv \
    --results-csv /tmp/beach-monitoring-results.csv \
    --advisories-csv /tmp/beach-monitoring-advisories.csv \
    --merge-ceden \
    --with-external-covariates \
    --with-hydrology \
    --start-date "$(date -v-7d +%Y-%m-%d 2>/dev/null || date -d '7 days ago' +%Y-%m-%d)" \
    --end-date "$FORECAST_DATE"

echo "[daily_forecast] pipeline done — retraining"

.venv/bin/python -m app.ml.training \
    --curated \
    --forecast-date "$FORECAST_DATE"

echo "[daily_forecast] done — forecasts.parquet updated for $FORECAST_DATE"
