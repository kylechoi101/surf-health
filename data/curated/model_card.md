# Model Card: Shorelife `gbdt-marine-v1.4`

## Feature List & Biological Rationale
The model incorporates standard hydrologic covariates alongside new marine-microbiology features:
- **UV Index / Solar Inactivation Index**: Enterococcus survival in the surf zone is highly sensitive to UV radiation. Extended sunny days increase bacterial die-off rates.
- **Shore-Normal Wind**: Onshore winds promote mixing and transport nearshore contaminants toward the beach face, especially critical following rain events or near coastal outfalls.
- **Pier / Estuary Proximity**: Features (`is_near_pier`, `is_near_estuary_mouth`) capture the localized shedding of bacteria from pilings (bird guano) and persistent coastal lagoon discharge.
- **Days Since Sunny**: Captures the compounding effect of multi-day overcast conditions where natural UV sterilization is suppressed.

## Spatial CV Protocol
To ensure the model generalizes across unobserved stretches of coastline, we utilize a robust spatial cross-validation strategy:
- **County GroupKFold**: Data is grouped by county to prevent spatial leakage (e.g., adjacent beaches in the same county sharing identical weather/ocean patterns).
- **Multi-Seed Evaluation**: We employ 3 folds × 3 random seeds to generate stable, bootstrapped confidence intervals for all performance metrics.

## Known Failure Modes
- **Low Base-Rate Counties**: Counties with historically pristine water quality (very low advisory frequency) exhibit high variance in precision and are prone to false positives due to class imbalance.
- **No Nowcast Capability**: The current pipeline runs daily (batch forecast). It cannot react to intra-day sewage spills, sudden localized runoff, or real-time morning turbidity readings (unlike CDPH nowcast models).

## Ceiling Discussion
- **Searcy & Boehm 2021 Benchmark**: The theoretical ceiling for predicting binary culture-based enterococcus exceedances using environmental proxies is bounded. Inherent noise in grab-sample lab results (due to patchy bacterial clustering in the surf zone) means that an AUCPR ~0.55 (vs. a base rate of ~21%) is considered state-of-the-art for global, non-site-specific machine learning approaches. Pushing past this ceiling likely requires site-specific hierarchical modeling or real-time local sensor inputs (e.g., turbidity).