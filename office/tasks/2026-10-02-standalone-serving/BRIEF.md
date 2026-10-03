---
task: standalone-serving
repo: /Users/kylechoi/surf_health-p3
worker: claude
created: 2026-10-02
status: open
---

## Goal

UPDATE_PLAN step 3.4. Today `lookup_serving` does not create the forecast — it overwrites the
`forecasts.parquet` that `app/ml/training.py` wrote, so training (~49 of ~75 daily CI minutes)
runs mainly to decide which beaches are served and to provide the 33 columns the served file
carries. When this task is done, `lookup_serving --standalone` builds that frame itself, and
the daily workflow runs it in **shadow** (into a temp folder, diffed against the real output,
never published) so 7 days of zero diff can be observed before the CI split (3.5).
Work on a branch the PM cuts from `main` after the Phase-1 PR merges.

## In scope

1. `lookup_serving.build_candidates(curated_dir, forecast_date) -> pd.DataFrame`: one row per
   beach that training's forecast export would serve — reproduce training's candidate rule
   exactly (read `_build_forecast_candidates` and `_export_forecasts` in `app/ml/training.py`:
   support status, `--forecast-min-recency-days 30` as the daily workflow passes it, and any
   other filter), with every column `forecasts.parquet` carries that is NOT recomputed by
   `apply_lookup_to_served` (environmental display columns such as `wave_height_m`,
   `water_temperature_c`, `uv_index`, `wind_speed_mps`, `uv_alert`, `salinity_psu`,
   `dominant_period_s`; `sample_age_days`, `sample_recency_band`, `is_beta_forecast`,
   `forecast_label_mode`, `forecast_generated_at`, …) taken from the same curated sources
   training uses. ML-only columns (`p_exceed_ml`, `risk_band_ml`, `p_exceed_precal`,
   `served_offset_weight`, `predicted_log_enterococcus`, prediction intervals) are null.
2. `--standalone` flag (and `--out DIR`, default = `--curated`): build candidates, then run the
   normal `apply_lookup_to_served` path on them, writing `forecasts.parquet` (and the history /
   health updates it normally makes) into `--out` — never into `--curated` when `--out` differs.
3. `scripts/diff_standalone_forecast.py --real DIR --shadow DIR`: same beach set; `p_exceed`,
   `risk_band`, `advisory_floor_applied`, `persistence_floor_applied` equal (p to 1e-9); prints
   a one-line verdict + up to 20 differing rows; exit 0 always (shadow is informational).
4. Daily workflow: after "Re-apply the per-beach estimate after advisory expiry", a step
   `Shadow standalone serving (UPDATE_PLAN 3.4)` with `continue-on-error: true` that copies
   `data/curated` to a temp dir, runs `--standalone --out <tmp>` on it, then the diff script,
   and appends the verdict line to `data/curated/standalone_shadow_log.jsonl`
   (`{date, rows_real, rows_shadow, beaches_equal, max_abs_dp, n_diff}`) so the 7-day record
   is committed with the data. It must not modify any other file in `data/curated`.
5. Tests: `build_candidates` on a fixture reproduces the beach set training exports for the
   same fixture (run both); `--standalone --out` never writes into `--curated`; the diff
   script's verdict on equal / differing inputs; a workflow test asserting the shadow step
   exists, is `continue-on-error`, and runs after the re-apply step.

## Out of scope

- Turning training off, the CI split, `p_exceed_ml` scheduling (3.5).
- `validate_forecast.py` changes (3.4 step 5) — next task, after the shadow shows its diffs.
- Any change to served values.

## Allowed files

- backend/app/ml/lookup_serving.py
- backend/scripts/diff_standalone_forecast.py
- .github/workflows/daily-forecast.yml (the shadow step only)
- backend/tests/**

## Allowed packages

- none

## Acceptance

```bash
cd backend
.venv/bin/pytest -q                       # no new failures
.venv/bin/ruff check app tests scripts    # clean
SN=/Users/kylechoi/surf_health/data/snapshots/after-2026-10-02
rm -rf /tmp/shadow && cp -r $SN /tmp/shadow_in
.venv/bin/python -m app.ml.lookup_serving --curated /tmp/shadow_in --standalone --out /tmp/shadow
.venv/bin/python scripts/diff_standalone_forecast.py --real $SN --shadow /tmp/shadow
# expect: same beach set (496) and zero p_exceed differences, or every difference explained in the report
```

## Phases

### Phase 25
Deliverable: `build_candidates` reproducing training's served beach set on a fixture, with tests.

### Phase 50
Deliverable: all non-recomputed columns filled from curated sources; `--standalone --out`.

### Phase 75
Deliverable: `diff_standalone_forecast.py` + the workflow shadow step + tests.

### Phase 100
Deliverable: Acceptance commands pass; the diff on the after snapshot pasted with every difference explained.

## Corrections

(appended by the PM; newest last; each entry dated)

### 2026-10-02 22:05 — before phase 25 (PM)

Repo is the worktree `/Users/kylechoi/surf_health-p3` on branch `feat/update-plan-phase3`
(cut from `main` after the Phase-1 merge). Its `data/raw` is a symlink to the main checkout's
cache — never commit it. Do not modify `data/curated` there; use copies in /tmp for any run.
