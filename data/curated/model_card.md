# Model Card: Shorelife `hist-gbm-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-07T03:14:56.440572+00:00
- **Deployment stage**: candidate_ready
- **Public release eligible**: true
- **Promotion blocker (latest)**: None

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.382
- **Brier**: 0.086
- **Log loss**: 0.296
- **Calibration slope**: 0.853

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.330
- **Brier**: 0.097
- **n_samples**: 924

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.846
- **Brier**: 0.121

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.669
- **Spatial county persistence AUCPR**: 0.576

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): 0.171

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
