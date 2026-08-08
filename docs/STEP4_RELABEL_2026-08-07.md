# Step 4 — full non-incremental relabel (2026-08-07)

Step 4 of `REBUILD_STEPS.md`. Step 3 added `label_method` / `label_units` /
`is_pcr` / `assay_disagreement` to `build_beach_day_frame` **without
regenerating anything**. This step regenerates the label frame so those columns
actually populate across all history, instead of on the seven days the daily
incremental path would touch.

**Shipped: Stage A.** `data/curated/beach_day.parquet` is now 492,543 × **87**
columns, **100% non-null `label_method`**, **zero** `exceeds_stv` flips and
**zero** `enterococcus_value` changes against the pre-step frame.

**Not shipped: Stage B.** The full re-normalisation runs, is fully attributed
(zero unattributed rows), and is snapshotted — but it moves the frame by
**+49%** (492,543 → 732,535 beach-days), for a reason that has nothing to do
with the label: the state export has been republished with ~240k pre-2011 rows
this repo never ingested. `REBUILD_STEPS.md`'s own stop-rule ("if Stage B's
movement is large or unexplainable, STOP and report rather than pressing on")
applies. § 4 is the evidence; § 8 is the recommendation.

---

## 0. Artifacts

| snapshot | `beach_day` sha256 | rows × cols | `observations` sha256 | rows |
|---|---|---|---|---|
| `data/snapshots/step4-pre` | `d0d7c0dcf6e2` | 492,543 × 83 | `5bdaec00fd78` | 503,766 |
| `data/snapshots/step4-postA` **(shipped)** | `8a8c128c374f` | 492,543 × **87** | `5bdaec00fd78` | 503,766 |
| `data/snapshots/step4-postB` (held) | `2ba9c2f1aa79` | **732,535** × 87 | `03c6b737b9a4` | **748,480** |

`data/snapshots/` is gitignored (same rule as `data/baseline/`); the durable
record is `docs/baselines/MANIFEST_2026-08-07_step4-{pre,postA,postB}.json`.

`data/baseline/2026-08-07/` verified byte-identical (9/9 sha256) **before and
after** this step. Never written to.

Reproduce:

```bash
cd backend
# Stage A — rebuild from the observations already on disk
.venv/bin/python scripts/rebuild_beach_day.py \
    --curated ../data/curated \
    --observations ../data/curated/observations.parquet \
    --stations   ../data/curated/beaches.parquet \
    --advisories <state advisories CSV, normalized> \
    --covariate-source ../data/snapshots/step4-pre/beach_day.parquet \
    --out ../data/curated/beach_day.parquet

# Stage B — force full re-normalisation first (needs ~15 GB RSS; the chunked
# CSV pass alone ran ~3 min, the live fetch adds several more)
CURATED_DIR=/tmp/stageB .venv/bin/python -m app.data.pipeline.cli \
    --normalize-beachwatch --full-rebuild \
    --stations-csv ... --results-csv ... --advisories-csv ... \
    --merge-ceden --max-ceden-rows 50000 \
    --with-beachwatch-live --beachwatch-live-days 30 --with-county-direct
```

---

## 1. The deliverable: `--full-rebuild`

`cli.py` gained an opt-in flag plus two extracted, testable helpers.

```
build_arg_parser()                          # the parser, so a test can parse the daily argv
use_incremental_beachwatch_normalization()  # the branch predicate, in one place
normalize_beachwatch_results_full()         # chunked whole-history normalisation
preserve_prior_additive_observations()      # see § 1.2 — this one is load-bearing
```

The branch predicate is unchanged except for the new term:

```python
observations_exists and stations_exists and not args.start_date and not args.full_rebuild
```

**The daily workflow passes neither `--start-date` nor `--full-rebuild`, so it
still takes the incremental branch.** `tests/test_full_rebuild_flag.py` parses
the *actual* argv out of `.github/workflows/daily-forecast.yml` (rather than
restating it) and asserts the predicate returns `True`, and separately asserts
the YAML contains no `--full-rebuild`. No workflow YAML was touched.

### 1.1 Why the flag and not the existing `--start-date`

`--start-date` already forces the full branch — and then calls
`load_beachwatch_csv`, a single `pd.read_csv(dtype=str)` over a **1.67 GB /
2,317,268-row × 93-column** CSV. That materialises ~220M Python strings.
`normalize_beachwatch_results_full` reads it in 200k-row chunks and normalises
each, because `normalize_bacteria_results` is strictly row-wise; the normalised
output is ~723k × 21. Four `chunksize` values are tested against the whole-frame
result with `assert_frame_equal`.

⚠️ **Peak RSS observed during the Stage B run was ~15 GB** (sampled: 1.2 GB →
5.9 GB during the chunked read → 15.2 GB in the post-normalisation stage). This
does **not** fit a 16 GB CI runner, which is a second reason the flag is a
local one-off. Lower `chunksize` if you need to.

### 1.2 The flag's first version was destructive. This is the important part.

A naive full rebuild — re-derive everything from the sources, keep nothing —
**loses the newest five months of data**, and it does so silently.

`data.ca.gov`'s results resource is frozen at sample date **2026-03-05**
(`last_modified` 2026-03-12, confirmed via the CKAN `resource_show` API).
Everything after that reaches `observations.parquet` only through the additive
sources, which the daily job accumulates one run at a time:
`--with-beachwatch-live` (a rolling 30-day *entered* window), the CEDEN /
SafeToSwim slice, and the county-direct scrape. One run's fetch windows cannot
reconstruct five months of accumulation.

Measured, first attempt, beach-days after 2026-03-05:

| | on disk | naive rebuild |
|---|---|---|
| beach-days > 2026-03-05 | **12,768** | **3,114** |
| 2026-03 / 04 / 05 / 06 / 07 rows | 1,936 / 2,833 / 2,623 / 2,977 / 2,677 | 304 / 305 / 70 / 86 / 2,062 |

**9,654 beach-days lost**, concentrated in exactly the window that feeds serving
and the tail of every training window. April–June fell by 89–97%.

`preserve_prior_additive_observations` fixes it: under `--full-rebuild`, rows
whose `data_source != "BeachWatch"` are folded back through the existing
additive gap-fill merge (`merge_live_into_observations`), so a rebuilt state row
always outranks a preserved row for the same physical sample. Prior *BeachWatch*
rows are **not** preserved — otherwise the flag could never remove anything,
and the 280 negative sentinels in § 4.2 would survive.

Preserved rows have `exceeds_stv` recomputed under today's rule, so preservation
cannot smuggle a stale label definition past the very rebuild that exists to
remove one. (Measured: **0 of 503,766** stored rows currently disagree with
`compute_exceeds_stv`, so this is a no-op today. It is there to keep it one.)

With preservation, Stage B keeps all 27,543 additive rows and loses **zero**
recent beach-days.

### 1.3 Tests

`tests/test_full_rebuild_flag.py` — **18 tests**: the daily-argv branch
assertion, the YAML assertion, `--full-rebuild` / `--start-date` /
missing-artifact branch selection, chunk-equivalence at four chunk sizes, the
PCR-threshold and negative-sentinel guards surviving the chunked path,
`observations_normalized` short-circuiting the CSV read (proved by passing a
path that does not exist), and five preservation tests — additive rows kept,
prior BeachWatch rows *not* resurrected, stale `exceeds_stv` corrected, mirror
collapse favouring the state row, and the no-prior-data no-op.

Full backend suite: **604 passed** (586 before + 18). `ruff check .` clean.

---

## 2. Method: why the two stages were run through a driver, not the CLI

Step 3 § 8 established that replaying the day-collapse over the *existing*
`observations.parquet` reproduces the shipped `beach_day` exactly, so all
expected label movement comes from re-normalising the source. Running both at
once confounds them. Hence two stages.

But ~9 of the 83 columns (`wave_height_m`, `salinity_psu`,
`water_temperature_c`, the CDIP/ERDDAP assignments) come from live network
fetches whose values move every run. Running
`cli.py --with-external-covariates` for Stage A would have put that movement in
the same diff as the relabel. So `scripts/rebuild_beach_day.py`:

- rebuilds the label half via `build_beach_day_frame`;
- **re-derives** every covariate block that is a deterministic function of an
  on-disk artifact — hydrology/precip (`build_beach_hydrology_daily`),
  solar-wind + marine microbiology (`explode_solar_wind_to_beaches` →
  `build_marine_microbiology_daily`, `compute_beach_coastal_features`),
  stormwater + rain policy (`apply_stormwater_features`) — using the same
  functions `cli.py` calls, so rows the rebuild *adds* get real feature values
  rather than nulls;
- re-attaches only the 9 network-derived columns verbatim on
  `(beach_id, sample_date)`.

**The re-derivation was validated before it was trusted.** Run in Stage A mode
against the pre-step frame, every re-derived column reproduced the shipped
values on all 492,543 rows to within 1e-9. (`dist_to_pier_km` /
`dist_to_estuary_km` flagged 9,876 / 12,254 rows under exact `==`; every one of
those deltas is ≤ 1e-9, i.e. float representation noise. Zero rows differ above
that tolerance.) Both stages then ran through identical code, which is what
makes the A→B diff attributable.

`data/curated/advisories.parquet` was deliberately not rewritten — it is the
post-county-scrape file, and the pipeline builds `beach_day` from the state CSV
(see § 3.2).

---

## 3. Stage A — rebuild from the existing `observations.parquet`

`diff_curated.py --before step4-pre --after step4-postA`:

```
-- beach_day.parquet ---------------------------------------------------------
   rows: 492,543 -> 492,543  (+0)
   schema: 83 -> 87 columns
     + added   (4): label_method, label_units, is_pcr, assay_disagreement
   keys: identical (492,543 on beach_id+sample_date)
   labels: no exceeds_stv flips (492,543 shared rows, base rate 0.1036)
   values: enterococcus_value unchanged
   coverage: 4 column(s) moved — the four new columns, all 100.00%
-- observations / beaches / forecast_history / forecasts: identical
-- json artifacts: identical
```

**Exit criterion met: assay columns only, zero label movement, zero value
movement.** Step 3's replay prediction reproduces exactly.

### 3.1 What the shipped frame now carries

| | value |
|---|---|
| rows | 492,543 |
| **`label_method` non-null** | **492,543 / 492,543 = 100.0%**, 27 distinct values |
| `is_pcr` true | 18,781 (3.81%) |
| `assay_disagreement` true | 581 |
| base rate | 0.1036 (unchanged) |
| 1095d window | 89,071 rows, PCR 13,744 (15.43%) |
| weather features, 2020+ | 99.99% on all 7 (unchanged — see § 6) |

### 3.2 One column moved that the harness does not report: `advisory_active_prev_14d`

`diff_curated.py` reports schema, keys, `exceeds_stv`, `enterococcus_value` and
per-column *coverage*. **Coverage is a `notna()` fraction, not a per-cell
equality check** — a column can change value on every row and still read
"unchanged". A cell-wise comparison was run separately and found exactly one
column moved:

| column | rows changed | direction | beaches | date range |
|---|---|---|---|---|
| `advisory_active_prev_14d` | **187** (0.038%) | 107 `0→1`, 80 `1→0` | 23 | 2015-09-24 → 2026-08-03 |

**Cause: the advisories feed's own churn, not the relabel.**
`_advisory_temporal_features` is a pure function of (beach_day keys,
advisories); the observations were byte-identical between the two sides, so the
advisories input is the only thing that could have moved. Corroborated two ways:

- The shipped `historical_advisory_count` reproduces the freshly-downloaded
  state CSV's per-beach counts for **all 842 beaches** (0 differ), so no
  advisory records were added or removed — only `DateOpened` was backfilled onto
  existing rows. That flips `fill_open_ended_advisory_end`'s `start + 14d` cap
  to a real end date, which moves the 14-day window test in **both** directions,
  matching the 107/80 split.
- Building against `data/curated/advisories.parquet` instead moved
  `historical_advisory_count` on 26,771 rows / 26 beaches. That file is the
  **post-county-scrape** rewrite (35,090 rows, 220 active) and is not what the
  pipeline builds `beach_day` from (35,072 rows, 202 active from the state CSV).
  The driver uses the state CSV, as the pipeline does.

`advisory_active_prev_14d` is a model feature; 187 of 492,543 rows is 0.04%.

---

## 4. Stage B — full re-normalisation

`diff_curated.py --before step4-postA --after step4-postB`, with the cell-wise
comparison folded in.

```
rows: 492,543 -> 732,535  (+239,992)
keys: 278 only-before, 240,270 only-after, 492,265 shared
labels: 342 exceeds_stv flips of 492,265 shared rows
  0->1  342     1->0  0     ->null 0     null-> 0
  base rate 0.1037 -> 0.1044
values: enterococcus_value changed on 821 rows (0.17% of shared)
  up 821   down 0
  delta  min 1  p05 3  med 65  p95 1.01e+04  max 1.44e+06
```

### 4.1 Cause attribution — **zero unattributed rows**

| cause | observation rows | beach-days | `exceeds_stv` flips | value changes |
|---|---|---|---|---|
| **state export republished with deeper pre-2011 history** | **+247,327** | **+240,270** | **342, all `0→1`** | **821, all up** |
| **negative-sentinel guard** (`value < 0 → NaN → dropna`) | **−280** | **−278** (0 positives) | 0 | 0 |
| **cross-source mirror collapse** (no data lost) | −2,333 | 0 | 0 | 0 |
| PCR threshold (1413 vs 104) | 0 | 0 | 0 | 0 |
| county corrections | 0 | 0 | 0 | 0 |
| spelling normalisation | 0 | 0 | 0 | 0 |
| CEDEN negative guard | 0 | 0 | 0 | 0 |
| **unattributed** | **0** | **0** | **0** | **0** |

Each line, measured:

**(a) The export republication.** The shipped `observations.parquet` holds
**21.5%** of the pre-2011 BeachWatch rows the current export carries (65,801 of
305,680) and **98.3%** of 2011+ (410,422 of 417,571). Growth by year: 2000–2010
each **+17k to +25k** rows (3–5×); 2011–2026 each **+67 to +1,422** (≤0.6%).
The 74 stations that appear only in the recovered history account for 17,745 of
the added rows; the other 229,563 are at beaches already in the frame.

Retention is wildly uneven by county (Humboldt 100%, Mendocino 94%, San Diego
78%, Orange 10%, Ventura 0.6%, San Francisco 0.0%), which is **not** a
truncation signature — a `--max-results-rows` prefix cap was tested at
400k/450k/475k/500k/525k/550k/600k/700k/800k/1M and none reproduces the
on-disk year distribution (best absolute year error 134,707 rows, and every
prefix also pulls in pre-2000 rows the frame has none of). Nor is it a per-beach
date-range cut. The resource was **created 2025-10-30 and last modified
2026-03-12**, so the most likely explanation is that the export itself gained
history after this repo's last full normalisation. ⚠️ **Which historical run
created the gap could not be determined.** What *is* certain is why it survived:
the incremental branch only ever adds rows newer than `max(sample_time) − 7d`,
so history missing at the time of the last full normalisation can never be
recovered by a daily run. **The trap does not merely freeze the label
definition — it freezes the row set.**

**(b) The flips are mechanically explained, all 342 of them.** Every flipped
beach-day (i) has more samples that day in the new frame than the old, **and**
(ii) contains an exceeding sample the old frame did not: **342 of 342 on both
tests**. Direction is **100% `0→1`**, which is the only direction a
worst-sample rule can move when samples are added — a strong internal
consistency check. Same for values: **821 of 821 increases, 0 decreases**.
Examples: Doheny S-1 2000-11-13, winner `1600`@10 → `Enterolert`@313;
Newport Slough BNS01 2021-05-19, `EPA 1600`@9 → `1600`@600.

By county: San Diego 318, Orange 22, Los Angeles 1, Marin 1. By assay: 341
culture, 1 PCR. By year: 325 of 342 fall in 2000–2007.

**(c) The negative-sentinel guard.** 280 `BeachWatch` rows carry −99 (274),
−88 (3), −1 (2), −999.99 (1), dated 2000–2022, 187 of them Los Angeles. Today's
`normalize_bacteria_results` nulls negatives and drops them; these predate the
guard and the incremental path never re-touched them. They removed 278
beach-days, **0 of which were positive**.

**(d) The 2,333 "dropped" additive rows are not losses.** Every one of them
(651 `BeachWatch.Live`, 1,682 `BeachWatch.SafeToSwim`) has its
`(beach_id, sample_date, value)` present in the new frame — **2,333 of 2,333**.
They are the same physical samples, collapsed in favour of the state row now
that the export carries them (the `"1600"` vs `"EPA 1600"` mirror case).

**(e) Three named candidate causes measured at exactly zero.** The stored
`exceeds_stv` in `observations.parquet` is **100% consistent** with today's
`compute_exceeds_stv` (0 of 503,766 disagree), so the PCR-threshold correction
has nothing left to fix — a prior full re-normalisation already applied it
(`observations.parquet.bak-pre-pcr-threshold`). Re-applying `correct_county`,
and `correct_place_spelling` to `station_name` / `beach_name`, changes **0**
rows each. The CEDEN negative guard fires on 0 rows.

### 4.2 Second-order movement Stage B causes, which is why it is held

| column | rows changed | mechanism |
|---|---|---|
| `shore_normal_wind_ms` | **36,906** (139 beaches) | roster 850 → 924 beaches changes the 5-nearest-neighbour set that `compute_beach_shore_azimuth` runs SVD over, so the coastline tangent moves. Mean Δ −0.13 m/s, range −13.0 to +14.8. **The other 6 solar/wind features changed on 0 rows**, confirming azimuth is the only channel. |
| `support_status` | **2,099** (24 beaches; 2,007 San Diego) | `support_status_for(count, span)` recomputed from the fuller history: `production→beta` 1,812, `production→unsupported` 172, `unsupported→production` 79, `beta→production` 34. Note the incremental branch **never** recomputes this — today's values are frozen at the last full normalisation. Same trap, third instance. |
| `label_method` | 1,642 | 1,483 are `EPA 1600 → 1600` — the same assay under the state export's spelling, **label-neutral**. The other 159 are genuine winner changes from added samples. |
| 9 `stormwater_*_count_*` | dtype `int64 → float64` | the 74 recovered beaches have no stormwater features, so the merge introduces NaN before `fillna(0)`. |

Full-frame feature coverage falls (`water_temperature_c` 84.5% → 56.8%,
precip/solar block 39.0% → 26.3%) purely because 240k pre-2011 rows enter a
frame whose covariate sources start in 2020. **Coverage on 2020+ is unchanged
at 99.99%** (§ 6).

### 4.3 Stage B does not move the training window

| | Stage A | Stage B |
|---|---|---|
| 1095d window rows | 89,071 | 89,139 (**+68, +0.08%**) |
| beaches | 671 | 671 |
| base rate | 0.1762 | 0.1761 |
| PCR share | 0.1543 | 0.1542 |

The entire +49% lands outside every current training window. Stage B is a
**history** change, not a model change.

---

## 5. The daily incremental path after the rebuild

The daily invocation was replayed against a copy of the shipped state
(`--normalize-beachwatch --merge-ceden --max-ceden-rows 50000
--with-beachwatch-live --beachwatch-live-days 30 --with-county-direct`, no
`--full-rebuild`, same three CSVs).

```
[beachwatch] incremental results fetch from 2026-07-29 (existing obs max - 7d)
[beachwatch] 0 new result rows to normalize
...
{"stations": 850, "observations": 502831, "advisories": 35072, "beach_day": 492611}
```

- Took the **incremental** branch. ✅
- `beach_day` carries all four assay columns, **0 null `label_method` of
  492,611**. ✅ No mixed vintage is possible in the *columns*: the daily run
  rebuilds `beach_day` from scratch via `build_beach_day_frame` (both
  `--merge-ceden` and `--with-beachwatch-live` do so), so every row is built by
  today's code every day.
- Added 68 new beach-days (2026-07-20 → 2026-08-05, San Diego 49 / LA 18 /
  SF 1), all with non-null `label_method`. ✅
- `is_pcr` identical on all 492,543 shared rows. ✅

### 5.1 ⚠️ But the replay surfaced a pre-existing defect in that same path

Holding the source CSVs fixed and running the daily job **once**:

| | before | after |
|---|---|---|
| `observations.parquet` rows | 503,766 | **502,831** (−935: 1,009 lost, 74 gained) |
| `beach_day` `exceeds_stv` flips | — | **51, all `1→0`** |
| `beach_day` `enterococcus_value` changes | — | **543, 542 down, 0 up** |

**Every flip is in the false-negative direction, and it happens on an ordinary
daily run.** Cause: the incremental branch's

```python
_merged.drop_duplicates(subset=["beach_id", "sample_time"], keep="last")
```

keys on `(beach_id, sample_time)` only. The additive merges key on
`(beach_id, sample_time, analyte, method, units, value)` — deliberately, because
"two genuinely different assays on one sample are two observations". So every
daily run destroys the same-timestamp rows the additive sources are careful to
keep. All **1,009** lost rows share a `(beach_id, sample_time)` with another row
(1,009 of 1,009); all are `*.SafeToSwim`; **120 of them exceeded**; they span
2020–2026 evenly.

This is the same bug class as the one `CLAUDE.md` records for the day-collapse
(".tail(1) flipped 1,021 contaminated beach-days to safe, 100% in the
false-negative direction"). The fix landed in `build_beach_day_frame`; the
observations dedupe one layer up was never fixed.

It is **pre-existing and unrelated to this step** — the replay ran the unmodified
incremental branch against the untouched shipped `observations.parquet`, and
Stage A has zero flips against the pre-step frame, so the 51 flips are equally
51 flips against `step4-pre`. It is **not** fixed here (the brief forbids
changing the collapse rule, and this is a source-merge change that deserves its
own diff). `--full-rebuild` does not have the defect: the full path never
applies that dedupe.

**Recommended for Step 5**, alongside the `curation.py` / `serving_repository.py`
threshold cleanup already scoped there.

---

## 6. Step 2's weather backfill survived

| feature (2020+, 192,052 rows) | pre | Stage A | Stage B (192,412 rows) |
|---|---|---|---|
| `shore_normal_wind_ms` | 99.99% | 99.99% | 99.99% |
| `solar_inactivation_index` | 99.99% | 99.99% | 99.99% |
| `cloud_cover_24h_mean` | 99.99% | 99.99% | 99.99% |
| `shortwave_24h_sum` | 99.99% | 99.99% | 99.99% |
| `uv_index_24h_max` | 99.99% | 99.99% | 99.99% |
| `wind_speed_24h_max` | 99.99% | 99.99% | 99.99% |
| `days_since_sunny` | 99.99% | 99.99% | 99.99% |

No regression. The rebuild re-derives these from
`data/curated/solar_wind_daily.parquet` (Step 2's output) rather than lifting
them, so even Stage B's added 2020+ rows are covered.

---

## 7. Recorded for Steps 5 and 7 (not acted on here)

**(a) `enterococcus_value` holds copies in an otherwise-MPN column on 18,781
rows (3.81% of the frame; 13,744 = 15.43% of the 1095d window).** Two channels
put them there. The larger is simply that a PCR-only beach-day's value *is* a
copies count. The subtler one is Step 3's finding: on the **591** mixed-assay
beach-days where the two assays *agree*, the collapse's value tiebreak compares
copies against MPN and hands the row to ddPCR **590** times — a units artefact,
not the "worst sample". Deliberately unchanged here; changing the collapse rule
in the same pass would have confounded the relabel. Full mixed-day picture on
the shipped frame: 1,172 mixed beach-days, **1,164 (99.32%) won by PCR**; 581
disagreed (all flagged by `assay_disagreement`), 591 agreed.

**(b) Three Mendocino `Enterolert` rows carry `Copies/100ml` units** and are
therefore judged against 1413 rather than 104 — Hare Creek 2025-10-28 (20),
Caspar Headlands SB 2024-10-08 (10), Pudding Creek Beach 2025-05-20 (10). All
below both thresholds, so no label moves. **As of this step "PCR exists in 2
counties" is now true in the shipped frame**, which will contaminate a naive
per-regime stratification in Step 7. Fix belongs in `pipeline/` as a source
correction alongside `county_corrections.py` — **do not** narrow
`is_pcr_measurement`, which would change `compute_exceeds_stv` for real San
Diego rows.

**(c) One `ddPCR` row is dated 2002-09-13** (San Diego, 375 copies, below the
BAV). `min(sample_date | is_pcr)` therefore reads **2002-09-13**; the
**second**-earliest is **2022-05-05**, which matches the documented "in use
since May 5, 2022" exactly. Use 2022-05-05 as the PCR-era boundary.

---

## 8. What this changes for Steps 5–10

1. **Stage B is a decision for the next review, not a fait accompli.** It is
   fully attributed with zero unattributed rows, every label flip is `0→1` and
   mechanically explained, and no data is lost. But it is a **+49% history
   expansion driven by an upstream republication**, and shipping it drags in
   three things outside Step 4's scope: a `beaches.parquet` that grows 850 → 924
   (the 74 new beaches carry no CDIP / ERDDAP / surf enrichment, so `beach_day`
   would reference beaches the serving roster does not know), a
   `shore_normal_wind_ms` change on 36,906 *existing* rows caused purely by the
   roster growth, and a `support_status` change on 24 beaches. Each deserves its
   own diff. Recommendation: **take Stage B as its own step between 5 and 6**,
   run with `--with-external-covariates` so the new beaches get enriched in the
   same pass, and re-check the § 4.2 table afterwards.
2. **Step 5 gains a second, higher-priority work item**: the incremental dedupe
   key (§ 5.1). It silently deletes ~1,000 same-timestamp observations per daily
   run, 120 of them exceedances, flipping 51 beach-days `1→0` — the direction
   the label rule is explicitly designed to prevent. This is a live defect
   affecting the shipped frame every day, unlike the `curation.py` fixture path
   already scoped there.
3. **Step 6 must re-derive `shore_normal_wind_ms`, not inherit it**, if the
   roster ever changes. The feature is a function of which *other* beaches are
   in the frame — 74 additions moved it on 139 beaches. Any held-out-beach
   ablation that adds or removes beaches perturbs this feature for the beaches
   that remain, which is a leakage-shaped hazard worth pinning before the plume
   feature lands.
4. **Step 7's assay stratification is now a one-line `groupby`** — `is_pcr` and
   `label_method` are columns on 100% of rows. And the stratification must
   exclude, or specially handle, the three Mendocino rows in § 7b, or "PCR
   regime" silently means "San Diego + 3 Mendocino rows".
5. **`diff_curated.py` needs a per-cell equality mode.** Its "coverage:
   unchanged on every column" line means `notna()` fractions match, not values.
   Stage A's 187-row `advisory_active_prev_14d` movement was invisible to it and
   had to be found with a separate cell-wise pass. Every remaining step relies
   on this harness to tell a fix from a regression; it currently cannot see a
   value-only change in any column other than `exceeds_stv` and
   `enterococcus_value`.
6. **`support_status` is frozen**, like the row set was. The incremental branch
   reads `beaches.parquet` as-is and never re-runs `support_status_for`, so the
   station-quality cap reflects whenever the last full normalisation ran. 24
   beaches would move today. It gates training-row inclusion
   (`support_status != "unsupported"`), so it is a silent training-population
   drift.
