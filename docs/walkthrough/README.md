# Shorelife / Surf Health — code walkthrough

A block-by-block tour of the backend, written for someone who has never opened the
repo. Read in order; each document assumes the previous one.

| # | Document | What it covers |
|---|---|---|
| 0 | **This file** | System architecture, the daily lifecycle, where state lives |
| 1 | [`01-data-pipeline.md`](01-data-pipeline.md) | Ingest → normalize → label → feature-build. Every module in `app/data/` |
| 2 | [`02-ml-training.md`](02-ml-training.md) | Models, calibration, the two-tier router, the promotion gate. `app/ml/` |
| 3 | [`03-serving-and-api.md`](03-serving-and-api.md) | Repositories, schemas, FastAPI surface, staleness policy |
| 4 | [`04-design-patterns-review.md`](04-design-patterns-review.md) | **Does this follow established patterns? Does it use libraries the documented way?** |
| 5 | [`05-model-effectiveness.md`](05-model-effectiveness.md) | Per-county / per-beach accuracy, and how to reproduce it |

Companion visualization:
**[Model effectiveness by county and beach](https://claude.ai/code/artifact/eceb160a-a2c3-4d56-8698-d2a87621ce6a)**
— every table in Document 5 rendered as charts, with the data tables inline.

---

## What the system does

Predicts, for ~650 California marine beach sampling stations, the probability that
today's water will exceed the enterococcus single-sample action value. It publishes
one `p_exceed` + a risk band per station per day, plus official county advisories,
surf/tide/UV conditions, and a `/system/health` accountability endpoint.

The crucial framing, which the whole codebase is organised around:

> **Labs sample a beach roughly once a week. The product answers every day.**

So ~6 out of 7 published predictions can never be checked against a lab result, and
the model is asked a question (is *today* different from *yesterday* at this beach?)
that its training data barely contains. Nearly every unusual design decision in this
repo — the two-tier router, the served-metrics loop, the staleness augmentation, the
`within_beach_auroc` metric — exists because of that one sentence.

---

## Architecture

```
                            ┌─────────────────────────────────────────┐
  PUBLIC DATA SOURCES       │  GitHub Actions: daily-forecast.yml     │
  ───────────────────       │  cron 16:00 UTC · 170 min budget        │
  CA State Water Board      └──────────────────┬──────────────────────┘
    BeachWatch (Socrata)                       │
  CEDEN / SafeToSwim              ┌────────────▼─────────────┐
  County scrapers (12)            │ app/data/pipeline/cli.py │   ← Document 1
  data.sfgov.org                  │  the pipeline orchestrator│
  USGS NWIS (streamflow)          └────────────┬─────────────┘
  Open-Meteo (ERA5-Land,                       │  writes
    Marine, forecast)               ┌──────────▼──────────┐
  NOAA CO-OPS (tides)               │   data/curated/*.parquet
  EPA BEACON / WQP                  │   beach_day · observations · beaches
                                    │   precip_daily · solar_wind_daily …
                                    └──────────┬──────────┘
                                               │  reads
                                    ┌──────────▼────────────┐
                                    │  app/ml/training.py   │   ← Document 2
                                    │  train → backtest →   │
                                    │  gate → calibrate →   │
                                    │  route → export       │
                                    └──────────┬────────────┘
                                               │  writes
                        ┌──────────────────────▼──────────────────────┐
                        │ forecasts.parquet · hourly_forecast.parquet │
                        │ system_health.json · serving.sqlite         │
                        │ forecast_history.parquet (accountability log)│
                        └──────────────────────┬──────────────────────┘
                                               │  git commit → Docker build
                        ┌──────────────────────▼──────────────────────┐
                        │  FastAPI on Render   (app/main.py)          │   ← Document 3
                        │  ServingSnapshotRepository → sqlite         │
                        └───────┬─────────────────────┬───────────────┘
                                │                     │
                    web (Next.js, GitHub Pages)   mobile (Expo/RN)
```

### The one non-obvious deployment fact

**The API serves a snapshot baked into the Docker image.** `backend/Dockerfile` COPYs
`data/curated/` at build time. A fresh data commit changes nothing users see until a
Render *build* completes. This caused a silent 47-hour staleness incident on
2026-07-24, and is why both workflows now run `backend/scripts/verify_deploy.py`,
which polls the public health endpoint until the *served* `pipeline_freshness` is at
least as new as the commit that just landed.

---

## The daily lifecycle

One cron run does all of this in sequence. Every arrow is a hard dependency.

```
1  INGEST      cli.py --normalize-beachwatch --merge-ceden --with-beachwatch-live
               --with-county-direct --with-external-covariates --with-hydrology
               --with-solar-wind --with-surf
                 ↓ raw CSV/JSON → normalized observations
2  LABEL       build_beach_day_frame: collapse same-day samples to the WORST one,
               join station metadata + advisory history        → beach_day.parquet
                 ↓
3  FEATURES    add_temporal_features: ~190 columns — lags, rolling windows,
               regulatory geomeans, marine microbiology, SD boundary flags
                 ↓
4  TRAIN       training.py --curated --spatial-backtests --winner-only
               temporal split → candidates → spatial leave-one-out backtests
                 ↓
5  GATE        _promotion_assessment: must beat persistence on held-out county AND
               beach AUCPR + Brier, calibration slope ≥ 0.4, ≥1 usable fold
                 ↓ (fail ⇒ forecasts.parquet is NOT overwritten)
6  CALIBRATE   isotonic on the inner-validation split, then a SECOND isotonic refit
               on the trailing 120 d of served-vs-lab pairs (serving calibration)
                 ↓
7  ROUTE       _route_fresh_stale_probabilities: sample ≤3 d old → ensemble,
               ≥5 d → offset model, linear blend between
                 ↓
8  PUBLISH     forecasts.parquet (+ append to forecast_history.parquet)
                 ↓
9  SCORE       served_performance: yesterday's published forecasts vs the lab
               results that have since arrived      → system_health.json
                 ↓
10 VERIFY      validate_forecast.py (anomaly gate) → git commit → Render deploy
               → verify_deploy.py polls until the new snapshot is actually served
```

Steps 5, 9 and 10 are the parts most ML codebases don't have, and they are the reason
this repo's published numbers are trustworthy: it grades its own homework in public
and refuses to ship when it fails.

---

## Where state lives

| Artifact | Written by | Read by | Role |
|---|---|---|---|
| `beach_day.parquet` | pipeline step 2–3 | training | The labelled training frame, one row per beach-day |
| `observations.parquet` | pipeline step 1 | training, served scoring | Raw per-sample lab results — the ground truth |
| `beaches.parquet` | pipeline step 1 | everything | Station roster, coords, county, `latest_official_sample_at` |
| `forecasts.parquet` | training step 8 | serving snapshot | **What is published today** |
| `forecast_history.parquet` | `served_metrics.append_forecast_history` | served scoring, serving calibration | Append-only log of what was *actually served* |
| `holdout_predictions_{temporal,spatial}.parquet` | training | offline analysis | Per-row held-out (label, probability) — lets any operating point be recomputed without retraining |
| `system_health.json` | training + pipeline | `/system/health`, web `/research` | Every published metric |
| `serving.sqlite` | `pipeline/serving_snapshot.py` | the API | Denormalized read-optimised snapshot |
| `serving_calibration.json` | `served_metrics.fit_serving_calibration` | next day's export | The isotonic map from raw → served probability |

`data/curated/` is committed to git. That is deliberate: it makes every published
number reproducible from a commit SHA, and it is what let `backfill_forecast_history.py`
reconstruct 189 days of served history after the fact.
