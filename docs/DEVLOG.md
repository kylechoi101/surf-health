
## 2026-09-22 — lookup-baseline (office/tasks/2026-09-22-lookup-baseline)

**Shipped (uncommitted worker code, per office rules):** `backend/scripts/lookup_baseline.py`
(1,070 lines) + `backend/tests/test_lookup_baseline.py` (11 tests). Two modes: forecast for a
date, and backtest over every date in `forecast_history.parquet`. Inputs are the gitignored
`data/snapshots/main-2026-09-22/` copy of `origin/main` `data/curated/`; outputs in
`data/experiments/lookup_baseline/`.

**Result:** a strictly-prior 365-day per-beach exceedance rate (shrunk k=5) beats the served
ML forecast on the served log, forward D+1..D+3: 90d AUROC 0.8775 vs 0.8238, AUCPR 0.5791 vs
0.3946, Brier 0.0604 vs 0.0713 (n=11,616). Holds on all-rows, 30d, culture-only, ddPCR-only.
Within-beach the ML is at chance (mean 0.513 over 148 dates; 0.45 on the 90d cut).
On 2026-09-22: of 402 served beaches, 22 have no sample in 30d (lookup: Unmonitored), 92 served
Low have a ≥0.10 lookup rate, 14 served High are High only because of the advisory floor.

**Corrections:** phase 50 — PM spec error, advisory rule ignored `status` (207 historical rows
with null `ended_at` → 139 false Posted); phase 75 — per-beach "winner" table compared a
near-constant predictor within-beach; replaced with ML vs persistence.

**Tokens (Gemini):** 25: 256k, 50: 297k (×2 runs logged as one), 75: 285k, 100: 345k.

## 2026-09-22 — serve the lookup estimate (serve-lookup, web-lookup-copy)

**Shipped.**
- Backend PR 37 (merged `443e5ef5e`): `app/ml/lookup_serving.py` runs after training and overwrites the served fields. p = (pos + 5g)/(n + 5) over [D-365d, D), a persistence floor at the Low cutpoint, the existing advisory floor, and the existing band cutpoints. ML kept as `p_exceed_ml` / `risk_band_ml`. Served beaches need a sample within 30 days, down from 45.
- Mobile `465cf9b` on feat/dual-mode: band and footer copy describe the lab track record. It ships by OTA after the backend is verified live.
- Web PR 13: the same copy change, plus methodology, labels and calibration pages.

**Evidence.** On a copy of main's data: validate_forecast PASS (anomaly mean ratio 1.33), serving_snapshot ok, values equal to lookup_baseline exactly. Lookup bands at the existing cutpoints realized 0.033 / 0.114 / 0.354 / 0.818 over 90 days of forward outcomes.

**Corrections.** In serve-lookup phase 25 the worker exited mid-suite with no report; it was retried with foreground-only tests. In web phase 75 the PM fixed two phrases, and at 100 reworded two lines outside the allowed files.

**Tokens (Gemini).** serve-lookup 3094614, web-lookup-copy 4228994.

## 2026-09-22 (late) — lookup live; advisory-floor ordering fix (PR 39)

**Live.** Daily run 35803491578 committed and deployed the lookup: 380 beaches, all `lookup-365d-v1`. The Render deploy was verified. Web Pages was re-deployed (run 35809353797): all 380 baked beaches carry lab-test drivers and no ML drivers. The mobile OTA was published by the CEO from `465cf9b`.

**Bug found after going live.** The lookup step ran before G.2 zombie-advisory expiry. It floored 81 beaches to High, but only 18 were still posted after G.2. Users were unaffected, because the API and the bake re-derive the band from `p_exceed_raw` and live advisories (8 of 8 sampled correct). The stored `risk_band` and today's history rows were inflated. PR 39 re-runs the idempotent lookup after G.2, and a test pins the order. Its merge started daily run 35809660033, which re-issues today's forecast.

## 2026-09-28 — serve the logistic model on top of the lookup

**Shipped (branch `claude/gifted-faraday-w20l4z`, not yet merged).** Yesterday's shadow challenger (`e238b21`, `app/ml/logit_challenger.py`) now sets the served number. `lookup_serving` computes the lookup, fits `logit(p) = logit(lookup) + b0 + b1·R + b2·R·F + b3·W + b4·S` on 4 years of sample-days before D, and serves it through the same persistence and advisory floors. The lookup is kept as `p_exceed_lookup` in `forecasts.parquet` and `forecast_history.parquet`. Model version: `logit-lookup-offset-v1`.

**Safety.** If the model cannot be served (missing artifact or ratio column, under 20k training rows, a coefficient outside ±3, rain rows for D on under 90% of beaches, or the model's lookup term drifting from `compute_lookup`), the step serves the plain lookup and records why. `scripts/verify_served_estimate.py` then fails the job after the commit and deploy, so the fallback ships and still raises a `pipeline-failure` issue. Rollback without a code change: set the repository variable `SHORELIFE_SERVED_ESTIMATE=lookup`.

**Evidence.** Walk-forward backtest, forward D+1..3 (2025-09..2026-09): AUROC 0.827 → 0.851, AUCPR 0.548 → 0.591, Brier 0.0803 → 0.0766, within-beach AUROC 0.45 → 0.64. The beach-cluster bootstrap CIs exclude 0. Dry run on the 2026-09-27 data: 374 beaches, 116,613 training rows, 100% rain coverage, about 9 s per run, idempotent across both runs. `validate_forecast` passes, anomaly checks included. Mean p went 0.135 → 0.097. Bands vs the served lookup: 24 Moderate→Low, 12 High→Moderate, 3 High→Low, 2 Very High→High, none up (a dry day).

**Review corrections.**
- Drivers were computed before the floors: 8 posted beaches at the High floor read "below this beach's 12-month record". They are now computed on the served number, and the line is dropped on posted beaches.
- A dead rain feed would have scored every beach as dry. It now falls back to the lookup.
- "Recent" was applied to old exceedances.
- A fallback to the lookup was silent.
- The interval was shifted from the floored bound instead of the Beta quantile.

The tests for each were mutation-checked. Backend suite: 709 passed.

**Caveat.** At the Low cutoff it misses about as many exceedances as the lookup, with ~23% fewer false alarms. It is slightly overconfident at the extremes on forward days.

**Apps.** Web copy: kylechoi101/shorelife-web#14. Mobile copy: kylechoi101/shorelife-mobile#1, against `feat/dual-mode`, which is where `465cf9b` and the live OTA are. Both change the band rates to the served model's 4 / 19 / 37 / 87%, and both should merge after this backend change has served a day.

## 2026-10-02 — UPDATE_PLAN Phase 0–1: data fixes, county sources (in progress)

Branch `feat/update-plan-phase1` (worktree `../surf_health-p1`), runbook `docs/UPDATE_PLAN.md`.

**Phase 0.** Baseline `pytest -q`: 718 passed / 0 failed. Before snapshot built locally the CI
way from pinned raw inputs (`data/snapshots/raw-2026-10-02/`, BeachWatch CSVs downloaded once
and reused for "after"), training `--winner-only` without spatial backtests, forecast date
pinned to 2026-10-02. **Local vs served:** against the CI-committed 10-02 run (`e5a826fe7`, what
Render serves) the local before has the same 375 served beaches, +19 observation rows, +3
culture positives, the same median age; 7 of 375 bands differ, all from fetch timing (advisory
scrape 17:38 vs 20:32; live feed −41 Live / +59 SafeToSwim rows). The worktree venv first
resolved torch 2.14.1 vs main's 2.11.0 (an MPS test failed); synced to main's exact freeze so
before and after differ only in code.

**Found: 10,790 SafeToSwim rows on the wrong beach.** `ceden.py::build_ceden_station_crosswalk`
looked the CEDEN station code up in an index of BeachWatch station *names*, so codes never
matched and fell through to "nearest station within 0.5 km" — the neighbour (EH-030→EH-033,
IB-070→IB-069, BDP13→MDP11, S-3→Doheny DSB4Z). Each row kept its true `station_code`, so the
defect is exact: 10,703 `BeachWatch.SafeToSwim` + 87 `CEDEN.SafeToSwim`, 2,312 exceedances
(1,412 rows / 202 exceedances in the last 365 d), mostly San Diego and Orange. Fixed at the
root (code match first) and repaired in place (`sample_key.rebind_by_station_code`). Label
effect: 5,990 beach-days that existed only through a neighbour's sample removed, 302
exceedance→clean flips, 11 the other way; last 365 d positives 4,859 → 4,697.

**1.1 canonical sample key** (`sample_key.py`): collapses 12,085 physical duplicates incl. all
151 SF CountyDirect rows later re-reported by SafeToSwim/Live (the 151 were a cross-run effect
of the incremental pipeline, not merge order within a run). Same-source different-value rows
are kept as separate samples (first draft collapsed them and lost 164 exceedances). 8
exceedances are dropped where `BeachWatch.Live` revised a SafeToSwim reading at the same
timestamp — by rule. 3,712 groups keep >1 row (plan expected a few hundred): same-source
pairs with different values, e.g. Enterolert + MF the same day.

**1.4 Orange County.** OC did not stop publishing — it stopped reporting to the state (state
routes end 2026-08-24). `ocbeachinfo.com/data/` links a running-year xlsx
(`Orange-County-Beach-Monitoring-Data-2026-9.15.2026.xlsx`, 5,459 enterococcus rows,
2026-01-05..09-11, all 180 StationIDs = `beaches.station_code`). Mirror check vs state,
2026-03-01..07-31: 3,363 state beach-days, 3,230 matched (96.0%); identical value 94.1% of
matched, 95.1% counting non-detects (xlsx `ND` blank vs state 0/1) as identical; exceedance
label agreement 99.63% (state 131 positives vs xlsx 119 — the excess state positives are the
mis-bound SafeToSwim rows above, e.g. S-3's 820 on Doheny DSB4Z 04-28). Newest OC sample is
09-11 (21 d), so OC re-enters serving under the 30-d gate but the plan's "within 14 days"
check cannot pass until OC posts its next file. **Monterey: no public source** — the county
page offers a phone hotline only (831-755-4599); per-beach pages carry no status or results;
state routes end 2026-08-25. Needs outreach to Monterey County EH, not code.

**1.5 scraper failures, live-investigated.** San Diego moved to an OutSystems app
(`cosdapps.sandiegocounty.gov/sdbeachinfo`); `BlockNotification/ScreenDataSetGetEventsList`
returns station ID + issue time per event type, browser-free. San Mateo's page moved; per-site
posting status is a Google My Maps layer exportable as KML. Santa Barbara's map reads a
public ArcGIS layer with status *and* numeric results for all 16 beaches. OC's parser works
locally (3/3) — the CI failure is runner-specific; the scraper will now log what it received.
Humboldt/Sonoma/SLO: the advisory step lacks `GITHUB_TOKEN` and `models: read`. Ventura's
parser emits prose fragments ("cate that water quality at the following beach") that were
all 3 of CI's "unexpected unresolved". Los Angeles' "error" is informational (no warnings
in window). Implementation: task `county-scrapers`.

**canonical-sample-key task closed** (`office/tasks/2026-10-02-canonical-sample-key`): `sample_key.py`
(rebind + collapse + `assay_kind`), `ceden.py` crosswalk fix, cli wiring, `label_method` in
beach_day / history / forecasts (never a model input — pinned by test). PM-run acceptance: full
suite 741 passed / 0 failed, ruff clean. Corrections: phase 25 (collapse lost 164 exceedances →
same-source rule + rebind). Worker's phase 50/75 reports misstated the lost-exceedance count as
0 (PM recompute 8). Tokens (Gemini): 25: 510k (two runs), 50: 425k, 75: 826k, 100: 272k.

**county-scrapers task closed** (`office/tasks/2026-10-02-county-scrapers`). San Diego (OutSystems
`GetEventsList`, runtime apiVersion discovery), Santa Barbara (ArcGIS layer), San Mateo (My Maps
KML + notices, resolved through `StationResolver` — the old inline unguarded substring scanner is
gone), OC advisory diagnostics, OC lab-result connector (`fetch_orange_county_samples`, 2,024
station-days live; `"Orange"` in `INGEST_COUNTIES`), Monterey recorded as no-source, workflow
`GITHUB_TOKEN` + `models: read`, Ventura prose fragments rejected, resolver layer kinds + per-county
`heuristic_matches` + `--heuristic-mode {resolve,suggest}` (default still `resolve`; UPDATE_PLAN
1.3.4 flips it after this alias review is merged). Gemini dropped twice on Google network resets
in phase 50; Cursor failed on an `office-worker` bug (`--continue` with no prior Cursor chat when
a task switches worker mid-way); phases 50–100 ran on the Claude Sonnet fallback.
**PM fixes after acceptance:** `RetryingClient.post` had no `json=`, so San Diego failed in every
real `main()` run while the worker's raw-httpx smoke and MockTransport tests passed; fixed, and
the offline test now drives `RetryingClient` (fails without the fix). **1.3 review:** in the live
10-02 scrape, 2 of the 5 substring-layer resolutions were wrong-beach — "Newport Bay - Bayside
Drive Beach" → Newport Beach BGC (should be BNB33, literally "Bayside Drive Beach") and "Dana Point
Harbor - All of Baby Beach" → Doheny DSB5U (should be BDP12–15). With the advisory floor, that
put a Doheny station at High while the four Baby Beach stations showed their own band. 10 alias
rows added (wrong ones corrected, Baby Beach fanned out, 3 correct picks confirmed) + Calera Creek
unmapped. Result: `resolve` == `suggest` == 90 resolved, 0 heuristic (CI 10-02: 59).
Full suite 773 passed / 0 failed. Tokens: Gemini 25: 538k; Claude fallback 50/75/100 ≈ 41k
(reported by the CLI).

**2026-10-02 (late) — CEO plan amendments applied** (Monterey, OC freshness). UPDATE_PLAN 1.4:
Monterey connector dropped; the outreach asks Monterey County EH to *resume reporting to the
State Water Board* (last state row 2026-08-25; hotline 831-755-4599) — the state routes pick it
up with no code change. 1.4 check: "OC within 14 days" replaced by a spreadsheet-match check —
PASS (newest 2026-09-11 both; per station 178/180 equal, 2 newer from state, 0 older). 1.5:
Monterey marked `no_public_source` (new `CountyReport` field, never `error`), so the known gap no
longer counts as a scraper breakage (after: 4 errors, all expected). 1.6 / 2.5: Orange County is
the only new county in the comparison. OC posting cadence measured from the county's WordPress
media library (uploads since 2020): median gap 20 / 36 / 21 days in 2023 / 2024 / 2025, newest
sample 1–4 days old at upload; at the 2024 cadence OC would be unserved ~20% of days under the
30-day gate. Unfloored OC forecasts track the 12-month record at r = 0.967, same as the rest of
the state.
