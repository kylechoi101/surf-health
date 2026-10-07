---
task: monterey-samples
worker: gemini
created: 2026-10-07
status: done
---

## Goal

Monterey County stopped uploading to the State Water Board after 2026-08-25, so 0 of its 14
production beaches are served. The county still publishes weekly lab results on plain HTML
pages. When this task is done, the daily advisory scrape reads those pages, appends the
results to `data/curated/county_direct_samples.parquet`, and the pipeline's county-direct
step ingests Monterey enterococcus rows into observations (gap-fill only), exactly as it
already does for San Francisco and Orange County. The PM verified every fact below live on
2026-10-07; implement against them rather than re-discovering.

## Verified facts (PM, 2026-10-07)

**Source.** `https://apps.co.monterey.ca.us/CountyWebsite/health/beaches/<page>.htm`,
encoding cp1252, no bot protection (plain httpx GET with the existing `_BROWSER_UA` works;
the countyofmonterey.gov pages that iframe these are Akamai-blocked, do NOT use them).
Eight pages, mapped to `beaches.station_code` for county `Monterey`:

| page | station_code |
|---|---|
| sunset | SDA |
| spanish_bay | SPB |
| lovers_point | LOP |
| san_carlos | SCB |
| del_monte | DMB |
| monterey_state_beach | MBH |
| stillwater_cove | STCO |
| carmel | CBOA |

Hard-code this map. Other guessed page names return 404; do not probe for more.

**Page layout.** Hand-edited FrontPage HTML. Each page has a status line
(`AS OF 10/6/2026 LOVER'S POINT IS OPEN WITHOUT RESTRICTION.`), then one table: a header row
starting `Analysis Name` with the last 5 sampling dates, then rows `Enterococcus`,
`Fecal coliform`, `Total coliform-Q`, each with 5 value cells followed by criteria columns.
- **The header markup is broken** (a stray `<FONT </td>` swallows a date cell), so an HTML
  parser returns only 4 header dates. Read the dates with a regex
  `\d{1,2}/\d{1,2}/20\d\d` over the raw text between `Analysis Name` and `Single Sample`;
  read the analyte rows with `html.parser` (cells parse correctly) and zip value cells 1..N
  with the N dates.
- **Values:** `<10` = non-detect → **10.0** (the state stores Monterey non-detects as 10; 80%
  of Monterey state rows are exactly 10). Strip a leading `>`, `>=` or `=` qualifier and use
  the number (`>63` → 63.0, `=10` → 10.0); the state rows carry the same qualifier characters
  on ordinary values. Skip any cell that is not numeric after that: `Not Sampled`,
  `Data Missing`, `NA`, empty.
- **Dates: page date = sample date + 1 day.** Store `sample_date = page date − 1 day`.
  Verified on four Oct-2025 snapshots (fixtures `2025-10/`) against state rows, 19 of 19
  enterococcus values identical, with the page always one day after the state's sample date.
  Getting this wrong makes the date-keyed gap-fill insert duplicates if the state ever
  backfills, so pin it with a test. Expected state values for the fixtures:

  | fixture | page date → sample date | state enterococcus |
  |---|---|---|
  | sunset (SDA) | 9/19,9/30,10/7,10/18,10/21/2025 → 09-18,09-29,10-06,10-17,10-20 | 10,10,63,10,10 |
  | spanish_bay (SPB) | same dates | 10,10,10,10,10 |
  | san_carlos (SCB) | 9/30,10/7,10/18,10/21 (9/23 is `Data Missing`) → 09-29,10-06,10-17,10-20 | 41,20,10,691 |
  | monterey_state_beach (MBH) | same as sunset | 10,10,20,10,62 |

  (sunset/spanish_bay/monterey_state_beach page dates: 9/19, 9/30, 10/7, 10/18, 10/21/2025.)
- Method is SM 9230 D (Enterolert, culture MPN), so `county_direct.UNITS`/`METHOD` already fit.

**Fixtures** (already in the repo, saved 2026-10-07):
`backend/tests/fixtures/county_scrapers/monterey/*.htm` (current pages; `index.htm` is the
directory index with a county-wide status line, not needed) and `.../monterey/2025-10/*.htm`.
In the current fixtures `san_carlos` is `Not Sampled` on all five dates, and `spanish_bay`
has dates 9/16, 9/22, 9/23, 9/29, 10/6/2026.

**Plumbing that already exists** (`backend/scripts/fetch_county_advisories.py`):
`CountySample`, `_COLLECTED_SAMPLES`, `persist_samples` (dedupes on
county, area, sample_date, analyte; keep="last"), `fetch_orange_county_samples` (the pattern to
copy: never raises, logs to stderr, returns count), and `NO_SOURCE_COUNTIES["Monterey"]`.
`backend/app/data/pipeline/county_direct.py`: `INGEST_COUNTIES = {"San Francisco", "Orange"}`.

## In scope

- `_monterey_parse_page(html: str) -> list[...]` (pure) and
  `fetch_monterey_samples(client, resolver) -> int` in `fetch_county_advisories.py`.
  Emit a `CountySample` per (station, sample_date, analyte) for ENTEROCOCCUS,
  FECAL_COLIFORM and TOTAL_COLIFORM; `area` = station_code; `station_code` set; `beach_id`
  from `resolver.resolve_by_station_code("Monterey", code)`; `exceeds_limit` = value > 104 /
  400 / 10000 respectively; `source_url` = the page URL. A page that fails (HTTP error, no
  header dates) is logged and skipped; the other pages still count.
- Wire it into `main()` next to the Orange County samples call (respect `--only`).
- Remove Monterey from `NO_SOURCE_COUNTIES` and append its own `CountyReport` in `main()`:
  `county="Monterey"`, `source_url` = the pages' base URL, `samples_collected` = count,
  `success = count > 0`, and when count is 0, `error` = a short reason (so
  `data_change_report.py` shows it as a breakage, not a known gap). It is NOT added to
  `COUNTIES_FIRST_CLASS` (no advisory scraping in this task).
- Add `"Monterey"` to `county_direct.INGEST_COUNTIES`; extend the module docstring's
  allowlist note with one short paragraph giving the verification above (19/19, +1-day offset,
  ND = 10).
- Tests (new file `backend/tests/test_monterey_samples.py`): parser on every fixture; the
  broken-header case yields 5 dates; `<10`/`>63`/`=10` handling; `Not Sampled`/`Data Missing`
  skipped; −1 day; the 19-value mirror table above; `fetch_monterey_samples` with a fake
  client (one page 404 → others still collected, never raises); `main()` report entry for
  Monterey; a `county_direct` test that a Monterey row is ingested and is dropped when a state
  row already holds the same (beach_id, date, analyte).

## Out of scope

- Scraping Monterey advisory/status lines into the advisory layer.
- Any change to `.github/workflows/**`, `CLAUDE.md`, `docs/**`, `data/**`.
- Running the full pipeline or committing.

## Allowed files

- backend/scripts/fetch_county_advisories.py
- backend/app/data/pipeline/county_direct.py
- backend/tests/test_monterey_samples.py
- backend/tests/test_county_direct.py
- backend/tests/test_fetch_county_advisories.py
- backend/tests/test_county_scrapers.py (only `test_monterey_is_a_no_source_report_not_a_scraper`)

## Allowed packages

- none (stdlib `html.parser`, `re`; httpx and pandas are already used)

## Acceptance

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_monterey_samples.py tests/test_county_direct.py tests/test_fetch_county_advisories.py tests/test_county_scrapers.py   # all pass
cd backend && .venv/bin/python -m pytest -q -x                                  # full suite passes
cd backend && .venv/bin/ruff check scripts/fetch_county_advisories.py app/data/pipeline/county_direct.py tests/test_monterey_samples.py   # clean
cd backend && .venv/bin/python -c "import sys,httpx,pandas as pd; sys.path.insert(0,'scripts'); import fetch_county_advisories as f; r=f.StationResolver(pd.read_parquet('../data/curated/beaches.parquet')); c=httpx.Client(follow_redirects=True); n=f.fetch_monterey_samples(c,r); s=[x for x in f._COLLECTED_SAMPLES if x.analyte=='ENTEROCOCCUS']; print(n,len(s),sorted({x.station_code for x in s}),all(x.beach_id for x in s)); assert len({x.station_code for x in s})>=7 and all(x.beach_id for x in s)"   # live: >=7 stations, all resolved
```

## Phases

### Phase 25
Deliverable: `_monterey_parse_page` + the station map, with parser tests on all fixtures (dates, qualifiers, skips, −1 day, the 19-value mirror table) passing.

### Phase 50
Deliverable: `fetch_monterey_samples` wired into `main()`, Monterey moved out of `NO_SOURCE_COUNTIES` into its own `CountyReport`, with the fake-client and report tests passing.

### Phase 75
Deliverable: `"Monterey"` in `county_direct.INGEST_COUNTIES` with the docstring note, and the county_direct ingest/gap-fill tests passing.

### Phase 100
Deliverable: cleanup, and all Acceptance commands pass.

## Corrections

(appended by the PM; newest last; each entry dated)

### 2026-10-07 (after phase 25, apply in phase 50)
- `_monterey_parse_value`: the page legend says `ND = Not Detected` (below the 10/100 mL
  detection limit). A cell reading `ND` (any case) must become **10.0**, same as `<10`; today it
  is skipped. Add a test.
- Remove the alias names `MONTEREY_STATIONS` and `MONTEREY_PAGE_TO_STATION`; keep only
  `MONTEREY_PAGES` (update the test).

### 2026-10-07 (after phase 50, apply in phase 75)
- `test_county_scrapers.py::test_monterey_is_a_no_source_report_not_a_scraper` asserts the old
  behaviour and now fails (`KeyError: 'Monterey'`). `test_county_scrapers.py` is added to
  Allowed files for this one test only: replace it with a test that Monterey is NOT in
  `NO_SOURCE_COUNTIES` and is NOT in `COUNTIES_FIRST_CLASS` (samples only, no advisory scrape).
  Touch nothing else in that file.

### 2026-10-07 (after phase 75, apply in phase 100)
- In `test_county_scrapers.py`, rename `test_monterey_is_a_no_source_report_not_a_scraper` to
  `test_monterey_is_samples_only_not_no_source` and keep its three Monterey asserts. Restore the
  generic checks the old test had, which still guard the NO_SOURCE path for any future county:
  `no_public_source` is a `CountyReport` field, and `main()`'s source contains
  `no_public_source=reason` and not `error=reason`.
