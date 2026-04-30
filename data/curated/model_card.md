# Model Card: Shorelife `hist-gbm-curated-v0`

## Deployment Status
This model card describes the production model named in `data/curated/system_health.json` as of 2026-04-30.
The current public web release is a daily forecast product covering 576 of 924 monitored stations
(62.3% coverage). Unsupported stations should show the latest official sample without a colored
forecast claim.

## Feature List & Biological Rationale
The production model now incorporates the explicit stormwater/outfall lane recommended in
`expert_data.txt`, alongside the existing hydrology, rainfall, marine weather, and site-history
features:
- **Storm Drain / Outfall Geometry**: San Diego Drain Structure and Drain Conveyance assets, Orange County MS4 outfall locations, Santa Monica discharge points, and CEDEN TMDL/WQIP receiving-water or outfall stations are linked to beaches by proximity. Features include nearest stormwater asset/outfall distance and counts within 0.5 km, 1 km, and 2 km.
- **Watershed / Receiving-Water Hotspot Proxies**: CEDEN TMDL/WQIP stations are converted into nearby stormwater receiving-water features, including TMDL bacteria and impaired-water proximity/count signals.
- **Low-Flow / Field-Screening Metadata**: Source metadata is normalized where present into low-flow diversion, field-verified, and impaired-water nearby-asset counts. In the current artifact those three count families are all zero, so the model cannot learn from them yet. Expert field-screening values such as pH, conductivity, clarity, and floatables remain future work because the local source export does not yet expose those fields consistently.
- **Explicit Rain Advisory Policy Thresholds**: The San Diego expert thresholds are encoded as 72-hour rain flags at 0.1 inch and 0.2 inch, while preserving the existing 6h/24h/48h/72h/7d precipitation features.
- **Distributed-Lag Hydrology**: Rainfall/runoff and streamflow signals now include constrained nonnegative lag kernels so short-term runoff shocks can be represented before considering a TCN research lane.
- **Existing Covariates**: Streamflow, gage distance, pour-point distance, hydrologic unit IDs, UV/solar, wind, tides, waves, pier/estuary proximity, recent advisory activity, and public observation fields remain in the feature set.
- **Hierarchical Probability Calibration**: The HistGBM probability output is calibrated with a county/site partial-pooling logit layer. Forecast exports include `p_exceed_lower` and `p_exceed_upper` uncertainty bands derived from that calibrator.

## Stormwater Source Coverage
The v1.6 stormwater pass ingested 138,840 normalized assets:
- City of San Diego Drain Structure: 71,724 features.
- City of San Diego Drain Conveyance: 64,232 normalized features.
- OC Public Works MS4 Outfall Locations: 2,460 normalized features.
- City of Santa Monica Storm Drain Discharge Points: 19 features.
- CEDEN TMDL / WQIP receiving-water and outfall stations: 405 normalized stations.

Los Angeles County storm drain GIS was identified as an official comparable source, but the available
download is a geodatabase ZIP and was not parsed into this pass.

## Spatial CV Protocol
To ensure the model generalizes across unobserved stretches of coastline, the current public artifact
reports spatial holdout metrics from the daily pipeline:
- **County and Beach Holdouts**: Data is grouped by county and by beach to reduce spatial leakage from adjacent monitoring sites sharing similar weather and ocean patterns.
- **Current Snapshot Scope**: The 2026-04-30 `system_health.json` artifact records the requested expanded spatial backtest using a 365-day training window, 50 beach holdouts, and 12 county holdouts.

### Current Production Snapshot (from `system_health.json`)
- **Production model**: `hist-gbm-curated-v0`
- **Test AUCPR**: 0.583
- **Test Brier Score**: 0.101
- **Test Log Loss**: 0.336
- **Test Calibration Slope**: 0.961
- **Test Precision at 80% Recall**: 0.288
- **Temporal Validation AUCPR**: 0.830
- **Temporal Validation Brier Score**: 0.128
- **Temporal Validation Log Loss**: 0.410
- **Temporal Validation Calibration Slope**: 0.807
- **Spatial County AUCPR**: 0.389 (baseline persistence: 0.227)
- **Spatial County Brier Score**: 0.163 (baseline persistence: 0.228)
- **Spatial County Log Loss**: 0.494
- **Spatial County Calibration Slope**: 0.687
- **Spatial County Precision at 80% Recall**: 0.372
- **Spatial County Holdout Scope**: 12 folds / 22,042 held-out rows / 22.7% positive rate.
- **Spatial Beach AUCPR**: 0.857 (baseline persistence: 0.433)
- **Spatial Beach Brier Score**: 0.129 (baseline persistence: 0.433)
- **Spatial Beach Log Loss**: 0.419
- **Spatial Beach Calibration Slope**: 0.934
- **Spatial Beach Precision at 80% Recall**: 0.783
- **Spatial Beach Holdout Scope**: 50 folds / 7,071 held-out rows / 43.3% positive rate.
- **Validation protocol**: 365-day training window plus requested county and beach spatial holdouts recorded in the daily pipeline artifact.

### Interpretation
- The current snapshot keeps `hist-gbm-curated-v0` as the production baseline after adding explicit stormwater/outfall features, distributed-lag hydrology, and hierarchical probability calibration.
- TCN remains a research-only direction. The current bottleneck is still spatial transfer, calibration, label noise, irregular sampling, and missing causal covariates rather than sequence model capacity.
- The model clears the persistence baseline in temporal and requested spatial checks, but it remains decision support for daily planning, not a safety clearance.
- Static stormwater geometry can improve spatial risk context, but sudden sewage spills, blockages, or same-day field observations still require official health-agency updates.

## Known Failure Modes
- **Incomplete Comparable-City Coverage**: San Diego, Orange County, Santa Monica, and CEDEN-derived TMDL/WQIP sources are represented. Other cities and counties may still rely on proxy features until their official storm drain/outfall GIS is parsed.
- **Remaining Spatial Transfer Risk**: The current artifact uses the requested expanded spatial strategy. A later all-beach/all-county uncapped ablation and a before/after stormwater spatial ablation would further reduce uncertainty.
- **Low Base-Rate Counties**: Counties with historically pristine water quality exhibit high variance in precision and are prone to false positives due to class imbalance.
- **No Nowcast Capability**: The current pipeline runs daily. It cannot react to intra-day sewage spills, sudden localized runoff, or real-time morning turbidity readings.
- **Field Notes Not Fully Structured**: Expert field-screening details since 2018 are recognized as high-value, but only normalized public observation fields and available low-flow/field-verification flags are incorporated in this pass.

## Ceiling Discussion
- **Searcy & Boehm 2021 Benchmark**: The theoretical ceiling for predicting binary culture-based enterococcus exceedances using environmental proxies is bounded. Inherent noise in grab-sample lab results means that moderate AUCPR values can still be near the practical ceiling for broad, non-site-specific models. Pushing materially beyond the current regime likely requires richer city-specific stormwater records, site-specific hierarchical modeling, or real-time local sensor inputs.
