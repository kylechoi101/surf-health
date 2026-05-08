# Spatial Brier and Data Strategy

Generated: 2026-05-08

## Current Findings

The previous checked-in model artifact says `hist_gbm` fails the public-release gate because county holdout Brier is worse than persistence:

```text
spatial_county_persistence.brier = 0.13779453345900095
spatial_county_hist_gbm.brier   = 0.14533630060851013
```

The new diagnostics found that this gate is not reproducible unless the histogram GBM seed is fixed. The baseline constructors now set `random_state=42` on both histogram GBM estimators.

With the seeded model and the same 365-day / 12-county spatial setup used by the daily workflow, the fresh county diagnostic is:

```text
spatial_county_persistence.brier = 0.13779453345900095
spatial_county_hist_gbm.brier   = 0.1254431338325134
```

That is better than persistence in aggregate, but it is not enough to treat the product as public-ready. San Diego is a major failure pocket:

```text
county      n     actual_rate  model_brier  persistence_brier  brier_delta  model_bias
San Diego   5765  0.5913       0.2508       0.1502             +0.1005      -0.3204
```

Interpretation: the model badly underpredicts San Diego risk on held-out county validation. Persistence is nearly perfectly calibrated there because the local base rate is high and stable. A public product cannot hide behind a statewide aggregate if one high-volume county is this miscalibrated.

The blend sweep is promising:

```text
best_alpha = 0.60
blend_brier = 0.101789
delta_vs_persistence = -0.036006
```

This supports the next modeling step:

```text
p_final = alpha * p_model + (1 - alpha) * p_persistence
```

But alpha should not be hard-coded globally without validation by county and beach. San Diego suggests we need group-aware calibration or routing.

The first implementation now adds a spatial diagnostic candidate:

```text
model = hist_gbm_persistence_blend
alpha = tuned on inner validation, capped at 0.60 model weight
```

With the same 365-day / 12-county diagnostic, the capped candidate produced:

```text
spatial_county_persistence.brier             = 0.13779453345900095
spatial_county_hist_gbm_persistence_blend    = 0.10183272788493031
delta_vs_persistence                         = -0.03596180557407064
aucpr                                        = 0.742673534891104
```

The San Diego failure pocket improves but does not disappear:

```text
county      n     actual_rate  model_brier  persistence_brier  brier_delta  model_bias
San Diego   5765  0.5913       0.1410       0.1502             -0.0093      -0.1600
```

Interpretation: conservative blending is the right direction for Brier, but the
remaining San Diego underprediction confirms that public readiness needs nested
spatial validation, local routing, and fallback rules before this candidate can
serve user-facing probabilities.

## Immediate Model Direction

Build a calibrated model router, not a more impressive single model.

Recommended route:

1. Official advisory override.
2. Beach-specific calibrated model if the beach has enough rows, enough positives, recent sampling, and beats persistence on validation.
3. County-specific calibrated model or blend if the county beats persistence.
4. Global calibrated blend.
5. Persistence fallback.
6. Insufficient-data status.

Every promoted route must beat persistence on its own validation group. If a beach or county model fails its local persistence baseline, it should not serve as the displayed probability source.

## Data Source Research

### Highest Priority

1. California BeachWatch / Safe to Swim open data
   - Source: California Open Data dataset for beach advisories, monitoring results, stations, beach details, and EPA spatial beach data.
   - Use: replace partial history, improve station metadata, advisory history, permanent postings, and coverage accounting.
   - Notes: the bacteria monitoring CSV is large; ingest through the data.ca.gov API or chunked CSV.
   - Links:
     - https://lab.data.ca.gov/dataset/beach-water-quality-postings-and-closures
     - https://catalog.data.gov/dataset/beach-advisories-postings-and-closures-and-beach-water-quality-monitoring

2. CIWQS sanitary sewer overflow data
   - Source: State Water Board CIWQS public reports and SSO flat files.
   - Use: spill proximity features, spill volume, spill category, responsible agency, upstream/downstream timing, beach closure explanation.
   - Notes: public reports are refreshed nightly; flat files are available but may require robust parsing.
   - Links:
     - https://www.waterboards.ca.gov/ciwqs/publicreports.html
     - https://waterboards.ca.gov/water_issues/programs/sso/

3. NOAA precipitation and hydrology
   - Source: NWPS/National Water Model APIs and Stage IV precipitation.
   - Use: watershed runoff, streamflow forecasts, antecedent wetness, catchment-level precipitation, and storm timing.
   - Notes: Stage IV gives quality-controlled gridded precipitation; NWPS/NWM gives current streamflow/NWM output but historical API coverage needs care.
   - Links:
     - https://water.noaa.gov/about/api
     - https://api.water.noaa.gov/about/nwm
     - https://api.water.noaa.gov/about/precipitation-data-access

### Ocean and Coastal Context

4. CDIP wave observations and modeled nearshore points
   - Source: CDIP THREDDS, Python API, realtime/archive NetCDF, and MOP alongshore modeled wave points.
   - Use: beach-local wave height, peak period, direction, nearshore transformation, sea surface temperature, wave-energy exposure.
   - Notes: this is probably better than nearest-buoy only because MOP alongshore points provide dense California-coast wave context.
   - Links:
     - https://cdip.ucsd.edu/m/documents/data_access.html
     - https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/realtime/latest_3day.nc.html

5. NOAA CO-OPS tides, water level, currents, water temperature, wind
   - Source: CO-OPS Data Retrieval API.
   - Use: tide phase, water level anomalies, wind, water temperature, coastal station observations.
   - Notes: API request length limits vary by product and interval; batch by station/date.
   - Link: https://api.tidesandcurrents.noaa.gov/api/uat/

6. NOAA NDBC buoy data
   - Source: NDBC historical and current buoy data.
   - Use: wind, wave, spectral wave, oceanographic observations, data gaps fallback.
   - Notes: historical files are gzipped by station/year; current and historical directories are stable enough for batch ingestion.
   - Links:
     - https://www.ndbc.noaa.gov/historical_data.shtml
     - https://www.ndbc.noaa.gov/data/historical/

### Gap Filling

7. Open-Meteo historical / forecast weather
   - Source: Open-Meteo historical weather and archived forecast APIs.
   - Use: fallback precipitation, wind, radiation, humidity, cloud cover, forecast-aligned features.
   - Notes: very easy operationally, but treat as fallback or comparison source behind official NOAA/CDIP/CO-OPS where available.
   - Links:
     - https://open-meteo.com/en/docs/historical-weather-api
     - https://open-meteo.com/en/docs/historical-forecast-api

## Heat Map / Multimodal Embedding Direction

Do not jump straight to image embeddings. First create structured gridded context features:

- precipitation field around the beach and watershed
- NWM runoff/streamflow field near pour points
- CDIP MOP nearshore wave field
- tide/water-level anomaly context
- wind vector and shore-normal wind field

Then render those fields into a weather-status heat map with a fixed legend only after the structured version is working. The image/embedding version should be treated as an experimental model candidate and must beat the structured-grid baseline on held-out county and held-out beach Brier before it influences serving.

## Next Implementation Slice

1. Add beach-level diagnostics for `hist_gbm_persistence_blend`.
2. Add eligibility tables for beach-specific models: sample count, positive count, recency, validation Brier.
3. Add router evaluation that fails closed to persistence when a beach/county route does not beat persistence.
4. Tune or learn alpha with nested spatial validation instead of relying on a fixed cap.
5. Keep public framing as beta decision support until the routed system passes aggregate and local validation checks.
