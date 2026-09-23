
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
