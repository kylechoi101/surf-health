# Model Card: Shorelife `stacked-ensemble-curated-v0`

## Deployment Status
This model card describes the production model named in `data/curated/system_health.json` as of 2026-04-29.
The current public web release is a daily forecast product covering 377 of 924 monitored stations
(40.8% coverage). Unsupported stations should show the latest official sample without a colored
forecast claim.

## Feature List & Biological Rationale
The production stack incorporates standard hydrologic covariates alongside marine-microbiology features:
- **UV Index / Solar Inactivation Index**: Enterococcus survival in the surf zone is highly sensitive to UV radiation. Extended sunny days increase bacterial die-off rates.
- **Shore-Normal Wind**: Onshore winds promote mixing and transport nearshore contaminants toward the beach face, especially critical following rain events or near coastal outfalls.
- **Pier / Estuary Proximity**: Features (`is_near_pier`, `is_near_estuary_mouth`) capture the localized shedding of bacteria from pilings (bird guano) and persistent coastal lagoon discharge.
- **Days Since Sunny**: Captures the compounding effect of multi-day overcast conditions where natural UV sterilization is suppressed.

## Spatial CV Protocol
To ensure the model generalizes across unobserved stretches of coastline, the current public artifact reports spatial holdout metrics from the daily pipeline:
- **County and Beach Holdouts**: Data is grouped by county and by beach to reduce spatial leakage from adjacent monitoring sites sharing similar weather and ocean patterns.
- **Current Snapshot Scope**: The 2026-04-29 `system_health.json` artifact records a quick spatial backtest. Historical full-validation runs may use more folds or random seeds, but those are not claimed for the current production snapshot unless the artifact records them.

### Current Production Snapshot (from `system_health.json`)
- **Production model**: `stacked-ensemble-curated-v0`
- **Spatial County AUCPR**: 0.367 (baseline persistence: 0.172)
- **Spatial County Brier Score**: 0.126
- **Spatial Beach AUCPR**: 0.347 (baseline persistence: 0.241)
- **Spatial Beach Brier Score**: 0.184
- **Validation protocol**: quick spatial backtest with county and beach holdouts recorded in the daily pipeline artifact

### Interpretation
- The current production model clears the persistence baseline, but absolute skill remains modest.
- This should be presented as decision support for a daily planning workflow, not as a safety clearance.
- Low-base-rate counties can still experience alert fatigue if thresholds are interpreted too aggressively.

## Known Failure Modes
- **Low Base-Rate Counties**: Counties with historically pristine water quality (very low advisory frequency) exhibit high variance in precision and are prone to false positives due to class imbalance.
- **No Nowcast Capability**: The current pipeline runs daily (batch forecast). It cannot react to intra-day sewage spills, sudden localized runoff, or real-time morning turbidity readings (unlike CDPH nowcast models).
- **Coverage Ceiling**: More than half of monitored stations still lack public model coverage, so neutral unsupported surfaces are part of the product, not an edge case.

## Ceiling Discussion
- **Searcy & Boehm 2021 Benchmark**: The theoretical ceiling for predicting binary culture-based enterococcus exceedances using environmental proxies is bounded. Inherent noise in grab-sample lab results (due to patchy bacterial clustering in the surf zone) means that moderate AUCPR values can still be near the practical ceiling for broad, non-site-specific models. Pushing materially beyond the current regime likely requires site-specific hierarchical modeling or real-time local sensor inputs (e.g., turbidity).
