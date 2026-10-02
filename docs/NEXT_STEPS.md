# Next steps (written 2026-10-02)

Context: two served-estimate changes in one week (XGB ensemble → per-beach lookup on 09-22,
lookup → logistic-on-lookup on 09-28). Both were decided on the forward served log, which is
the first time the metric that picked the model was the one users experience. The steps below
reorder the project around that fact. Numbers are measured on the 2026-10-02 `data/curated/`
snapshot (`observations.parquet`, `beaches.parquet`, `forecasts.parquet`,
`county_advisories_report.json`); re-measure before citing.

## Data-source inventory (as of 2026-10-02)

Every lab row in `observations.parquet` is enterococcus and reaches us by one of five routes.
Four of them are the SAME State Water Board database read four ways; only one is a county feed.

| `data_source` | What it is | Rows (all) | Newest | Role today |
|---|---|---|---|---|
| `BeachWatch` | data.ca.gov CKAN CSV dump of the state BeachWatch DB (curl'd in CI) | 476,223 | **2026-03-05** | History. The dump is frozen; nothing newer than March arrives this way. |
| `BeachWatch.SafeToSwim` | data.ca.gov CKAN datastore (`safetoswim_geomeans_2020-present`), same DB | 21,156 | 2026-09-29 | Main recent feed, ~weekly lag |
| `BeachWatch.Live` | HTML scrape of `beachwatch.waterboards.ca.gov/public/result.php`, same DB | 9,518 | 2026-10-02 | Fastest state route; near-daily in LA / SD |
| `CEDEN.SafeToSwim` | CEDEN datastore SQL, 38 beaches | 1,167 | 2026-06-08 | Marginal |
| `CountyDirect` | San Francisco Socrata `v3fv-x3ux` (date-keyed, gap-fill only) | 232 | 2026-09-29 | Only county-direct SAMPLE source; `INGEST_COUNTIES = {"San Francisco"}` |

The 15 county scrapers in `scripts/fetch_county_advisories.py` produce ADVISORIES, not samples
(SF is the single exception that also emits sample rows). Covariates are all third-party and
feature-only: Open-Meteo archive (precip, ERA5-Land solar/wind, UV), Open-Meteo Marine, USGS
NWIS streamflow, CDIP waves, NHDPlus hydrography, NOAA stations.

### What the inventory means on the ground

- **Orange County has gone dark in every state route since 2026-08-24.** It had ~700
  rows/month Mar–Jul (Live + SafeToSwim), then 82 rows in August and none since. Both state
  routes read the same DB, so this is upstream of us (OC → state reporting, or the state DB's
  OC ingest), not a connector bug. Consequence today: **0 of 224 OC beaches are served**
  (205 production, 146 of them with a sample < 90 days old that just missed the 30-day
  freshness gate). OC is the largest county in the registry. The county publishes results on
  ocbeachinfo.com; we scrape only its advisory sections, and today that parser failed too
  ("expected section markers not all found"). `ocbeachinfo.com` is 403 from this sandbox's
  proxy, so the county site was not verified here.
- **Monterey: 0 of 15 served**, newest state-routed row 2026-08-25, both candidate county URLs
  failed in today's scrape.
- **Served coverage is 375 of 726 production beaches.** 168 unserved production beaches have
  a sample < 90 days old; 160 of those are OC + Monterey.
- **Today's scraper run: 8 of 15 county scrapers errored** (SD `GetData` 405, OC markers
  missing, San Mateo 403, Monterey and Santa Barbara no live URL, Humboldt/Sonoma/SLO skipped
  because the LLM-extraction token was not set in that step). 59 advisories resolved
  statewide; `scraper_health.json` alarm `unresolved_count_today=7`, clean-day streak reset to 0.
- **Lab cadence is weekly almost everywhere** (median gap 7 days in 13 of 15 counties, 12 in
  Santa Cruz). Only San Diego's ddPCR programme samples near-daily.
- **Two assays, one label column.** San Diego is the only county running ddPCR (4,191 of its
  7,477 rows in 365d; 1 stray row in Mendocino). ddPCR flags 59.2% of samples vs 10.1% for
  culture. `method`/`units` exist in `observations.parquet` but are dropped before `beach_day`.

## The five steps

### 1. Scoreboard before model (formalise the shadow-and-promote loop)

Already have: `forecast_history.parquet`, `served_metrics` (forward D+1..3), `p_exceed`,
`p_exceed_lookup`, `p_exceed_ml` logged side by side.

- Write the promotion rule down in `backend/app/ml/PROMOTION.md`: a challenger must beat the
  incumbent on forward D+1..3 AUROC, Brier, AND within-beach AUROC over ≥ 28 served days, with a
  beach-cluster bootstrap 95% CI excluding 0 on each; promotion is a one-line config change.
- Make `served_metrics` report every logged column, not just the served one, so the shadow
  comparison is published daily in `system_health.json["served_metrics"]["by_estimator"]`.
- Add the three baselines as permanent columns: pooled rate, 365d per-beach lookup (already),
  persistence (last result exceeded → 1 else 0).
- Done when: a swap is a PR that changes one config line and cites the published table.

### 2. Keep the simple model on the critical path; XGB becomes a weekly challenger

Live logistic coefficients (2026-10-02): rain 0.70, last-result×freshness 0.67, last result
0.36, season 0.32. The 50-feature ensemble scored ~0.50 within-beach AUROC in serving.

- Move `app.ml.training` (ensemble + spatial backtests, ~60 retrains, most of the 170-min
  budget) out of `daily-forecast.yml` into a weekly `challenger-eval.yml`. Daily keeps
  `lookup_serving` (lookup + logistic, ~9 s) and writes `p_exceed_ml` from the last weekly
  model's saved artifact.
- Carry `label_method` (culture / ddPCR) into `beach_day` and `forecast_history`; stratify
  every published metric by it. Fit the logistic with a method term and check whether R (which
  already uses `enterococcus_action_ratio`) absorbs the difference.
- Done when: the daily job runs in < 20 min and the weekly job publishes the challenger table.

### 3. Ingestion: county feeds primary, state board as backfill, curated aliases over heuristics

- Add a county-direct SAMPLE connector for **Orange County** (ocbeachinfo.com results) and
  **Monterey** first — they are the two counties with zero served beaches today. Mirror-verify
  against the state route over the overlap window the way SF was (date-keyed match rate), then
  add to `INGEST_COUNTIES`. Then LA and SD (the near-daily programmes) so the serving anchor
  stops depending on `result.php` HTML.
- Canonical sample key = (`beach_id`, `sample_date`, `analyte`, `method`); value excluded.
  All five routes dedupe on it. Retire the `sample_time`-keyed collapse.
- Promote `method` and `units` into `beach_day`.
- Replace heuristic layers in `StationResolver` with the curated alias CSV as the primary
  index: export every current heuristic resolution into
  `_static_data/advisory_station_aliases.csv`, review the ~600 wrong-group cases from the
  decorated-posting replay, and demote substring/fuzzy to "log a candidate, never resolve".
- Serve from last-good inputs: a scraper failure must not block the day's forecast
  (today 8 of 15 failed and the job still produced a forecast — keep it that way, and make the
  scraper step its own job so its timeouts never eat the training budget).
- Done when: OC and Monterey beaches are served; `unresolved_count_today` alarm is driven by
  new names only.

### 4. Serve static files, retire the API tier

The product is a daily batch producing ~40 MB of parquet/JSON. The Render free-tier Docker
image bakes `data/curated/` at build time, which created the whole "committed ≠ served" class
of failures (fire-and-forget hook, `verify_deploy.py` re-triggering, 36-h fail-closed 503,
`GITHUB_TOKEN` pushes not triggering `deploy-backend.yml`).

- Publish `forecasts.json`, `beaches.json`, `advisories.json`, `system_health.json` as static
  files from the data commit (GitHub Pages under the existing web export, or an object store
  behind a CDN). `bake_web_static.py` already produces most of this.
- Point web and mobile at the static files; keep the FastAPI app only for anything that
  genuinely needs a query (currently nothing user-facing does).
- Delete `verify_deploy.py` re-trigger logic and the Render hook once no client reads the API.
- Done when: a data commit IS the deploy, and freshness is the commit timestamp.

### 5. Split daily serving from research in CI

- `daily-forecast.yml`: fetch → normalise → lookup+logistic → bake → publish → verify.
  Target < 20 min, `timeout-minutes` 45.
- `challenger-eval.yml` (weekly, `workflow_dispatch`): training, spatial backtests, challenger
  scoring, `holdout_predictions_*`, model card.
- `scraper-health.yml` already exists; move `fetch_county_advisories.py` into it (or its own
  job) so advisory scraping and sample serving fail independently.
- Done when: a scraper or training failure cannot cost a day's forecast.

## Framing to carry into county conversations

With weekly labels, ~6 of 7 served days are unverifiable in principle; the honest product is a
risk estimate with a credible interval. Where the model earns money for a county under budget
cuts is adaptive sampling: direct the crew to beaches whose Beta interval is wide or whose
estimate sits near a band cutpoint. `lookup_serving` already computes that interval.

## Keep as is

Date-keyed dedupe; floors as display rules, not model overrides; the NaN-safe JSON writer;
verify steps that fail the job after the deploy rather than before; `is_stale` on every
forecast row.
