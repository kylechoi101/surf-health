# Model Card: Shorelife `hist-gbm-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-07T04:11:27.910613+00:00
- **Deployment stage**: research_prototype
- **Public release eligible**: false
- **Promotion blocker (latest)**: Held-out county Brier score does not beat persistence.

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.357
- **Brier**: 0.088
- **Log loss**: 0.299
- **Calibration slope**: 0.789

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.293
- **Brier**: 0.099
- **n_samples**: 924

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.846
- **Brier**: 0.125

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.588
- **Spatial county persistence AUCPR**: 0.575

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): —

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
