# Model Card: Shorelife `hist-gbm-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-12T18:41:42.986460+00:00
- **Deployment stage**: candidate_ready
- **Public release eligible**: true
- **Promotion blocker (latest)**: None

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.344
- **Brier**: 0.086
- **Log loss**: 0.296
- **Calibration slope**: 0.816

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.355
- **Brier**: 0.094
- **n_samples**: 1206

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.848
- **Brier**: 0.099

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.642
- **Spatial county persistence AUCPR**: 0.571

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): 0.553

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
