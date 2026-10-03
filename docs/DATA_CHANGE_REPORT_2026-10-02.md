# Data change report — 2026-10-02

`docs/UPDATE_PLAN.md` step 1.6. Three snapshots of `data/curated/`, same forecast date
(2026-10-02), compared by `backend/scripts/data_change_report.py`:

- **ci** — what the daily workflow committed on 2026-10-02 (`e5a826fe7`) and Render serves.
- **before** — today's `main` code, built locally from pinned raw inputs.
- **after** — branch `feat/update-plan-phase1` (UPDATE_PLAN 1.1–1.5), built locally from the
  same pinned inputs, the same CEDEN pull, the same package set, and the same starting state.

Both local builds ran the CI chain (pipeline → advisories → stormwater → training
`--winner-only` without spatial backtests → `lookup_serving` → advisory expiry → re-serve). Neither
had `GITHUB_TOKEN`, so the Humboldt / Sonoma / San Luis Obispo LLM scrapers are skipped in both;
the workflow fix for them is only exercised in CI.

| | ci | before | after |
|---|---|---|---|
| observations rows | 508,296 | 508,315 | 497,106 |
| beach_day rows | 496,649 | 496,665 | 491,700 |
| enterococcus beach-days, last 365 d | 27,100 | 27,116 | 27,420 |
| positive labels, last 365 d (culture / ddPCR) | 2,399 / 2,460 | 2,402 / 2,460 | 2,341 / 2,379 |
| beaches served (production) | 375 (374) | 375 (374) | 496 (495) |
| served: Orange | 0 | 0 | 125 |
| served: Monterey | 0 | 0 | 0 |
| served: San Diego | 97 | 97 | 94 |
| served: Los Angeles | 88 | 88 | 88 |
| served: San Francisco | 17 | 17 | 17 |
| served: Santa Barbara | 16 | 16 | 16 |
| median sample age of served beaches (d) | 4 | 4 | 4 |
| advisories resolved | 59 | 60 | 90 |
| unresolved (unexpected / total) | 3 / 7 | 0 / 4 | 0 / 5 |
| county scrapers with an error | 9 | 8 | 4 |
| known gaps (no public source) | — | — | Monterey |

## Local vs served

`before` reproduces `ci` closely: same 375 served beaches, +19 observation rows, +3 culture
positives, same median age. 7 of 375 served bands differ, all from fetch timing (advisory scrape
17:38 local vs 20:32 CI; the live feed returned 41 fewer `BeachWatch.Live` and 59 more
`BeachWatch.SafeToSwim` rows). The before→after deltas below are therefore code effects, and
the absolute "after" numbers are a fair preview of what CI would publish.

## What changed, and why

- **Observations −11,209.** Two effects. (a) 10,790 SafeToSwim rows carried the wrong `beach_id`
  — a neighbouring station's — because `ceden.py`'s crosswalk matched CEDEN station codes against
  station *names* and fell back to nearest-within-0.5 km. They are re-bound to their own
  station, where most then collapse with that station's own state row. (b) The canonical
  sample key collapses 12,182 physical duplicates (one sample reported by several state
  mirrors, or by SF's county feed and later by the state). +816 Orange County samples from
  `ocbeachinfo.com`'s results spreadsheet (gap-fill only; 1,647 already held by the state).
- **Positive labels, last 365 d: 4,862 → 4,720.** Removing neighbour samples from beaches that
  never took them deletes phantom positives; OC adds new culture beach-days at a low rate. The
  ddPCR count falls (2,460 → 2,379) because most of the mis-bound rows were San Diego.
- **Served +121.** Orange County returns: 125 beaches whose newest sample (2026-09-11, from the
  county spreadsheet) is inside the 30-day serving gate. 4 beaches leave, and should — each
  had been served purely from a neighbour's samples:
  | beach | its own newest sample | served from |
  |---|---|---|
  | San Elijo SB EH-403 | 2004-06-30 | EH-400 |
  | Tourmaline Surfing Park EH-255 | 2018-10-31 | FM-030 |
  | Silver Strand SB IB-069 | 2026-01-31 | IB-070 |
  | Keller Mid Beach (EBRPD) | 2011-11-28 | Keller South Beach |
- **Advisories resolved 60 → 90; unexpected unresolved 0.** San Diego, San Mateo and Santa
  Barbara scrapers fixed; OC parses again with diagnostics if CI's copy differs; Ventura prose
  fragments no longer reach the resolver. Two wrong-beach resolutions found in review and
  corrected via alias rows: "Newport Bay - Bayside Drive Beach" (was Newport Beach BGC, is BNB33)
  and "Dana Point Harbor - All of Baby Beach" (was Doheny DSB5U, is BDP12–15).
- **Scraper errors 8 → 4.** Remaining: Los Angeles (informational: no warnings in window) and
  Humboldt / Sonoma / San Luis Obispo (no `GITHUB_TOKEN` locally — fixed in the workflow).
  Monterey is no longer an error: it is reported as a known gap (`no_public_source`), see below.

## Checks

| check (UPDATE_PLAN) | result |
|---|---|
| 1.1 groups with >1 row on the canonical key | 3,712 — above the plan's "a few hundred"; all are same-source different-value pairs kept on purpose (e.g. Enterolert + MF the same day) |
| 1.2 `label_method` two values, SD share | no nulls (473,970 culture / 17,730 ddpcr); last 365 d San Diego 4,022 of 6,583 beach-days ddpcr, 1 ddpcr beach-day outside SD; 42 of 496 served rows ddpcr; never a model input (test-pinned) |
| 1.3 resolve vs suggest resolved counts equal | 90 = 90, 0 heuristic hits after review |
| 1.4 OC beaches in `forecasts.parquet` | yes, 125 |
| 1.4 newest OC sample = newest in the county's latest spreadsheet (amended check) | **PASS**: 2026-09-11 = 2026-09-11; per station 178 of 180 equal, 2 newer from a state row (Laguna WESTD/WESTU, Feb), 0 older |
| 1.5 no scraper error for the listed counties | SD, OC, San Mateo, Santa Barbara clear; Monterey reported as no public source (not an error); Humboldt/Sonoma/SLO need the CI token |
| 1.6 `pytest -q` no worse than 0.1 | 781 passed / 0 failed (baseline 718 / 0) |
| 1.6 `validate_forecast.py` after vs before | PASS: 496 rows, p_exceed [0.0039, 0.9641], 359 distinct |

## Orange County: freshness, posting cadence, what the forecast can do with it

- **The connector already helped.** Through the state routes, OC's newest sample was 2026-08-24
  (39 days old on 10-02). Through the county's own spreadsheet it is 2026-09-11 (21 days).
- **Posting cadence**, from the county's WordPress media library (every results spreadsheet
  since 2020; full-year compilations excluded): median days between uploads **20 (2023), 36
  (2024), 21 (2025)**; p90 25 / 43 / 34; worst gap 84. Each file is current when posted: the
  newest sample was 1, 2 and 4 days old at the three 2026 uploads (08-11, 08-27, 09-15). In
  2026 there was no interim upload between 03-26 and 08-11 — while the state routes still
  carried OC — so the 2026 cadence is three data points.
- **Beaches will drop in and out of the forecast.** The serving gate is 30 days, so the 09-11
  samples keep OC served through about 10-11. If the next spreadsheet arrives on the 2025
  cadence (~21 days after 09-15, i.e. around 10-06), OC never drops. On the 2024 cadence
  (~36 days), OC is unserved for a few days each cycle — roughly (36 − 30 + lag) / 36 ≈ 20% of
  days. Whether OC needs a county-specific gate depends on which cadence the county is on now;
  re-measure after the next two uploads before changing the gate.
- **The connector depends on a file name that has changed three times** (`Historical-Data-…`
  through 2025, `Orange-County-Data-2026-Compiled` in March, `Orange-County-Beach-Monitoring-
  Data-…` since August). Listing uploads through the WordPress media API
  (`/wp-json/wp/v2/media?search=…`, sorted by date) would survive the next rename.
- **What the forecast does with three-week-old data.** On the after snapshot, unfloored OC
  forecasts track each beach's 12-month record at correlation 0.967 — the same 0.967 as the
  rest of the state, and the served logistic scales the record by about 0.45 in both. So OC is
  not an outlier: the served model leans on the yearly record everywhere, and for OC the last
  test reaches the forecast only through the persistence floor (6 of 125 beaches, last test
  exceeded → never Low), never through the freshness term. That is the honest answer with data
  this old; OC forecasts will not move with a test until the county posts it.
