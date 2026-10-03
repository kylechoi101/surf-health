# Status

| phase | verdict | time | note |
|---|---|---|---|
| 25 | corrected | 2026-10-02 17:43 | collapse drops 164 exceedances: same-source diff-value rows merged; mis-bound STS rows (station_code≠beach_id, 10,790) need rebind first. C1+C2 added |
| 25 | aligned | 2026-10-02 17:53 | rerun: rebind 10,790; lost-exceedance 164→8 (all Live revisions of STS, by rule); ceden.py root fix; suite 736/0 after PM synced worktree venv to main (torch 2.14.1→2.11.0 was the MPS failure) |
| 50 | aligned | 2026-10-02 18:00 | wiring OK; suite 737/0. Report claimed lost-exceedance 0 — PM recompute = 8 (Live revisions, allowed). Label impact: rebind removes 5,990 phantom beach-days, 302 1→0 flips; collapse 8 flips; last-365d positives 4859→4697 |
| 75 | aligned | 2026-10-02 18:08 | label_method in beach_day/schema_guard/history/forecasts. PM verified training matrices are select_dtypes(number) so the string column never reaches a model; test requested in 100 |
| 100 | aligned | 2026-10-02 18:13 | PM ran acceptance: test_sample_key 18/18; full suite 741/0; ruff clean; rows 508296→496211, CountyDirect 232→81, groups>1 3712, lost-exceedance 8 (Live revisions). Worker code left uncommitted in ../surf_health-p1 per office rules |
