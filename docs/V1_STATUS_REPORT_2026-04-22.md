# Surf Health

> **ARCHIVED — historical snapshot.** This document captures the project state
> on 2026-04-22. As of 2026-05-12 the model gate has flipped to
> `public_release_eligible: true` (production winner: `hist-gbm-curated-v0`,
> spatial county AUCPR 0.637 vs persistence 0.569, slope 1.159 ≥ 0.4). For the
> current state see `data/curated/model_card.md` and the live
> `/system/health` endpoint.

## Development Status Report and V1 Vision

Date: April 22, 2026

## Executive Summary

Surf Health is a California marine beach health forecast platform designed to estimate daily bacteria risk between official sampling days. The product vision is a public-facing beach decision tool for surfers and beachgoers, paired with a research and operations view for environmental agencies and marine scientists.

The current codebase is a strong research prototype. It includes a working ingestion pipeline, curated Parquet data warehouse, causal feature engineering stack, multiple model baselines, a research neural-network track, a FastAPI backend, and a Next.js web product. The system can ingest California marine monitoring data, enrich it with selected ocean and weather covariates, train models locally, export forecast snapshots, and serve those results through an API and website.

The most important current conclusion is that the platform is not yet a statistically trustworthy statewide public forecast system. After removing leakage and enforcing more honest blocked and spatial evaluations, the best current production candidate is a plain logistic baseline, not the neural network and not the more complex grouped or clustered variants. The system currently performs credibly on blocked-time and held-out beach evaluation, but it does not generalize well enough across held-out counties to justify public statewide release.

As of April 22, 2026, the project should be treated as a research prototype with a clear path to V1, not a finished consumer health product.

## Product Vision for V1

V1 should be a California-focused web platform with a daily public health-risk forecast for marine beaches, backed by a transparent research-grade methodology and clear uncertainty communication.

Core V1 product goals:

- Help surfers and beachgoers make better daily decisions than weather and swell alone.
- Help environmental agencies and marine scientists prioritize field effort between sample days.
- Translate sparse official bacteria measurements into a prospective daily exceedance-risk estimate.
- Present official measurements, forecast probabilities, and uncertainty clearly enough that users understand the difference.
- Preserve a strict boundary between official sampled facts and model-generated estimates.

User-facing V1 scope:

- California statewide beach explorer
- Beach detail pages
- Daily risk band and probability of exceedance
- Recent official sample history
- Surf and environmental context such as wave and salinity when available
- Methodology and model limitations page
- Research and operator dashboard for model registry, source freshness, and validation status

Out of scope for V1:

- Public statewide launch without stronger spatial generalization
- Expo mobile app as a first release
- Ad monetization
- Neural-network-first production deployment

## Problem Statement

Official marine bacteria sampling is sparse. Many beaches are sampled approximately weekly or on a limited monthly cadence, while actual exposure decisions happen daily. Surfers and beachgoers often choose where to go using swell, weather, and convenience, but they rarely have an actionable estimate of water-health risk between official sample days.

From an operations perspective, environmental staff and marine biologists spend real field effort collecting and checking these samples. A mathematically defensible forecast or nowcast can help prioritize labor, identify persistent high-risk patterns, and create a real applied use case for public and operational decision support.

## Current System Overview

### Data Layer

Implemented data sources and curated assets:

- California BeachWatch monitoring data
- Safe to Swim and CEDEN-linked marine enterococcus merge path
- CDIP ocean context
- CeNCOOS and ERDDAP-derived environmental context
- EPA UV
- curated station metadata and sensor distance fields

Curated data status on April 22, 2026:

- `beaches.parquet`: 291 beaches across 11 counties
- `beach_day.parquet`: 58,734 beach-day rows
- `observations.parquet`: 59,961 official observations
- `advisories.parquet`: 18,777 advisory rows
- `forecasts.parquet`: 257 forecast rows in the latest dated export

Current warehouse characteristics:

- v1 label target is culture-based marine enterococcus exceedance only
- non-target bacteria streams are preserved separately and not pooled into the v1 target
- implausible pre-2000 training rows are filtered from training
- official BeachWatch rows are preferred over mirrored Safe-to-Swim duplicates

### Feature Engineering

The feature pipeline is intentionally causal for forecasting.

Implemented feature behavior:

- 30-day sliding history window
- exact lags at 1, 2, 3, 7, 14, 21, and 28 days
- rolling antecedent statistics
- seasonality features
- beach metadata joins
- current-day label leakage removed
- current-day observed exogenous covariates excluded from the forecast feature set
- conformal-style prediction intervals for density regression output instead of fake quantiles

Important modeling rule:

- Supervision happens only on observed sample days.
- Daily forecasts are generated prospectively by constructing an unlabeled forecast-day row using prior available history.

### Modeling Stack

Implemented model families:

- persistence baseline
- logistic classification baseline
- histogram gradient boosting classifier
- elastic net regression baseline
- histogram gradient boosting regressor
- TCN sequence model as research-only neural track
- county and region fallback logistic variants
- K-Means coastal-cell logistic experiment

Current modeling position:

- the plain logistic classifier is the best current statewide model
- the TCN remains research-only
- grouped county and region fallbacks do not improve statewide performance
- unsupervised coastal-cell clustering does not improve statewide performance

### Backend and API

Implemented backend capabilities:

- FastAPI service
- forecast, beach, observations, and system health endpoints
- curated repository fallback logic
- forecast explanation integration via Ollama for narrative summaries
- model registry and validation metadata surfaced through the API

Public API shape already exists for:

- `GET /beaches`
- `GET /beaches/:id/forecast?date=`
- `GET /beaches/:id/observations`
- `GET /system/health`

### Web Product

Implemented web capabilities:

- California landing page
- statewide beach explorer
- beach detail views backed by the API
- methodology page
- research and operations dashboard
- display of model registry, blockers, and spatial metrics

The web app is useful today as a product prototype and internal research interface.

### Testing and Reliability

Current backend test status:

- `34` backend tests passed after the latest coastal-cell work

Covered areas include:

- causal forecasting behavior
- blocked date splitting
- feature generation
- conformal interval width logic
- hierarchical fallback logic
- coastal-cell fallback logic
- spatial backtest metric emission
- promotion blocker logic

## Current Empirical Status

### Official Model Registry Status

Registry status on April 22, 2026:

- production model artifact: `logistic-curated-v0`
- deployment stage: `research_prototype`
- public release eligible: `false`
- current blocker: held-out county AUCPR does not beat persistence

### Current Best Model

Current statewide winner:

- `logistic`

Blocked-time validation:

- validation AUCPR: `0.6278`
- validation Brier: `0.2141`

Blocked-time test:

- test AUCPR: `0.5604`
- test Brier: `0.1928`

These numbers are materially lower than the earlier near-perfect scores because the earlier pipeline had information leakage and a mismatch between training-time and forecast-time covariates. Those issues have been corrected.

### Spatial Generalization

Held-out beach results:

- persistence AUCPR: `0.6245`, Brier: `0.2726`
- logistic AUCPR: `0.6776`, Brier: `0.2056`

Held-out county results:

- persistence AUCPR: `0.4691`, Brier: `0.2492`
- logistic AUCPR: `0.3802`, Brier: `0.2486`

Interpretation:

- the logistic model beats persistence on held-out beaches
- the logistic model does not beat persistence on held-out counties
- county-to-county transfer is the main scientific weakness in the current system

### Experimental Model Outcomes

Neural track:

- the TCN is not production-ready
- it underperforms the logistic baseline
- its regression head still shows unstable RMSE behavior

Hierarchical county and region fallback:

- underperforms plain logistic on blocked and spatial metrics
- does not solve county transfer

Coastal-cell clustering experiment:

- K-Means cells based on beach geometry, sensor distances, and circular wave direction were implemented and tested
- beach holdout remained close to logistic but still worse
- county holdout became worse than plain logistic
- conclusion: better static grouping alone is not the missing ingredient

## What We Learned

### 1. Leakage Was the Biggest Early Illusion

The project initially appeared much closer to deployment than it really was. Once same-day leakage and forecast-time feature mismatch were removed, model scores dropped sharply. This was a healthy correction. The current numbers are lower, but they are much more trustworthy.

### 2. Simpler Baselines Are Winning for Good Reasons

The logistic baseline is currently the strongest statewide classifier because the current feature set is noisy, sparse, and still missing key physical drivers. Under these conditions, stronger regularization is helping more than extra model complexity.

### 3. The Main Bottleneck Is Missing Causal Covariates

The county wall suggests the system still lacks the physical drivers that would generalize across regions:

- rainfall timing and antecedent wetness
- stormwater and outfall influence
- watershed and drainage context
- creek and rivermouth influence
- stronger tide, wind, and nearshore transport context

### 4. Spatial Grouping Alone Does Not Solve the Problem

Political grouping was not sufficient, but oceanographic clustering was not sufficient either. The limiting factor is not just how beaches are grouped. The limiting factor is what explanatory data the model has available before forecast issuance.

## Current Readiness Assessment

There are really two readiness questions:

Engineering readiness:

- high
- the platform infrastructure is real and working
- the codebase is capable of ingesting data, training models, exporting forecasts, and serving a product

Scientific and public-release readiness:

- not yet sufficient
- the system is still best described as a research prototype
- statewide public release would overstate the current evidence

Practical readiness estimate:

- research prototype and internal demo platform: near-complete
- scientifically defensible statewide public V1: incomplete

## Vision for a Defensible V1

A real V1 should not be defined as "the current prototype with nicer branding." It should be defined as the first release that is honest, operationally useful, and scientifically defensible for a limited but real use case.

The strongest V1 definition is:

- web-first product
- California marine beaches
- daily prospective risk forecasts
- official sample overlays
- clear uncertainty language
- explicit research-prototype labeling unless spatial gates are met
- pilot-ready for agencies and collaborators

The strongest honest release strategy is probably not a blanket statewide public launch. It is one of these:

- limited pilot release in a small number of beaches or regions
- agency or research partner pilot
- public beta only after improved spatial generalization

## Recommended Path to V1

### Phase 1: Physical Driver Ingestion

Highest-priority additions:

- rainfall and antecedent wetness
- storm drain and outfall proximity and discharge proxies
- watershed and drainage-basin linkage
- creek and rivermouth proximity
- stronger tide and wind transport context
- local runoff and hydrologic context from agencies where possible

This is the most important next step. It is more important than another neural-network round.

### Phase 2: Regional and Operational Validation

Once stronger causal covariates exist:

- retrain the logistic baseline
- rerun blocked and spatial evaluations
- compare statewide and pilot-region performance
- define region-specific or pilot-specific release criteria if needed
- consider a same-day nowcast product separately from a 5:00 AM forecast product

### Phase 3: Release Hardening

Before a public V1:

- make spatial holdouts a hard promotion gate
- improve stale-data and unsupported-site handling
- tighten methodology wording and uncertainty messaging
- finalize operational schedules for daily forecast refresh and source freshness checks
- document release boundaries clearly in product copy

## Recommended Product Strategy

Short-term product strategy:

- continue developing the web platform as the main V1 surface
- keep the research and operator dashboard visible
- use the current system as a partner-facing prototype
- avoid claiming statewide public health readiness

Model strategy:

- keep `logistic` as the statewide benchmark
- keep `hist_gbm`, `logistic_hierarchical`, and `logistic_coastal_cells` as secondary comparisons
- keep `TCN` as research only

Data strategy:

- prioritize stormwater, runoff, and watershed context over new model architecture
- interview marine biologists and stormwater specialists to identify the highest-value agency data layers

## Major Risks

Current risks:

- county generalization remains below the baseline needed for public confidence
- many physically important drivers are not yet in the warehouse
- operational covariate freshness still needs hardening
- product users may over-interpret forecasts if uncertainty and product boundaries are not explicit

Communication risk:

- a forecast system can easily look more finished than it really is
- the project must keep distinguishing official samples from model estimates

## Recommended Near-Term Deliverables

Recommended next deliverables in order:

1. Demote grouped and clustered logistic variants from default promotion logic unless they empirically win.
2. Ingest rainfall, antecedent wetness, watershed, and stormwater covariates.
3. Interview domain experts and convert those interviews into a feature-priority map.
4. Re-run causal blocked and spatial benchmarks after the new physical covariates are added.
5. Decide whether V1 should be:
   - a limited regional pilot
   - a research beta
   - or a broader public release

## Bottom Line

Surf Health has successfully crossed the line from concept into working research system. The platform now has real ingestion, modeling, API, and web infrastructure, and it has gone through the most important hardening step: replacing flattering but invalid metrics with more honest evaluation.

The current system is promising, useful, and technically credible as a prototype. It is not yet ready to be described as a scientifically defensible statewide public forecast product.

The path to V1 is clear:

- keep the strong engineering foundation
- stop chasing complexity for its own sake
- add the missing physical drivers
- validate again under honest spatial holdouts
- release narrowly and responsibly

That is the right way to turn the current prototype into a real V1.
