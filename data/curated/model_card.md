# Model Card: Shorelife `hist-gbm-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-13T20:12:18.086888+00:00
- **Deployment stage**: candidate_ready
- **Public release eligible**: true
- **Promotion blocker (latest)**: None

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.377
- **Brier**: 0.086
- **Log loss**: 0.297
- **Calibration slope**: 0.864

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.390
- **Brier**: 0.092
- **n_samples**: 1184

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.865
- **Brier**: 0.090

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.682
- **Spatial county persistence AUCPR**: 0.570

## Operational Agreement Check
Active advisories are decomposed into three pools by age. The overall agreement rate below is dominated by the stale pool (administrative postings the model is not designed to flag), so per-pool numbers are the honest model-quality signal.

- **Acute** (started ≤14 d, real outbreaks): 0 advised → agreement —
- **Chronic** (15-365 d, geomean postings): agreement 0.346
- **Stale** (>365 d, admin zombies the model is not expected to flag): agreement 0.000

- **Active-advisory agreement rate** (legacy overall metric, dominated by stale pool): 0.191

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
