# Model Card: Shorelife `hist-gbm-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-17T06:06:04.412349+00:00
- **Deployment stage**: candidate_ready
- **Public release eligible**: true
- **Promotion blocker (latest)**: None

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.366
- **Brier**: 0.078
- **Log loss**: 0.273
- **Calibration slope**: 0.809

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: —
- **Brier**: —
- **n_samples**: 0

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.835
- **Brier**: 0.115

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.634
- **Spatial county persistence AUCPR**: 0.567

## Operational Agreement Check
Active advisories are decomposed into three pools by age. The overall agreement rate below is dominated by the stale pool (administrative postings the model is not designed to flag), so per-pool numbers are the honest model-quality signal.

- **Acute** (started ≤14 d, real outbreaks): 2 advised → agreement 1.000
- **Chronic** (15-365 d, geomean postings): agreement 0.308
- **Stale** (>365 d, admin zombies the model is not expected to flag): agreement 0.000

- **Active-advisory agreement rate** (legacy overall metric, dominated by stale pool): 0.387

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
