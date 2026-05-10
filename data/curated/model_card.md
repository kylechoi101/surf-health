# Model Card: Shorelife `hist-gbm-positive-persistence-guard-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-10T16:47:37.236275+00:00
- **Deployment stage**: candidate_ready
- **Public release eligible**: true
- **Promotion blocker (latest)**: None

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.247
- **Brier**: 0.130
- **Log loss**: 1.235
- **Calibration slope**: 0.108

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: —
- **Brier**: —
- **n_samples**: 0

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.627
- **Brier**: 0.172

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.655
- **Spatial county persistence AUCPR**: 0.574

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): 0.277

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
