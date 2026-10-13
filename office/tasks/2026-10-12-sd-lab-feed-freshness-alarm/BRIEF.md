---
task: sd-lab-feed-freshness-alarm
worker: gemini
created: 2026-10-12
status: open
---

## Goal

Two things. (1) San Diego County lab results come straight from the county's public
data endpoint into `county_direct_samples.parquet` and, gap-only, into observations,
the way San Francisco, Orange and Monterey already do. Today San Diego results reach
us only through the State Water Board feed, which runs days to weeks behind.
(2) A daily per-county lab-freshness check that flags any county whose newest
enterococcus result has stopped advancing. That way a county going quiet (Orange
stopped reporting to the state on 2026-08-24, Monterey on 08-25, both noticed weeks
late) raises a GitHub issue within days.

## In scope

- San Diego endpoint (public, no login). POST
  `https://cosdapps.sandiegocounty.gov/sdbeachinfo/screenservices/CoSD_Beach_Water_CW/MainFlow/SampleBlock/ScreenDataSetGetSamples`
  with the same session steps as `fetch_san_diego_advisories` in
  `backend/scripts/fetch_county_advisories.py`: GET the homepage, then GET
  `moduleservices/moduleversioninfo` for `versionToken`, and send headers
  `Content-Type: application/json; charset=UTF-8` and `X-CSRFToken: T6C+9iB49TLra4jEsMeSckDMNhQ=`.
  Body:
  `{"versionInfo":{"moduleVersion":<versionToken>,"apiVersion":"L1afk6NDVnwatxTYNUtNLA"},"viewName":"MainFlow.SamplesReport","screenData":{"variables":{"TableSort":"","StartIndex":<n>,"MaxRecords":500,"StationIdFilter":"","StationName3":"","SampleDataFrom":"YYYY-MM-DD","SampleDataTo":"YYYY-MM-DD","isPublic":true,"SiteId":"0","ShowImport":false,"UrlBase":""}},"inputParameters":{}}`.
  The response is `data.List.List[]`, with the total in `data.Count`; page with StartIndex.
  Each item has `Site.StationID`, `Site.LocationName`, `Sample.SampleDate` (YYYY-MM-DD),
  `Sample.SampleTime`, `Sample.Result` (string), `Sample.Qualifier` ("=" or "<"),
  `AnalysisMethod.Label` (ddPCR | MF | MTF | Enterolert), `Parameter.Label` (Enterococcus |
  Fecal Coliforms | Total Coliforms) and `Units.Label` (Copies/100ml | CFU/100ml | MPN/100ml).
  Verified live 2026-10-12: 1,080 rows for 09-01..10-12. If `versionInfo.hasApiVersionChanged`
  is true or `exception` is present, log the error and return 0. Never raise.
- Keep **Enterococcus only**. A "<" qualifier stores the reported number as the value.
  `exceeds_limit`: ddPCR (copies) > 1413, culture (CFU/MPN) > 104.
- **Method and units must travel with each row.** Today `county_direct.py` stamps every
  row `UNITS="MPN/100mL"` and `METHOD="unknown"`. That would judge San Diego ddPCR
  copies against 104 instead of 1413, which is wrong. Add optional `method` and `units`
  fields to `CountySample` and to the persisted parquet (nullable columns; old rows stay
  valid). `normalize_county_direct_samples` uses per-row method/units when present and the
  existing constants when null, so `compute_exceeds_stv` (method-aware) judges ddPCR rows
  against 1413. Write SD units in the exact strings the state feed uses for the same
  assays, so `is_pcr_measurement` recognises "copies".
- New `fetch_san_diego_samples(client, resolver, *, now=None) -> int`, a 60-day trailing
  window, wired into `main()` beside `fetch_monterey_samples`, appending to `_COLLECTED_SAMPLES`.
- Add "San Diego" to `INGEST_COUNTIES` in `backend/app/data/pipeline/county_direct.py`, and
  update that module's docstring rule for adding counties. Merging stays gap-only and keyed
  on DATE (existing behaviour), so a state row for the same (beach_id, date, analyte) always wins.
- New `backend/scripts/lab_freshness_check.py` (CLI: `--curated DIR [--today YYYY-MM-DD] [--json-out PATH]`).
  Per county, from `observations.parquet`, enterococcus only, all sources merged:
  - Eligible if the county has >= 20 distinct sample dates in the trailing 365 days.
  - cadence_days = median gap between consecutive distinct county-wide sample dates over the trailing 180 days.
  - age_days = today - newest sample date.
  - stale if age_days > max(14, 3 * cadence_days).
  - Output: one row per county with newest, age_days, cadence_days, stale and reason.
  - Writes `system_health.json["lab_freshness"]` (merge into the existing file; never drop
    other keys; use `app.core.json_safe.dumps_strict`). Prints a table. Exit 0 always.
- `.github/workflows/daily-forecast.yml`: run the check after the pipeline writes
  observations and before the data commit. Add an `actions/github-script@v9` step that
  opens, or comments on, ONE open issue labelled `county-feed-stale` when any county is
  stale, de-duped like the existing `notify-failure` job (same label search pattern), and
  closes it when none are. It never fails the job.
- `.github/workflows/scraper-health.yml`: exit early with success, without updating the
  streak, when the triggering daily-forecast run's `refresh` job was skipped. The new `gate`
  job skips runs when today's forecast already exists; those must not count as a checked day.
  Use `gh api repos/{repo}/actions/runs/${{ github.event.workflow_run.id }}/jobs`.

## Out of scope

- Fecal/total coliforms into observations; any model, serving or threshold change.
- Other counties' feeds; web/mobile; CLAUDE.md and docs (the PM writes them).
- Changing the 1413 / 104 thresholds.

## Allowed files

- backend/scripts/fetch_county_advisories.py
- backend/app/data/pipeline/county_direct.py
- backend/scripts/lab_freshness_check.py
- backend/tests/test_sd_samples.py
- backend/tests/test_county_direct.py
- backend/tests/test_lab_freshness_check.py
- backend/tests/test_scraper_health_check.py
- backend/tests/fixtures/county_scrapers/sd_samples_*.json
- .github/workflows/daily-forecast.yml
- .github/workflows/scraper-health.yml

## Allowed packages

- none (httpx, pandas, pyarrow already installed)

## Acceptance

```bash
cd backend && .venv/bin/python -m pytest -q                                  # all tests pass
cd backend && .venv/bin/ruff check scripts app tests                        # All checks passed
cd backend && .venv/bin/python scripts/lab_freshness_check.py --curated ../data/curated --json-out /tmp/lf.json   # prints a per-county table, exits 0
cd backend && .venv/bin/python -c "import sys; sys.path[:0]=['scripts','.']; import fetch_county_advisories as f; assert callable(f.fetch_san_diego_samples); print('ok')"   # ok
backend/.venv/bin/python -c "import yaml,sys; [yaml.safe_load(open(p)) for p in ['.github/workflows/daily-forecast.yml','.github/workflows/scraper-health.yml']]; print('yaml ok')"   # yaml ok
```

## Phases

### Phase 25
Deliverable: a pure parser `_parse_sd_samples_payload(data, resolver) -> list[CountySample]` (enterococcus only, method/units per row, the "<" rule, 1413/104 limits) plus `method`/`units` on CountySample and in `persist_samples`, with a fixture JSON trimmed from a real response and tests in `backend/tests/test_sd_samples.py`.

### Phase 50
Deliverable: `fetch_san_diego_samples` (paginated, never raises) wired into `main()`; `county_direct.normalize_county_direct_samples` honours per-row method/units; "San Diego" in INGEST_COUNTIES; tests prove a ddPCR row of 1500 copies exceeds and one of 500 copies does not, and that a state row on the same (beach_id, date) is never duplicated. The report includes a LIVE dry run: rows fetched, enterococcus rows, station-days not already in `data/curated/observations.parquet`, and for overlapping station-days how many values are identical (do not write to data/curated).

### Phase 75
Deliverable: `backend/scripts/lab_freshness_check.py` + `backend/tests/test_lab_freshness_check.py` (synthetic frames: a fresh county, a county gone quiet, an ineligible sparse county, a county with a slow but steady cadence that must NOT flag), wired into daily-forecast.yml with the de-duped `county-feed-stale` issue step. The report pastes the check's table on the real `data/curated`.

### Phase 100
Deliverable: scraper-health.yml skips a gate-skipped forecast run (with a test in test_scraper_health_check.py if the logic is in Python; otherwise explain), and all Acceptance commands pass.

## Corrections

(appended by the PM; newest last; each entry dated)
