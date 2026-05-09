# Stale-Sample Weather Delta Design

Date: 2026-05-09

## Goal

Improve model reliability for beaches that have enough historical bacteria samples overall, but whose latest official bacteria sample is stale. Coverage is not the goal. The route must improve aggregate held-out county and beach Brier, and it must also beat the relevant local baseline before it is eligible.

## Non-Goals

- Do not use a weather-only model as a standalone public probability.
- Do not optimize for forecasting more beaches.
- Do not replace bacteria-history models when recent official bacteria data is available.
- Do not serve this route unless its validation gates pass.

## Core Idea

Use a no-bacteria model only as a capped adjustment around a smoothed local prior:

```text
p_prior = smoothed beach/county/season base rate
p_weather = no-bacteria model(weather + ocean + hydrology + stormwater + spatial + seasonality)
delta = p_weather - p_prior
p_gap_fill = p_prior + clipped(delta, -max_delta, +max_delta)
```

The model may say "recent runoff, plume transport, wind, waves, tide, or UV conditions move risk up/down from the prior." It may not claim to infer the hidden biological source state from weather alone.

## Feature Policy

The no-bacteria candidate must exclude direct bacteria-history features:

- `enterococcus_value_last_obs`
- `days_since_enterococcus_value_obs`
- `enterococcus_value_lag_*`
- `enterococcus_geomean_*`
- `geomean_*`
- `samples_in_geomean_*`
- `log_enterococcus`
- `enterococcus_value`

It may keep non-bacteria context:

- precipitation and hydrology
- streamflow and runoff kernels
- waves, wind, tide, salinity, water temperature, UV and solar features
- stormwater asset proximity/features
- spatial priors such as coastal coordinates, sensor availability, distances, and plume-zone indicators
- seasonality and sampling cadence features that do not encode bacteria values

## Eligibility

A beach can be evaluated for this stale-sample route only if:

- it passes the historical-sample threshold selected for beach-specific evaluation;
- it has enough positive examples for validation to be meaningful;
- the latest official bacteria sample is stale relative to the configured recency threshold;
- the no-bacteria weather-delta route beats the relevant prior or persistence baseline in validation.

If any condition fails, the route falls back to the prior/persistence baseline and should be reported as not eligible.

## Prior

The prior should be smoothed, not raw:

```text
p_prior = weighted_average(beach_rate, county_rate, statewide_or_seasonal_rate)
```

The beach rate gets more weight as sample count and positive count increase. Sparse beaches shrink toward county and statewide/seasonal rates. This avoids overconfident probabilities from small local histories.

## Delta Cap

The weather model output is converted into a bounded adjustment:

```text
delta = p_weather - p_prior
p_gap_fill = p_prior + clip(delta, -max_delta, +max_delta)
```

The cap is a safety device. It prevents weather covariates from inventing a large hidden-source change when current bacteria measurements are stale. `max_delta` should be tuned on validation and should have a conservative default.

## Validation Gates

The route must pass both aggregate and local gates:

```text
aggregate held-out county Brier: route < baseline
aggregate held-out beach Brier:  route < baseline
eligible county route Brier:     route < local baseline
eligible beach route Brier:      route < local baseline
```

AUCPR can be tracked as supporting evidence, but Brier is the promotion gate because the product depends on trustworthy probabilities.

## Self-Skepticism Loop

Every implementation and evaluation pass must include a "try to disprove it" loop:

1. **Ablation check:** Compare prior-only, persistence-only, no-bacteria raw model, capped weather-delta, bacteria-history model, and the existing calibrated blend.
2. **Leakage check:** Assert excluded bacteria columns are absent from the no-bacteria feature matrix.
3. **Local failure table:** Report worst counties and worst beaches by `route_brier - baseline_brier`.
4. **Staleness stratification:** Break results by days since latest official bacteria sample.
5. **Weather-condition stratification:** Break results by dry, light rain, storm, high waves, stale wave data, and advisory-like rain flags.
6. **Overconfidence check:** Report calibration bins and mean prediction vs actual rate.
7. **Fallback audit:** Count how many eligible routes fail closed to baseline.
8. **Promotion veto:** If one high-volume local group fails badly, do not treat aggregate success as release readiness.

This loop is part of the design, not an optional notebook exercise.

## Implementation Units

1. **Feature exclusion helper**
   - Produces a no-bacteria feature frame from the existing feature frame.
   - Owns the explicit exclusion list and tests it.

2. **Smoothed prior helper**
   - Computes beach/county/season priors using training rows only.
   - Returns prior probabilities for validation and held-out rows.

3. **Weather-delta candidate**
   - Fits a classifier on no-bacteria features.
   - Converts raw probabilities to capped deltas around the prior.
   - Tunes `max_delta` and blend weight on inner validation.

4. **Spatial diagnostics**
   - Adds this candidate to diagnostics without making it a production serving route.
   - Emits aggregate, county, beach, staleness, weather-slice, calibration, and fallback tables.

5. **Router evaluation**
   - Evaluates the route only for stale-sample beach/date rows.
   - Fails closed to the baseline when local validation gates do not pass.

## Testing

Tests should cover:

- bacteria-history columns are excluded;
- no-bacteria feature selection keeps weather/spatial/stormwater columns;
- smoothed priors shrink sparse beaches toward county/state rates;
- weather delta is clipped to the configured cap;
- local route fails closed when Brier does not beat baseline;
- diagnostics include aggregate and local Brier comparisons;
- stale-sample rows are routed differently from fresh-sample rows.

## Success Criteria

The first implementation is successful if it produces a reproducible diagnostic report answering:

- Does capped weather-delta beat prior/persistence for stale-sample rows?
- Which counties and beaches fail?
- Does it improve aggregate held-out county and beach Brier?
- Does it avoid severe local regressions?
- How often does it fail closed?

It is not successful merely because it forecasts more rows.
