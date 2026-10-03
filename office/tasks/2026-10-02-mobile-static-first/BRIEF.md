---
task: mobile-static-first
repo: /Users/kylechoi/shorelife-mobile
worker: cursor
created: 2026-10-02
status: open
---

## Goal

UPDATE_PLAN step 3.3. The mobile app reads the daily snapshot from static files on GitHub
Pages first and falls back to the Render API only when a file is missing, stale or
unreachable. This removes the app's dependence on the Render API (which can hang 5–30 s on a
cold start) for everything that is a daily snapshot. The file shapes are fixed by
`/Users/kylechoi/surf_health/docs/STATIC_DATA_CONTRACT.md` — read it first; it is the spec.
The backend side that produces `health.json` and `beach/{id}.json` is being built in parallel;
until it ships those files 404 and the app must keep working through the API fallback.

## In scope

1. New pure module `lib/staticData.ts` (no React Native imports, so `node --test` can load
   it; `fetch` injectable for tests):
   - `STATIC_BASE = process.env.EXPO_PUBLIC_STATIC_URL ?? "https://kylechoi101.github.io/surf-health/data"`.
   - `fetchStatic<T>(path, { fetchImpl, timeoutMs })` → `T | null` (null on network error,
     timeout, non-200, or invalid JSON; never throws).
   - An in-memory per-session cache of `beaches.json` (one request per app session; a failed
     fetch is NOT cached, so the next call retries).
   - `staticForecast(beaches, id, date)` → the `forecast` of that beach only if
     `forecast.forecast_date === date`, else null.
   - `beachDetail(id)` → the parsed `beach/{id}.json` or null, cached per session per id; and
     section accessors that return null when the section is null or when
     `detail.forecast_date !== date` for the date-scoped `explain` section.
2. Wire `lib/api.ts`: `getParentBeaches`, `getBeaches`, `getSystemHealth`, `getForecast`,
   `getForecastExplanation` (whatever the existing names are), `getObservations`,
   `getHourly`, `getTides` each try the static source first and fall back to the existing
   `request<T>(path)` call unchanged. Keep `API_BASE`, `request`, retries, `ApiError` and
   the cache-age helpers exactly as they are. `getForecast` must not trigger a second
   `beaches.json` download — use the session cache.
3. Tests `tests/static-data.test.mjs` (import `../lib/staticData.ts`, inject a fake fetch):
   static hit returns the file's data; 404 / network error / bad JSON → null (so the caller
   falls back); `beaches.json` fetched once across many calls; a failed `beaches.json` fetch is
   retried next time; forecast date mismatch → null; explain section date mismatch → null;
   `null` hourly/tides sections → null; `EXPO_PUBLIC_STATIC_URL` override respected.

## Out of scope

- Any native change: no new native packages, no `app.json` plugin/permission changes, no
  `runtimeVersion` / version bump (the app is already 1.3.31 > the plan's 1.3.29). This must
  ship as an EAS OTA update, which requires an unchanged native fingerprint.
- Running `eas update`, `eas build` or `eas submit`, or pushing — the PM ships after the
  backend files are live.
- UI changes, copy changes, removing the API fallback (that is plan step 3.6).
- The `main` branch: work on the current branch `feat/dual-mode` (the release branch).

## Allowed files

- lib/staticData.ts
- lib/api.ts
- tests/static-data.test.mjs

## Allowed packages

- none

## Acceptance

```bash
cd /Users/kylechoi/shorelife-mobile
npm test            # all tests pass (27 test files before this task)
npm run typecheck   # clean
npm run lint        # no new errors
npx expo-doctor 2>/dev/null | tail -3 || true   # informational
```

## Phases

### Phase 25
Deliverable: `lib/staticData.ts` with `fetchStatic`, `STATIC_BASE`, the session cache, and its tests for hit/miss/error/once-per-session.

### Phase 50
Deliverable: `staticForecast` and `beachDetail` + section accessors with the date rules, tested.

### Phase 75
Deliverable: `lib/api.ts` wired static-first for all eight getters with the unchanged API fallback; typecheck clean.

### Phase 100
Deliverable: all Acceptance commands pass, outputs pasted, and a short note listing each getter and which static file/section it now reads.

## Corrections

(appended by the PM; newest last; each entry dated)
