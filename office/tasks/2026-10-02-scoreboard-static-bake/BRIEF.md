---
task: scoreboard-static-bake
repo: /Users/kylechoi/surf_health-p3
worker: claude
created: 2026-10-02
status: done
---

## Goal

UPDATE_PLAN steps 3.1 (live scoreboard) and 3.2 (bake everything the mobile app reads into
static files), backend side. Work on a branch cut from `main` AFTER the Phase-1 PR is merged
(the PM creates it; work in this repo's checkout on that branch). The static file shapes are
fixed by `docs/STATIC_DATA_CONTRACT.md` — read it first. The mobile reader is being built
against that contract in parallel.

## In scope

**3.1 scoreboard** (`backend/app/ml/served_metrics.py`, `backend/app/ml/lookup_serving.py`):
1. Move `within_beach_auroc` and `cluster_bootstrap_delta` (the versions in
   `backend/scripts/compare_all_models.py`, which include the within-beach delta) into a new
   module `backend/app/ml/scoreboard_stats.py`; make `compare_all_models.py` import them from
   there (no behaviour change — its tests must still pass).
2. `_score` adds `within_beach_auroc` (beaches with both outcomes only).
3. `lookup_serving` writes `p_exceed_persistence` into `forecasts.parquet`: 1.0 if the beach's
   last label exceeded, else the statewide pooled rate of labels in the 365 d before the
   forecast date (same definition as the `persistence` arm of `compare_all_models.py`). Add it
   to `served_metrics._HISTORY_COLUMNS` and to the `compare_columns` passed at
   `lookup_serving.py:~663` (`("p_exceed_lookup", "p_exceed_ml", "p_exceed_persistence")`).
4. Each `head_to_head` challenger entry gains `ci`: the beach-cluster bootstrap 95% CI of
   (challenger − served) for within-beach AUROC, AUROC and Brier, 300 replicates, fixed seed.
5. `reportable` (both the outcome block and `head_to_head`) additionally requires
   `served_days >= 28`, matching `backend/app/ml/PROMOTION.md`.

**3.2 static bake** (`backend/scripts/bake_web_static.py`, pipeline):
6. New pipeline step `--with-tides` in `backend/app/data/pipeline/cli.py`: for every NOAA
   station `backend/app/services/tides.py` maps a beach to, call its existing fetch once per
   station and write `data/curated/tides.parquet` (station id, timestamp, height, plus the
   high/low extrema the route returns, covering ≥ 72 h from the run). Reuse `tides.py`
   functions; do not reimplement the NOAA call. Add `--with-tides` to the "Run data
   pipeline" step of `.github/workflows/daily-forecast.yml`.
7. `bake_web_static.py --with-details` writes, next to the existing files:
   - `health.json` = the `SystemHealthResponse` payload (trim large research sections if the
     model allows; must validate),
   - `beach/{beach_id}.json` per the contract for every beach in `beaches.json`:
     `observations` (newest 52 samples, newest first, from `observations.parquet`), `explain`
     (summary + used_model the way `BeachService.explain_forecast` builds them, re-derived from
     `forecasts.parquet` columns such as `top_drivers`; the baker must NOT import the `app`
     package — it is curl'd standalone by shorelife-web's deploy — so port the small amount of
     logic and pin it with a parity test), `hourly` (from `hourly_forecast.parquet` the way
     `app/services/hourly_store.get_precomputed_hourly` reads it, else null), `tides` (from
     `tides.parquet` for the beach's nearest station, else null).
   The baker keeps working with no flag exactly as today.
8. Parity tests (`backend/tests/test_static_bake_parity.py`): bake a small fixture curated dir;
   validate `beaches.json` rows against `BeachSummary` (+ `ForecastRecord` for `.forecast`),
   `parent_beaches.json` against `ParentBeachSummary`, `health.json` against
   `SystemHealthResponse`, and every `beach/*.json` section against the API response model or
   the route's payload; and assert the `explain` summary equals what `BeachService` returns for
   the same fixture.

## Out of scope

- shorelife-web changes (its deploy must pass `--with-details`; the web research-page table of
  3.1 step 5) and `scripts/validate-bake.mjs` — separate task in that repo.
- Mobile (separate task). Render, CI split, standalone serving (later tasks).
- Changing what is served (p_exceed values, bands, floors).

## Allowed files

- backend/app/ml/scoreboard_stats.py
- backend/app/ml/served_metrics.py
- backend/app/ml/lookup_serving.py
- backend/scripts/compare_all_models.py (import change only)
- backend/scripts/bake_web_static.py
- backend/app/data/pipeline/cli.py
- backend/app/services/tides.py (only if a small refactor is needed to reuse it)
- .github/workflows/daily-forecast.yml (add `--with-tides` only)
- backend/tests/**

## Allowed packages

- none

## Acceptance

```bash
cd backend
.venv/bin/pytest -q                                  # no new failures
.venv/bin/ruff check app tests scripts               # clean
.venv/bin/python -m app.data.pipeline.cli --with-tides   # writes ../data/curated/tides.parquet (network)
.venv/bin/python scripts/bake_web_static.py --curated ../data/curated --out /tmp/bake --with-details
ls /tmp/bake/beach | wc -l                           # == number of beaches in /tmp/bake/beaches.json
.venv/bin/pytest -q tests/test_static_bake_parity.py # all pass
.venv/bin/python -m app.ml.lookup_serving --curated ../data/curated/   # system_health.json serving_method.live.forward_1_3d.head_to_head has within_beach_auroc and ci per challenger
```

## Phases

### Phase 25
Deliverable: `scoreboard_stats.py`, `_score` within-beach AUROC, `p_exceed_persistence` written + logged + compared, CIs, 28-day reportable rule, tests.

### Phase 50
Deliverable: `--with-tides` pipeline step writing `tides.parquet` + workflow flag, tested offline with a fake NOAA response.

### Phase 75
Deliverable: `bake_web_static.py --with-details` writing `health.json` and `beach/{id}.json` per the contract.

### Phase 100
Deliverable: parity tests and all Acceptance commands pass with output pasted.

## Corrections

(appended by the PM; newest last; each entry dated)

### 2026-10-02 23:10 — before phase 25 (PM)

Repo is the worktree `/Users/kylechoi/surf_health-p3`, branch `feat/update-plan-phase3-static`
(cut from `main` after PRs #45 and #46). `data/raw` there is a symlink — never commit it; do not
modify `data/curated` there (use /tmp copies; a full fixture is
`/Users/kylechoi/surf_health/data/snapshots/after-2026-10-02`). `lookup_serving.py` now also has
the standalone path from PR #46 — keep it working (its tests must stay green).

### 2026-10-02 23:45 — after phase 75 (PM) — read docs/STATIC_DATA_CONTRACT.md again (amended)

1. **API-shaped files live under `api/`.** You were right: the existing top-level
   `beaches.json` / `parent_beaches.json` are the web's flat shapes. Leave them exactly as they
   are. With `--with-details`, write instead:
   - `api/parent_beaches.json` — `ParentBeachSummary[]` exactly as `GET /parent-beaches` returns,
   - `api/beaches.json` — `BeachSummary[]` exactly as `GET /beaches` returns, each with an extra
     `forecast` key = the `ForecastRecord` `GET /beaches/{id}/forecast?date=<bake forecast_date>`
     returns (including the serve-time confidence cap you noted; port it), or `null`,
   - `api/health.json` (move `health.json` here),
   - `api/beach/{id}.json` (move `beach/` here), one per `api/beaches.json` row.
   The mobile reader (already updated) reads only `api/*`.
2. **Station list:** the vendored `_CA_TIDE_STATIONS` must equal `app.services.tides.CA_TIDE_STATIONS`
   (the PM removed 3 dead NOAA stations there in phase 50: 9410665, 9415118, 9413745). Sync it and
   pin equality in a test. Expect the null-tides count to drop from 66 to (near) the beaches
   with no coordinates.
3. **Parity tests (phase 100)** run the API's own code on the same fixture and compare: every
   `api/beaches.json` row (minus `forecast`) equals `BeachService.list_beaches()` output; each
   `forecast` equals `get_forecast(id, date)`; `api/parent_beaches.json` equals
   `list_parent_beaches()`; `api/health.json` validates as `SystemHealthResponse`; each
   `observations` equals `get_observations(id)` (or is null where the API 404s); `explain` equals
   `explain_forecast(id, date)`; vendored twins (`explain_summary`, `_derive_friendly_name`,
   `ADVISORY_AUTO_EXPIRE_DAYS`, the station list) equal their `app` originals. Build the
   `BeachService` against the fixture the way `app/api/deps` / the repository factory does.
4. Keep `hourly` per beach as is (31 MB is acceptable).
