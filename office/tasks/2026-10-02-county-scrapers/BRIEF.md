---
task: county-scrapers
repo: /Users/kylechoi/surf_health-p1
worker: gemini
created: 2026-10-02
status: done
---

## Goal

Fix the county advisory scrapers that failed on 2026-10-02, add Orange County lab results
as a county-direct sample source, and make the advisory report say which resolver layer
matched each posting. The PM has already investigated every site live on 2026-10-02; the
facts below are verified, so implement against them rather than re-discovering.

## Verified facts (PM, 2026-10-02)

**San Diego** — `sdbeachinfo.com` now 301-redirects to an OutSystems app at
`https://cosdapps.sandiegocounty.gov/sdbeachinfo/`. The old `/Home/GetData` partials are gone
(405/404). Working, browser-free sequence (tested from Python httpx):
1. `GET https://cosdapps.sandiegocounty.gov/sdbeachinfo/` (sets cookies).
2. `GET .../sdbeachinfo/moduleservices/moduleversioninfo` → `{"versionToken": "<moduleVersion>"}`.
3. `POST .../sdbeachinfo/screenservices/CoSD_Beach_Water_CW/MainFlow/BlockNotification/ScreenDataSetGetEventsList`
   headers `Content-Type: application/json; charset=UTF-8`, `X-CSRFToken: T6C+9iB49TLra4jEsMeSckDMNhQ=`
   (OutSystems' public anonymous token), body
   `{"versionInfo":{"moduleVersion":<versionToken>,"apiVersion":"7ZgLP6EfhAWhyK1_ilFFoA"},"viewName":"MainFlow.Home","screenData":{"variables":{"EventTypeId":<N>,"_eventTypeIdInDataFetchStatus":1}},"inputParameters":{}}`
   → `data.List.List[]`, each with `Site.StationID` (e.g. `EH-010`), `Site.BeachName`,
   `Site.LocationName`, `Event.IssueDateTime` (ISO UTC).
   On 10-02: `EventTypeId=1` → 5 rows (EH-310 since 1997-09-01, MB-205, FM-070, EH-280, EH-010) =
   the page's 5 ADVISORIES; `EventTypeId=2` → 4 rows (IB-010/020/030/040 since 2025-10-13) =
   the page's 4 CLOSURES; `3` and `4` → 0 rows (page shows 0 WARNINGS).
   The `apiVersion` changes whenever the county republishes. Do NOT rely only on the constant:
   read `.../sdbeachinfo/moduleservices/moduleinfo` (lists the script URLs) or the homepage,
   fetch the `CoSD_Beach_Water_CW.MainFlow.BlockNotification.mvc.js` script, and regex
   `"screenservices/CoSD_Beach_Water_CW/MainFlow/BlockNotification/ScreenDataSetGetEventsList", "([^"]+)"`
   for the current apiVersion; fall back to the constant if discovery fails. If a response
   has `versionInfo.hasApiVersionChanged == true` or `exception`, set `rpt.error` with it.
   Confirm from that same JS (look for EventTypeId constants / the three notification
   buttons) whether 3 is WARNINGS; if it cannot be confirmed, treat every type other than 2
   as a Posting.

**Orange County** — advisories: the page `https://www.ocbeachinfo.com/` still has all three
markers, and the existing parser returned 3 correct postings locally on 10-02. The CI
"section markers not found" therefore comes from what the GitHub runner receives (likely a
bot challenge). Make the failure diagnosable: when markers are missing, put the HTTP status,
final URL, page `<title>` and the first 200 chars of cleaned text into `rpt.error`.
Lab results: `https://ocbeachinfo.com/data/` links a running-year spreadsheet named like
`https://ocbeachinfo.com/wp-content/uploads/Orange-County-Beach-Monitoring-Data-2026-9.15.2026.xlsx`
(name changes with each update; pick the newest `Orange-County-Beach-Monitoring-Data-*.xlsx`
by the date in its filename). One sheet, columns: `SampleAgencyCode, StationID, SampleDate,
SampleTime, SampleType, LabAgencyCode, LabBatch, AnalysisDate, AnalysisTime, ParameterCode,
AnalysisMethod, RL, MDL, Dilution, Result, Units, Qualifier, DetectedAboveMDL, QACode,
Comments`. `ParameterCode == "Enterococcus"` rows: 5,459 from 2026-01-05 to 2026-09-11,
methods `SM 9230 C` / `EPA 1600`, units CFU/100 mL, `Qualifier` in `= < ND > >=`; `ND` rows
have `Result` NaN (state stores these as 0 or 1, majority 1 → use **1.0**). All 180
`StationID`s match `beaches.station_code` for county `Orange` (case-insensitive).
PM mirror-verification over 2026-03-01..07-31 against state rows (to record in DEVLOG, not
re-derive): 3,363 state beach-days; 3,230 matched by the xlsx (96.0%); identical value on
94.1% of matched (95.1% counting ND as identical); exceedance label agreement 99.63%
(state 131 positives vs xlsx 119 — the gap is the state's mis-bound SafeToSwim rows, being
fixed in task canonical-sample-key).

**San Mateo** — `smchealth.org/beaches` is 404 (site moved). New page:
`https://smchealth.org/division/divisions/environmental-health-services/permits-business-services/water-protection-and-land-use/beach-creek-monitoring-program/`.
Per-site posting status is in a Google My Maps layer exported as KML:
`https://www.google.com/maps/d/kml?mid=1Y0U-5M0-ej_PnH8i1mJYFaXBlok-8fE&forcekml=1`
(41 `<Placemark>`s; site name in `<name>`, possibly CDATA-wrapped; status is the colour at the
end of `<styleUrl>` like `#icon-1701-A52714`; legend in the Document description:
Red = Posted, Green = Not Posted, Gray = Not Sampled, Orange = Not Sampled, Posted).
On 10-02: `A52714` (red) ×9 incl. "LINDA MAR #5 (at San Pedro Creek)", "PILLAR POINT #9",
"GAZOS CREEK"; `0F9D58` green; `757575` gray. Treat red and any orange hue as Posting.
Also parse the new page's "Beach and Creek Notices" text for closures, e.g. on 10-02:
"Rockaway Beach and Calera Creek are closed due to a Sanitary Sewer Overflow …" → Closure for
each named site (split on "and"/","), `started_at` = scrape date.

**Santa Barbara** — page moved to `https://www.countyofsb.org/ch-ocean-water-monitoring-program`
and renders client-side. Its map reads a public ArcGIS layer:
`https://services.arcgis.com/KkJhFbLnXVqahKz2/arcgis/rest/services/Ocean_Water_Quality_Points_Public/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=false&f=json`
→ 16 features with `Identifier` (= `beaches.station_code`, e.g. `WP0000004`), `Beach_Name`,
`Beach_status` (`Open`/`Warning`/…), `StatusDate` (epoch ms), `entercoccus_result` (sic, string
like `"<10"`/`"640"`). On 10-02 eight are `Warning` dated 2026-09-28. Map `Warning` → Posting,
any status containing `Clos` → Closure, `Open` → nothing. Resolve with
`resolver.resolve_by_station_code("Santa Barbara", Identifier)`. Promote Santa Barbara from
`BEST_EFFORT_COUNTIES` to a first-class scraper.

**Monterey** — no public source exists: the page (403 to non-browser clients) offers only a
phone hotline, and per-beach pages carry no status or results. Keep Monterey out of the
scrapers; replace its best-effort entry with a report entry whose `error` is
`"no public posting source (hotline only); see DEVLOG 2026-10-02"` and make sure it does not
count toward the scraper gate. Do not attempt WAF evasion.

**Humboldt / Sonoma / San Luis Obispo** — `GITHUB_TOKEN not set; skipping LLM extraction`.
The workflow's advisory step has no `env:`. Add to that step in
`.github/workflows/daily-forecast.yml`:
`env: { GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }} }` and add `models: read` to the job's
`permissions:` (keep `contents: write`). Check `backend/tests/test_daily_forecast_workflow.py`
for workflow assertions and extend it to assert both.

**Resolver layer reporting (plan step 1.3)** — `StationResolver.resolve_all_by_name` returns
`"live_list"` for three different layers (exact `beach_name` at ~line 421, exact secondary at
~451, token-guarded substring at ~489), so the report cannot tell exact from heuristic.

## In scope

1. San Diego rewrite per the facts above (keep the `CountyAdvisory` output shape; map
   EventTypeId 2 → `Closure`, others → `Posting`, and an `Advisory` whose `IssueDateTime` is
   more than 365 days old → `Chronic Posting` like the old "Chronic Advisory").
2. OC advisory diagnostics; OC sample collector `fetch_orange_county_samples` appending
   `CountySample` rows (county `Orange`, `analyte="ENTEROCOCCUS"`, `station_code=StationID`,
   `beach_id` via `resolver.resolve_by_station_code`, `sample_date=SampleDate`, `value` per the
   ND rule, `exceeds_limit = value > 104`, `source_url` = the xlsx URL), called from `main()`
   alongside the other collectors; only samples from the last 120 days are emitted. Add
   `"Orange"` to `app/data/pipeline/county_direct.py::INGEST_COUNTIES`.
3. San Mateo KML + notice scraper, Santa Barbara ArcGIS scraper, Monterey no-source entry,
   workflow `GITHUB_TOKEN` + `models: read`.
4. Resolver layer labels: return distinct kinds `exact`, `csv`, `secondary`, `substring`,
   `fuzzy` from `resolve_all_by_name`; keep every existing caller working (anything that
   tested for `"live_list"` must now accept `exact`/`secondary`/`substring`; keep the report's
   existing `matched_via_live_list`/`matched_via_csv`/`matched_via_fuzzy` keys for backwards
   compatibility, and ADD `matched_via_exact`, `matched_via_secondary`, `matched_via_substring`
   plus a per-county `heuristic_matches: [{"posted_name", "beach_id", "kind"}]` list covering
   every `substring`/`fuzzy` hit).
5. Flag `--heuristic-mode {resolve,suggest}`, default `resolve`. In `suggest`, substring/fuzzy
   hits are NOT resolved: they go to `unresolved_advisories.parquet` with a new
   `suggested_beach_id` column and count as unresolved in `evaluate_scraper_gate`.
6. Tests (in `backend/tests/test_fetch_county_advisories.py` or new `test_county_scrapers.py`),
   all offline with recorded fixtures under `backend/tests/fixtures/county_scrapers/`
   (save small trimmed real responses — the PM's live copies from 10-02 are in this task folder's `fixtures-src/`:
   `sd_events1.json`, `sd_events2.json`, `sm.kml`, `sm2.html` (new San Mateo page),
   `oc.html`, `sb_pts.json` (ArcGIS query result); build a tiny xlsx
   fixture in the test with openpyxl rather than committing the 1.4 MB file): SD parse of both
   types incl. chronic rule; SD apiVersion regex; SM KML colour mapping + notice closures;
   SB status mapping; OC xlsx → CountySample incl. ND and newest-file selection; resolver kinds;
   `suggest` mode moves a substring hit to unresolved with `suggested_beach_id`.

## Out of scope

- Changing resolver matching logic or thresholds (only labels + suggest mode).
- Ingesting Santa Barbara or San Mateo samples into observations (their state data is fresh).
- Any change under `backend/app/ml/`, web, mobile, or `data/`.
- Running the real advisory scrape against `data/curated/` (the PM does that).

## Allowed files

- backend/scripts/fetch_county_advisories.py
- backend/app/data/pipeline/county_direct.py
- backend/pyproject.toml (add `openpyxl` to the base dependencies)
- backend/constraints.txt (pin openpyxl if the file pins everything)
- .github/workflows/daily-forecast.yml (advisory step env + job permissions only)
- backend/tests/test_fetch_county_advisories.py
- backend/tests/test_county_scrapers.py
- backend/tests/test_daily_forecast_workflow.py
- backend/tests/test_county_direct.py
- backend/tests/fixtures/county_scrapers/**

## Allowed packages

- openpyxl (into the worktree venv: `cd /Users/kylechoi/surf_health-p1/backend && VIRTUAL_ENV=.venv uv pip install openpyxl`)

## Acceptance

```bash
cd /Users/kylechoi/surf_health-p1/backend
.venv/bin/pytest -q tests/test_county_scrapers.py tests/test_fetch_county_advisories.py tests/test_county_direct.py tests/test_daily_forecast_workflow.py   # all pass
.venv/bin/pytest -q                       # no new failures vs the suite before this task
.venv/bin/ruff check app tests scripts    # clean
# live smoke (network) — writes nothing:
.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "scripts")
import fetch_county_advisories as f, httpx, pandas as pd
b = pd.read_parquet("../data/curated/beaches.parquet")
r = f.StationResolver(b) if hasattr(f, "StationResolver") else None
c = httpx.Client(follow_redirects=True, timeout=30)
for fn in ("fetch_san_diego_advisories", "fetch_san_mateo_advisories", "fetch_santa_barbara_advisories", "fetch_orange_county_advisories"):
    adv, rpt = getattr(f, fn)(c, r)
    print(fn, len(adv), rpt.error)
f.fetch_orange_county_samples(c, r); print("OC samples", len(f._COLLECTED_SAMPLES))
PY
# expect: SD 9 (5 advisories + 4 closures as of 10-02), SM >= 9, SB 8, OC 3, all error None; OC samples > 0
```
(If `StationResolver`'s constructor differs, adapt the smoke script; report what you ran.)

## Phases

### Phase 25
Deliverable: San Diego OutSystems scraper and Santa Barbara ArcGIS scraper with offline fixture tests passing, and the live smoke output for those two.

### Phase 50
Deliverable: San Mateo KML+notice scraper, OC advisory diagnostics, Monterey no-source entry, workflow GITHUB_TOKEN + `models: read` with workflow test.

### Phase 75
Deliverable: `fetch_orange_county_samples` + `"Orange"` in `INGEST_COUNTIES`, openpyxl dependency, tests.

### Phase 100
Deliverable: resolver layer kinds + report fields + `--heuristic-mode`, tests, and all Acceptance commands pass with output pasted.

## Corrections

(appended by the PM; newest last; each entry dated)

### 2026-10-02 18:40 — added before phase 25 (PM)

**C1. Ventura parser emits prose fragments as beach names.** The CI-committed
`system_health.json["scraper_gate"]` for 2026-10-02 lists all 3 "unexpected unresolved" names
as Ventura sentence fragments: `"cate that water quality at the following beach"`,
`"on either side of each posted sign. This beach"`, `"ducted once per week on Tuesdays. When a
beach"`. They inflate the scraper gate with non-postings. In the Ventura scraper (find it with
`grep -n "Ventura" scripts/fetch_county_advisories.py`), reject candidate names that start
with a lowercase letter, contain a sentence break (`". "`), or exceed 10 words; count rejects
in a new `rpt.rejected_fragments` int (and the JSON report) instead of passing them to the
resolver. Add a test with those three strings. Do this in phase 50.

### 2026-10-02 19:55 — phase 50 blocked, retry (PM)

The first phase-50 run died mid-way on a network error (`write: broken pipe` to the Gemini
API, rc=3). Partial edits from that run are in the working tree (San Mateo fixtures
`sm.kml`/`sm2.html` under `backend/tests/fixtures/county_scrapers/`, some changes in
`fetch_county_advisories.py`). Inspect `git diff` first, keep what is correct, and complete
phase 50.

### 2026-10-02 20:05 — phase 50 moved to Cursor (PM)

Gemini failed twice on network drops to Google (broken pipe; connection reset during the agent's
eligibility check). Phase 50 now runs on Cursor. Partial phase-50 edits from the Gemini runs
are in the working tree; inspect `git diff`, keep what is correct, and complete phase 50.

### 2026-10-02 20:40 — before phase 75 (PM)

1. **San Mateo must resolve through `StationResolver`, not an inline scanner.** `_sm_build_lookup`
   / `_sm_lookup_beach_id` do an unguarded `key in norm` longest-key scan — the single-token
   wrong-beach failure class the 2026-08-05 resolver hardening removed (CLAUDE.md, "Substring
   rule was producing wrong-beach advisories"). It was carried over from the old page scraper,
   but the KML now gives one clean site name per placemark. Remove both helpers; emit
   `CountyAdvisory(county="San Mateo", area=<placemark name>, station_code=None, ...)` and let
   the normal resolution path (`resolve_advisories` → `resolve_all_by_name`) resolve them, so
   the alias CSV precedence, the anchoring guard and phase 100's per-layer accounting all
   apply. Names it cannot resolve go to unresolved — the PM reviews them into the alias CSV.
2. Trim `sm2.html` and `oc.html` fixtures to the minimum the tests need (the notices block /
   the CLOSURES…ADVISORIES section plus enough markup to parse) — target < 30 KB each.
3. Then do phase 75 as written.

### 2026-10-02 21:05 — before phase 100 (PM)

Answer to your open question: do the 20:40 correction (items 1 and 2: San Mateo through
`StationResolver` with the inline scanner removed; fixtures trimmed < 30 KB each) **first** in
phase 100, then the phase-100 work. Phase 100's acceptance includes both. Report the live San
Mateo smoke after the change: how many of the 11 resolve and by which resolver kind.
