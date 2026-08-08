# Step 2 — weather backfill coverage report (2026-08-07)

Step 2 of the rebuild programme (`REBUILD_STEPS.md`). Fills the hole behind the
seven weather-derived "marine microbiology" features so Step 6 can test the
photo-inactivation and plume-transport hypotheses against data that exists, and
so the `+0.029 AUCPR, spatially confirmed` claim in `CLAUDE.md` can be re-checked
against features that are actually present rather than zero-filled.

Every figure below is measured against the pinned Step 1 baseline
(`data/baseline/2026-08-07`, sha256 verified before and unchanged after), not
against a live frame.

---

## 1. Headline

| | before | after |
|---|---|---|
| 6 ERA5 features, **2020+ rows** (n=192,052) | 22.23% | **99.99%** |
| `uv_index_24h_max`, **2020+ rows** | 4.14% | **99.99%** |
| 7 weather features, **1095d training window** (n=89,071) | 26.71% / 8.93% | **100.00%** |
| window beaches at ≥95% coverage (of 671) | **109** | **671** |
| `exceeds_stv` flips | — | **0** |
| `enterococcus_value` changes | — | **0** |
| `beach_day` rows / columns | 492,543 / 83 | **492,543 / 83** |

Both exit criteria are met. The 0.01% shortfall on 2020+ is **22 beach-days on
2020-01-01**, the first day of the fetch range, whose 24-hour window reaches back
into 2019 where nothing was fetched. It is a real absence, not a gap — see § 5.

## 2. Coverage, all 11 marine-microbiology features

`notna()` fraction. The four static-geometry features are listed to show they did
not move; the step touched the eight weather-derived columns and nothing else.

| feature | full frame | | 2020+ | | 1095d window | |
|---|---|---|---|---|---|---|
| | before | after | before | after | before | after |
| `shore_normal_wind_ms` | 8.67% | 38.99% | 22.23% | **99.99%** | 26.71% | **100.00%** |
| `solar_inactivation_index` | 8.67% | 38.99% | 22.23% | **99.99%** | 26.71% | **100.00%** |
| `cloud_cover_24h_mean` | 8.67% | 38.99% | 22.23% | **99.99%** | 26.71% | **100.00%** |
| `shortwave_24h_sum` | 8.67% | 38.99% | 22.23% | **99.99%** | 26.71% | **100.00%** |
| `wind_speed_24h_max` | 8.67% | 38.99% | 22.23% | **99.99%** | 26.71% | **100.00%** |
| `days_since_sunny` | 8.67% | 38.99% | 22.23% | **99.99%** | 26.71% | **100.00%** |
| `uv_index_24h_max` | 1.62% | 38.99% | 4.14% | **99.99%** | 8.93% | **100.00%** |
| `wind_direction_24h_mean` † | 1.62% | 38.99% | 4.14% | **99.99%** | 8.93% | **100.00%** |
| `dist_to_pier_km` | 100% | 100% | 100% | 100% | 100% | 100% |
| `is_near_pier` | 100% | 100% | 100% | 100% | 100% | 100% |
| `dist_to_estuary_km` | 100% | 100% | 100% | 100% | 100% | 100% |
| `is_near_estuary_mouth` | 100% | 100% | 100% | 100% | 100% | 100% |

† not one of the "11", but produced by the same aggregation and previously stuck
at UV's coverage for the same reason (both columns were added to
`aggregate_solar_wind_windows` after most cached rows were written).

**The full-frame column caps at 38.99% by construction.** 61.0% of `beach_day`
(300,491 rows) predates 2020-01-01, and ERA5 was only fetched from 2020 —
the range `REBUILD_PLAN.md` specifies. 38.99% of the full frame *is* 100% of the
2020+ rows. None of those pre-2020 rows are in the training window.

### By year

| year | n | `shore_normal_wind_ms` | | `uv_index_24h_max` | |
|---|---|---|---|---|---|
| | | before | after | before | after |
| 2019 | 28,167 | 0.00% | 0.00% | 0.00% | 0.00% |
| 2020 | 28,245 | 19.00% | **99.92%** | 0.00% | **99.92%** |
| 2021 | 29,998 | 18.17% | **100.00%** | 0.00% | **100.00%** |
| 2022 | 27,791 | 18.05% | **100.00%** | 0.00% | **100.00%** |
| 2023 | 29,343 | 17.86% | **100.00%** | 0.00% | **100.00%** |
| 2024 | 30,859 | 17.36% | **100.00%** | 0.00% | **100.00%** |
| 2025 | 28,793 | 18.18% | **100.00%** | 0.00% | **100.00%** |
| 2026 | 17,023 | 64.76% | **100.00%** | 46.73% | **100.00%** |

Note that the pre-backfill UV column read **0.00% for every year 2020–2025** —
the 8.93% window figure was entirely 2026 rows.

### By the Step 1 bimodal beach split

Step 1 found coverage was bimodal *by beach*, not a temporal drift. Reproduced
here on 2020–2025 rows of the baseline frame: **106 beaches >95% covered, 578
beaches <5%, zero in between** (Step 1 reported 105/552 on a slightly different
counting rule; same shape).

| group | window rows | `shore_normal_wind_ms` | | `uv_index_24h_max` | |
|---|---|---|---|---|---|
| | | before | after | before | after |
| the 106 covered beaches | 15,837 | 100.00% | 100.00% | 8.17% | **100.00%** |
| the 578 uncovered beaches | 73,223 | 10.85% | **100.00%** | 9.09% | **100.00%** |

The split is now gone: **all 671 window beaches are ≥95% covered** (was 109), and
none are below 5% (was 101). Median per-beach window coverage 11.27% → 100%.

## 3. What the model was actually reading

`build_inference_features` zero-fills missing values, so the absent 73% was not
read as "unknown" — it was read as a *measurement of zero*. Means over the 1095d
window, what the model saw versus the truth now on disk:

| feature | model read | truth | ratio |
|---|---|---|---|
| `solar_inactivation_index` | 2.314 | 12.503 | 5.4× |
| `shortwave_24h_sum` (MJ/m²) | 3.689 | 19.832 | 5.4× |
| `uv_index_24h_max` | 0.706 | 6.532 | 9.3× |
| `cloud_cover_24h_mean` (%) | 10.453 | 40.676 | 3.9× |
| `wind_speed_24h_max` (m/s) | 1.086 | 4.300 | 4.0× |
| `days_since_sunny` | 0.684 | 4.073 | 6.0× |
| `shore_normal_wind_ms` | 0.067 | 0.242 | 3.6× |

`shore_normal_wind_ms` is the one to be careful with: it is *signed* (positive =
onshore), so zero-fill did not merely shrink it, it inserted a neutral wind on
73% of rows and destroyed the onshore/offshore contrast the feature exists to
express.

## 4. UV: what is real, what is a proxy, and what is permanently gone

`uv_index_24h_max` has always fallen back to a shortwave stand-in
(`shortwave_peak / 80`, capped at 15) when no real UV was available, so it was
never *missing* in the way the ERA5 columns were — it was **present and
synthetic**. Coverage therefore understates the change; provenance is the real
story. Recorded per row in `solar_wind_daily.parquet` as `uv_index_is_proxy`.

| population | rows with a value | real measured UV | shortwave proxy |
|---|---|---|---|
| 1095d window | 89,071 | **89,071 (100%)** | 0 (0%) |
| 2020+ | 192,030 | 116,822 (60.8%) | 75,208 (39.2%) |

- **The whole 1095-day training window is real measured UV.** The window starts
  2023-08-07; the air-quality archive starts 2022-08-04.
- **2020-01-01 → 2022-08-03 is permanently proxy.** This is not a fetch that can
  be retried — the source does not go back that far (§ 4.1). If a future analysis
  needs a UV-clean sample, it must start at 2022-08-04.
- On the 7,955 rows that had a UV value *before* this step, **99.5% changed**:
  mean 7.90 (proxy) → 9.28 (real). The proxy was not calibrated to the real
  index, so any prior fit on `uv_index_24h_max` was fitting a rescaled shortwave
  variable under a UV name. That is a change of feature *meaning*, not only of
  coverage, and Step 7 should not compare a new UV coefficient to an old one.

### 4.1 The earliest UV date, pinned

`archive-api.open-meteo.com/v1/archive` (ERA5-Land) **cannot supply UV at all**.
Re-verified live on 2026-08-07 — it accepts `uv_index` in `hourly`, answers
**HTTP 200**, includes the key, and returns `null` for every hour:

```
archive 2023-08-06..08   cloud_cover 72/72   shortwave_radiation 72/72
                         wind_speed_10m 72/72  wind_direction_10m 72/72
                         uv_index  0/72          <-- silent
archive 2020-01-01..03   uv_index  0/72          <-- same in 2020
```

`air-quality-api.open-meteo.com/v1/air-quality` does serve it. Single-day probes,
`hourly=pm10,uv_index`, at 33.9/-118.4:

| date | `uv_index` non-null | `pm10` non-null |
|---|---|---|
| 2022-07-25 | 0/24 | 0/24 |
| 2022-07-28 | 0/24 | 0/24 |
| 2022-07-29 | 0/24 | 0/24 ← Open-Meteo's *documented* start; not what is served |
| 2022-08-01 | 0/24 | 0/24 |
| 2022-08-02 | 0/24 | 0/24 |
| 2022-08-03 | 0/24 | 0/24 |
| **2022-08-04** | **24/24** | **24/24** ← first served hour |
| 2022-08-05 | 24/24 | 24/24 |
| 2022-09-01 | 24/24 | 24/24 |

Identical boundary at 33.9/-118.4 (Los Angeles), 32.6/-117.1 (San Diego) and
40.8/-124.2 (Humboldt). A single multi-day request over 2022-08-01..08 returns
120/192 non-null with its first non-null hour at exactly **2022-08-04T00:00 UTC**.
`pm10` shares the boundary, so this is the archive's start date, not a UV-specific
gap.

Recorded as `UV_ARCHIVE_EARLIEST_DATE` in
`backend/app/data/connectors/hydrology_sources.py`, with this table in the
constant's docstring.

> ⚠️ **2022-08-04 is 1,464 days before the probe date** — close enough to a
> rolling ~4-year retention window to be worth treating as one. If it rolls, the
> earliest reachable UV advances about a day per day and older history becomes
> unrecoverable. The 40 MB of UV already cached on disk is the mitigation; do not
> delete it expecting to refetch.

## 5. The partial-window bug, found and fixed

Not in the plan. Found while checking why rows that *already had* a value changed.

A daily summary covers the 24 hours ending at the 5 AM PT cutoff, so a complete
window is exactly 24 hourly samples. The daily pipeline refetches only
`[last_stored_date − 7d, today]` and aggregates that slice **in isolation**, so
the slice's first day never has the preceding evening's hours and its aggregates
came out truncated. Because the merge is `keep="last"` (new wins) and each run's
window starts one day later than the last, **every day was written exactly once
while it sat at position 0 of a fetch window, and then never repaired.**

Reproduced directly on one cell, aggregating a 7-day slice against continuous
history:

```
sample_date   full   incremental
2026-06-01   30.79       4.93     <- slice's first day
2026-06-02   29.96      29.96
2026-06-03   28.39      28.39     ... all remaining days identical
```

Blast radius on the shipped frame: of the 42,687 beach-days that carried a
`shortwave_24h_sum` before this step, **8,767 (20.5%) were wrong**, and they are
*all* in 2026-04..2026-07 — exactly the window the 116 partially-cached cells were
filled by daily incremental runs. Median 4.57 MJ/m² against 26.77 for the same
rows recomputed over continuous history, an **83% understatement**;
`days_since_sunny` was reset to 0.

Cross-check that this is a correction and not a new error: the 33,927 rows served
by the 7 cells that always had continuous history reproduce **bit-for-bit**
(mean 19.38 MJ/m²), and the 149,343 newly-covered rows land at mean 19.59 — the
same scale. Only the 8,767 truncated rows moved.

**Fix:** `aggregate_solar_wind_windows` now drops any day with fewer than
`_MIN_WINDOW_HOURS = 24` samples instead of emitting a truncated aggregate. That
is what makes the daily merge safe — `keep="last"` cannot overwrite a good value
with a bad one if the bad one is never emitted. Pinned by
`test_a_partial_24h_window_is_dropped_not_emitted_truncated`.

Consequence: 2020-01-01 is no longer emitted (its window reaches into 2019, which
was not fetched), costing **22 beach-days** and taking 2020+ coverage to 99.99%
rather than 100%. A missing value there is the honest answer.

## 6. Label integrity — this step moved no labels

`diff_curated.py --before data/baseline/2026-08-07 --after data/curated`:

```
-- beach_day.parquet ---------------------------------------------------------
   rows: 492,543 -> 492,543  (+0)
   schema: unchanged (83 columns)
   keys: identical (492,543 on beach_id+sample_date)
   labels: no exceeds_stv flips (492,543 shared rows, base rate 0.1036)
   values: enterococcus_value unchanged
   coverage: 8 column(s) moved (top 25)
     column                                   before    after     delta
     uv_index_24h_max                          1.62%   38.99%   +37.37%
     wind_direction_24h_mean                   1.62%   38.99%   +37.37%
     cloud_cover_24h_mean                      8.67%   38.99%   +30.32%
     days_since_sunny                          8.67%   38.99%   +30.32%
     shore_normal_wind_ms                      8.67%   38.99%   +30.32%
     shortwave_24h_sum                         8.67%   38.99%   +30.32%
     solar_inactivation_index                  8.67%   38.99%   +30.32%
     wind_speed_24h_max                        8.67%   38.99%   +30.32%

-- observations.parquet / beaches.parquet / forecast_history.parquet /
   forecasts.parquet / all four JSON artifacts ------------------------------
   rows unchanged, schema unchanged, keys identical, coverage unchanged
   on every column; JSON byte-identical
```

Achieved by **not** running the pipeline CLI. `--normalize-beachwatch
--with-solar-wind` would also re-normalise BeachWatch, re-merge CEDEN and re-pull
the live feed — i.e. it would move the label, which this step must not do.
`scripts/backfill_solar_wind.py --apply-to-beach-day` instead drops exactly the
eight solar-wind-derived columns from the existing frame, re-merges them on
`(beach_id, sample_date)`, and refuses to write if the row count or the column
set changes.

The **daily** pipeline path is wired to the same shared helpers
(`merge_uv_hourly`, `explode_solar_wind_to_beaches`) so the one-off backfill and
the daily run cannot drift apart.

## 7. Cost

| | |
|---|---|
| grid cells fetched | **120** (0.1° cells covering all 850 CA beaches) |
| requests | 1,440 = 120 cells × (7 ERA5 year-chunks + 5 UV year-chunks) |
| wall-clock, successful run | **19.2 min** |
| wall-clock incl. 2 aborted attempts | ~45 min |
| re-run entirely from cache | **1.3 min** (resumability verified end to end) |
| `openmeteo_solar_wind/` | 109.6 MB, 1,279 files (102.7 MB / 1,196 CA; 6.8 MB / 83 pre-existing TX) |
| `openmeteo_uv/` | **41.4 MB, 600 files** (all CA) |
| **total raw weather cache** | **151.0 MB** (Step 1 estimated 150–200 MB) |
| `solar_wind_daily.parquet` | 289,200 rows × 120 cells, 2020-01-02 → 2026-08-07, 9.15 MB |
| `beach_day.parquet` | 11.17 MB → **14.77 MB** |

> ⚠️ **Do not wire this into the `hydro-${{ runner.os }}-v4` Actions cache.**
> 151 MB against the previous 11 MB. `CLAUDE.md` and `REBUILD_PLAN.md` both flag
> committing the aggregated daily parquet (9.15 MB) as the better option; this
> report is the measurement they asked for. Nothing in CI was changed by this
> step.

### Rate limiting

Open-Meteo throttles the archive by request *weight*, not request count: the
first attempt tripped **HTTP 429** at roughly 40 requests/min, far below the
documented 600 calls/min, and recovered within ~2 minutes. A 1.5 s inter-chunk
pause at the connectors' native `concurrency: 5` ran the whole job without a
single trip.

**The 429 was invisible.** `_fetch_coord` catches HTTP errors, logs, and returns
an empty frame so one bad coordinate cannot kill a daily run — correct for the
daily job, a data-integrity hazard for a backfill, because the chunk comes back
short with no exception anywhere. The first attempt silently dropped whole
cell-years that way. `_fetch_verified` now checks the returned `station_id` set
against the requested one and retries with backoff on a short result, and the run
ends with a completeness audit (`120/120 cells, median 2410 of 2411 expected
days`).

## 8. What this changes for Steps 3–10

1. **Step 6's photo-inactivation test now has power.** Paired same-beach same-day
   culture-vs-ddPCR beach-days with a solar covariate present: **84 → 1,172**
   (with UV present: **70 → 1,172**). `REBUILD_PLAN.md` quotes n = 56 for the
   original analysis; the whole set of 1,172 pairs is now usable. The plume-distance
   correlation (Spearman −0.916) can be tested with solar as a covariate rather
   than as a null column.
2. **Step 6's `+0.029 AUCPR` re-check is now a different experiment.** The
   original claim was measured when these features were ~9–27% present and
   zero-filled elsewhere, i.e. it partly measured *"is this one of the 106 beaches
   near a fully-cached grid cell"*, which is a spatial proxy. Whatever the
   re-check finds, it is not comparable to the old number.
3. **Step 7 must not compare UV coefficients across the boundary.** Pre-step
   `uv_index_24h_max` was a rescaled shortwave proxy on 100% of rows; it is now
   real measured UV on the whole training window, on a different scale (§ 4).
4. **Any pre-2022-08-04 UV analysis is capped.** Permanently proxy, possibly a
   rolling window that will erode further. Not fixable.
5. **Steps 3–5 inherit a clean diff harness result.** The baseline is unchanged
   and still restorable; `diff_curated.py` shows this step moved exactly eight
   coverage numbers and nothing else, so any label movement seen in Step 4 is
   entirely Step 4's.
6. **The daily job now fetches a second endpoint.** `--with-solar-wind` calls the
   air-quality archive alongside ERA5. Failure degrades to the shortwave proxy —
   it cannot block a run — but it is a new external dependency in the daily path.
7. **A silent-null re-run is now impossible.** `AllNullVariableError` fails the
   fetch when a requested variable comes back 100% null while its siblings are
   populated, and refuses to cache the column. See § 9.

## 9. The all-null guard: chosen semantics

The failure this exists to stop is precise: a variable the endpoint **does not
serve**, returned as `null` for every hour inside an otherwise-healthy 200
response. That hid a missing feature for three months and would have burned this
step's entire compute budget leaving UV at 0%.

The guard fires only when all three hold:

1. the response has timestamps (something came back);
2. **at least one other requested variable is ≥50% populated** — a witness that
   the endpoint answered correctly for this coordinate and date range;
3. the offending variable has **exactly zero** non-null values.

Then it raises `AllNullVariableError`, and the response is **not cached**. The
`asyncio.gather(return_exceptions=True)` loops re-raise it specifically, because
a misconfigured variable is wrong for every coordinate and must not be reduced to
a log line.

Everything else is treated as transient and does **not** raise:

- no timestamps at all → empty frame, caller retries next run;
- *every* requested variable null → an outage, a coordinate outside the model
  domain, or a date before the archive begins. This is exactly the shape the UV
  connector sees before 2022-08-04, and it must not be fatal.
- a sibling below the 50% floor → the sibling is itself degraded, so it cannot
  witness anything, so nothing is provable.

**Why this line and not "raise on any null":** a reanalysis or air-quality outage
degrades *all* variables together and lands in the transient branch, so the daily
job survives it. A single systematically-empty column while its siblings are full
has never once been transient in this codebase — it has always been a request for
something the endpoint does not have. Condition (2) is the whole safety argument.

Escape hatch for operators: `OPENMETEO_ALLOW_NULL_VARS=1` downgrades the raise to
an error log. The column is still refused; it is never cached all-null.

`OpenMeteoHistoricalUvConnector` requests a single variable, so condition (2) can
never hold for it and the transient branch always wins — correct, because
pre-epoch dates return that shape. It carries a second, explicit refusal: an
all-null UV response is logged and skipped rather than written to disk.

---

## Reproduce

```bash
cd backend
# fetch + aggregate + apply (resumable; re-runs from cache in ~1.3 min)
.venv/bin/python scripts/backfill_solar_wind.py \
    --start 2020-01-01 --cell-batch 5 --pause 1.5 \
    --state-file /tmp/backfill.state --apply-to-beach-day

# prove nothing but coverage moved
.venv/bin/python scripts/snapshot_curated.py --out /tmp/after-2026-08-07
.venv/bin/python scripts/diff_curated.py \
    --before ../data/baseline/2026-08-07 --after /tmp/after-2026-08-07
```

## Files

| file | change |
|---|---|
| `backend/scripts/backfill_solar_wind.py` | **new** — resumable, rate-limit-aware, completeness-audited backfill driver + surgical `--apply-to-beach-day` |
| `backend/app/data/connectors/hydrology_sources.py` | `AllNullVariableError` + `_assert_no_all_null_variables`; `uv_index` removed from the archive connector; **new** `OpenMeteoHistoricalUvConnector` + `UV_ARCHIVE_EARLIEST_DATE` |
| `backend/app/data/pipeline/solar_wind.py` | `_MIN_WINDOW_HOURS` partial-window guard; `uv_index_is_proxy` provenance; `merge_uv_hourly`, `explode_solar_wind_to_beaches`, `map_beaches_to_solar_wind_stations`, `SOLAR_WIND_DERIVED_COLUMNS` |
| `backend/app/data/pipeline/cli.py` | `--with-solar-wind` fetches real UV and uses the shared join helpers |
| `backend/tests/test_openmeteo_null_guard.py` | **new** — 16 tests: the guard, the transient/never distinction, the UV connector, the partial-window rule |
| `data/curated/solar_wind_daily.parquet` | 29,152 → 289,200 rows |
| `data/curated/beach_day.parquet` | 8 columns repopulated; rows, schema and labels untouched |
| `data/raw/cnrfc/openmeteo_solar_wind/`, `.../openmeteo_uv/` | 11 MB → 151 MB |
