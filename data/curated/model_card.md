# Model Card: Shorelife `hist-gbm-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-10T14:43:51.489087+00:00
- **Deployment stage**: research_prototype
- **Public release eligible**: false
- **Promotion blocker (latest)**: Held-out county Brier score does not beat persistence.

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.335
- **Brier**: 0.081
- **Log loss**: 0.283
- **Calibration slope**: 0.828

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.352
- **Brier**: 0.090
- **n_samples**: 1264

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.840
- **Brier**: 0.131

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.559
- **Spatial county persistence AUCPR**: 0.574

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): —

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
