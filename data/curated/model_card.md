# Model Card: Shorelife `hist-gbm-curated-v0`

## Deployment Status
- **Generated at**: 2026-05-22T06:52:00.628507+00:00
- **Deployment stage**: candidate_ready
- **Public release eligible**: true
- **Promotion blocker (latest)**: None

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.374
- **Brier**: 0.074
- **Log loss**: 0.259
- **Calibration slope**: 0.863

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: 0.381
- **Brier**: 0.081
- **n_samples**: 1164

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.812
- **Brier**: 0.105

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.709
- **Spatial county persistence AUCPR**: 0.568

## Operational Agreement Check
Active advisories are decomposed into three pools by age. The overall agreement rate below is dominated by the stale pool (administrative postings the model is not designed to flag), so per-pool numbers are the honest model-quality signal.

- **Acute** (started ≤14 d, real outbreaks): 0 advised → agreement —
- **Chronic** (15-365 d, geomean postings): agreement —
- **Stale** (>365 d, admin zombies the model is not expected to flag): agreement —

- **Active-advisory agreement rate** (legacy overall metric, dominated by stale pool): 0.500

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
