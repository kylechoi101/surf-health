# Surf Health / Shorelife — Claude Code context

## Repo layout

```
backend/           Python FastAPI service + ML pipeline
  app/
    core/config.py          Settings (data_dir, curated_dir, precip_cache_dir)
    data/
      connectors/
        hydrology_sources.py   UsgsNwisConnector, OpenMeteoHistoricalPrecipConnector,
                               OpenMeteoHistoricalSolarWindConnector (ERA5-Land archive)
      pipeline/
        county_direct.py       County-direct samples -> observations (SF recency; date-keyed)
        cli.py                 Main pipeline entry point (--normalize-beachwatch, --with-hydrology,
                               --with-solar-wind, etc.)
        features.py            Feature column lists + add_temporal_features()
        solar_wind.py          aggregate_solar_wind_windows() — forecast-safe daily summaries
        marine_microbiology.py compute_beach_shore_azimuth(), compute_beach_coastal_features(),
                               build_marine_microbiology_daily()
        _static_data/
          ca_piers.csv          31 hand-curated CA piers (lat/lon/county)
          ca_estuary_mouths.csv 27 CA estuary mouths
    ml/
      training.py              --curated --spatial-backtests --spatial-strategy [quick|shortlist|full]
      feature_agent/
        agent_features.py      AGENT_BUILDERS list (currently empty after pivot)
mobile/            Expo/React Native app (shorelife brand)
web/               Next.js app (served at https://kylechoi101.github.io/surf-health/
                   — shorelife.app is NOT the domain; it does not resolve)
data/
  curated/         beach_day.parquet, beaches.parquet, solar_wind_daily.parquet, ...
  raw/cnrfc/       Open-Meteo cache (openmeteo/, openmeteo_solar_wind/ subdirs)
```

## Data pipeline

Run from `backend/` with `.venv/bin/python -m app.data.pipeline.cli`.

Full refresh (what CI does):
```
python -m app.data.pipeline.cli \
  --normalize-beachwatch --stations-csv ... --results-csv ... --advisories-csv ... \
  --merge-ceden --max-ceden-rows 50000 \
  --with-beachwatch-live --beachwatch-live-days 30 --with-county-direct \
  --with-external-covariates --with-hydrology --with-solar-wind
```

`--with-solar-wind` fetches ERA5-Land hourly cloud/shortwave/UV/wind via Open-Meteo,
aggregates to forecast-safe daily summaries, and merges 11 marine-microbiology features
into beach_day: `shore_normal_wind_ms`, `solar_inactivation_index`, `cloud_cover_24h_mean`,
`shortwave_24h_sum`, `uv_index_24h_max`, `wind_speed_24h_max`, `days_since_sunny`,
`dist_to_pier_km`, `is_near_pier`, `dist_to_estuary_km`, `is_near_estuary_mouth`.

Cache persists per (lat_0.1°, lon_0.1°, date_range) parquet in `data/raw/cnrfc/openmeteo_solar_wind/`.

`--with-surf` fetches the Open-Meteo **Marine** forecast (waves + primary/secondary swell
trains: height/period/direction) for surf-spot beaches and writes `surf_now.parquet`
(current conditions, one row/spot) + `surf_daily_forecast.parquet` (per-spot, per-day range +
dominant swell). Surf spots come from the curated `surf_spot_aliases.csv` matched onto beaches
via `surf_spots.apply_surf_aliases()`, which also adds `surf_name` / `is_surf_spot` /
`surf_latitude` / `surf_longitude` to `beaches.parquet` (display-only; official `name`/coords
untouched). Marine cache: `data/raw/cnrfc/openmeteo_marine/`, keyed by (coord, issue_date).
Aggregation lives in `pipeline/surf_conditions.py`. Note: surf heights are honest offshore
significant wave heights in feet — translating to breaking-wave *face* height per spot needs
per-spot swell-window modeling (deferred fast-follow).

### Data-quality corrections (applied in normalization, 2026-06-01)

- **PCR exceedance threshold** (`pipeline/exceedance.py`): San Diego ddPCR/MCB-ddPCR samples
  report enterococcus in **copies/100mL** and must be judged against **1413 copies**, NOT the
  104 culture STV. `is_pcr_measurement` (method contains "pcr" OR units contain "copies") +
  `compute_exceeds_stv` are wired into both beachwatch + ceden normalizers. The flat 104 had
  false-flagged ~98% of PCR samples.
- **County corrections** (`pipeline/county_corrections.py`): jurisdiction-as-county fixes
  (`"Long Beach City"` → `"Los Angeles"`). Note `region` is the regulatory **Regional Water
  Board** (San Diego board covers south Orange County) — NOT the county; the apps label by
  county only.
- **Place-name spelling** (`pipeline/spelling.py`): Tijana→Tijuana, Oceanisde→Oceanside,
  storn→storm, oultet→outlet (display name/beach_name/station_name; `beach_id` keys untouched).
- **One-time-station cap** (`pipeline/station_quality.py`): `support_status_for` marks stations
  whose sampling history spans **<90 days** as `unsupported` (one-time incidents, out of training).
- **Negative enterococcus values** (−1000 sentinels) are dropped → NaN in normalization.

### County-direct sample source — SF recency fix (2026-07-30)

`--with-county-direct` (`pipeline/county_direct.py`) makes
`county_direct_samples.parquet` a **fourth observations source**. That file — written by
`scripts/fetch_county_advisories.py` — was previously a dead end: it fed the advisory/closure
layer only, and nothing read the sample rows.

- **The bug it fixes:** San Francisco publishes weekly results to its own Socrata dataset
  (`data.sfgov.org` resource `v3fv-x3ux`) within days, but reports into the State Water Board —
  the route `observations.parquet` is built from — weeks late. On 2026-07-30 every state-routed
  source held **zero** SF rows for July while the direct feed already had 07-06/13/20/27. SF's
  serving anchor read 30 days stale next to an **active 07-27 posting** the advisory layer had
  published from the same samples. Merging adds 68 SF beach-days incl. **12 exceedances** the
  model had never seen, moving 17 of 21 SF beaches from ~30d stale to 3d.
- **The merge key is the sample DATE, not `sample_time`.** The state feed carries real collection
  times (`10:25:00`); this feed is date-only, so the same physical sample hashes apart on
  `sample_time` and `merge_live_into_observations`'s time-keyed collapse would NOT catch it.
  Measured over the overlap window (04-20..06-30): all **206/206** state SF rows match a direct
  row on (beach_id, date) with an identical value — i.e. time-keying would have inserted 206
  duplicates. Same mirror-bug class as `738c99d`'s "1600" vs "EPA 1600", new guise. Value is
  deliberately OUT of the key too, so a revised result can't slip in as a second beach-day.
- **Gap-fill only, never displaces:** a direct row whose (beach_id, date, analyte) any source
  already covers is dropped. Enterococcus only (SF's coliform-driven postings — e.g. Baker Beach
  East 07-27, COLI_FECAL 4200 with entero at 10 — stay advisory-only, so the two layers will not
  agree beach-for-beach). Counties are allowlisted (`INGEST_COUNTIES`, SF only): Sonoma/Humboldt
  are in the parquet but months stale and report freshwater indicators.
- **Ordering:** runs inside bundle construction, right after the live merge — it must precede the
  precip/solar/marine joins or the new rows land in `beach_day` with every covariate all-NaN.
  Consequence: it reads the **previous** run's scrape (`fetch_county_advisories.py` runs after the
  pipeline in the daily workflow), so SF lands at ~4d lag rather than 3. Deliberate trade.
- **`latest_official_sample_at` is now recomputed after every late merge**
  (`cli.py::refresh_latest_official_sample_at`). It is what the apps render as "last sampled", and
  it was computed once during bundle construction — so `--with-beachwatch-live`'s rows never
  updated it. Measured on the shipped `beaches.parquet`: **75 beaches carried a stamp BEHIND their
  own observations** — Orange County by up to **63 days** (stamp 04-29, newest row 07-01), LA and
  Santa Barbara by ~7 — rising to 92 once the SF rows merge. Those beaches had fresh rows in the
  label frame while the UI showed them two months stale. This is an independent **pre-existing**
  bug that `--with-beachwatch-live` introduced, not an SF one; the fix clears all of them (92 → 0).

### Advisory name resolution + G.1 gate severity (2026-08-05)

The 2026-08-05 daily run failed at `fetch_county_advisories.py` with 5 unresolved of 49 scraped
(10.2% vs the 10% ratio; the absolute floor is `> 5`, so only the ratio tripped). The step runs
BEFORE ML training, so one unmatched beach name cost the whole day's forecast. Three separate
problems, fixed separately:

- **Resolver blind spot — `beach_name` is a site GROUP, not a site.** `StationResolver`'s Layer A
  indexed `beach_name` only. Two failure modes: Marin's `GREEN BRIDGE` (a `production` beach)
  carries the county-wide placeholder `All_Marin_County` in `beach_name`, so it was invisible and
  its posting was dropped every run since 07-31 (its sibling Inkwells resolved only because a
  SECOND registry row happens to carry `beach_name="Inkwells"`); and every site sharing a
  `beach_name` collapsed to one arbitrary `beach_id`, so **"Del Valle WEST Swim Beach" resolved
  onto the EAST beach** — the west posting landed on the wrong beach and west showed clean. Fixed
  with an exact-only secondary index on the site-level `name`/`station_code` (~1.4k keys; the 13
  statewide keys that map to >1 beach are dropped as ambiguous rather than resolved arbitrarily).
- **Substring rule was producing wrong-beach advisories.** Layer A.1 accepted any containment over
  a 4-char floor, so **"Shinn Pond at Alameda Creek Trails"** (a Fremont freshwater pond) resolved
  onto **"Alameda Point Encinal Beach Mid"** on the single shared token `alameda`. Now requires
  ≥2 shared tokens, and an ambiguous match (several qualifying keys) is a miss rather than a
  dict-order coin flip. A dropped advisory is a miss; a mis-mapped one posts a warning on the
  wrong beach AND clears the real one.
  - **The guard is ANCHORING, not a raw shared-token count** (`_match_is_anchored`). A match
    qualifies on ≥2 shared tokens **or** on one side being a token-PREFIX of the other. The prefix
    arm is load-bearing: `_normalize_name` strips `beach/creek/bay/point/park/state/...`, which
    collapses **131 of 324 (40%)** roster keys to a single token (`doheny`, `zuma`, `crown`), and
    counties post decorated names (`"Doheny State Beach - 100 feet up and down coast of the San
    Juan Creek outlet"`). A shared-tokens-only rule can never reach 2 against those — measured, it
    silently dropped **1,773** correct resolutions across all 15 counties, including the Crown and
    Keller EBRPD beaches this very fix targets. `"alameda"` is a token of `"shinn pond alameda
    trails"` but does not lead it, which is what still rejects the mis-map.
  - **Multiple qualifying keys are RANKED, not coin-flipped**: a key that leads the posting beats
    one that merely appears inside it (picks Cardiff over San Elijo for `"Cardiff/ San Elijo
    Lagoon - ..."`), then the more specific key wins (`"huntington city"` over `"huntington"`).
    Only a tie at the top rank is a miss. **Known limitation:** `"<feature> on <beach>"` phrasing
    ranks wrong — `"Santa Monica Canyon on Will Rogers State Beach"` picks Santa Monica, because
    it is structurally identical to the Cardiff case with the opposite correct answer. Use the
    alias CSV for those.
  - **The fuzzy layer needed the same guard, and this is a trap for the next person.**
    `rapidfuzz.fuzz.token_set_ratio` scores **100** whenever one token set is a *subset* of the
    other, so guarding only the substring layer left the identical mis-map fully intact
    (`token_set_ratio("shinn pond alameda trails", "alameda") == 100`, 39-point gap to the
    runner-up). A fuzzy candidate must now also be token-anchored (≥2 shared tokens) **or**
    near-identical end-to-end by the length-sensitive `fuzz.ratio` (≥90), which scores that pair
    43.8. Costs nothing measurable — the fuzzy layer matched **0** advisories in the last
    committed run (45 live_list, 1 csv). ⚠️ **`rapidfuzz` is an optional import**: without it
    installed the whole layer is skipped, so a dev sandbox silently passes tests that CI fails.
    `test_substring_rule_rejects_single_incidental_token_match` now asserts `HAS_RAPIDFUZZ`.
  - **Layer order: exact `beach_name` → alias CSV → exact secondary → substring → fuzzy.** The
    curated alias outranks the *secondary index*, not just the heuristics, because a site-level
    `name` can collide with a different beach's group name and only a human can adjudicate: LA has
    two Mother's Beaches ~40 km apart (Long Beach's site is literally `"Mothers' Beach"`; Marina
    del Rey's carries it in `beach_name`), and neither index looks ambiguous on its own.
  - **Measured two ways.** Exact registry names (all 850 beaches × both name columns): 1017
    identical, 683 newly-correct, 0 lost. That corpus is exactly what the new exact index is built
    from, so it is blind to substring/fuzzy regressions — the review of this change caught the
    1,773-row loss above precisely because it was invisible there. The honest test is a
    **decorated**-posting replay (registry names × 8 realistic county qualifiers, 13,384 probes):
    correct-group **7278 → 8214**, wrong-group **1148 → 615** vs `main`. The 9 newly-wrong vs the
    mid-PR state are 2 underlying strings: the deliberate Mothers alias and the `on`-phrasing
    limitation above.
- **Layer order is now confidence order:** exact `beach_name` → exact secondary → **alias CSV** →
  token-guarded substring → fuzzy. The curated alias file deliberately outranks the heuristic so
  an operator can correct a bad match by adding a row. Alias rows may now **fan out**: repeated
  `(county, beach_name_normalized)` keys accumulate, and `resolve_advisories` replicates the
  posting onto every covered `beach_id`. EBRPD's one district-wide "Crown Beach Regional
  Shoreline" notice covers all **6** sampled Crown Beach points; resolving to one would leave
  five showing clean. `resolve_by_name` stays single-valued for `persist_samples` — a scraped MPN
  reading is one physical measurement and must not be duplicated.
- **Gate severity split (`evaluate_scraper_gate`).** The numerator is now UNEXPECTED unresolved
  only: venues with no possible `beach_id` live in `_static_data/unmapped_advisory_venues.csv`
  (still scraped, still logged, excluded from floor/ratio) — otherwise they pin the counter at
  the threshold and any single new posting fails the run, which is exactly what happened. The
  allowlist is a deferral, not a mute: `review_by` is enforced, an expired row starts counting
  again, and a name not on the list always counts. A **soft** trip (floor/ratio) now publishes
  `system_health.json["scraper_gate"]`, returns 0, and lets the pipeline finish;
  `scripts/verify_scraper_gate.py` fails the job **after** the commit AND after the Render deploy
  (that step is `if: success()`, so failing earlier would commit a fresh forecast and then skip
  shipping it). Only a **hard** trip aborts in place, before `_export_forecasts` builds the
  advisory floor: >15 unexpected unresolved, or a county that resolved advisories
  last run and resolves none now (`detect_county_resolution_regressions`, baselined against the
  previous run's committed `county_advisories_report.json` — a volume-independent schema-drift
  signal the ratio only approximated). `--strict-gate` restores exit-on-soft for local debugging.
  - ⚠️ **What the hard abort actually protects — corrected 2026-08-26.** This section, and the
    workflow comment beside the step, used to justify the abort as protecting "the training step
    that consumes `advisory_active_prev_14d`". **Training does not consume it.** The column is
    built into `beach_day.parquet` by `_advisory_temporal_features`, and then dropped by
    `_load_curated_training_frame`'s allowlist — verified: neither it nor `days_since_advisory_
    closed` appears among the **194** columns `_model_feature_columns` returns. `training.py:2767`
    still assigns both onto forecast candidates, where `reindex(columns=features.columns)`
    discards them. No model has ever read an advisory.
  - **The abort is still warranted, on a stronger and more immediate ground: the SERVING floor.**
    `_export_forecasts` (training.py:4589) forces `p_exceed` to at least `_HIGH_THRESHOLD` (0.20)
    — i.e. the band to **High** — whenever `advisory_active_recent_for_floor` (a serve-path
    column set at training.py:3434, *not* a model feature despite what the comment beside it
    says) or `_display_active_advisory_ids` fires. On the shipped 2026-08-07 forecast that is
    **21 of 541 rows (3.9%)**, and all 21 are High *because of the floor* — nothing else put them
    there. So a mis-resolved advisory does not merely lose a warning: it floors the **wrong**
    beach to High and leaves the real one showing its unfloored band. That is exactly the
    wrong-beach failure the 2026-08-05 resolver work targeted, and it reaches users the same day
    with no model involvement at all.
  - **Consequence for the placement.** "Before training" is the right ordering for the wrong
    stated reason: what must precede the gate is `_export_forecasts`, not feature construction.
    Anything that reorders these steps should preserve *that* dependency.

### Pipeline robustness guards (2026-06-11)

- **CEDEN negative-value guard** (`pipeline/ceden.py`): the CEDEN/SafeToSwim normalizer now nulls
  negative `value`s before exceedance + `dropna`, matching the long-standing beachwatch guard
  (`beachwatch.py:381`). Previously only beachwatch dropped −999/−1000 "not analyzed" sentinels, so
  CEDEN-sourced negatives could leak into training. Takes effect on the next daily refresh.
- **Atomic cache writes** (`connectors/hydrology_sources.py`): all per-coord parquet cache writes go
  through `_atomic_to_parquet` (write `.tmp` → `os.replace`), so a crash mid-write can no longer
  leave a corrupt cache that later reads as garbage.
- **Output schema guard** (`pipeline/schema_guard.py`): `validate_beach_day` runs before the
  `beach_day.parquet` write — HARD-raises only on an empty frame or missing primary keys
  (`beach_id`, `sample_date`, `exceeds_stv`); WARN-only if an expected feature column is absent/
  all-NaN (a connector outage legitimately yields all-NaN, so it must not fail the daily job).
- **Holdout prediction artifacts** (`ml/training.py` + `ml/evaluation.py`): the production winner's
  held-out (label, probability) pairs are persisted to `data/curated/holdout_predictions_temporal
  .parquet` / `..._spatial.parquet`, and `sensitivity_at_specificity(...0.87)` is recorded into
  `system_health.json` (`production_metrics["sensitivity_at_spec_0.87"]` + spatial equivalents) —
  closing the long-standing "Searcy sensitivity is unverifiable" gap. As of the 2026-06-11 daily run
  (`c64a0b5da`) these artifacts EXIST on disk and the operating points are populated; any other
  operating point recomputes from the parquet with no retrain.

### Public-readiness hardening (2026-06-11, post-audit round 2)

An external ML-reliability audit was adversarially verified (16-agent workflow); confirmed
findings were fixed in this round:

- **Any-exceedance daily labels** (`pipeline/beachwatch.py` `build_beach_day_frame`): same-day
  samples now collapse to the WORST sample (max `exceeds_stv`, then max value, then `sample_time`)
  instead of `.tail(1)` chronologically-last. The old rule flipped 1,021 contaminated beach-days
  (120 beaches, ~440 in the 1095d window, 100% false-negative direction) to "safe".
- **Forecast-time precip/streamflow refresh** (`ml/training.py`
  `_refresh_candidate_precip_features` / `_refresh_candidate_streamflow_features`): forecast
  candidates previously froze ALL rain features at the last lab sample's values (12–37 days
  stale); they now refresh from `precip_daily.parquet` / `streamflow_daily.parquet` (already
  regenerated daily through the forecast date) via the same beach→station links the pipeline
  uses; rain-policy flags recompute via `add_rain_policy_features`; derived lag/interaction
  features recompute downstream in `build_inference_features`. No-match rows keep the frozen
  value (env-persistence) and are counted in a stderr warning.
- **Release gate now BLOCKS publication** (`--enforce-release-gate`, set in CI): if
  `public_release_eligible` is false, `forecasts.parquet`/`hourly_forecast.parquet` are NOT
  overwritten (last-validated keeps serving), blockers land in `system_health.json
  ["release_gate"]`, the data commit still happens (auditability), and
  `scripts/verify_release_gate.py` then FAILS the job (no continue-on-error) → notify-failure
  issue. `validate_forecast.py` tolerates the deliberately-frozen stale forecast date ONLY when
  this run's fresh health payload says publication was blocked (fail-closed otherwise). The gate
  also fails CLOSED on zero-fold spatial backtests.
- **Forecast anomaly gate** (`scripts/validate_forecast.py` + `--previous` snapshot in CI):
  all-safe collapse (every `p_exceed` below the Low threshold), mean-shift >4× either way vs the
  previous run, and non-Low band-count collapse now fail validation.
  `SKIP_FORECAST_ANOMALY_CHECKS=1` is the deliberate-change escape hatch.
- **Serve-time staleness** (`repositories/serving_repository.py`, `schemas/domain.py`,
  `api/routes.py`): forecast records carry `is_stale` (age > 48h via un-truncated hours from
  `forecast_generated_at`, fallback `forecast_date`; unknowable age on a fallback row ⇒ stale);
  `forecast_generated_at` is Optional and never fabricated; forecast/beach/advisory responses
  use `max-age=3600, stale-while-revalidate=600` (was 86400); advisory windows are judged as-of
  the snapshot's own `generated_at` (not `datetime('now')`), removing the asymmetric decay of
  warnings out of a stale snapshot. Web + mobile render tiered staleness (≤24h fresh, 24–48h
  amber notice, >48h/unknown strong warning + greyed band UI; advisories never greyed).
- **Statistical rigor** (`ml/evaluation.py`, `ml/training.py`): spatial metrics in
  `system_health.json` now carry cluster-bootstrap `aucpr_ci_low/high` (resampling unit = fold;
  the 6-fold pooled county AUCPR 95% CI measured [0.32, 0.59]); holdout predictions persist for
  EVERY backtested candidate (`model` column in `holdout_predictions_spatial.parquet`); the
  winner swap needs gap > 0.01 AND a paired cluster-bootstrap 90% CI of the county-AUCPR gap
  excluding 0 (fallback without per-row preds: gap > 0.07 ≈ measured cluster half-width).

### Served-forecast accountability loop (2026-07-22, `model_truth.md` audit response)

A reliability audit (`model_truth.md`) proved the backtest metrics measure a regime the product
never serves: backtests score sample-days (fresh lagged risk-history features) while the product
serves between-sample days (median 9-day-stale features, 95% of served rows). Scored against the
lab results that followed, the served forecast ran **AUCPR ≈0.24 (vs 0.63–0.70 backtest)** and its
probabilities lost to a flat base-rate constant on Brier (served ~0.98 → ~0.38 realized — mostly
the positive-persistence floor). Fixes shipped in `app/ml/served_metrics.py` + `_export_forecasts`:

- **`data/curated/forecast_history.parquet`** — append-only log of what actually served (post
  release-gate), keyed by (beach_id, forecast_date, forecast_generated_at). Seeded from 189 git
  commits by `scripts/backfill_forecast_history.py`; the daily run appends in place.
- **`system_health.json["served_metrics"]`** — daily forecast-vs-outcome scoring (same-day +
  strictly-forward D+1..D+3, 90d/30d windows, band operating point, reliability bins,
  `verifiable_fraction`). These are the deployment-truth numbers; cite them, not the backtest
  figures, for "how good is the product".
- **Serving-regime recalibration** — daily isotonic refit (trailing 120d of served/lab pairs,
  guards: ≥500 pairs & ≥25 positives else identity) applied to `p_exceed` + interval bounds before
  banding; `p_exceed_precal` persists the pre-calibration probability for future refits. First
  fit: Brier 0.0603 → 0.0464, beating flat base rate 0.0521; monotone so AUROC (the part that held
  up, ~0.80–0.86) is untouched; persistence rows keep a ≥`_LOW_THRESHOLD` floor (never display
  Low). Stats in `system_health.json["serving_calibration"]`. Band cutpoints unchanged — honest
  probabilities restore their published meaning. Anomaly-gate impact simulated safe (mean ratio
  0.66, no band collapse); expect Very High to mostly vanish until real skill supports ≥0.70.
- **Known remaining gap (model-side):** train/serve staleness mismatch itself — candidate fix is
  staleness-augmented training (censor risk-history features to the serving age distribution +
  days-since-sample feature), validated offline via `scripts/diagnose_spatial_brier.py` first.

### Positive-persistence: override → FLOOR (2026-08-06)

**Symptom:** on the shipped 2026-08-05 forecast, 18 rows served an *identical* `p_exceed = 0.45`
(17 of them the pinned beaches, plus one genuine row at precal 0.689 that the same top step also
mapped there), across 6 counties — lab readings from 107 to 6628, sample ages 2 to 35 days, same number. All 519
served rows carried only **28 distinct probabilities** (from 502 distinct pre-calibration values,
501 of them non-pin).

**Cause — two hand-written corrections cancelling into a constant:**
1. `_export_forecasts` OVERRODE the model wherever the last official sample exceeded, via
   `_positive_persistence_guarded_blend_probabilities(..., alpha=1.0)` = `where(persistence >= 0.5,
   1.0, p)`. The model's own answer was discarded.
2. The daily serving isotonic, seeing 1.0 was wildly overconfident, mapped its whole top step
   (x ∈ [0.617, 1.0]) back down to **y = 0.45**. Every overridden beach landed on that one plateau.

`exceeds_stv_last_obs` was **already a model feature** (`features.py:412`; it is not in
`_model_feature_columns`'s exclusion set), so the model had learned what a prior exceedance is
worth *in context*. The override replaced that learned estimate with a constant, and the isotonic
then erased what little spread remained.

**Fix:** the override is gone. The safety property it existed for — a beach whose last sample
exceeded is never displayed Low — is now a **post-calibration floor at `_LOW_THRESHOLD`**. It also
moved OUT of the `serving_calibration is not None` branch: a run with too little served history to
fit an isotonic previously got no floor at all, a hole the pin was masking.

**Measured A/B** (1095d window, temporal test split, 11,973 held-out sample-days, ONE shared model,
serving isotonic refit per arm so neither inherits the other's calibration):

| | override (old) | floor (new) |
|---|---|---|
| Brier | 0.0846 | **0.0640** |
| AUCPR | 0.573 | **0.791** |
| within-beach AUROC | 0.616 | **0.651** |
| **on the 2,119 affected rows** | | |
| distinct served values | **1** | **43** |
| Brier | 0.2330 | **0.1171** |
| AUROC | **0.500** | **0.910** |

Brier gap on affected rows **0.1159**, cluster-bootstrap 95% CI over 285 beaches **[0.0989,
0.1323]**. The override arm scored **worse than the flat base rate** (0.2330 vs 0.2325) — not
merely uninformative, a *miscalibrated* constant. Control rows (persistence-negative) moved
0.05269 → 0.05260, confirming the change is confined to where it should be.

- ⚠️ **The A/B refits the serving isotonic PER ARM; production cannot.** Production reuses one
  calibrator fitted on a trailing 120d of `forecast_history.parquet`, so the table above is the
  **ceiling this change reaches once the calibration history is clean**, not the first-run result.
  Pushing the same arm-B probabilities through the *live* calibrator gives Moderate 999 / High
  1120 / **Very High 0**, mean 0.344, against a 0.632 realized rate.
- ⚠️ **`_drop_pin_era_rows` restores the TOP of the scale; it does NOT undo the High→Moderate
  reclassification.** Measured, the Moderate count is **999 either way** — the exclusion only
  changes the map above x≈0.617 (High 1120 → 825, Very High 0 → 295). ~47% of the previously-pinned
  rows do move from High to Moderate, and that is a *consequence of removing the override*, which
  stands. It is defensible on its own evidence, not because the exclusion cancels it: under the new
  map the realized rates by served band are **Moderate 0.293 / High 0.912 / Very High 1.000** (and
  within-affected-row model AUROC is 0.913), i.e. the rows sent to Moderate really do sit at the top
  of the Moderate band. An earlier draft of this section claimed the exclusion fixed the downgrade.
  It does not.
- ⚠️ **First-run level is still short.** Every pre-change persistence-positive row carried precal
  1.0, so excluding them leaves the legacy fit population entirely persistence-NEGATIVE, and that
  map is then applied to a mixed one. On the A/B holdout it under-predicts the affected rows —
  **mean 0.4444 against 0.6324 realized** — where a clean per-arm refit does not (0.6378). Not
  fixable from history (the pin destroyed those x-values); it decays as the window rolls.
- **Pin-era rows are excluded from the serving-calibration fit**
  (`served_metrics.py::_drop_pin_era_rows`). Until 2026-08-06 the pin was applied BEFORE
  `p_exceed_precal` was snapshotted, so on those rows the recorded "pre-calibration probability" is
  the constant 1.0, not a model output. On the 2026-08-05 history that was **482 of 13,813** rows in
  the window, realizing 0.4149 — enough to pin the isotonic's top step at **y = 0.45** and cap
  *every* served probability there. Excluding them: `max(y)` 0.45 → **1.0**, fit Brier 0.0684 →
  **0.0617** (flat base rate 0.0673), and on the affected rows Brier 0.2541 → **0.1778** with Very
  High 0 → 295. Keyed on "legacy row (no `persistence_floor_applied`) AND precal == 1.0", so it is
  **self-limiting**: post-change rows are never dropped and the exclusion stops firing once the
  window rolls past the change.
- **"Very High" was unreachable, and the pin was only part of why.** An earlier draft of this
  section claimed the pin was *the* reason the band never fired. It was not: the live isotonic's
  ceiling capped output at 0.45 outright, so 0.70 could not be reached by any row regardless. The
  pin was one contributor to that ceiling. Fixed by the exclusion above; expect Very High to return
  in small numbers — **295 of the 2,119 affected rows (13.9%)** on the offline replay. ⚠️ Every one
  of the 43 fit rows in the `y ≥ 0.70` region is **San Diego** (14 beaches), so "Very High returns"
  means "San Diego ddPCR beaches get Very High", calibrated on San Diego ddPCR labels — the regime
  the label-regime section below flags as a different labelling universe. The top step is also
  support-capped (`_MIN_TOP_STEP_SUPPORT`): un-capped it was **y = 1.0 off two rows**, both Mission
  Bay stations on one afternoon.
- **Caveats.** Scored on *sample-days*, not the between-sample regime where ~95% of served rows
  live; the pinned constant is 0.61 here vs 0.45 in production because the test population's base
  rate is 0.165 vs ~0.061 served (structure transfers, level does not); and the affected rows are
  overwhelmingly San Diego ddPCR beaches, so the label-regime caveat below applies.
- **Reproduce:** `backend/scripts/compare_persistence_override_ab.py` (~25 min, needs a retrain).
  Held-out predictions for both arms are committed to
  `data/experiments/persistence_override_ab_predictions.parquet`, so any further cut is a recompute.
- **The guard MODEL keeps the old semantics.** `hist_gbm_positive_persistence_guard` is a scored
  backtest candidate whose *definition* is the pin; changing it would silently rescore a different
  estimator against its own history. If it ever won promotion it would reintroduce the flattening —
  known and accepted, not an oversight.
- **The NaN/inf serving guard no longer falls back to 1.0** on persistence-positive rows (it now
  uses `_LOW_THRESHOLD` for both branches). The old fallback re-created the exact constant this
  change removed — a *failed* prediction became the loudest forecast in the product — and because
  `probabilities_precal` is snapshotted after the guard, that 1.0 was written to
  `forecast_history` and re-seeded the pin contamination in the next day's isotonic, permanently.
- **New audit columns:** `forecasts.parquet` gains `persistence_floor_applied`, also added to
  `forecast_history.parquet`'s `_HISTORY_COLUMNS` — where it doubles as the marker that identifies
  legacy rows for `_drop_pin_era_rows`. NOTE it does *not* mirror `advisory_floor_applied` end to
  end: that one is plumbed through the API schema and the web bake, this one stops at the parquet
  and the history log. And
  `p_exceed_precal` is now genuinely the model's own pre-calibration probability — it used to be
  captured *after* the pin, so on exactly the rows that mattered the model's answer was absent from
  every shipped artifact and the change could not be measured retrospectively.
- ⚠️ **Serve-time features are reindexed onto the TRAINING feature columns**
  (`_export_forecasts`, `reindex(columns=features.columns)`). If `exceeds_stv_last_obs` ever leaves
  the training feature set, persistence silently reverts to the method-blind `value > 104` fallback.
  Both branches are now pinned by tests.

### ⚠️ `exceeds_stv` is not one label (2026-08-06 investigation, UNRESOLVED)

Culture rows are judged against 104 MPN/CFU; San Diego ddPCR rows against **1413 copies**. On
**1,175 paired same-beach same-day samples** the two rules agree only **50.6%** of the time —
culture flags 0.122, PCR flags 0.603, PCR-flags-alone 48.8%, culture-flags-alone 0.6%.

- **1413 is correct — do not change it.** It is not a misapplied EPA figure (EPA's qPCR BAV is 1000
  CCE/100 mL for Method 1611). It is a CDPH-developed value fitted directly against **raw ddPCR
  copies** (Crain et al. 2021, "Intrinsic Copy Number Equation", 1,993 paired results), approved by
  EPA Region 9 (2020-10-06) and authorized under H&SC §115880(d). San Diego DEH uses it to issue the
  Bacterial Exceedance Advisories this product predicts. The 2026 Coronado paper confirms the
  provenance verbatim — "The ICE was used to propose a new ddPCR-based BAV of 1413 copies/100 mL",
  EPA approval 2020-10-06, in use "since May 5, 2022" (which matches our data exactly) — and notes
  that "some beaches have experienced more frequent BAV exceedances". ⚠️ The SD County / EPA /
  SCCWRP pages themselves are still 403 from the CI network policy and remain unverified.
- **The divergence is a published property of the method,** not a bug here. Verified against the
  **primary source** (Verbyla & Lacarra, *J. Microbiol. Methods* 240:107346, Jan 2026 — PDF read
  2026-08-06, no longer a search-snippet citation). Coronado, 3 beaches, daily sampling, summer
  2023:
  - **The method fails EPA's own comparability criteria at these beaches.** Per the paper quoting
    US EPA (2014): "An IA value of 0.70 or greater demonstrates acceptable equivalence…; if IA is
    less than 0.70, then an R² value of at least 0.60 demonstrates acceptable equivalence."
    Measured at Coronado: **IA = 0.25** and **R² = 0.41** — *neither* gate is met, so by that rule
    ddPCR there qualifies neither for the same numerical limits nor for regression-derived new
    ones. ⚠️ Scope: three beaches, one summer. The EPA approval rests on Crain's county-wide
    N=1,993, not on this.
  - **56.3% ddPCR false-positive rate** against the Enterolert action value — our 48.8%
    PCR-flags-alone rate independently reproduces it on a different corpus.
  - **Their own numbers mirror ours.** Coronado ddPCR median **1,669** copies and geometric mean
    **3,101** — *both above the 1413 BAV* — while Enterolert median 7.8 MPN and geomean 18.0 sit
    "well below" 104. We measured median ddPCR 2,240 vs threshold 1413. Same shape.
  - **The conversion is not portable.** The ICE fitted on Coronado data has slope **0.00385**
    against the county-wide ICE's **0.06183** — a ~16× shallower relationship at one location than
    the one 1413 is derived from. Their log-transformed slope 0.5151 is close to our log-log 0.637;
    both far below 1, i.e. no constant conversion factor exists.
  - ⚠️ **A CORRIGENDUM exists** (*J. Microbiol. Methods* 244:107453, May 2026) and has NOT been
    read. Do not treat the figures above as final until someone checks what it revises. No alternative threshold is fittable from our data: the "pairs" are a median **2.27 h**
  apart (5 of 1,175 share a timestamp), only **6.3%** of ddPCR beach-days have a same-day culture,
  the three highest-volume ddPCR stations contribute 0/1/0 pairs, and three defensible estimators
  span 21× (OLS 14,433 / RMA 42,702 / inverse-regression 300,030).
- **Consequence for the model:** ddPCR is **15.3%** of enterococcus rows in the 1095d window but
  supplies **51.9% of all positive labels**; San Diego is 24.9% of `beach_day` rows and **57.0% of
  positives** (base rate 0.406 vs 0.102 elsewhere). Leave-one-county-out with San Diego held out is
  holding out a different labelling universe.
- **Next step is NOT a threshold change:** carry `is_pcr` / `label_method` into `beach_day` (it is
  dropped there today — the root of the method-blind feature class: `enterococcus_value_lag_*`,
  `enterococcus_value_last_obs`, `log_enterococcus`, and the 35/104-thresholded geomeans all mix
  MPN and copies in one column), stratify `system_health` metrics by it, and re-run the persistence
  A/B per regime. Open question for SD DEH: our ddPCR flag rate is ~60% vs a ~38% advisory-day rate,
  which suggests a confirmatory-resample or duration rule on top of 1413.

### Two-tier serve-time router (2026-07-23, resolves the staleness gap above — **DEPLOYED, serving 100% of beaches**)

The gap above is now addressed by a **level+deviation two-tier model served by a regime router**
(`app/ml/two_tier.py`, `app/ml/models.py::XGBUndersampleOffsetEnsemble`, router in
`training.py::_route_fresh_stale_probabilities`). Motivation (`model_truth.md`): the deployed
ensemble is skilful on fresh sample-days but **collapses between samples** — on the CA
deployment eval (known beaches, future dates, anchor censored to serving age) served AUCPR falls
**0.696 → 0.379** and it under-predicts (mean 0.037 vs 0.139 actual — "defaults to safe").

- **The offset model** (`XGBUndersampleOffsetEnsemble`) is the incumbent's undersample EasyEnsemble
  **plus** two things: each beach's shrunk historical log-odds supplied as XGBoost `base_margin`
  (the trees learn only the *within-beach deviation*; the level comes from a never-stale historical
  rate), and **staleness augmentation** (train on fresh + anchor-censored copies). On the same CA
  eval it **holds**: served AUCPR 0.621, mean pred 0.181 (calibrated), Brier 0.121→0.083. The
  offset is a training-time change (`base_margin` alters the fit gradient) — it cannot be derived
  from the trained ensemble by reweighting.
- **Both models are trained** every winner-only run (offset alongside the ensemble winner). Serving
  **routes by sample age**: beaches with a lab sample ≤`_FRESH_ROUTE_CUTOFF_DAYS` (3d) keep the
  ensemble (it wins at low lag); staler beaches get the offset; a short linear ramp
  (`_route_offset_weight`, days 3→`_ROUTE_BLEND_END_DAYS`=5) blends the two so no beach jumps bands
  in a single day (raw handoff Δ mean 0.074 / p90 0.186, halved by the ramp). Served population is
  ~98% stale (min age ~4d), so the offset serves nearly everyone; the ensemble is the fresh-day
  specialist (mostly San Diego same-day ddPCR). Diagnostics: `system_health.json`
  `two_tier_diagnostics.serving_router`.
- **Gates unchanged / promotion gate KEPT** (2026-07-24 decision): the router serves *under* the
  existing health/anomaly/release gates (`--enforce-release-gate` still on in CI). The single-winner
  promotion selection still runs and still picks the ensemble as the registry "winner"; routing is a
  serving-path layer, not a gate bypass. Offset registered as `SPATIAL_DIAGNOSTIC_MODEL_NAMES` +
  shortlist backtest (not `PRODUCTION_MODEL_NAMES`).
- **Honest metrics wired:** `two_tier_diagnostics` records within-beach AUROC per candidate on the
  fresh AND served (censored) regimes (`spatial_beach{,_stale}_by_model`, `temporal_ca_by_model`);
  holdout artifacts now carry `beach_id`+`lag`. Within-beach AUROC (not global AUCPR) is the
  primary metric — global AUCPR is blind to daily skill (it stayed ~0.65 while served within-beach
  was ~0.50).
- **Status: LIVE.** Merged in `00612cae` and serving since ~2026-07-22. The daily Action needed no
  YAML change (already `--winner-only`).
  - **⚠️ The "fresh 0 / blended 0 / stale 297" once written here was wrong — the offset model does
    NOT serve every beach.** No shipped run reproduces it. The 2026-07-30 daily run reports
    **fresh 183 / blended 8 / stale 329**. Read the live `system_health.json`, never this prose.
  - **The split is a pure function of data lag, and it is violently sensitive to it.** The router
    keys on `forecast_date − latest enterococcus sample_date` per beach against the 3d/5d cutoffs;
    nothing else enters it. Holding the 2026-08-01 observations fixed and moving only the forecast
    date: 07-30 → 268/0/250, 07-31 → 124/144/250, 08-01 → 43/81/394, 08-02 → 11/32/475. **One day
    of pipeline lag moves ~144 beaches onto a different model**, silently and with no alert, so a
    late daily run or an upstream feed delay will show up later as an unexplained metric shift.
    Both figures above were reconstructed exactly from sample ages alone (183/8/329 and 43/81/394),
    so if a router split ever looks surprising, check the data lag before suspecting the model.
  - **`production_model` still reads `xgb-undersample-ensemble-curated-v0`** and always will — that
    is the registry *winner*, not the model that computed `p_exceed`. Do NOT read it as "what is
    served"; read `model_registry.metrics.two_tier_diagnostics.serving_router` (note the **nesting**
    — it is not a top-level key) and the per-row `served_offset_weight` in `forecast_history.parquet`
    (0 = ensemble, 1 = offset, null = no router ran).
  - **Side effect, confirmed:** the persistence pin is gone. Rows at `p_exceed = 1.0` ran 2.39% of
    the 90d window (612 rows, realising only ~31%) and have been **0 since 2026-07-22**, along with
    every `p_exceed ≥ 0.7`. Mean served `p` fell ~0.10 → ~0.07. This is the predicted "Very High
    mostly vanishes until real skill supports ≥0.70" — not a regression.
  - **`served_metrics` currently averages two regimes.** Its 90d window straddles the ~07-22 switch,
    so the published AUCPR ≈0.22–0.24 / Brier is mostly the *pre-router* ensemble and understates
    what is running now. Split it by `served_offset_weight` before quoting it; it self-corrects once
    the window rolls past the switch.
  - Caveats unchanged: the offline served numbers are a censored proxy (optimistic vs the true
    forward-scored ~0.24 incumbent baseline — the *relative* gap + bias fix are the solid signals);
    no cluster-bootstrap CI on the served gap yet. See [[project_two_tier_model]] memory.
- **Challenger tested and rejected (2026-07-28):** bagged/boosted logistic regression on balanced
  undersamples (XGBoost `gblinear`, ±per-beach `base_margin`), proposed as a simpler replacement.
  On known beaches in the served regime it beats the *plain* ensemble (AUCPR 0.623 vs 0.531) but
  loses to the deployed offset model on both global AUCPR (0.623 vs 0.716) **and** within-beach
  daily skill (0.609 vs 0.691), which is the metric that matters. Also measured: averaging the
  logistic *weights* across undersamples is a no-op (members correlate >0.99 — they share every
  positive), and the outer bagging loop around XGBoost is worth only ~+0.02 AUCPR (most of the
  benefit is the class rebalancing, not the averaging). Scripts left in the session scratchpad, not
  committed. Do not re-litigate without a daily-cadence evaluation (below).

### The measurement gap: daily product, weekly labels (2026-07-28)

**Every metric in this file is computed on days a lab result exists.** The product publishes a
forecast for every beach every day; labs sample a median of **7 days** apart. So ~6 of 7 served
predictions are unverifiable in principle, and the numbers above grade the one day a week that
is not the hard case. Two consequences worth internalising before trusting any model comparison:

- **Global AUCPR/AUROC is blind to the daily question.** It is dominated by *between-beach*
  variance — a model scores well by knowing Tijuana Slough is dirtier than Carmel, with zero
  ability to tell Tuesday from Thursday at one beach. Use `within_beach_auroc` (`two_tier.py`)
  as the headline; a value near 0.50 means the model is a per-beach lookup table no matter how
  good the global number looks.
- **AUCPR is base-rate dependent and the eval/serve base rates differ ~3×** (0.174 in the
  sample-day training population vs 0.061 served). Measured directly by diluting a fixed set of
  predictions: AUCPR falls 0.532 → 0.322 with the model, ranking and all held constant, while
  AUROC stays flat at ~0.772. So **~71% of the apparent "0.54 backtest → 0.24 served" collapse is
  arithmetic, not skill loss.** Never compare AUCPR across populations; compare AUROC.

**Where daily skill is actually falsifiable:** 37 beaches (mostly SD ddPCR + LA) sample at a
median gap ≤2d, giving **3,188 consecutive-day pairs**. Day-over-day the label flips **19.4%**
of the time (vs 49.2% under independence) — strongly autocorrelated but far from static, so
interpolating between weekly samples is structurally wrong. Those beaches are unrepresentative
(base rate 0.437 vs 0.061 served), but a model that cannot beat persistence *there* cannot be
trusted on a weekly-sampled beach. The evaluation to build: retrospective daily grid per
candidate → within-beach AUROC by lead time 1–7 vs persistence, plus a flip-day readout.

**Label-free check that needs no daily truth:** does the predicted series *move* like reality?
Measured on the live grid — bands change on 6.49% of beach-days and **92.5% of those changes
occur on days with no new lab sample**, i.e. the model responds to rain/solar covariates rather
than parroting the last result. Necessary but not sufficient: right variance ≠ right timing.

## ML training

```
python -m app.ml.training --curated --spatial-backtests \
  --spatial-strategy shortlist \
  --forecast-date "$(TZ=America/Los_Angeles date +%Y-%m-%d)"
```

**Evaluation (as actually implemented in `app/ml/training.py`):**
1. **Temporal split** (`_blocked_indices`, line 1514): unique sample dates split 70% train / 15% valid / 15% test. Single split, no folds. Produces `temporal_validation_metrics` and `production_metrics`.
2. **Spatial county holdouts** (`_spatial_backtest_metrics`, line 1183): leave-one-county-out — train on N-1 counties, test on the held-out county, rotate. Capped by `--spatial-county-limit` (CI default 12, rigorous local 30). Produces `spatial_county_<model>` metrics.
3. **Spatial beach holdouts**: same pattern at the individual-beach level. Capped by `--spatial-beach-limit` (CI default 50, rigorous local 500). Produces `spatial_beach_<model>` metrics.
4. **Promotion gate** (`_spatially_qualified_production_winner`): the temporal winner is vetoed
   when it fails the spatial gates (held-out county/beach AUCPR + Brier must beat persistence,
   spatial calibration slope ≥ 0.4) and a sibling passes. **Fixed 2026-06-01**: the gate now runs
   for ANY temporal winner (the prior `winner.startswith("hist_gbm")` guard let an overfit
   non-hist_gbm winner like logistic bypass the spatial veto), and shortlist mode always backtests
   the full hist_gbm family so a robust alternative is available to swap in.

**2026-06-01 model rebuild** (`app/ml/training.py`, `app/ml/models.py`):
- **Training window 60 → 365 days** — the 60-day default starved the fit (~1.8k rows / ~9 unique
  dates → degenerate temporal split). 365d ≈ 24k rows. **(Superseded 2026-06-08: 365d in turn
  starved the SPATIAL fit; now 1095d ≈ 84k rows — see the 2026-06-08 section below.)**
- **Marine-microbiology features wired into the loader allowlist** — the 11 columns
  (`solar_inactivation_index`, `uv_index_24h_max`, `wind_speed_24h_max`, pier/estuary proximity…)
  were computed into `beach_day` but dropped by `_load_curated_training_frame`'s column list, so
  they re-entered as all-NaN→0. Now selected. (Also fixes the dead `uv_index`/`wind_speed_mps`
  name mismatch by adding the real `*_24h_max` columns.)
- **Class weight** `{0:1, 1:3}` → `"balanced"` (true base rate ~10%).
- Risk bands (`calibration.py`): Low <0.20, Moderate 0.20–0.30, High 0.30–0.70, Very High ≥0.70
  (High = ~3× the average beach's ~10% base rate). Pre-rebuild the calibrated probabilities were
  squashed (<0.06) so upper bands never fired; post-rebuild the spread is being re-established.

Baseline AUCPR is being re-established by the rebuild (the prior "≈0.37 / 0.85 / 0.76" figures
predate the corrected labels + feature fixes and should not be cited until the rebuild lands).

**2026-06-02 architecture flip — `xgb_undersample_ensemble`** (`app/ml/models.py`,
`app/ml/training.py`, `scripts/spatial_compare.py`, `scripts/spatial_incumbent.py`):
Added `XGBUndersampleEnsemble` (EasyEnsemble variant: keep all positives, draw N balanced
negative undersamples at a 2:1 ratio, fit one XGBoost each, soft-average probabilities). It is
**always trained** alongside hist_gbm and registered in `PRODUCTION_MODEL_NAMES` + the planner's
spatial backtest set, so the existing promotion gate can swap it in **on its own
leave-one-county-out spatial logic** (no hard-override).
- **Why it won (honest spatial numbers, not temporal):** leave-one-CA-county-out validation,
  predictions pooled across 12 counties:
  - ensemble +marine **0.615 AUCPR / 0.100 Brier** vs incumbent single balanced GBM
    **0.546 / 0.114** (+0.069 AUCPR, better calibration).
  - **Texas pooling REJECTED** — every CA+TX cell was *worse* than CA-only on held-out counties
    (Gulf regime doesn't transfer); the temporal split had falsely favored it (0.775). The product
    stays **CA-only**; the WQP/TX cohort scripts remain offline experiments, not a training input.
  - **Marine features CONFIRMED spatially** (+0.029 over base, best Brier) — they help *more*
    spatially than temporally (unseen counties can't lean on memorized base rates).
  - **0.615 is the real generalization number** — the earlier ~0.76 was temporal-split inflation
    (same beaches in train+test).
- **macOS-only fix:** `import xgboost` must precede `import torch` (duplicate-libomp segfault);
  guarded at the top of both `models.py` and `training.py`. Harmless on Linux CI.
- MPS/LSTM was compared and **dropped** — it lost on every cohort (CA 0.721, TX 0.235,
  CA+TX 0.718) AND would need a freeze→CPU-inference→CI path to ship; the XGB ensemble is CPU,
  fast, and retrains daily in the existing CI with no new infra.

**2026-06-08 — training window 365 → 1095d (the real spatial lever)**
(`.github/workflows/daily-forecast.yml`, `pipeline/cli.py`):
The 0.615 county AUCPR above was an offline `spatial_compare` number; the in-pipeline gate only
reproduced 0.509 for the ensemble. Root cause is the **training window, not the model**:
`spatial_compare` trains each leave-one-county-out fold on full history (~76k rows); the gate's
`--winner-only` path used only the 365-day window (~24k rows). Isolation test (spatial_compare
restricted to 365d): +marine 0.612 → 0.567 (−0.045 from the window); the rest of the gap is the
gate's calibration + inner-validation split.
- **Window experiment** (gate retrain @ 1095d, 84,805 rows): the 1095d window genuinely lifts
  the ensemble over hist_gbm on held-out counties; hist_gbm does NOT benefit from more data.
  1095d captures all feature-rich post-2020 history (precip/marine features only exist from 2020).
  CI now trains at 1095d.
  - **⚠️ Reconciliation (2026-06-10, refreshed 2026-06-11; see `backend/METRICS_RECONCILIATION.md`).
    These spatial metrics are REGENERATED EVERY DAILY RUN — `data/curated/system_health.json`
    (`model_registry.spatial_metrics` + `production_metrics`) is the single source of truth, and
    any number written here is a dated snapshot that WILL drift (the daily sweep is now 6-county /
    15-beach folds — commit `153f1368a` — so the pooled AUCPR is noisy run-to-run; re-read the JSON
    before citing).** The "county AUCPR 0.590 / beach 0.900, slopes 1.26/1.16" once written here
    were **never reproduced by the in-pipeline gate** (they were an offline `spatial_compare` number;
    no gate run has ever shown them). **Current on-disk snapshot — daily run `c64a0b5da`,
    2026-06-11, 6-county / 15-beach @1095d: held-out county AUCPR 0.553 / beach 0.932, calib slopes
    1.21 / 1.18** (county persistence baseline 0.420, pooled county base rate 0.197; beach
    persistence 0.762 over a high 0.561 base rate). hist_gbm on the same gate path: county 0.481 /
    beach 0.928. (The prior 12/50 daily run `5d99a8587` had written 0.499 / 0.871, slopes 0.99 /
    0.88 — now historical/superseded.) The offline-`spatial_compare`-vs-in-gate gap is calibration
    (isotonic on test probs), the gate's inner train/valid split, and a different county-selection
    rule (gate picks counties by row count, `spatial_compare` by positive count) — the model is
    identical; only the eval path differs. The county number (over a ~0.20 base rate) is the honest
    spatial-generalization test; the beach number sits over a high base rate where persistence
    already scores high. **Do not cite 0.590 / 0.900 — never reproduced by the shipping path.**
- **Gate picks-best among passing models (2026-06-11: was wrongly documented as a TODO).**
  `_spatially_qualified_production_winner` (`training.py:1806`) filters candidates to those that
  clear the held-out county+beach persistence gates, then picks the best by temporal-valid AUCPR
  (tiebreak lower spatial Brier), with `_WINNER_SWAP_MARGIN` hysteresis so the daily winner-only
  retrain doesn't churn on backtest noise. The earlier "keeps a passing incumbent even when a
  sibling is decisively better — never auto-swaps" note described an OLD veto that no longer
  exists; the swap logic landed with the 1095d ensemble case (2026-06-08) and the code at lines
  1843-1851 already does pick-best. The ensemble remains the registry winner because it wins this
  selection, not because of a manual override.
- **first_rain_score cache self-heal** (`pipeline/cli.py`): the incremental `precip_daily.parquet`
  cache only re-fetched the last 7 days, so derived columns added later (first_rain_score,
  precip_*_prior, precip_mm_96h/192h) stayed NaN for all history (~0% covered). Now the pipeline
  detects missing/sparse derived columns and forces a full re-aggregation from the on-disk raw
  cache. Honest result: a live first_rain_score did NOT help the GLOBAL county metric (rainfall is
  beach-specific — Searcy et al. 2018; pays off only in per-station models).
- **Benchmark (Searcy et al. 2018, 10 CA oceanic beaches, operational):** median sensitivity 0.50
  @ specificity 0.87 for enterococcus. The old "sens 0.59 @ spec 0.87" claim was UNVERIFIABLE
  (2026-06-10, no holdout artifact persisted). **Now computed:** `training.py` persists the winner's
  held-out (label, probability) pairs to `data/curated/holdout_predictions_{temporal,spatial}.parquet`
  and records `sensitivity_at_specificity(0.87)` into `system_health.json`. **As of the 2026-06-11
  daily run (`c64a0b5da`) these artifacts EXIST on disk** and the operating points are populated.
  **Snapshot of that run (these are REGENERATED EVERY DAILY RUN — read `system_health.json` for the
  live values):**
  - **Temporal-test (same beaches in train+test, in-distribution-optimistic): sensitivity 0.722 @
    spec 0.871.**
  - **Leave-one-county-out holdout (the honest generalization figure): sensitivity 0.482 @ spec
    0.896** — essentially the Searcy operational median (0.50 @ 0.87).
  - Leave-one-beach-out holdout: sensitivity 0.832 @ spec 0.871 (over a high ~0.56 base rate).
  So cite **~0.48 @ 0.90 (county holdout)** as the conservative real-world number and **0.72 @ 0.87
  (temporal)** as the in-distribution number — NOT a single blended figure. Recompute any other
  operating point from the parquet with no retrain. See `backend/METRICS_RECONCILIATION.md`.

## Key design decisions

- **Feature space**: 50+ features plus the 11 marine-microbiology features (UV inactivation,
  wind plume transport, point-source proximity) — now actually fed to the model (2026-06-01 fix;
  they were previously computed-but-dropped) and **spatially confirmed** to help (2026-06-02).
  Remaining headroom: per-station models.
- **Production classifier**: `xgb_undersample_ensemble` — balanced-undersample XGBoost soft-ensemble.
  Trained on the **1095-day window** (2026-06-08) where it beats hist_gbm on held-out counties and
  beaches. **Shipped held-out metrics are REGENERATED EVERY DAILY RUN — read
  `data/curated/system_health.json` for the live values; the figures below are a dated snapshot that
  WILL drift** (6-county / 15-beach folds → noisy pooled AUCPR). **Snapshot, daily run `c64a0b5da`
  (2026-06-11): county AUCPR 0.553 / beach 0.932, calib slopes 1.21 / 1.18** (county persistence
  0.420, beach persistence 0.762; hist_gbm on the same gate path county 0.481 / beach 0.928) — NOT
  the 0.590/0.900 once cited (that was an offline `spatial_compare` number **never reproduced by the
  gate**; see `backend/METRICS_RECONCILIATION.md`). The beach figure sits over a high ~0.56 base
  rate where persistence already scores ~0.76; the county figure (base rate ~0.20) is the harder,
  honest spatial test. CA-only; cross-region (TX) pooling tested and rejected on held-out counties.
  It is the registry winner because it wins the gate's pick-best-among-passing selection (with
  hysteresis), not via a manual override — see the corrected "Gate picks-best" note above.
- **Forecast-safe cutoff**: 5 AM PT daily summaries; nothing leaks same-morning sample data.
- **Shore azimuth**: SVD over 5 nearest-neighbor beaches for coastline tangent; disambiguated
  by vector toward CA inland centroid (37°N, 120.5°W).
- **LLM feature agent**: parked after 200+ iterations with 0 legitimate accepts. Re-engage only
  if per-station stacking / nowcasting don't move AUCPR.

## CI

`.github/workflows/daily-forecast.yml` runs at 9 AM PDT (cron `0 16 * * *`).
Hydrology + solar-wind cache key: `hydro-${{ runner.os }}-v4`.
Timeout: 170 min (was 120; bumped 2026-06-10 — the 1095d window's spatial sweep was
overrunning the old budget and timing the job out before it could commit).

**Action versions (2026-06-11):** all workflows pinned to Node-24 runtimes
(`checkout@v5`, `setup-python@v6`, `cache@v5`) ahead of GitHub's 2026-06-16 forced Node-20→24
migration; a github-actions-only Dependabot keeps them current (pip is intentionally manual).

**Failure alerting (2026-06-11):** daily-forecast has a `notify-failure` job (`if: failure()`)
that opens/comments a de-duped `pipeline-failure` GitHub Issue (assigned to the repo owner, who
gets emailed) — previously a failed run was silent until `/system/health` went 503.
`deploy-backend.yml` now polls `/system/health` after the Render webhook (~5 min) and fails the
deploy if it never returns 200, so a broken Render build no longer ships unnoticed. Both have
`concurrency` with `cancel-in-progress: false` (never kill a mid-flight train/commit/deploy).

**Invalid JSON froze every publisher (2026-07-25 root cause).** `two_tier.within_beach_auroc`
returns `float("nan")` when no beach qualifies in a bucket — a legitimate "undefined", but
`json.dumps` writes it as a bare `NaN` token, which is **not valid JSON** (RFC 8259). It first
appeared in `17acde4` (the 2026-07-24 daily run, the first refresh after the two-tier router
merged in `00612cae`), under
`model_registry.metrics.two_tier_diagnostics.temporal.by_lag.lag_8_14d`. Consequences:
the private **shorelife-web** build died prerendering `/research`
(`SyntaxError: Unexpected token 'N'` from `JSON.parse`) and its static export froze at the last
good bake — which is what actually showed users a "47 hours ago" timestamp. The same NaN sits in
`serving.sqlite`'s health row, but the **API survives it**: FastAPI's `jsonable_encoder` runs the
response model through pydantic v2's `model_dump(mode="json")`, whose default
`ser_json_inf_nan="null"` maps non-finite floats to `null` before Starlette's `allow_nan=False`
renderer sees them — `/system/health` returned 200 throughout while serving the NaN-carrying
2026-07-25 snapshot (`verify_deploy` confirmed it live at 18:47 and 19:00 UTC). Any *other*
strict consumer of the file or that sqlite row still rejects the whole document. Fix:
`app/core/json_safe.py`
(`json_safe` scrubs non-finite floats → `null`; `dumps_strict` then serialises with
`allow_nan=False` so a future producer fails loudly at the write instead of shipping an
unparseable document). Every published JSON now goes through it — `system_health.json`
(training + beachwatch), `production_model_registry`, `serving_calibration.json`, and the
sqlite health row. NaN metrics are legitimate; publishing them as `NaN` is not.

**Deploy verification — committed ≠ served (2026-07-25 hardening).** The API serves a snapshot
**baked into the Docker image** (`backend/Dockerfile` COPYs `data/curated/`), so a fresh data
commit changes nothing users see until a Render **build** finishes. Both workflows POSTed the
Render deploy hook fire-and-forget; a 200 from the hook only means Render *accepted* the request,
and the last **verified** build (`deploy-backend` #111, 2026-07-24 18:04, sha `00612cae`) baked
the 2026-07-23 forecast, so nothing proves the 19:13 daily commit (`17acde4`) ever went live.
The user-visible "47 hours ago" traced to the frozen web export above, not to Render — but the
backend had the identical blind spot: a failed Render build leaves the previous image serving
while CI stays green. Both workflows now run `backend/scripts/verify_deploy.py`, which
polls the public health endpoint until the **served** `pipeline_freshness` is ≥ the one just
committed (40 × 30 s) and fails the job otherwise → `notify-failure` opens the `pipeline-failure`
issue. `deploy-backend.yml`'s old bare "returns 200" poll could not catch this (the previous
image answers 200 too), so it was replaced by the same check.

**Daily spatial backtest folds — 6 counties / 15 beaches** (`--spatial-county-limit 6
--spatial-beach-limit 15`, commit `153f1368a`, 2026-06-10). The full 12-county / 50-beach
sweep at 1095d (~84k rows, ~60 retrains) overran the ML budget and timed the whole job out
(stale forecast → `/system/health` 503). 6/15 still yields valid spatial-holdout metrics that
pass the public-release gate. The full 12/50 sweep is kept only for the manual
`workflow_dispatch full_comparison=true` (winner re-selection) path. NOTE: the first daily
refresh at 6/15 has now run (`c64a0b5da`, 2026-06-11), writing **county AUCPR 0.553 /
beach 0.932** — *above* the prior 12/50 run's 0.499 / 0.871, illustrating that the
fewer-fold pooled spatial AUCPR is noisy run-to-run. Always read the live
`system_health.json` rather than any prose snapshot. Reconciliation detail:
`backend/METRICS_RECONCILIATION.md`.
