# Surf Health Phase 1 Implementation Plan

Date: April 22, 2026

## Objective

Implement Phase 1 of the next-generation forecasting architecture by adding forecast-safe terrestrial hydrology and precipitation data to the existing California marine beach pipeline.

Phase 1 scope:

- USGS real-time streamflow ingestion
- CNRFC sub-hourly observed precipitation ingestion
- CNRFC forecast precipitation ingestion where operationally safe
- NHDPlus / WBD coastal hydrologic linkage using pour-point architecture
- new hydrology-first curated features for model training and daily forecast generation

This phase does not attempt to solve the full statewide generalization problem by itself. Its purpose is to replace weak spatial proxies with physically causal upstream forcing features.

## Why This Is the Next Step

Current empirical status:

- best statewide model is still `logistic-curated-v0`
- held-out beach generalization is acceptable for a research prototype
- held-out county generalization still fails to beat persistence
- county grouping and unsupervised coastal-cell clustering did not improve statewide transfer

Interpretation:

- the limiting factor is not model class
- the limiting factor is missing physics
- the first missing physics layer is terrestrial runoff forcing

Phase 1 therefore focuses on the part of the causal chain that is currently absent:

`rain -> watershed wetness -> stream discharge -> coastal delivery pressure`

## Engineering Principles

1. Forecast-safe only

- No feature may use data that would not be available before the operational forecast issue time.
- Operational target remains a 5:00 AM PT forecast.
- Day-0 rainfall summaries published after 5:00 AM PT are forbidden.

2. No hidden leakage

- Historical training features must be reconstructable exactly as they would have been available at forecast time.
- Derived rainfall windows must be built from continuous or sub-hourly raw feeds, not post-hoc daily summaries.

3. Hydrologic linkage over proximity

- Replace county and naive nearest-neighbor logic with explicit hydrologic routing and coastal discharge linkage.

4. Start with reliable feature contracts

- The priority is not to ingest every possible source immediately.
- The priority is to establish clean, testable data contracts for precipitation, streamflow, and coastal catchment mapping.

## Deliverables

By the end of Phase 1, the repo should support:

- downloading and caching raw USGS streamflow data for mapped coastal discharge gages
- downloading and caching raw CNRFC precipitation data at sub-hourly resolution
- storing a static hydrologic linkage table from beaches to coastal catchments / pour points / stream gages
- enriching `beach_day` with hydrology and precipitation features
- retraining the current logistic baseline using these new features
- rerunning blocked and spatial backtests with no change to leakage standards

## Current Codebase Anchor Points

We should build on the current architecture rather than introducing a parallel system.

Existing anchor files:

- `backend/app/core/config.py`
- `backend/app/data/connectors/base.py`
- `backend/app/data/connectors/official_sources.py`
- `backend/app/data/pipeline/cli.py`
- `backend/app/data/pipeline/external_covariates.py`
- `backend/app/data/pipeline/features.py`
- `backend/app/ml/training.py`

## Proposed File Additions

### New connectors

- `backend/app/data/connectors/hydrology_sources.py`

Add:

- `UsgsNwisConnector`
- `CnrfcObservedPrecipConnector`
- `CnrfcQpfConnector`
- `NhdPlusMetadataConnector`

Purpose:

- isolate remote-source fetch and raw caching logic from downstream geospatial joins and feature engineering

### New pipeline modules

- `backend/app/data/pipeline/hydrology.py`
- `backend/app/data/pipeline/precipitation.py`
- `backend/app/data/pipeline/hydrography.py`

Purpose:

- transform raw hydrology data into daily beach-linked covariates
- keep CLI thin
- keep feature engineering deterministic and testable

### New tests

- `backend/tests/test_hydrology_pipeline.py`
- `backend/tests/test_precipitation_pipeline.py`
- `backend/tests/test_hydrography_pipeline.py`

## Configuration Additions

Add to `backend/app/core/config.py`:

- `forecast_issue_hour_local: int = 5`
- `usgs_nwis_base_url`
- `cnrfc_base_url`
- `nhdplus_data_dir`
- `hydrology_cache_dir`
- `precip_cache_dir`
- `default_precip_lookback_days`
- `default_streamflow_lookback_days`

Optional but useful:

- `cnrfc_observed_station_allowlist_path`
- `usgs_gage_allowlist_path`
- `hydrologic_mapping_path`

## Raw Data Contracts

### 1. USGS streamflow

Raw cache target:

- `data/raw/usgs_streamflow/*.parquet`

Expected normalized columns:

- `gage_id`
- `time_utc`
- `time_local`
- `discharge_cfs`
- `gage_height_ft`
- `provisional`
- `source_name`

### 2. CNRFC observed precipitation

Raw cache target:

- `data/raw/cnrfc/observed_precip/*.parquet`

Expected normalized columns:

- `station_id`
- `time_utc`
- `time_local`
- `precip_mm_increment`
- `latitude`
- `longitude`
- `elevation_m`
- `source_name`

Important:

- this must preserve raw increments
- we aggregate locally into 1h, 6h, 24h windows
- we do not ingest unsafe published summary artifacts as training features

### 3. CNRFC QPF

Raw cache target:

- `data/raw/cnrfc/qpf/*.parquet`

Expected normalized columns:

- `grid_id` or `cell_id`
- `forecast_issue_time_utc`
- `valid_start_utc`
- `valid_end_utc`
- `qpf_mm`
- `latitude`
- `longitude`

### 4. NHDPlus / WBD linkage

Raw static assets:

- local geospatial assets under `data/raw/nhdplus/`

Expected normalized beach linkage table:

- `beach_id`
- `hydrologic_unit_id`
- `pour_point_id`
- `pour_point_latitude`
- `pour_point_longitude`
- `distance_to_pour_point_km`
- `nearest_stream_gage_id`
- `distance_to_gage_km`
- `watershed_area_km2`
- `mapping_confidence`

## Curated Data Contracts

### New curated tables

1. `hydrologic_beach_links.parquet`

One row per beach with static hydrologic routing metadata.

2. `streamflow_daily.parquet`

Expected columns:

- `gage_id`
- `sample_date`
- `streamflow_cfs_latest`
- `streamflow_cfs_mean_6h`
- `streamflow_cfs_mean_24h`
- `streamflow_cfs_max_24h`
- `streamflow_cfs_mean_72h`
- `streamflow_rising_flag`

3. `precip_daily.parquet`

Expected columns:

- `hydrologic_unit_id`
- `sample_date`
- `precip_mm_1h`
- `precip_mm_6h`
- `precip_mm_24h`
- `precip_mm_48h`
- `precip_mm_72h`
- `precip_mm_7d`
- `precip_awi`
- `first_flush_flag`

4. `beach_hydrology_daily.parquet`

Beach-linked daily table combining hydrologic routing with streamflow and precipitation.

Expected columns:

- `beach_id`
- `sample_date`
- `hydrologic_unit_id`
- `pour_point_id`
- `nearest_stream_gage_id`
- `distance_to_pour_point_km`
- `distance_to_gage_km`
- `streamflow_cfs_latest`
- `streamflow_cfs_mean_24h`
- `streamflow_cfs_max_24h`
- `streamflow_rising_flag`
- `precip_mm_6h`
- `precip_mm_24h`
- `precip_mm_48h`
- `precip_mm_72h`
- `precip_mm_7d`
- `precip_awi`
- `first_flush_flag`

## CLI Changes

Extend `backend/app/data/pipeline/cli.py` with new flags:

- `--with-hydrology`
- `--usgs-gages-csv`
- `--cnrfc-observed-csv`
- `--cnrfc-qpf-csv`
- `--hydrologic-links-csv`
- `--build-hydrologic-links`
- `--start-date`
- `--end-date`

Expected usage pattern:

```bash
python -m app.data.pipeline.cli \
  --normalize-beachwatch \
  --stations-csv /tmp/beach-monitoring-stations.csv \
  --results-csv /tmp/beach-monitoring-results.csv \
  --advisories-csv /tmp/beach-advisories.csv \
  --merge-ceden \
  --with-external-covariates \
  --with-hydrology \
  --start-date 2018-01-01 \
  --end-date 2026-04-22
```

## Class and Function Design

### `backend/app/data/connectors/hydrology_sources.py`

#### `UsgsNwisConnector`

Responsibilities:

- fetch raw continuous-values time series for configured gages
- normalize timestamps
- write raw parquet cache

Methods:

- `fetch_streamflow(gage_ids: list[str], start: date, end: date) -> pd.DataFrame`

#### `CnrfcObservedPrecipConnector`

Responsibilities:

- fetch sub-hourly observed precipitation
- preserve incremental precipitation records
- avoid unsafe summary endpoints in default path

Methods:

- `fetch_observed_precip(station_ids: list[str], start: date, end: date) -> pd.DataFrame`

#### `CnrfcQpfConnector`

Responsibilities:

- fetch forecast precipitation windows
- store issue time and validity time separately

Methods:

- `fetch_qpf(start: date, end: date) -> pd.DataFrame`

### `backend/app/data/pipeline/hydrography.py`

#### `build_hydrologic_beach_links(...)`

Inputs:

- beach station metadata
- NHDPlus / WBD mapping assets
- optional stream-gage metadata

Output:

- `hydrologic_beach_links.parquet`

Responsibilities:

- map each beach to coastal hydrologic unit
- map to a coastal pour point
- map to nearest valid discharge gage if available
- assign `mapping_confidence`

### `backend/app/data/pipeline/precipitation.py`

#### `aggregate_precip_windows(...)`

Responsibilities:

- aggregate sub-hourly precipitation safely into forecast-ready windows
- compute:
  - 1h, 6h, 24h, 48h, 72h, 7d totals
  - AWI
  - first flush flag

#### `compute_antecedent_wetness_index(...)`

Reference:

- exponentially decayed rolling accumulation

#### `compute_first_flush_flag(...)`

Responsibilities:

- detect dry spell followed by threshold rain event

### `backend/app/data/pipeline/hydrology.py`

#### `aggregate_streamflow_windows(...)`

Responsibilities:

- compute forecast-safe daily streamflow features:
  - latest discharge prior to cutoff
  - mean 6h / 24h / 72h
  - max 24h
  - rising indicator

#### `build_beach_hydrology_daily(...)`

Responsibilities:

- join hydrologic links, streamflow_daily, and precip_daily onto beaches by date

## Feature Engineering Changes

Extend `backend/app/data/pipeline/features.py` to include the following new numeric columns when present:

- `streamflow_cfs_latest`
- `streamflow_cfs_mean_24h`
- `streamflow_cfs_max_24h`
- `streamflow_rising_flag`
- `precip_mm_6h`
- `precip_mm_24h`
- `precip_mm_48h`
- `precip_mm_72h`
- `precip_mm_7d`
- `precip_awi`
- `first_flush_flag`
- `distance_to_pour_point_km`
- `distance_to_gage_km`
- `watershed_area_km2`

Rules:

- these should participate in lagged and rolling feature generation only when forecast-safe
- no post-issue-time values may enter the training frame
- AWI and first-flush are already derived features and can be used directly on their forecast-safe day

## Training Changes

Update `backend/app/ml/training.py` so the curated training frame loads hydrology-enriched beach-day rows when present.

Requirements:

- do not change the current blocked-time split logic
- do not change the current spatial holdout methodology
- keep `logistic` as the primary statewide benchmark
- treat Phase 1 as a covariate improvement experiment, not a model-family rewrite

Success criterion:

- compare new hydrology-enabled `logistic` against the current baseline on:
  - blocked test AUCPR / Brier
  - held-out beach AUCPR / Brier
  - held-out county AUCPR / Brier

## Testing Plan

### Unit tests

1. Streamflow ingestion

- timestamps normalize correctly
- duplicate gage/timestamp rows are removed
- provisional flags are preserved

2. Precipitation aggregation

- raw sub-hourly increments aggregate correctly to trailing windows
- 24h values do not exceed what would have been available before 5:00 AM PT
- AWI is monotonic with added rainfall
- first-flush logic behaves correctly for dry-to-wet transitions

3. Hydrologic beach links

- beaches map deterministically to one hydrologic unit / pour point
- missing mappings are flagged instead of silently dropped

4. Beach daily join

- joins preserve row counts by beach-day
- unmatched hydrologic data results in nulls rather than dropping target rows

### Regression tests

- current curated training still runs when hydrology tables are absent
- forecast export still works with hydrology columns present
- spatial backtests still emit the expected keys

## Acceptance Criteria

Phase 1 is complete when all of the following are true:

1. Raw USGS and CNRFC ingestion works from the CLI.
2. Static hydrologic linkage tables are generated and cached.
3. `beach_day` or a downstream joined table contains the new hydrology fields.
4. The backend test suite passes.
5. A full curated retrain completes successfully.
6. We can compare pre-Phase-1 and post-Phase-1 logistic metrics from the same evaluation pipeline.

## Explicit Non-Goals for Phase 1

- no neural architecture redesign
- no public release decision
- no Expo/mobile work
- no same-day satellite nowcast
- no statewide MS4 unification yet
- no replacement of the current API schema

## Development Order

Recommended implementation order:

1. Add config and new connector module.
2. Add hydrologic linkage pipeline and static beach link outputs.
3. Add raw streamflow ingestion and daily aggregations.
4. Add raw precipitation ingestion and AWI / first-flush aggregation.
5. Join hydrology outputs into curated beach-day rows.
6. Add tests.
7. Retrain and benchmark.

## First Concrete Code Tasks

The first coding tasks should be:

1. Create `backend/app/data/connectors/hydrology_sources.py`
2. Create `backend/app/data/pipeline/hydrography.py`
3. Extend `backend/app/data/pipeline/cli.py` with `--with-hydrology`
4. Add `hydrologic_beach_links.parquet` generation
5. Add `streamflow_daily.parquet` and `precip_daily.parquet` generation

## Bottom Line

The right next move is development, but only in the Phase 1 hydrology-first direction.

Do not spend the next cycle on:

- more clustering
- bigger neural nets
- region labels

Do spend the next cycle on:

- forecast-safe hydrology
- rainfall windows
- upstream watershed linkage
- deterministic beach-to-discharge mapping

That is the most defensible path to raising the statewide generalization ceiling.

---

# Phase 2: Live Hydration & Neural Architecture Redux

## Objective
The objective of Phase 2 is two-fold:
1. **The Empirical Proof**: Hydrate the data engineering pipeline (replacing our mock Pandas stubs) with live USGS NWIS and CNRFC precipitation calls to mathematically prove the 14 new hydrologic features defeat the "Generalization Wall" (spatial hold-out persistence) using the Logistic baseline.
2. **Architecture Tuning (BeachTCN V2)**: Once the physical covariates prove their deterministic value in standard logistics, physically alter the PyTorch `BeachTCN` architecture so it doesn't naively process `precip_awi` and `streamflow` through the exact same 1D standard Convolutional window as standard water temp. We will inject a parallel exogenous dense pathway.

## User Review Required

> [!IMPORTANT]
> **Decisions on Open Questions:**
> 
> 1. **Hard-Caching & Validation Window:** Yes, **hard-caching** is absolutely acceptable and essential. Querying EPA WATERS and USGS for 5 years of daily data across 300 beaches on every run will hit severe rate limits. Restricting the validation window to a subset of beaches (e.g., Southern California Bight) for the initial empirical proof is a pragmatic and statistically valid approach.
> 
> 2. **NOAA NWS API vs CNRFC QPF:** Yes, utilizing the simplified point-based **NOAA NWS API** (`api.weather.gov/stations/{id}/observations`) as an initial proxy to acquire the localized 24-hr `precip_awi` is perfectly fine. Building a full GRIB binary handler for CNRFC spatial grids is overkill for this phase.

Please review the above decisions and let me know if you approve them before we begin execution.

## Proposed Changes

### Data Ingestion & Spatial Linkages

#### [MODIFY] `backend/app/data/connectors/hydrology_sources.py`
- Rip out `pd.DataFrame()` stubs and implement the actual `httpx.AsyncClient` logic mapping targeting the continuous volumetric endpoints.
- `UsgsNwisConnector` -> Ping `https://waterservices.usgs.gov/nwis/iv/` using parameter code `00060` (Discharge). *(Note: Currently it uses `dv/` for daily values, we will transition to `iv/` if sub-daily is required, or ensure `dv/` handles the full scope).*
- `CnrfcObservedPrecipConnector` -> Transition to NOAA NWS API point-based observation parsing as a proxy to acquire 24-hr precipitation values.

#### [NEW] `backend/app/data/pipeline/hydro_mapper.py`
- Build a lightweight geometric resolver `geopandas` script bounding off the official EPA WATERS GeoViewer REST API (`https://watersgeo.epa.gov/arcgis/rest/services/`).
- Dynamically query which USGS streamgage and HU12 catchment overlaps any given beach's `lat/long` to bypass downloading large static Geodatabases.

### Neural Architecture Redesign (BeachTCN)

#### [MODIFY] `backend/app/ml/models.py`
- **Current State**: `BASE_NUMERIC_COLUMNS` are thrown directly into the `sequence` matrix and squeezed through standard 1D dilatated temporal filters. `BeachTCN` already has an `exogenous_net` (dense pathway) configured for `static_features`.
- **Change**: Strip the 14 hydrology metrics and spatial distances out of the standard 1D CNN `sequence` matrix preparation in the training loop/features generation. 
- Feed them directly into the parallel `self.exogenous_net` (`nn.Sequential` Exogenous network) as `static_features`.
- Ensure the concatenation of the 1D CNN (oceanic state) and the Exogenous dense network (terrestrial forcing state) strictly happens at the final `self.shared` linear layers as designed.

## Verification Plan

### Automated Tests
- Run `python -m app.ml.training --curated --spatial-backtests`.
- Monitor the empirical `brier_score` and `aucpr`.
- **Success Criteria**: The `logistic_valid` hold-out AUCPR mapping strictly crests the `persistence_valid` AUCPR.
