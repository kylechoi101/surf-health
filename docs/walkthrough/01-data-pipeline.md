# 1 — The data pipeline (`backend/app/data/`)

Turns a dozen heterogeneous public feeds into one labelled, forecast-safe training
frame. ~6,000 lines across `connectors/` (fetch) and `pipeline/` (transform).

Entry point:

```bash
cd backend
.venv/bin/python -m app.data.pipeline.cli \
  --normalize-beachwatch --stations-csv … --results-csv … --advisories-csv … \
  --merge-ceden --max-ceden-rows 50000 \
  --with-beachwatch-live --beachwatch-live-days 30 --with-county-direct \
  --with-external-covariates --with-hydrology --with-solar-wind
```

---

## 1.1 `connectors/` — the fetch layer

### `base.py` — the contract

```python
@dataclass
class SourceContext:
    raw_dir: Path
    curated_dir: Path
    research_dir: Path

class SourceConnector(ABC):
    source_name: str
    @abstractmethod
    async def fetch(self, context: SourceContext) -> pd.DataFrame: ...
```

Textbook **Strategy pattern**: one async method, a context object instead of a long
parameter list, and `pd.DataFrame` as the universal return type so the pipeline never
has to know which source a row came from.

⚠️ Only `official_sources.py` actually implements it (`CaliforniaOpenDataConnector`,
`CedenFibConnector`, `JsonEndpointConnector`). **`hydrology_sources.py` defines eight
more connectors that do not inherit `SourceConnector` at all** and take explicit
arguments instead of a `SourceContext`. Two parallel conventions in one package —
see [Document 4](04-design-patterns-review.md#the-abandoned-abc).

### `hydrology_sources.py` — the cached-fetch pattern

Every connector here follows the same three-block shape:

```python
cache_file = cache_dir / f"{lat:.1f}_{lon:.1f}_{start}_{end}.parquet"
if cache_file.exists():                 # 1. cache hit → return
    return pd.read_parquet(cache_file)
df = _fetch_from_api(...)               # 2. miss → HTTP
_atomic_to_parquet(df, cache_file)      # 3. persist
```

Two details worth copying:

- **The cache key rounds coordinates to 0.1°.** ERA5-Land and Open-Meteo are gridded
  at roughly that resolution, so two beaches 5 km apart legitimately share a cell.
  This turns ~650 per-beach fetches into ~120 per-cell fetches.
- **`_atomic_to_parquet` writes `.tmp` then `os.replace`.** A crash mid-write used to
  leave a truncated parquet that later read back as garbage. `os.replace` is atomic
  on POSIX, so a reader sees either the old file or the new one, never a half file.

Connectors here: `UsgsNwisConnector` (streamflow), `CnrfcObservedPrecipConnector`,
`OpenMeteoHistoricalPrecipConnector`, `OpenMeteoHistoricalSolarWindConnector`
(ERA5-Land cloud/shortwave/UV/wind), `OpenMeteoMarineForecastConnector` (waves +
swell trains), `OpenMeteoMarineHistoricalConnector`, `CnrfcQpfConnector`,
`NhdPlusMetadataConnector`.

---

## 1.2 `pipeline/` — the transform layer

### `cli.py` — the orchestrator (1,090 lines)

A flag-driven procedural script, not a DAG framework. Each `--with-*` flag gates one
stage, and **the stage order is load-bearing**. The comment block in `CLAUDE.md` spells
out the single most fragile ordering constraint:

> `--with-county-direct` must run *inside* bundle construction, immediately after the
> live merge and **before** the precip/solar/marine joins — otherwise the newly merged
> rows land in `beach_day` with every covariate `NaN`.

`refresh_latest_official_sample_at` (line 255) deserves a callout. It recomputes the
"last sampled" timestamp the apps display *after* every late merge. It was previously
computed once during bundle construction, so rows added by `--with-beachwatch-live`
never updated it: **75 beaches carried a stamp behind their own observations**, Orange
County by up to 63 days. The UI showed beaches as two months stale while fresh rows sat
in the label frame. Fix: recompute at the end, unconditionally.

### `beachwatch.py` — normalization and labelling (667 lines)

The most important function in the pipeline is `build_beach_day_frame` (line 560),
which collapses multiple same-day samples into one training row:

```python
_ranked["_exceed_rank"] = _ranked["exceeds_stv"].fillna(False).astype(bool).astype(int)
_ranked["_value_rank"]  = pd.to_numeric(_ranked["value"], errors="coerce").fillna(-inf)
per_day = (_ranked
    .sort_values(["_exceed_rank", "_value_rank", "sample_time"])
    .groupby(["beach_id", "sample_date"], as_index=False)
    .tail(1))
```

Sort by (exceeded, value, time) and take the last → **the worst sample of the day wins.**
The previous rule took the chronologically last sample, which meant a morning exceedance
followed by a clean afternoon resample was labelled *safe*. That flipped 1,021
contaminated beach-days to negative — 100% in the false-negative direction, which is the
dangerous direction for a public-health product.

Sorting on three keys rather than one is also what keeps `enterococcus_value` and
`exceeds_stv` mutually consistent: whichever row wins carries *both* fields, so every
value-derived lag and geomean feature downstream describes the same physical sample as
the label.

Other blocks in this file:

| Function | Job |
|---|---|
| `is_marine_station` | Filters to saltwater/estuarine — freshwater sites use different indicators and thresholds |
| `derive_beach_id` | Slug-based stable primary key. **Never** regenerated from a display name, so spelling fixes can't orphan history |
| `derive_parent_beaches` | DBSCAN at ε = 3 km over station coordinates, sub-clustered when a group spans > 5 km. Gives the apps "Santa Monica State Beach" as one card over 6 stations |
| `normalize_bacteria_results` | Unit/method canonicalization; **drops negative values** (−999/−1000 "not analyzed" sentinels) |
| `fill_open_ended_advisory_end` | Caps advisories with no end date at 14 days so a forgotten posting doesn't warn forever |

### `exceedance.py` — the threshold that had to be method-aware

```python
is_pcr = method contains "pcr"  OR  units contain "copies"
threshold = 1413 if is_pcr else 104
```

San Diego reports ddPCR results in **copies/100 mL**, judged against 1413. The rest of
California reports culture MPN/CFU, judged against 104. A single flat 104 had
false-flagged ~98% of San Diego's PCR samples as exceedances. This is wired into both
the BeachWatch and CEDEN normalizers.

The knock-on effect shows up in `features.py`: because `beach_day` carries no
method/units column, and 84 beaches report *both* ways, **the raw
`enterococcus_value` is not comparable across rows of the same beach.** That is why the
persistence feature is `exceeds_stv_last_obs` (carry the already-decided label forward)
rather than re-thresholding the raw value.

### `features.py` — feature construction (735 lines)

`add_temporal_features` is the single entry point. It appends ~140 derived columns to
`beach_day` in nine blocks, all concatenated on the index at the end:

| Block | Columns | Notes |
|---|---|---|
| Seasonal | `day_of_year`, `sin_doy`, `cos_doy`, `log_enterococcus` | Cyclic encoding so Dec 31 and Jan 1 are adjacent |
| `_spatial_context_features` | neighbour density, Tijuana-plume zone flags | |
| Zone interactions | `tijuana_plume_onshore_flag`, `…_wind_interaction` | Domain physics: onshore wind compresses the nearshore plume |
| `_exact_lag_features` | `{col}_lag_{1,2,3,7,14}` | Date-shifted self-merge |
| `_rolling_and_spacing_features` | 7 d/30 d mean, std, trend; `days_since_*_obs`; `*_last_obs` | |
| `_distributed_lag_hydrology_features` | precip/streamflow decay windows | |
| `_regulatory_geomean_features` | 30 d/42 d rolling geometric means | Mirrors the actual regulatory statistic |
| `_sd_boundary_features` | San Diego border/lagoon flags + interactions | |
| Missing indicators | `{col}_missing` | Missingness is signal (a lab skipped a site for a reason) |

**Two leakage guards worth studying.**

*1. `closed="left"` on every rolling window.*

```python
mean_7d = time_series.rolling("7D", min_periods=1, closed="left").mean()
```

`closed="left"` excludes the right endpoint — i.e. *this row's own value* — from its own
rolling mean. Without it the 7-day mean of a sample would contain that sample, and the
model would be reading its own answer. Note also that the window is the **string
`"7D"`**, not the integer `7`: a time-based window over a `DatetimeIndex`, so a beach
sampled irregularly gets a true 7-calendar-day window rather than "the previous 7 rows,"
which for a monthly-sampled beach would span half a year.

*2. `shift(1).ffill()` on every last-observed value.*

```python
observed_dates = sample_date_series.where(col_values.notna()).shift(1).ffill()
feature_map[f"{column}_last_obs"] = col_values.shift(1).ffill()
feature_map["exceeds_stv_last_obs"] = exceedance.shift(1).ffill()
```

Shift first (drop the current row), *then* forward-fill (carry the most recent prior
observation). Doing it in the other order would leak the current value into its own
feature. This pair of lines is the model's entire "memory," and it is the reason the
model is skilful on sample-days and much weaker between them.

*3. The index-restoration bug that is now a comment.*

```python
# .merge() discards the caller's index for a fresh RangeIndex. add_temporal_features
# combines this block with `enriched` via pd.concat(axis=1), which aligns on index —
# so whenever `enriched` has a non-contiguous index (any .loc[mask] filter …) the two
# UNION instead of aligning and every *_lag_* column silently lands on the wrong row.
return feature_frame.drop(columns=["beach_id","sample_date"]).set_index(enriched.index)
```

This is the highest-value comment in the repo. `pd.concat(axis=1)` aligns on index, and
`merge` resets it — so a `.loc[mask]` filter anywhere upstream silently scrambled every
lag feature. `set_index(enriched.index)` restores alignment. If you add a feature block,
it must end with the same call.

### `marine_microbiology.py` — the domain-knowledge features

Eleven columns encoding published enterococcus-inactivation physics:

- `solar_inactivation_index`, `shortwave_24h_sum`, `uv_index_24h_max`,
  `cloud_cover_24h_mean`, `days_since_sunny` — UV is the dominant natural die-off
  mechanism for enterococcus in seawater.
- `shore_normal_wind_ms` — wind projected onto the beach's shore normal, so positive =
  onshore = plume compression toward the surf zone.
- `wind_speed_24h_max` — mixing/resuspension.
- `dist_to_pier_km`, `is_near_pier`, `dist_to_estuary_km`, `is_near_estuary_mouth` —
  point-source proximity, from 31 hand-curated piers and 27 estuary mouths in
  `_static_data/`.

`compute_beach_shore_azimuth` derives the coastline tangent by **SVD over the 5 nearest
neighbouring beaches**, then disambiguates which side is ocean by pointing the normal
away from an inland California centroid (37 °N, 120.5 °W). A neat trick: it needs no
coastline polygon, just the station roster.

These were computed but **silently dropped** by the training loader's column allowlist
until 2026-06-01. They are now selected, and leave-one-county-out validation confirmed
they help more spatially (+0.029 AUCPR) than temporally — unseen counties can't fall
back on a memorized base rate, so real physics matters more.

### `county_direct.py` — the fourth observations source

Merges `county_direct_samples.parquet` (scraped directly from county portals) into
`observations`. Three rules make it safe:

1. **The merge key is the sample DATE, not `sample_time`.** The state feed carries real
   collection times (`10:25:00`); the direct feed is date-only. Measured over the
   overlap window, all 206/206 state San Francisco rows matched a direct row on
   `(beach_id, date)` with an identical value — so a time-keyed merge would have
   inserted 206 duplicates.
2. **Value is deliberately out of the key**, so a revised result can't enter as a second
   beach-day.
3. **Gap-fill only.** A direct row whose `(beach_id, date, analyte)` any source already
   covers is dropped.

Motivation: San Francisco publishes to its own Socrata dataset within days but reports
to the State Water Board weeks late. On 2026-07-30 every state-routed source held zero
SF rows for July while the direct feed already had four weekly results — and the
advisory layer had *already published a posting* from those same samples.

### `schema_guard.py` — the write barrier

`validate_beach_day` runs immediately before the `beach_day.parquet` write:

- **HARD raise** on an empty frame or a missing primary key (`beach_id`,
  `sample_date`, `exceeds_stv`).
- **WARN only** on an absent or all-NaN feature column.

The asymmetry is the point. A connector outage legitimately yields an all-NaN column,
and failing the daily job for that would replace a slightly degraded forecast with no
forecast at all. A missing primary key means the frame is structurally wrong and
nothing downstream can be trusted.

### `serving_snapshot.py` — the read-model build

Denormalizes the curated parquets into `serving.sqlite`: beaches joined to their
latest forecast, advisories, parent groupings, and the health payload. This is a
**CQRS read model** — the write side is columnar parquet optimised for the training
scan, the read side is row-oriented sqlite optimised for "one beach by id."
