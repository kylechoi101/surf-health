# Model Card: Shorelife `hist-gbm-persistence-blend-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-12T19:16:42.257266+00:00
- **Deployment stage**: candidate_ready
- **Public release eligible**: true
- **Promotion blocker (latest)**: None

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.360
- **Brier**: 0.084
- **Log loss**: 0.290
- **Calibration slope**: 0.876

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.371
- **Brier**: 0.092
- **n_samples**: 1206

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.839
- **Brier**: 0.103

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.700
- **Spatial county persistence AUCPR**: 0.572

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): 0.553

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
