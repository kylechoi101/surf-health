# 3 — Serving and the API (`backend/app/{main,api,repositories,schemas,services}`)

The read path is small (~2,300 lines) and the most conventionally-architected part of
the repo. It is a clean four-layer stack.

```
HTTP  →  api/routes.py        thin: parse, delegate, set Cache-Control
      →  services/beach_service.py   ordering + response composition
      →  repositories/*.py    data access behind an ABC (3 implementations)
      →  schemas/domain.py    pydantic models = the public contract
```

---

## 3.1 `main.py` — application assembly

### The rate-limiter key function

```python
def _client_ip_key(request: Request) -> str:
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"
```

The service runs behind Cloudflare → Render's proxy, and uvicorn is not started with
`--proxy-headers`, so `request.client.host` is the *proxy's* IP — identical for every
visitor. Keying SlowAPI on it collapsed all traffic into one global 60/min bucket, so a
single busy minute 429'd everyone.

The precedence order is a security decision, not just a fallback chain:
`CF-Connecting-IP` is set by the Cloudflare edge and cannot be forged by a client;
`X-Forwarded-For` can be, so it comes second and only its first hop is trusted.

### Middleware order

`SlowAPIMiddleware` → `CORSMiddleware` → the logging `@app.middleware("http")`.
CORS is locked to GET/HEAD/OPTIONS with `allow_credentials=False` — correct for a
read-only public API; there are no cookies to protect and no mutating verbs to expose.

### Structured logging

One JSON line per request (`request_id`, `method`, `path`, `status_code`,
`duration_ms`) via `time.monotonic()`. Using `monotonic` rather than `time.time()` is
right — a clock adjustment mid-request can't produce a negative duration.

---

## 3.2 `core/config.py` — settings

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    ...

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

This is **verbatim the pattern from FastAPI's "Settings and Environment Variables"
documentation** — pydantic-settings `BaseSettings` plus an `lru_cache`d factory used as a
dependency, so the `.env` file is parsed once and tests can override it with
`app.dependency_overrides`. Nothing to change here.

`cors_origins` is exposed as a `@property` splitting a comma-separated string, because
env vars are strings and a `list[str]` field would require JSON-encoding the value in the
environment.

---

## 3.3 `repositories/` — the Repository pattern, properly done

```python
class BeachRepository(ABC):
    def list_parent_beaches(self) -> list[ParentBeachSummary]: return []   # optional
    @abstractmethod
    def list_beaches(self) -> list[BeachSummary]: ...
    @abstractmethod
    def get_beach(self, beach_id: str) -> BeachSummary: ...
    @abstractmethod
    def get_forecast(self, beach_id: str, forecast_date: date) -> ForecastRecord: ...
    @abstractmethod
    def get_observations(self, beach_id: str) -> ObservationResponse: ...
    @abstractmethod
    def get_system_health(self) -> SystemHealthResponse: ...
```

Three implementations:

| Implementation | Backing store | Used for |
|---|---|---|
| `ServingSnapshotRepository` | `serving.sqlite` | production |
| `CuratedBeachRepository` | the parquet files | local dev, pipeline debugging |
| `FixtureBeachRepository` | a JSON fixture | tests, cold start |

`list_parent_beaches` is deliberately **concrete with a `[]` default** rather than
abstract — an optional capability that older implementations can skip without breaking.
That is the right call for an interface that has to evolve.

### `factory.py` — selection with a production guard

```python
if settings.app_env == "production":
    raise RuntimeError(
        "No data repository available … Refusing to serve fixture data in production."
    )
return FixtureBeachRepository(settings.fixture_data_path)
```

The most important four lines in the file. Silently degrading to fixture data in
production would mean the API returns plausible, well-formed, **fabricated** beach safety
data. It refuses instead. For a public-health product this is the only defensible
behaviour, and it is easy to get wrong.

The selection ladder is `fixture` → `serving`/`sqlite` → `auto`/`curated` → hard failure
in prod. Explicit modes raise `FileNotFoundError` when their store is missing; only
`auto` falls through.

### `test_repository_parity.py` — the pattern's safety net

The Repository pattern only pays off if the implementations are actually
interchangeable. A dedicated parity test asserts they agree, which converts "we intended
these to be substitutable" into a checked property.

---

## 3.4 `serving_repository.py` — where the serving policy lives

888 lines, and the file where the product's hardest correctness rules are enforced.

### `serve_time_band` — one decision, shared by card and detail

```python
def serve_time_band(raw_p_exceed, stored_p_exceed, *, active_advisory, recency_band
                    ) -> tuple[str, float]:
    """Decide (band, probability) at SERVE time. Never read the stored band."""
```

The bug it fixes is a classic. `list_parent_beaches` read `risk_band` straight out of the
forecasts table — a value baked at **export** time with the advisory floor already
applied — while `_build_forecast_record` re-derived the band from `p_exceed_raw` against
the **current** advisory state. Those agree only while the advisory state is unchanged
between export and serve.

On 2026-08-02 they had diverged for 12 beaches. Dillon Beach showed **High on the card and
Low on the detail, both reporting `p_exceed = 0.3`** — and the detail was internally
self-contradictory, since 0.3 is exactly the High cutpoint.

The fix is architectural, not a patch: **one function, called by both paths, that never
reads the stored band.** An advisory floors the probability only while it is actually
active at serve time.

Note the deliberate asymmetry inside the posted branch: the *band* is derived from the
floored model probability (so a posting can never render Low), but the *served
probability* keeps the stored value — because banding the override itself would escalate
a posted beach to Very High off nothing but the posting. Two different numbers, each
correct for its job, with the reason written down.

### Staleness — fail toward warning

```python
staleness_age_hours = age_hours_exact          # un-truncated float
if staleness_age_hours is None:                # legacy row: fall back to forecast_date
    ...
is_stale = (staleness_age_hours is None
            or staleness_age_hours > MAX_FORECAST_AGE_HOURS      # 48
            or (age_hours is None and is_fallback_row))
```

Three things done right:

1. **The un-truncated age feeds the threshold.** The display integer would let a
   48.9-hour-old forecast read as `48` and slip under the cap.
2. **Unknowable age ⇒ stale.** A fallback row with no generation timestamp is flagged
   rather than assumed current.
3. **`forecast_generated_at` is `Optional` and never fabricated.** Filling in "now" for a
   legacy row would make every stale row look fresh and defeat the whole flag.

The record is still **served**, with `is_stale=True` — degrade honestly, never refuse and
never present stale data as current. Web and mobile render three tiers (≤24 h fresh,
24–48 h amber, >48 h/unknown strong warning + greyed band). Advisories are never greyed,
because a county posting doesn't expire just because our model run did.

### Advisory windows judged as-of the snapshot

Advisory active/expired is evaluated against the snapshot's own `generated_at`, not
`datetime('now')`. Otherwise warnings decay out of a stale snapshot while the
model bands in that same snapshot stay put — an asymmetric decay that would quietly
remove the *safety* signal from an old bundle while leaving the *reassuring* one.

---

## 3.5 `api/routes.py` — the HTTP surface

Nine endpoints. The interesting parts are not the routing.

### Dependency wiring

```python
@lru_cache(maxsize=1)
def get_repository() -> BeachRepository:
    return build_repository(get_settings())

def get_service(repository: BeachRepository = Depends(get_repository)) -> BeachService:
    return BeachService(repository)
```

Idiomatic FastAPI: `Depends` for injection, `lru_cache` to make the expensive repository
(which opens a sqlite connection) a singleton, and a cheap per-request service wrapper.
Both are overridable in tests via `app.dependency_overrides`.

### Cache-Control

```python
SNAPSHOT_CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=600"
```

Reduced from 86400. A 24-hour edge TTL kept serving pre-recovery data for a full day
after a stale snapshot was *fixed* — the fix landed and users still saw the broken
version. One hour caps that exposure; `stale-while-revalidate` keeps the edge fast while
it refetches behind the request.

Per-endpoint TTLs are tuned to how deterministic the upstream is: tides get 21600 s
(harmonic predictions are deterministic), hourly weather 10800 s, snapshot data 3600 s.

### `/system/health` — a real health check

Returns **503 with reasons** when:

- `pipeline_freshness` is older than 36 h, or is not a parseable timestamp;
- `model_registry.public_release_eligible` is not `true`;
- `production_metrics` is missing or has no `aucpr`.

Sentinel values (`fixtures-current`, `development`, `unknown`) are skipped so local dev
doesn't red-line. This is a *liveness-plus-correctness* check: a process that is up but
serving an unvalidated model is not healthy, and this endpoint says so. It is also what
`verify_deploy.py` polls to prove a Render build actually shipped.

### The hourly endpoint's two-tier fetch

```python
payload = get_precomputed_hourly(get_settings().curated_dir, lat, lon)
if payload is None:
    payload = await fetch_hourly(lat, lon)
if payload is None:
    raise HTTPException(status_code=502, detail="upstream weather service unavailable")
```

The precomputed snapshot (built by the daily pipeline from a non-throttled IP) is tried
first, because the live per-request Open-Meteo call gets rate-limited from the production
server. Live fetch is the fallback for grid cells the snapshot doesn't cover. A genuine
upstream failure returns **502**, not a fabricated payload.

---

## 3.6 `schemas/domain.py` — the contract

Pydantic v2 models with `Literal` unions for closed enumerations
(`RiskBand`, `SupportStatus`, `ForecastLabelMode`, `SampleRecencyBand`) and `Field`
constraints (`p_exceed: float = Field(ge=0.0, le=1.0)`). The constraints are real:
a probability outside [0,1] fails validation at the boundary rather than rendering as a
nonsense percentage in the app.

**Every optional field carries a comment explaining why it is optional**, and the reason
is almost always backward compatibility with a legacy serving snapshot. That is the
discipline that makes additive schema evolution safe: new fields are `Optional` with
defaults, so an old snapshot and a new API binary coexist.

`sample_recency_band()` is a pure function on the schema module (`fresh` ≤3 d,
`recent` ≤20 d, `stale` ≤60 d, else `very_stale`), so the band definition lives with the
type it annotates rather than being reimplemented in each client.

`ObservationRecord` deliberately exposes `analyte`, `method`, and `units` alongside
`value` — without them a raw enterococcus number is ambiguous (copies/100 mL vs MPN),
which is exactly the confusion that produced the PCR-threshold bug in the pipeline.

---

## 3.7 `services/beach_service.py` — a thin, honest layer

40 lines. Mostly delegation plus deterministic ordering
(`sorted(..., key=lambda b: (b.county, b.name))`), with one piece of real logic:
`explain_forecast` composes a natural-language summary from the top two drivers and
labels itself `used_model="template-v1"`.

That last field matters. It is a template, and the response says so, so a future LLM-backed
explainer can be swapped in and clients can tell the difference. Every generated summary
also ends with *"This is a model estimate, not an official advisory or lab result."*

Some would call this layer redundant. It earns its place here for two reasons: ordering
is a presentation concern that does not belong in a repository, and it gives the future
LLM explainer somewhere to live that is not the HTTP handler.
