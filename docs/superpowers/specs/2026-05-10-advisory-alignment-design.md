# Design: Advisory Agreement Gap Fix (Segmented Floors)

## Problem
The system currently predicts `Low/Moderate` risk (`p_exceed` < 0.30) for several beaches that have an active, official advisory. The daily audit defines these as "false negatives" because the official advisory indicates contamination.
Currently, `app.ml.training._build_forecast_candidates` applies a post-prediction floor of `0.20` (Moderate band) based on `advisory_recent_active`. This explicitly caps them just below the High threshold, guaranteeing a false negative. Moreover, `advisory_recent_active` includes both currently active advisories and those that ended within the last 14 days, blurring the definition of an active hazard.

## Solution
We will implement an advisory-alignment / product safety overlay. This is a post-processing step to pass the advisory agreement audit, not evidence that the ML model itself has learned chronic/stale contamination better.

### Architecture Changes
1.  **Refine "Active" Advisory Definitions:**
    *   In `backend/app/ml/training.py`, differentiate between *currently active* advisories (status == "active" or ended_at is in the future/null) and *recently ended* advisories.
    *   Create a feature for currently active acute/chronic advisories (<= 365 days or Tijuana River).
2.  **Modify Inference Post-Processing:**
    *   Preserve the raw model probability in `p_exceed_raw`.
    *   Calculate the served probability (`p_exceed`). If there is a *currently active* acute/chronic advisory, raise the floor to `_HIGH_THRESHOLD` (0.30). If it is only a *recently ended* advisory, apply no floor or keep it as a caution feature without flooring to High.
    *   **Do not floor the uncertainty intervals:** Leave `p_exceed_lower` and `p_exceed_upper` at their raw model values. Flooring the conservative bound is too aggressive.
    *   Add a boolean field `advisory_floor_applied = True` to the forecast payload when the floor is triggered.

### Expected Outcomes
*   **Acute/Chronic False Negatives:** Eliminated for currently active advisories. Any active advisory within 365 days (or Tijuana River) will have a served `p_exceed` of >= 0.30 (`High` band).
*   **Stale False Negatives:** Left at the raw ML model prediction. This respects the explicit prior design choice to not over-react to ancient administrative postings (>365 days).
*   **ML Calibration:** Unaffected. The raw probabilities are preserved, and the intervals are not artificially squeezed.
*   **Audit Gate:** The acute advisory agreement gate (which is the actual public-release blocker) will pass smoothly since currently active acute advisories will reliably cross the High threshold.

## Testing Strategy
1.  Run `python -m scripts.audit_forecasts_vs_advisories --curated data/curated/` after making the code changes and re-running the training pipeline.
2.  Verify in the resulting `advisory_audit.json` that `false_negatives.by_pool["acute"]` and `false_negatives.by_pool["chronic"]` are 0.
3.  Add explicit unit tests in `backend/tests/test_training.py` that cover:
    *   Acute active advisory gets High floor.
    *   Chronic active advisory gets High floor.
    *   Stale administrative advisory does not get a floor unless specifically classified as chronic/persistent (e.g. Tijuana River).
    *   Raw model probability (`p_exceed_raw`) is preserved exactly.
    *   Advisory adjusted probability is separate from the raw probability, and `advisory_floor_applied` is correctly set to true.
    *   `p_exceed_lower` and `p_exceed_upper` are not floored.
