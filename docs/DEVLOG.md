
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
