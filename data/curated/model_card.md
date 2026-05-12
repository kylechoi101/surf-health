# Model Card: Shorelife `hist-gbm-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-12T15:13:09.742609+00:00
- **Deployment stage**: candidate_ready
- **Public release eligible**: true
- **Promotion blocker (latest)**: None

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.357
- **Brier**: 0.082
- **Log loss**: 0.284
- **Calibration slope**: 0.851

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.373
- **Brier**: 0.091
- **n_samples**: 1300

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.856
- **Brier**: 0.104

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.685
- **Spatial county persistence AUCPR**: 0.572

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): 0.553

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
