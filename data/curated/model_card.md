# Model Card: Shorelife `hist-gbm-persistence-blend-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-12T16:13:01.823676+00:00
- **Deployment stage**: candidate_ready
- **Public release eligible**: true
- **Promotion blocker (latest)**: None

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.353
- **Brier**: 0.079
- **Log loss**: 0.275
- **Calibration slope**: 0.857

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.367
- **Brier**: 0.088
- **n_samples**: 1300

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.859
- **Brier**: 0.101

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.707
- **Spatial county persistence AUCPR**: 0.573

## Operational Agreement Check
- **Active-advisory agreement rate** (model flags High band on advised beaches): 0.553

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
