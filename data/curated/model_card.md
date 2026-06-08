# Model Card: Shorelife `xgb-undersample-ensemble-curated-v0`

## Deployment Status
- **Generated at**: 2026-06-08T18:46:09.412993+00:00
- **Deployment stage**: research_prototype
- **Public release eligible**: false
- **Promotion blocker (latest)**: Spatial holdout metrics have not been run for this artifact.

## Headline Metrics (from `system_health.json`)

### Temporal (held-out time slice)
- **AUCPR**: 0.750
- **Brier**: 0.096
- **Log loss**: 0.321
- **Calibration slope**: 1.153

### Deployment (active stations only; recency-filtered roster)
- **AUCPR**: —
- **Brier**: —
- **n_samples**: 0

### Validation (calibration/training-time slice; not a public headline)
- **AUCPR**: 0.695
- **Brier**: 0.077

### Spatial (holdouts)
- **Spatial county AUCPR**: —
- **Spatial county persistence AUCPR**: —

## Operational Agreement Check
Active advisories are decomposed into three pools by age. The overall agreement rate below is dominated by the stale pool (administrative postings the model is not designed to flag), so per-pool numbers are the honest model-quality signal.

- **Acute** (started ≤14 d, real outbreaks): 10 advised → agreement 1.000
- **Chronic** (15-365 d, geomean postings): agreement —
- **Stale** (>365 d, admin zombies the model is not expected to flag): agreement 0.000

- **Active-advisory agreement rate** (legacy overall metric, dominated by stale pool): 0.923

## Notes
- Forecasts are decision support and are not official lab results.
- Active official advisories override displayed risk in consumer surfaces.
