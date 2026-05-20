# Sub-projects A–E: Web bacteria/naming + backend capacity + interactive forecast + mini-map + mobile redesign

_Date: 2026-05-19  ·  Status: approved for implementation_

## Context

User-reported multi-feature ask spanning web, mobile, and backend. This spec
covers two independent sub-projects that can ship as parallel PRs in the same
session. Other sub-projects (interactive forecast, mini-map, mobile redesign)
are queued for separate specs.

Concurrent-capacity rationale comes from a 5-agent claude_space debate
transcript at `docs/superpowers/research/2026-05-19-concurrent-capacity-debate.md`.
Borda winner: Cassandra's analysis — current ceiling ≈ 7-14 concurrent users,
bound by Open-Meteo's 10k/day quota.

## Sub-project A: Web bacteria + beach naming

### Symptoms

1. "Black's Beach" beach detail page shows "Unable to load beach data —
   please try again." for users navigating to the production `ca922367-…fm-090`
   record.
2. Web detail page does not surface bacteria probability (`p_exceed`) or
   the analyte name/units, even though both are in the API response.
3. Beach names don't match Google Maps or surfer conventions — there are
   two duplicate `FM-090` records and the displayed parent name
   ("Torrey Pines City Beach") is not what surfers call the spot.

### Root cause

`shorelife-web/app/(desktop)/beaches/[id]/BeachDetail.tsx:81-91` fires
`getForecast`, `getObservations`, and `getHourly` in parallel and sets
`fetchError = true` whenever **any** of them fail. For Black's Beach the
forecast loads (production record has a model) but observations 404 (the
sample data lives under the sibling unsupported `ca785240-…fm-090` record),
which trips the error screen unconditionally. Same pattern in `BeachSharePage.tsx:101`.

### Approach (Approach 1 — UI-only, approved)

Three thin changes per app, one PR per app:

**A.1 Tolerant fetch error handling**
- Only `forecast` failures route to the error screen. Observations or hourly
  failures degrade gracefully (page renders without that section).

**A.2 Surface bacteria fields already in the API**
- Render `p_exceed` as a percentage in the risk card.
- Render `analyte` name + `units` in the recent-samples table rows.

**A.3 Frontend surfer-name alias overlay**
- New file `lib/beach-aliases.ts` mirrored in both web and mobile.
- Constant table: `{ beach_id: { surfer_name, source } }`.
- Seed with ~5-10 famous SoCal/NorCal spots (Black's, Trestles, Rincon,
  Windansea, Sunset Cliffs, Steamer Lane).
- `getDisplayName(beach_id, official)` returns `{ primary, subtitle? }`.
- Detail h1 renders `primary`; official `name` shown as small subtitle when
  an alias exists.

### Files touched (web)

- `shorelife-web/app/(desktop)/beaches/[id]/BeachDetail.tsx`
- `shorelife-web/app/b/[id]/BeachSharePage.tsx`
- `shorelife-web/lib/beach-aliases.ts` (new)

### Files touched (mobile)

- `shorelife-mobile/lib/beach-aliases.ts` (new — mirrored copy)
- `shorelife-mobile/app/beach/[id]/detail.tsx` (h1 + alias only this pass)

### Out of scope

- Mobile bacteria-field surfacing and mobile error-gate work → sub-project E
  (Mobile UI redesign).
- Backend dedupe of the duplicate FM-090 records → future data-curation spec.

## Sub-project B: Backend capacity lift

### Goal

Lift the concurrent-user ceiling from ~7-14 to ~150+ for $0/month, this week.

### Bottleneck (verified)

- Open-Meteo unauthenticated quota = 10,000 calls/day = 0.116 calls/sec.
- One `/hourly` call per beach view → Little's Law N = λW gives 7-14
  simultaneous users at 60-120s sessions.
- Render's 0.1 vCPU would only bind at ~20-25 req/s — 200× headroom over
  the rate limit.
- In-memory caches normally die on Render free's 15-min cold start, but the
  user already runs a 5-min cron ping that keeps the container warm.

### Approach

**B.1 Bump existing TTL cache from 1h to 3h**
- `app/services/hourly_weather.py` already has a hand-rolled module-scope
  TTL cache keyed by `(round(lat, 1), round(lon, 1))`. Change
  `_CACHE_TTL_SECONDS = 60 * 60` to `60 * 60 * 3`. Update the docstring
  to match the new cadence. No new dependency.
- The existing cache is `dict`-backed; module-scope; correct for a
  single-worker uvicorn. The debate's `functools.lru_cache` concern does
  not apply (this code already does it the right way).

**B.2 Cache-Control headers on read endpoints**
- `/beaches/{id}/hourly`: `public, max-age=10800, stale-while-revalidate=3600`.
- `/beaches/{id}/forecast`: `public, max-age=86400` (SQLite baked into image).
- Sets up free Cloudflare edge cache later (the 100x path) with no further
  code change.

**B.3 No keep-alive ping needed**
- User confirmed an existing 5-min cron handles Render's sleep behavior.

### Capacity math (post-fix)

- Open-Meteo calls drop from 1/session to ~8/beach/day → 400/day at 50
  beaches → 25× under quota.
- Bottleneck shifts to Render CPU → 20-25 req/s → **~150-700 concurrent**
  users at typical session lengths.

### Files touched

- `surf_health/backend/app/services/hourly_weather.py` (TTL bump + comment)
- `surf_health/backend/app/api/routes.py` (Cache-Control headers)

### Out of scope

- Cloudflare CDN in front of Render (separate effort if 100x path is needed).
- Redis (only needed if in-process cache + cron isn't enough).
- Render Starter tier upgrade.

## Sub-project C: Interactive forecast + wind + language + source disclosure (web)

### Symptoms

- Hourly chart shows static 72-hour single series — surfers want to scrub
  through nearby hours like Surfline.
- `wind_direction_deg` is in the API but never rendered.
- Labels use "tempo", "modeled exceedance", "STV" — biostatistical not
  surfer language.
- Wave height/period source (Open-Meteo Marine model) is not disclosed,
  so users assume buoy.

### Approach

**C.1 IntraDayChart interactive ±8h cursor**
- Add `mode: "full" | "compact"` prop. Compact clips visible range to ±8h
  from now (16-hour window).
- Add touch + mouse handlers for a draggable vertical cursor + tooltip
  showing hour and value. Snap to nearest hour.
- Reserved `extraSeries?` prop for future stacked overlays — added but not
  wired up this pass.

**C.2 Wind direction renderer**
- `components/WindRose.tsx` — small SVG compass with 4-point ticks + arrow
  rotated by `degrees + 180` (Open-Meteo convention is "from").
- Cardinal text below ("Wind from NW").
- Inline in the Wind Speed card.

**C.3 Open-Meteo source disclosure**
- New row in the Station Metadata sidebar: "Wave source: Open-Meteo Marine
  model (not a buoy)".

**C.4 Surfer-language sweep**
- `lib/forecastPresentation.ts`: replace risk-band copy with plain-English
  ("Low chance of high bacteria today" etc.). Keep "beta forecast" label
  (accurate and meaningful).

### Files touched (web)

- `components/IntraDayChart.tsx`
- `components/WindRose.tsx` (new)
- `app/(desktop)/beaches/[id]/BeachDetail.tsx`
- `lib/forecastPresentation.ts`

### Out of scope

- Stacked multi-metric overlays (prop reserved, not enabled).
- Backend `shore_normal_wind_ms` exposure (compass-direction approach
  works without it; revisit if onshore/offshore becomes a clear ask).
- NDBC buoy integration (separate spec).

## Sub-project D: Mini-map inset on beach detail (web)

### Approach

OSM iframe embed at the top of the right column in `BeachDetail.tsx`.
Zero new dependencies. ~200px tall, with a "View larger →" link to
openstreetmap.org centered on the beach.

### Files touched (web)

- `app/(desktop)/beaches/[id]/BeachDetail.tsx` (right column addition)

### Out of scope

- Mapbox / Leaflet / interactive zoom-pan map (iframe is good enough for
  an inset; user can click through for a real map).
- Multi-beach map showing nearby stations (sub-project for later).

## Sub-project E: Mobile UI redesign (mirror C+D + finish A pieces)

### Scope

E is the mobile half of what C/D shipped on web, plus the bacteria/error
pieces deferred from sub-project A.

### Approach

**E.1 Finish deferred A pieces (mobile)**
- `app/beach/[id]/detail.tsx`: render `p_exceed` percentage under the band
  label; show analyte name + units + result in the recent-observations
  caption; replace silent `return null` on missing beach with a friendly
  "Beach not found" view.

**E.2 Surfer-language sweep (mobile)**
- "Wave Tempo" → "Wave Period".
- "exceed STV of 104" → "exceed the EPA 104 limit".
- Mirror the forecastPresentation.ts strings if a mobile copy exists.

**E.3 WindRose.tsx (mobile)**
- Mirror the web component using `react-native-svg`. Same `degrees + 180`
  convention. Same `cardinalFromDegrees()`.
- Pass as `accessory` prop to the Wind Speed GridCard.

**E.4 IntraDayChart ±8h cursor (mobile)**
- Same `mode` prop. Add `PanResponder` for the draggable cursor; layer
  user-cursor over the existing "now" dashed marker.

**E.5 MapInset (mobile)**
- Platform-split: `MapInset.ios.tsx` (react-native-maps), `MapInset.android.tsx`
  (MapLibre). Mirrors the existing `MapScreen.{ios,android}.tsx` pattern.
- Non-interactive: scroll/zoom/pan disabled. Single marker at the beach
  coord, region delta ≈ 0.015°.
- Rendered under the hero block in `detail.tsx`.

**E.6 Mini-forecast docked on map screen**
- When a marker is tapped on the map tab, render a card pinned to the
  bottom of the map screen (above the tab bar via safe-area inset).
- Card shows: beach name, risk chip, wave height, wind speed + cardinal,
  "View detail →" button.
- Dismissible (× or tap-outside).

### Files touched (mobile)

- `app/beach/[id]/detail.tsx`
- `components/IntraDayChart.tsx`
- `components/WindRose.tsx` (new)
- `components/MapInset.ios.tsx` (new)
- `components/MapInset.android.tsx` (new)
- `app/(tabs)/map.tsx` (or current map route — file confirmed during
  implementation) for the docked mini-forecast.
- `lib/forecastPresentation.ts` (if present)

### Out of scope

- Wholesale visual redesign (the user said "redesign", but this pass
  is functional parity with web + the deferred A pieces; a deeper
  visual revamp can be its own spec).
- Tablet / iPad layouts.

## Cross-cutting

### Error handling

A: Forecast failure → error screen (unchanged). Observations failure →
render the page without the recent-samples block, small inline
"Recent samples unavailable" note. Alias miss → fall through to official
`beach.name`.

B: First request per (lat,lon) after TTL expiry → upstream Open-Meteo
fetch (~400ms). Subsequent within 3h → in-memory hit (<1ms). Upstream
error with no cache → existing HTTPException path.

### Testing

A: Manual — load Black's Beach URL, verify page renders even when
observations 404. Unit test for `getDisplayName`. Visual confirmation
of `p_exceed` and analyte rendering.

B: `tests/test_hourly_cache.py` — mock the upstream HTTP call, invoke
twice, assert one upstream call. Verify TTL expiry triggers re-fetch.

### Sequencing

Parallel: A is `shorelife-web` + `shorelife-mobile`, B is `surf_health`.
No file overlap. Separate commits/PRs per repo.

## Risks

- A: Alias table drift between web and mobile. Mitigation: keep the seed
  set tiny (≤10 entries) so it's trivially audited. Long-term: promote to
  backend-curated CSV (deferred per user choice).
- B: 3h staleness on the "current conditions" reading is the cost of
  caching. Open-Meteo model updates 4×/day; staleness is ≤3h. Surf
  conditions don't shift faster.
- B: Cache key is `(lat,lon)` rounded to 0.01°. Two beaches within ~1 km
  share a cache entry. This is intentional (less load on Open-Meteo) and
  semantically correct (same upstream cell).
