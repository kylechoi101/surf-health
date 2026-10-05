---
task: florida-ml-models
repo: /Users/kylechoi/surf_health-fl
worker: gemini
created: 2026-10-05
status: open
---

## Goal

Score **every machine-learning model California trains** on Florida's data, on exactly the same Florida beach-days the served logistic model was scored on, and put the results side by side. This answers whether any ML model beats the simple logistic model in Florida.

This is research only, in the worktree `/Users/kylechoi/surf_health-fl` on branch `research/florida-prototype`. That branch already has `backend/scripts/florida_prototype.py`, its outputs in `data/experiments/florida/` and `data/experiments/florida/REPORT.md`.

## In scope

- New script `backend/scripts/florida_ml_models.py`. Run it from `backend/` as `python scripts/florida_ml_models.py <features|backtest|report|all>`.
- **Inputs:**
  - `data/experiments/florida/FL_usf_sample_days.parquet` and `FL_usf_stations.parquet`, both from `florida_prototype.py`.
  - The Florida rain cache in `data/raw/openmeteo_multistate/FL_*.parquet`.
  - The scored rows of `data/experiments/florida/FL_usf_walkforward_predictions.parquet`, which has the served logistic and lookup predictions.
- **`features`:** build one feature row per sample-day, using only information strictly before that day (05:00 America/New_York cutoff for weather):
  - **Lab history:** lookup rate, n and pos over 365 d; last value (log10); last exceeds; age of last sample in days; the previous 3 values (log10) and their ages; exceedance count over the last 30 / 90 / 365 d; geometric mean of the last 5 values; days since the last exceedance.
  - **Rain:** 24 h, 48 h, 72 h and 7 d totals ending 05:00 on the day, from the cached hourly rain.
  - **Weather, to give the ML its best shot:** fetch hourly `cloud_cover`, `shortwave_radiation`, `wind_speed_10m` and `wind_direction_10m` from the Open-Meteo archive, one request per 0.1° coordinate. Use the same timeout, 429 handling and caching as `fetch_rain` in `scripts/multistate_feasibility.py`. Cache under `data/raw/florida/weather/`. Derive 24 h mean cloud, 24 h shortwave sum, 24 h max wind, and wind direction as sin and cos, all ending 05:00.
  - **Season and place:** day-of-year sin and cos, month, lat, lon.
  - Write `data/experiments/florida/ml/FL_ml_features.parquet`.
- **`backtest`:** the same walk-forward as the served model. For each month 2025-10..2026-09, train on every eligible sample-day before the month and score that month. Score **exactly** the `(station_id, sample_date)` rows in `FL_usf_walkforward_predictions.parquet`. Use the same eligibility as `florida_prototype.py`: training rows need ≥365 d of history before them.
  - **Calibration:** like California, hold out the last 15% of each month's training rows by date, fit on the rest, fit an isotonic calibrator on the held-out part, and apply it to the scored month. Report both raw and calibrated Brier.
  - **The models, as California defines them**, reusing `app.ml.models` and `app.ml.training` wherever the code is pure:
    1. `logistic`: `make_baselines(features).logistic` (sklearn, balanced class weights).
    2. `logistic_coastal_cells`: per-cluster logistic on k-means clusters of beaches (see `_fit_coastal_cell_assigner` / `_fit_coastal_cell_logistic_artifacts`).
    3. `logistic_hierarchical`: see `_fit_hierarchical_logistic_artifacts`.
    4. `hist_gbm`: `make_baselines(features).tree_classifier`.
    5. `hist_gbm_positive_persistence_guard`: `_positive_persistence_guarded_blend_probabilities` on hist_gbm + persistence, with the alpha training.py uses.
    6. `hist_gbm_persistence_blend`: see training.py around line 1260.
    7. `xgb_undersample_ensemble`: `XGBUndersampleEnsemble()`.
    8. `xgb_undersample_offset`: `XGBUndersampleOffsetEnsemble()` with `beach_ids` = station_id.
    9. `stacked_ensemble`: see training.py around line 1208.
  - Where a training.py implementation is tied to California-only artifacts (counties, regions, CA files), reimplement it faithfully on Florida data and write down in the report exactly what you changed.
  - Remember `import xgboost` must come before `import torch` on macOS.
  - Write `data/experiments/florida/ml/FL_ml_walkforward_predictions.parquet`, one probability column per model plus `p_lookup` and `p_logistic_served` joined from the served-model file, and `data/experiments/florida/ml/ml_backtest.json`.
- **`report`:**
  - For every model plus `lookup`, `persistence` and `logistic_served`: AUROC, AUCPR, Brier (raw and calibrated) and within-station AUROC.
  - Beach-cluster bootstrap 95% CIs on each ML model minus `logistic_served`, using `cluster_bootstrap` from `multistate_feasibility.py`.
  - Training time per model.
  - Feature importance for hist_gbm (permutation importance on the last month is fine).
  - Write `data/experiments/florida/ml/ML_REPORT.md`: a short, plain-language ranked table, which models beat the served logistic and whether the CIs exclude zero, what was reimplemented, and caveats.
- Tests in `backend/tests/test_florida_ml_models.py`, with no network:
  - every feature is strictly prior (a fixture where a same-day or future sample would change the feature);
  - weather windows end at 05:00;
  - the backtest scores exactly the served-model row set;
  - the calibration split is by date, not random.

## Out of scope

- Sequence models (tcn, cnn, lstm, transformer, pinn). California dropped them, and they need a separate per-beach sequence pipeline. Mention this in the report.
- `hist_gbm_regressor` (not a probability model).
- Any change to `backend/app/**`, `backend/scripts/florida_prototype.py`, `backend/scripts/multistate_feasibility.py`, `.github/**`, `data/curated/**`, the existing `data/experiments/florida/*` files, or the web and mobile repos.
- New dependencies.

## Allowed files

- backend/scripts/florida_ml_models.py
- backend/tests/test_florida_ml_models.py
- data/experiments/florida/ml/**
- data/raw/florida/weather/** (gitignored)
- data/raw/openmeteo_multistate/** (gitignored; new FL_* rain files only, if any coordinate is missing)

## Allowed packages

- none (backend venv: pandas, numpy, scikit-learn, xgboost, httpx, scipy)

## Acceptance

```bash
# from /Users/kylechoi/surf_health-fl/backend; PY=/Users/kylechoi/surf_health/backend/.venv/bin/python
$PY -m pytest -q tests/test_florida_ml_models.py tests/test_florida_prototype.py      # all pass, no network
/Users/kylechoi/surf_health/backend/.venv/bin/ruff check scripts/florida_ml_models.py tests/test_florida_ml_models.py   # clean
$PY scripts/florida_ml_models.py all          # exits 0
$PY -c "import pandas as pd; m=pd.read_parquet('../data/experiments/florida/ml/FL_ml_walkforward_predictions.parquet'); s=pd.read_parquet('../data/experiments/florida/FL_usf_walkforward_predictions.parquet'); k=['station_id','sample_date']; assert len(m)==len(s) and m[k].merge(s[k]).shape[0]==len(s); need=['logistic','logistic_coastal_cells','logistic_hierarchical','hist_gbm','hist_gbm_positive_persistence_guard','hist_gbm_persistence_blend','xgb_undersample_ensemble','xgb_undersample_offset','stacked_ensemble']; miss=[n for n in need if 'p_'+n not in m]; assert not miss, miss; print(len(m),'rows, all 9 models')"
$PY -c "import json; b=json.load(open('../data/experiments/florida/ml/ml_backtest.json')); print({k: round(v['auroc'],3) for k,v in b['metrics'].items()})"
test -s ../data/experiments/florida/ml/ML_REPORT.md && echo report-ok
```

## Phases

### Phase 25
Deliverable: the `features` subcommand writes `FL_ml_features.parquet` (lab history, rain, weather, season, place) with strictly-prior and 05:00-window tests passing; the weather cache is fetched.

### Phase 50
Deliverable: the `backtest` harness scores the exact served-model row set with date-split isotonic calibration, for `logistic`, `hist_gbm`, `xgb_undersample_ensemble` and `xgb_undersample_offset`; row-set and calibration-split tests pass.

### Phase 75
Deliverable: the remaining five models (`logistic_coastal_cells`, `logistic_hierarchical`, `hist_gbm_positive_persistence_guard`, `hist_gbm_persistence_blend`, `stacked_ensemble`) are added, with what was reimplemented written down.

### Phase 100
Deliverable: `report` writes `ml_backtest.json` and `ML_REPORT.md` with metrics, CIs vs the served logistic, training times and hist_gbm importances, and all Acceptance commands pass.

## Corrections

(appended by the PM; newest last; each entry dated)
