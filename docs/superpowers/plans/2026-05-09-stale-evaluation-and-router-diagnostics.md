# Stale Evaluation and Router Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stale-sample censoring evaluation set first, then add local router diagnostics for the calibrated blend, while collecting current source metadata for the next data-ingest step.

**Architecture:** Add focused diagnostic helpers in `app/ml/stale_evaluation.py` so stale/censored rows can be tested independently from the production serving path. Extend the spatial diagnostics script to emit local pass/fail router tables for existing prediction CSVs and record official source metadata in a small research document.

**Tech Stack:** Python, pandas, NumPy, existing spatial diagnostics, pytest, official open-data metadata endpoints.

---

### Task 1: Stale-Row Censoring Helpers

**Files:**
- Create: `backend/app/ml/stale_evaluation.py`
- Create/Modify: `backend/tests/test_stale_evaluation.py`

- [x] Write failing tests for censoring bacteria-history columns when `days_since_enterococcus_value_obs` exceeds a cutoff.
- [x] Implement helpers that produce stale/censored feature frames and select naturally stale rows.
- [x] Verify tests pass.

### Task 2: Stale Stress-Test CLI Path

**Files:**
- Modify: `backend/scripts/diagnose_spatial_brier.py`
- Modify: `backend/tests/test_spatial_diagnostics.py` or `backend/tests/test_stale_evaluation.py`

- [x] Add tests for cutoff labels such as `censored_30d`, `censored_45d`, `censored_60d`, `censored_90d`.
- [x] Add CLI args to emit stale/censored slice outputs without changing production training.
- [x] Verify targeted tests pass.

### Task 3: Local Router Diagnostics for Calibrated Blend

**Files:**
- Modify: `backend/app/ml/spatial_diagnostics.py`
- Modify: `backend/scripts/diagnose_spatial_brier.py`
- Modify: `backend/tests/test_spatial_diagnostics.py`

- [x] Add tests for local pass/fail tables: county/beach, n, model_brier, baseline_brier, delta, route_eligible.
- [x] Implement helper that marks local route eligibility only when model Brier beats baseline.
- [x] Emit router tables for `hist_gbm_persistence_blend` diagnostic runs.

### Task 4: Official Data Metadata Pull

**Files:**
- Create/Modify: `docs/modeling/data_source_inventory.md`
- Optionally create small metadata snapshots under `data/source_metadata/`.

- [x] Fetch current metadata for California BeachWatch/Safe to Swim, CIWQS, NOAA water APIs, CDIP, CO-OPS, NDBC, and Open-Meteo.
- [x] Record URLs, update cadence, available formats, likely connector strategy, and immediate ingest priority.
- [x] Do not ingest large data files in this slice unless an endpoint exposes a small schema/metadata JSON.

### Task 5: Verification and Commit

**Files:**
- All touched code/tests/docs.

- [x] Run touched-file ruff.
- [x] Run targeted tests.
- [x] Run full backend pytest.
- [x] Run a real diagnostic for `hist_gbm_persistence_blend` and the stale/censored outputs.
- [x] Commit the implementation and docs.
