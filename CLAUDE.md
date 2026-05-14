# Surf Health / Shorelife — Claude Code context

## Repo layout

```
backend/           Python FastAPI service + ML pipeline
  app/
    core/config.py          Settings (data_dir, curated_dir, precip_cache_dir)
    data/
      connectors/
        hydrology_sources.py   UsgsNwisConnector, OpenMeteoHistoricalPrecipConnector,
                               OpenMeteoHistoricalSolarWindConnector (ERA5-Land archive)
      pipeline/
        cli.py                 Main pipeline entry point (--normalize-beachwatch, --with-hydrology,
                               --with-solar-wind, etc.)
        features.py            Feature column lists + add_temporal_features()
        solar_wind.py          aggregate_solar_wind_windows() — forecast-safe daily summaries
        marine_microbiology.py compute_beach_shore_azimuth(), compute_beach_coastal_features(),
                               build_marine_microbiology_daily()
        _static_data/
          ca_piers.csv          31 hand-curated CA piers (lat/lon/county)
          ca_estuary_mouths.csv 27 CA estuary mouths
    ml/
      training.py              --curated --spatial-backtests --spatial-strategy [quick|shortlist|full]
      feature_agent/
        agent_features.py      AGENT_BUILDERS list (currently empty after pivot)
mobile/            Expo/React Native app (shorelife brand)
web/               Next.js app (shorelife.app)
data/
  curated/         beach_day.parquet, beaches.parquet, solar_wind_daily.parquet, ...
  raw/cnrfc/       Open-Meteo cache (openmeteo/, openmeteo_solar_wind/ subdirs)
```

## Data pipeline

Run from `backend/` with `.venv/bin/python -m app.data.pipeline.cli`.

Full refresh (what CI does):
```
python -m app.data.pipeline.cli \
  --normalize-beachwatch --stations-csv ... --results-csv ... --advisories-csv ... \
  --merge-ceden --max-ceden-rows 50000 \
  --with-external-covariates --with-hydrology --with-solar-wind
```

`--with-solar-wind` fetches ERA5-Land hourly cloud/shortwave/UV/wind via Open-Meteo,
aggregates to forecast-safe daily summaries, and merges 11 marine-microbiology features
into beach_day: `shore_normal_wind_ms`, `solar_inactivation_index`, `cloud_cover_24h_mean`,
`shortwave_24h_sum`, `uv_index_24h_max`, `wind_speed_24h_max`, `days_since_sunny`,
`dist_to_pier_km`, `is_near_pier`, `dist_to_estuary_km`, `is_near_estuary_mouth`.

Cache persists per (lat_0.1°, lon_0.1°, date_range) parquet in `data/raw/cnrfc/openmeteo_solar_wind/`.

## ML training

```
python -m app.ml.training --curated --spatial-backtests \
  --spatial-strategy shortlist \
  --forecast-date "$(TZ=America/Los_Angeles date +%Y-%m-%d)"
```

**Evaluation (as actually implemented in `app/ml/training.py`):**
1. **Temporal split** (`_blocked_indices`, line 1514): unique sample dates split 70% train / 15% valid / 15% test. Single split, no folds. Produces `temporal_validation_metrics` and `production_metrics`.
2. **Spatial county holdouts** (`_spatial_backtest_metrics`, line 1183): leave-one-county-out — train on N-1 counties, test on the held-out county, rotate. Capped by `--spatial-county-limit` (CI default 12, rigorous local 30). Produces `spatial_county_<model>` metrics.
3. **Spatial beach holdouts**: same pattern at the individual-beach level. Capped by `--spatial-beach-limit` (CI default 50, rigorous local 500). Produces `spatial_beach_<model>` metrics.
4. **Promotion gate** (`_spatially_qualified_production_winner`, line 1815): the persisted hist_gbm winner can be swapped to a variant if it fails spatial gates AND a sibling passes. Both spatial holdout sets must produce non-NaN Brier scores. Result reflected in `public_release_eligible` + `promotion_blockers`.

**Doc/code drift** (deferred future work): the previously-claimed "county GroupKFold 3×3 seeds + 1000-bootstrap 10th-percentile gate" is *not* in the code. Either implement it (real work) or remove the claim. The current temporal-+spatial-holdout stack is what runs and what gates promotion.

Current baseline AUCPR ≈ 0.37 production held-out (hist-gbm-curated-v0). Per-spatial-beach AUCPR ≈ 0.85 in the rigorous 500-fold backtest; sequence-model LSTM hits 0.76 county-level (best of the candidates), worth promoting to a research_winner candidate.

## Key design decisions

- **Feature space**: 50+ existing features have absorbed cross-county-generalizable signal from
  standard meteorology. Remaining headroom comes from marine-microbiology features (UV inactivation,
  wind plume transport, point-source proximity) and per-station models.
- **Forecast-safe cutoff**: 5 AM PT daily summaries; nothing leaks same-morning sample data.
- **Shore azimuth**: SVD over 5 nearest-neighbor beaches for coastline tangent; disambiguated
  by vector toward CA inland centroid (37°N, 120.5°W).
- **LLM feature agent**: parked after 200+ iterations with 0 legitimate accepts. Re-engage only
  if per-station stacking / nowcasting don't move AUCPR.

## CI

`.github/workflows/daily-forecast.yml` runs at 6 AM PDT.
Hydrology + solar-wind cache key: `hydro-${{ runner.os }}-v3`.
Timeout: 120 min (covers 6-year initial solar-wind backfill on first run).
