# 4 — Does this follow established patterns? Does it use libraries the documented way?

Two separate questions, answered separately. Short version:

> **Architecture: yes, mostly — the serving layer is textbook, the pipeline is
> pragmatic, and `training.py` is a god module.**
>
> **Library usage: yes for FastAPI / pydantic / pandas / parquet; partially for
> scikit-learn, where the custom estimators skip the documented estimator contract;
> correct-but-inconsistent for XGBoost.**
>
> **What is genuinely unusual — and better than most production ML code — is the
> evaluation and release discipline.** The release gate, the served-metrics
> accountability loop, cluster-bootstrap CIs on model comparison, and
> `within_beach_auroc` are things most teams never build.

Measurements below are from `ast` over the current tree, not impressions.

---

## Part 1 — Design patterns

### 1.1 Patterns implemented correctly

| Pattern | Where | Assessment |
|---|---|---|
| **Repository** | `repositories/base.py` + 3 implementations | Textbook. ABC, three backends, a factory, and `test_repository_parity.py` asserting they agree. `list_parent_beaches` is concrete-with-default rather than abstract — the right call for an evolving optional capability |
| **Factory** | `repositories/factory.py` | Explicit selection ladder, explicit failure modes, and a hard refusal to serve fixture data in production |
| **Dependency Injection** | `api/routes.py` | FastAPI `Depends` throughout; every dependency overridable in tests |
| **Adapter** | `pipeline/{beachwatch,ceden,wqp,county_direct}.py` | Each `normalize_*` adapts a foreign schema to one internal shape. Adding a 13th county scraper touches exactly one file |
| **CQRS (read model)** | `pipeline/serving_snapshot.py` | Columnar parquet for the training scan, row-oriented sqlite for point lookups. Two shapes, one truth, rebuilt not synced |
| **Null Object** | `FixtureBeachRepository`; `_identity_or_calibrated` | A safe do-nothing implementation instead of `None` checks at every call site |
| **Event log / append-only ledger** | `served_metrics.append_forecast_history` | Idempotent on `(beach_id, forecast_date, forecast_generated_at)`, atomic write. Enabled a full 189-commit historical backfill after the fact |
| **Circuit breaker** | `_publish_forecasts_unless_blocked` | Gate fails ⇒ new artifact is not written, previous validated one keeps serving, CI job fails, issue opens |
| **Strategy** | `calibration.py`, `connectors/base.py` | Correct where used — see the caveat below |

### 1.2 The god module

```
app/ml/training.py — 4,950 lines, 86 functions
    585  _export_forecasts
    443  _run_winner_only
    367  train_curated_and_export
    253  _spatial_holdout_fold_result
    9 functions over 100 lines; 3 over 300

app/data/pipeline/cli.py — 1,090 lines, 15 functions
    704  main
```

`_export_forecasts` takes **18 parameters** and does candidate construction, hydrology
refresh, inference, routing, calibration, banding, driver attribution, artifact
persistence, and publication. `cli.main` is a 704-line procedure of `if args.with_x:`
blocks.

This is the repo's real architectural debt. The consequences are concrete, not
stylistic:

- **Untestable in units.** `tests/test_training.py` exists, but the seams available to
  it are small helpers; the 585-line export path can only be exercised end-to-end.
- **Ordering constraints are invisible.** The county-direct-before-covariates rule
  documented in `CLAUDE.md` is enforced by *statement order inside `main`*, so nothing
  fails loudly if someone reorders the blocks — the covariates just come out `NaN`.
- **Merge conflicts concentrate** in exactly the two files most likely to be edited.

The refactor is unglamorous but mechanical: extract `_export_forecasts` into a
`ForecastExporter` with `build_candidates` / `predict` / `route` / `band` / `publish`
steps, and turn `cli.main`'s flag blocks into an explicit ordered stage list where each
stage declares the artifacts it requires. The second one would convert an implicit
ordering rule into a checked precondition.

### 1.3 The abandoned ABC

```python
# connectors/base.py
class SourceConnector(ABC):
    @abstractmethod
    async def fetch(self, context: SourceContext) -> pd.DataFrame: ...
```

`official_sources.py` implements it (4 classes). **`hydrology_sources.py` does not** — its
eight connectors are plain `@dataclass`es with bespoke signatures that never see a
`SourceContext`.

So the package has two connector conventions, and the abstraction that was supposed to
unify them covers a third of the cases. It is not causing bugs — the hydrology
connectors are internally consistent with each other — but it means "implements
`SourceConnector`" tells you nothing about a given connector, and a generic
"fetch all sources" driver cannot be written.

Either extend the ABC to cover the parameterised case (`fetch(self, context, **params)`)
or delete it and document duck typing as the convention. The current middle state is the
worst of both.

### 1.4 The function-shadowing hack

```python
# _spatial_holdout_fold_result
def _identity_or_calibrated(p, labels, m=None):  # type: ignore[misc]
    from app.ml.training import _identity_or_calibrated as _orig  # noqa: F811
    return _orig(p, labels)   # metadata deliberately excluded
```

A local function shadows a module-level name and re-imports it from its own module to
reach the shadowed original. It needs a `# noqa: F811` and a `# type: ignore` to get past
the linter and type checker — two suppressions are a reliable signal that the language is
being fought.

**The intent is correct and important**: inside a spatial fold the held-out county is
absent from the calibrator's training data, so the hierarchical calibrator falls back to
global parameters and the calibration slope collapses to ≈0.18. Passing metadata there
would be wrong.

The plain expression of the same idea is a parameter:

```python
def _identity_or_calibrated(p, labels, metadata=None, *, use_metadata: bool = True):
    ...
# call site
_identity_or_calibrated(valid_raw, labels[...], meta, use_metadata=False)
```

Same behaviour, no shadowing, no suppressions, and the *reason* appears at the call site
where a reader is asking the question.

### 1.5 Stringly-typed metrics registry

Metrics live in nested `dict[str, dict[str, float]]` with keys assembled by f-string:

```python
metrics.get(f"spatial_county_{model_name}", {}).get("aucpr")
```

`_WINNER_TO_METRICS_KEY`, `_metrics_base_key`, and `_registry_model_version` exist purely
to translate between naming conventions. A typo in a key is a silent `None`, and every
`is not None` guard in `_promotion_assessment` is defending against exactly that. The
zero-fold fail-closed check exists because a *missing* key and a *failed* backtest were
indistinguishable.

A `@dataclass` (or `TypedDict`) for the per-scope metric bundle would make the gate's
preconditions checkable at the type level rather than at runtime. This one is worth doing
because the gate is the safety-critical component.

### 1.6 Committed backup artifacts

`data/curated/` contains `*.bak-pre-cleanup`, `*.bak-pre-scrape`, `*.bak-pre-retrain`,
`*.bak-pre-orphan-fix`, `*.pre-cdip.parquet` — including a 8.9 MB `beach_day.parquet.bak`
and two 7.2 MB `serving.sqlite.bak` copies, all committed to git.

Committing `data/curated/` itself is a *good* decision (it is what makes every published
number reproducible from a SHA, and what enabled the forecast-history backfill). The
ad-hoc `.bak-*` siblings are not — git already is the backup, and each one is permanently
in the history and in every clone and every Docker build context.

---

## Part 2 — Library usage vs the documentation

### 2.1 FastAPI — conformant, with one real gap

**Follows the docs:**

- `@lru_cache`d `get_settings()` used as a dependency — *verbatim* the pattern in
  FastAPI's "Settings and Environment Variables" page.
- `APIRouter` + `include_router`, `Depends` for injection, `HTTPException` with structured
  detail, middleware for cross-cutting concerns, pydantic v2 response models.
- SlowAPI wired through its documented extension point (`key_func`) rather than patched.

**Gap: no `response_model`, and no return type annotations.**

```python
@router.get("/beaches")
def list_beaches(response: Response, service: BeachService = Depends(get_service)):
    ...
```

FastAPI derives the OpenAPI response schema from either `response_model=` or the return
annotation. With neither, `/docs` documents every endpoint as an untyped 200, clients
cannot codegen, and FastAPI's response *filtering* never runs — so if a repository ever
returns a field that isn't in the schema, it is serialized straight to the public API
instead of being stripped.

The fix is one annotation per route and costs nothing:

```python
@router.get("/beaches")
def list_beaches(...) -> list[BeachSummary]:
```

The domain models already exist; they are simply not connected to the HTTP layer's
contract. For a public API with two client apps, this is the highest value-per-keystroke
change in the repo.

### 2.2 pydantic / pydantic-settings — conformant

v2 idioms throughout: `SettingsConfigDict`, `Field(ge=…, le=…)`, `Literal` unions for
closed enums, `Field(default_factory=list)` for mutable defaults. Additive-optional
evolution is applied consistently and each optional field documents the legacy snapshot
it is tolerating.

`json_safe.py`'s header even documents pydantic's `ser_json_inf_nan="null"` default and
correctly refuses to rely on it — the right conclusion from a correct reading of the
library's behaviour.

### 2.3 scikit-learn — correct usage, non-conformant custom estimators

**Follows the docs:**

- Preprocessing inside `Pipeline` + `ColumnTransformer`, so imputation and scaling are fit
  on train folds only. No leakage.
- `IsotonicRegression(out_of_bounds="clip")` for probability calibration — the documented
  approach.
- `average_precision_score` / `brier_score_loss` / `roc_auc_score` used correctly, with
  the base-rate caveat on AUCPR explicitly documented rather than ignored.
- Fitted attributes carry the trailing-underscore convention (`members_`, `boosters_`,
  `feature_names_`, `beach_margins_`).

**Deviates from "Developing scikit-learn estimators":**

| Requirement | Status |
|---|---|
| Inherit `BaseEstimator` + `ClassifierMixin` | ✗ neither custom estimator does |
| `get_params` / `set_params` | ✗ absent, so `clone()` fails |
| Fitted attributes set in `fit`, not `__init__` | ✗ `classes_ = np.array([0,1])` is set in `__init__` |
| `fit(X, y)` signature | ✗ `XGBUndersampleOffsetEnsemble.fit(X, y, beach_ids=…)` |
| `check_estimator` in tests | ✗ not run |

The practical cost: neither model can be used with `clone`, `GridSearchCV`,
`cross_val_score`, or `CalibratedClassifierCV`, because all of them clone via
`get_params`. That is *why* `training.py` has to hand-roll its own fold loops,
its own calibration split, and its own model dispatch — a large amount of the code
in the god module exists to work around estimators that opted out of the ecosystem.
Adding `BaseEstimator` is a two-line change per class and would delete real code.

The extra `beach_ids` fit parameter is handled with a hand-rolled capability flag:

```python
accepts_beach_ids = True     # training dispatch checks this before passing beach_ids
```

scikit-learn ≥ 1.3 has a documented mechanism for exactly this — **metadata routing**
(`sklearn.set_config(enable_metadata_routing=True)` plus
`.set_fit_request(beach_ids=True)`), and this project runs sklearn 1.8. The hand-rolled
flag works, and it is honest and commented; it is simply reimplementing a supported
feature. Worth revisiting only alongside the `BaseEstimator` change, since the two go
together.

### 2.4 XGBoost — correct, but two APIs for one job

**`base_margin` is exactly the documented mechanism for a fixed offset**, and using it
rather than a feature is the right call — the docstring records the +0.05 AUCPR
difference that justifies it. Good use of a feature most users never touch.

The inconsistency is *how* it is reached. `XGBUndersampleEnsemble` uses the sklearn
wrapper (`XGBClassifier`); `XGBUndersampleOffsetEnsemble` drops to the low-level
`xgb.train` + `DMatrix` API. On the pinned xgboost 3.2.0 the wrapper supports the same
thing directly — verified against the installed package:

```
XGBClassifier.fit(...)          → ['X','y','sample_weight','base_margin', …]
XGBClassifier.predict_proba(...)→ ['X','validate_features','base_margin','iteration_range']
```

So the DMatrix path is not required, and it costs the class `feature_importances_`,
`early_stopping_rounds`, and the sklearn-wrapper conveniences its sibling has. Two nearly
identical classes reaching XGBoost through two different APIs is the kind of divergence
that makes future maintainers guess which one to copy.

*(This is a consistency observation, not a bug — the current code is correct.)*

### 2.5 pandas — conformant, with above-average time-series discipline

- `errors="coerce"` on every numeric/date coercion; explicit `.copy()` before mutation.
- **Time-based rolling windows** (`rolling("7D", closed="left")`) rather than integer
  windows — correct for irregularly-sampled data, and `closed="left"` is the leakage
  guard. Using the string window is the documented way to get calendar semantics.
- `shift(1).ffill()` ordering for last-observed values — the right order, and commented.
- Atomic parquet writes via `.tmp` → `os.replace`.
- The `pd.concat(axis=1)` index-alignment hazard was diagnosed, fixed with
  `set_index(enriched.index)`, and documented in a 6-line comment. That specific bug
  (merge resets the index; concat aligns on it) silently corrupts every lag feature and is
  very hard to find. Finding it, fixing it, and writing it down is exactly right.

### 2.6 Tooling

`ruff` passes clean on `app/` at the pinned version. Pinning it (`ruff==0.15.12`) with a
comment explaining that an unpinned floor turned CI red on unchanged source is a correct
call. `constraints.txt` pins the scientific stack so a fresh PyPI resolve cannot silently
shift calibrated probabilities between runs — a reproducibility concern most projects
discover only after it bites them.

56 test files, ~11,000 lines of tests against ~19,000 lines of application code. Coverage
is concentrated where the risk is: `test_release_gate`, `test_two_tier`,
`test_served_metrics`, `test_holdout_persistence`, `test_repository_parity`,
`test_serving_staleness`, `test_schema_guard`, `test_json_safe`.

---

## Part 3 — What this codebase does better than most

These are worth naming, because they are rarer than the flaws above:

1. **The release gate blocks publication, not just logging.** A model that fails spatial
   validation does not ship. The previous validated forecast keeps serving, blockers are
   persisted, and CI fails. Most "model validation" is a printed metric nobody reads.

2. **It scores its own served output against reality, daily, in public.**
   `forecast_history.parquet` + `served_metrics` measure the *deployed* regime, not the
   backtest regime — and publish `brier_flat_base_rate` beside every Brier score so the
   number that would embarrass the model is always visible.

3. **It publishes `verifiable_fraction`.** Roughly half of everything published can never
   be checked against a lab result, and the system says so rather than quietly reporting
   metrics only on the checkable half.

4. **Model comparison uses cluster-bootstrap CIs with the correct resampling unit.**
   Fold-level, not row-level, because rows within a held-out county are not independent.
   The winner-swap rule then requires the paired CI's lower bound to clear zero — with an
   in-code comment doing the arithmetic (bootstrap half-width ~0.136 vs a 0.01 floor, so
   the floor alone would churn the winner on noise daily).

5. **`within_beach_auroc` exists at all.** Inventing the metric that can invalidate your
   headline number, computing it every run, and acting on the result is the single
   strongest signal of engineering integrity in this repo.

6. **Comments explain *why*, with measurements.** "1,021 beach-days flipped, 100% in the
   false-negative direction." "206/206 rows matched, so time-keying would have inserted
   206 duplicates." "The winner moves 1.1467 → 1.1523, but persistence moves ~50%." This
   is how postmortem knowledge survives a team change.

---

## Recommended order of work

| # | Change | Effort | Why first |
|---|---|---|---|
| 1 | Add return type annotations / `response_model` to all routes | ~1 h | Public API contract, OpenAPI, response filtering. Highest value per keystroke |
| 2 | `BaseEstimator, ClassifierMixin` + `get_params` on both custom estimators | ~1 h | Unlocks `clone`/CV/`CalibratedClassifierCV`; lets `training.py` *delete* hand-rolled loops |
| 3 | Replace the `_identity_or_calibrated` shadow with a `use_metadata` flag | ~30 m | Removes two linter suppressions from safety-critical calibration code |
| 4 | Typed metrics bundle (dataclass/TypedDict) for the gate | ~3 h | The gate is the safety-critical path; stringly-typed keys fail silently |
| 5 | Resolve the `SourceConnector` ABC — extend or delete | ~2 h | Ends the two-conventions ambiguity |
| 6 | Extract `_export_forecasts` into a staged exporter class | ~1–2 d | Makes the 585-line publication path unit-testable |
| 7 | Turn `cli.main`'s flag blocks into a declared stage list with required-artifact preconditions | ~1–2 d | Converts an implicit ordering rule into a checked one |
| 8 | Delete `data/curated/*.bak-*` | ~10 m | ~30 MB of redundant blobs in every clone; git is the backup |
