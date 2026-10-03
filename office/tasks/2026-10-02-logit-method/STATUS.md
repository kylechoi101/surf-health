# Status

| phase | verdict | time | note |
|---|---|---|---|
| 25 | aligned | 2026-10-02 22:18 | strictly-prior ddpcr/R_ddpcr, assay.py shared, v2 constant; 857 pass + 3 expected verify failures (phase 50). PM checked: compare_all_models v1 arm uses explicit columns (unaffected); compare_logit_challenger now backtests v2 (intended) |
| 50 | aligned | 2026-10-02 22:20 | v2 served; v1 recognised + pooled in live (versions listed); guards cover new coefs; lab_logit incl. ddpcr terms; 864/0 |
| 75 | aligned | 2026-10-02 22:23 | after-snapshot: v2 served, fallback null, validate PASS; 5/496 band changes vs v1 (SD 4 Mod→Low, EBRPD 1 High→VH); coefs in ±3 (ddpcr 0.115, R_ddpcr 0.654); v2 walk-forward vs lookup CIs exclude 0; 865/0 |
| 100 | aligned | 2026-10-02 22:25 | PM ran: 865/0, ruff, v2 served fallback null, validate PASS. PR #48 |
