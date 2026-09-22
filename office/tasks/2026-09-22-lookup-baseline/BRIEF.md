---
task: lookup-baseline
worker: gemini
created: 2026-09-22
status: open
---

## Goal

A standalone "lookup baseline" forecaster that predicts beach water-quality
exceedance from each beach's OWN history only — no trained model — plus a
report that shows, beach by beach, how it differs from the currently served
ML forecast and which one the lab results actually agreed with. Measured on
the served log, a strictly-prior 365-day per-beach exceedance rate beats the
served model (forward 1–3 day AUROC 0.879 vs 0.824, AUCPR 0.581 vs 0.395,
Brier 0.0596 vs 0.0713). This task turns that measurement into a runnable
script the CEO can execute locally and read.

All input data is a frozen snapshot of `origin/main` at
`data/snapshots/main-2026-09-22/` (gitignored). Read ONLY from there. Never
read or write `data/curated/`.

## In scope

- `backend/scripts/lookup_baseline.py` — one script, two modes, argparse:
  `--snapshot DIR --out DIR --forecast-date YYYY-MM-DD` (forecast mode) and
  `--snapshot DIR --out DIR --backtest` (replay mode).
- **The lookup forecast, per beach, for one forecast date D.** Uses only
  rows with `sample_date < D` (strictly prior — this is the whole point):
  - `rate_365d`: exceedance rate over samples in `[D-365d, D)` from
    `beach_day.parquet` (`exceeds_stv`), shrunk toward the global rate g of
    all beaches over the same window: `p_lookup = (pos + g*5) / (n + 5)`.
  - `last_sample_date`, `last_sample_exceeds`, `last_sample_value`,
    `sample_age_days = D - last_sample_date`.
  - `advisory_active`: any row in `advisories.parquet` with
    `started_at <= D` and (`ended_at` null or `ended_at >= D`), matched on
    `beach_id`.
  - `rain_flag`: `precip_mm_72h >= 5` on date D in `precip_daily.parquet`,
    matched by rounding the beach's `latitude`/`longitude` (from
    `beaches.parquet`) to one decimal and joining on
    `station_id == f"{lat:.1f}_{lon:.1f}"`. If no station row, flag is null.
  - `band`: exactly one of `Unmonitored` (no sample in 30 days, or never),
    `Posted` (advisory_active), `Elevated` (`p_lookup >= 0.10`), `Low`.
    Precedence in that order.
  - Written to `<out>/lookup_forecast_<D>.parquet`, one row per beach in
    `beaches.parquet`.
- **Comparison against the served forecast for D** (`forecasts.parquet`,
  one row per served beach: `p_exceed`, `risk_band`, `sample_age_days`,
  `advisory_floor_applied`): `<out>/comparison_<D>.md` with (a) a summary
  count table of served `risk_band` × lookup `band`, (b) how many beaches
  the ML serves that the lookup calls `Unmonitored`, (c) the 25 beaches
  with the largest `|p_exceed - p_lookup|`, with name, county, both bands,
  both numbers, sample age, last sample result. Plus `<out>/comparison_<D>.csv`
  with every beach.
- **Backtest mode.** For every distinct `forecast_date` in
  `forecast_history.parquet` (final issue per beach-day = latest
  `forecast_generated_at`), build the lookup forecast for that date and
  score BOTH `p_exceed` and `p_lookup` against the first lab result in
  `beach_day` at D+1..D+3 (`exceeds_stv`). Report AUROC, AUCPR, Brier,
  n, base rate for: all rows; last 90 days; last 30 days; culture beaches vs
  ddPCR beaches (a beach is ddPCR if any of its `observations.parquet` rows
  has `method` containing "pcr" or `units` containing "opies",
  case-insensitive). Also per-beach: for each beach with ≥10 verifiable
  rows and both outcomes present, AUROC of each predictor, and which won.
  Write `<out>/backtest.md` (tables) and `<out>/backtest_by_beach.csv`.
  Expected to reproduce the Goal's numbers within ±0.01 on the 90-day cut.
- `backend/tests/test_lookup_baseline.py` — pure-function tests on small
  synthetic frames: (1) a sample ON date D or after is never counted
  (strictly prior); (2) shrinkage: a beach with 0 samples gets exactly g;
  (3) band precedence Unmonitored > Posted > Elevated > Low; (4) rain
  station key rounding (e.g. lat 32.4499, lon -117.1499 → `32.4_-117.1`).

## Out of scope

- Touching anything under `backend/app/`, `data/curated/`, workflows, the
  web or mobile repos.
- Any trained model, any calibration, any new feature engineering.
- Changing the ML forecast or its bands. This is a read-only comparison.
- Plots/images. Markdown tables only.

## Allowed files

- backend/scripts/lookup_baseline.py
- backend/tests/test_lookup_baseline.py
- data/experiments/lookup_baseline/**   (outputs only; gitignored area)

## Allowed packages

- Only what is already in `backend/.venv`: pandas, numpy, pyarrow,
  scikit-learn (metrics only). No new installs.

## Acceptance

```bash
# run from the repo root; the venv is backend/.venv
backend/.venv/bin/python -m pytest backend/tests/test_lookup_baseline.py -q     # all pass
backend/.venv/bin/python backend/scripts/lookup_baseline.py --snapshot data/snapshots/main-2026-09-22 --out data/experiments/lookup_baseline --forecast-date 2026-09-22   # exit 0
test -s data/experiments/lookup_baseline/lookup_forecast_2026-09-22.parquet && test -s data/experiments/lookup_baseline/comparison_2026-09-22.md && test -s data/experiments/lookup_baseline/comparison_2026-09-22.csv   # files exist
backend/.venv/bin/python backend/scripts/lookup_baseline.py --snapshot data/snapshots/main-2026-09-22 --out data/experiments/lookup_baseline --backtest   # exit 0
test -s data/experiments/lookup_baseline/backtest.md && test -s data/experiments/lookup_baseline/backtest_by_beach.csv   # files exist
grep -c "0.8[6-9]" data/experiments/lookup_baseline/backtest.md   # >0 — lookup AUROC on the 90d cut lands in 0.86–0.89
cd backend && .venv/bin/ruff check scripts/lookup_baseline.py tests/test_lookup_baseline.py   # clean
```

## Phases

### Phase 25
Deliverable: `lookup_baseline.py` with the pure functions (`lookup_rate`,
`last_sample`, `advisory_active`, `rain_station_key`, `assign_band`) and
`test_lookup_baseline.py` passing against them. No I/O yet beyond argparse
skeleton.

### Phase 50
Deliverable: forecast mode works end to end on the snapshot for
2026-09-22 and writes `lookup_forecast_2026-09-22.parquet` with one row per
beach in `beaches.parquet` (850 rows) and the columns listed in scope.

### Phase 75
Deliverable: `comparison_2026-09-22.md` + `.csv` written; backtest mode
implemented and writing `backtest.md` + `backtest_by_beach.csv`.

### Phase 100
Deliverable: report at `reports/100.md` states the 90-day backtest numbers
for both predictors, the served-band × lookup-band table, and the count of
served beaches the lookup calls Unmonitored; and all Acceptance commands
pass.

## Corrections

(appended by the PM; newest last; each entry dated)
