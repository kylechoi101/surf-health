# Model Card: Shorelife `hist-gbm-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-09T14:36:47.446742+00:00
- **Deployment stage**: research_prototype
- **Public release eligible**: false
- **Promotion blocker (latest)**: Held-out county Brier score does not beat persistence.

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.337
- **Brier**: 0.080
- **Log loss**: 0.277
- **Calibration slope**: 0.824

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.349
- **Brier**: 0.087
- **n_samples**: 1326

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.848
- **Brier**: 0.122

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.572
- **Spatial county persistence AUCPR**: 0.573

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): —

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
