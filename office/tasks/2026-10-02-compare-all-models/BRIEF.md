---
task: compare-all-models
repo: /Users/kylechoi/surf_health-p1
worker: gemini
created: 2026-10-02
status: open
---

## Goal

`docs/UPDATE_PLAN.md` Phase 2 (steps 2.2–2.5): one harness that scores every candidate model
on the same forward forecasts, so `backend/app/ml/PROMOTION.md` (already committed — read it
first; it is the decision rule) can be applied to a before and an after data snapshot. This
task builds the tooling and tests it on a small window. The PM runs the full comparisons.

## In scope

1. `backend/scripts/compare_all_models.py`, copied from `backend/scripts/compare_logit_challenger.py`
   (keep its `forward_pairs`, `metrics`, slices, walk-forward refit) and extended:
   - Args: `--curated`, `--out`, `--start`, `--end`, `--train-years`, `--bootstrap`,
     `--arms` (comma list, default all), `--xgb-grid-days` (default 1 = every day; see 4).
   - Arms, all scored on the SAME `forward_1_3d` pairs (and `same_day` pairs, reported only):
     | arm | definition |
     |---|---|
     | `pooled` | statewide base rate of labels in the 365 d before D (strictly < D) |
     | `persistence` | 1.0 if the beach's last label before D exceeded, else `pooled` |
     | `lookup` | `pairs["lookup"]` (as in the existing harness) |
     | `logit` | the existing monthly-refit `p_challenger` |
     | `logit_method` | `logit` + a `ddpcr` indicator term and its interaction with `R`; the beach's assay = its most recent `beach_day.label_method` before D; if `label_method` is absent from beach_day, derive it from `observations.parquet` with `app.data.pipeline.sample_key.assay_kind` on the worst sample of each beach-day. Implement by extending `fit_coefficients`/`predict` locally in the script (do NOT edit `app/ml/logit_challenger.py`) |
     | `xgb_ensemble` | `app.ml.models.XGBUndersampleEnsemble` |
     | `xgb_offset` | `app.ml.models.XGBUndersampleOffsetEnsemble` with `app.ml.two_tier.beach_baseline_margin`, trained on `two_tier.staleness_augmented_frame` exactly as `app/ml/training.py` does (read how training.py calls them and mirror it) |
   - Every arm passes through `logit_challenger.apply_persistence_floor` with `last_exceeds`.
2. XGB training: rows = `training._load_curated_training_frame(curated)` →
   `features.build_inference_features(frame).feature_frame`, numeric columns restricted to
   the columns `features._model_feature_columns` selects (as training does). Train on
   sample-days in `[refit − train_years, refit)`; refit QUARTERLY (first day of each quarter
   in the window). Use the same hyperparameters training.py uses for these classes.
3. XGB scoring in the SERVED regime (this is the point of the arm — do not score sample-day
   rows): for each forecast day D on the grid, call
   `training._build_forecast_candidates(frame_before_D, stations, uv_daily, D, full_frame=frame_before_D, advisories=..., min_sample_recency_days=None, precip_daily=..., streamflow_daily=..., hydrologic_links=...)`
   where `frame_before_D` = training frame rows with `sample_date < D`, then
   `build_inference_features(pd.concat([history, candidates]))` and keep the candidate rows
   (match how `_export_forecasts` extracts them, ~training.py:3532-3600), reindexed onto the
   fitted model's feature columns. Load the parquet inputs once, the way `_export_forecasts`
   does (~training.py:3525).
   **Leak check:** nothing dated ≥ D may enter features for D. Write a test that builds a
   tiny frame with a sample ON D and asserts the candidate's recency/lag features ignore it.
4. Cost control: before the full loop, time one D. If one D takes > 15 s, set the default
   grid for the XGB arms to every 7th day and score ALL arms on that same sub-grid in an
   extra slice named `xgb-grid`, so XGB is never compared to other arms on different pairs.
   Print the per-D time and the chosen grid in `results.json`.
5. Served-log check (plan 2.3 step 5): where `forecast_history.parquet` has `p_exceed_ml` for
   (beach, D), report the AUROC of the reconstructed `xgb_ensemble` vs the logged
   `p_exceed_ml` on those pairs, and their Pearson correlation.
6. Bootstrap: extend `cluster_bootstrap_delta` to also return the **within-beach AUROC** delta
   CI (PROMOTION.md needs it), and compute deltas of every arm vs `logit` (the served model)
   on slices `all` and `not San Diego`, same seed for every arm.
7. Slices: existing ones plus `culture`, `ddpcr` (by the beach's assay at D) and nothing else.
8. Outputs in `--out`: `results.json` (via `app.core.json_safe.dumps_strict`) and
   `predictions.parquet` with one column per arm (`p_<arm>`) + `beach_id, county, date,
   outcome, y, last_exceeds, assay`.
9. `backend/scripts/diff_comparisons.py --before DIR --after DIR --out docs/MODEL_COMPARISON_<day>.md`:
   per arm and slice (all, not San Diego, culture, ddpcr, wet, dry, new beaches): within-beach
   AUROC, AUROC, AUCPR, Brier, sensitivity at specificity 0.87, three ways — **common pairs**
   (beach, date, outcome) present in both, **full** (each run on its own), **new beaches only**
   (pairs in after whose beach has no pair in before) — plus the before→after delta of each
   metric with a beach-cluster bootstrap CI on common pairs; then the realized exceedance rate
   per risk band (Low < 0.20 ≤ Moderate < 0.30 ≤ High < 0.70 ≤ Very High) per arm; then a
   "PROMOTION.md verdict" section that applies the rule mechanically to the after/full table
   and prints PASS/FAIL per challenger with the deciding CIs.
10. Tests `backend/tests/test_compare_all_models.py`: synthetic frames (no real data) for
    `pooled`/`persistence` strictly-prior behaviour, the leak check in 3, the within-beach
    bootstrap delta (known answer: identical predictions → CI [0,0]), the PROMOTION verdict
    logic (a challenger with CI excluding 0 on both metrics and both slices → PASS; one slice
    failing → FAIL), and `diff_comparisons` common/new-beach splitting.

## Out of scope

- Changing any served/production code (`app/ml/training.py`, `lookup_serving.py`,
  `logit_challenger.py`, `models.py`, `two_tier.py`) — import and call only. If something
  you need is impossible without a change there, stop and ask under Open questions.
- Running the full 12-month comparison on real snapshots (PM does it). Do run a smoke on
  `../data/curated` with `--start 2026-08-01 --end 2026-08-31 --bootstrap 20`.

## Allowed files

- backend/scripts/compare_all_models.py
- backend/scripts/diff_comparisons.py
- backend/tests/test_compare_all_models.py

## Allowed packages

- none

## Acceptance

```bash
cd /Users/kylechoi/surf_health-p1/backend
.venv/bin/pytest -q tests/test_compare_all_models.py           # all pass
.venv/bin/pytest -q                                             # no new failures
.venv/bin/ruff check scripts tests                              # clean
.venv/bin/python scripts/compare_all_models.py --curated ../data/curated --start 2026-08-01 --end 2026-08-31 --bootstrap 20 --out /tmp/cam_smoke
# expect: results.json with all 7 arms on forward_1_3d "all" and "not San Diego"; logit arm reproduces the same-window numbers of compare_logit_challenger.py run with the same args (paste both)
.venv/bin/python scripts/diff_comparisons.py --before /tmp/cam_smoke --after /tmp/cam_smoke --out /tmp/cam_smoke/report.md
# expect: every before→after delta exactly 0, every challenger verdict printed
```

## Phases

### Phase 25
Deliverable: `compare_all_models.py` with arms pooled, persistence, lookup, logit, logit_method, the extended bootstrap and slices; tests for those; smoke run with `--arms pooled,persistence,lookup,logit,logit_method`.

### Phase 50
Deliverable: `xgb_ensemble` and `xgb_offset` arms with quarterly refit, served-regime scoring via `_build_forecast_candidates`, the leak-check test, cost control, served-log check.

### Phase 75
Deliverable: `diff_comparisons.py` with common/full/new-beach tables, band realized rates, PROMOTION verdict, and tests.

### Phase 100
Deliverable: all Acceptance commands pass, outputs pasted.

## Corrections

(appended by the PM; newest last; each entry dated)

### 2026-10-02 21:50 — before phase 25 (PM)

- **Do not read `../data/curated` in this task.** The PM is rebuilding it in the background
  while you work. Use the frozen snapshot
  `/Users/kylechoi/surf_health/data/snapshots/before-2026-10-02` for every smoke run (replace
  `../data/curated` in the Acceptance commands with that path). An "after" snapshot will appear
  at `/Users/kylechoi/surf_health/data/snapshots/after-2026-10-02`.
- Phase-1 code (`app/data/pipeline/sample_key.py` with `assay_kind`, `label_method` in
  `beach_day`) is in the working tree, uncommitted. The before snapshot has NO `label_method`
  column — that is the case the brief's derivation-from-observations fallback is for.
- Do not install packages; the venv is pinned to match the before/after runs.
