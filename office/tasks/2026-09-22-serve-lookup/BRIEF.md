---
task: serve-lookup
repo: /Users/kylechoi/surf_health-lookup
worker: gemini
created: 2026-09-22
status: open
---

## Goal

Replace the probability the product SERVES with the per-beach lookup
estimate, keeping every downstream contract (forecasts.parquet columns, the
API, the web bake, validation gates, forecast_history) intact. The ML
pipeline still trains and runs exactly as today; a new step runs right after
it and overwrites the served fields. Measured on the served log, the lookup
beats the served ML on forward 1–3 day lab outcomes (90d AUROC 0.878 vs
0.824, AUCPR 0.580 vs 0.395, Brier 0.060 vs 0.071) and gives four separated
bands at the EXISTING cutpoints (realized Low 0.033 / Moderate 0.114 / High
0.354 / Very High 0.818). Both apps read these fields, so no app code change
is needed for the numbers.

Repo is the worktree `/Users/kylechoi/surf_health-lookup` (branch
`feat/serve-lookup-baseline`, based on origin/main). `backend/.venv` is a
symlink to a working venv. Test data: `data/snapshots/main-2026-09-22/` is a
copy of main's `data/curated/` (never commit it).

## The lookup (exact spec)

For forecast date D (read it from `forecasts.parquet`'s `forecast_date`
column — all rows share one date; do NOT take it from the wall clock), per
beach, from `beach_day.parquet` rows with `D-365d <= sample_date < D`
(strictly before D):

- `n` = row count, `pos` = sum of `exceeds_stv`.
- `g` = pooled `exceeds_stv` mean over ALL beaches in the same window.
- `p_lookup = (pos + 5*g) / (n + 5)`.
- `last_sample_date`, `last_exceeds` = most recent row strictly before D.
- Persistence floor: if `last_exceeds` is true, `base = max(p_lookup,
  calibration._LOW_THRESHOLD)` and `persistence_floor_applied = True`, else
  `base = p_lookup`, False.
- Interval: `p_exceed_lower/upper` = 5th/95th percentiles of
  `Beta(pos + 5*g, n - pos + 5*(1-g))` (scipy.stats.beta), then
  `max(lower, …)`-adjust so `lower <= base <= upper` still holds after the
  floor (set upper = max(upper, base)).
- Advisory floor (export time, same rule as today): a beach is posted if
  `advisories.parquet` has a row for it with `status == "active"` and
  `started_at <= D`. For posted beaches, `p_exceed, advisory_floor_applied =
  calibration.advisory_floored_probability(base, True)`; others `p_exceed =
  base`, `advisory_floor_applied = False`.
- `risk_band = calibration.risk_band(p_exceed)`.

## In scope

1. `backend/app/ml/lookup_serving.py` with:
   - `compute_lookup(beach_day, forecast_date, beach_ids, window_days=365,
     prior_strength=5) -> DataFrame` (pure; one row per requested beach_id,
     a beach with no rows in the window gets `p_lookup == g`, n=0, pos=0,
     last_* null).
   - `apply_lookup_to_served(curated_dir: Path) -> dict` that:
     a. reads `forecasts.parquet`; if its `model_version` is NOT already
        `LOOKUP_MODEL_VERSION`, copies `p_exceed`→`p_exceed_ml` and
        `risk_band`→`risk_band_ml` (idempotent: a second run must not
        overwrite the ML copies with lookup values);
     b. writes the lookup into: `p_exceed`, `p_exceed_raw` (= base, the
        pre-advisory-floor value; the API and web bake band from this),
        `p_exceed_lower`, `p_exceed_upper`, `risk_band`,
        `persistence_floor_applied`, `advisory_floor_applied`;
        `model_version = LOOKUP_MODEL_VERSION = "lookup-365d-v1"`;
        `served_offset_weight = None`; `predicted_log_enterococcus`,
        `lower_prediction_interval`, `upper_prediction_interval`,
        `prediction_interval_level` = None (they are ML-regressor outputs);
        `top_drivers` = list of plain-English strings, in order:
          - `"Above the safety limit in {pos} of {n} lab tests over the past 12 months"`
            (if n == 0: `"No lab tests in the past 12 months — using the statewide average"`)
          - `"Last test {Mon D}: above the limit"` or `"...: within the limit"`
            (omit if no last sample)
          - if 0 < n < 10: `"Few recent tests — estimate leans on the statewide average"`
        Leave `p_exceed_precal`, `sample_age_days`, `sample_recency_band`,
        `forecast_label_mode`, `forecast_generated_at` and all environment
        columns untouched.
     c. updates `forecast_history.parquet`: for rows whose (`beach_id`,
        `forecast_date`, `forecast_generated_at`) match the forecasts rows,
        set the same served fields (`p_exceed`, `p_exceed_raw`,
        `risk_band`, `model_version`, `persistence_floor_applied`,
        `served_offset_weight`) and `p_exceed_ml` (the ML value, same
        idempotency rule). For all OTHER history rows where `p_exceed_ml`
        is null and `model_version != LOOKUP_MODEL_VERSION`, backfill
        `p_exceed_ml = p_exceed` (those rows served the ML).
        `p_exceed_precal` stays the ML's pre-calibration value.
     d. adds `"p_exceed_ml"` to `served_metrics._HISTORY_COLUMNS` (and to
        `_PROBABILITY_COLUMNS` if that list is used for numeric coercion) so
        tomorrow's history append keeps it.
     e. writes `system_health.json["serving_method"] = {"name":
        "lookup-365d-v1", "window_days": 365, "prior_strength": 5,
        "forecast_date": D, "rows": N, "posted": k, "persistence_floored":
        m, "applied_at": <UTC ISO>}` via `app.core.json_safe.dumps_strict`
        (read-modify-write; keep every other key).
     f. all parquet writes atomic (write `.tmp` then `os.replace`).
     Returns a summary dict.
   - `__main__`: `python -m app.ml.lookup_serving --curated DIR`, prints
     the summary, exit 0.
2. `.github/workflows/daily-forecast.yml`:
   - new step `Serve the lookup estimate` immediately AFTER `Run ML
     training + forecasts` and BEFORE `Honor release gate for hourly
     forecast`, same `working-directory` as the neighbouring python steps,
     running the module with `--curated ../data/curated/`.
   - change `--forecast-min-recency-days 45` to `30`.
3. `backend/tests/test_lookup_serving.py`: (1) strictly prior — a row ON
   D is ignored; (2) n=0 beach gets exactly g; (3) persistence floor binds
   and sets the flag; (4) posted beach floored to `_HIGH_THRESHOLD` with
   `p_exceed_raw` unfloored; (5) `lower <= p_exceed_raw <= upper`;
   (6) idempotency — running `apply_lookup_to_served` twice leaves
   `p_exceed_ml` equal to the original ML value; (7) history rows for
   today updated, older rows backfilled; (8) `_HISTORY_COLUMNS` contains
   `p_exceed_ml`. Use tmp_path with small synthetic parquet files.
4. Update the one paragraph in `CLAUDE.md` that describes what is served:
   add a short dated section "Served estimate: per-beach lookup
   (2026-09-22)" stating the formula, that the ML still trains and its
   probability is preserved as `p_exceed_ml`, and that the change was made
   because the lookup beat the served ML on the served log (numbers in
   Goal). Keep it under 25 lines.

## Out of scope

- Any change to training, calibration cutpoints, the API code, the web
  bake script, or the apps.
- Deleting the ML pipeline.
- Committing or pushing (the PM does that).

## Allowed files

- backend/app/ml/lookup_serving.py
- backend/app/ml/served_metrics.py   (only the column lists in d.)
- backend/tests/test_lookup_serving.py
- .github/workflows/daily-forecast.yml
- CLAUDE.md

## Allowed packages

- None new. pandas, numpy, scipy, pyarrow are in the venv.

## Acceptance

```bash
cd /Users/kylechoi/surf_health-lookup
rm -rf /tmp/lookup_accept && cp -r data/snapshots/main-2026-09-22 /tmp/lookup_accept && cp data/snapshots/main-2026-09-22/forecasts.parquet /tmp/lookup_prev.parquet
cd backend && .venv/bin/python -m app.ml.lookup_serving --curated /tmp/lookup_accept      # exit 0, prints summary
cd backend && .venv/bin/python -m app.ml.lookup_serving --curated /tmp/lookup_accept      # second run exit 0 (idempotent)
cd backend && .venv/bin/python -c "import pandas as pd; f=pd.read_parquet('/tmp/lookup_accept/forecasts.parquet'); p=pd.read_parquet('/tmp/lookup_prev.parquet'); assert (f.model_version=='lookup-365d-v1').all(); assert (f.p_exceed_ml.values==p.p_exceed.values).all(); assert len(f)==len(p); print(f.risk_band.value_counts().to_dict())"
cd backend && SKIP_FORECAST_ANOMALY_CHECKS=0 .venv/bin/python scripts/validate_forecast.py --curated /tmp/lookup_accept --previous /tmp/lookup_prev.parquet ; echo "exit=$?"   # anomaly checks pass; a stale-date failure is acceptable ONLY if it is the forecast-date freshness check
cd backend && .venv/bin/python -m app.data.pipeline.serving_snapshot --curated /tmp/lookup_accept   # exit 0
cd backend && .venv/bin/python -m pytest tests/test_lookup_serving.py -q      # all pass
cd backend && .venv/bin/python -m pytest -q -x -p no:cacheprovider 2>&1 | tail -3   # full suite passes
cd backend && .venv/bin/ruff check app/ml/lookup_serving.py tests/test_lookup_serving.py app/ml/served_metrics.py   # clean
```

## Phases

### Phase 25
Deliverable: `compute_lookup` + tests (1), (2) passing.

### Phase 50
Deliverable: `apply_lookup_to_served` a–f + CLI, tests (3)–(8) passing,
first three Acceptance commands pass.

### Phase 75
Deliverable: workflow step + recency change; validate_forecast and
serving_snapshot Acceptance commands pass on the temp copy.

### Phase 100
Deliverable: CLAUDE.md section; report states the risk_band counts on the
temp copy, the validate_forecast output, and full-suite result; all
Acceptance commands pass.

## Corrections

(appended by the PM; newest last; each entry dated)
