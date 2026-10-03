# Static data contract (UPDATE_PLAN 3.2 / 3.3)

Written 2026-10-02 before either side was built, so the backend bake and the mobile reader
are built against the same shapes. Base URL:
`https://kylechoi101.github.io/surf-health/data/` (GitHub Pages; the shorelife-web deploy
publishes it). Every file is the JSON the API route already returns, so a client can swap a
route for a file without changing a type.

| Mobile call today (`shorelife-mobile/lib/api.ts`) | Static file | Shape |
|---|---|---|
| `GET /parent-beaches` | `parent_beaches.json` (exists) | `ParentBeachSummary[]` |
| `GET /beaches` | `beaches.json` (exists) | `BeachSummary[]`, each with `forecast` (`ForecastRecord` for the bake's `forecast_date`, or `null`) |
| `GET /beaches/{id}/forecast?date=D` | `beaches.json[].forecast` | `ForecastRecord`; use it only when `forecast.forecast_date == D`, else call the API |
| `GET /system/health` | `health.json` (new) | `SystemHealthResponse` |
| `GET /beaches/{id}/observations` | `beach/{id}.json` → `observations` (new) | `ObservationResponse` (newest 52 samples, newest first) |
| `GET /beaches/{id}/forecast/explain?date=D` | `beach/{id}.json` → `explain` | `ForecastExplanationResponse`; valid only when `beach/{id}.json.forecast_date == D` |
| `GET /beaches/{id}/hourly` | `beach/{id}.json` → `hourly` | the route's payload (`{"beach_id", ...hourly}`) or `null` when the beach's grid cell is not in `hourly_forecast.parquet` |
| `GET /beaches/{id}/tides` | `beach/{id}.json` → `tides` | the route's payload (`{"beach_id", ...tides}`) or `null` when no NOAA station maps |

`beach/{id}.json` top level: `{"beach_id": str, "forecast_date": "YYYY-MM-DD", "generated_at":
ISO-8601, "observations": ..., "explain": ... | null, "hourly": ... | null, "tides": ... | null}`.
One file per beach in `beaches.json`. (The plan's separate `tides/{station}.json` is folded into
the per-beach file: one request per beach detail screen instead of two.)

**Client rule:** fetch the static file first; on a network error, non-200, or a `null` /
stale section, call the API route as today. The API fallback stays until Render is retired
(UPDATE_PLAN 3.6).

**Parity rule (backend):** a test validates every static payload against the API's pydantic
response models, so the two shapes cannot drift.
