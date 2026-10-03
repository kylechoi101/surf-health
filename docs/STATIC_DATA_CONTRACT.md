# Static data contract (UPDATE_PLAN 3.2 / 3.3)

Written 2026-10-02 before either side was built, so the backend bake and the mobile reader
are built against the same shapes. Base URL:
`https://kylechoi101.github.io/surf-health/data/` (GitHub Pages; the shorelife-web deploy
publishes it). Every file under **`api/`** is the JSON the API route already returns, so a client
can swap a route for a file without changing a type.

*Amended 2026-10-02 (before anything shipped):* the existing top-level `beaches.json` /
`parent_beaches.json` are the **web's** flat shapes (`id`, `latitude`, …), not the API's
`BeachSummary` (`geometry`, …). They stay as they are for the web; API-shaped copies live under
`api/`.

| Mobile call today (`shorelife-mobile/lib/api.ts`) | Static file | Shape |
|---|---|---|
| `GET /parent-beaches` | `api/parent_beaches.json` | `ParentBeachSummary[]` |
| `GET /beaches` | `api/beaches.json` | `BeachSummary[]`, each with an extra `forecast` key (`ForecastRecord` for the bake's `forecast_date`, or `null`) |
| `GET /beaches/{id}/forecast?date=D` | `api/beaches.json[].forecast` | `ForecastRecord`; use it only when `forecast.forecast_date == D`, else call the API |
| `GET /system/health` | `api/health.json` | `SystemHealthResponse` |
| `GET /beaches/{id}/observations` | `api/beach/{id}.json` → `observations` (new) | `ObservationResponse` (newest 52 samples, newest first) |
| `GET /beaches/{id}/forecast/explain?date=D` | `api/beach/{id}.json` → `explain` | `ForecastExplanationResponse`; valid only when `api/beach/{id}.json.forecast_date == D` |
| `GET /beaches/{id}/hourly` | `api/beach/{id}.json` → `hourly` | the route's payload (`{"beach_id", ...hourly}`) or `null` when the beach's grid cell is not in `hourly_forecast.parquet` |
| `GET /beaches/{id}/tides` | `api/beach/{id}.json` → `tides` | the route's payload (`{"beach_id", ...tides}`) or `null` when no NOAA station maps |

`api/beach/{id}.json` top level: `{"beach_id": str, "forecast_date": "YYYY-MM-DD", "generated_at":
ISO-8601, "observations": ..., "explain": ... | null, "hourly": ... | null, "tides": ... | null}`.
One file per beach in `api/beaches.json`. (The plan's separate `tides/{station}.json` is folded into
the per-beach file: one request per beach detail screen instead of two.)

**Client rule:** fetch the static file first; on a network error, non-200, or a `null` /
stale section, call the API route as today. The API fallback stays until Render is retired
(UPDATE_PLAN 3.6).

**Parity rule (backend):** a test validates every static payload against the API's pydantic
response models, so the two shapes cannot drift.
