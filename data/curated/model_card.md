# Model Card: Shorelife `xgb-undersample-ensemble-curated-v0`

## Deployment Status
- **Generated at**: 2026-09-01T20:31:23.262170+00:00
- **Deployment stage**: candidate_ready
- **Public release eligible**: true
- **Promotion blocker (latest)**: None

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.806
- **Brier**: 0.058
- **Log loss**: 0.205
- **Calibration slope**: 1.079

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: —
- **Brier**: —
- **n_samples**: 0

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.784
- **Brier**: 0.102

### Spatial (holdouts)
- **Spatial county AUCPR**: 0.726
- **Spatial county persistence AUCPR**: 0.502

## Operational Agreement Check
Active advisories are decomposed into three pools by age. The overall agreement rate below is dominated by the stale pool (administrative postings the model is not designed to flag), so per-pool numbers are the honest model-quality signal.

- **Acute** (started ≤14 d, real outbreaks): 0 advised → agreement —
- **Chronic** (15-365 d, geomean postings): agreement —
- **Stale** (>365 d, admin zombies the model is not expected to flag): agreement —

- **Active-advisory agreement rate** (legacy overall metric, dominated by stale pool): 1.000

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
