"""Fetch county-direct beach advisories and override stale state-feed records.

California's data.ca.gov BeachWatch dataset is refreshed on a slow cadence
(currently ~60 days stale for status changes). County health-department
websites publish current postings same-day. This script pulls those direct
sources and overrides the state-feed active records in advisories.parquet
so the pipeline downstream of this (training feature, audit, serving) sees
the real current state.

Today it covers San Diego County via sdbeachinfo.com. The structure is
designed for easy addition of OC (ocbeachinfo.com), LA (publichealth.lacounty.gov
beach-grades), and SF Bay (sfdph.org) — each county is one parser function
returning a list of CountyAdvisory records.

Run after the state-feed normalization step in the daily-forecast pipeline:
    python scripts/fetch_county_advisories.py --curated ../data/curated/
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import httpx

UA = "Shorelife/1.0 (+https://github.com/kylechoi101/surf-health)"
SD_HOMEPAGE = "https://www.sdbeachinfo.com/"
SD_GETDATA = "https://www.sdbeachinfo.com/Home/GetData"


@dataclass
class CountyAdvisory:
    """A live posting from a county health-department source."""

    county: str
    station_code: str  # e.g. "FM-070"
    area: str
    advisory_type: str  # "Posting", "Closure", "Chronic Posting"
    started_at: pd.Timestamp
    advisory_website: str
    cause: str | None = None


def _clean_html_text(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = (
        s.replace("&nbsp;", " ")
        .replace("&#39;", "'")
        .replace("&amp;", "&")
        .replace("'", "'")
        .replace("’", "'")
    )
    return re.sub(r"\s+", " ", s).strip()


def _parse_san_diego_date(date_str: str) -> pd.Timestamp | None:
    """Parse 'May 12, 2026' or 'September 1997' (chronic-no-day) formats."""
    date_str = date_str.strip()
    for fmt in ("%B %d, %Y", "%B %d %Y", "%B %Y"):
        try:
            return pd.Timestamp(datetime.strptime(date_str, fmt), tz="UTC")
        except ValueError:
            continue
    return None


def fetch_san_diego_advisories(client: httpx.Client) -> list[CountyAdvisory]:
    """Scrape sdbeachinfo.com /Home/GetData?name=_AdvisoryPartialView for
    every currently-listed advisory. This is the County of San Diego DEH's
    own page, served by their internal Beach Water Quality system — the
    authoritative source for SD postings, refreshed within hours of
    sampling lab results."""
    resp = client.post(
        SD_GETDATA,
        data={"name": "_AdvisoryPartialView"},
        headers={
            "User-Agent": UA,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": SD_HOMEPAGE,
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    html = resp.text

    advisories: list[CountyAdvisory] = []
    for li in re.findall(r"<li>(.*?)</li>", html, re.DOTALL):
        text = _clean_html_text(li)
        if "Status Since" not in text:
            continue
        m_type = re.match(r"^(Advisory|Closure|Chronic Advisory)\s*:", text)
        if not m_type:
            continue
        ui_type = m_type.group(1)
        # Normalize to our advisory_type column vocabulary
        if ui_type == "Closure":
            adv_type = "Closure"
        elif ui_type == "Chronic Advisory":
            adv_type = "Chronic Posting"
        else:
            adv_type = "Posting"

        m_code = re.search(r"\(([A-Z]{2,4}-\d{2,4})\)", text)
        if not m_code:
            continue
        station_code = m_code.group(1)

        m_date = re.search(
            r"Status Since\s*:\s*([A-Za-z]+\s+\d+,?\s*\d{4}|[A-Za-z]+\s+\d{4})",
            text,
        )
        if not m_date:
            continue
        started_at = _parse_san_diego_date(m_date.group(1))
        if started_at is None:
            continue

        m_area = re.search(
            r"^(?:Advisory|Closure|Chronic Advisory)\s*:\s*(.+?)\s*Station\s*:",
            text,
        )
        area = m_area.group(1).strip() if m_area else ""

        # Cause guess: text after the date often has a phrase like
        # "Bacteria levels exceed health standards"
        cause = None
        if "exceed" in text.lower():
            cause = "Bacterial Standards Violation"
        elif "tijuana" in text.lower():
            cause = "Other - Tijuana River Associated"

        advisories.append(
            CountyAdvisory(
                county="San Diego",
                station_code=station_code,
                area=area,
                advisory_type=adv_type,
                started_at=started_at,
                advisory_website=SD_HOMEPAGE,
                cause=cause,
            )
        )

    return advisories


def merge_into_advisories_parquet(
    county_advisories: list[CountyAdvisory],
    curated_dir: Path,
) -> tuple[int, int]:
    """Overwrite the state-feed's `active` records for any beach mentioned by
    a county-direct source. Returns (n_added, n_demoted)."""
    if not county_advisories:
        return (0, 0)

    advisories = pd.read_parquet(curated_dir / "advisories.parquet")
    beaches = pd.read_parquet(curated_dir / "beaches.parquet")

    # Resolve each county station_code to our beach_id (suffix match)
    beach_ids: dict[str, str] = {}
    counties_covered: set[str] = set()
    for ca in county_advisories:
        code_lower = ca.station_code.lower()
        match = beaches[beaches["beach_id"].str.endswith(code_lower)]
        if match.empty:
            print(
                f"  [skip] no matching beach_id for {ca.station_code}",
                file=sys.stderr,
            )
            continue
        beach_ids[ca.station_code] = str(match.iloc[0]["beach_id"])
        counties_covered.add(ca.county)

    # Demote any existing `active` record for the covered beaches — the state
    # feed for those is stale; county-direct is the truth.
    keep_mask = ~(
        advisories["beach_id"].isin(beach_ids.values())
        & (advisories["status"] == "active")
    )
    n_demoted = int((~keep_mask).sum())
    base = advisories.loc[keep_mask].copy()

    # Construct new records and append
    new_rows = []
    for ca in county_advisories:
        if ca.station_code not in beach_ids:
            continue
        new_rows.append(
            {
                "beach_id": beach_ids[ca.station_code],
                "advisory_type": ca.advisory_type,
                "started_at": ca.started_at.tz_localize(None)
                if ca.started_at.tzinfo is not None
                else ca.started_at,
                "ended_at": pd.NaT,
                "status": "active",
                "cause": ca.cause,
                "county": ca.county,
                "advisory_website": ca.advisory_website,
            }
        )

    if not new_rows:
        return (0, n_demoted)

    new_df = pd.DataFrame(new_rows)
    # Align column dtypes/order with the existing parquet
    for col in advisories.columns:
        if col not in new_df.columns:
            new_df[col] = None
    new_df = new_df[advisories.columns]

    combined = pd.concat([base, new_df], ignore_index=True)
    combined.to_parquet(curated_dir / "advisories.parquet", index=False)
    return (len(new_rows), n_demoted)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--curated",
        type=Path,
        default=Path(__file__).resolve().parent.parent.parent / "data" / "curated",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + parse but don't modify advisories.parquet",
    )
    args = parser.parse_args()

    if not args.curated.exists():
        print(f"curated dir not found: {args.curated}", file=sys.stderr)
        return 1

    print("Fetching San Diego County advisories from sdbeachinfo.com ...")
    try:
        with httpx.Client(follow_redirects=True) as client:
            sd = fetch_san_diego_advisories(client)
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return 1
    print(f"  parsed {len(sd)} live advisories")
    for ca in sd:
        print(
            f"    {ca.advisory_type:18s}  {ca.station_code:8s}  "
            f"{ca.started_at.date().isoformat():12s}  "
            f"{ca.area[:40]}"
        )

    if args.dry_run:
        print("\n[dry-run] not modifying advisories.parquet")
        return 0

    added, demoted = merge_into_advisories_parquet(sd, args.curated)
    print(
        f"\nMerged into {args.curated / 'advisories.parquet'}: "
        f"added {added}, demoted {demoted} stale state records"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
