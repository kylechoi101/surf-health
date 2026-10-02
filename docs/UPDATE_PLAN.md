# Shorelife update plan: data first, compare, then serve

Written 2026-10-02 against branch `claude/laughing-cannon-5d0ukr` (`90626df`). Companion to
`docs/NEXT_STEPS.md`, which has the reasoning; this file is the runbook.

**Run this locally.** The cloud session that wrote it could not reach any data host
(data.ca.gov, beachwatch.waterboards.ca.gov, data.sfgov.org, ocbeachinfo.com, Open-Meteo,
USGS were all denied by its network policy). Every number below marked *measured* was taken
from the committed `data/curated/` snapshot of 2026-10-02; everything else is a step for you
to run and check.

**The ordering rule.** Nothing changes what users see until Phase 2 is done and read.

| Phase | What | Changes what users see? |
|---|---|---|
| 0 | Setup, baseline tests, freeze the "before" snapshot | No |
| 1 | Data pipeline fixes, build the "after" snapshot | No (branch only) |
| 2 | Compare every model on before vs after data | No |
| 3 | Serving changes: scoreboard, static files, CI split, Render retirement | Yes, in stages |

Each step has **Do**, **Check** (an acceptance test you can run), and where it matters
**Rollback**.

---

## Phase 0 — Setup and the "before" snapshot

### 0.1 Environment

The backend requires Python 3.12 (`pyproject.toml`: `>=3.12,<3.13`).

```bash
cd surf-health
git fetch origin && git checkout claude/laughing-cannon-5d0ukr
cd backend
uv venv -p 3.12 .venv            # or: python3.12 -m venv .venv
VIRTUAL_ENV=.venv uv pip install -e ".[training,dev]" -c constraints.txt
.venv/bin/python -c "import xgboost, rapidfuzz, sklearn; print('ok')"
```

`rapidfuzz` must import. Without it the resolver's fuzzy layer is skipped silently and tests
pass locally that fail in CI (see CLAUDE.md, advisory resolution section).

**Check:** `.venv/bin/pytest -q` and write down the pass/fail count. Every later step must
leave that count no worse.

### 0.2 Keep snapshots out of git

```bash
cd surf-health
grep -q '^data/snapshots/' .gitignore || printf '\n# Local before/after snapshots for model comparison\ndata/snapshots/\n' >> .gitignore
```

### 0.3 Freeze the "before" data, built by today's `main` code on today's sources

Before and after must be built **on the same day from the same upstream pull**. Otherwise
the comparison mixes "new code" with "new lab results arrived".

```bash
DAY=$(TZ=America/Los_Angeles date +%Y-%m-%d)
git worktree add ../surf-health-main origin/main
cd ../surf-health-main/backend
# Separate venv: an editable install into the branch venv would repoint it at main's code
# and the "after" run would silently use the old pipeline.
uv venv -p 3.12 .venv && VIRTUAL_ENV=.venv uv pip install -e ".[training]" -c constraints.txt
# Run the exact pipeline command CI runs (copy it from .github/workflows/daily-forecast.yml,
# step "Run data pipeline", including the BeachWatch CSV + SafeToSwim fetch steps before it).
# Then the serving step so forecasts.parquet / forecast_history are consistent:
./.venv/bin/python -m app.ml.lookup_serving --curated ../data/curated/
mkdir -p ../../surf-health/data/snapshots/before-$DAY
cp -r ../data/curated/. ../../surf-health/data/snapshots/before-$DAY/
```

If you do not want to rerun `main` locally, use the committed `data/curated/` of the same day
from `origin/main` instead, and accept that sources may have moved a few hours.

**Check:** `ls data/snapshots/before-$DAY/{observations,beach_day,beaches,forecasts,precip_daily}.parquet`

---

## Phase 1 — Fix the data pipeline

Order inside Phase 1 matters: 1.1 and 1.2 change rows and columns, 1.3 changes advisories,
1.4 adds sources. Do 1.1 → 1.2 → 1.3 → 1.4 → 1.5, then 1.6 builds "after".

### 1.1 One canonical sample key across all five lab routes

**Measured problem (2026-10-02 snapshot, `observations.parquet`, 508,296 rows):**

| Symptom | Count |
|---|---|
| Rows sharing (beach, date, assay, value) with another row | 5,423 |
| Extra rows on that key, last 12 months | 475 of 28,802 |
| SafeToSwim and Live rows for the same sample, timestamps 1 minute apart | 137 pairs, 0 with equal `sample_time` |
| CountyDirect (SF) rows now duplicated by a state row on beach/date/value | 151 |

Every dedupe today is time-keyed or source-keyed, and they disagree:
`cli.py:303` (`beach_id, sample_time`), `cli.py:373`, `beachwatch_live.py:174-183`
(`_t` = time), `ceden.py:506-527` (`_sample_time_key`), `county_direct.py` (date-keyed).
A 1-minute disagreement between two state mirrors defeats all of them.

The 151 SF rows are a separate defect worth confirming first: `county_direct` is gap-fill
only, so once the state route caught up those rows should have been dropped. Either a state
route merges *after* county-direct in bundle construction, or the gap-fill check runs against
a frame that does not yet hold the SafeToSwim rows.

**Do:**

1. Confirm the 151: in `cli.py`, print the order in which `merge_live_into_observations`,
   the CEDEN/SafeToSwim merge and `merge_county_direct_into_observations` run inside
   `normalize_beachwatch_bundle`. If SafeToSwim merges after county-direct, that is the bug.
2. Add `backend/app/data/pipeline/sample_key.py`:
   - `assay_kind(method, units) -> "ddpcr" | "culture"` using the existing
     `exceedance.is_pcr_measurement` (do not write a second rule).
   - `CANONICAL_KEY = ["beach_id", "sample_day", "analyte", "assay_kind"]` and
     `with_canonical_key(df) -> DataFrame`, a copy with `sample_day = sample_date.normalize()`
     and `assay_kind` added. **Value is not in the key**, same reason as the
     SF fix in CLAUDE.md: a revised result must not become a second sample.
   - `collapse_physical_duplicates(df, priority)` keeps one row per key. Priority:
     the row with a real collection time over a date-only row, then source order
     `BeachWatch.Live > BeachWatch.SafeToSwim > BeachWatch > CEDEN.SafeToSwim > CountyDirect`
     for state-vs-state, **except** that a county row wins when no state row exists (gap-fill).
     Record the dropped rows' `data_source` in a `merged_from` column so it stays auditable.
   - Two genuinely different samples on one day at one station (morning + afternoon resample,
     different values, both with times > 30 min apart) must both survive. Implement this as:
     rows with the same key whose times are both present and more than 30 minutes apart are
     distinct samples; everything else is one sample.
3. Call `collapse_physical_duplicates` once, at the end of bundle construction, after every
   source has merged and **before** the precip/solar/marine joins. Leave the existing
   per-source dedupes in place for now; the final pass is the authority.
4. Tests in `backend/tests/test_sample_key.py`:
   - SafeToSwim 08:50 and Live 08:51, same value → one row, `merged_from` lists both.
   - Same, different value (a revision) → one row, Live's value kept.
   - 08:50 and 14:10, different values → two rows.
   - SF date-only row alone → kept; SF date-only + state timed row → state row kept.
   - ddPCR and culture on the same beach-day → two rows (different `assay_kind`).

**Check:**

```bash
.venv/bin/pytest -q tests/test_sample_key.py
.venv/bin/python - <<'EOF'
import pandas as pd
from app.data.pipeline.sample_key import CANONICAL_KEY, with_canonical_key
o = with_canonical_key(pd.read_parquet("../data/curated/observations.parquet"))
print("groups with >1 row:", (o.groupby(CANONICAL_KEY).size() > 1).sum())
EOF
```

Expect only the genuine same-day resamples to remain (a few hundred at most, all with times
more than 30 minutes apart). Write the before/after row counts into the Phase 1 report (1.6).

**Expected model impact: small.** The lookup and logistic read `beach_day`, which already
collapses each beach-day to its worst sample, so cross-source duplicates mostly do not
double-count there. The fix matters for per-sample features (lags, counts) and for honesty of
`observations.parquet`. Do not expect Phase 2 to show a big shift from 1.1 alone.

### 1.2 Carry the assay method into `beach_day`

**Measured:** San Diego is the only county running ddPCR (4,191 of its 7,477 rows in the last
365 days). ddPCR flags 59.2% of samples against 10.1% for culture. `beach_day` has
`exceeds_stv` and `enterococcus_action_ratio` but no method column: `build_beach_day_frame`
deliberately drops `method`/`units` at `beachwatch.py:643-646`.

**Do:**

1. In `build_beach_day_frame`, before the drop, add `label_method` = `assay_kind(method, units)`
   of the row that won the worst-sample collapse. Keep dropping raw `method`/`units`.
2. Add `label_method` to `schema_guard.EXPECTED_FEATURE_COLUMNS` (warn-only, as designed).
3. Add `label_method` to `served_metrics._HISTORY_COLUMNS` and to the row written into
   `forecasts.parquet` by `lookup_serving` (the beach's most recent `label_method`).
4. Do **not** add it to the XGB feature set or the served logistic yet. Phase 2 tests whether
   it helps; Phase 3 adopts it only if it does.

**Check:** `beach_day.label_method.value_counts()` shows two values and no nulls on rows with
an enterococcus result; the San Diego share of `ddpcr` matches the 365-day split above.

### 1.3 Advisory resolver: stop heuristic layers from resolving silently

**Correction to NEXT_STEPS.md:** the alias CSV is already second, not third. The code order
in `StationResolver.resolve` (`scripts/fetch_county_advisories.py:418-491`) is exact
`beach_name` → alias CSV → exact secondary index → substring → fuzzy. (CLAUDE.md states two
different orders in two places; the code is the truth. Fix the doc as part of this step.)
What remains is that the substring and fuzzy layers still *resolve*, so a wrong match posts a
warning on the wrong beach and clears the real one.

**Do:**

1. Measure first. From the last 30 committed `county_advisories_report.json` versions
   (`git log -p --follow data/curated/county_advisories_report.json`), count resolutions by
   method (`exact`, `csv`, `secondary`, `substring`, `fuzzy`). If the report does not carry the
   method per posting, add it to the report and run 1 day.
2. For every distinct (county, posted name) that resolved via `substring` or `fuzzy` in that
   window, review it by hand and add a row to
   `backend/app/data/pipeline/_static_data/county_beach_name_to_station.csv` if correct, or to
   `unmapped_advisory_venues.csv` if not.
3. Add a flag `--heuristic-mode {resolve,suggest}` (default `resolve` for this release). In
   `suggest` mode, substring/fuzzy hits are written to `unresolved_advisories.parquet` with a
   `suggested_beach_id` column and counted as unresolved by `evaluate_scraper_gate`.
4. After step 2 is merged, flip the default to `suggest`.

**Check:** run `fetch_county_advisories.py` in both modes on the same day; the resolved count
must be equal (every former heuristic hit is now an alias row). Keep
`test_substring_rule_rejects_single_incidental_token_match` green.

**Rollback:** `--heuristic-mode resolve`.

### 1.4 County lab-result connectors: Orange County, then Monterey

**Measured:** Orange County has had no rows in any state route since 2026-08-24 (it ran about
700 rows/month March–July). 0 of 224 OC beaches are served; 146 of its production beaches have
a sample under 90 days old and miss only the 30-day serving gate. Monterey: 0 of 15 served,
newest row 2026-08-25. Both state routes read the same database, so this is upstream.

**Do (Orange County):**

1. **Find out whether OC is still publishing.** Open https://www.ocbeachinfo.com/ in a browser
   with devtools → Network. If results after 08-24 are on the page, OC stopped reporting to
   the state, and a connector fixes it. If not, OC paused sampling or publication, and the fix
   is an email to OC Health Care Agency, not code. Record which.
2. Look for a JSON endpoint behind the page. San Diego's site (`sdbeachinfo.com`) serves
   `/Home/GetData`; if OC runs the same platform, try `ocbeachinfo.com/Home/GetData` with the
   same request shape the SD scraper uses (`fetch_san_diego_advisories`, line ~552; note SD
   returned **405** on 10-02, so check whether it now wants POST or GET).
3. Implement `fetch_orange_county_samples` in `fetch_county_advisories.py`, emitting
   `CountySample` rows into `_COLLECTED_SAMPLES` exactly like the SF collector (lines ~1368,
   ~1510): `county`, `beach_id` via `resolver.resolve_by_name`, `sample_date`, `analyte`,
   `value`, `exceeds_limit`, `source_url`. Units: OC is culture (MPN or CFU/100 mL); set them
   explicitly so `compute_exceeds_stv` judges against 104.
4. **Mirror-verify before ingesting**, the same way SF was verified: over March–July 2026, when
   the state route still had OC rows, join the direct rows to state rows on
   (beach_id, sample_day). Require ≥ 95% of state rows matched with identical value. Save the
   verification numbers in `docs/DEVLOG.md`.
5. Add `"Orange"` to `county_direct.INGEST_COUNTIES`.

**Do (Monterey):** same steps against the county's environmental health page. On 10-02 both
candidate URLs in the best-effort scraper returned non-200; find the current one first.

**Check:** after 1.6, OC and Monterey beaches appear in `forecasts.parquet`, and
`beaches.latest_official_sample_at` for OC is within 14 days.

**Rollback:** remove the county from `INGEST_COUNTIES`. Gap-fill only, so removing it can
never displace a state row.

### 1.5 Fix the scraper failures from 2026-10-02

From `county_advisories_report.json`:

| County | Error | First thing to try |
|---|---|---|
| San Diego | 405 on `sdbeachinfo.com/Home/GetData` | the endpoint's method or path changed; inspect in devtools |
| Orange | section markers not found | page layout changed; see 1.4 step 1 |
| San Mateo | 403 on `smchealth.org/beaches` | rate limit or user agent; the code already notes 403 after rapid scrapes |
| Humboldt, Sonoma, SLO | `GITHUB_TOKEN not set; skipping LLM extraction` | pass `GITHUB_TOKEN` into the advisory step's `env:` in the workflow |
| Monterey, Santa Barbara | no candidate URL returned 200 | find current URLs, update `fetch_best_effort_county` candidates |

**Check:** a local run of `fetch_county_advisories.py` reports no error for these counties.

### 1.6 Build the "after" snapshot and write the data-change report

Same day as 0.3, on this branch:

```bash
cd surf-health/backend
# Same pipeline command as CI, now with the fixes; then:
.venv/bin/python scripts/fetch_county_advisories.py --curated ../data/curated/
.venv/bin/python -m app.ml.lookup_serving --curated ../data/curated/
mkdir -p ../data/snapshots/after-$DAY && cp -r ../data/curated/. ../data/snapshots/after-$DAY/
```

Note the ordering trap in CLAUDE.md: county-direct reads the **previous** run's scrape. For
the snapshot, run the advisory fetch once before the pipeline so the new OC/Monterey sample
rows are on disk when the pipeline merges them.

Write `docs/DATA_CHANGE_REPORT_$DAY.md` with this table filled in (a 30-line script that
reads both snapshots is enough):

| | before | after |
|---|---|---|
| observations rows | | |
| beach_day rows | | |
| beach-days with an enterococcus label, last 365 d | | |
| positive labels, last 365 d (culture / ddPCR) | | |
| production beaches served | 375 | |
| served by county (OC, Monterey, SD, LA, …) | | |
| median sample age of served beaches | 3 d | |
| advisories resolved | 59 | |
| unresolved (unexpected) | 7 | |

**Check:** `pytest -q` is no worse than 0.1; `validate_forecast.py` passes on the after
snapshot against the before snapshot as `--previous`.

---

## Phase 2 — Compare every model on before vs after data

No serving change happens in this phase.

### 2.1 Write the decision rule first

Commit `backend/app/ml/PROMOTION.md` **before** running anything, so the result cannot shape
the rule:

> A challenger replaces the served estimate only if, on forward D+1..D+3 outcomes over the
> walk-forward window, it beats the served model on **within-beach AUROC** and **Brier**,
> with the beach-cluster bootstrap 95% CI of each delta excluding 0, on **both** the all-beach
> slice and the non-San-Diego slice. AUROC and AUCPR are reported but do not decide.
> Ties go to the simpler model.

Within-beach AUROC is the headline because global AUROC/AUCPR mostly measure "knows which
beaches are dirty", not daily skill (CLAUDE.md, measurement-gap section).

### 2.2 Extend the existing harness instead of starting over

`backend/scripts/compare_logit_challenger.py` already has the right skeleton: monthly
walk-forward refit, strictly-prior features, same_day and forward_1_3d outcomes, the
persistence floor applied as in serving, `within_beach_auroc`, `cluster_bootstrap_delta`, and
slices. Copy it to `backend/scripts/compare_all_models.py` and add arms.

| Arm | How it is scored | Notes |
|---|---|---|
| `pooled` | statewide 365-day base rate | floor of usefulness |
| `persistence` | 1 if last sample exceeded else pooled rate | the bar any model must clear on daily skill |
| `lookup` | `pairs["lookup"]` + persistence floor | already in the harness |
| `logit` | the served model, monthly refit | already in the harness; the incumbent |
| `logit_method` | `logit` plus a `label_method == ddpcr` term and its interaction with R | needs 1.2; run on **after** only, or on before with method derived from `observations` |
| `xgb_ensemble` | `XGBUndersampleEnsemble` | see 2.3 |
| `xgb_offset` | `XGBUndersampleOffsetEnsemble` with `beach_baseline_margin` | see 2.3 |

### 2.3 Scoring the XGB arms in the served regime

The ML must be scored the way it would serve: on day D, from the beach's last sample-day
features with stale bacteria history and today's rain. Do not score it on sample-day rows
only; that is the regime gap `model_truth.md` documents.

1. Training rows: `training._load_curated_training_frame(curated)` →
   `features.build_inference_features(frame)`. Train on sample-days in
   `[refit − 3 years, refit)`. Refit **quarterly**, not monthly: each fit takes minutes, and
   four refits over the 12-month window keeps the run near an hour.
2. `xgb_offset` trains on `two_tier.staleness_augmented_frame(features)`, margins from
   `two_tier.beach_baseline_margin`, as in `training.py`.
3. Scoring rows: for each eval pair (beach, D), take that beach's latest sample-day feature row
   with `sample_date < D`, set the recency feature to `D − last sample date`, and refresh the
   rain features for D. Reuse the serve-time helpers rather than reimplementing:
   `training._refresh_candidate_precip_features` and
   `training._refresh_candidate_streamflow_features`. If `_export_forecasts` builds candidates
   inline, factor that into `build_candidates_for_date(frame, forecast_date)` first and make
   `_export_forecasts` call it, so the comparison and production share one code path.
4. Apply the same persistence floor to every arm.
5. Where `forecast_history.parquet` overlaps, also score `p_exceed_ml` as it actually served.
   That is a check on step 3: your reconstructed `xgb_ensemble` should land close to it on the
   overlap. If it does not, step 3 has a leak or a gap; fix before trusting the arm.

### 2.4 Run it on both snapshots

```bash
cd surf-health/backend
for S in before after; do
  .venv/bin/python scripts/compare_all_models.py \
    --curated ../data/snapshots/$S-$DAY \
    --start 2025-09-01 --train-years 4 --bootstrap 300 \
    --out ../data/experiments/compare_all/$S-$DAY
done
```

### 2.5 Separate "the data changed" from "the scored population changed"

The after snapshot serves more beaches (OC, Monterey), so its eval pairs are a different
population. Report every metric three ways:

1. **Common pairs:** (beach, D) pairs present in both runs. Isolates the effect of fixed data
   on the same forecasts.
2. **Full:** each run on its own pairs.
3. **New beaches only:** pairs in after that are absent from before (mostly OC/Monterey).

Add `scripts/diff_comparisons.py` that reads both `--out` folders and writes
`docs/MODEL_COMPARISON_$DAY.md` with, per arm and per slice (all, non-SD, culture, ddPCR, wet,
dry, new beaches): within-beach AUROC, AUROC, AUCPR, Brier, sensitivity at specificity 0.87,
and the before→after delta with its bootstrap CI. Put the realized exceedance rate per risk
band per arm underneath, because that is what a beachgoer reads.

**What to expect, so a surprise is visible:**

- 1.1 alone: within ±0.005 on every metric (see 1.1 note).
- 1.2: no change for arms that do not use it; `logit_method` vs `logit` is the test of whether
  ddPCR needs its own term.
- 1.4: the visible change. OC is culture-only with a 6.6% exceedance rate over the last year,
  so the full-population base rate drops, AUCPR drops with it (arithmetic, not skill; see
  CLAUDE.md on base-rate dependence), and within-beach AUROC is the number to read.

**Check:** reconstructed `xgb_ensemble` on the served-log overlap within 0.02 AUROC of the
logged `p_exceed_ml`; `logit` arm reproduces the published walk-forward (forward AUROC ≈ 0.851,
within-beach ≈ 0.64) on the before snapshot.

### 2.6 Decide

Apply `PROMOTION.md` to the table. Three outcomes:

- **Logistic stays** (most likely): Phase 3 proceeds unchanged.
- **`logit_method` wins:** add the term to `logit_challenger.FEATURE_COLUMNS` and to
  `lab_history_features`/`build_features`, refit, and remember the CLAUDE.md warning that the
  lookup is computed twice and the serving step refuses to serve if they disagree.
- **An XGB arm wins:** it serves only through the existing router/fallback machinery, after a
  2-week shadow period on the live scoreboard (3.1).

---

## Phase 3 — Serving changes

### 3.1 Finish the live scoreboard

Most of it exists: `lookup_serving` already publishes
`system_health.json["serving_method"]["live"]` with a `head_to_head` of the served model
against `p_exceed_lookup` and `p_exceed_ml` (via `served_metrics.served_performance_for_versions`).

**Do:**

1. Add `within_beach_auroc` to `served_metrics._score` (import from `two_tier`).
2. Add a persistence column to the comparison: write `p_exceed_persistence` (last exceeded → 1
   else pooled rate) into `forecasts.parquet` and `_HISTORY_COLUMNS`, and pass it in
   `compare_columns`.
3. Add the beach-cluster bootstrap CI for each head-to-head delta (reuse
   `compare_logit_challenger.cluster_bootstrap_delta`; move it into `app/ml/` first).
4. `reportable` becomes true at 28 served days, matching `PROMOTION.md`.
5. Show the table on the web research page (shorelife-web already reads `serving_method`).

**Check:** `system_health.json["serving_method"]["live"]["forward_1_3d"]["head_to_head"]` has
`within_beach_auroc` and a `ci` per challenger.

### 3.2 Bake everything the mobile app reads into static files

Today the web bake (`bake_web_static.py`, curl'd standalone by shorelife-web's deploy) writes
`beaches.json` (850 beaches, 614 KB, **already with each beach's `forecast`**),
`parent_beaches.json`, `regional_summary.json`, `conditions.json`, `wind_grid.json` to
`https://kylechoi101.github.io/surf-health/data/`. The mobile app calls eight API routes; seven
read only the daily snapshot.

| Mobile call (`shorelife-mobile/lib/api.ts`) | Static source |
|---|---|
| `/parent-beaches` | `parent_beaches.json` (exists) |
| `/beaches` | `beaches.json` (exists) |
| `/beaches/{id}/forecast` | `beaches.json[].forecast` (exists) |
| `/system/health` | new `health.json` (copy of `system_health.json`, trimmed) |
| `/beaches/{id}/observations` | new `beach/{id}.json` |
| `/beaches/{id}/forecast/explain` | new `beach/{id}.json` |
| `/beaches/{id}/hourly` | new `beach/{id}.json` from `hourly_forecast.parquet` |
| `/beaches/{id}/tides` | new `tides/{station}.json`, see below |

**Do:**

1. In `bake_web_static.py` add `--with-details`, writing `beach/{id}.json` with `observations`
   (last 52 samples), `explain` (the drivers lookup_serving computes) and `hourly`. The baker
   cannot import the app package, so it must read these from parquet only.
2. Tides are fetched live from NOAA today (`services/tides.py`, 24 h cache). Add a pipeline step
   `--with-tides` that calls `fetch_tides` for every station `tides.py` maps beaches to and
   writes `tides.parquet` (72 h of predictions). The baker then writes `tides/{station}.json`.
3. Field parity: write a test that loads the API's `BeachSummary`/`ForecastRecord` pydantic
   models and validates `beaches.json` rows against them, so the static and API shapes cannot
   drift.

**Check:** `node scripts/validate-bake.mjs public/data` in shorelife-web passes, and every
`beach/{id}.json` validates against the API response models.

### 3.3 Mobile reads static first, API second

In `shorelife-mobile/lib/api.ts` (`API_BASE` at line 136, `request` at 139):

1. Add `STATIC_BASE = process.env.EXPO_PUBLIC_STATIC_URL ?? "https://kylechoi101.github.io/surf-health/data"`.
2. Each getter fetches the static file, and on a network error or non-200 falls back to the
   current API call. Keep the fallback until 3.6.
3. Cache `beaches.json` in memory per app session; the forecast getter reads from it instead of
   a second request.
4. Ship by EAS OTA update. Bump the version above 1.3.29.

**Check:** with the Render API URL pointed at a dead host in a dev build, the app still loads
the list, a beach detail, hourly and tides.

**Rollback:** OTA a build with the static branch removed.

### 3.4 Make `lookup_serving` independent of the training step

**This is the riskiest step and the reason the CI split is not a one-line move.**
`lookup_serving` does not create the forecast; it overwrites the `forecasts.parquet` that
`training.py` wrote (`lookup_serving.py:333`). Training decides the candidate set (which
beaches are served), writes `hourly_forecast.parquet`, the release-gate fields in
`system_health.json`, and `serving_calibration.json`.

**Do:**

1. Add `lookup_serving.build_candidates(curated, forecast_date)`: every `production` or `beta`
   beach with an enterococcus sample in the last 30 days (the current serving gate), with the
   columns `forecasts.parquet` carries today.
2. Behind `--standalone`, `lookup_serving` builds its own frame instead of reading training's.
3. Shadow it for 7 days: in the daily workflow, run `--standalone` into a temp folder and diff
   against the real output (same beaches, same `p_exceed` to 1e-9). Keep the diff in the job log.
4. Decide what happens to `p_exceed_ml` on days training does not run: leave it null. The
   Phase 2 harness and the weekly job score the ML; the daily live scoreboard compares the
   served model against lookup and persistence.
5. Move the release-gate inputs that serving still needs (anomaly gate vs yesterday) into
   `validate_forecast.py`, which already does most of it.

**Check:** 7 consecutive days of zero diff.

### 3.5 Split CI

1. `daily-serve.yml` (new; copy of `daily-forecast.yml` minus training):
   fetch → pipeline → advisory fetch → `lookup_serving --standalone` → validate → expire
   advisories → re-serve → bake → commit → dispatch web deploy. `timeout-minutes: 45`.
2. `challenger-eval.yml` (new): weekly cron plus `workflow_dispatch`. Runs `training.py` with
   the spatial backtests and `compare_all_models.py` over the trailing year; commits
   `data/experiments/compare_all/weekly/` and the model card.
3. `advisory-scrape.yml`: either fold the advisory fetch into the existing hourly
   `closures-refresh.yml` or keep it in daily-serve but `continue-on-error` with the forecast
   using the last good `advisories.parquet` (the 7-day window keeps postings live).
4. Disable the daily cron on `daily-forecast.yml` (keep `workflow_dispatch`) for two weeks,
   then delete it.

**Check:** a week of daily-serve runs under 30 minutes, and one forced scraper failure
(bad URL in a branch run) still publishes a forecast.

**Rollback:** re-enable the `daily-forecast.yml` cron.

### 3.6 Retire Render

Only after 3.3 has been live for 2 weeks and the Render dashboard shows API traffic near zero:

1. Remove the steps "Trigger Render deploy" and "Verify the fresh data actually went live"
   from the serving workflow, and `deploy-backend.yml`.
2. Remove the API fallback branch from `lib/api.ts`; OTA.
3. Suspend the service in the Render dashboard (manual). Keep `render.yaml` and the
   `Dockerfile` for local development, or delete them in a follow-up.
4. `verify_deploy.py` becomes a check that `https://kylechoi101.github.io/surf-health/data/health.json`
   carries today's `pipeline_freshness`.

### 3.7 Update the docs

- CLAUDE.md: the two conflicting resolver orders (1.3), the CI section (3.5), the deploy
  section (3.6), and a pointer to `PROMOTION.md` and the comparison report.
- `docs/NEXT_STEPS.md`: mark steps done with dates.

---

## Checklist

- [ ] 0.1 venv on 3.12, baseline test count recorded
- [ ] 0.2 `data/snapshots/` ignored
- [ ] 0.3 before snapshot
- [ ] 1.1 canonical key + tests; 151 SF duplicates explained
- [ ] 1.2 `label_method` in beach_day, history, forecasts
- [ ] 1.3 heuristic resolutions reviewed into alias CSV; `suggest` mode
- [ ] 1.4 OC publishing status known; OC connector mirror-verified; Monterey
- [ ] 1.5 scraper errors fixed
- [ ] 1.6 after snapshot + data-change report
- [ ] 2.1 PROMOTION.md committed before any run
- [ ] 2.2–2.4 compare_all_models on both snapshots
- [ ] 2.5 comparison report: common / full / new-beach
- [ ] 2.6 decision recorded
- [ ] 3.1 scoreboard: within-beach AUROC, persistence, CIs
- [ ] 3.2 static detail + tides files
- [ ] 3.3 mobile static-first, OTA
- [ ] 3.4 standalone serving, 7 days zero diff
- [ ] 3.5 CI split
- [ ] 3.6 Render retired
- [ ] 3.7 docs
