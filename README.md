# Surf Health

California marine beach health forecast platform focused on daily enterococcus risk for surfers and beachgoers.

## Workspace

- `backend/`: FastAPI service, ingestion pipeline, feature engineering, model training, and tests.
- `web/`: Next.js website for public and research-facing views.

## Local Development

### Backend

1. Install Python 3.12.
2. Run `make setup-backend`.
3. Copy `backend/.env.example` to `backend/.env` if needed.
4. Run `make dev-api`.

### Web

1. Run `make setup-web`.
2. Set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` in `web/.env.local`.
3. Run `make dev-web`.

### Data + Modeling

- The backend ships with fixtures so the API and UI work immediately.
- Ingestion connectors and training code are included for the official California beach dataset plus ocean/weather covariates.
- Use `make train-sample` to exercise the modeling pipeline against fixture-backed data once dependencies are installed.
- To build curated snapshots from official California BeachWatch CSVs, run:
- To build curated snapshots from official California BeachWatch CSVs and enrich them with live CDIP, CeNCOOS, and EPA UV covariates, run:
- To merge the cleaned Safe-to-Swim fecal-indicator dataset into the BeachWatch marine label set, first obtain:
  - a Safe-to-Swim results CSV such as `safetoswim_geomeans_2020-present.csv`
  - the Safe-to-Swim sites CSV such as `safetoswim_sites_2025-03-25.csv`
- Then run:

```bash
cd /Users/kylechoi/surf_health/backend
. .venv/bin/activate
python -m app.data.pipeline.cli \
  --normalize-beachwatch \
  --stations-csv /tmp/beach-monitoring-stations.csv \
  --results-csv /tmp/beach-monitoring-results.csv \
  --advisories-csv /tmp/beach-advisories.csv \
  --merge-ceden \
  --ceden-results-csv /tmp/safetoswim_geomeans_2020-present.csv \
  --ceden-sites-csv /tmp/safetoswim_sites_2025-03-25.csv \
  --max-results-rows 25000 \
  --max-ceden-rows 50000 \
  --with-external-covariates
```

- The CEDEN merge is conservative by design:
  - only enterococcus rows are considered for the v1 label
  - only Safe-to-Swim/CEDEN stations that map back to known marine BeachWatch beaches are merged
  - duplicate samples prefer direct BeachWatch records over mirrored Safe-to-Swim rows
  - when `--max-ceden-rows` is used, the CLI now queries the official Safe-to-Swim datastore for enterococcus rows tied to known marine station codes and caches that subset locally, instead of reading the first rows of the full statewide CSV
- To build curated snapshots from official California BeachWatch CSVs alone and enrich them with live CDIP, CeNCOOS, and EPA UV covariates, run:

```bash
cd /Users/kylechoi/surf_health/backend
. .venv/bin/activate
python -m app.data.pipeline.cli \
  --normalize-beachwatch \
  --stations-csv /tmp/beach-monitoring-stations.csv \
  --results-csv /tmp/beach-monitoring-results.csv \
  --advisories-csv /tmp/beach-advisories.csv \
  --max-results-rows 25000 \
  --with-external-covariates
```

- Then export a dated forecast snapshot from the curated beach-day table:

```bash
cd /Users/kylechoi/surf_health/backend
. .venv/bin/activate
python -m app.ml.training --curated --forecast-date 2026-04-20
```

- When curated snapshots exist under `data/curated`, the API automatically serves them unless `PREFERRED_REPOSITORY=fixture` is set.

## Notes

- Operational storage targets Postgres/PostGIS and research snapshots target DuckDB/Parquet.
- Ollama is used only for explanations and QA assistance, not numeric forecasting.
- The current repo is scaffolded for local-first development on Apple Silicon with PyTorch MPS.

## Acknowledgement 

- This project is inspired by the project my team attempted to do: https://github.com/SatrunsDream/DataTide
