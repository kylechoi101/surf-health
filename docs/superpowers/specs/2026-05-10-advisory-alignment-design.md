# Design: Advisory Agreement Gap Fix (Segmented Floors)

## Problem
The ML model predicts `Low/Moderate` risk (p_exceed < 0.30) for several beaches that have an active, official advisory. The daily audit defines these as "false negatives."
Currently, `app.ml.training._build_forecast_candidates` applies a post-prediction floor of `0.20` (Moderate band) for recent/chronic advisories. This explicitly caps them just below the High threshold, guaranteeing a false negative.

## Solution
We will implement "Segmented Floors" to balance alignment with model purity.

### Architecture Changes
1.  **Modify Inference Post-Processing:**
    *   In `backend/app/ml/training.py`, update the logic that calculates `p_final` during candidate generation.
    *   Import `_HIGH_THRESHOLD` from `app.ml.calibration`.
    *   Change the floor for `advisory_recent` from `0.20` to `_HIGH_THRESHOLD` (0.30).
    *   `p_lower_final` will also be raised to `_HIGH_THRESHOLD` if `advisory_recent` is active.

### Expected Outcomes
*   **Acute/Chronic False Negatives:** Eliminated completely. Any advisory within 365 days (or Tijuana River) will force the model prediction to `High` (p_exceed >= 0.30).
*   **Stale False Negatives:** Left to the raw ML model prediction. This respects the explicit prior design choice to not over-react to ancient administrative postings (>365 days).
*   **Agreement Rate:** The overall agreement rate will spike above the `_MIN_ADVISORY_AGREEMENT_FOR_PUBLIC_RELEASE` threshold (0.50), allowing the pipeline to pass the gate.

## Testing Strategy
1.  Run `python -m scripts.audit_forecasts_vs_advisories --curated data/curated/` after making the code changes and re-running the training pipeline.
2.  Verify in the resulting `advisory_audit.json` that `false_negatives.by_pool["chronic"]` is 0.
3.  Ensure unit tests in `backend/tests/test_training.py` pass, specifically checking if any mock predictions test the `0.20` floor logic.
