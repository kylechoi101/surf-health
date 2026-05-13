# Model Card: Shorelife `hist-gbm-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-13T03:07:11.786478+00:00
- **Deployment stage**: candidate_ready
- **Public release eligible**: true
- **Promotion blocker (latest)**: None

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.368
- **Brier**: 0.083
- **Log loss**: 0.285
- **Calibration slope**: 0.903

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.379
- **Brier**: 0.090
- **n_samples**: 1206

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.844
- **Brier**: 0.101

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.664
- **Spatial county persistence AUCPR**: 0.572

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): 0.553

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
