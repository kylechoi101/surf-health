# Model Card: Shorelife `hist-gbm-positive-persistence-guard-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-12T07:49:22.619246+00:00
- **Deployment stage**: research_prototype
- **Public release eligible**: false
- **Promotion blocker (latest)**: Spatial county calibration slope 0.194 is below 0.4. Probabilities are not trustworthy on held-out counties.

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.362
- **Brier**: 0.082
- **Log loss**: 0.284
- **Calibration slope**: 0.857

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.378
- **Brier**: 0.091
- **n_samples**: 1300

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.856
- **Brier**: 0.103

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.656
- **Spatial county persistence AUCPR**: 0.573

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): 0.596

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
