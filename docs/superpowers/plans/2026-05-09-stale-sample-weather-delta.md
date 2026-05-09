# Stale-Sample Weather Delta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a diagnostic no-bacteria weather-delta candidate for stale-sample cases, with explicit leakage checks, smoothed priors, capped deltas, and skeptical diagnostics.

**Architecture:** Put the model-specific helpers in a new focused `app/ml/weather_delta.py` module, then wire the candidate into spatial holdout evaluation in `app/ml/training.py`. Extend the diagnostic script to report prior baselines and stale-sample stratification before any serving/product path changes.

**Tech Stack:** Python, pandas, NumPy, scikit-learn histogram GBM, pytest, existing spatial diagnostics.

---

### Task 1: No-Bacteria Feature Policy

**Files:**
- Create: `backend/app/ml/weather_delta.py`
- Test: `backend/tests/test_weather_delta.py`

- [ ] **Step 1: Write the failing tests**

```python
import pandas as pd

from app.ml.weather_delta import select_no_bacteria_features


def test_select_no_bacteria_features_removes_bacteria_history_columns():
    features = pd.DataFrame(
        {
            "enterococcus_value_last_obs": [120.0],
            "days_since_enterococcus_value_obs": [12.0],
            "enterococcus_value_lag_7": [80.0],
            "enterococcus_geomean_42d_lagged": [55.0],
            "geomean_30d_exceeds_35_lagged": [1.0],
            "samples_in_geomean_30d_lagged": [5.0],
            "log_enterococcus": [2.0],
            "enterococcus_value": [100.0],
            "precip_mm_24h": [3.0],
            "wave_height_m_last_obs": [1.2],
            "coastal_x_km": [-1000.0],
        }
    )

    result = select_no_bacteria_features(features)

    assert list(result.columns) == ["precip_mm_24h", "wave_height_m_last_obs", "coastal_x_km"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk .venv/bin/pytest tests/test_weather_delta.py::test_select_no_bacteria_features_removes_bacteria_history_columns`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.ml.weather_delta'`.

- [ ] **Step 3: Implement the helper**

```python
from __future__ import annotations

import re

import pandas as pd


BACTERIA_HISTORY_PATTERNS = (
    re.compile(r"^enterococcus_value(?:_last_obs|_lag_\d+)?$"),
    re.compile(r"^days_since_enterococcus_value_obs$"),
    re.compile(r"^enterococcus_geomean_"),
    re.compile(r"^geomean_"),
    re.compile(r"^samples_in_geomean_"),
    re.compile(r"^log_enterococcus$"),
)


def is_bacteria_history_feature(column: str) -> bool:
    return any(pattern.search(column) for pattern in BACTERIA_HISTORY_PATTERNS)


def select_no_bacteria_features(features: pd.DataFrame) -> pd.DataFrame:
    keep_columns = [column for column in features.columns if not is_bacteria_history_feature(column)]
    return features.loc[:, keep_columns].copy()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk .venv/bin/pytest tests/test_weather_delta.py::test_select_no_bacteria_features_removes_bacteria_history_columns`

Expected: PASS.

### Task 2: Smoothed Prior and Capped Delta

**Files:**
- Modify: `backend/app/ml/weather_delta.py`
- Test: `backend/tests/test_weather_delta.py`

- [ ] **Step 1: Write failing tests**

```python
import numpy as np
import pandas as pd

from app.ml.weather_delta import (
    clip_weather_delta,
    fit_smoothed_rate_prior,
    select_delta_cap,
)


def test_smoothed_prior_shrinks_sparse_beaches_toward_county_and_global_rates():
    labels = np.array([1, 0, 0, 0, 1, 1], dtype=float)
    metadata = pd.DataFrame(
        {
            "beach_id": ["a", "a", "b", "c", "c", "c"],
            "county": ["x", "x", "x", "y", "y", "y"],
        }
    )

    prior = fit_smoothed_rate_prior(labels, metadata, np.array([0, 1, 2, 3, 4, 5]))
    predictions = prior.predict(
        pd.DataFrame({"beach_id": ["a", "b", "unknown"], "county": ["x", "x", "z"]})
    )

    assert predictions[0] > predictions[1]
    assert 0.0 < predictions[2] < 1.0
    assert abs(predictions[2] - labels.mean()) < 1e-9


def test_clip_weather_delta_limits_probability_adjustment():
    result = clip_weather_delta(
        np.array([0.9, 0.1, 0.4]),
        np.array([0.4, 0.6, 0.5]),
        max_delta=0.2,
    )

    assert np.allclose(result, np.array([0.6, 0.4, 0.4]))


def test_select_delta_cap_minimizes_validation_brier_conservatively():
    labels = np.array([1, 0], dtype=float)
    weather = np.array([0.9, 0.1], dtype=float)
    prior = np.array([0.5, 0.5], dtype=float)

    cap = select_delta_cap(labels, weather, prior, caps=[0.1, 0.2, 0.4])

    assert cap == 0.4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `rtk .venv/bin/pytest tests/test_weather_delta.py`

Expected: FAIL with import errors for the new helpers.

- [ ] **Step 3: Implement prior, delta, and cap selection**

Add `SmoothedRatePrior`, `fit_smoothed_rate_prior`, `clip_weather_delta`, and `select_delta_cap` to `backend/app/ml/weather_delta.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk .venv/bin/pytest tests/test_weather_delta.py`

Expected: PASS.

### Task 3: Spatial Holdout Candidate

**Files:**
- Modify: `backend/app/ml/training.py`
- Test: `backend/tests/test_training.py`

- [ ] **Step 1: Write failing tests**

Add assertions that default spatial backtests emit:

```python
assert "spatial_beach_hist_gbm_no_bacteria_weather_delta" in metrics
assert "spatial_county_hist_gbm_no_bacteria_weather_delta" in metrics
```

Add a direct fold test that monkeypatches `select_no_bacteria_features` and asserts excluded bacteria columns are not passed to the weather-only classifier.

- [ ] **Step 2: Run tests to verify they fail**

Run: `rtk .venv/bin/pytest tests/test_training.py::test_spatial_backtests_emit_beach_and_county_metrics`

Expected: FAIL because the new spatial candidate is not registered.

- [ ] **Step 3: Implement the candidate branch**

Register `hist_gbm_no_bacteria_weather_delta` as a spatial diagnostic model. In `_spatial_holdout_fold_result`, fit a GBM on no-bacteria features, calibrate raw weather probabilities on inner validation rows, fit a smoothed prior on inner training rows, tune `max_delta` on inner validation, tune blend weight against the prior, and return held-out probabilities.

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk .venv/bin/pytest tests/test_training.py tests/test_weather_delta.py`

Expected: PASS.

### Task 4: Skeptical Diagnostic Outputs

**Files:**
- Modify: `backend/app/ml/spatial_diagnostics.py`
- Modify: `backend/scripts/diagnose_spatial_brier.py`
- Test: `backend/tests/test_spatial_diagnostics.py`

- [ ] **Step 1: Write failing tests**

Add tests for:

```python
add_default_context_buckets(...)
```

creating `sample_recency_bucket` from `days_since_enterococcus_value_obs`, and a fail-closed summary helper that reports `eligible`, `route_beats_baseline`, and `failed_closed`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `rtk .venv/bin/pytest tests/test_spatial_diagnostics.py`

Expected: FAIL because the new staleness bucket/fallback summary does not exist.

- [ ] **Step 3: Implement diagnostics**

Add `sample_recency_bucket` in `add_default_context_buckets`. Add a small `fallback_audit` helper that compares model Brier to a configurable baseline column. Extend `diagnose_spatial_brier.py` to include `prior_probability` for all folds when possible and to emit staleness-slice CSVs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk .venv/bin/pytest tests/test_spatial_diagnostics.py`

Expected: PASS.

### Task 5: Run Real Diagnostics and Self-Skepticism Loop

**Files:**
- Modify docs only if observed results need to be recorded.

- [ ] **Step 1: Run the candidate diagnostic**

Run:

```bash
rtk .venv/bin/python scripts/diagnose_spatial_brier.py \
  --model hist_gbm_no_bacteria_weather_delta \
  --group-columns county beach_id \
  --training-window-days 365 \
  --max-county-groups 12 \
  --max-beach-groups 50 \
  --output-dir /tmp/surf-health-weather-delta-365
```

- [ ] **Step 2: Inspect skepticism outputs**

Read:

```bash
rtk read /tmp/surf-health-weather-delta-365/county_summary.md
rtk read /tmp/surf-health-weather-delta-365/beach_id_summary.md
rtk head -n 20 /tmp/surf-health-weather-delta-365/county_brier_deltas.csv
rtk head -n 20 /tmp/surf-health-weather-delta-365/beach_id_brier_deltas.csv
```

Expected: The report answers whether weather-delta improves or fails, not just whether it runs.

- [ ] **Step 3: Run verification**

Run:

```bash
rtk .venv/bin/ruff check app/ml/weather_delta.py app/ml/training.py app/ml/spatial_diagnostics.py scripts/diagnose_spatial_brier.py tests/test_weather_delta.py tests/test_training.py tests/test_spatial_diagnostics.py
rtk .venv/bin/pytest tests/test_weather_delta.py tests/test_training.py tests/test_spatial_diagnostics.py
rtk .venv/bin/pytest
```

Expected: touched-file ruff passes; backend pytest passes.

- [ ] **Step 4: Commit**

Run:

```bash
rtk git add backend/app/ml/weather_delta.py backend/app/ml/training.py backend/app/ml/spatial_diagnostics.py backend/scripts/diagnose_spatial_brier.py backend/tests/test_weather_delta.py backend/tests/test_training.py backend/tests/test_spatial_diagnostics.py
rtk git commit -m "Add stale-sample weather-delta diagnostic candidate"
```

### Skepticism Output Summary

- **County Level**: Model Brier: 0.2200, Persistence Brier: 0.1378. The weather-delta candidate is **worse** than persistence by +0.0822 globally. This is primarily driven by massive underprediction in San Diego (model mean 0.085 vs actual rate 0.591), which results in a +0.3406 Brier delta.
- **Beach Level**: Model Brier: 0.1458, Persistence Brier: 0.1990. The weather-delta candidate is **better** than persistence by -0.0532 globally.
- **Conclusion**: The weather-delta approach improves predictions at the fine-grained beach level, but fails catastrophically when generalized at the county level for San Diego due to extreme bias. The diagnostic skepticism loop validates that this approach has mixed results and cannot be blindly applied everywhere.
