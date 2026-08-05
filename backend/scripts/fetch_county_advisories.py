"""Fetch county-direct beach advisories and override stale state-feed records.

California's data.ca.gov BeachWatch dataset is refreshed on a slow cadence
(metadata_modified ~60 days stale for status changes). County health-department
websites publish current postings same-day. This script pulls county-direct
sources, overrides the state-feed `active` records in advisories.parquet,
AND rebuilds the advisory-derived columns in beach_day.parquet so the
training feature (advisory_active_prev_14d) reflects the same fresh state.

Each county is a (station_lookup_fn, advisory_parser_fn) pair. Name→station
code resolution is hybrid (see StationResolver for the full layer order):
  1. Auto-built from beaches.parquet (county-filtered station_code + beach_name,
     plus an exact-only secondary index on the site-level name/station_code)
  2. Static alias CSV in _static_data/county_beach_name_to_station.csv, which
     may fan one scraped posting out to several beach_ids
  3. Token-guarded substring match, then a rapidfuzz fuzzy fallback
     (≥0.90, gap≥0.20 vs runner-up, same county)

Per-run telemetry written to data/curated/county_advisories_report.json; the
G.1 gate verdict to data/curated/system_health.json under `scraper_gate`.

G.1 gate severity (changed 2026-08-05): a SOFT trip no longer aborts in place.
It publishes the verdict and returns 0 so the daily pipeline still produces a
forecast, and scripts/verify_scraper_gate.py fails the job after the data
commit. Only a HARD trip — mass resolution loss, or a county that resolved
advisories last run and resolves none now — exits non-zero here, because that
means the advisory feed itself cannot be trusted by the training step that
consumes advisory_active_prev_14d.

Run after the state-feed normalization step in the daily-forecast pipeline:
    python scripts/fetch_county_advisories.py --curated ../data/curated/
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from dataclasses import dataclass, field, asdict, replace
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


# ---------- Retry-with-backoff for transient county-site failures ---------- #
# County sites flake (smchealth.org hit a 403 after 4-5 rapid scrapes today).
# Wrap every county fetch so a transient 403/429/5xx/timeout doesn't silently
# zero-out the county for the whole day.

import random as _rand  # noqa: E402
import time as _time  # noqa: E402

_RETRY_STATUS = {403, 408, 425, 429, 500, 502, 503, 504}
_RETRY_DELAYS_S = (5, 15, 45)


def _do_with_retry(raw_client: httpx.Client, method: str, url: str, *,
                   headers: dict[str, str] | None = None,
                   data: dict[str, str] | None = None,
                   timeout: float = 30.0) -> httpx.Response:
    """Retry GET/POST on 403/429/5xx/timeout with exponential backoff +
    jitter. After the first attempt, fall back to a browser UA in case
    the original UA was being filtered."""
    last_exc: Exception | None = None
    for attempt, delay in enumerate((0, *_RETRY_DELAYS_S)):
        if delay:
            _time.sleep(delay + _rand.uniform(0, 2.0))
        try:
            req_headers = dict(headers or {})
            if attempt >= 1 and "User-Agent" in req_headers and not req_headers["User-Agent"].startswith("Mozilla"):
                req_headers["User-Agent"] = _BROWSER_UA
            if method == "GET":
                resp = raw_client.get(url, headers=req_headers, timeout=timeout)
            else:
                resp = raw_client.post(url, headers=req_headers, data=data or {}, timeout=timeout)
            if resp.status_code in _RETRY_STATUS and attempt < len(_RETRY_DELAYS_S):
                last_exc = httpx.HTTPStatusError(
                    f"transient {resp.status_code}", request=resp.request, response=resp
                )
                continue
            return resp
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_exc = exc
            if attempt >= len(_RETRY_DELAYS_S):
                break
            continue
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _RETRY_STATUS:
                raise
            last_exc = exc
            continue
    assert last_exc is not None
    raise last_exc


class RetryingClient:
    """httpx.Client-compatible wrapper. Call sites use it like the raw
    client (get/post with headers, data, timeout) and get free retry on
    transient failures. No per-county code changes needed."""

    def __init__(self, **kwargs):
        self._raw = httpx.Client(**kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self._raw.close()

    def get(self, url, *, headers=None, timeout=30.0):
        return _do_with_retry(self._raw, "GET", url, headers=headers, timeout=timeout)

    def post(self, url, *, data=None, headers=None, timeout=30.0):
        return _do_with_retry(self._raw, "POST", url, headers=headers, data=data, timeout=timeout)


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
class CountySample:
    """A single numeric water-quality reading scraped from a county-direct
    source. Stored to county_direct_samples.parquet so the model + audit
    can cross-validate against the state BeachWatch feed."""
    county: str
    area: str               # beach name as it appears on the source
    sample_date: pd.Timestamp
    analyte: str            # ENTEROCOCCUS | FECAL_COLIFORM | E_COLI | TOTAL_COLIFORM
    value: float            # MPN/100mL or CFU/100mL — units inferred from analyte+county
    exceeds_limit: bool
    source_url: str
    station_code: str | None = None
    beach_id: str | None = None  # filled in by the resolver, mirrors CountyAdvisory


# Module-level collector so adding samples doesn't require changing the
# fetcher return signature for every county. Fetchers that have sample
# values (SF, Humboldt, Sonoma) append to this; everyone else ignores it.
# main() drains it once per run after all fetchers are done.
_COLLECTED_SAMPLES: list[CountySample] = []


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
    samples_collected: int = 0  # purely informational counter for the report


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

# Minimum length for any normalized key we are willing to match on. Applies to
# the secondary index and the substring rule alike — below this, keys like
# "bay" collide with half the roster.
_MIN_MATCH_KEY_LEN = 4

# Heuristic matches (Layer A.2 substring, Layer C fuzzy) must be ANCHORED — see
# _match_is_anchored. The old rule accepted ANY containment over a 4-character
# floor, which is how "Shinn Pond at Alameda Creek Trails" (a Fremont freshwater
# pond) resolved onto "Alameda Point Encinal Beach Mid" — a bay swim beach — on
# the single shared token "alameda". A dropped advisory is a miss; a mis-mapped
# one posts a warning on the wrong beach and clears the real one, so the
# heuristic layers have to be the conservative ones.
_MIN_SUBSTRING_SHARED_TOKENS = 2

# A fuzzy candidate that is not anchored must instead be a near-identical string
# end to end, scored with the length-sensitive `fuzz.ratio` rather than
# `token_set_ratio`. This is what still lets a genuine MISSPELLING through
# (which by definition shares no exact token) while rejecting "roster key
# happens to appear somewhere in the posting".
_MIN_FUZZY_WHOLE_STRING_RATIO = 90


def _is_token_prefix(shorter: list[str], longer: list[str]) -> bool:
    return len(shorter) <= len(longer) and longer[: len(shorter)] == shorter


def _match_is_anchored(norm: str, key: str) -> bool:
    """Is `key` naming the SUBJECT of posting `norm` (or vice versa)?

    Two ways to qualify:

      * >= _MIN_SUBSTRING_SHARED_TOKENS shared tokens — enough overlap that the
        match cannot rest on one incidental word.
      * one side is a token-PREFIX of the other. Counties decorate a beach name
        with trailing location detail ("Doheny State Beach - 100 feet up and
        down coast of the San Juan Creek outlet"), so the roster key leads the
        posting. This is what separates a decorated name from an incidental
        mention: "alameda" is a token of "shinn pond alameda trails" but not its
        prefix, whereas "doheny" leads "doheny 100 feet up and down coast...".

    The prefix arm is NOT optional. `_normalize_name` strips the noise tokens
    (beach, creek, bay, point, park, state...), which collapses 131 of 324
    roster keys — 40% — to a single token: "doheny", "zuma", "stinson",
    "crown". A shared-token count alone can never reach 2 against those, so a
    shared-tokens-only rule silently drops EVERY decorated posting for 40% of
    the roster (measured: 1,773 correct resolutions lost across all 15
    counties, incl. the two EBRPD beaches this scraper fix targets).
    """
    norm_tokens, key_tokens = norm.split(), key.split()
    if len(set(norm_tokens) & set(key_tokens)) >= _MIN_SUBSTRING_SHARED_TOKENS:
        return True
    return _is_token_prefix(norm_tokens, key_tokens) or _is_token_prefix(key_tokens, norm_tokens)


class StationResolver:
    """Resolve a (county, beach_name) tuple to a beach_id using:
    Layer A   — live county station_lookup, keyed on `beach_name` (exact)
    Layer A.1 — secondary index keyed on the per-site `name` / `station_code`
                (exact only; see __init__)
    Layer A.2 — substring against the Layer A keys (token-guarded)
    Layer B   — static alias CSV (county, beach_name_normalized → beach_id(s))
    Layer C   — rapidfuzz against the live county station_lookup
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
        # Secondary per-county index keyed on the SITE-level `name` and
        # `station_code` columns: { county: { normalized: beach_id } }.
        #
        # `beach_name` is a site *group* ("Crown Beach (Alameda Co)" covers six
        # sampling points), and some rows carry a county-wide placeholder in it
        # — all of Marin's GREEN BRIDGE identity lives in `name`/`station_code`
        # while its `beach_name` reads "All_Marin_County", so a beach_name-only
        # index cannot see it at all. Two consequences this index fixes:
        #   * GREEN BRIDGE was unresolvable (its Marin sibling Inkwells only
        #     resolved because a SECOND registry row happens to carry
        #     beach_name="Inkwells");
        #   * every site under a shared beach_name collapsed to one arbitrary
        #     beach_id, so "Del Valle WEST Swim Beach" resolved onto the EAST
        #     beach's id — the west posting landed on the wrong beach and the
        #     west beach showed clean.
        #
        # EXACT MATCHES ONLY. These keys are numerous (~1.4k) and noisier than
        # beach_name (a few counties carry junk like "Open"), so they must never
        # feed the substring or fuzzy layers. Keys that map to more than one
        # beach_id within a county are dropped as ambiguous rather than
        # resolved arbitrarily — 13 keys statewide as of 2026-08.
        self._secondary_name_lookup: dict[str, dict[str, str]] = {}
        for cnty, grp in beaches.groupby("county"):
            candidates: dict[str, set[str]] = {}
            for _, row in grp.iterrows():
                for column in ("name", "station_code"):
                    value = row.get(column)
                    if not value or pd.isna(value):
                        continue
                    key = _normalize_name(str(value))
                    if len(key) < _MIN_MATCH_KEY_LEN:
                        continue
                    candidates.setdefault(key, set()).add(str(row["beach_id"]))
            self._secondary_name_lookup[str(cnty)] = {
                key: next(iter(ids))
                for key, ids in candidates.items()
                if len(ids) == 1
            }
        # Per-county station_code → beach_id
        self._station_code_lookup: dict[str, dict[str, str]] = {}
        for cnty, grp in beaches.groupby("county"):
            self._station_code_lookup[str(cnty)] = {
                str(row["station_code"]).upper(): str(row["beach_id"])
                for _, row in grp.iterrows()
                if row.get("station_code")
            }
        # Static alias CSV. One scraped name may legitimately map to MANY
        # beach_ids: EBRPD posts "Crown Beach Regional Shoreline" as a single
        # district-wide notice covering all six sampled points, so the alias
        # file carries one row per covered beach_id and the advisory fans out
        # (see resolve_all_by_name). Repeated (county, name) keys accumulate
        # instead of overwriting.
        self._alias_lookup: dict[tuple[str, str], list[str]] = {}
        if _STATIC_ALIAS_CSV.exists():
            try:
                alias_df = pd.read_csv(_STATIC_ALIAS_CSV)
                for _, row in alias_df.iterrows():
                    key = (str(row["county"]), _normalize_name(str(row["beach_name_normalized"])))
                    target = str(row.get("beach_id") or row.get("station_code") or "")
                    if not target or target == "nan":
                        continue
                    bucket = self._alias_lookup.setdefault(key, [])
                    if target not in bucket:
                        bucket.append(target)
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

    def resolve_all_by_name(self, county: str, beach_name: str) -> tuple[list[str], str]:
        """Hybrid name resolution. Returns (beach_ids, match_kind).

        Returns a LIST because one scraped posting can legitimately cover
        several sampled beaches (a district-wide EBRPD notice over the six
        Crown Beach points). Every layer but the alias CSV is single-valued;
        only a curated multi-row alias entry fans out.

        Layer order is confidence order — exact identity first, curated human
        mapping next, heuristics last. The alias CSV deliberately outranks the
        substring layer so an operator can correct a bad heuristic match by
        adding a row rather than by tuning the heuristic.
        """
        norm = _normalize_name(beach_name)
        if not norm:
            return [], "miss"

        # Layer A: live county lookup on beach_name (exact normalized match)
        county_lookup = self._beach_name_lookup.get(county, {})
        if norm in county_lookup:
            return [county_lookup[norm]], "live_list"

        # Layer B: alias CSV (curated; may fan out to several beach_ids).
        #
        # Runs ahead of the secondary index, not just ahead of the heuristics: a
        # site-level `name` can collide with a DIFFERENT beach's group name in
        # the same county, and only a human can adjudicate. LA has two distinct
        # Mother's Beaches — Long Beach's Alamitos Bay site is literally named
        # "Mothers' Beach", while Marina del Rey's carries it in `beach_name`
        # ("Marina Del Rey Beach - Mothers Beach") — so a bare "Mothers Beach"
        # posting hit the secondary index and silently moved 40 km. The
        # ambiguity guard cannot see that: the two keys normalize differently,
        # so neither index looks ambiguous on its own.
        aliases = self._alias_lookup.get((county, norm)) or []
        resolved_aliases: list[str] = []
        for target in aliases:
            # If CSV gave a station_code rather than a beach_id, translate it.
            if target.startswith("ca"):
                resolved_aliases.append(target)
            else:
                translated, _ = self.resolve_by_station_code(county, target)
                if translated:
                    resolved_aliases.append(translated)
        if resolved_aliases:
            return resolved_aliases, "csv"

        # Layer A.1: secondary index on site-level name/station_code (exact
        # only — see __init__ for why these keys never feed the fuzzy layers).
        secondary = self._secondary_name_lookup.get(county, {})
        if norm in secondary:
            return [secondary[norm]], "live_list"

        # Layer A.2: substring match either direction, token-guarded. Requires
        # _MIN_SUBSTRING_SHARED_TOKENS shared tokens so a single incidental
        # token ("alameda") can no longer carry a match onto the wrong beach.
        # Ambiguity is a miss, not a coin flip: when several roster keys
        # qualify we drop to the unresolved sink rather than let dict order
        # decide which beach gets the advisory.
        if len(norm) >= _MIN_MATCH_KEY_LEN:
            norm_tokens = norm.split()
            candidates = [
                (key, bid)
                for key, bid in county_lookup.items()
                if len(key) >= _MIN_MATCH_KEY_LEN
                and (norm in key or key in norm)
                and _match_is_anchored(norm, key)
            ]
            # Several roster keys can legitimately qualify ("Huntington City
            # Beach near the creek mouth" matches both "huntington" and
            # "huntington city"). Rank rather than coin-flip on dict order:
            #   1. a key that LEADS the posting names its subject, beating one
            #      that merely appears inside it — this is what picks Cardiff
            #      over San Elijo for "Cardiff/ San Elijo Lagoon - ...";
            #   2. then the more specific (longer) key — "huntington city"
            #      over "huntington".
            # Only a tie at the top rank is genuinely ambiguous, and that is
            # still a miss rather than an arbitrary pick.
            if candidates:
                def _rank(item: tuple[str, str]) -> tuple[int, int]:
                    key = item[0]
                    return (
                        1 if _is_token_prefix(key.split(), norm_tokens) else 0,
                        len(key.split()),
                    )

                best = max(_rank(c) for c in candidates)
                winners = {bid for c, bid in ((c, c[1]) for c in candidates) if _rank(c) == best}
                if len(winners) == 1:
                    return [next(iter(winners))], "live_list"

        # Layer C: fuzzy match (only if rapidfuzz available), under the SAME
        # conservatism as Layer A.2.
        #
        # `token_set_ratio` scores 100 whenever one token set is a subset of the
        # other, so on its own it re-admits the exact mis-map the substring
        # guard rejects: token_set_ratio("shinn pond alameda trails",
        # "alameda") == 100 with a 39-point gap to the runner-up, which is how
        # a Fremont freshwater pond kept resolving onto Alameda Point. A match
        # must therefore ALSO be either token-anchored (>= 2 shared tokens, the
        # Layer A.2 rule) or a near-identical string overall (`ratio`, which is
        # length-sensitive and so immune to the subset pathology — it scores
        # that pair 43.8). This costs nothing measurable: the fuzzy layer
        # matched 0 advisories in the last committed run (45 live_list, 1 csv).
        if HAS_RAPIDFUZZ and county_lookup:
            candidates = list(county_lookup.keys())
            top = process.extract(norm, candidates, scorer=fuzz.token_set_ratio, limit=2)
            if top and top[0][1] >= 90:
                if len(top) == 1 or (top[0][1] - top[1][1] >= 20):
                    key = top[0][0]
                    if (
                        _match_is_anchored(norm, key)
                        or fuzz.ratio(norm, key) >= _MIN_FUZZY_WHOLE_STRING_RATIO
                    ):
                        return [county_lookup[key]], "fuzzy"

        return [], "miss"

    def resolve_by_name(self, county: str, beach_name: str) -> tuple[str | None, str]:
        """Single-valued name resolution. Returns (beach_id, match_kind).

        Kept for callers that must land on exactly one beach — notably
        `persist_samples`: a scraped MPN reading is one physical measurement
        and must not be duplicated across a fan-out group the way a
        district-wide advisory is.
        """
        beach_ids, kind = self.resolve_all_by_name(county, beach_name)
        return (beach_ids[0] if beach_ids else None), kind


# ---------- San Diego (sdbeachinfo.com) ---------- #


SD_HOMEPAGE = "https://www.sdbeachinfo.com/"
SD_GETDATA = "https://www.sdbeachinfo.com/Home/GetData"


def _sd_fetch_partial(client: httpx.Client, name: str) -> str:
    resp = client.post(
        SD_GETDATA,
        data={"name": name},
        headers={
            "User-Agent": UA,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": SD_HOMEPAGE,
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.text


def fetch_san_diego_advisories(client: httpx.Client, resolver: StationResolver) -> tuple[list[CountyAdvisory], CountyReport]:
    """Scrape sdbeachinfo.com.

    Pulls TWO partials:
      - _AdvisoryPartialView: per-station Advisories / Closures / Chronic
        Advisories (with station code in parentheses).
      - _ClosurePartialView: shoreline-scope closures (Tijuana Slough,
        Silver Strand, Imperial Beach) that span multiple stations and
        have no per-station code.
    """
    rpt = CountyReport(
        county="San Diego",
        success=False,
        last_attempted_at=datetime.now(timezone.utc).isoformat(),
        source_url=SD_HOMEPAGE,
    )
    rpt.stations_in_lookup = len(resolver._station_code_lookup.get("San Diego", {}))
    try:
        html = _sd_fetch_partial(client, "_AdvisoryPartialView")
        closure_html = _sd_fetch_partial(client, "_ClosurePartialView")
    except Exception as e:
        rpt.error = f"fetch failed: {e}"
        return [], rpt

    # San Diego also lists "Closure: <Shoreline name>" entries that span
    # multiple stations without a per-station code (Tijuana Slough,
    # Silver Strand, Imperial Beach). Map each shoreline to the stations
    # the live page describes (verified from sdbeachinfo.com's Stations
    # field). These persist as long as the shoreline closure is listed.
    SD_SHORELINE_CLOSURES = {
        "Tijuana Slough Shoreline": ["IB-010", "IB-020", "IB-030", "IB-040"],
        "Silver Strand Shoreline": ["IB-067", "IB-068", "IB-069", "IB-070"],
        "Imperial Beach Shoreline": [
            "EH-010", "EH-020", "EH-030", "EH-033", "EH-041",
            "IB-045", "IB-050", "IB-060", "PL-010",
        ],
    }

    advisories: list[CountyAdvisory] = []

    # Pass 1: per-station Advisories / Closures / Chronic from _AdvisoryPartialView
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

    # Pass 2: shoreline-scope closures from _ClosurePartialView. These span
    # multiple stations without per-station codes (Tijuana Slough since
    # Oct 2025, Imperial Beach since Dec 2025, etc.). Expand each to all
    # the affected stations so they show as Closed in the API+UI.
    for li in re.findall(r"<li>(.*?)</li>", closure_html, re.DOTALL):
        text = _clean_html_text(li)
        if "Status Since" not in text:
            continue
        if not re.match(r"^Closure\s*:", text):
            continue
        # Match shoreline name; allow flexible whitespace because the live
        # HTML has &nbsp; sprinkled inside (e.g., "Silver Strand Shoreline").
        matched_codes: list[str] | None = None
        matched_name: str | None = None
        for shoreline, codes in SD_SHORELINE_CLOSURES.items():
            pattern = re.compile(r"\s+".join(re.escape(w) for w in shoreline.split()), re.IGNORECASE)
            if pattern.search(text):
                matched_codes = codes
                matched_name = shoreline
                break
        if not matched_codes:
            continue
        m_date = re.search(
            r"Status Since\s*:\s*([A-Za-z]+\s+\d+,?\s*\d{4}|[A-Za-z]+\s+\d{4})",
            text,
        )
        if not m_date:
            continue
        started_at = _parse_us_date(m_date.group(1))
        if started_at is None:
            continue
        cause = "Other - Tijuana River Associated" if "tijuana" in text.lower() else "Bacterial Standards Violation"
        for code in matched_codes:
            advisories.append(CountyAdvisory(
                county="San Diego",
                station_code=code,
                area=matched_name,
                advisory_type="Closure",
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
    # Section boundaries. The ADVISORIES section runs from m_ad.end() to EOF;
    # without slicing it into the dict the section's entries were never even
    # scanned (the 2026-05-23 regression: 0 of 3 entries returned because all
    # 3 were under ADVISORIES — Salt Creek, Doheny, etc.).
    sections = {"Closure": None, "Posting": None, "Advisory": None}
    m_cl = re.search(r"CLOSURES\s*:?", text, re.IGNORECASE)
    m_wr = re.search(r"WARNINGS\s*:?", text, re.IGNORECASE)
    m_ad = re.search(r"ADVISORIES\s*:?", text, re.IGNORECASE)
    if not (m_cl and m_wr and m_ad):
        rpt.error = "expected section markers (CLOSURES/WARNINGS/ADVISORIES) not all found"
        return [], rpt
    sections["Closure"] = (m_cl.end(), m_wr.start())
    sections["Posting"] = (m_wr.end(), m_ad.start())
    sections["Advisory"] = (m_ad.end(), len(text))

    advisories: list[CountyAdvisory] = []
    for adv_type, (s, e) in sections.items():
        chunk = text[s:e]
        # Skip if "currently in effect" → "No ocean, harbor, or bay water X currently in effect."
        if re.search(r"No (ocean|water).{0,80}currently in effect", chunk, re.IGNORECASE):
            continue
        # Each entry: "<description> (posted M/D/YYYY)" or "(updated on M/D/YYYY)".
        # The "on" was historically required; OC dropped it in some entries
        # (verified 2026-05-23: "Newport Bay (updated 5/15/2026)") so the regex
        # makes "on" optional.
        for m in re.finditer(
            r"([\dA-Z][^.()]+?)\s*\((?:posted|updated)\s+(?:on\s+)?(\d{1,2}/\d{1,2}/\d{2,4})\)",
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
    # `_alias_lookup` values are lists (one scraped name may cover several
    # beach_ids); San Mateo's line-scanner is single-valued, so take the first
    # target. No San Mateo alias fans out today.
    for (cnty, norm_alias), aids in resolver._alias_lookup.items():
        if cnty != "San Mateo":
            continue
        aid = next((a for a in aids if a and a != "nan"), "")
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


# ---------- San Francisco (data.sfgov.org Socrata API) ---------- #


SF_HOMEPAGE = "https://www.sf.gov/information--checking-ocean-and-beach-water-quality"
SF_API = "https://data.sfgov.org/resource/v3fv-x3ux.json"

# CA AB411 single-sample exceedance thresholds (Title 17 CCR §7958)
_SF_THRESHOLDS = {
    "ENTERO": 104.0,       # MPN/100mL — primary marine indicator
    "COLI_FECAL": 400.0,   # MPN/100mL — fecal coliform (used for SF Bay)
    # Total coliform threshold (10,000) intentionally omitted: it's the
    # weakest signal of the three, and the AB411 trigger condition for
    # total coliform also requires the fecal-to-total ratio to exceed 0.1
    # — we'd need to pair them, and the FECAL threshold catches the same
    # high-risk samples directly.
}


def _sf_parse_value(raw: str) -> float | None:
    """SF reports values as text: '<5', '<10', '110', '1,100'. The '<N'
    form means below detection limit, so the *true* value is bounded
    above by N — safe to treat as N (still well below thresholds for
    the small-N cases we see here)."""
    s = str(raw).strip().replace(",", "")
    if not s:
        return None
    if s.startswith("<"):
        s = s[1:].strip()
    try:
        return float(s)
    except ValueError:
        return None


def fetch_san_francisco_advisories(
    client: httpx.Client, resolver: StationResolver
) -> tuple[list[CountyAdvisory], CountyReport]:
    """San Francisco DPH publishes beach sample results to a Socrata
    dataset (no separate advisory feed). We apply AB411 single-sample
    thresholds to the *latest* sample per (station, analyte) and emit
    an advisory wherever ENTERO ≥104 or COLI_FECAL ≥400 MPN/100mL.

    This is the same single-sample post-trigger logic BeachWatch uses,
    so SF's results stay consistent with the rest of the pipeline."""
    rpt = CountyReport(
        county="San Francisco",
        success=False,
        last_attempted_at=datetime.now(timezone.utc).isoformat(),
        source_url=SF_API,
    )
    rpt.stations_in_lookup = len(resolver._station_code_lookup.get("San Francisco", {}))

    # Pull last 30 days of ENTERO + COLI_FECAL samples. The 30-day window
    # is wider than the 14-day acute advisory window so we don't miss a
    # station that only got sampled once recently.
    cutoff = (pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")
    analytes = "(" + ",".join(f"'{a}'" for a in _SF_THRESHOLDS) + ")"
    url = (
        f"{SF_API}"
        f"?$where=sample_date >= '{cutoff}' AND analyte IN {analytes}"
        f"&$order=sample_date DESC"
        f"&$limit=2000"
    )
    try:
        resp = client.get(url, headers={"User-Agent": UA}, timeout=30.0)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as e:
        rpt.error = f"fetch failed: {e}"
        return [], rpt

    if not isinstance(rows, list):
        rpt.error = "unexpected response shape (not a list)"
        return [], rpt

    # Reduce to latest sample per (source, analyte) — rows are already
    # sample_date DESC so we keep the first occurrence of each key.
    # Also emit one CountySample per row so we persist the full sample
    # feed to county_direct_samples.parquet, not just the exceedances.
    _SF_ANALYTE_NORMALIZE = {"ENTERO": "ENTEROCOCCUS", "COLI_FECAL": "FECAL_COLIFORM"}
    latest: dict[tuple[str, str], dict] = {}
    for row in rows:
        src = row.get("source")
        anl = row.get("analyte")
        if not src or anl not in _SF_THRESHOLDS:
            continue
        key = (src, anl)
        if key not in latest:
            latest[key] = row
        value = _sf_parse_value(row.get("data", ""))
        if value is None:
            continue
        try:
            sample_date = pd.Timestamp(row["sample_date"]).normalize()
        except Exception:
            continue
        _COLLECTED_SAMPLES.append(CountySample(
            county="San Francisco",
            area=src,
            sample_date=sample_date,
            analyte=_SF_ANALYTE_NORMALIZE.get(anl, anl),
            value=value,
            exceeds_limit=value >= _SF_THRESHOLDS[anl],
            source_url=SF_API,
            station_code=src,
        ))

    # Emit one advisory per station whose latest sample on ANY tracked
    # analyte exceeds the threshold. Use the highest-priority exceedance
    # (ENTERO before COLI_FECAL) for the started_at + cause text.
    advisories: list[CountyAdvisory] = []
    seen_stations: set[str] = set()
    for analyte in ("ENTERO", "COLI_FECAL"):
        threshold = _SF_THRESHOLDS[analyte]
        for (src, anl), row in latest.items():
            if anl != analyte or src in seen_stations:
                continue
            value = _sf_parse_value(row.get("data", ""))
            if value is None or value < threshold:
                continue
            try:
                started_at = pd.Timestamp(row["sample_date"]).normalize()
            except Exception:
                continue
            cause = (
                f"{analyte} {value:.0f} MPN/100mL exceeds AB411 single-sample "
                f"threshold ({threshold:.0f})"
            )
            advisories.append(CountyAdvisory(
                county="San Francisco",
                station_code=src,
                area=src,  # resolver will lift the real beach name from station_code
                advisory_type="Posting",
                started_at=started_at,
                advisory_website=SF_HOMEPAGE,
                cause=cause,
            ))
            seen_stations.add(src)

    rpt.success = True
    rpt.advisories_parsed = len(advisories)
    return advisories, rpt


# ---------- Humboldt + Sonoma + SLO (LLM extraction) ---------- #


HUMBOLDT_HOMEPAGE = "https://humboldtgov.org/1696/Water-Quality-Test-Results"
SONOMA_HOMEPAGE = (
    "https://sonomacounty.gov/health-and-human-services/health-services/"
    "divisions/public-health/environmental-health/programs-and-services/"
    "ocean-water-quality"
)
SLO_HOMEPAGE = "https://slocounty.maps.arcgis.com/apps/dashboards/0693b6f43f444995afc3f90d29b81432"


def _fetch_via_ai_extract(
    client: httpx.Client,
    county: str,
    url: str,
    homepage: str | None = None,
    use_playwright: bool = False,
    wait_for_text: str | None = None,
) -> tuple[list[CountyAdvisory], CountyReport]:
    """Shared LLM-extraction path for counties without a structured feed.
    Loads the AI extraction helpers from scripts/ai_extract_advisories.py
    so we don't duplicate the prompt + GitHub Models plumbing."""
    rpt = CountyReport(
        county=county,
        success=False,
        last_attempted_at=datetime.now(timezone.utc).isoformat(),
        source_url=url,
    )

    # Lazy import — keeps the static scrapers usable even if the AI module
    # has its own optional deps in the future.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from ai_extract_advisories import (  # type: ignore
            fetch_page, trim_html, extract_via_github_models_full,
        )
    except ImportError as e:
        rpt.error = f"ai_extract_advisories import failed: {e}"
        return [], rpt

    import os as _os
    if not _os.environ.get("GITHUB_TOKEN"):
        rpt.error = "GITHUB_TOKEN not set; skipping LLM extraction"
        return [], rpt

    try:
        # client is the RetryingClient — but fetch_page uses its own httpx
        # client because Playwright path needs different setup. The plain
        # httpx fetch inside fetch_page() handles retries via its own UA.
        html = fetch_page(
            url,
            use_playwright=use_playwright,
            timeout=45.0 if use_playwright else 30.0,
            wait_for_text=wait_for_text,
        )
        text = trim_html(html)
        if len(text) < 200:
            rpt.error = f"page text too short ({len(text)} chars) — likely a 404/block"
            return [], rpt
        payload = extract_via_github_models_full(text, county)
        rows = payload.get("advisories", [])
        sample_rows = payload.get("samples", [])
    except Exception as e:
        rpt.error = f"extraction failed: {e}"
        return [], rpt

    # Persist numeric sample values to the shared collector. Reject any
    # sample with sample_date outside the last 90 days — that filters out
    # the common hallucination where the LLM invents a date for what's
    # actually a non-sample number on the page (e.g., SLO's dashboard
    # publishes sample *counts*, not values, and the LLM tries to
    # convert them with a fabricated 2023 date).
    recency_cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=90)
    _ALLOWED_ANALYTES = {"ENTEROCOCCUS", "FECAL_COLIFORM", "E_COLI", "TOTAL_COLIFORM"}
    for s in sample_rows:
        beach_name = (s.get("beach_name") or "").strip()
        if not beach_name:
            continue
        sample_date_str = str(s.get("sample_date") or "").strip()
        sample_date = _parse_us_date(sample_date_str) if sample_date_str else None
        if sample_date is None or sample_date < recency_cutoff:
            continue
        analyte = (s.get("analyte") or "").strip().upper()
        if analyte not in _ALLOWED_ANALYTES:
            continue
        # value may be a number or a string like "<5" — coerce
        raw_value = s.get("value")
        try:
            value = float(str(raw_value).lstrip("<").replace(",", "")) if raw_value is not None else None
        except (ValueError, TypeError):
            value = None
        if value is None or value < 0 or value > 1_000_000:
            continue
        _COLLECTED_SAMPLES.append(CountySample(
            county=county,
            area=beach_name,
            sample_date=sample_date,
            analyte=analyte,
            value=value,
            exceeds_limit=bool(s.get("exceeds_limit", False)),
            source_url=url,
        ))

    advisories: list[CountyAdvisory] = []
    for row in rows:
        beach_name = (row.get("beach_name") or "").strip()
        if not beach_name:
            continue
        adv_type = (row.get("advisory_type") or "Posting").strip()
        if adv_type.lower() in ("rain advisory", "rain"):
            adv_type = "Posting"
        elif adv_type.lower().startswith("clos"):
            adv_type = "Closure"
        elif adv_type.lower().startswith("chronic"):
            adv_type = "Chronic Posting"
        else:
            adv_type = "Posting"

        started_at = None
        if row.get("started_at"):
            started_at = _parse_us_date(str(row["started_at"]))
        if started_at is None:
            started_at = pd.Timestamp.now().normalize()

        cause = row.get("cause") or "Bacterial Standards Violation"

        advisories.append(CountyAdvisory(
            county=county,
            station_code=(row.get("station_code") or None),
            area=beach_name,
            advisory_type=adv_type,
            started_at=started_at,
            advisory_website=homepage or url,
            cause=cause,
        ))

    # Empty list = legitimate all-clear (no current postings). Mark success
    # so the authoritative-county demotion logic still fires for any stale
    # state-feed records in this county.
    rpt.success = True
    rpt.advisories_parsed = len(advisories)
    return advisories, rpt


def fetch_humboldt_advisories(
    client: httpx.Client, resolver: StationResolver
) -> tuple[list[CountyAdvisory], CountyReport]:
    advs, rpt = _fetch_via_ai_extract(
        client, "Humboldt", HUMBOLDT_HOMEPAGE, homepage=HUMBOLDT_HOMEPAGE
    )
    rpt.stations_in_lookup = len(resolver._beach_name_lookup.get("Humboldt", {}))
    return advs, rpt


def fetch_sonoma_advisories(
    client: httpx.Client, resolver: StationResolver
) -> tuple[list[CountyAdvisory], CountyReport]:
    advs, rpt = _fetch_via_ai_extract(
        client, "Sonoma", SONOMA_HOMEPAGE, homepage=SONOMA_HOMEPAGE
    )
    rpt.stations_in_lookup = len(resolver._beach_name_lookup.get("Sonoma", {}))
    return advs, rpt


def fetch_slo_advisories(
    client: httpx.Client, resolver: StationResolver
) -> tuple[list[CountyAdvisory], CountyReport]:
    """SLO publishes via an ArcGIS Online dashboard (SurfSafeSLO). The
    page is JS-rendered, so we use Playwright to wait for the widgets
    to populate before extracting. Counts of "Health Advisory / Rain
    Advisory / Beach Closed / Other Advisory" appear in the rendered
    page text and the LLM extractor picks up any listed beaches."""
    advs, rpt = _fetch_via_ai_extract(
        client,
        "San Luis Obispo",
        SLO_HOMEPAGE,
        homepage=SLO_HOMEPAGE,
        use_playwright=True,
        wait_for_text="beach",
    )
    rpt.stations_in_lookup = len(resolver._beach_name_lookup.get("San Luis Obispo", {}))
    return advs, rpt


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


# ---------- County-direct sample persistence ---------- #


_SAMPLES_PARQUET = "county_direct_samples.parquet"


def persist_samples(
    samples: list[CountySample],
    curated_dir: Path,
    resolver: StationResolver | None = None,
) -> tuple[int, int]:
    """Append fresh county-direct samples to county_direct_samples.parquet,
    de-duping on (county, area, sample_date, analyte). If a resolver is
    available we also fill in beach_id for any unresolved sample.

    Returns (n_new, n_total)."""
    if not samples:
        return (0, 0)

    if resolver is not None:
        for s in samples:
            if s.beach_id:
                continue
            if s.station_code:
                bid, _ = resolver.resolve_by_station_code(s.county, s.station_code)
                if bid:
                    s.beach_id = bid
                    continue
            bid, _ = resolver.resolve_by_name(s.county, s.area)
            if bid:
                s.beach_id = bid

    new_rows = pd.DataFrame([{
        "county": s.county,
        "beach_id": s.beach_id,
        "area": s.area,
        "station_code": s.station_code,
        "sample_date": s.sample_date,
        "analyte": s.analyte,
        "value": float(s.value),
        "exceeds_limit": bool(s.exceeds_limit),
        "source_url": s.source_url,
    } for s in samples])

    parquet_path = curated_dir / _SAMPLES_PARQUET
    if parquet_path.exists():
        existing = pd.read_parquet(parquet_path)
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows

    # De-dup: keep the most recent row per (county, area, sample_date, analyte).
    # This lets a re-scrape overwrite values if the county republishes them.
    combined = combined.drop_duplicates(
        subset=["county", "area", "sample_date", "analyte"],
        keep="last",
    )
    combined.to_parquet(parquet_path, index=False)
    return (len(new_rows), len(combined))


# ---------- Resolution + merge ---------- #


def resolve_advisories(
    advisories: list[CountyAdvisory],
    resolver: StationResolver,
    report: CountyReport,
    unresolved_sink: list[dict] | None = None,
) -> list[CountyAdvisory]:
    """Resolve each CountyAdvisory.beach_id via the hybrid resolver.

    G.1: any advisory we can't resolve to a known beach_id is appended
    to `unresolved_sink` so main() can persist it to
    unresolved_advisories.parquet and fail the workflow when the drop
    rate is too high. Without this, scraper bugs (e.g. ocbeachinfo.com
    schema drift) silently vanished from the active set.

    One scraped posting may resolve to SEVERAL beaches (a district-wide
    notice over a multi-point beach group); each gets its own
    CountyAdvisory so downstream merge logic stays one-row-per-beach."""
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
        beach_ids, kind = resolver.resolve_all_by_name(ca.county, ca.area)
        if beach_ids:
            if kind == "csv":
                report.matched_via_csv += 1
            elif kind == "fuzzy":
                report.matched_via_fuzzy += 1
            else:
                report.matched_via_live_list += 1
            ca.beach_id = beach_ids[0]
            resolved.append(ca)
            # Fan-out: replicate the posting onto every other covered beach.
            for extra_id in beach_ids[1:]:
                resolved.append(replace(ca, beach_id=extra_id))
        else:
            report.unmatched_names.append(ca.area)
            if unresolved_sink is not None:
                started_naive = (
                    ca.started_at.tz_localize(None)
                    if (ca.started_at is not None and ca.started_at.tzinfo is not None)
                    else ca.started_at
                )
                unresolved_sink.append({
                    "source_county": ca.county,
                    "scraped_name": ca.area,
                    "scraped_name_normalized": _normalize_name(ca.area),
                    "scraped_date": started_naive,
                    "scraped_at": pd.Timestamp.now(tz="UTC").tz_localize(None),
                })
    return resolved


# ---------- Unresolved-advisory observability (G.1) ---------- #


_UNRESOLVED_PARQUET = "unresolved_advisories.parquet"

# Soft floor (G.1): more than this many UNEXPECTED unresolved advisories marks
# the run as gate-failed. Tracks the absolute pain threshold ("OC's whole schema
# changed and we silently dropped 12 entries").
_UNRESOLVED_ABSOLUTE_FLOOR = 5

# Relative threshold (G.1): if more than 10% of scraped advisories failed
# to resolve, mark the run gate-failed. Tracks proportional regressions for
# counties that publish a small number per day.
_UNRESOLVED_RATIO_THRESHOLD = 0.10

# Hard abort (G.1/C2): at this many unexpected unresolved names the advisory
# feed itself is untrustworthy — a county's schema has moved under us — and the
# run must stop BEFORE training consumes advisory_active_prev_14d. Below it, the
# soft gate keeps the pipeline running and fails the job after the commit (see
# the module docstring and scripts/verify_scraper_gate.py).
_UNRESOLVED_HARD_FLOOR = 15

# Static allowlist of venues that have no beach_id to resolve to.
_UNMAPPED_VENUES_CSV = (
    Path(__file__).resolve().parent.parent
    / "app" / "data" / "pipeline" / "_static_data"
    / "unmapped_advisory_venues.csv"
)

# Where the gate verdict is published for scripts/verify_scraper_gate.py.
_HEALTH_FILE = "system_health.json"


def load_unmapped_venues(
    path: Path | None = None,
    today: pd.Timestamp | None = None,
) -> dict[tuple[str, str], str]:
    """Load the known-unmapped venue allowlist.

    Returns { (county, normalized_name): reason } for entries whose `review_by`
    date has NOT passed. An expired row is dropped from the allowlist so the
    venue starts counting against the gate again — the allowlist is a deferral,
    not a permanent mute. A malformed or missing file yields an empty allowlist
    (fail-closed: everything counts).
    """
    path = path or _UNMAPPED_VENUES_CSV
    today = today or pd.Timestamp.now().normalize()
    if not path.exists():
        return {}
    try:
        # Strip whole comment LINES only. `pd.read_csv(comment="#")` truncates
        # at a '#' anywhere on the line, including inside a quoted reason, which
        # would silently drop that row's remaining columns (e.g. a future
        # justification mentioning "site #3").
        body = "".join(
            line for line in path.read_text().splitlines(keepends=True)
            if not line.lstrip().startswith("#")
        )
        frame = pd.read_csv(io.StringIO(body))
    except Exception as exc:  # pragma: no cover - defensive
        print(f"  [gate] could not load unmapped-venue allowlist: {exc}", file=sys.stderr)
        return {}

    allowed: dict[tuple[str, str], str] = {}
    for _, row in frame.iterrows():
        county = str(row.get("county") or "").strip()
        name = _normalize_name(str(row.get("scraped_name_normalized") or ""))
        if not county or not name:
            continue
        review_by = pd.to_datetime(row.get("review_by"), errors="coerce")
        if pd.notna(review_by) and review_by.normalize() < today:
            print(
                f"  [gate] allowlist entry expired ({county} / {name}, review_by="
                f"{review_by.date()}) — counting it against the gate again.",
                file=sys.stderr,
            )
            continue
        allowed[(county, name)] = str(row.get("reason") or "")
    return allowed


def load_previous_report(curated_dir: Path) -> dict:
    """Read the PREVIOUS run's county_advisories_report.json.

    Must be called before main() overwrites it. data/curated is versioned, so
    the CI checkout carries the last committed run's telemetry.
    """
    report_path = curated_dir / "county_advisories_report.json"
    if not report_path.exists():
        return {}
    try:
        return json.loads(report_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _resolved_count(report: CountyReport) -> int:
    return report.matched_via_live_list + report.matched_via_csv + report.matched_via_fuzzy


def split_unresolved(
    unresolved_rows: list[dict],
    allowlist: dict[tuple[str, str], str],
) -> tuple[list[dict], list[dict]]:
    """Partition unresolved rows into (expected, unexpected) by the allowlist."""
    expected: list[dict] = []
    unexpected: list[dict] = []
    for row in unresolved_rows:
        key = (
            str(row.get("source_county") or ""),
            str(
                row.get("scraped_name_normalized")
                or _normalize_name(str(row.get("scraped_name") or ""))
            ),
        )
        (expected if key in allowlist else unexpected).append(row)
    return expected, unexpected


def detect_county_resolution_regressions(
    reports: list[CountyReport],
    previous_payload: dict,
    unexpected_by_county: dict[str, int] | None = None,
) -> list[str]:
    """Detect counties that resolved advisories last run and resolve none now.

    This is the signal G.1 actually exists for — a county changing its naming
    convention so every posting stops matching — and it is what the ratio
    threshold only approximates. Unlike the ratio it does not depend on
    statewide scrape volume, so a quiet day cannot mask or manufacture it.

    Two things are NOT regressions:

    * a county with nothing posted today — it must have parsed advisories this
      run and resolved none of them;
    * a county whose every unresolved name is on the known-unmapped allowlist.
      EBRPD routinely posts only its freshwater venues (Lake Temescal, Big
      Break, Martinez Shoreline), none of which has a beach_id to resolve to.
      Without this check that ordinary day is a HARD failure that aborts the
      run before training and costs the whole day's forecast — the exact
      outage this gate was re-shaped to prevent, and the gate would be
      contradicting its own numerator (0 unexpected) while doing it.
      `unexpected_by_county` is that same allowlist-filtered count, so the two
      cannot disagree.
    """
    prior_resolved: dict[str, int] = {}
    for entry in (previous_payload.get("counties") or []):
        if not isinstance(entry, dict):
            continue
        prior_resolved[str(entry.get("county"))] = (
            int(entry.get("matched_via_live_list") or 0)
            + int(entry.get("matched_via_csv") or 0)
            + int(entry.get("matched_via_fuzzy") or 0)
        )

    regressions: list[str] = []
    for report in reports:
        if not report.success or report.advisories_parsed <= 0:
            continue
        if _resolved_count(report) > 0:
            continue
        # Every name it failed on is a known-unmapped venue -> ordinary day.
        if unexpected_by_county is not None and unexpected_by_county.get(report.county, 0) <= 0:
            continue
        if prior_resolved.get(report.county, 0) > 0:
            regressions.append(
                f"{report.county}: parsed {report.advisories_parsed} advisories but resolved "
                f"0 (previous run resolved {prior_resolved[report.county]}) — the source's "
                f"naming convention likely changed."
            )
    return regressions


def persist_unresolved(
    rows: list[dict],
    curated_dir: Path,
) -> int:
    """Append unresolved advisories to unresolved_advisories.parquet so
    operators can see what got dropped. Returns the row count written
    THIS run (not historical), which the gate compares against the
    absolute floor + ratio threshold."""
    if not rows:
        return 0
    new_df = pd.DataFrame(rows)
    parquet_path = curated_dir / _UNRESOLVED_PARQUET
    if parquet_path.exists():
        try:
            existing = pd.read_parquet(parquet_path)
            combined = pd.concat([existing, new_df], ignore_index=True)
        except Exception:
            combined = new_df
    else:
        combined = new_df
    combined.to_parquet(parquet_path, index=False)
    return len(new_df)


def evaluate_scraper_gate(
    unresolved_rows: list[dict],
    total_scraped: int,
    regressions: list[str],
    allowlist: dict[tuple[str, str], str],
) -> dict:
    """Score the G.1 observability gate and return the verdict payload.

    The numerator is UNEXPECTED unresolved advisories only: venues on the
    known-unmapped allowlist are reported but excluded, because a venue with no
    possible beach_id would otherwise pin the counter at the threshold forever
    and turn any single new posting into a workflow failure (which is exactly
    how the 2026-08-05 run died at 5/49 = 10.2%).

    Two severities:
      * `hard_failed` — the advisory feed cannot be trusted (mass resolution
        loss or a county-wide regression). The run must stop before training
        consumes advisory_active_prev_14d.
      * `passed=False` without `hard_failed` — a soft gate trip. The pipeline
        continues (a dropped advisory is dropped whether or not we also skip
        the forecast) and the job fails AFTER the data commit.
    """
    expected, unexpected = split_unresolved(unresolved_rows, allowlist)
    unexpected_count = len(unexpected)
    ratio = (unexpected_count / total_scraped) if total_scraped else 0.0
    over_floor = unexpected_count > _UNRESOLVED_ABSOLUTE_FLOOR
    over_ratio = total_scraped > 0 and ratio > _UNRESOLVED_RATIO_THRESHOLD
    over_hard_floor = unexpected_count > _UNRESOLVED_HARD_FLOOR

    blockers: list[str] = []
    if over_hard_floor:
        blockers.append(
            f"{unexpected_count} advisories failed name resolution — above the hard floor "
            f"of {_UNRESOLVED_HARD_FLOOR}. The advisory feed is not trustworthy this run."
        )
    elif over_floor:
        blockers.append(
            f"{unexpected_count} advisories failed name resolution (absolute floor "
            f"{_UNRESOLVED_ABSOLUTE_FLOOR})."
        )
    if over_ratio:
        blockers.append(
            f"{ratio:.1%} of {total_scraped} scraped advisories failed name resolution "
            f"(ratio threshold {_UNRESOLVED_RATIO_THRESHOLD:.0%})."
        )
    blockers.extend(regressions)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": not blockers,
        "hard_failed": bool(over_hard_floor or regressions),
        "total_scraped": total_scraped,
        "unresolved_total": len(unresolved_rows),
        "unresolved_unexpected": unexpected_count,
        "unresolved_expected": len(expected),
        "unresolved_ratio": round(ratio, 4),
        "absolute_floor": _UNRESOLVED_ABSOLUTE_FLOOR,
        "hard_floor": _UNRESOLVED_HARD_FLOOR,
        "ratio_threshold": _UNRESOLVED_RATIO_THRESHOLD,
        "blockers": blockers,
        "unexpected_names": [
            {"county": r.get("source_county"), "name": r.get("scraped_name")}
            for r in unexpected[:25]
        ],
        "expected_names": [
            {"county": r.get("source_county"), "name": r.get("scraped_name")}
            for r in expected[:25]
        ],
        "county_regressions": regressions,
    }


def publish_scraper_gate(verdict: dict, curated_dir: Path) -> None:
    """Merge the gate verdict into system_health.json under `scraper_gate`.

    Read-modify-write so this cannot clobber what the pipeline already wrote;
    the ML training step merges into the same file afterwards. Uses the
    repo-wide strict writer so a non-finite value can never publish a bare NaN
    token and break every downstream JSON consumer (see app/core/json_safe.py).
    """
    from app.core.json_safe import write_json

    health_path = curated_dir / _HEALTH_FILE
    payload: dict = {}
    if health_path.exists():
        try:
            payload = json.loads(health_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            print(
                f"  [gate] existing {_HEALTH_FILE} unreadable ({exc}); writing a fresh one.",
                file=sys.stderr,
            )
            payload = {}
    payload["scraper_gate"] = verdict
    write_json(health_path, payload)


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

    PRECEDENCE (G.3): when a per-county scraper ran successfully AND a
    beach_id appears in the scraper's resolved output, the SCRAPER WINS
    over any state-CSV record for that beach_id. The state CSV is only
    authoritative for beaches the scraper didn't cover at all (either the
    county has no first-class scraper, or the scraper failed this run).
    This flip lives in `beach_demote` (nuke state-CSV active rows for any
    scraped beach_id) + the unconditional re-add of every county_advisory
    that resolved to a beach_id.

    Returns (n_added_to_advisories, n_demoted)."""
    advisories = pd.read_parquet(curated_dir / "advisories.parquet")
    beach_ids_covered = {ca.beach_id for ca in county_advisories if ca.beach_id}
    auth_counties = authoritative_counties or set()

    if not county_advisories and not auth_counties:
        return (0, 0)

    # Union-of-sources policy (revised 2026-05-23). For a health-safety
    # product, under-warning is worse than over-warning. Scraper silence on
    # a beach_id ≠ "no advisory" — it can mean the county website hasn't
    # synced from the State board yet (e.g. Tourmaline FM-030 on 2026-05-22:
    # State board has it active, sdbeachinfo.com cleared it the same day,
    # the State board signal is the safer one to keep). So we only demote
    # at the BEACH level when both sources see the same beach_id — there
    # the scraper's fresh data legitimately replaces the state-CSV row.
    # The previous county_demote lane (nuke any active SD record the SD
    # scraper didn't enumerate today) is removed. Stale state-feed cruft
    # is now bounded by:
    #   - G.2 auto-expire (14-day age cap, non-Chronic),
    #   - state CSV refreshes (next pull replaces the row),
    #   - the audit gate (>30d zombies fail the workflow).
    beach_demote = (
        advisories["beach_id"].isin(beach_ids_covered)
        & (advisories["status"] == "active")
    )
    keep_mask = ~beach_demote
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


# ---------- State Water Resources Control Board (beachwatch.waterboards.ca.gov) ---------- #
#
# This is a 3rd source layered on top of:
#   1. data.ca.gov "beach-advisories.csv" (state batch export, lags 1-6 months)
#   2. Per-county scrapers (county websites, sometimes lag the State board too)
# The State board's web search UI (beachwatch.waterboards.ca.gov/public/advisory.php)
# has the freshest authoritative state-level data. Discovered 2026-05-23: the CSV
# export had a 5-month gap for Tourmaline FM-030 while the UI had the current
# 2026-05-20 advisory.
#
# Per-county POSTs are required (the search form rejects "all counties").

STATE_BOARD_HOMEPAGE = "https://beachwatch.waterboards.ca.gov/public/advisory.php"

# County dropdown values from the form (HTML option value="N") → our parquet's
# canonical county name. Keep in sync with the form if they ever renumber.
STATE_BOARD_COUNTY_IDS: dict[str, int] = {
    "East Bay Parks District": 19,
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
}


def _state_board_parse_row(cells: list[str]) -> dict | None:
    """Column layout from the result table (verified 2026-05-23):
      0=Type, 1=County, 2=Station code, 3=Station name, 4=Beach name,
      5=Cause, 6=Source, 7=Substance, 8=DateOpened, 9=DateClosed, 10=Analyte
    Returns None for malformed rows."""
    if len(cells) < 10:
        return None
    type_str = cells[0].strip()
    if type_str not in ("Posting", "Closure", "Rain Advisory", "Chronic Advisory"):
        return None
    end_str = cells[9].strip()
    return {
        "type": type_str,
        "county": cells[1].strip(),
        "station_code": cells[2].strip(),
        "station_name": cells[3].strip(),
        "beach_name": cells[4].strip(),
        "cause": cells[5].strip() or None,
        "started_at": cells[8].strip(),
        "ended_at": end_str if end_str else None,
    }


def fetch_state_board_advisories(client: httpx.Client, resolver: StationResolver) -> tuple[list[CountyAdvisory], CountyReport]:
    """Scrape the State Water Board's beach advisory search UI for ACTIVE
    advisories across all 16 supported counties + East Bay Parks District.

    A row is treated as currently active when its DateClosed cell is empty.
    The State board's batch CSV export at data.ca.gov can lag this by months
    (see project_advisory_sources.md). We layer this on top of CSV + county
    scrapers via the union-policy merge so under-warning is bounded.
    """
    rpt = CountyReport(
        county="State Board",
        success=False,
        last_attempted_at=datetime.now(timezone.utc).isoformat(),
        source_url=STATE_BOARD_HOMEPAGE,
    )
    rpt.stations_in_lookup = sum(
        len(by_code) for by_code in resolver._station_code_lookup.values()
    )
    current_year = datetime.now(timezone.utc).year
    advisories: list[CountyAdvisory] = []
    counties_tried = 0
    counties_with_data = 0
    last_err: str | None = None

    for county_name, county_id in STATE_BOARD_COUNTY_IDS.items():
        counties_tried += 1
        try:
            resp = client.post(
                STATE_BOARD_HOMEPAGE,
                data={
                    "type": "",
                    "County": str(county_id),
                    "stationID": "",
                    "cause": "",
                    "source": "",
                    "substance": "",
                    "year": str(current_year),
                    "start_dt": "",
                    "end_dt": "",
                    "sort1": "`Start Date`",
                    "sort2": "DESC",
                    "submit": "Submit",
                },
                headers={"User-Agent": _BROWSER_UA},
                timeout=30.0,
            )
            resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            last_err = f"{county_name}: {e}"
            continue
        html = resp.text
        # Find <tr> with <td> cells; first row is the header, skip rows
        # without a recognized type in cell 0 (the parser returns None).
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
        county_active = 0
        for r in rows:
            cells_raw = re.findall(r"<td[^>]*>(.*?)</td>", r, re.DOTALL)
            cells = [_clean_html_text(c) for c in cells_raw]
            parsed = _state_board_parse_row(cells)
            if parsed is None:
                continue
            # ACTIVE = empty DateClosed. (Future end dates are rare but should
            # also be active; we don't see them in practice — keep simple.)
            if parsed["ended_at"]:
                continue
            started_at = _parse_iso_date(parsed["started_at"])
            if started_at is None:
                continue
            adv_type = parsed["type"]
            # Normalize Chronic Advisory → Chronic Posting (matches G.2 opt-out)
            if adv_type == "Chronic Advisory":
                adv_type = "Chronic Posting"
            # State Board lists "Rain Advisory" as its own type — funnel to
            # Posting so downstream UI treats it as an advisory chip.
            elif adv_type == "Rain Advisory":
                adv_type = "Posting"
            advisories.append(CountyAdvisory(
                county=parsed["county"] or county_name,
                station_code=parsed["station_code"] or None,
                area=parsed["beach_name"] or parsed["station_name"] or "",
                advisory_type=adv_type,
                started_at=started_at,
                advisory_website=STATE_BOARD_HOMEPAGE,
                cause=parsed["cause"],
            ))
            county_active += 1
        if county_active:
            counties_with_data += 1

    rpt.success = counties_tried > 0 and (counties_with_data > 0 or last_err is None)
    if last_err and counties_with_data == 0:
        rpt.error = f"all {counties_tried} county POSTs failed; last: {last_err}"
    return advisories, rpt


def _parse_iso_date(s: str) -> pd.Timestamp | None:
    """Parse YYYY-MM-DD into a pandas Timestamp (naive)."""
    if not s:
        return None
    try:
        return pd.Timestamp(s)
    except (ValueError, TypeError):
        return None


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
    ("San Francisco", fetch_san_francisco_advisories),
    ("Humboldt", fetch_humboldt_advisories),
    ("Sonoma", fetch_sonoma_advisories),
    ("San Luis Obispo", fetch_slo_advisories),
]

# Counties whose scraper is *new* and not yet validated. They still run and
# emit new advisories on success, but they do NOT join the authoritative set
# — so stale BeachWatch active records in those counties stay until we trust
# the new path. (Empty as of 2026-05-15 — all 12 first-class scrapers are
# authoritative.)
COUNTIES_PENDING_VALIDATION: set[str] = set()

BEST_EFFORT_COUNTIES: dict[str, list[str]] = {
    "Monterey": [
        # Both URLs return 403 even via headless Playwright (datacenter-IP WAF).
        # Resolving this requires either a residential proxy, undetected
        # chromedriver, or county outreach for an alternate data path.
        "https://www.countyofmonterey.gov/government/departments-a-h/health/environmental-health/general/public-beaches-water-quality",
        "https://www.countyofmonterey.gov/Home/Components/News/News/9999/16",
    ],
    "Santa Barbara": [
        # The Ocean Water Monitoring Program page only lists *sampling sites*,
        # not current advisory status. SB does not appear to publish current
        # postings on the public web — outreach to SB Public Health required
        # for either a live status URL or an API.
        "https://www.countyofsb.org/2263/Ocean-Water-Monitoring-Program",
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
    parser.add_argument(
        "--strict-gate",
        action="store_true",
        help="Exit non-zero on a SOFT gate trip too (default: soft trips only "
        "mark system_health.json['scraper_gate'], and scripts/verify_scraper_gate.py "
        "fails the job after the data commit). Useful when debugging locally.",
    )
    args = parser.parse_args()

    if not args.curated.exists():
        print(f"curated dir not found: {args.curated}", file=sys.stderr)
        return 1

    beaches = pd.read_parquet(args.curated / "beaches.parquet")
    resolver = StationResolver(beaches)
    # Snapshot the PREVIOUS run's telemetry before this run overwrites it —
    # detect_county_resolution_regressions compares against it.
    previous_report = load_previous_report(args.curated)
    unmapped_allowlist = load_unmapped_venues()

    all_advisories: list[CountyAdvisory] = []
    reports: list[CountyReport] = []
    unresolved_rows: list[dict] = []
    total_scraped = 0

    with RetryingClient(follow_redirects=True) as client:
        # State Water Board UI search — runs FIRST so its fresh statewide
        # active-set is in beach_ids_covered when the per-county scrapers
        # add their finer-grained data. Both populate via the union-policy
        # merge below; this just gets the state-of-record into the loop
        # early.
        if not args.only or "state" in args.only.lower():
            print("Fetching State Water Board advisories (all counties) ...")
            try:
                advs, rpt = fetch_state_board_advisories(client, resolver)
            except Exception as e:
                print(f"  ERROR for State Board: {e}", file=sys.stderr)
                rpt = CountyReport(
                    county="State Board",
                    success=False,
                    last_attempted_at=datetime.now(timezone.utc).isoformat(),
                    source_url=STATE_BOARD_HOMEPAGE,
                    error=str(e),
                )
                advs = []
            total_scraped += len(advs)
            # Authoritative per-county parse count. Every fetcher sets this
            # itself, but detect_county_resolution_regressions keys its
            # schema-drift check on it — so a fetcher that forgets must not
            # silently opt its county out of the check.
            rpt.advisories_parsed = len(advs)
            resolved = resolve_advisories(advs, resolver, rpt, unresolved_sink=unresolved_rows)
            print(
                f"  {len(advs)} parsed → {len(resolved)} resolved "
                f"(live_list={rpt.matched_via_live_list}, csv={rpt.matched_via_csv}, "
                f"fuzzy={rpt.matched_via_fuzzy}, unmatched={len(rpt.unmatched_names)})"
            )
            all_advisories.extend(resolved)
            reports.append(rpt)

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
            total_scraped += len(advs)
            # Authoritative per-county parse count. Every fetcher sets this
            # itself, but detect_county_resolution_regressions keys its
            # schema-drift check on it — so a fetcher that forgets must not
            # silently opt its county out of the check.
            rpt.advisories_parsed = len(advs)
            resolved = resolve_advisories(advs, resolver, rpt, unresolved_sink=unresolved_rows)
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
        print(
            f"\n[dry-run] would merge {len(all_advisories)} advisories + "
            f"{len(_COLLECTED_SAMPLES)} county-direct samples; skipping write"
        )
        return 0

    # Persist county-direct samples (numeric MPN values) — separate parquet
    # so they don't entangle with the advisory-status pipeline.
    if _COLLECTED_SAMPLES:
        n_new, n_total = persist_samples(_COLLECTED_SAMPLES, args.curated, resolver)
        print(
            f"  county_direct_samples.parquet: +{n_new} new rows "
            f"(de-duped total: {n_total})"
        )

    # Counties whose first-class scraper succeeded this run are authoritative:
    # they speak for ALL active records in that county, including the all-clear
    # case (Ventura's sentinel) and partial-coverage cases (county no longer
    # posts an older state-feed record).
    first_class_names = {name for name, _ in COUNTIES_FIRST_CLASS}
    authoritative_counties = {
        r.county for r in reports
        if r.county in first_class_names
        and r.success
        and r.county not in COUNTIES_PENDING_VALIDATION
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

    # G.1: persist unresolved advisories + fail loudly if too many got
    # dropped this run. A silent "Salt Creek vanished" is the failure mode
    # we're trying to eliminate — make it a workflow-stopping signal so the
    # operator sees it before the bad data ships to prod.
    unresolved_count = persist_unresolved(unresolved_rows, args.curated)
    # Score regressions on the SAME allowlist-filtered counts the gate uses, so
    # a day of only known-unmapped postings can never hard-fail the run.
    _, _unexpected_rows = split_unresolved(unresolved_rows, unmapped_allowlist)
    unexpected_by_county: dict[str, int] = {}
    for _row in _unexpected_rows:
        _cty = str(_row.get("source_county") or "")
        unexpected_by_county[_cty] = unexpected_by_county.get(_cty, 0) + 1
    regressions = detect_county_resolution_regressions(
        reports, previous_report, unexpected_by_county
    )
    verdict = evaluate_scraper_gate(
        unresolved_rows,
        total_scraped,
        regressions,
        unmapped_allowlist,
    )
    publish_scraper_gate(verdict, args.curated)

    by_county: dict[str, int] = {}
    for row in unresolved_rows:
        by_county[row["source_county"]] = by_county.get(row["source_county"], 0) + 1

    print("\n--- Unresolved advisories (G.1) ---")
    print(
        f"  scraped={total_scraped}  unresolved={unresolved_count} "
        f"(unexpected={verdict['unresolved_unexpected']}, "
        f"known-unmapped={verdict['unresolved_expected']})  "
        f"ratio={verdict['unresolved_ratio']:.1%}  floor={_UNRESOLVED_ABSOLUTE_FLOOR}  "
        f"max_ratio={_UNRESOLVED_RATIO_THRESHOLD:.0%}  hard_floor={_UNRESOLVED_HARD_FLOOR}"
    )
    if by_county:
        for county_name in sorted(by_county):
            print(f"    {county_name:24s} {by_county[county_name]:3d}")
    if unresolved_rows:
        allowed_keys = set(unmapped_allowlist)
        for row in unresolved_rows[:10]:
            key = (str(row["source_county"]), str(row.get("scraped_name_normalized") or ""))
            tag = "known-unmapped" if key in allowed_keys else "dropped"
            print(f"    [{tag}] {row['source_county']:20s} {str(row['scraped_name'])[:60]}")

    if verdict["passed"]:
        return 0

    severity = "HARD FAIL" if verdict["hard_failed"] else "FAIL (soft)"
    print(
        f"\n{severity}: scraper observability gate tripped. "
        f"See {args.curated / _UNRESOLVED_PARQUET} for the full list. "
        f"Likely cause: a county source changed its naming convention "
        f"and the resolver lookup needs a new alias or station-code mapping.",
        file=sys.stderr,
    )
    for blocker in verdict["blockers"]:
        print(f"  - {blocker}", file=sys.stderr)

    if verdict["hard_failed"] or args.strict_gate:
        return 1

    # Soft trip: keep the pipeline running so the day still gets a forecast.
    # The dropped advisories are dropped either way — aborting here does not
    # recover them, it only also costs the forecast (which is exactly what
    # happened on 2026-08-05). scripts/verify_scraper_gate.py reads the verdict
    # we just published and fails the job AFTER the data commit, so the state
    # is auditable in git before notify-failure fires.
    print(
        "  → continuing: the verdict is published to "
        f"{_HEALTH_FILE}['scraper_gate'] and verify_scraper_gate.py will fail "
        "the job after the data commit.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
