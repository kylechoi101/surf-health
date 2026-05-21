# Sub-projects G + H: scraper observability + parent-rollup count chip

_Date: 2026-05-21  ·  Status: implementing  ·  Debate: 2026-05-21-scraper-rollup-3opus-debate.md_

## Context

A live-product UX issue ("a lot of Dana Point beaches show advisory")
escalated into a full scope check that surfaced three classes of silent
failure in the advisory pipeline:

1. **Name-resolution drops** — `Salt Creek` from ocbeachinfo.com never
   appeared in `advisories.parquet` because the scraped string didn't
   match any beach_id in our roster; the script silently discarded it.
2. **Auto-demote false negatives** — `Doheny San Juan Creek` was demoted
   active→historical even though the live county still shows it posted,
   because the State Water Board CSV doesn't include it and our merge
   logic preferred the CSV over the per-county scraper.
3. **Stale "active" zombies** — 9 advisories aged 78-226 days still
   flagged active in our data because counties stop renewing without
   formally closing, and our pipeline has no auto-expire.

All daily-forecast workflow runs were exiting 0 despite these issues —
the failures are invisible to a green build. Meanwhile the map +
landing list show "Advisory" on a parent beach whenever ANY of its
1-26 child sampling stations has an active advisory, amplifying both
real advisories AND the silent-failure ghosts into a "lot of beaches
look bad" perception.

3-Opus council voted 8-7 (Borda) for **fix scraper trust first, defer
UX changes until the data is trustworthy**. User accepted the framing
with a pragmatic 14-day window (vs Cassandra's 30) given the product
is already live and labeled "beta forecast."

## Sub-project G — Scraper observability + auto-expire

### G.1 — Name-resolution drops become workflow failures
- `backend/scripts/fetch_county_advisories.py` writes unmatched scraped
  rows to `data/curated/unresolved_advisories.parquet`.
- Workflow exits 1 if `unresolved_count > 5` (absolute) OR
  `unresolved_count / scraped_count > 0.10` (relative).
- Salt-Creek-style silent drops become red builds, not invisible.

### G.2 — 14-day auto-expire for zombie active advisories
- In the bake step, auto-expire `status='active' AND age_days > 14 AND
  advisory_type != 'Chronic Posting'` to `status='historical'`.
- "Chronic Posting" type opts out (counties intentionally leave those
  open at known polluted sites).
- Drops active count by ~10% based on current zombie inventory.

### G.3 — Per-county scraper outranks State CSV on conflict
- When both sources ran successfully AND a beach_id appears in scraper
  results, the scraper's status wins.
- Falls back to CSV only when scraper didn't cover the beach_id at all.
- Fixes the Doheny San Juan Creek demote false-negative.

### G.4 — Audit script becomes a workflow gate
- `scripts/audit_forecasts_vs_advisories.py` already emits JSON.
- Workflow now parses the output and fails if `advisory_age_days > 30`
  count is non-zero (safety net if G.2 auto-expire is somehow bypassed).

## Sub-project H — Parent-rollup count chip

### H.1 — API exposes flagged_station_count
- `ParentBeachSummary.flagged_station_count: int` (number of distinct
  member stations with an active advisory). Optional for backward compat.
- Also `flagged_station_names: list[str]` reserved for future spec I
  (station naming) — NOT rendered on clients yet.

### H.2 — Map + list chip text rule
Apply this rule on every parent-beach chip render (web map + list,
mobile map + list + Today + Browse):

| Condition | Chip text |
|---|---|
| `flagged === total` (every station affected) | `Advisory` |
| `flagged === 1 && total > 1` | `Advisory (1 station)` |
| `flagged < total && total > 1` | `Advisory (N/M)` |
| `flagged_station_count` undefined (old backend) | `Advisory` (unchanged) |

Detail page + parent-station list pages are untouched — those already
have richer per-station UX.

## 14-day auto-checkup (new workflow)

`backend/scripts/scraper_health_check.py` runs daily via
`.github/workflows/scraper-health.yml` (30 min after daily-forecast).
Checks the three G failure modes against the latest committed data,
maintains `data/curated/scraper_health.json`:

```json
{
  "last_checked_utc": "...",
  "alarms_today": [],
  "consecutive_clean_days": 7,
  "streak_target_days": 14,
  "last_alarm_at": null,
  "ready_for_station_naming_spec_i": false
}
```

Any alarm trip → `consecutive_clean_days = 0`. Streak reaches 14 →
`ready_for_station_naming_spec_i = true`, the gate for the next spec.

The workflow itself always exits 0 — alarms are signaled via the
committed JSON, not via workflow status. This is deliberate: we don't
want red workflow runs piling up when the meaningful signal is "are
we ready for the next UX iteration."

## Out of scope (queued for after streak >= 14)

**Spec I — Station naming on map chips.** Rather than `Advisory (4/30)`,
show `Advisory · North Beach Upcoast +3 more`. Requires the underlying
data to be trustworthy enough that naming a specific station won't
embarrass us if the entry is stale or wrong. Gate: query
`scraper_health.json.ready_for_station_naming_spec_i === true`.

## Files

### Backend (modified + new)
- `backend/scripts/fetch_county_advisories.py` (G.1, G.3)
- `backend/scripts/audit_forecasts_vs_advisories.py` (G.4 gate logic)
- `backend/scripts/scraper_health_check.py` (NEW — 14-day streak)
- `backend/app/data/pipeline/...` (G.2 auto-expire in bake step)
- `backend/app/schemas/domain.py` (H.1 flagged_station_count field)
- `backend/app/repositories/curated_repository.py` (H.1 populate)
- `backend/app/repositories/serving_repository.py` (H.1 populate)
- `backend/tests/test_*.py` (new tests for G.1, G.2, G.3, H.1)
- `.github/workflows/daily-forecast.yml` (G.4 gate step)
- `.github/workflows/scraper-health.yml` (NEW)

### Web
- `shorelife-web/lib/api.ts` + `lib/curated.ts` (H.1 type)
- `shorelife-web/components/coastal-map.tsx` (H.2 chip rule)
- `shorelife-web/app/(desktop)/beaches/page.tsx` (H.2 chip rule)

### Mobile (via OTA, no native rebuild)
- `shorelife-mobile/lib/api.ts` (H.1 type — already shipped)
- `shorelife-mobile/app/(tabs)/index.tsx` (H.2 chip rule)
- `shorelife-mobile/app/(tabs)/search.tsx` (H.2)
- `shorelife-mobile/components/ImmersiveCard.tsx` (H.2)
- `shorelife-mobile/components/MapScreen.{ios,android}.tsx` (H.2 docked callout)

## Risks

- G.1 false alarm: if a legitimate new beach gets scraped before our
  roster picks it up, the workflow goes red. Acceptable — that's the
  signal we want; manual triage can either add the beach or whitelist
  the unmatched name.
- G.2 over-aggressive: a legitimate >14d advisory that the county
  actually still posts gets demoted. Mitigation: `Chronic Posting`
  opt-out; clients refresh from county website link anyway.
- G.3 trust shift: if a county scraper breaks silently, beaches it
  used to cover lose advisory data we'd have had from the CSV.
  Mitigation: G.1 alarms catch this (if the scraper drops a previously-
  covered beach_id, the next CSV sync will surface as unresolved or
  the audit gate catches the missing active flag).
- 14-day gate too lenient: if true scraper-quality bugs only manifest
  on bi-weekly county cycles, 14 days might not catch them. Easy to
  bump to 21 or 30 later by changing `STREAK_TARGET_DAYS` constant.
