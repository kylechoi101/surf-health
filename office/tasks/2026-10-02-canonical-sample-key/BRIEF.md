---
task: canonical-sample-key
repo: /Users/kylechoi/surf_health-p1
worker: gemini
created: 2026-10-02
status: open
---

## Goal

`observations.parquet` holds the same physical lab sample more than once when two
sources report it with timestamps that differ (SafeToSwim 08:50 vs Live 08:51), or when one
source is date-only (CountyDirect, San Francisco). Every existing dedupe is keyed on
`sample_time`, so none of them catches these. Measured on the 2026-10-02 snapshot: 5,423 rows
share (beach, date, assay, value) with another row, and all 151 CountyDirect rows dated
2026-07-06..2026-09-01 have a `BeachWatch.SafeToSwim` (139) or `BeachWatch.Live` (12) twin
with an identical value. That happens because the pipeline is incremental: the state twin
arrives on a later run, after the county row's one-time gap-fill check has already passed.

When this task is done there is one canonical sample key and one final collapse pass that
runs at the end of observation merging, so a physical sample appears once. The assay method
(`ddpcr` / `culture`) is also carried into `beach_day` as `label_method`.

## In scope

1. New module `backend/app/data/pipeline/sample_key.py`:
   - `assay_kind(method: pd.Series, units: pd.Series) -> pd.Series` of `"ddpcr"` /
     `"culture"`. It MUST call the existing `app.data.pipeline.exceedance.is_pcr_measurement`
     (do not write a second PCR rule).
   - `CANONICAL_KEY = ["beach_id", "sample_day", "analyte", "assay_kind"]`.
   - `with_canonical_key(df) -> pd.DataFrame`: returns a copy with `sample_day` =
     `pd.to_datetime(sample_time).dt.normalize()` (fall back to `sample_date` when
     `sample_time` is null) and `assay_kind` added. `value` is NOT in the key: a revised
     result must not become a second sample.
   - `collapse_physical_duplicates(df) -> pd.DataFrame`: keeps one row per physical sample.
     - Within one key group, two rows are DISTINCT samples only if both have a real
       collection time (time-of-day not exactly 00:00:00) and the times are more than
       30 minutes apart. Everything else in the group is one sample. Implement by sorting
       timed rows by time and starting a new cluster when the gap to the previous timed row
       is > 30 min; date-only rows (time-of-day 00:00:00, which is how CountyDirect rows are
       stored) join the cluster of the best-priority timed row, or form their own cluster if
       the group has no timed row.
     - Winner within a cluster: a row with a real collection time beats a date-only row;
       then source priority
       `BeachWatch.Live > BeachWatch.SafeToSwim > BeachWatch > CEDEN.SafeToSwim > CountyDirect`
       (null `data_source` = `BeachWatch`); unknown sources rank after CountyDirect.
       A CountyDirect row survives only when no other source is in its cluster (gap-fill).
       Final tiebreak between rows of the SAME source priority: higher `exceeds_stv`
       (True first), then higher `value`, then later `sample_time` — the worst sample wins,
       matching `build_beach_day_frame`'s false-negative-averse rule (note: 35% of
       `BeachWatch` rows are date-only, so same-source same-day collisions do happen).
       Add a test: two `BeachWatch` date-only rows, same key, values 50 and 200 → the 200
       row is kept.
     - Add a `merged_from` string column on every output row: the sorted, `;`-joined
       distinct `data_source` values of all rows collapsed into it (just its own source when
       nothing was collapsed).
     - Drop the helper columns (`sample_day`, `assay_kind`, internal ranks) before returning;
       keep every original column and the original dtypes. Deterministic output order:
       sort by `beach_id`, `sample_time` (stable).
     - Print one line: `[sample-key] collapsed N physical-duplicate rows (by source: ...)`.
2. Wire it into `backend/app/data/pipeline/cli.py` `main()`: call
   `collapse_physical_duplicates(bundle["observations"])` exactly once, AFTER the
   `if args.with_county_direct:` block and BEFORE `uv_daily = pd.DataFrame()` /
   `if args.with_external_covariates:`. If it changed the row count, re-run
   `refresh_latest_official_sample_at` and `build_beach_day_frame` the same way the
   county-direct block does. Leave all existing per-source dedupes untouched.
3. `label_method` in `beach_day` (`backend/app/data/pipeline/beachwatch.py`,
   `build_beach_day_frame`): before `method`/`units` are dropped, add
   `label_method = assay_kind(method, units)` computed from the row that won the
   worst-sample collapse. Rows without method AND units get `"culture"` (the same default
   `action_value_ratio` uses). Keep dropping raw `method`/`units`.
4. Add `"label_method"` to `schema_guard.EXPECTED_FEATURE_COLUMNS` (warn-only, with a short
   comment like the neighbouring entries).
5. Add `"label_method"` to `served_metrics._HISTORY_COLUMNS`, and in
   `backend/app/ml/lookup_serving.py` write a `label_method` column into `forecasts.parquet`:
   each served beach's most recent `beach_day.label_method` (null if it has none). Missing
   columns in older history rows must stay null, not crash (follow how
   `persistence_floor_applied` is handled there).
6. Tests:
   - `backend/tests/test_sample_key.py`:
     - SafeToSwim 08:50 and Live 08:51, same value → one row; `merged_from` lists both.
     - Same pair, different value (a revision) → one row, Live's value kept.
     - 08:50 and 14:10 same key, different values → two rows.
     - SF date-only (00:00) CountyDirect row alone → kept.
     - SF date-only CountyDirect + state timed row same day → state row kept,
       `merged_from` contains `CountyDirect`.
     - ddPCR (`method="ddPCR"`, `units="copies/100 mL"`) and culture (`"Enterolert"`,
       `"MPN/100 mL"`) on the same beach-day → two rows.
     - Different analytes same beach-day → two rows.
     - `assay_kind` agrees with `is_pcr_measurement` on a mixed series.
   - Extend existing tests (find them with `grep -l build_beach_day_frame tests/`) with one
     case asserting `label_method` is `ddpcr` for a day whose worst sample is ddPCR and
     `culture` otherwise.
   - A lookup_serving test (extend the existing one) asserting `label_method` lands in
     `forecasts.parquet`.

## Out of scope

- Adding `label_method` to any model feature set (XGB, logistic, lookup). It must NOT
  appear in `training._model_feature_columns` output; if the training loader's allowlist
  would pick it up, leave it out of the allowlist.
- Removing or changing existing per-source dedupes (`dedupe_incremental_beachwatch_observations`,
  `merge_live_into_observations`, `ceden.py`, `county_direct.py`).
- Running the real pipeline or touching anything under `data/`.
- Any change to scrapers, workflows, web or mobile.

## Allowed files

- backend/app/data/pipeline/sample_key.py
- backend/app/data/pipeline/cli.py
- backend/app/data/pipeline/beachwatch.py
- backend/app/data/pipeline/schema_guard.py
- backend/app/ml/served_metrics.py
- backend/app/ml/lookup_serving.py
- backend/tests/test_sample_key.py
- backend/tests/** (only to add cases for label_method / lookup_serving)

## Allowed packages

- none (pandas, numpy already present)

## Acceptance

```bash
cd /Users/kylechoi/surf_health-p1/backend
.venv/bin/pytest -q tests/test_sample_key.py         # all pass
.venv/bin/pytest -q                                   # >= 718 passed, 0 failed (baseline 718)
.venv/bin/ruff check app tests                        # clean
.venv/bin/python - <<'EOF'
import pandas as pd
from app.data.pipeline.sample_key import CANONICAL_KEY, with_canonical_key, collapse_physical_duplicates
o = pd.read_parquet("../data/curated/observations.parquet")
c = collapse_physical_duplicates(o)
k = with_canonical_key(c)
print("rows", len(o), "->", len(c))
print("CountyDirect", (o.data_source=="CountyDirect").sum(), "->", (c.data_source=="CountyDirect").sum())
print("groups with >1 row:", (k.groupby(CANONICAL_KEY).size() > 1).sum())
EOF
# expect: CountyDirect 232 -> 81 (the 151 twins gone); groups with >1 row a few hundred at most
```

## Phases

### Phase 25
Deliverable: `sample_key.py` with `assay_kind`, `CANONICAL_KEY`, `with_canonical_key`, `collapse_physical_duplicates`, and `tests/test_sample_key.py` passing.

### Phase 50
Deliverable: the collapse is wired into `cli.py` at the specified point with beach_day / latest_official_sample_at rebuilt on change, plus the acceptance python snippet's output pasted in the report.

### Phase 75
Deliverable: `label_method` in `build_beach_day_frame`, `schema_guard`, `_HISTORY_COLUMNS`, and `forecasts.parquet` via lookup_serving, with tests.

### Phase 100
Deliverable: full suite and ruff clean, and all Acceptance commands pass with output pasted in the report.

## Corrections

(appended by the PM; newest last; each entry dated)
