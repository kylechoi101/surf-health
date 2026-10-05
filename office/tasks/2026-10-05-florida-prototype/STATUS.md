# Status

| phase | verdict | time | note |
|---|---|---|---|
| 25 | aligned | 2026-10-05 10:54 | fetch+build: 20,780 sample-days / 241 stations / 2022-08-15..2026-09-24, exceed 5.3%, 0 dup station-days; 8 tests pass (PM ran), ruff clean |
| 50 | aligned | 2026-10-05 11:04 | backtest 2025-10..2026-09: 7,943 rows/437 pos/235 stations; logistic AUROC 0.744 vs lookup 0.728 (CI +0.007..+0.029), AUCPR 0.199 vs 0.180, within-station 0.478 vs 0.315; PM recomputed AUROC/AUCPR from predictions parquet (match); loop is strictly prior, rain coverage 100% |
| 75 | aligned | 2026-10-05 11:19 | forecast 2026-10-05: 223 stations, Low 200 / Moderate 14 / High 9; strictly prior, rain 72h to 05:00 ET from forecast API, 119/119 coords fetched; 12 tests pass. Silent defaults (missing rain -> 0, beta -> 0) to be surfaced in 100 |
| 100 | aligned | 2026-10-05 11:37 | PM ran all 6 Acceptance: 14 passed; ruff clean; `all --forecast-date 2026-10-05` exit 0; 223 stations Low 200/Mod 14/High 9, rain_missing 0, floor holds; backtest AUROC lookup 0.728 / persistence 0.523 / logistic 0.744 / free 0.743, calendar_2025 logistic 0.786 vs lookup 0.772; REPORT.md 157 lines; meta.json model_fallback null |
