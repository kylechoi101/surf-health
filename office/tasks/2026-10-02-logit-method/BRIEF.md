---
task: logit-method
repo: /Users/kylechoi/surf_health-p3
worker: claude
created: 2026-10-02
status: open
---

## Goal

UPDATE_PLAN step 2.6. `backend/app/ml/PROMOTION.md` applied to the 2026-10-02 comparison
(`docs/MODEL_COMPARISON_2026-10-02.md`) promoted `logit_method`: the served logistic plus a
`ddpcr` indicator and its interaction with `R`. Adopt it into the served model. Work on branch
`feat/logit-method` in `/Users/kylechoi/surf_health-p3` (cut from `main`). Read CLAUDE.md's
"serve the logistic model" section first, especially "The lookup is computed twice".

## In scope

1. `backend/app/ml/logit_challenger.py`:
   - `FEATURE_COLUMNS = ("R", "RF", "W", "S", "ddpcr", "R_ddpcr")`.
   - `build_features` / `lab_history_features` add `ddpcr` = 1.0 when the beach's most recent
     `beach_day.label_method` strictly before D is `"ddpcr"` (else 0.0; no prior label → 0.0),
     and `R_ddpcr = R * ddpcr`. Strictly-prior exactly as `compare_all_models.compute_assays`
     does (reuse its logic; if you move it into `app/ml/`, make the script import it).
     If `beach_day` has no `label_method` column, fall back to deriving it from
     `observations.parquet` with `app.data.pipeline.sample_key.assay_kind` on the worst sample
     of each beach-day (same as `compare_all_models.derive_label_method_from_observations`).
   - `LOGIT_CHALLENGER_VERSION = "logit-lookup-offset-v2"`. Find every place the v1 string or
     the served-estimate version set is used (`SERVED_ESTIMATE_VERSIONS`, `served_metrics`,
     `scripts/verify_served_estimate.py`, tests) and make v2 the served version while keeping v1
     recognised as a past served version in the history/live scoreboard.
2. The existing guards stay and apply to the new coefficients (±3 bound, ≥ 20k rows, rain
   coverage, lookup-term agreement). `system_health.json["serving_method"]["logit"]` records the
   two new coefficients.
3. Tests: strictly-prior assay (a ddPCR sample ON D does not flip `ddpcr` for D); fit/predict
   round-trip with the new columns; serving end to end on a fixture with one ddPCR beach and one
   culture beach (`ddpcr` 1/0, `R_ddpcr` = R·ddpcr); v2 is the served version and v1 rows are
   still scored by the live scoreboard.
4. `CLAUDE.md`: update the logistic section — v2, the two features, and that adoption came from
   `PROMOTION.md` on the 2026-10-02 comparison (effect: within-beach AUROC +0.003..+0.007,
   Brier −0.0001..−0.0006, all and non-SD slices).

## Out of scope

- Any change to the lookup, floors, bands, XGB, or the comparison harness beyond an import.
- Running the production workflow.

## Allowed files

- backend/app/ml/logit_challenger.py
- backend/app/ml/lookup_serving.py
- backend/app/ml/served_metrics.py
- backend/app/ml/assay.py (new, if you move the strictly-prior assay logic)
- backend/scripts/compare_all_models.py (import change only)
- backend/scripts/compare_logit_challenger.py (only if it must follow the new feature set)
- backend/scripts/verify_served_estimate.py
- backend/tests/**
- CLAUDE.md

## Allowed packages

- none

## Acceptance

```bash
cd /Users/kylechoi/surf_health-p3/backend
.venv/bin/pytest -q                                  # no new failures
.venv/bin/ruff check app tests scripts               # clean
rm -rf /tmp/lm && cp -r /Users/kylechoi/surf_health/data/snapshots/after-2026-10-02 /tmp/lm
.venv/bin/python -m app.ml.lookup_serving --curated /tmp/lm/   # serves logit-lookup-offset-v2, fallback_reason null
.venv/bin/python scripts/validate_forecast.py --curated /tmp/lm/ --previous /Users/kylechoi/surf_health/data/snapshots/after-2026-10-02/forecasts.parquet   # PASS
# report: the fitted coefficients incl. ddpcr / R_ddpcr, mean served p vs v1 on this snapshot,
# and band changes vs v1 by county (expect changes concentrated in San Diego)
```

## Phases

### Phase 25
Deliverable: strictly-prior `ddpcr` / `R_ddpcr` features in `build_features` / `lab_history_features`, with tests.

### Phase 50
Deliverable: v2 version wiring across serving, scoreboard and verify script; guards apply; health records the new coefficients.

### Phase 75
Deliverable: end-to-end fixture test and the acceptance run on the after snapshot with the band-change report.

### Phase 100
Deliverable: CLAUDE.md updated; all Acceptance commands pass with output pasted.

## Corrections

(appended by the PM; newest last; each entry dated)
