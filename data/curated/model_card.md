# Model Card: Shorelife `hist-gbm-positive-persistence-guard-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-11T22:59:10.849261+00:00
- **Deployment stage**: candidate_ready
- **Public release eligible**: true
- **Promotion blocker (latest)**: None

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
- **Spatial county AUCPR**: 0.657
- **Spatial county persistence AUCPR**: 0.573

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): 0.596

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
