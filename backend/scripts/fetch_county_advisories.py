"""Fetch county-direct beach advisories and override stale state-feed records.

California's data.ca.gov BeachWatch dataset is refreshed on a slow cadence
(metadata_modified ~60 days stale for status changes). County health-department
websites publish current postings same-day. This script pulls county-direct
sources, overrides the state-feed `active` records in advisories.parquet,
AND rebuilds the advisory-derived columns in beach_day.parquet so the
training feature (advisory_active_prev_14d) reflects the same fresh state.

Each county is a (station_lookup_fn, advisory_parser_fn) pair. Name→station
code resolution is hybrid:
  1. Auto-built from beaches.parquet (county-filtered station_code + beach_name)
  2. Static alias CSV in _static_data/county_beach_name_to_station.csv
  3. rapidfuzz fuzzy fallback (≥0.90, gap≥0.20 vs runner-up, same county)

Per-run telemetry written to data/curated/county_advisories_report.json.

Run after the state-feed normalization step in the daily-forecast pipeline:
    python scripts/fetch_county_advisories.py --curated ../data/curated/
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

try:
    from rapidfuzz import fuzz, process
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

UA = "Shorelife/1.0 (+https://github.com/kylechoi101/surf-health)"
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)


# ---------- Data classes ---------- #


@dataclass
class CountyAdvisory:
    county: str
    station_code: str | None  # may be None if only beach name available
    area: str
    advisory_type: str  # "Posting" | "Closure" | "Chronic Posting"
    started_at: pd.Timestamp
    advisory_website: str
    cause: str | None = None
    # populated after resolution
    beach_id: str | None = None


@dataclass
class CountyReport:
    county: str
    success: bool
    last_attempted_at: str
    source_url: str
    stations_in_lookup: int = 0
    advisories_parsed: int = 0
    matched_via_live_list: int = 0
    matched_via_csv: int = 0
    matched_via_fuzzy: int = 0
    unmatched_names: list[str] = field(default_factory=list)
    error: str | None = None


# ---------- Common parsing utilities ---------- #


def _clean_html_text(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    replacements = {
        "&nbsp;": " ",
        "&#39;": "'",
        "&#8217;": "'",
        "&#8211;": "-",
        "&#8212;": "-",
        "&amp;": "&",
        "&quot;": '"',
        "'": "'",
        "’": "'",
        "–": "-",
        "—": "-",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    return re.sub(r"\s+", " ", s).strip()


def _normalize_name(name: str) -> str:
    """Normalize beach name for matching: lowercase, strip punctuation,
    collapse whitespace, drop noise tokens."""
    n = name.lower()
    n = re.sub(r"[^\w\s-]", " ", n)
    # Drop common location qualifiers that don't help disambiguate
    drop = {"the", "at", "near", "beach", "creek", "channel", "bay", "point", "park", "state"}
    tokens = [t for t in n.split() if t and t not in drop]
    return " ".join(tokens).strip()


def _parse_us_date(date_str: str) -> pd.Timestamp | None:
    """Robust date parser for various US formats county pages use."""
    s = date_str.strip()
    for fmt in (
        "%B %d, %Y", "%B %d %Y", "%B %Y",
        "%m/%d/%Y", "%m/%d/%y", "%-m/%-d/%Y",
        "%Y-%m-%d", "%m-%d-%Y",
        "%A, %B %d, %Y",
    ):
        try:
            return pd.Timestamp(datetime.strptime(s, fmt))
        except ValueError:
            continue
    return None


# ---------- Hybrid name→station resolver ---------- #


_STATIC_ALIAS_CSV = (
    Path(__file__).resolve().parent.parent
    / "app" / "data" / "pipeline" / "_static_data"
    / "county_beach_name_to_station.csv"
)


class StationResolver:
    """Resolve a (county, beach_name) tuple to a beach_id using:
    Layer A — live county station_lookup (passed in per-county)
    Layer B — static alias CSV (county, beach_name_normalized → station_code)
    Layer C — rapidfuzz against the live county station_lookup
    """

    def __init__(self, beaches: pd.DataFrame) -> None:
        self.beaches = beaches
        # Build per-county lookup: { county: { normalized_name: beach_id } }
        self._beach_name_lookup: dict[str, dict[str, str]] = {}
        for cnty, grp in beaches.groupby("county"):
            self._beach_name_lookup[str(cnty)] = {
                _normalize_name(str(row["beach_name"])): str(row["beach_id"])
                for _, row in grp.iterrows()
                if row.get("beach_name")
            }
        # Per-county station_code → beach_id
        self._station_code_lookup: dict[str, dict[str, str]] = {}
        for cnty, grp in beaches.groupby("county"):
            self._station_code_lookup[str(cnty)] = {
                str(row["station_code"]).upper(): str(row["beach_id"])
                for _, row in grp.iterrows()
                if row.get("station_code")
            }
        # Static alias CSV
        self._alias_lookup: dict[tuple[str, str], str] = {}
        if _STATIC_ALIAS_CSV.exists():
            try:
                alias_df = pd.read_csv(_STATIC_ALIAS_CSV)
                for _, row in alias_df.iterrows():
                    key = (str(row["county"]), _normalize_name(str(row["beach_name_normalized"])))
                    self._alias_lookup[key] = str(row.get("beach_id") or row.get("station_code") or "")
            except Exception as e:
                print(f"  [resolver] could not load alias CSV: {e}", file=sys.stderr)

    def resolve_by_station_code(self, county: str, station_code: str) -> tuple[str | None, str]:
        """Direct station_code lookup. Returns (beach_id, match_kind)."""
        code = station_code.upper()
        bid = self._station_code_lookup.get(county, {}).get(code)
        if bid:
            return bid, "station_code"
        # Suffix-match fallback for codes with slight format differences
        code_lower = station_code.lower()
        for cnty_codes in self._station_code_lookup.values():
            for bid_full in cnty_codes.values():
                if bid_full.endswith(code_lower):
                    return bid_full, "station_code_suffix"
        return None, "miss"

    def resolve_by_name(self, county: str, beach_name: str) -> tuple[str | None, str]:
        """Hybrid name resolution. Returns (beach_id, match_kind)."""
        norm = _normalize_name(beach_name)
        if not norm:
            return None, "miss"

        # Layer A: live county lookup (exact normalized match)
        county_lookup = self._beach_name_lookup.get(county, {})
        if norm in county_lookup:
            return county_lookup[norm], "live_list"
        # Layer A.1: substring match either direction
        for key, bid in county_lookup.items():
            if norm in key or key in norm:
                # Require minimum overlap to avoid "venice" matching everything
                if len(norm) >= 4 and len(key) >= 4:
                    return bid, "live_list"

        # Layer B: alias CSV
        bid = self._alias_lookup.get((county, norm))
        if bid:
            # If CSV gave a station_code, translate to beach_id
            if not bid.startswith("ca"):
                resolved, _ = self.resolve_by_station_code(county, bid)
                if resolved:
                    return resolved, "csv"
            else:
                return bid, "csv"

        # Layer C: fuzzy match (only if rapidfuzz available)
        if HAS_RAPIDFUZZ and county_lookup:
            candidates = list(county_lookup.keys())
            top = process.extract(norm, candidates, scorer=fuzz.token_set_ratio, limit=2)
            if top and top[0][1] >= 90:
                if len(top) == 1 or (top[0][1] - top[1][1] >= 20):
                    return county_lookup[top[0][0]], "fuzzy"

        return None, "miss"


# ---------- San Diego (sdbeachinfo.com) ---------- #


SD_HOMEPAGE = "https://www.sdbeachinfo.com/"
SD_GETDATA = "https://www.sdbeachinfo.com/Home/GetData"


def fetch_san_diego_advisories(client: httpx.Client, resolver: StationResolver) -> tuple[list[CountyAdvisory], CountyReport]:
    """Scrape sdbeachinfo.com /Home/GetData?name=_AdvisoryPartialView."""
    rpt = CountyReport(
        county="San Diego",
        success=False,
        last_attempted_at=datetime.now(timezone.utc).isoformat(),
        source_url=SD_HOMEPAGE,
    )
    rpt.stations_in_lookup = len(resolver._station_code_lookup.get("San Diego", {}))
    try:
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
    except Exception as e:
        rpt.error = f"fetch failed: {e}"
        return [], rpt

    advisories: list[CountyAdvisory] = []
    for li in re.findall(r"<li>(.*?)</li>", html, re.DOTALL):
        text = _clean_html_text(li)
        if "Status Since" not in text:
            continue
        m_type = re.match(r"^(Advisory|Closure|Chronic Advisory)\s*:", text)
        if not m_type:
            continue
        ui_type = m_type.group(1)
        adv_type = (
            "Closure" if ui_type == "Closure"
            else "Chronic Posting" if ui_type == "Chronic Advisory"
            else "Posting"
        )
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
        started_at = _parse_us_date(m_date.group(1))
        if started_at is None:
            continue
        m_area = re.search(
            r"^(?:Advisory|Closure|Chronic Advisory)\s*:\s*(.+?)\s*Station\s*:",
            text,
        )
        area = m_area.group(1).strip() if m_area else ""
        cause = None
        if "tijuana" in text.lower():
            cause = "Other - Tijuana River Associated"
        elif "exceed" in text.lower():
            cause = "Bacterial Standards Violation"
        advisories.append(CountyAdvisory(
            county="San Diego",
            station_code=station_code,
            area=area,
            advisory_type=adv_type,
            started_at=started_at,
            advisory_website=SD_HOMEPAGE,
            cause=cause,
        ))
    rpt.success = True
    rpt.advisories_parsed = len(advisories)
    return advisories, rpt


# ---------- Orange County (ocbeachinfo.com) ---------- #


OC_HOMEPAGE = "https://www.ocbeachinfo.com/"


def fetch_orange_county_advisories(client: httpx.Client, resolver: StationResolver) -> tuple[list[CountyAdvisory], CountyReport]:
    """Scrape ocbeachinfo.com homepage which lists current
    CLOSURES / WARNINGS / ADVISORIES sections inline."""
    rpt = CountyReport(
        county="Orange",
        success=False,
        last_attempted_at=datetime.now(timezone.utc).isoformat(),
        source_url=OC_HOMEPAGE,
    )
    rpt.stations_in_lookup = len(resolver._beach_name_lookup.get("Orange", {}))
    try:
        resp = client.get(OC_HOMEPAGE, headers={"User-Agent": _BROWSER_UA}, timeout=30.0)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        rpt.error = f"fetch failed: {e}"
        return [], rpt

    text = _clean_html_text(html)
    # Section boundaries
    sections = {"Closure": None, "Posting": None}
    m_cl = re.search(r"CLOSURES\s*:?", text, re.IGNORECASE)
    m_wr = re.search(r"WARNINGS\s*:?", text, re.IGNORECASE)
    m_ad = re.search(r"ADVISORIES\s*:?", text, re.IGNORECASE)
    if not (m_cl and m_wr and m_ad):
        rpt.error = "expected section markers (CLOSURES/WARNINGS/ADVISORIES) not all found"
        return [], rpt
    sections["Closure"] = (m_cl.end(), m_wr.start())
    sections["Posting"] = (m_wr.end(), m_ad.start())

    advisories: list[CountyAdvisory] = []
    for adv_type, (s, e) in sections.items():
        chunk = text[s:e]
        # Skip if "currently in effect" → "No ocean, harbor, or bay water X currently in effect."
        if re.search(r"No (ocean|water).{0,80}currently in effect", chunk, re.IGNORECASE):
            continue
        # Each posting: "<area or full description> (posted on M/D/YYYY)" or "(updated on M/D/YYYY)"
        # Allow descriptions starting with digits (e.g., "33rd Street Channel") AND uppercase.
        for m in re.finditer(
            r"([\dA-Z][^.()]+?)\s*\((?:posted|updated)\s+on\s+(\d{1,2}/\d{1,2}/\d{2,4})\)",
            chunk,
        ):
            description = m.group(1).strip(" -:")
            date_str = m.group(2)
            started_at = _parse_us_date(date_str)
            if started_at is None:
                continue
            advisories.append(CountyAdvisory(
                county="Orange",
                station_code=None,
                area=description,
                advisory_type=adv_type,
                started_at=started_at,
                advisory_website=OC_HOMEPAGE,
                cause="Bacterial Standards Violation",
            ))
    rpt.success = True
    rpt.advisories_parsed = len(advisories)
    return advisories, rpt


# ---------- San Mateo County ---------- #


SM_HOMEPAGE = "https://www.smchealth.org/beaches"


def fetch_san_mateo_advisories(client: httpx.Client, resolver: StationResolver) -> tuple[list[CountyAdvisory], CountyReport]:
    rpt = CountyReport(
        county="San Mateo",
        success=False,
        last_attempted_at=datetime.now(timezone.utc).isoformat(),
        source_url=SM_HOMEPAGE,
    )
    rpt.stations_in_lookup = len(resolver._beach_name_lookup.get("San Mateo", {}))
    try:
        resp = client.get(SM_HOMEPAGE, headers={"User-Agent": _BROWSER_UA}, timeout=30.0)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        rpt.error = f"fetch failed: {e}"
        return [], rpt

    # SM's page lists posted beaches as short <br>-separated lines (Linda Mar #5,
    # Pillar Point #7, Dunes Beach, etc.) — within an advisory-list section that
    # is preceded by markers like "currently posted" / "contaminated" and that
    # contains the literal list of beach names.
    text = _clean_html_text(html)
    m_upd = re.search(r"(?:updated|last updated)\s*[:on]*\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})", text, re.IGNORECASE)
    page_date = _parse_us_date(m_upd.group(1)) if m_upd else None
    if page_date is None:
        page_date = pd.Timestamp.now().normalize()

    advisories: list[CountyAdvisory] = []
    san_mateo_beaches = resolver._beach_name_lookup.get("San Mateo", {})

    # Split the FULL page into <br>-separated lines and scan every line that's
    # short enough to be a beach-name entry (not a paragraph of FAQ prose).
    # Build a combined lookup keyed by NORMALIZED station_code AND beach_name.
    # The live SM page posts by station_code ("Linda Mar #5", "Pillar Point #7"),
    # not by parent beach_name ("Pacifica State Beach", "Pillar Point Harbor"),
    # so station_code is what we need to match. Also normalize the line text
    # itself so "#5" maps to "5" — without this, "linda mar 5" never substring-
    # matches "linda mar #5 (at san pedro creek)".
    sm_lookup: dict[str, str] = {}
    for norm_name, bid in san_mateo_beaches.items():
        if len(norm_name) >= 6:
            sm_lookup[norm_name] = bid
    for code, bid in resolver._station_code_lookup.get("San Mateo", {}).items():
        norm_code = _normalize_name(code)
        if len(norm_code) >= 4:
            sm_lookup.setdefault(norm_code, bid)
    # Also honor the static alias CSV — same county-specific keys the
    # other counties' resolvers use. Catches semantic mismatches like
    # "Fitzgerald Marine Reserve" → moss-beach station.
    for (cnty, norm_alias), aid in resolver._alias_lookup.items():
        if cnty != "San Mateo":
            continue
        if not aid or aid == "nan":
            continue
        if aid.startswith("ca") and len(norm_alias) >= 4:
            sm_lookup.setdefault(norm_alias, aid)

    lines = re.split(r"<br\s*/?>|</p>|</li>", html, flags=re.IGNORECASE)
    seen = set()
    for raw_line in lines:
        line_text = _clean_html_text(raw_line)
        if not (4 < len(line_text) < 80):
            continue
        # Discard lines that are clearly FAQ prose
        word_count = len(line_text.split())
        if word_count > 12:
            continue
        norm_line = _normalize_name(line_text)
        if not norm_line:
            continue
        # Prefer longer matches (catches "linda mar 5" before "linda mar")
        for lookup_key in sorted(sm_lookup, key=len, reverse=True):
            beach_id = sm_lookup[lookup_key]
            if lookup_key in norm_line and beach_id not in seen:
                seen.add(beach_id)
                advisories.append(CountyAdvisory(
                    county="San Mateo",
                    station_code=None,
                    area=line_text[:60],
                    advisory_type="Posting",
                    started_at=page_date,
                    advisory_website=SM_HOMEPAGE,
                    cause="Bacterial Standards Violation",
                    beach_id=beach_id,
                ))
                break

    rpt.success = True
    rpt.advisories_parsed = len(advisories)
    return advisories, rpt


# ---------- Los Angeles County ---------- #


LA_HOMEPAGE = "http://publichealth.lacounty.gov/phcommon/public/eh/water_quality/beach_grades.cfm"


def fetch_la_county_advisories(client: httpx.Client, resolver: StationResolver) -> tuple[list[CountyAdvisory], CountyReport]:
    """LA County publishes ocean-water advisories as press releases linked from
    publichealth.lacounty.gov/.../beach_grades.cfm. Each press release contains
    a structured 'BEACH AREA WARNINGS:' section with bulleted beach names
    (using middle-dot '·' as the bullet marker). We follow the most recent
    press-release link and parse those bullets."""
    rpt = CountyReport(
        county="Los Angeles",
        success=False,
        last_attempted_at=datetime.now(timezone.utc).isoformat(),
        source_url=LA_HOMEPAGE,
    )
    rpt.stations_in_lookup = len(resolver._beach_name_lookup.get("Los Angeles", {}))
    try:
        resp = client.get(LA_HOMEPAGE, headers={"User-Agent": _BROWSER_UA}, timeout=30.0)
        resp.raise_for_status()
        index_html = resp.text
    except Exception as e:
        rpt.error = f"index fetch failed: {e}"
        return [], rpt

    # The index page truncates each press release after "...." then links to a
    # full detail page at mediapubhpdetail.cfm?prid=N. We need to follow the
    # link(s) to get the full bulleted list. The date appears in a
    # <span class="pressTitle"> AFTER the link.
    #
    # Index structure per release block:
    #   <p>...BEACH AREA WARNINGS:</p>
    #   <p>· Avalon Beach at....<a href="...prid=N">Click here for the complete release.</a>
    #   <span class="pressTitle">Ocean Water Use Warning ... M/D/YYYY</span>

    advisories: list[CountyAdvisory] = []
    # Each press release on the index has a <span class="pressTitle"> followed
    # by truncated content with a `Click here for the complete release` link
    # to the full release at /phcommon/public/media/mediapubhpdetail.cfm?prid=N.
    # Capture (title → trailing prid) pairs.
    release_blocks = list(re.finditer(
        r"<span class=\"pressTitle\">([^<]*)</span>"
        r".*?href=\"([^\"]*mediapubhpdetail\.cfm\?prid=\d+)\"",
        index_html,
        re.DOTALL | re.IGNORECASE,
    ))
    if not release_blocks:
        rpt.error = "no press-release links found"
        return [], rpt

    # Only the FIRST press-release block on the index reflects the current state
    # (earlier releases are historical; their warnings may have been cleared by
    # a later update). Take just the newest.
    release_blocks = release_blocks[:1]
    for m in release_blocks:
        title = m.group(1)
        path = m.group(2)
        # Only follow current "Ocean Water Use Warning" releases (skip Rain Advisory, Archived)
        if "Warning" not in title or "Archived" in title:
            continue
        date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", title)
        if not date_match:
            continue
        pr_date = _parse_us_date(date_match.group(1))
        if pr_date is None:
            continue
        # Skip stale press releases (>14d old — county updates these every few days)
        if (pd.Timestamp.now().normalize() - pr_date).days > 14:
            continue
        full_url = "http://publichealth.lacounty.gov" + path if path.startswith("/") else path

        try:
            pr_resp = client.get(full_url, headers={"User-Agent": _BROWSER_UA}, timeout=30.0)
            pr_resp.raise_for_status()
        except Exception as e:
            rpt.error = (rpt.error or "") + f"; PR fetch {path} failed: {e}"
            continue

        pr_text = _clean_html_text(pr_resp.text)
        # Extract BEACH AREA WARNINGS section (stop at REASON or NOW CLEARED)
        warn_match = re.search(
            r"BEACH\s*AREA\s*WARNINGS\s*:?(.+?)"
            r"(?:REASON\s*FOR\s*WARNING|BEACH\s*AREAS\s*NOW\s*CLEARED|FOR\s*MORE\s*INFORMATION|$)",
            pr_text,
            re.IGNORECASE | re.DOTALL,
        )
        if not warn_match:
            continue
        warnings_text = warn_match.group(1)
        # Split on bullet markers
        bullets = re.split(r"\s*[·•‣◦∙]\s*", warnings_text)
        for bullet in bullets:
            bullet = bullet.strip(" \t.")
            if not bullet or len(bullet) < 5:
                continue
            if re.match(r"^(the warning|warning|applies|the\s+warning\s+applies)", bullet, re.IGNORECASE):
                continue
            # Beach name: everything before the extent qualifier
            name_match = re.match(
                r"(.+?)(?:,|\s+(?:100\s+(?:yards|feet)|Entire\s+swim|\d+\s+feet|\d+\s+yards)\b)",
                bullet,
            )
            beach_name = name_match.group(1).strip() if name_match else bullet.split(".")[0].strip()
            if not beach_name or len(beach_name) > 80:
                continue
            advisories.append(CountyAdvisory(
                county="Los Angeles",
                station_code=None,
                area=beach_name,
                advisory_type="Posting",
                started_at=pr_date,
                advisory_website=full_url,
                cause="Bacterial Standards Violation",
            ))
    rpt.success = len(advisories) > 0
    if not advisories and not rpt.error:
        rpt.error = "no current Ocean Water Use Warning press releases (within 14d window)"
    rpt.advisories_parsed = len(advisories)
    return advisories, rpt


# ---------- Marin County (Carto/Socrata) ---------- #


MARIN_HOMEPAGE = "https://data.marincounty.gov"
# Marin EH publishes weekly beach inspection results to a Socrata dataset.
# Schema (per /resource/88ua-5nh2.json):
#   beach_name, inspection_week_date (ISO), inspection_result ("OK" | "AVOID" | "N/A"),
#   is_latest_inspection ("1" for current week), latitude, longitude, unique_id
MARIN_API = "https://data.marincounty.gov/resource/88ua-5nh2.json"


def fetch_marin_advisories(client: httpx.Client, resolver: StationResolver) -> tuple[list[CountyAdvisory], CountyReport]:
    rpt = CountyReport(
        county="Marin",
        success=False,
        last_attempted_at=datetime.now(timezone.utc).isoformat(),
        source_url=MARIN_API,
    )
    rpt.stations_in_lookup = len(resolver._beach_name_lookup.get("Marin", {}))
    try:
        # Only the latest-inspection rows that are AVOID (current advisories).
        # SoQL: $where=is_latest_inspection='1' AND inspection_result='AVOID'
        url = (
            f"{MARIN_API}?$where=is_latest_inspection='1' AND inspection_result='AVOID'"
            f"&$limit=200"
        )
        resp = client.get(url, headers={"User-Agent": UA}, timeout=30.0)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as e:
        rpt.error = f"fetch failed: {e}"
        return [], rpt

    advisories: list[CountyAdvisory] = []
    for row in rows if isinstance(rows, list) else []:
        result = str(row.get("inspection_result", "")).upper().strip()
        if result != "AVOID":
            continue
        beach_name = row.get("beach_name") or ""
        date_str = row.get("inspection_week_date") or ""
        try:
            started_at = pd.Timestamp(date_str).normalize()
        except Exception:
            started_at = None
        if started_at is None:
            continue
        advisories.append(CountyAdvisory(
            county="Marin",
            station_code=None,
            area=str(beach_name).title(),
            advisory_type="Posting",
            started_at=started_at,
            advisory_website=MARIN_HOMEPAGE,
            cause="Bacterial Standards Violation",
        ))
    rpt.success = True
    rpt.advisories_parsed = len(advisories)
    return advisories, rpt


# ---------- Long Beach City ---------- #


LB_HOMEPAGE = "https://longbeach.gov/health/inspections-and-reporting/inspections/recreational-water-samples/"
# Long Beach renders a 4-column status grid per beach: cells colored
# green (#00cc00 OPEN), blue (#9bc2e6 ADVISORY), yellow (#ffff00 RAIN ADVISORY),
# red (#ff0000 CLOSED). The active cell contains "●". Beach rows are <tr>'s
# with first two cells = station code (B-XX) and beach name, then 4 status cells.
_LB_STATUS_COLORS = {
    "#00cc00": ("OPEN", None),
    "#9bc2e6": ("Posting", "Bacterial Standards Violation"),
    "#ffff00": ("Posting", "Rain Advisory"),
    "#ff0000": ("Closure", "Significant health risk"),
}


def fetch_long_beach_advisories(
    client: httpx.Client, resolver: StationResolver
) -> tuple[list[CountyAdvisory], CountyReport]:
    rpt = CountyReport(
        county="Long Beach City",
        success=False,
        last_attempted_at=datetime.now(timezone.utc).isoformat(),
        source_url=LB_HOMEPAGE,
    )
    rpt.stations_in_lookup = len(resolver._beach_name_lookup.get("Long Beach City", {}))
    try:
        resp = client.get(LB_HOMEPAGE, headers={"User-Agent": _BROWSER_UA}, timeout=30.0)
        resp.raise_for_status()
    except Exception as e:
        rpt.error = f"fetch failed: {e}"
        return [], rpt

    html = resp.text
    # Find the page-level "Website Updated: M/D/YYYY" so we have an accurate
    # `started_at` for each row (LB doesn't show per-row dates).
    date_match = re.search(r"Website Updated:\s*(\d{1,2}/\d{1,2}/\d{2,4})", html)
    started_at = _parse_us_date(date_match.group(1)) if date_match else pd.Timestamp.now().normalize()

    # Each row: <tr>...<td>B-XX</td>...<td>name</td>...4× <td style="background-color: ..."> with ● in the active cell.
    advisories: list[CountyAdvisory] = []
    for row_match in re.finditer(r"<tr[^>]*>(.+?)</tr>", html, re.DOTALL):
        row_html = row_match.group(1)
        # Pull each <td ...>inner</td> as a (opening-tag, inner) pair
        cells = re.findall(r"(<td[^>]*>)(.*?)</td>", row_html, re.DOTALL)
        if len(cells) < 6:
            continue
        code_clean = re.sub(r"<[^>]+>", "", cells[0][1]).strip().replace("\xa0", "")
        code_clean = re.sub(r"\s+", " ", code_clean).strip()
        name_clean = re.sub(r"<[^>]+>", " ", cells[1][1])
        name_clean = re.sub(r"&nbsp;|\xa0", " ", name_clean)
        name_clean = re.sub(r"\s+", " ", name_clean).strip()
        # Must look like "B-NN"
        m_code = re.match(r"^(B-\d+)", code_clean)
        if not m_code:
            continue
        code_clean = m_code.group(1)
        # Find which of cells 2..5 has ● and what color the cell is
        active_status = None
        active_cause = None
        for open_tag, inner in cells[2:6]:
            if "●" not in inner:
                continue
            style = open_tag.lower()
            for color, (status, cause) in _LB_STATUS_COLORS.items():
                if color in style:
                    active_status = status
                    active_cause = cause
                    break
            if active_status is not None:
                break
        if active_status in (None, "OPEN"):
            continue
        advisories.append(CountyAdvisory(
            county="Long Beach City",
            station_code=code_clean,
            area=name_clean,
            advisory_type=active_status,
            started_at=started_at,
            advisory_website=LB_HOMEPAGE,
            cause=active_cause,
        ))
    rpt.success = True
    rpt.advisories_parsed = len(advisories)
    return advisories, rpt


# ---------- East Bay Regional Park District ---------- #


EB_HOMEPAGE = "https://www.ebparks.org/natural-resources/water-quality"


def fetch_east_bay_advisories(
    client: httpx.Client, resolver: StationResolver
) -> tuple[list[CountyAdvisory], CountyReport]:
    """East Bay Parks publishes a 3-column table (Alert Level | Park | Description).
    Each row that is not 'No Advisory Posted' is an active alert. The Description
    cell starts with the specific beach/lake name."""
    rpt = CountyReport(
        county="East Bay Parks District",
        success=False,
        last_attempted_at=datetime.now(timezone.utc).isoformat(),
        source_url=EB_HOMEPAGE,
    )
    rpt.stations_in_lookup = len(resolver._beach_name_lookup.get("East Bay Parks District", {}))
    try:
        resp = client.get(EB_HOMEPAGE, headers={"User-Agent": _BROWSER_UA}, timeout=30.0)
        resp.raise_for_status()
    except Exception as e:
        rpt.error = f"fetch failed: {e}"
        return [], rpt

    html = resp.text
    table_match = re.search(r"<table.*?</table>", html, re.DOTALL)
    if not table_match:
        rpt.error = "no <table> found"
        return [], rpt
    rows = re.findall(r"<tr[^>]*>(.+?)</tr>", table_match.group(0), re.DOTALL)

    started_at = pd.Timestamp.now().normalize()
    advisories: list[CountyAdvisory] = []
    for row in rows:
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL)
        if len(cells) < 3:
            continue
        alert = re.sub(r"<[^>]+>", " ", cells[0])
        alert = re.sub(r"\s+", " ", alert).strip()
        if not alert or "Alert Level" in alert or "No Advisory" in alert:
            continue
        descr = re.sub(r"<[^>]+>", " ", cells[2])
        descr = re.sub(r"&nbsp;", " ", descr)
        descr = re.sub(r"\s+", " ", descr).strip()
        # Beach name = everything before "Water Quality Conditions"
        name_match = re.match(r"(.+?)\s*Water Quality Conditions", descr)
        beach_name = name_match.group(1).strip() if name_match else descr.split(".")[0][:60]
        if not beach_name:
            continue
        if "Caution" in alert:
            adv_type = "Posting"
            cause = "Caution Advisory (Blue-Green Algae)"
        elif "Danger" in alert:
            adv_type = "Closure"
            cause = "Danger Advisory (Blue-Green Algae)"
        elif "Water Advisory" in alert:
            adv_type = "Posting"
            cause = "Water Advisory"
        else:
            adv_type = "Posting"
            cause = alert
        advisories.append(CountyAdvisory(
            county="East Bay Parks District",
            station_code=None,
            area=beach_name,
            advisory_type=adv_type,
            started_at=started_at,
            advisory_website=EB_HOMEPAGE,
            cause=cause,
        ))
    rpt.success = True
    rpt.advisories_parsed = len(advisories)
    return advisories, rpt


# ---------- Ventura County ---------- #


VT_HOMEPAGE = "https://rma.venturacounty.gov/divisions/environmental-health/ocean-water-quality-sampling-results/"


def fetch_ventura_advisories(
    client: httpx.Client, resolver: StationResolver
) -> tuple[list[CountyAdvisory], CountyReport]:
    """Ventura publishes either:
      - the all-clear sentinel 'no beaches in Ventura County posted with ocean
        water quality warning signs', OR
      - a list of currently-posted beaches.
    We detect the sentinel first (legitimate 0-advisory state) and, if absent,
    scan for posted-beach mentions."""
    rpt = CountyReport(
        county="Ventura",
        success=False,
        last_attempted_at=datetime.now(timezone.utc).isoformat(),
        source_url=VT_HOMEPAGE,
    )
    rpt.stations_in_lookup = len(resolver._beach_name_lookup.get("Ventura", {}))
    try:
        resp = client.get(VT_HOMEPAGE, headers={"User-Agent": _BROWSER_UA}, timeout=30.0)
        resp.raise_for_status()
    except Exception as e:
        rpt.error = f"fetch failed: {e}"
        return [], rpt

    text = _clean_html_text(resp.text)
    # All-clear sentinel
    if re.search(
        r"no beaches in Ventura County posted with ocean water quality warning signs",
        text,
        re.IGNORECASE,
    ):
        rpt.success = True
        rpt.advisories_parsed = 0
        return [], rpt

    # Fallback: scan for "is posted" / "Warning is in effect" near beach names.
    # Ventura uses table rows for posted beaches; conservative scan returns
    # empty if structure is unrecognized rather than guessing.
    advisories: list[CountyAdvisory] = []
    for m in re.finditer(
        r"([A-Z][A-Za-z'\.\s]{3,40}Beach)[^.]{0,200}?(?:warning|posted|exceeds?\s+state)",
        text,
        re.IGNORECASE,
    ):
        beach = m.group(1).strip()
        if len(beach) > 50:
            continue
        advisories.append(CountyAdvisory(
            county="Ventura",
            station_code=None,
            area=beach,
            advisory_type="Posting",
            started_at=pd.Timestamp.now().normalize(),
            advisory_website=VT_HOMEPAGE,
            cause="Bacterial Standards Violation",
        ))
    rpt.success = True
    rpt.advisories_parsed = len(advisories)
    return advisories, rpt


# ---------- Best-effort stubs (try, log, move on) ---------- #


def fetch_best_effort_county(
    client: httpx.Client,
    county: str,
    urls: list[str],
    resolver: StationResolver,
) -> tuple[list[CountyAdvisory], CountyReport]:
    """Generic best-effort: try each URL with browser UA, look for date-keyed
    bullet items. If nothing matches, log and return empty."""
    rpt = CountyReport(
        county=county,
        success=False,
        last_attempted_at=datetime.now(timezone.utc).isoformat(),
        source_url=urls[0] if urls else "",
    )
    rpt.stations_in_lookup = len(resolver._beach_name_lookup.get(county, {}))
    for url in urls:
        try:
            resp = client.get(url, headers={"User-Agent": _BROWSER_UA}, timeout=20.0)
            if resp.status_code != 200:
                continue
            text = _clean_html_text(resp.text)
            if not re.search(r"(advisory|posting|closure|exceed)", text, re.IGNORECASE):
                continue
            rpt.source_url = url
            rpt.success = True
            rpt.error = "page reachable but parser not implemented for this county"
            return [], rpt
        except Exception:
            continue
    rpt.error = f"all {len(urls)} candidate URLs returned non-200 or unrelated content"
    return [], rpt


# ---------- Resolution + merge ---------- #


def resolve_advisories(advisories: list[CountyAdvisory], resolver: StationResolver, report: CountyReport) -> list[CountyAdvisory]:
    """Resolve each CountyAdvisory.beach_id via the hybrid resolver."""
    resolved: list[CountyAdvisory] = []
    for ca in advisories:
        if ca.beach_id:
            # already resolved by parser (some inline)
            report.matched_via_live_list += 1
            resolved.append(ca)
            continue
        if ca.station_code:
            bid, kind = resolver.resolve_by_station_code(ca.county, ca.station_code)
            if bid:
                ca.beach_id = bid
                report.matched_via_live_list += 1
                resolved.append(ca)
                continue
        bid, kind = resolver.resolve_by_name(ca.county, ca.area)
        if bid:
            ca.beach_id = bid
            if kind == "csv":
                report.matched_via_csv += 1
            elif kind == "fuzzy":
                report.matched_via_fuzzy += 1
            else:
                report.matched_via_live_list += 1
            resolved.append(ca)
        else:
            report.unmatched_names.append(ca.area)
    return resolved


def merge_and_rebuild(
    county_advisories: list[CountyAdvisory],
    curated_dir: Path,
    rebuild_beach_day: bool = True,
    authoritative_counties: set[str] | None = None,
) -> tuple[int, int]:
    """Overwrite the state-feed's `active` records for county-direct beaches,
    AND rebuild the advisory_active_prev_14d / days_since_advisory_closed
    columns in beach_day.parquet so training features stay consistent.

    `authoritative_counties` is the set of counties whose scraper succeeded
    this run (regardless of count). Any active record in those counties that
    isn't re-affirmed by a freshly-resolved advisory is treated as stale and
    demoted. This is what nukes leftover state-feed records when a county
    page reports all-clear (e.g., Ventura's sentinel) or when older records
    that the county no longer posts have been silently closed.

    Returns (n_added_to_advisories, n_demoted)."""
    advisories = pd.read_parquet(curated_dir / "advisories.parquet")
    beach_ids_covered = {ca.beach_id for ca in county_advisories if ca.beach_id}
    auth_counties = authoritative_counties or set()

    if not county_advisories and not auth_counties:
        return (0, 0)

    # Two demotion lanes:
    # 1. Beach-level: any active record sharing a beach_id with a freshly
    #    resolved advisory (the original behavior). Keeps semantics for
    #    counties without a first-class scraper.
    # 2. County-level: for counties with an authoritative scraper, demote
    #    EVERY active record in that county whose beach_id is not in the
    #    re-resolved set. Closes the "Ventura returns 0 but state-feed has
    #    44 stale active records from 2018" hole.
    beach_demote = (
        advisories["beach_id"].isin(beach_ids_covered)
        & (advisories["status"] == "active")
    )
    county_demote = (
        advisories["county"].isin(auth_counties)
        & (advisories["status"] == "active")
        & ~advisories["beach_id"].isin(beach_ids_covered)
    )
    keep_mask = ~(beach_demote | county_demote)
    n_demoted = int((~keep_mask).sum())
    base = advisories.loc[keep_mask].copy()

    new_rows = []
    for ca in county_advisories:
        if not ca.beach_id:
            continue
        started_naive = (
            ca.started_at.tz_localize(None)
            if ca.started_at.tzinfo is not None
            else ca.started_at
        )
        new_rows.append({
            "beach_id": ca.beach_id,
            "advisory_type": ca.advisory_type,
            "started_at": started_naive,
            "ended_at": pd.NaT,
            "status": "active",
            "cause": ca.cause,
            "county": ca.county,
            "advisory_website": ca.advisory_website,
        })
    if new_rows:
        new_df = pd.DataFrame(new_rows)
        for col in advisories.columns:
            if col not in new_df.columns:
                new_df[col] = None
        new_df = new_df[advisories.columns]
        combined = pd.concat([base, new_df], ignore_index=True)
    else:
        # All-clear case: authoritative counties returned zero advisories.
        # Persist the demotion (base only) so stale state-feed records leave
        # the active set.
        combined = base
    combined.to_parquet(curated_dir / "advisories.parquet", index=False)

    # Rebuild beach_day.parquet advisory features so training matches serving
    if rebuild_beach_day:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from app.data.pipeline.beachwatch import _advisory_temporal_features

        bd_path = curated_dir / "beach_day.parquet"
        if bd_path.exists():
            bd = pd.read_parquet(bd_path)
            # _advisory_temporal_features expects advisories with started_at, ended_at
            adv_for_feat = combined[["beach_id", "started_at", "ended_at"]].copy()
            bd_rebuilt = _advisory_temporal_features(bd, adv_for_feat)
            bd_rebuilt.to_parquet(bd_path, index=False)
            print(
                f"  [beach_day rebuild] refreshed advisory_active_prev_14d for {len(bd_rebuilt)} rows",
                file=sys.stderr,
            )

    return (len(new_rows), n_demoted)


# ---------- Main ---------- #


COUNTIES_FIRST_CLASS = [
    ("San Diego", fetch_san_diego_advisories),
    ("Orange", fetch_orange_county_advisories),
    ("San Mateo", fetch_san_mateo_advisories),
    ("Los Angeles", fetch_la_county_advisories),
    ("Marin", fetch_marin_advisories),
    ("Long Beach City", fetch_long_beach_advisories),
    ("East Bay Parks District", fetch_east_bay_advisories),
    ("Ventura", fetch_ventura_advisories),
]

BEST_EFFORT_COUNTIES: dict[str, list[str]] = {
    "Monterey": [
        "https://www.countyofmonterey.gov/government/departments-a-h/health/environmental-health/general/public-beaches-water-quality",
        "https://www.countyofmonterey.gov/Home/Components/News/News/9999/16",
    ],
    "Santa Barbara": [
        "https://countyofsb.org/phd/eh/beach-water.sbc",
        "https://www.countyofsb.org/phd/eh/Beach-Water-Quality.sbc",
        "https://publichealthsbc.org/environmentalhealth/beach-water-quality/",
    ],
    "San Francisco": [
        "https://www.sfgov.org/dph/swimming-beaches",
        "https://www.sf.gov/information--checking-ocean-and-beach-water-quality",
        "https://sfpuc.org/water/water-quality/ocean-and-bay-monitoring",
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--curated",
        type=Path,
        default=Path(__file__).resolve().parent.parent.parent / "data" / "curated",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", type=str, help="Filter to one county")
    parser.add_argument("--skip-rebuild-beach-day", action="store_true")
    args = parser.parse_args()

    if not args.curated.exists():
        print(f"curated dir not found: {args.curated}", file=sys.stderr)
        return 1

    beaches = pd.read_parquet(args.curated / "beaches.parquet")
    resolver = StationResolver(beaches)

    all_advisories: list[CountyAdvisory] = []
    reports: list[CountyReport] = []

    with httpx.Client(follow_redirects=True) as client:
        for county_name, fetcher in COUNTIES_FIRST_CLASS:
            if args.only and args.only.lower() not in county_name.lower():
                continue
            print(f"Fetching {county_name} advisories ...")
            try:
                advs, rpt = fetcher(client, resolver)
            except Exception as e:
                print(f"  ERROR for {county_name}: {e}", file=sys.stderr)
                rpt = CountyReport(
                    county=county_name,
                    success=False,
                    last_attempted_at=datetime.now(timezone.utc).isoformat(),
                    source_url="",
                    error=str(e),
                )
                advs = []
            resolved = resolve_advisories(advs, resolver, rpt)
            print(
                f"  {len(advs)} parsed → {len(resolved)} resolved "
                f"(live_list={rpt.matched_via_live_list}, csv={rpt.matched_via_csv}, "
                f"fuzzy={rpt.matched_via_fuzzy}, unmatched={len(rpt.unmatched_names)})"
            )
            for ca in resolved:
                tag = ca.station_code or "name-resolved"
                print(
                    f"    {ca.advisory_type:18s}  {tag:14s}  {ca.started_at.date()}  {ca.area[:45]}"
                )
            if rpt.unmatched_names:
                for nm in rpt.unmatched_names[:5]:
                    print(f"    [unmatched] {nm[:60]}", file=sys.stderr)
            all_advisories.extend(resolved)
            reports.append(rpt)

        # Best-effort counties
        for county_name, urls in BEST_EFFORT_COUNTIES.items():
            if args.only and args.only.lower() not in county_name.lower():
                continue
            print(f"Trying best-effort: {county_name} ...")
            advs, rpt = fetch_best_effort_county(client, county_name, urls, resolver)
            note = rpt.error or "fetched"
            print(f"  {note}")
            reports.append(rpt)

    # Write telemetry
    report_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_resolved_advisories": len(all_advisories),
        "counties": [asdict(r) for r in reports],
    }
    if not args.dry_run:
        (args.curated / "county_advisories_report.json").write_text(
            json.dumps(report_payload, indent=2)
        )

    if args.dry_run:
        print(f"\n[dry-run] would merge {len(all_advisories)} advisories; skipping write")
        return 0

    # Counties whose first-class scraper succeeded this run are authoritative:
    # they speak for ALL active records in that county, including the all-clear
    # case (Ventura's sentinel) and partial-coverage cases (county no longer
    # posts an older state-feed record).
    first_class_names = {name for name, _ in COUNTIES_FIRST_CLASS}
    authoritative_counties = {
        r.county for r in reports
        if r.county in first_class_names and r.success
    }
    added, demoted = merge_and_rebuild(
        all_advisories,
        args.curated,
        rebuild_beach_day=not args.skip_rebuild_beach_day,
        authoritative_counties=authoritative_counties,
    )
    print(
        f"\nMerged into {args.curated / 'advisories.parquet'}: "
        f"added {added}, demoted {demoted} stale state records "
        f"(authoritative counties: {sorted(authoritative_counties)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
