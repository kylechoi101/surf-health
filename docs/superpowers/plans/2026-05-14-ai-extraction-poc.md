# AI-Extraction PoC for Uncovered Counties

**Drafted:** 2026-05-14
**Status:** Scoped — script shipped as PoC, integration pending
**Goal:** Replace fragile/missing scrapers for 6 California counties with an LLM-driven extractor that emits the same `CountyAdvisory` shape as the existing regex scrapers.

## Why

Today's regex scrapers cover 8 of California's 15 coastal counties. The remaining 6 fail in three ways:

| County | Failure mode | What we get today |
|---|---|---|
| Monterey | 403 Forbidden to any UA | Nothing (best-effort fallback fails) |
| Santa Barbara | JS-rendered SPA (CivicPlus) | Nothing |
| San Francisco | JS-rendered SPA (sf.gov) | Nothing |
| Humboldt | No first-class scraper | Slow state-feed only (60-day lag) |
| San Luis Obispo | No first-class scraper | Slow state-feed only |
| Sonoma | No first-class scraper | Slow state-feed only |

A daily-fresh extractor on those 6 would close ~30% of CA's coastal data gap, captured in `OUTREACH_CONTACTS` and in the live audit deficit.

## Approach

For each uncovered county, the loop is:

1. **Fetch** the live page (httpx for static, Playwright for JS-rendered)
2. **Extract** structured advisory data via an LLM with constrained JSON output
3. **Resolve** the extracted beach names to our roster via the existing `StationResolver`
4. **Merge** into `advisories.parquet` via the existing `merge_and_rebuild` (so the
   authoritative-county demotion logic still applies)

The LLM is the differentiator. Regex scrapers break on every page redesign; an LLM extractor reads the page like a human — robust to layout changes as long as the data is visible to the user.

## Free-tier path: GitHub Models

GitHub Models hosts Claude 3.5 Sonnet, GPT-4o, Llama, etc., with a free programmatic tier authenticated via the same `GITHUB_TOKEN` GH Actions already has.

- **Endpoint:** `https://models.inference.ai.azure.com/chat/completions`
- **Free rate limit:** ~15 req/min, 150/day for most models
- **Cost math for our workload:** 6 counties × 8 scrapes/day = 48 calls/day — fits with headroom
- **Auth:** `Bearer $GITHUB_TOKEN` (no extra secret)

If we outgrow the free tier, falling back to Anthropic API direct costs ~$0.20-0.50/day at our volume.

## Deliverable: `backend/scripts/ai_extract_advisories.py`

Shipped today as PoC (not yet wired into production scraper):

- Accepts `--county <name>` and `--url <page>` (or default URL for known counties)
- Optional `--playwright` flag for JS-rendered sites
- Sends HTML + structured-output schema to GitHub Models
- Prints extracted advisories as JSON for inspection
- Same return shape as the existing `fetch_*_advisories` functions so it slots cleanly into `main()` later

## Pilot county: Monterey

Monterey is the highest-leverage starting point:

- **Why:** 403-blocks all our scraper attempts. A normal browser sees the page fine. The county does have current postings — they're just invisible to us.
- **Page:** https://www.countyofmonterey.gov/government/departments-a-h/health/environmental-health/general/public-beaches-water-quality
- **Format:** Standard CivicEngage table, ~15 sampling sites with current status. No JS rendering required for the main content.
- **Validation step:** After PoC runs, manually compare LLM output to the visible page contents on three consecutive days. Only wire into production after that.

## Phases

| Phase | Scope | Done? |
|---|---|---|
| **0** | Script PoC (this commit) | ✓ |
| 1 | Validate Monterey extraction (3 days manual review) | — |
| 2 | Add to `main()` as a new fetcher; ship with existing retry + merge logic | — |
| 3 | Repeat for SB, SF, Humboldt, SLO, Sonoma | — |
| 4 | Add Playwright for JS-rendered pages (SB + SF) | — |

## Phase 0 usage (local test)

```bash
cd /Users/kylechoi/surf_health/backend
export GITHUB_TOKEN=ghp_...   # personal access token w/ models:read
.venv/bin/python scripts/ai_extract_advisories.py \
  --county Monterey \
  --url https://www.countyofmonterey.gov/government/departments-a-h/health/environmental-health/general/public-beaches-water-quality
```

Output: JSON list of `{beach_name, station_code, advisory_type, started_at, cause}` ready to feed into the StationResolver.

## Risks / things to watch

1. **LLM hallucination of stations** — must validate every output against our beach roster. The `StationResolver` already enforces this (any beach_name we can't resolve gets logged but doesn't pollute the parquet).
2. **Rate-limit exhaustion** — GH Models free tier is 150/day. If it fires, we'd fall back to Anthropic API direct. PoC includes the same RetryingClient backoff logic the regex scrapers use.
3. **Cost creep** — if we end up calling on >2 retries per beach × 6 beaches × 8 scrapes = 96 calls/day worst-case. Still under the free tier.
4. **Prompt injection** — county pages don't accept user input, so injection risk is low. We sanitize HTML before passing it to the LLM.

## Out of scope for this iteration

- Replacing the existing 8 regex scrapers with LLM extraction (they work; don't rewrite working systems)
- Multi-language / non-English pages
- Image-based postings (OCR — separate project)
