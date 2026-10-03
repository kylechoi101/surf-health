# Status

| phase | verdict | time | note |
|---|---|---|---|
| 25 | aligned | 2026-10-02 19:25 | 5 non-XGB arms, within-beach bootstrap delta, culture/ddpcr slices; logit arm == compare_logit_challenger to all digits (Aug smoke, before snapshot); suite 781/0 |
| 50 | blocked | 2026-10-02 19:41 | Gemini out of AI credits (429 RESOURCE_EXHAUSTED) mid-phase; partial edits kept. Cursor skipped (office-worker --continue bug on mid-task switch); moving to claude fallback |
| 50 | aligned | 2026-10-02 19:48 | (claude fallback) XGB arms via build_sliding_windows (PM verified = training.py path) + _build_forecast_candidates per D; leak-check test; 5.98 s/D → daily grid. Served-log check compared raw ensemble to router-blended served ML (Aug: 89% rows offset-weighted, mean w 0.86) — invalid comparison; corrected in 75 |
| 75 | aligned | 2026-10-02 19:58 | served-log check vs router blend: AUROC gap 0.0194 (bar 0.02, PASS narrowly) on before/Aug, n=5,914; diff_comparisons.py with common/full/new-beach, bands, PROMOTION verdict + reversal check; suite 794/0 |
| 100 | aligned | 2026-10-02 20:07 | PM re-ran: 21/21, 794/0, ruff clean; /tmp/cam_smoke has 7 arms + served-log n=5914 PASS. Logit parity exact. Full-year runs launched by PM |
