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

## Stale-Sample Weather-Delta Diagnostic

The no-bacteria weather-delta route was implemented as a diagnostic candidate:

```text
model = hist_gbm_no_bacteria_weather_delta
excluded = enterococcus lags, last observation, geomean, and geomean flags
formula = smoothed prior + capped weather/ocean/hydrology/stormwater delta
```

The first 365-day / 12-county / 50-beach diagnostic is not sufficient to promote
the route:

```text
county persistence Brier                    = 0.137795
county hist_gbm_no_bacteria_weather_delta   = 0.220000
county delta vs persistence                 = +0.082206

beach persistence Brier                     = 0.199015
beach hist_gbm_no_bacteria_weather_delta    = 0.145808
beach delta vs persistence                  = -0.053207
```

The county failure is large enough to veto serving. San Diego is the worst
county failure:

```text
county      n     actual_rate  model_brier  persistence_brier  brier_delta  model_bias
San Diego   5765  0.5913       0.4908       0.1502             +0.3406      -0.5055
```

The staleness slice also shows a data limitation: in this held-out snapshot,
rows are mostly `fresh` with a small `recent` slice and no `stale`/`very_stale`
rows under the current bucket definitions. This means the diagnostic does not
yet answer the intended stale-latest-sample use case. Treat the current result
as a failed or inconclusive stale-route experiment, not as a product improvement.

## Stale Censoring Stress Test

The diagnostics now support artificial stale-sample censoring. For a cutoff such
as 30, 45, 60, or 90 days, direct bacteria-history inputs are hidden and
`days_since_enterococcus_value_obs` is forced to at least the cutoff. This creates
a stress set that asks how routes behave when recent biology is unavailable.

The current full stress run used:

```text
model = hist_gbm_persistence_blend
cutoffs = 30, 45, 60, 90 days
groups = 12 counties and 50 beaches
output = /tmp/surf-health-stale-blend-365-current
```

Headline results:

```text
variant       group     model_brier  persistence_brier  prior_brier  failed local groups
observed      county    0.106241     0.138799           0.219190     1 / 12 vs persistence
observed      beach     0.126562     0.201470           0.186936     6 / 50 vs persistence
censored_30d  county    0.218217     0.239217           0.219190     1 / 12 vs persistence
censored_30d  beach     0.205555     0.473897           0.186936     1 / 50 vs persistence
```

The censored 45/60/90-day runs currently match the 30-day run because the
censoring removes direct bacteria-history values and only varies the recency
counter. This reveals a modeling limitation: the current blend is not yet using
recency enough for different stale horizons to matter.

Interpretation:

- The observed calibrated blend remains the strongest current diagnostic path.
- Under censoring, the blend still beats the degenerate stale-persistence
  baseline, but that baseline is weak because direct last-observation bacteria is
  hidden.
- Against the smoothed prior, the censored blend is nearly tied at county level
  and worse at beach level. The censored beach route fails 21 of 50 local groups
  against the prior, so that is not enough to promote a stale-sample route.
- Local router tables are now required; aggregate success is not sufficient.
- Natural labeled stale rows were empty for 30/45/60/90-day cutoffs in the
  one-year holdout matrix because the maximum sample recency among labeled rows
  was 22 days. That means the current stale-sample problem is mostly a serving
  candidate-set and fallback-routing problem, not a labeled Brier subset in this
  snapshot.
- The serving stale-sample candidate builder found 277 beaches with at least 100
  historical samples, at least 10 positives, and a latest official sample at
  least 50 days stale as of 2026-05-09. None currently had a forecast row, which
  is exactly where a fail-closed prior/persistence route is needed.

## Serving Stale Prior Router

The serving stale-sample builder now emits a second file with fail-closed prior
routes:

```text
output = /tmp/surf-health-serving-stale-router
candidates = 277
forecast_available = 0
route_counts = beach_prior: 277
```

Because the stale candidate set is already filtered to beaches with at least 100
samples and 10 positives, every current candidate can use a smoothed beach prior.
This is intentionally not a model forecast. It is a historical baseline route
for beaches whose latest official sample is stale and whose current forecast row
is missing.

Prior-band distribution:

```text
Low        214
Moderate    32
High        26
Very High    5
```

Self-skeptical read: these prior bands identify historically risky stale beaches,
not current water quality. The route can support product honesty and triage, but
it should be presented as "historical baseline; latest sample stale" until the
system has fresh labels or a validated stale-sample model that beats the prior.

## Next Implementation Slice

1. Wire the serving stale prior route into the API/UI as a non-forecast status,
   not as a modeled forecast.
2. Make stale horizon matter by decaying or recomputing bacteria-history features
   instead of only zeroing them.
3. Add eligibility tables for beach-specific models: sample count, positive count, recency, validation Brier.
4. Add router evaluation that fails closed to persistence/prior when a beach/county route does not beat its local baseline.
5. Tune or learn alpha with nested spatial validation instead of relying on a fixed cap.
6. Keep public framing as beta decision support until the routed system passes aggregate and local validation checks.
