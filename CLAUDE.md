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

`--with-surf` fetches the Open-Meteo **Marine** forecast (waves + primary/secondary swell
trains: height/period/direction) for surf-spot beaches and writes `surf_now.parquet`
(current conditions, one row/spot) + `surf_daily_forecast.parquet` (per-spot, per-day range +
dominant swell). Surf spots come from the curated `surf_spot_aliases.csv` matched onto beaches
via `surf_spots.apply_surf_aliases()`, which also adds `surf_name` / `is_surf_spot` /
`surf_latitude` / `surf_longitude` to `beaches.parquet` (display-only; official `name`/coords
untouched). Marine cache: `data/raw/cnrfc/openmeteo_marine/`, keyed by (coord, issue_date).
Aggregation lives in `pipeline/surf_conditions.py`. Note: surf heights are honest offshore
significant wave heights in feet — translating to breaking-wave *face* height per spot needs
per-spot swell-window modeling (deferred fast-follow).

### Data-quality corrections (applied in normalization, 2026-06-01)

- **PCR exceedance threshold** (`pipeline/exceedance.py`): San Diego ddPCR/MCB-ddPCR samples
  report enterococcus in **copies/100mL** and must be judged against **1413 copies**, NOT the
  104 culture STV. `is_pcr_measurement` (method contains "pcr" OR units contain "copies") +
  `compute_exceeds_stv` are wired into both beachwatch + ceden normalizers. The flat 104 had
  false-flagged ~98% of PCR samples.
- **County corrections** (`pipeline/county_corrections.py`): jurisdiction-as-county fixes
  (`"Long Beach City"` → `"Los Angeles"`). Note `region` is the regulatory **Regional Water
  Board** (San Diego board covers south Orange County) — NOT the county; the apps label by
  county only.
- **Place-name spelling** (`pipeline/spelling.py`): Tijana→Tijuana, Oceanisde→Oceanside,
  storn→storm, oultet→outlet (display name/beach_name/station_name; `beach_id` keys untouched).
- **One-time-station cap** (`pipeline/station_quality.py`): `support_status_for` marks stations
  whose sampling history spans **<90 days** as `unsupported` (one-time incidents, out of training).
- **Negative enterococcus values** (−1000 sentinels) are dropped → NaN in normalization.

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
4. **Promotion gate** (`_spatially_qualified_production_winner`): the temporal winner is vetoed
   when it fails the spatial gates (held-out county/beach AUCPR + Brier must beat persistence,
   spatial calibration slope ≥ 0.4) and a sibling passes. **Fixed 2026-06-01**: the gate now runs
   for ANY temporal winner (the prior `winner.startswith("hist_gbm")` guard let an overfit
   non-hist_gbm winner like logistic bypass the spatial veto), and shortlist mode always backtests
   the full hist_gbm family so a robust alternative is available to swap in.

**2026-06-01 model rebuild** (`app/ml/training.py`, `app/ml/models.py`):
- **Training window 60 → 365 days** — the 60-day default starved the fit (~1.8k rows / ~9 unique
  dates → degenerate temporal split). 365d ≈ 24k rows.
- **Marine-microbiology features wired into the loader allowlist** — the 11 columns
  (`solar_inactivation_index`, `uv_index_24h_max`, `wind_speed_24h_max`, pier/estuary proximity…)
  were computed into `beach_day` but dropped by `_load_curated_training_frame`'s column list, so
  they re-entered as all-NaN→0. Now selected. (Also fixes the dead `uv_index`/`wind_speed_mps`
  name mismatch by adding the real `*_24h_max` columns.)
- **Class weight** `{0:1, 1:3}` → `"balanced"` (true base rate ~10%).
- Risk bands (`calibration.py`): Low <0.20, Moderate 0.20–0.30, High 0.30–0.70, Very High ≥0.70
  (High = ~3× the average beach's ~10% base rate). Pre-rebuild the calibrated probabilities were
  squashed (<0.06) so upper bands never fired; post-rebuild the spread is being re-established.

Baseline AUCPR is being re-established by the rebuild (the prior "≈0.37 / 0.85 / 0.76" figures
predate the corrected labels + feature fixes and should not be cited until the rebuild lands).

**2026-06-02 architecture flip — `xgb_undersample_ensemble`** (`app/ml/models.py`,
`app/ml/training.py`, `scripts/spatial_compare.py`, `scripts/spatial_incumbent.py`):
Added `XGBUndersampleEnsemble` (EasyEnsemble variant: keep all positives, draw N balanced
negative undersamples at a 2:1 ratio, fit one XGBoost each, soft-average probabilities). It is
**always trained** alongside hist_gbm and registered in `PRODUCTION_MODEL_NAMES` + the planner's
spatial backtest set, so the existing promotion gate can swap it in **on its own
leave-one-county-out spatial logic** (no hard-override).
- **Why it won (honest spatial numbers, not temporal):** leave-one-CA-county-out validation,
  predictions pooled across 12 counties:
  - ensemble +marine **0.615 AUCPR / 0.100 Brier** vs incumbent single balanced GBM
    **0.546 / 0.114** (+0.069 AUCPR, better calibration).
  - **Texas pooling REJECTED** — every CA+TX cell was *worse* than CA-only on held-out counties
    (Gulf regime doesn't transfer); the temporal split had falsely favored it (0.775). The product
    stays **CA-only**; the WQP/TX cohort scripts remain offline experiments, not a training input.
  - **Marine features CONFIRMED spatially** (+0.029 over base, best Brier) — they help *more*
    spatially than temporally (unseen counties can't lean on memorized base rates).
  - **0.615 is the real generalization number** — the earlier ~0.76 was temporal-split inflation
    (same beaches in train+test).
- **macOS-only fix:** `import xgboost` must precede `import torch` (duplicate-libomp segfault);
  guarded at the top of both `models.py` and `training.py`. Harmless on Linux CI.
- MPS/LSTM was compared and **dropped** — it lost on every cohort (CA 0.721, TX 0.235,
  CA+TX 0.718) AND would need a freeze→CPU-inference→CI path to ship; the XGB ensemble is CPU,
  fast, and retrains daily in the existing CI with no new infra.

## Key design decisions

- **Feature space**: 50+ features plus the 11 marine-microbiology features (UV inactivation,
  wind plume transport, point-source proximity) — now actually fed to the model (2026-06-01 fix;
  they were previously computed-but-dropped) and **spatially confirmed** to help (2026-06-02).
  Remaining headroom: per-station models.
- **Production classifier**: `xgb_undersample_ensemble` (2026-06-02) — balanced-undersample XGBoost
  soft-ensemble, promoted by the spatial gate over hist_gbm. CA-only; cross-region (TX) pooling was
  tested and rejected on held-out counties.
- **Forecast-safe cutoff**: 5 AM PT daily summaries; nothing leaks same-morning sample data.
- **Shore azimuth**: SVD over 5 nearest-neighbor beaches for coastline tangent; disambiguated
  by vector toward CA inland centroid (37°N, 120.5°W).
- **LLM feature agent**: parked after 200+ iterations with 0 legitimate accepts. Re-engage only
  if per-station stacking / nowcasting don't move AUCPR.

## CI

`.github/workflows/daily-forecast.yml` runs at 6 AM PDT.
Hydrology + solar-wind cache key: `hydro-${{ runner.os }}-v3`.
Timeout: 120 min (covers 6-year initial solar-wind backfill on first run).
