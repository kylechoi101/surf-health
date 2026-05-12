# Model Card: Shorelife `hist-gbm-persistence-blend-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-12T19:10:22.996907+00:00
- **Deployment stage**: candidate_ready
- **Public release eligible**: true
- **Promotion blocker (latest)**: None

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.354
- **Brier**: 0.085
- **Log loss**: 0.293
- **Calibration slope**: 0.875

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.365
- **Brier**: 0.093
- **n_samples**: 1206

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.850
- **Brier**: 0.099

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.681
- **Spatial county persistence AUCPR**: 0.571

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): 0.553

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
