# Model Card: Shorelife `hist-gbm-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-13T18:31:53.005796+00:00
- **Deployment stage**: candidate_ready
- **Public release eligible**: true
- **Promotion blocker (latest)**: None

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.351
- **Brier**: 0.083
- **Log loss**: 0.286
- **Calibration slope**: 0.813

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.363
- **Brier**: 0.090
- **n_samples**: 1206

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.848
- **Brier**: 0.099

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.616
- **Spatial county persistence AUCPR**: 0.571

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): 0.553

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
