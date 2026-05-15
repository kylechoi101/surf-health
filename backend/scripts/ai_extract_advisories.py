"""Extract beach water-quality advisories from any county page via LLM.

Bridges the gap for counties our regex scrapers can't handle today:
- Monterey (returns 403 to direct scrapes)
- Santa Barbara, San Francisco (JS-rendered SPAs)
- Humboldt, SLO, Sonoma (no first-class scraper)

Uses GitHub Models (free tier) by default — same GITHUB_TOKEN that GH
Actions has. Returns advisories in the same shape as the existing
fetch_*_advisories() functions so it plugs cleanly into the merge path
later.

PoC mode (this commit): prints extracted JSON to stdout for manual
review. NOT yet wired into production scraping. Validate output by
hand for 3 consecutive days before promoting to the live pipeline.

Usage:
    export GITHUB_TOKEN=ghp_xxx   # needs `models:read` scope
    python scripts/ai_extract_advisories.py \\
        --county Monterey \\
        --url https://www.countyofmonterey.gov/.../public-beaches-water-quality
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx

# Optional: only required for JS-rendered pages (SB, SF). For static pages
# (Monterey, Humboldt, SLO, Sonoma) we can use plain httpx.
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)

# GitHub Models endpoint. Auth: Bearer $GITHUB_TOKEN with models:read scope.
# Endpoint migrated from models.inference.ai.azure.com → models.github.ai
# in late 2025.
GH_MODELS_ENDPOINT = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"  # Cheap, fast, strong at structured extraction

# Known county pages — verified URLs as of 2026-05-14.
#
# Each entry: (url, use_playwright)
# Counties not listed here have their own structured/JSON feed and
# should be ingested directly, not via LLM extraction:
#
#   San Francisco → data.sfgov.org Socrata API (resource v3fv-x3ux)
#                   Returns ENTERO/COLI_FECAL/COLI_TOTAL/COLI_E samples
#                   as JSON. Direct ingest is better than scraping.
#
KNOWN_COUNTY_URLS = {
    "Santa Barbara": (
        # JS-rendered CivicPlus dashboard
        "https://www.countyofsb.org/2263/Ocean-Water-Monitoring-Program",
        True,
    ),
    "Monterey": (
        # 403 to httpx — needs Playwright to bypass the WAF
        "https://www.countyofmonterey.gov/government/departments-a-h/health/"
        "environmental-health/general/public-beaches-water-quality",
        True,
    ),
    "Humboldt": (
        # Static CivicPlus page; enterococcus + MPN values inline
        "https://humboldtgov.org/1696/Water-Quality-Test-Results",
        False,
    ),
    "San Luis Obispo": (
        # ArcGIS Online dashboard; underlying feature service not yet
        # discovered. Playwright needed to render the dashboard, OR
        # query the AGO item REST API directly (future work).
        "https://slocounty.maps.arcgis.com/apps/dashboards/0693b6f43f444995afc3f90d29b81432",
        True,
    ),
    "Sonoma": (
        # Static page with enterococcus / coliform / sample-results text
        "https://sonomacounty.gov/health-and-human-services/health-services/"
        "divisions/public-health/environmental-health/programs-and-services/"
        "ocean-water-quality",
        False,
    ),
}

# San Francisco gets its own first-class path (no LLM):
# https://data.sfgov.org/resource/v3fv-x3ux.json — enterococcus samples
SF_SOCRATA_RESOURCE_ID = "v3fv-x3ux"


def fetch_page(url: str, use_playwright: bool, timeout: float = 30.0) -> str:
    """Fetch raw HTML. Playwright path waits for network-idle so JS content
    finishes loading. Static path is a single GET with browser UA."""
    if use_playwright:
        if not HAS_PLAYWRIGHT:
            raise RuntimeError("Playwright required for JS-rendered pages. Install with: pip install playwright && playwright install chromium")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=_BROWSER_UA)
            page = ctx.new_page()
            page.goto(url, wait_until="networkidle", timeout=int(timeout * 1000))
            html = page.content()
            browser.close()
            return html
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        resp = client.get(url, headers={"User-Agent": _BROWSER_UA})
        resp.raise_for_status()
        return resp.text


def trim_html(html: str, max_chars: int = 50000) -> str:
    """Strip scripts/styles + collapse whitespace so the LLM gets the
    visible content, not the page's CSS/JS chrome. Caps length so we
    don't blow the model context."""
    html = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style\b[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # Strip HTML tags but keep text content
    text = re.sub(r"<[^>]+>", " ", html)
    # Decode common entities
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


SCHEMA_INSTRUCTION = """\
Extract the list of beach advisories / closures CURRENTLY POSTED on this
California county environmental-health page. For each currently-posted
beach, return:
  - beach_name (string, as listed on the page)
  - station_code (string or null) — any per-station ID like "EH-050" or "B-5"
  - advisory_type (one of "Posting", "Closure", "Rain Advisory", "Chronic Posting")
  - started_at (ISO date "YYYY-MM-DD" or null if not shown)
  - cause (string or null, e.g., "Bacterial Standards Violation", "Sewage Spill", "Rain")

CRITICAL: Only include beaches that are CURRENTLY POSTED. Do NOT include
historical postings, FAQ examples, or all-clear sentinels. If the page says
"no current advisories" or similar, return an empty list.

Output strictly as JSON: {"advisories": [...]}. No prose, no markdown.
"""


def extract_via_github_models(text: str, county: str, model: str = DEFAULT_MODEL) -> list[dict]:
    """Call GitHub Models with a structured-output prompt; return the
    parsed list of advisory dicts."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN env var required (PAT with models:read or GH Actions default token)")

    system = (
        "You are a precise data-extraction agent for beach water quality. "
        "You return JSON only — no commentary."
    )
    user = (
        f"County: {county}\n\n"
        f"Page text:\n{text}\n\n"
        f"{SCHEMA_INSTRUCTION}"
    )

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            GH_MODELS_ENDPOINT,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.0,  # deterministic extraction
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        body = resp.json()

    content = body["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        raise RuntimeError(f"LLM returned non-JSON content:\n{content[:500]}")

    return parsed.get("advisories", [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--county", required=True, help="County name (e.g. 'Monterey')")
    parser.add_argument("--url", help="Override the county URL (defaults to KNOWN_COUNTY_URLS)")
    parser.add_argument("--playwright", action="store_true", help="Force Playwright (for JS pages)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="GitHub Models model name")
    parser.add_argument("--out", type=Path, help="Optional: write extracted JSON to this file")
    args = parser.parse_args()

    # Resolve URL
    url = args.url
    use_playwright = args.playwright
    if not url:
        if args.county not in KNOWN_COUNTY_URLS:
            print(f"Unknown county: {args.county}. Pass --url explicitly.", file=sys.stderr)
            return 1
        url, default_playwright = KNOWN_COUNTY_URLS[args.county]
        if url is None:
            print(
                f"County {args.county!r} has no verified URL yet.\n"
                f"  Pass --url <verified_url> to test extraction manually.",
                file=sys.stderr,
            )
            return 1
        use_playwright = use_playwright or default_playwright

    print(f"Fetching {url} (playwright={use_playwright})...", file=sys.stderr)
    html = fetch_page(url, use_playwright)
    text = trim_html(html)
    print(f"  page text: {len(text)} chars", file=sys.stderr)

    print(f"Extracting via GitHub Models ({args.model})...", file=sys.stderr)
    advisories = extract_via_github_models(text, args.county, args.model)
    print(f"  found {len(advisories)} advisories", file=sys.stderr)

    out_payload = {
        "county": args.county,
        "source_url": url,
        "extracted_at": datetime.utcnow().isoformat() + "Z",
        "model": args.model,
        "advisories": advisories,
    }
    text_out = json.dumps(out_payload, indent=2)
    if args.out:
        args.out.write_text(text_out)
        print(f"  wrote {args.out}", file=sys.stderr)
    print(text_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
