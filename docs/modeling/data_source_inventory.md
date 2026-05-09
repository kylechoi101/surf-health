# Data Source Inventory

Generated: 2026-05-09

This inventory captures the next data sources to improve stale-sample and local-router evaluation. It records current official endpoints and the connector strategy. Large files should not be ingested in this slice; prefer metadata/schema checks first, then focused incremental connectors.

## Priority 1: California BeachWatch / Safe to Swim

- Source: https://data.ca.gov/dataset/beach-water-quality-postings-and-closures
- CKAN package API: https://data.ca.gov/api/3/action/package_show?id=beach-water-quality-postings-and-closures
- Workspace scratch metadata: `data/source_metadata/ca_beachwatch_package.json`
- Workspace raw CSV scratch copies: `/tmp/surf-health-source-data/ca_beachwatch/`
- Package modified: `2026-03-17T22:03:20.892560`
- Connector priority: highest

Current resource URLs:

```text
Beach Posting and Closures- Advisories:
https://data.ca.gov/dataset/b9c8ce91-40ff-4ad3-8164-bc17c46afb44/resource/d5cd6a23-829c-426d-a63e-689a55a3db9c/download/beach-advisories.csv

Beach Water Quality Monitoring Stations:
https://data.ca.gov/dataset/b9c8ce91-40ff-4ad3-8164-bc17c46afb44/resource/98e628ff-d012-4982-ad32-b9f9ad8ab524/download/beach-monitoring-stations.csv

Beach Detail Information:
https://data.ca.gov/dataset/b9c8ce91-40ff-4ad3-8164-bc17c46afb44/resource/fcbc9250-06e3-437d-b0c6-3cc5ddde93fc/download/beach-information-csv.csv

Beach Water Quality Monitoring Results - Bacteria:
https://data.ca.gov/dataset/b9c8ce91-40ff-4ad3-8164-bc17c46afb44/resource/7bd961cf-abe4-433b-8033-378161237ff3/download/beach-monitoring-results.csv

Beach EPA Spatial data:
https://data.ca.gov/dataset/b9c8ce91-40ff-4ad3-8164-bc17c46afb44/resource/3077fe5b-4bf6-4f43-873e-34ada85db750/download/ca-only-beaches.zip
```

Immediate use:

- Replace partial bacteria/advisory history with canonical BeachWatch resources.
- Add station/beach detail joins for coverage, stale-sample eligibility, and county/site metadata.
- Chunk the bacteria CSV; a scratch download exceeded 1.5 GB before completion.
- Keep the downloaded CSVs out of git; they are current scratch inputs for connector/schema work.

## Priority 2: CIWQS Sanitary Sewer System Data Flat Files

- Source: https://www.waterboards.ca.gov/ciwqs/publicreports.html
- Data flat-file index: https://www.waterboards.ca.gov/water_issues/programs/sso/docs/data_files/
- Workspace scratch metadata: `data/source_metadata/ciwqs_sso_data_files_index.html`
- Observed index update: files mostly modified `2026-05-08 06:00/06:01`
- Connector priority: high

Important files:

```text
Cat1-2-3-Spills.txt
SSO.txt
PLSD.txt
plps_spills.txt
Enrollee_Info.txt
No_spill.txt
annualReports.txt
```

Immediate use:

- Build spill proximity/timing features for beaches, especially San Diego.
- Join spill category, volume, recovered volume, responsible agency, and distance to beach/pour point.
- Treat as high-value because the weather-only route failed badly when hidden source state was omitted.

## Priority 3: NOAA Precipitation and Hydrology

- NWPS API overview: https://water.noaa.gov/about/api
- Precipitation data access: https://api.water.noaa.gov/about/precipitation-data-access
- Workspace scratch metadata:
  - `data/source_metadata/noaa_water_api.html`
  - `data/source_metadata/noaa_precipitation_data_access.html`
- Connector priority: high

Immediate use:

- Improve rain/runoff fields with Stage IV QPE and NWPS/NWM streamflow context.
- Use Stage IV for historical precipitation where current precipitation coverage is missing.
- Keep Open-Meteo as fallback, not primary, when NOAA coverage exists.

## Priority 4: CDIP Waves

- Source: https://cdip.ucsd.edu/m/documents/data_access.html
- Realtime THREDDS example: https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/realtime/latest_3day.nc.html
- Workspace scratch metadata: `data/source_metadata/cdip_data_access.html`
- Connector priority: medium-high

Immediate use:

- Replace nearest-buoy-only wave context with CDIP/MOP nearshore wave fields.
- Add wave height, period, direction, and alongshore wave-energy exposure features.

## Priority 5: NOAA CO-OPS

- Source: https://api.tidesandcurrents.noaa.gov/api/uat/
- Workspace scratch metadata: `data/source_metadata/noaa_coops_api.html`
- Connector priority: medium

Immediate use:

- Add tide, water level anomaly, currents where available, water temperature, and wind observations.
- Batch by station/product/date because product request windows vary.

## Priority 6: NDBC

- Source: https://www.ndbc.noaa.gov/historical_data.shtml
- Historical files: https://www.ndbc.noaa.gov/data/historical/
- Workspace scratch metadata: `data/source_metadata/ndbc_historical_data.html`
- Connector priority: medium

Immediate use:

- Use as fallback or cross-check for wind/wave observations.
- Prefer CDIP for California nearshore wave fields where available.

## Priority 7: Open-Meteo

- Historical weather: https://open-meteo.com/en/docs/historical-weather-api
- Historical forecast: https://open-meteo.com/en/docs/historical-forecast-api
- Workspace scratch metadata:
  - `data/source_metadata/open_meteo_historical_weather.html`
  - `data/source_metadata/open_meteo_historical_forecast.html`
- Connector priority: fallback

Immediate use:

- Fill missing wind, radiation, cloud, and precipitation fields where official sources are sparse.
- Use archived forecasts to align training features with what would have been known at forecast time.

## Recommended Next Data Work

1. Implement a BeachWatch canonical connector from the CKAN package resources.
2. Add a CIWQS SSO flat-file connector focused on spill events near beaches/pour points.
3. Add Stage IV precipitation or NWPS/NWM hydrology enrichment for historical rain/runoff.
4. Only then revisit heat-map or multimodal inputs, using structured grids as the baseline to beat.
