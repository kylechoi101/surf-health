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

## Positive Persistence Guard Candidate

The next diagnostic candidate keeps the calibrated GBM's upside only where it is
allowed to improve on persistence. If the latest prior official sample exceeded
the STV threshold, the candidate preserves persistence at `1.0` instead of
letting the GBM dilute that recent warning. Otherwise it uses the existing capped
blend weight:

```text
if persistence == 1:
    p_final = 1.0
else:
    p_final = 0.60 * p_hist_gbm
```

This is intentionally conservative. It encodes the physics/math assumption that
recent confirmed exceedance is serially informative and should not be averaged
away by a global model, while still letting weather/context lift risk after a
non-exceeding prior sample.

The 365-day / 12-county / 50-beach diagnostic produced:

```text
model = hist_gbm_positive_persistence_guard

group     model_brier  persistence_brier  delta_vs_persistence  local result
county    0.126892     0.138799           -0.011907             12 wins / 0 ties / 0 worse
beach     0.159621     0.201470           -0.041849             46 wins / 4 ties / 0 worse
```

The four beach ties are all perfect-persistence groups with persistence Brier
equal to `0.0`, so strict improvement is mathematically impossible there. The
candidate is therefore the first current route that is no worse than persistence
for every tested county and beach group, while still improving aggregate Brier.

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

## 2026-05-16 — Persistence Guard Promotion Re-Assessment

Re-running `_promotion_assessment` against the latest `system_health.json` (post
advisory-cleanup retrain of 2026-05-14) on the persistence-guard variant
reveals the guard now **fails the spatial county calibration-slope floor**:

```text
Source: data/curated/system_health.json
Cleaned-data retrain, 365-day window, 30-county / 500-beach spatial limits

variant                                county_aucpr  county_brier  county_cal_slope  beach_aucpr  beach_brier   gates_clear
─────────────────────────────────────  ────────────  ────────────  ────────────────  ───────────  ────────────  ───────────
persistence (baseline)                 0.5705        0.1397        —                 0.7186       0.2025        —
hist_gbm                               0.6975        0.1218        1.151             0.8952       0.1089        ✅ all clear
hist_gbm_persistence_blend             0.7552        0.1020        0.843             0.8883       0.1270        ✅ all clear
hist_gbm_positive_persistence_guard    0.6551        0.1271        0.193             0.7750       0.1618        ❌ county cal_slope 0.193 < 0.4
hist_gbm_no_bacteria_weather_delta     0.1912        0.2212       −0.768             0.8188       0.1433        ❌ county AUCPR/Brier worse than persistence
```

Interpretation:

- The guard still beats persistence on both AUCPR and Brier at county + beach
  levels (consistent with the original 2026-05-08 finding above).
- **But** the cleaned-data retrain shrank the calibration slope on held-out
  counties from a previously-acceptable value to **0.193**, well below the
  `_promotion_assessment` floor of `0.4`. The guard's emitted probabilities are
  therefore untrustworthy on counties not seen in training — they're
  systematically under-confident and not safe to surface to users.
- The same retrain leaves `hist_gbm` and `hist_gbm_persistence_blend` clearing
  every gate (calibration slopes 1.151 and 0.843 respectively).
- The `no_bacteria_weather_delta` ablation remains catastrophic at the county
  level (negative calibration slope, well below persistence on AUCPR).

**Decision: keep `hist_gbm` as the production winner.** The blend variant has
marginally better spatial Brier on county holdouts (0.102 vs 0.122) and
qualifies as the preferred fallback if `hist_gbm` ever fails its gates. The
persistence guard cannot be promoted in its current form — its conservative
floor inflates the high-prevalence tail and depresses model variance enough to
collapse the calibration slope on held-out counties.

**Follow-up if we want to keep the guard idea**:

1. Move from a hard `p=1` floor when prior persistence is `1` to a soft floor
   (e.g. `max(p_hist_gbm, 0.7)`) that preserves model variance.
2. Recompute the spatial calibration slope after the softer guard — the
   AUCPR/Brier wins should mostly survive while restoring slope ≥ 0.4.
3. If a soft guard still fails, retire the guard route entirely; the blend has
   the same "fail closed on recent positive" effect at lower variance cost.

No serving change is required from this assessment: `hist_gbm` remains in
production via `production_model.json`.

## 2026-05-16 — SD Boundary Features Diagnostic vs Persistence Guard

Following implementation of the [San Diego boundary cohort
flags](../superpowers/plans/2026-05-10-san-diego-boundary-features.md) —
`transboundary_sewage_exposure_flag`, `south_swell_sensitive_flag`,
`dry_weather_contamination_zone_flag`, `engineered_runoff_protection_flag`,
`uv_treatment_protected_flag`, `lagoon_mouth_barrier_flag` and 4 physical
interaction terms — re-ran the 365-day / 12-county / 50-beach diagnostic
against the persistence guard:

```text
Run: 2026-05-16
Command: backend/.venv/bin/python scripts/diagnose_spatial_brier.py \
  --model hist_gbm_positive_persistence_guard \
  --group-columns county beach_id \
  --training-window-days 365 --max-county-groups 12 --max-beach-groups 50 \
  --output-dir /tmp/sd-boundary-guard-365

                          model       persistence    delta     this vs prior baseline
county      Brier        0.127138    0.139614       −0.0125   +0.0002 (essentially flat)
beach       Brier        0.160363    0.202661       −0.0423   +0.0007 (essentially flat)
blend       best alpha   1.00 (pure guard wins; no blending helps)
worst-group analysis     no county or beach group is worse than persistence
```

Prior baseline (pre-SD-boundary, recorded in plan §3): county Brier 0.126892,
beach Brier 0.159621.

**Verdict: features land as a standalone artifact, no production promotion.**

- The cohort flags + interactions are mathematically present in
  `_sd_boundary_features` (features.py) and pass 18 unit tests, but they do
  not move the spatial Brier needle on the persistence-guard wrapper. The
  guard's bottleneck is its calibration slope on held-out counties (0.193;
  see prior section), not the feature space.
- No group regression: every county and beach is no-worse than persistence
  under the augmented feature set. Safe to keep the flag columns active so
  future experiments (per-station or per-cohort heads, rerouting via
  hist_gbm directly instead of the guard wrapper) can inherit them.
- San Diego county itself: 5,624 rows, model Brier 0.1349 vs persistence
  0.1511, delta −0.0162. Improvement is real but small relative to the
  base-rate (0.585 positive rate at SD beaches — daily testing bias still
  dominates). Group A (Imperial/Coronado/Silver Strand) members all show
  0.0 / 0.0 Brier on holdout — they are perfect-persistence groups,
  mathematically unsavable by any model without breaking the persistence
  prior.
- The feature columns join `SD_BOUNDARY_FLAG_COLUMNS` and
  `SD_BOUNDARY_INTERACTION_COLUMNS` in features.py. They will be picked up
  automatically by the next training run.

**Next step if pursuing further**: route SD-cohort beaches to a county-
specific or per-station head that doesn't run through the guard's positive-
persistence floor. The boundary features are only meaningful when the model
is allowed to learn *off* the daily-positive autocorrelation; the guard
masks them.

## 2026-05-16 — LSTM Promotion Assessment

Trained the full candidate slate including `--model lstm` on cleaned data
(`--training-window-days 365 --spatial-beach-limit 500 --spatial-county-limit 30`).
Spatial backtests completed; metrics persisted to `system_health.json`.

`_promotion_assessment` called on the LSTM artifact:

```text
lstm:
  public_release_eligible: True
  deployment_stage: candidate_ready
  blockers: []
```

The county calibration-slope floor (≥ 0.4) clears with substantial margin:

```text
                       AUCPR    Brier    cal_slope    log_loss   prec@80recall
spatial_county_lstm    0.7348   0.1044   1.0747       0.3637     0.5815
spatial_beach_lstm     0.8227   0.0824   1.1412       0.2934     0.6763

(persistence baseline)
spatial_county_persistence  0.5667   0.1386   0.1151
spatial_beach_persistence   0.5682   0.1383   0.1154
```

**Heads-up comparison against the tree slate**:

| metric | hist_gbm | persistence_blend | guard | LSTM |
|---|---|---|---|---|
| county AUCPR | 0.6975 | 0.7552 | 0.6551 | **0.7348** |
| county Brier | 0.1218 | **0.1020** | 0.1271 | 0.1044 |
| county cal_slope | 1.151 | 0.843 | 0.193 ✗ | 1.075 |
| beach AUCPR | **0.8952** | 0.8883 | 0.7750 | 0.8227 |
| beach Brier | 0.1089 | 0.1270 | 0.1618 | **0.0824** |
| beach cal_slope | 0.709 | 0.577 | 0.179 ✗ | **1.141** |
| passes gates | ✓ | ✓ | ✗ | ✓ |

**LSTM is the strongest beach-level model in this slate** — it cuts spatial
beach Brier by 24% versus hist_gbm (0.0824 vs 0.1089) and is calibrated
nearly 1:1 on held-out beaches. At county level it sits between hist_gbm
and the blend on Brier, and improves the persistence-guard's failed
calibration slope from 0.19 → 1.07.

**Decision**: LSTM is recorded as a research candidate in `system_health.json`
(`research_models: ["lstm-curated-v0"]`) and would-be qualified for
production promotion, but is **not** swapped in this commit because:

1. `_two_stage_training_plan` deliberately keeps sequence models in
   `research_winner` slot — promoting LSTM to production_winner requires
   touching `PRODUCTION_MODEL_NAMES` and the serving pickle path (LSTM
   artifact is a torch checkpoint, not a sklearn estimator). Estimated
   half-day's plumbing work.
2. The current production winner (`hist_gbm`) already clears every gate,
   has a better beach AUCPR (0.895 vs 0.823), and ships via the existing
   sklearn pipeline. Swapping requires either co-deploying both
   architectures or carefully rerouting at the beach level (where LSTM
   wins) while keeping county-level decisions on the tree path.
3. LSTM's calibration slope marginally trails hist_gbm at the county
   level (1.075 vs 1.151) — both are excellent, but the tree path is
   slightly more conservative.

**Recommended follow-up** (separate ticket): wire LSTM into serving for
beach-level routing — at every beach where the model is confident, route
to LSTM (lower Brier); county-level fallbacks stay on hist_gbm. Treat
this as a per-beach router decision, similar to the existing
`hist_gbm_no_bacteria_weather_delta` route for stable beaches.

Until that ships, LSTM lives as `research_winner` and the daily forecast
remains `hist-gbm-curated-v0`.
