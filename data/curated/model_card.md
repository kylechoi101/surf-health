# Model Card: Shorelife `hist-gbm-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-07T16:56:18.063495+00:00
- **Deployment stage**: research_prototype
- **Public release eligible**: false
- **Promotion blocker (latest)**: Held-out county Brier score does not beat persistence.

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.387
- **Brier**: 0.084
- **Log loss**: 0.284
- **Calibration slope**: 0.838

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.380
- **Brier**: 0.085
- **n_samples**: 1311

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.844
- **Brier**: 0.119

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.515
- **Spatial county persistence AUCPR**: 0.576

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): —

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
