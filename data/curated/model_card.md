# Model Card: Shorelife `hist-gbm-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-08T15:09:44.590403+00:00
- **Deployment stage**: candidate_ready
- **Public release eligible**: true
- **Promotion blocker (latest)**: None

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.344
- **Brier**: 0.084
- **Log loss**: 0.289
- **Calibration slope**: 0.854

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.351
- **Brier**: 0.089
- **n_samples**: 1358

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.842
- **Brier**: 0.124

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.641
- **Spatial county persistence AUCPR**: 0.574

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): —

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
