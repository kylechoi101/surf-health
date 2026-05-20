# Sub-project F: Surfline-parity Tier 1 (free features)

_Date: 2026-05-20  ·  Status: implementing_

## Context

User asked: "can we do whatever Surfline does?" Answer (from the dissection):
the visible 90% is replicable with public data sources at ~$0/mo marginal
cost. The 10% that isn't replicable is the capital moat (HD cams, human
reporter network, LOTUS-class spot-specific ML calibration on 25yr of
historical reports). This spec covers ALL the free pieces.

Out of scope: cams, narrative reports, LOTUS-class model, smart-cam ML.
Those would require capital + multi-year data corpora.

## Features (all derivable from free public sources)

### F.1 Backend — extend `/hourly` with multi-swell + weather codes

`app/services/hourly_weather.py`:
- Bump `forecast_days` 2 → 7 (Open-Meteo supports 16; pick 7 for chart
  width balance).
- Add `weathercode` to forecast hourly params.
- Add wave partition to marine hourly params: `wind_wave_*`,
  `swell_wave_*`, `secondary_swell_wave_*`.
- Parse into response as `weather_code`, `wind_wave_height_m`,
  `primary_swell_*`, `secondary_swell_*` (renamed for surf-app clarity).
- Additive — existing fields unchanged.

### F.2 Backend — new `/beaches/{id}/tides` endpoint

NEW `app/services/tides.py`:
- NOAA CO-OPS connector (`api.tidesandcurrents.noaa.gov`). Free, no auth.
- Hardcoded CA tide station list (~20-25 stations from Crescent City to
  San Diego). Nearest by haversine.
- 24-hour TTL cache (tides are deterministic predictions; no need to
  re-fetch within a day).
- Returns dense predictions + sparse high/low extrema.

NEW route in `app/api/routes.py`:
- `GET /beaches/{beach_id}/tides` with
  `Cache-Control: public, max-age=21600, stale-while-revalidate=3600`.

### F.3 Frontend — TideChart component

`shorelife-web/components/TideChart.tsx` + mirror in mobile.
- Curve of tide height over 24h with high/low extrema dots.
- Station name + distance in caption.

### F.4 Frontend — SwellComponentsRow

Display up to 3 swell components (primary + secondary + wind wave).
Format: "2.2ft @ 12s S". Filter components below noise floor.

### F.5 Frontend — AstronomyRow

Pure client computation via `suncalc` (tiny, no deps). First light /
Sunrise / Sunset / Last light from lat/lon/date.

### F.6 Frontend — WeatherStrip

3-hourly weather strip for 24h. WMO code → unicode glyph mapping.

### F.7 Frontend — SurfRatingChip

POOR · FAIR · GOOD · EPIC chip from a pure rule engine over wave height,
period, wind speed, and (when available) wind-direction-vs-shore-normal.

### F.8 Frontend — Derived metrics (wave energy + consistency)

`lib/surf-metrics.ts`:
- `waveEnergyKJ(heightM, periodS)`: classical deep-water wave energy
  formula. Surfline shows this as "131 kJ".
- `consistencyScore(periodSeries, windowHours=6)`: 100 − normalized
  stdev of period over rolling window. Surfline shows this as "39/100".

Rendered as a sub-line on the existing Wave Height MetricRow.

## Files

### Backend (1 modified, 2-3 new)
- `app/services/hourly_weather.py` (modified — new fields + horizon)
- `app/api/routes.py` (modified — new /tides route)
- `app/services/tides.py` (new)
- `tests/test_tides.py` (new)

### Web (~7 new components + integration)
- `components/TideChart.tsx`
- `components/SwellComponentsRow.tsx`
- `components/AstronomyRow.tsx`
- `components/WeatherStrip.tsx`
- `components/SurfRatingChip.tsx`
- `lib/surf-metrics.ts`
- `lib/api.ts` (modified — new types + getTides)
- `app/(desktop)/beaches/[id]/BeachDetail.tsx` (modified — integration)
- `package.json` (modified — add `suncalc` dep)

### Mobile (mirrored set)
- `components/TideChart.tsx`
- `components/SwellComponentsRow.tsx`
- `components/AstronomyRow.tsx`
- `components/WeatherStrip.tsx`
- `components/SurfRatingChip.tsx`
- `lib/surf-metrics.ts`
- `lib/api.ts` (modified)
- `app/beach/[id]/detail.tsx` (modified)
- `package.json` (modified — add `suncalc`)

## Out of scope

- HD live cams (capital moat — $$$$)
- Human surf reporter narratives (labor cost)
- LOTUS-class proprietary nearshore wave model (years of R&D, requires
  ground-truth corpus we don't have)
- Smart Cam ML (requires cams first)
- LLM-generated narrative summaries (technically <$5/mo but not strictly
  "free"; defer to a future spec)
- Backend `shore_normal_deg` exposure (frontend computes onshore/offshore
  approximately from cardinal; backend addition deferred)

## Risks

- Open-Meteo Marine API doesn't always return swell partition fields for
  all global coordinates. If missing, frontend gracefully falls back to
  dominant-wave-only display.
- NOAA CO-OPS has rate limits (~10k req/day soft); 24h TTL cache plus
  Cache-Control header makes this comfortable headroom.
- 7-day forecast horizon makes the hourly response payload larger
  (~3.5× current). Cache-Control on /hourly already handles repeat hits;
  cold-start payload size goes from ~30 KB to ~110 KB — acceptable.

## Capacity impact

`/tides` adds 1 fresh NOAA call per beach per 24h. At 330 beaches:
330 calls/day vs NOAA's ~10k/day soft limit. Headroom is 30×. Combined
with the v0.2.0/1.3.17 Open-Meteo TTL bump, total upstream footprint
stays well under all free-tier ceilings.
