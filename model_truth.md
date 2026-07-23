# Model Truth — California reliability audit (2026-07-23)

This document records the **methods and results of the reliability tests run on
2026-07-23** against the shipped California model. It is a point-in-time audit,
not a spec. Every number here is reproducible from the artifacts named in each
method block.

**Question asked:** *Is the model as reliable as it claims, for California only?*

**One-line answer:** The shipped headline metrics are **honestly reported** (they
reproduce exactly from disk) but they measure a **regime the product does not
operate in**. When scored against the way it is actually served — a daily
forecast on beaches whose last recorded sample is days old — real-world **AUCPR is
≈0.24–0.27 (vs. a claimed 0.63–0.70)** and its probabilities are **worse
calibrated than a flat base-rate constant**. Rank-ordering survives (AUROC
≈0.80–0.86); the probability *values* and the "Low risk" band do not.

## Provenance

| Item | Value |
| --- | --- |
| Repo commit at audit time | `0fb84cd` |
| Curated data snapshot (daily run) | `2026-07-22T18:12Z` |
| Observations (ground truth) available through | `2026-07-18` |
| Forecast history reconstructed from git | 189 daily commits, `2026-04-23 → 2026-07-22` |
| Scope | California only (15 CA counties in the training frame; no out-of-state data) |

Environment note: `pandas`/`scikit-learn` were used for independent recompute;
`xgboost`/`torch`/`pydantic` were installed to run the on-disk diagnostic. The
production classifier is `xgb_undersample_ensemble`; the on-disk censoring
diagnostic (Test 5) uses `hist_gbm` (the script default and a same-family
proxy). Test 4 scores the **actual production `p_exceed`** that was served, so it
reflects the real deployed model.

---

## Test 1 — Are the shipped numbers real? (independent recompute)

**Method.** Recompute AUCPR, Brier, and sensitivity@specificity=0.87 directly
from the persisted per-row holdout predictions
(`data/curated/holdout_predictions_{temporal,spatial}.parquet`) and compare to
`data/curated/system_health.json` (`model_registry`).

**Result — matches the self-report to 3 decimals.** The pipeline is not lying
about its own arithmetic.

| Split (holds out…) | AUCPR | Brier | sens@spec0.87 | persistence AUCPR |
| --- | --- | --- | --- | --- |
| Temporal (future dates, same beaches) | 0.698 | 0.072 | 0.735 | — |
| Spatial **county** (new county) | 0.634 | 0.112 | 0.704 | 0.437 |
| Spatial **beach** (new beach) | 0.953 | 0.103 | 0.842 | 0.789 |

**Caveat surfaced.** The county number carries a 95% cluster-bootstrap CI of
**[0.331, 0.697]** over only 6 folds — the lower bound sits *below* the county
persistence baseline (0.437). The point estimate beats persistence; the
confidence does not.

**Verdict:** claims are honestly reported. This test only rules out reporting
bugs — it says nothing about real-world performance (Tests 2–5).

---

## Test 2 — Does the spatial holdout mimic deployment? (design audit)

**Method.** Read the fold logic (`app/ml/training.py::_spatial_holdout_fold_result`):
`test = held-out county, train = every other county`. Then measure, per held-out
county, the fraction of its test-set dates that also appear in the training
counties (i.e. dates the model trained on from elsewhere).

**Result.** Place identity is genuinely held out, **but the split is purely
spatial — never temporal.** Held-out-county test dates overlap training dates:

| Held-out county | test-date overlap with train counties |
| --- | --- |
| San Mateo | 99.8% |
| Ventura | 99.8% |
| San Francisco | 97.2% |
| Orange | 96.2% |
| Los Angeles | 91.4% |
| San Diego | 81.6% |

Because exceedances are storm-driven and storms hit the whole coast on the same
day, the model has already trained on that date's shared weather from other
counties. The spatial backtest answers *"predict a new place on a day whose
weather you've seen elsewhere,"* not *"forecast a future day."* **No backtest in
the pipeline holds out place and time together** — the real deployment condition.

**Per-county AUCPR (ensemble vs persistence).** Beats persistence in every
county, but the pooled 0.634 is carried by San Diego; low-base-rate counties are
weak:

| County | base rate | ensemble AUCPR | persistence | Δ |
| --- | --- | --- | --- | --- |
| San Diego | 0.40 | 0.711 | 0.573 | +0.137 |
| Los Angeles | 0.18 | 0.530 | 0.323 | +0.207 |
| San Mateo | 0.21 | 0.518 | 0.327 | +0.191 |
| San Francisco | 0.13 | 0.497 | 0.204 | +0.293 |
| Ventura | 0.05 | 0.375 | 0.063 | +0.312 |
| Orange | 0.05 | 0.186 | 0.085 | +0.101 |

**Coverage gap.** Only **6 of 15** CA counties are ever held out (daily CI cap).
Santa Cruz, San Luis Obispo, Santa Barbara, Marin, Monterey, Humboldt,
Mendocino, Sonoma, East Bay Parks are in the training data but never
spatially validated.

---

## Test 3 — Training cadence vs serving cadence

**Method.** Measure inter-sample gaps per beach in `beach_day.parquet`; measure
`sample_age_days` in the served `forecasts.parquet`; compare against the 45-day
stale-censoring cutoff (`_STALE_CUTOFF_DAYS`).

**Result.**
- **Labels are weekly:** median inter-sample gap **7 days**; 62% of gaps are 6–8 days.
- **The product is daily** and always off-sample: 284 served beaches, **zero**
  sampled on the forecast day, `sample_age_days` min 4 / median 9 / mean 15 /
  max 37. All rows `is_beta_forecast=True`.
- **95.1%** of served forecasts fall in an **8–44 day "middle band"** — the last
  recorded sample is stale, but below the 45-day cutoff, so the model consumes the
  weeks-old risk-history feature at face value. **0%** are actually censored.

**Implication.** The strongest features are the lagged risk-indicator geomeans
(`risk_geomean_30d_lagged`, `_42d_lagged`). They are fresh in every
evaluation row (a sample was taken that day = the label) and stale in nearly
every served row. The metrics measure a fresher regime than anything shipped.

---

## Test 4 — Real forecast vs. ground truth (the prospective test) ★

This is the authoritative test: it scores the **actual `p_exceed` the production
model served**, against the outcomes that followed. Nothing synthetic.

**Method.**
1. Extract `forecasts.parquet` from every daily git commit → 23,901 forecasts,
   646 beaches, 89 days (final forecast kept per beach-day).
2. Join to `observations.parquet` (worst sample per beach-day) on `(beach_id,
   date)`.
3. Score two ways: **same-day** (forecast D vs outcome D) and **strictly-forward**
   (first outcome in D+1…D+3, which the forecast provably could not have seen).

**Result — full 89-day window (2026-04-23 → 07-22):**

| Match | pairs | base | AUCPR | AUROC | Brier | Brier(flat base rate) | sens@spec0.87 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Same-day | 2,506 | 0.063 | **0.239** | 0.816 | 0.068 | **0.059 (better)** | 0.569 |
| Strictly-forward (no leakage) | 6,701 | 0.058 | **0.213** | 0.802 | 0.065 | **0.054 (better)** | — |

**Result — last 30 days (2026-06-23 → 07-22):**

| Match | pairs | base | AUCPR | AUROC | Brier | Brier(flat base rate) | sens@spec0.87 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Same-day | 605 (37 pos) | 0.061 | **0.269** | 0.857 | 0.079 | **0.057 (better)** | 0.703 |

**Calibration (89-day, predicted p_exceed → actual exceedance rate).**
Systematically overconfident at the top:

| predicted p_exceed | actual rate | n |
| --- | --- | --- |
| ~0.98 | 0.36 | 88 |
| ~0.55 | 0.25 | 16 |
| ~0.32 | 0.23 | 167 |
| ~0.13 | 0.068 | 263 |
| ~0.02 | 0.019 | 1,450 |

The claimed calibration slope (1.18) does **not** hold forward.

**Operational banding (Low = "safe", Moderate+ = warning).**

| Window | sensitivity | exceedances shown as "Low" | specificity | false alarms |
| --- | --- | --- | --- | --- |
| 89 days | 0.633 (100/158) | **58** | 0.862 | 325 |
| Last 30 days | 0.649 (24/37) | **13** | 0.910 | 51 |

**Ranking survives staleness** (89-day AUROC by sample age): 2–7d 0.82, 8–14d
0.80, 15–30d 0.82, >30d 0.95. The weekly→daily extrapolation degrades
*calibration/precision*, not rank order.

**Falsifiability.** Only **10.5%** (89-day) / **8.6%** (30-day) of issued
forecasts ever had a same-day verified result. ~90% of what the system published was
never checkable against truth.

---

## Test 5 — On-disk stale-censoring diagnostic

**Method.** `scripts/diagnose_spatial_brier.py --model hist_gbm --group-columns
county --training-window-days 365 --max-county-groups 6 --stale-censor-cutoffs
5,7,9,14,21,30`. This uses the repo's own history-censoring utility (the
`stale_evaluation` module) to zero the risk-history features (simulating a
stale, between-sample serving row) and re-scores leave-one-county-out. 16,101
rows, 6 CA counties.

**Result.**

| Regime | Model Brier | Persistence Brier | Model edge |
| --- | --- | --- | --- |
| **Fresh** risk history (backtest ideal) | 0.128 | 0.185 | **−0.057** |
| **Censored** (= daily between-sample serving reality) | 0.170 | 0.184 | **−0.014** |

Identical at every cutoff (censoring zeros all risk features regardless of
the number). Censored, the model **under-predicts risk**: Los Angeles mean
prediction 0.026 against a true 0.208 exceedance rate (bias **−0.18**) — it
defaults to "safe" exactly when the recent risk signal is gone.

**Interpretation.** ~75% of the model's Brier edge over persistence comes from
the recent-outcome autocorrelation feature. In the regime it actually serves (95% of
forecasts have stale risk history), that edge collapses to near-persistence
**and acquires a low-side bias** — the same false-negative mode Test 4 caught
live.

---

## Consolidated verdict (California)

Two independent methods — synthetic censoring on backtest data (Test 5) and real
forecast-vs-outcome scoring (Test 4) — **converge**: the model is **not as reliable
as its shipped metrics claim in the regime it operates in.**

- Headline **AUCPR 0.63–0.70 is an artifact of scoring fresh sample-days**; the
  live product runs **≈0.24–0.27**.
- **Calibration fails forward** — overconfident up top, and probabilities beat
  neither a flat base rate.
- The real skill is **borrowed from recent-outcome autocorrelation**, which is stale
  on ~95% of served forecasts, where the model tilts **unsafe** (calls
  flagged beaches "Low").
- **Saving grace:** rank-ordering holds (AUROC ≈0.80–0.86), so "Very High" really
  is ~6× base rate. The tiers are directionally useful; the probabilities and the
  "Low" label are not.

## Recommended follow-ups — status (2026-07-22)

1. **Publish the live number — SHIPPED** (`app/ml/served_metrics.py`). Every daily
   run appends what actually served to `data/curated/forecast_history.parquet`
   (seeded from git by `scripts/backfill_forecast_history.py`; reproduces this
   audit's Test-4 numbers to 3 decimals) and writes the served-regime
   AUCPR/AUROC/Brier-vs-flat, band operating point, and reliability bins into
   `system_health.json["served_metrics"]` (90d + 30d windows).
2. **Spatiotemporal holdout — NOT implemented.** Deliberate: the live
   forecast-vs-outcome loop in #1 now measures the true deployment condition
   directly and prospectively, which strictly dominates a backtest proxy for
   accountability. A place+time-blocked backtest remains useful for offline
   *model selection* (`scripts/diagnose_spatial_brier.py`, `spatial_compare.py`)
   before promoting a new architecture.
3. **Censored-regime metrics — subsumed by #1.** `served_metrics` scores the
   stale-history rows the product actually serves; the synthetic censoring
   diagnostic stays available offline (Test 5's script) for pre-deployment
   checks of new models.
4. **Recalibrate — SHIPPED** (`fit_serving_calibration` + serve-time apply in
   `training.py::_export_forecasts`). Daily isotonic refit on the trailing 120d
   of served-forecast/lab pairs, applied to `p_exceed` (+ interval bounds)
   before banding; `p_exceed_precal` persists the pre-calibration value for
   future refits. First fit (8,888 pairs / 490 positives): served Brier 0.0603 →
   0.0464, now **beating** the flat base rate (0.0521); the ~0.98 tail maps to
   ~0.41 (realized ~0.38). Monotone, so the surviving AUROC is untouched; the
   positive-persistence "never display Low" invariant is preserved via an
   explicit floor. Band cutpoints were left alone — with honest probabilities
   the bands regain their published meaning ("Low < 0.20" now actually means
   <20%); mapping stats land in `system_health.json["serving_calibration"]`.

**Not yet addressed (model-side):** the underlying train/serve regime mismatch —
training rows are all fresh-history sample-days. Candidate fix: staleness
augmentation (train on rows with risk-history features censored to the serving
age distribution + a days-since-sample feature) so the model degrades gracefully
instead of defaulting safe; validate offline with Test 5 before shipping.
