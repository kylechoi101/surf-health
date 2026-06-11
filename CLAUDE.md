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

### Pipeline robustness guards (2026-06-11)

- **CEDEN negative-value guard** (`pipeline/ceden.py`): the CEDEN/SafeToSwim normalizer now nulls
  negative `value`s before exceedance + `dropna`, matching the long-standing beachwatch guard
  (`beachwatch.py:381`). Previously only beachwatch dropped −999/−1000 "not analyzed" sentinels, so
  CEDEN-sourced negatives could leak into training. Takes effect on the next daily refresh.
- **Atomic cache writes** (`connectors/hydrology_sources.py`): all per-coord parquet cache writes go
  through `_atomic_to_parquet` (write `.tmp` → `os.replace`), so a crash mid-write can no longer
  leave a corrupt cache that later reads as garbage.
- **Output schema guard** (`pipeline/schema_guard.py`): `validate_beach_day` runs before the
  `beach_day.parquet` write — HARD-raises only on an empty frame or missing primary keys
  (`beach_id`, `sample_date`, `exceeds_stv`); WARN-only if an expected feature column is absent/
  all-NaN (a connector outage legitimately yields all-NaN, so it must not fail the daily job).
- **Holdout prediction artifacts** (`ml/training.py` + `ml/evaluation.py`): the production winner's
  held-out (label, probability) pairs are persisted to `data/curated/holdout_predictions_temporal
  .parquet` / `..._spatial.parquet`, and `sensitivity_at_specificity(...0.87)` is recorded into
  `system_health.json` (`production_metrics["sensitivity_at_spec_0.87"]` + spatial equivalents) —
  closing the long-standing "Searcy sensitivity is unverifiable" gap (appears after next daily run).

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
  dates → degenerate temporal split). 365d ≈ 24k rows. **(Superseded 2026-06-08: 365d in turn
  starved the SPATIAL fit; now 1095d ≈ 84k rows — see the 2026-06-08 section below.)**
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

**2026-06-08 — training window 365 → 1095d (the real spatial lever)**
(`.github/workflows/daily-forecast.yml`, `pipeline/cli.py`):
The 0.615 county AUCPR above was an offline `spatial_compare` number; the in-pipeline gate only
reproduced 0.509 for the ensemble. Root cause is the **training window, not the model**:
`spatial_compare` trains each leave-one-county-out fold on full history (~76k rows); the gate's
`--winner-only` path used only the 365-day window (~24k rows). Isolation test (spatial_compare
restricted to 365d): +marine 0.612 → 0.567 (−0.045 from the window); the rest of the gap is the
gate's calibration + inner-validation split.
- **Window experiment** (gate retrain @ 1095d, 84,805 rows): the 1095d window genuinely lifts
  the ensemble over hist_gbm on held-out counties; hist_gbm does NOT benefit from more data.
  1095d captures all feature-rich post-2020 history (precip/marine features only exist from 2020).
  CI now trains at 1095d.
  - **⚠️ 2026-06-10 reconciliation (see `backend/METRICS_RECONCILIATION.md`):** the "county AUCPR
    0.590 / beach 0.900, slopes 1.26/1.16" originally written here were **never reproduced by the
    in-pipeline gate**. The daily CI run that wrote the on-disk `data/curated/system_health.json`
    (commit `5d99a8587`, 12-county/50-beach sweep @1095d — the SAME config) actually produced
    **held-out county AUCPR 0.499 / beach 0.871, calib slopes 0.99 / 0.88** (county persistence
    baseline 0.370, pooled county base rate 0.175). 0.499 vs 0.590 is the **offline
    `spatial_compare` vs in-gate** gap — calibration (isotonic on test probs), the gate's inner
    train/valid split, and a different county-selection rule (gate picks counties by row count,
    `spatial_compare` by positive count). The model is identical; only the eval path differs.
    **0.499 / 0.871 are the honest, shipped numbers** — a modest but real spatial lift over
    persistence. Slopes 0.99/0.88 are *better* calibrated than the old 1.26/1.16 claim.
- **Gate picks-best among passing models (2026-06-11: was wrongly documented as a TODO).**
  `_spatially_qualified_production_winner` (`training.py:1806`) filters candidates to those that
  clear the held-out county+beach persistence gates, then picks the best by temporal-valid AUCPR
  (tiebreak lower spatial Brier), with `_WINNER_SWAP_MARGIN` hysteresis so the daily winner-only
  retrain doesn't churn on backtest noise. The earlier "keeps a passing incumbent even when a
  sibling is decisively better — never auto-swaps" note described an OLD veto that no longer
  exists; the swap logic landed with the 1095d ensemble case (2026-06-08) and the code at lines
  1843-1851 already does pick-best. The ensemble remains the registry winner because it wins this
  selection, not because of a manual override.
- **first_rain_score cache self-heal** (`pipeline/cli.py`): the incremental `precip_daily.parquet`
  cache only re-fetched the last 7 days, so derived columns added later (first_rain_score,
  precip_*_prior, precip_mm_96h/192h) stayed NaN for all history (~0% covered). Now the pipeline
  detects missing/sparse derived columns and forces a full re-aggregation from the on-disk raw
  cache. Honest result: a live first_rain_score did NOT help the GLOBAL county metric (rainfall is
  beach-specific — Searcy et al. 2018; pays off only in per-station models).
- **Benchmark (Searcy et al. 2018, 10 CA oceanic beaches, operational):** median sensitivity 0.50
  @ specificity 0.87 for enterococcus. The old "sens 0.59 @ spec 0.87" claim was UNVERIFIABLE
  (2026-06-10, no holdout artifact persisted). **Closed + computed 2026-06-11:** `training.py`
  persists the winner's held-out (label, probability) pairs to
  `data/curated/holdout_predictions_{temporal,spatial}.parquet` and records
  `sensitivity_at_specificity(0.87)` into `system_health.json`. **Real shipped numbers (ensemble,
  2026-06-11 dispatch run on `687aa2393`):**
  - **Temporal-test (same beaches in train+test, optimistic): sensitivity 0.722 @ spec 0.871.**
  - **Leave-one-county-out holdout (the honest generalization figure): sensitivity 0.482 @ spec
    0.896** — essentially the Searcy operational median (0.50 @ 0.87).
  - Leave-one-beach-out holdout: sensitivity 0.832 @ spec 0.871.
  So cite **~0.48 @ 0.90 (county holdout)** as the conservative real-world number and **0.72 @ 0.87
  (temporal)** as the in-distribution number — NOT a single blended figure. Recompute any other
  operating point from the parquet with no retrain. See `backend/METRICS_RECONCILIATION.md`.

## Key design decisions

- **Feature space**: 50+ features plus the 11 marine-microbiology features (UV inactivation,
  wind plume transport, point-source proximity) — now actually fed to the model (2026-06-01 fix;
  they were previously computed-but-dropped) and **spatially confirmed** to help (2026-06-02).
  Remaining headroom: per-station models.
- **Production classifier**: `xgb_undersample_ensemble` — balanced-undersample XGBoost soft-ensemble.
  Trained on the **1095-day window** (2026-06-08) where it beats hist_gbm on held-out counties and
  beaches. **Shipped held-out metrics (2026-06-10 reconciliation, from on-disk
  `system_health.json`): county AUCPR 0.499 / beach 0.871, calib slopes 0.99 / 0.88** — NOT the
  0.590/0.900 once cited (that was an offline `spatial_compare` number never reproduced by the
  gate; see `backend/METRICS_RECONCILIATION.md`). hist_gbm on the same gate path: county 0.480 /
  beach 0.853. CA-only; cross-region (TX) pooling tested and rejected on held-out counties. It is
  the registry winner because it wins the gate's pick-best-among-passing selection (with hysteresis),
  not via a manual override — see the corrected "Gate picks-best" note above.
- **Forecast-safe cutoff**: 5 AM PT daily summaries; nothing leaks same-morning sample data.
- **Shore azimuth**: SVD over 5 nearest-neighbor beaches for coastline tangent; disambiguated
  by vector toward CA inland centroid (37°N, 120.5°W).
- **LLM feature agent**: parked after 200+ iterations with 0 legitimate accepts. Re-engage only
  if per-station stacking / nowcasting don't move AUCPR.

## CI

`.github/workflows/daily-forecast.yml` runs at 9 AM PDT (cron `0 16 * * *`).
Hydrology + solar-wind cache key: `hydro-${{ runner.os }}-v4`.
Timeout: 170 min (was 120; bumped 2026-06-10 — the 1095d window's spatial sweep was
overrunning the old budget and timing the job out before it could commit).

**Action versions (2026-06-11):** all workflows pinned to Node-24 runtimes
(`checkout@v5`, `setup-python@v6`, `cache@v5`) ahead of GitHub's 2026-06-16 forced Node-20→24
migration; a github-actions-only Dependabot keeps them current (pip is intentionally manual).

**Failure alerting (2026-06-11):** daily-forecast has a `notify-failure` job (`if: failure()`)
that opens/comments a de-duped `pipeline-failure` GitHub Issue (assigned to the repo owner, who
gets emailed) — previously a failed run was silent until `/system/health` went 503.
`deploy-backend.yml` now polls `/system/health` after the Render webhook (~5 min) and fails the
deploy if it never returns 200, so a broken Render build no longer ships unnoticed. Both have
`concurrency` with `cancel-in-progress: false` (never kill a mid-flight train/commit/deploy).

**Daily spatial backtest folds — 6 counties / 15 beaches** (`--spatial-county-limit 6
--spatial-beach-limit 15`, commit `153f1368a`, 2026-06-10). The full 12-county / 50-beach
sweep at 1095d (~84k rows, ~60 retrains) overran the ML budget and timed the whole job out
(stale forecast → `/system/health` 503). 6/15 still yields valid spatial-holdout metrics that
pass the public-release gate. The full 12/50 sweep is kept only for the manual
`workflow_dispatch full_comparison=true` (winner re-selection) path. NOTE: the on-disk
`system_health.json` metrics (county 0.499 / beach 0.871) predate this trim — they were
written by the prior 12/50 daily run; the next daily refresh at 6/15 will have noisier
(fewer-fold) spatial numbers. Reconciliation detail: `backend/METRICS_RECONCILIATION.md`.
