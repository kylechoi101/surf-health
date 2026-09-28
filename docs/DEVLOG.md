
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

**Not in this change.** Mobile copy was not checked: the app (`465cf9b`, feat/dual-mode) is not in this session's repositories. Its lab-track-record wording likely needs the same edit as web, which described the rating as not reacting to rain.
