| phase | verdict | time | note |
|---|---|---|---|
| 25 | aligned | 2026-09-22 16:07 | pure functions + 6 tests, ruff clean; diffstat data/curated entries are pre-existing tree changes, not worker's |
| 50 | corrected | 2026-09-22 16:11 | advisory rule over-counts: 139 Posted vs 24 active rows (PM spec error; status column is authoritative). Re-running. |
| 50 | aligned | 2026-09-22 16:14 | re-run after correction: 23 active advisories, 850 rows, n_365d added, 7 tests + ruff clean |
| 75 | corrected | 2026-09-22 16:20 | deliverables exist and reproduce 90d numbers; per-beach 'winner' table compares a near-constant predictor within-beach (artifact). Re-running with persistence as the within-beach baseline. |
| 75 | aligned | 2026-09-22 16:25 | re-run: per-beach section now ML vs persistence within-beach (ML mean 0.513, persistence 0.492 over all 148 dates); 11 tests, ruff clean |
| 100 | aligned | 2026-09-22 16:26 | PM ran all 7 acceptance commands: 11 tests pass, both modes exit 0, files present, grep=5, ruff clean |
