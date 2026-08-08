# 2 — The ML system (`backend/app/ml/`)

~7,000 lines. `training.py` alone is 4,950 and is the least idiomatic file in the repo
(see [Document 4](04-design-patterns-review.md)); the supporting modules are small,
single-purpose, and well tested.

```
training.py           orchestrator: load → split → fit → backtest → gate → export
models.py             the estimators
two_tier.py           level+deviation primitives + within-beach AUROC
calibration.py        isotonic + hierarchical calibrators, risk bands
evaluation.py         metrics, cluster bootstrap, holdout persistence
served_metrics.py     the accountability loop (served forecast vs reality)
stale_evaluation.py   censoring rows to simulate the serving regime
spatial_diagnostics.py / per_station_residual.py / weather_delta.py / datasets.py
```

---

## 2.1 `models.py` — the estimators

### The macOS import dance (lines 1–25)

```python
if sys.platform == "darwin":
    os.environ.setdefault("OMP_NUM_THREADS", "1")
import xgboost   # noqa: F401   ← MUST precede torch
import torch
```

Both `xgboost` and `torch` vendor their own `libomp`. Loading torch's first then
xgboost's segfaults on macOS (duplicate OpenMP runtime), and even when it doesn't, the
two OpenMP pools deadlock during torch training. Forcing xgboost's to initialize first
and pinning to one thread breaks both. No-op on Linux CI. This is an environment
workaround, correctly scoped and correctly commented — but note it makes import order
load-bearing, so `ruff`'s import sorter must never be allowed to "fix" it.

### `make_baselines` — the reference implementations

Returns a `BaselineBundle` of four sklearn objects built from one shared
`ColumnTransformer` (median impute → standard scale over numeric columns):
`LogisticRegression(class_weight="balanced")`, `ElasticNet`,
`HistGradientBoostingClassifier`, `HistGradientBoostingRegressor`.

Idiomatic sklearn: preprocessing lives inside the `Pipeline`, so it is fit on train
folds only and cannot leak test statistics.

### `XGBUndersampleEnsemble` — the registry winner

An **EasyEnsemble** variant:

```python
pos = np.flatnonzero(labels == 1)
neg = np.flatnonzero(labels == 0)
k = min(int(len(pos) * self.negative_ratio), len(neg))   # 2 negatives per positive
for i in range(self.n_estimators_ensemble):              # 12 members
    draw = rng.choice(neg, size=k, replace=False)
    model = XGBClassifier(..., random_state=self.random_state + i)
    model.fit(features.iloc[np.concatenate([pos, draw])], labels[...])
```

Keep **every** positive, draw 12 independent balanced undersamples of the negatives,
fit one XGBoost each, soft-average the probabilities. Compared with a single
class-weighted model this trades a little bias for a lot of variance reduction on the
minority class, and it won leave-one-county-out validation (+0.069 AUCPR, better
Brier) against the incumbent single balanced GBM.

Three implementation details:

- `random_state + i` per member — otherwise all 12 undersamples would be identical.
- A **degenerate-input guard**: single-class input falls back to one plain fit rather
  than raising, so a bad spatial fold can't take down the run (the gate filters those
  folds out anyway).
- `predict_proba` reindexes to `feature_names_` with `fill_value=0.0`, so a column
  that vanishes between train and inference doesn't silently shift every other column
  by one position.

### `XGBUndersampleOffsetEnsemble` — the two-tier model

Same undersampling, plus the two changes that make it work between samples:

**(a) Per-beach baseline as `base_margin`.**

```python
self.beach_margins_, self.global_margin_ = beach_baseline_margin(labels, beach_ids)
margins = margins_for(beach_arr, self.beach_margins_, self.global_margin_)
dtrain = xgb.DMatrix(features.iloc[idx], label=labels[idx])
dtrain.set_base_margin(margins[idx])
```

`base_margin` is an offset added to the raw score *before* the logistic link. Supplying
each beach's shrunk historical log-odds means the boosted trees can only reduce loss by
explaining **within-beach departures** from that level — the level itself comes from a
statistic that never goes stale. This is a training-time change: it alters the gradient
the trees see, so it cannot be reproduced by reweighting a trained ensemble.

The docstring records that this beat supplying the same offset as an ordinary feature
by ~+0.05 AUCPR, which is the empirical justification for reaching past the sklearn
wrapper to the `DMatrix` API.

**(b) Staleness augmentation.**

```python
features, is_stale = staleness_augmented_frame(features, cutoff_days=14)
labels    = np.concatenate([labels, labels])
beach_arr = np.concatenate([beach_arr, beach_arr])
```

Every training row is duplicated with its bacteria-history features zeroed and its
recency forced to ≥ 14 days — a synthetic "between-sample day." Training on both copies
teaches the model to fall back on rain/solar/wind covariates when the anchor is stale,
instead of collapsing to "safe."

The measured effect on the censored/served regime: **AUCPR 0.535 → 0.668, Brier 0.119 →
0.085, low-side bias −0.102 → +0.004**, at essentially no cost to the fresh regime.

`accepts_beach_ids = True` is a class-level capability flag the training dispatch checks
before deciding whether to pass `beach_ids` into `fit`/`predict_proba`. See
[Document 4](04-design-patterns-review.md#sklearn-estimator-conventions) for why
sklearn's own metadata routing would be the documented alternative.

### The neural models — dead code, kept honestly

`BeachTCN`, `BeachCNN`, `BeachLSTM`, `BeachTransformer`, `BeachPINN_MultiTask` are
complete PyTorch implementations sharing one shape: sequence encoder → pooled → concat
with a static-feature MLP and a site embedding → shared trunk → classifier + regressor
heads.

They are registered as `SEQUENCE_MODEL_NAMES` and never promoted. `CLAUDE.md` records
why: MPS/LSTM lost on every cohort (CA 0.721 vs the XGB ensemble), and shipping any of
them would need a freeze → CPU-inference → CI path that does not exist. Keeping them
compiling but unpromoted is a defensible choice; leaving them un-deleted is a cost
(~250 lines of maintained surface for a rejected experiment).

### `persistence_probabilities` — the baseline everything is judged against

```python
latest = frame.groupby("beach_id")["exceeds_stv"].shift(1).fillna(0.0)
```

"Predict whatever happened last time." Two lines. It is the gate's veto baseline, and
on the leave-one-beach-out holdout it scores **AUCPR 0.826** — a number most models
would be delighted to publish. That is exactly why it is the baseline.

---

## 2.2 `two_tier.py` — the primitives and the honest metric

### `beach_baseline_margin` — empirical-Bayes shrinkage

```python
global_rate = clip(y.mean(), eps, 1-eps)
rate = (agg["sum"] + prior_strength * global_rate) / (agg["count"] + prior_strength)
margins = {beach: logit(r) for beach, r in rate.items()}
```

With `prior_strength = 4.0`, a beach with 4 samples is shrunk halfway to the global
rate; a beach with 400 is essentially its own empirical rate. Returned as a logit so it
drops straight into `set_base_margin`. Unseen beaches fall back to the global margin.

### `within_beach_auroc` — the metric that exposes everything

```python
for _, group in frame.groupby("b", sort=False):
    if len(group) < min_samples or group["y"].nunique() < 2:
        continue
    weights.append(len(group))
    scores.append(roc_auc_score(group["y"], group["p"]))
return float(np.average(scores, weights=weights)), len(weights), int(sum(weights))
```

**Compute AUROC separately inside each beach, then row-weight.** This asks the only
question the product actually poses: *at a fixed beach, can the model rank its bad days
above its clean days?*

0.5 means no daily skill — the model is a per-beach lookup table, however good its
global AUROC looks. Global metrics cannot see this failure because they are dominated by
*between-beach* variance: a model scores brilliantly by knowing Imperial Beach is dirtier
than Carmel, with zero ability to tell Tuesday from Thursday at either one.

This distinction is the single most valuable idea in the codebase, and
[Document 5](05-model-effectiveness.md) shows what it reveals.

`within_beach_auroc_by_lag` stratifies the same metric by days-since-last-sample, which
is how the train/serve gap was localised.

⚠️ **This function returns `float("nan")` when no beach qualifies**, which is legitimate.
Publishing it as a bare `NaN` token is not — see `core/json_safe.py` and the incident in
§ 2.7.

---

## 2.3 `calibration.py` — probabilities that mean what they say

### `LOGIT_EPSILON` — one clip, defined once

```python
LOGIT_EPSILON = 1e-4
```

The header comment explains a genuinely subtle bug: `evaluation._calibration_slope` used
`1e-6` while the transform actually applied to served probabilities used `1e-4`. The
reported calibration slope — **a publication-blocking gate metric below 0.4** — was
therefore fit on a wider log-odds range than the pipeline ever produces. Measured impact:
the winner moved 1.1467 → 1.1523 (nothing), but the saturated persistence baselines moved
~50% (0.1039 → 0.1559). No candidate crossed the gate either way, but "the number we
report" and "the number we apply" were silently different, which is the class of bug that
eventually bites.

### `ProbabilityCalibrator` vs `HierarchicalProbabilityCalibrator`

The simple one wraps sklearn's `IsotonicRegression(out_of_bounds="clip")`. The
hierarchical one fits an approximate partial-pooling model:

```
logit(p) = a_county + b_county · logit(q) + u_site  [+ u_station]
```

with each group's intercept/slope shrunk toward the global fit by
`n / (n + prior_strength)`. `predict_interval` widens the band by
`1/(count+1)` per level, so a beach with little history gets a visibly wider interval —
uncertainty that is *structural*, not just residual.

**Where the hierarchical calibrator is deliberately NOT used:** inside spatial holdout
folds. `_spatial_holdout_fold_result` shadows the helper —

```python
def _identity_or_calibrated(p, labels, m=None):
    return _orig(p, labels)   # metadata deliberately excluded
```

— because the held-out county is by construction absent from the calibrator's training
data, so it falls back to global parameters and the calibration slope collapses to ≈0.18.
The intent is right. The *mechanism* (a local function that shadows a module-level name
and re-imports it from its own module) is the least readable line in the file; a
`use_metadata: bool` parameter would say the same thing plainly.

### Risk bands and the two safety gates

```python
_LOW_THRESHOLD, _HIGH_THRESHOLD, _VERY_HIGH_THRESHOLD = 0.20, 0.30, 0.70
```

- **`advisory_floored_probability`** — while an official county posting is active, lift
  `p_exceed` to the High cutpoint. This means a posted beach can never render Low or
  Moderate, so the badge and the band cannot contradict each other. It exists because
  the pipeline's own advisory feature (baked into the training frame) and the serve-time
  advisory flag (read from `advisories.parquet`) are different sources and can disagree:
  measured on the 2026-07-30 bake, of 18 posted beaches the feature-driven floor fired on
  16, and the two it missed would have shown "Low" under an active advisory.
- **`confidence_capped_risk_band`** — caps the *displayed* band at Moderate when the
  underlying sample is >60 days old or of unknown age **and** no advisory is posted. The
  numeric `p_exceed` is left untouched. An active advisory always wins. This is a
  false-alarm lever that cannot raise the false-negative rate on recent data, because
  fresh/recent/stale samples are never capped.

Both are good examples of **separating the honest number from the displayed state**.

---

## 2.4 `evaluation.py` — metrics with their uncertainty

### `sensitivity_at_specificity`

Sweeps every distinct predicted probability as a candidate threshold, keeps those
achieving at least the target specificity, and returns the most sensitive one — with a
documented fallback to the best attainable specificity when the target is unreachable.

This exists to compare against a real operational benchmark: **Searcy et al. 2018**,
median sensitivity **0.50 at specificity 0.87** across 10 California oceanic beaches.
Before this shipped, the repo's claimed "0.59 @ 0.87" was unverifiable because no
holdout artifact was persisted.

### `cluster_bootstrap_aucpr_ci` — the right resampling unit

```python
drawn = rng.choice(n_groups, size=n_groups, replace=True)
idx = np.concatenate([group_to_rows[unique_groups[g]] for g in drawn])
```

Spatial AUCPR is pooled across leave-one-out folds, so rows are **not independent** —
every row in a held-out county shares that fold's single training draw. Resampling rows
would badly understate the uncertainty. Resampling *folds* is correct, and the result is
sobering: the 6-fold pooled county AUCPR 95% CI measures roughly **[0.38, 0.71]** on the
current snapshot. Any claim of a 0.02 improvement is noise against that width.

`paired_cluster_bootstrap_aucpr_gap_ci` extends this to model comparison by drawing the
same folds for both models, removing the between-fold variance that dominates a 6-fold
sweep.

### `persist_holdout_predictions` — an artifact, not just a number

Writes tidy `(label, probability, model, group, …)` parquet. This is what makes every
operating point recomputable without retraining, and it is the data behind
[Document 5](05-model-effectiveness.md). Note it swallows all exceptions and returns
`None` — deliberate: persisting an evaluation artifact must never take down a model
build.

---

## 2.5 `training.py` — the orchestrator

### Evaluation design (three layers)

1. **Temporal split** (`_blocked_indices`, line 1640) — unique sample *dates* split
   70/15/15. Splitting on dates, not rows, is what stops the same beach-day appearing on
   both sides. Single split, no folds.
2. **Leave-one-county-out** (`_spatial_backtest_metrics`, line 1386) — train on N−1
   counties, test on the held-out one, rotate. CI default 6 folds.
3. **Leave-one-beach-out** — same at station level. CI default 15 folds.

Fold counts were cut from 12/50 to 6/15 in commit `153f1368a` because the full sweep at
the 1,095-day window (~84 k rows, ~60 retrains) overran the 170-minute CI budget and
timed the whole job out, producing a stale forecast and a 503. The trade is honestly
recorded: the pooled AUCPR is now noisy run-to-run, so **`system_health.json` is the
source of truth and any number in prose is a dated snapshot.**

### The promotion gate — `_promotion_assessment` (line 2014)

Returns `public_release_eligible` plus a list of blockers. A model is blocked if:

- production test metrics are missing or have no AUCPR;
- spatial backtests were not run, or the county/beach keys are missing;
- **a backtest produced zero usable folds** — the fail-closed case. The metrics dict
  always gets its key, but a zero-fold run returns `{"folds": 0.0}` with no `aucpr`. Every
  downstream comparison is `is not None`-guarded, so without this explicit check an
  entirely unvalidated model would sail through by default;
- held-out **county** AUCPR ≤ persistence, or Brier ≥ persistence;
- held-out **beach** AUCPR ≤ persistence, or Brier ≥ persistence;
- either spatial calibration slope < 0.4.

### `_spatially_qualified_production_winner` (line 1941) — pick-best with hysteresis

Filter to models that clear the gate, then rank by held-out **county** AUCPR → beach
AUCPR → lower spatial Brier. Ranking on the spatial metric (not the temporal one an
earlier version used) is the whole point: *the gate filters on spatial generalization, so
it must also select on it.*

A challenger displaces a passing incumbent only when **both** hold:

```python
if gap <= _WINNER_SWAP_MARGIN:            # 0.01 point-estimate floor
    return preferred
gap_ci = _paired_county_aucpr_gap_ci(best, preferred, predictions_sink)
if gap_ci is None:
    if gap <= _WINNER_SWAP_LARGE_GAP_MARGIN:   # 0.07 fallback ≈ measured half-width
        return preferred
elif not (gap_ci[0] > 0.0):
    return preferred
```

The comment does the arithmetic that justifies this: the cluster-bootstrap 95%
half-width over 6 folds is ~0.136, **~14× the 0.01 floor**, so the floor alone would churn
the production winner on pure noise every day. This is a statistically literate guard, and
rare in production ML code.

### `_publish_forecasts_unless_blocked` (line 3287) — the gate has teeth

```python
if release_blocked:
    print("RELEASE GATE BLOCKED publication: …", file=sys.stderr)
    return False
pd.DataFrame(forecasts).to_parquet(curated_dir / "forecasts.parquet", index=False)
```

When the gate fails, `forecasts.parquet` is **not overwritten** — the last validated
forecast keeps serving. The data commit still happens (auditability), blockers land in
`system_health.json["release_gate"]`, and `scripts/verify_release_gate.py` then fails the
CI job so a `pipeline-failure` issue is opened. A gate that only logs is not a gate; this
one changes what ships.

### The serve-time router (lines 3321–3392)

```python
weight = np.clip((age - 3) / (5 - 3), 0.0, 1.0)
weight = np.where(np.isfinite(age), weight, 1.0)   # unknown age → offset
routed  = (1 - w) * ensemble_probs + w * offset_probs
```

Sample ≤ 3 days old → the ensemble (it wins at low lag, where the anchor is live).
≥ 5 days → the offset model. Between → a linear blend, so a beach crossing the boundary
as its sample ages doesn't jump bands overnight (the hard switch moved probabilities by
0.074 mean / 0.186 p90; the ramp halves that).

**The router keys on nothing but data lag, and it is violently sensitive to it.** Holding
observations fixed and moving only the forecast date, the fresh/blended/stale split
moves 268/0/250 → 124/144/250 → 43/81/394 across three consecutive days. One day of
pipeline lag moves ~144 beaches onto a different model, silently and with no alert. If a
router split ever looks surprising, **check the data lag before suspecting the model.**

Two traps this creates for anyone reading the metrics:

1. `production_model` in `system_health.json` reads
   `xgb-undersample-ensemble-curated-v0` and always will — that is the registry *winner*,
   not the model that computed `p_exceed`. Read
   `model_registry.metrics.two_tier_diagnostics.serving_router` (note the nesting) and the
   per-row `served_offset_weight`.
2. `served_metrics` averages across the router cutover until its 90-day window rolls past
   it, so the published served AUCPR understates what is running now.

---

## 2.6 `served_metrics.py` — the accountability loop

This module is the reason to trust anything else in the repo. It exists because a 2026-07
audit (`model_truth.md`) proved the backtests measure a regime the product never serves.

| Function | What it does |
|---|---|
| `append_forecast_history` | Appends `forecasts.parquet` **after** the release-gate decision to an append-only log keyed by `(beach_id, forecast_date, forecast_generated_at)`. Idempotent, atomic (`.tmp` → `os.replace`) |
| `daily_outcomes` | Worst lab result per beach-day — mirrors the training label rule exactly |
| `_final_per_beach_day` | Last-issued forecast per beach-day = *what a user actually saw* |
| `_with_outcomes` | Joins same-day truth, then the first result in D+1…D+3 (provably unseen by the forecast) |
| `served_performance` | Brier, AUCPR, AUROC, sensitivity@spec, band operating point, reliability bins, over 90 d and 30 d windows |
| `fit_serving_calibration` | Daily isotonic refit on the trailing 120 d of served/lab pairs |
| `apply_serving_calibration` | Piecewise-linear interpolation through the isotonic knots |

Three design choices deserve emphasis:

**`brier_flat_base_rate` ships alongside every Brier score.** The bar an uninformative
constant sets. The audit found the served probabilities *losing* to it, so it is now
published every day, permanently. Very few ML systems publish the number that can
embarrass them.

**`verifiable_fraction`.** Of forecasts old enough that a result *could* have arrived,
how many ever got one. Currently ~0.47–0.51. Roughly half of everything published can
never be checked, and the system says so out loud.

**Guards on the calibration refit.** `_MIN_FIT_PAIRS = 500`, `_MIN_FIT_POSITIVES = 25`;
below those it returns `None` and the caller serves the uncalibrated probability — exactly
the pre-audit behaviour. Failing back to a known state rather than to a noisy fit.

The first fit moved Brier 0.0603 → 0.0464, beating the flat base rate 0.0521. Because the
map is monotone, AUROC (the part that held up forward) is untouched.

---

## 2.7 `core/json_safe.py` — a small module with a large incident behind it

`within_beach_auroc` legitimately returns NaN. `json.dumps` writes it as a bare `NaN`
token, which is **not valid JSON** (RFC 8259). One such value under
`two_tier_diagnostics.temporal.by_lag.lag_8_14d` killed the private web build mid-prerender
(`SyntaxError: Unexpected token 'N'`), freezing the static export at the last good bake —
which is what actually showed users a "47 hours ago" timestamp.

The API survived only by luck: FastAPI's `jsonable_encoder` runs responses through
pydantic v2's `model_dump(mode="json")`, whose default `ser_json_inf_nan="null"` maps
non-finite floats to `null` before Starlette's `allow_nan=False` renderer sees them.

The fix is two functions:

```python
json_safe(value)    # recursively: non-finite float → None; numpy scalars → .item()
dumps_strict(payload)  # then json.dumps(..., allow_nan=False)
```

`allow_nan=False` is the important half: a future producer that slips a non-finite value
past the scrub now **fails loudly at the write** instead of shipping a document nobody
downstream can parse. Every published JSON goes through it.
