# Model Card: Shorelife `hist-gbm-positive-persistence-guard-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-10T17:36:03.067407+00:00
- **Deployment stage**: research_prototype
- **Public release eligible**: false
- **Promotion blocker (latest)**: Spatial holdout metrics have not been run for this artifact.

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: —
- **Brier**: —
- **Log loss**: —
- **Calibration slope**: —

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: —
- **Brier**: —
- **n_samples**: 0

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: —
- **Brier**: —

### Spatial (holdouts)
- **Spatial county AUCPR**: —
- **Spatial county persistence AUCPR**: —

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): 0.277

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
