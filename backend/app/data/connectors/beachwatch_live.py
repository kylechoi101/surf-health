"""Live BeachWatch monitoring-results connector.

The data.ca.gov CKAN export everyone treats as "the BeachWatch feed" is a *file
dump* and it is frozen: as of 2026-07-29 its newest ``SampleDate`` is 2026-03-05,
~5 months stale. The database behind it is current — the State Water Board's own
"Monitoring Data Search" page (``search_beach_mon.html``) iframes a live PHP app
at ``beachwatch.waterboards.ca.gov/public/result.php`` which queries it directly.

Measured gap on 2026-07-29 (enterococcus only), live app vs what we had ingested:

    county        live newest   ours   behind   Jul rows (live/ours)
    Los Angeles   2026-07-27    07-23    4d      440 /  71   (16%)
    San Diego     2026-07-26    07-20    6d      511 / 100   (20%)
    Ventura       2026-07-21    07-21    0d      117 / 114   (97%)

So this is ADDITIVE, not a replacement. Statewide the live app exposes 605
stations of which 602 already match ``beaches.parquet.station_code`` (3 new),
while 247 of our stations do not appear in it at all, and for historical years
our merged BeachWatch+CEDEN observations hold ~15% MORE rows than it does. Its
one advantage is recency in the high-frequency counties (San Diego's near-daily
ddPCR, Los Angeles), which is exactly where the serving anchor is stalest.

Access shape:
  * POST ``result.php`` with ``County`` (numeric code), ``year``, and optionally
    ``created`` = results *entered* within the last N days (1/7/30/60/90) — the
    cheap incremental handle, since the lab→publish lag is what we are chasing.
  * Response is an HTML table; there is no JSON API.
  * Station identity is the ``Station Name`` column, which matches our
    ``station_code`` exactly — we join through it rather than re-deriving
    ``beach_id``, because the live app does NOT return ``USEPAID`` (the slug
    input) and re-deriving would orphan every row from its history.
"""

from __future__ import annotations

import html as _html
import re
import time
from dataclasses import dataclass

import httpx
import pandas as pd

RESULT_URL = "https://beachwatch.waterboards.ca.gov/public/result.php"
REFERER = "https://www.waterboards.ca.gov/water_issues/programs/beaches/search_beach_mon.html"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# County dropdown values scraped from the live form. "Water Boards" (20) returns
# no monitoring rows; kept for completeness so a caller iterating ALL sees it.
COUNTY_CODES: dict[str, int] = {
    "Humboldt": 3,
    "Long Beach City": 4,
    "Los Angeles": 5,
    "Marin": 6,
    "Mendocino": 7,
    "Monterey": 8,
    "Orange": 9,
    "San Diego": 10,
    "San Francisco": 11,
    "San Luis Obispo": 12,
    "San Mateo": 13,
    "Santa Barbara": 14,
    "Santa Cruz": 15,
    "Sonoma": 16,
    "Ventura": 17,
    "East Bay Parks District": 19,
}

# Columns of the results table, in order.
_TABLE_COLUMNS = [
    "station_code", "sample_date", "sample_time_raw", "parameter", "qualifier",
    "result", "unit", "method", "county", "station_description",
    "latitude", "longitude", "beach_name",
]

# The site sits behind Incapsula; keep request rate conversational. A full
# backfill is 16 counties x N years, so this dominates wall-clock by design.
_DEFAULT_DELAY_S = 2.0
_TIMEOUT_S = 180.0

_ROW_RE = re.compile(r"<tr>\s*(<td class=\"tab-data\".*?)</tr>", re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class FetchResult:
    frame: pd.DataFrame
    county: str
    year: int | None
    created_days: int | None


def _text(cell: str) -> str:
    return _html.unescape(_TAG_RE.sub("", cell)).strip()


def parse_results_html(markup: str) -> pd.DataFrame:
    """Parse the result.php table into a raw frame (no typing, no filtering)."""
    rows = []
    for block in _ROW_RE.findall(markup):
        cells = [_text(c) for c in _CELL_RE.findall(block)]
        if len(cells) >= len(_TABLE_COLUMNS):
            rows.append(cells[: len(_TABLE_COLUMNS)])
    return pd.DataFrame(rows, columns=_TABLE_COLUMNS)


def fetch_county(
    county: str,
    *,
    year: int | None = None,
    created_days: int | None = None,
    client: httpx.Client | None = None,
) -> pd.DataFrame:
    """One county's results. Pass ``year`` for backfill, ``created_days`` for daily.

    ``created_days`` filters on when the lab result was ENTERED (not sampled), so
    it captures late-arriving backfill for older sample dates — which is the whole
    point: on 2026-07-24 we held 47 of 2026-07-20's samples, and 85 four days later.
    """
    if county not in COUNTY_CODES:
        raise ValueError(f"unknown county {county!r}; expected one of {sorted(COUNTY_CODES)}")
    payload = {
        "County": str(COUNTY_CODES[county]),
        "year": str(year) if year else "",
        "stationID": "",
        "parameter": "",
        "qualifier": "",
        "method": "",
        "created": str(created_days) if created_days else "",
        "sort": "SampleDate",
        "sortOrder": "DESC",
        "submit": "Search",
    }
    headers = {"User-Agent": USER_AGENT, "Referer": REFERER}
    owned = client is None
    client = client or httpx.Client(timeout=_TIMEOUT_S, follow_redirects=True)
    try:
        response = client.post(RESULT_URL, data=payload, headers=headers)
        response.raise_for_status()
        return parse_results_html(response.text)
    finally:
        if owned:
            client.close()


def fetch_all(
    *,
    counties: list[str] | None = None,
    year: int | None = None,
    created_days: int | None = None,
    delay_s: float = _DEFAULT_DELAY_S,
    on_progress=None,
) -> pd.DataFrame:
    """Every county for one (year | created_days) slice, concatenated.

    A county that errors is skipped with a warning rather than failing the run —
    this feeds a daily refresh, and one flaky county must not cost the other 15.
    """
    counties = counties or list(COUNTY_CODES)
    frames: list[pd.DataFrame] = []
    with httpx.Client(timeout=_TIMEOUT_S, follow_redirects=True) as client:
        for index, county in enumerate(counties):
            try:
                frame = fetch_county(
                    county, year=year, created_days=created_days, client=client
                )
            except Exception as exc:  # noqa: BLE001 - one county must not sink the run
                print(f"[beachwatch-live] {county}: FAILED ({type(exc).__name__}: {exc})")
                continue
            if on_progress:
                on_progress(county, len(frame))
            frames.append(frame)
            if index < len(counties) - 1 and delay_s:
                time.sleep(delay_s)
    if not frames:
        return pd.DataFrame(columns=_TABLE_COLUMNS)
    return pd.concat(frames, ignore_index=True)
