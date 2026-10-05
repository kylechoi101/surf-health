---
task: florida-prototype
repo: /Users/kylechoi/surf_health-fl
worker: gemini
created: 2026-10-05
status: open
---

## Goal

A research-only **Florida test forecast**. The repo is the worktree `/Users/kylechoi/surf_health-fl`, on branch `research/florida-prototype`, which branches from `research/hi-fl-feasibility`. A single script must do four things:
- download the University of South Florida (USF) Water Atlas copy of the Florida Department of Health (FL DOH) beach enterococcus results;
- build beach sample-days from them;
- score the same model California serves (logistic regression on top of the per-beach lookup) month by month over the last 12 months;
- write a forecast for every recently sampled Florida beach for a given date.

This answers whether the product would be useful in Florida before any production work starts. Nothing in production code, workflows or `data/curated/` changes.

## In scope

- New script `backend/scripts/florida_prototype.py` with subcommands `fetch`, `build`, `backtest`, `forecast`, and `all` (runs them in order). Run it from `backend/` as `python scripts/florida_prototype.py <cmd> [--forecast-date YYYY-MM-DD]`. The default date is today in America/New_York.
- **`fetch`:**
  - History CSV: `https://chnep.wateratlas.usf.edu/maps/coastal-water-quality-map/download-historic.ashx/?ds=FLHEALTH`, saved to `data/raw/florida/usf_flhealth_history.csv`.
  - Latest-per-site GeoJSON: `https://api.wateratlas.usf.edu/CoastalWaterQualityConcerns?param=Ecoccus_100ml`, saved to `data/raw/florida/usf_latest.json`.
  - Every request gets a timeout (connect 30 s, read 120 s) and at most 3 retries. Use a browser User-Agent.
  - If a download fails and a cached file exists, keep the cached file and log it.
- **`build`:**
  - Parse the CSV. It has a UTF-8 BOM. Dates look like `8/15/2022 12:00:00 AM`. Units say `CFU/mL` but the values are per 100 mL.
  - Keep `Datasource == FLHEALTH` and `Parameter == Ecoccus_100ml`.
  - `TNTC` and `>N` values count as exceeding: use N, or 2× the limit for TNTC. Values written with `<` count as half the number.
  - Collapse same-station, same-day samples to the worst one (maximum value).
  - Florida's advisory limit is **70** per 100 mL. Set `exceeds = value > 70` and `ratio = value / 70`.
  - Output `data/experiments/florida/FL_usf_sample_days.parquet` with columns `station_id, sample_date, value, exceeds, ratio, lat, lon, name, is_qpcr (False)`, and `FL_usf_stations.parquet`.
- **`backtest`:**
  - **Reuse** the pure functions in `backend/scripts/multistate_feasibility.py` by importing them: `lab_features`, `fit_offset_logit`, `predict_offset_logit`, `metrics`, `cluster_bootstrap`, `rain_72h_to_5am`, `fetch_rain`, `_coord_key`. Do NOT edit that file.
  - The rain cache for Florida is already in `data/raw/openmeteo_multistate/FL_*.parquet`, keyed by 0.1° coordinate. Fetch only missing coordinates, through 2026-10-05, using the same rate-limit handling.
  - Walk forward: refit monthly on every sample-day before the month and score that month. Score the 12 months 2025-10 through 2026-09.
  - Models: the lookup; persistence (1 if the last result exceeded, else the statewide rate g); `logistic` with features R, R·F, W, S; and `logistic_free_phase` with R, R·F, W, S, sin(season).
  - Report AUROC, AUCPR, Brier and within-station AUROC for each, plus beach-cluster bootstrap 95% CIs on logistic minus lookup, and coefficients per refit.
  - Write `data/experiments/florida/backtest.json` and `FL_usf_walkforward_predictions.parquet`.
- **`forecast`:**
  - For forecast date D, take every station with ≥3 samples in the 365 days before D and its newest sample within 30 days of D.
  - Compute the logistic offset model (the free-phase variant if the backtest showed it was better, otherwise the served form). Fit it on all sample-days strictly before D. Features use only samples strictly before D.
  - Rain is the 72 h ending 05:00 America/New_York on D. Use the Open-Meteo forecast API (`https://api.open-meteo.com/v1/forecast`, `past_days=3`, hourly precipitation) because the archive lags by days. Fetch once per 0.1° coordinate, cached under `data/raw/florida/rain_forecast_<D>/`.
  - Apply the persistence floor: if the last sample exceeded, p ≥ 0.20.
  - Bands: Low < 0.20, Moderate 0.20–0.30, High 0.30–0.70, Very High ≥ 0.70.
  - Write `data/experiments/florida/forecast_<D>.parquet` and `.csv` with columns `station_id, name, lat, lon, forecast_date, p_exceed, p_lookup, risk_band, last_sample_date, last_value, last_exceeds, rain_mm_72h, n_samples_365d`.
- **`data/experiments/florida/REPORT.md`:** a short, plain-language report. Include data coverage (stations, date range, samples per station per year, exceedance rate), the backtest table with CIs and coefficients, forecast-day counts by band, and the caveats:
  - USF runs 1–2 weeks behind FL DOH;
  - labels are single-sample exceedances, while FL DOH issues an advisory only after a confirming resample;
  - within-station skill.
- Tests in `backend/tests/test_florida_prototype.py`:
  - CSV parsing (BOM, date format, TNTC / `>` / `<` values);
  - worst-sample-per-day collapse;
  - the forecast uses no sample on or after D (build a fixture where a sample on D would change the answer);
  - the persistence floor;
  - band cutpoints.
  - No network in tests.

## Out of scope

- Any change to `backend/app/**`, `backend/scripts/multistate_feasibility.py`, `.github/**`, `data/curated/**`, the web or mobile repos.
- Scraping the FL DOH Caspio page, Surfrider or any source other than the two USF URLs and Open-Meteo.
- New dependencies, a production pipeline, scheduling, or a UI.

## Allowed files

- backend/scripts/florida_prototype.py
- backend/tests/test_florida_prototype.py
- data/experiments/florida/**
- data/raw/florida/** (gitignored; do not force-add)
- data/raw/openmeteo_multistate/** (gitignored; new FL_* cache files only)

## Allowed packages

- none (use what the backend venv already has: pandas, numpy, httpx, scikit-learn, scipy)

## Acceptance

```bash
# run from /Users/kylechoi/surf_health-fl/backend; PY=/Users/kylechoi/surf_health/backend/.venv/bin/python
$PY -m pytest -q tests/test_florida_prototype.py                       # all pass, no network
/Users/kylechoi/surf_health/backend/.venv/bin/ruff check scripts/florida_prototype.py tests/test_florida_prototype.py   # clean
$PY scripts/florida_prototype.py all --forecast-date 2026-10-05        # exits 0, writes the files below
$PY -c "import pandas as pd; f=pd.read_parquet('../data/experiments/florida/forecast_2026-10-05.parquet'); assert len(f)>=150, len(f); assert f.p_exceed.between(0,1).all(); assert (pd.to_datetime(f.last_sample_date)<'2026-10-05').all(); assert not ((f.last_exceeds) & (f.p_exceed<0.2)).any(); print(len(f), f.risk_band.value_counts().to_dict())"
$PY -c "import json; b=json.load(open('../data/experiments/florida/backtest.json')); print({k: round(v['auroc'],3) for k,v in b['metrics'].items()})"   # lookup, persistence, logistic, logistic_free_phase present
test -s ../data/experiments/florida/REPORT.md && echo report-ok
```

## Phases

### Phase 25
Deliverable: `fetch` and `build` subcommands work; `FL_usf_sample_days.parquet` and `FL_usf_stations.parquet` exist; parsing and collapse tests pass.

### Phase 50
Deliverable: `backtest` subcommand writes `backtest.json` and the walk-forward predictions for 2025-10..2026-09, reusing the multistate functions; no-leakage test passes.

### Phase 75
Deliverable: `forecast` subcommand writes `forecast_2026-10-05.parquet/.csv` with forecast-API rain, the persistence floor and bands; floor and band tests pass.

### Phase 100
Deliverable: `all` runs end to end, `REPORT.md` written, and all Acceptance commands pass.

## Corrections

(appended by the PM; newest last; each entry dated)
