"""Scalar coercion shared by the two BeachRepository backends.

``CuratedBeachRepository`` (parquet) and ``ServingSnapshotRepository`` (sqlite)
are interchangeable behind the same API — ``factory.build_repository`` picks the
snapshot when ``serving.sqlite`` exists and falls back to curated otherwise, so
both are live paths and must answer identically.

They each carried a private copy of these four helpers, and two had already
drifted:

    _safe_float("nan")  curated -> nan   serving -> None
    _safe_int("nan")    curated -> raises ValueError (uncaught!)  serving -> None

The serving semantics are kept here because they are strictly safer: casting
first and testing ``isnan`` on the result catches the string ``"nan"`` as well as
``NaT``/``pd.NA``/``None`` (those raise inside ``float()`` and are caught), while
the curated ``pd.isna(value)`` pre-check returns False for a non-empty string and
falls through.
"""

from __future__ import annotations

import re
from math import isnan


def safe_float(value: object) -> float | None:
    """Best-effort float, or None for anything null-ish or unparseable."""
    try:
        if value is None:
            return None
        parsed = float(value)
        return None if isnan(parsed) else parsed
    except (TypeError, ValueError):
        return None


def safe_int(value: object) -> int | None:
    number = safe_float(value)
    return int(number) if number is not None else None


def safe_bool(value: object, *, default: bool = True) -> bool:
    """Parse a boolean that may have been stored as string/int in parquet/SQLite."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        return value.lower() not in ("0", "false", "no", "")
    return default


def coerce_advisory_website(raw: object) -> str | None:
    """Advisory URL, or None when absent or a literal 'unknown' placeholder."""
    if raw is None:
        return None
    if isinstance(raw, float) and isnan(raw):
        return None
    text = str(raw).strip()
    if not text or text.lower() == "unknown":
        return None
    return text


def derive_friendly_name(
    beach_id: str,
    county: str,
    station_name: str,
    beach_name: str = "",
) -> str:
    """The user-facing name for a station, from its curated fields.

    Prefers an explicit ``beach_name`` and returns it unchanged — downstream
    products can surface the station separately, and the canonical beach name
    must not shift when station metadata does. Only when it is blank do we
    de-slug ``beach_id`` (dropping the ``ca#####-`` prefix, the county slug and
    a trailing station slug), then append the station in parentheses when it
    adds information.

    Both repositories had a copy and they disagreed: the curated one ignored
    ``beach_name`` entirely, so the same station rendered as
    'Long Beach City Long Beach B 10' on the parquet fallback path and
    'Long Beach' on the sqlite path. The curated copy also leaked the raw
    jurisdiction slug, because ``beach_id`` is minted from the UNCORRECTED
    county ('long-beach-city') while ``county`` is later corrected to
    'Los Angeles' by county_corrections — so the county-slug strip below no
    longer matches and the prefix survives into the displayed name.
    """
    b_name = str(beach_name or "").strip()
    station_raw = str(station_name or "")

    if b_name:
        return b_name

    stem = re.sub(r"^ca\d+-", "", str(beach_id))
    county_slug = str(county or "").lower().replace(" ", "-")
    if county_slug and stem.startswith(county_slug + "-"):
        stem = stem[len(county_slug) + 1 :]
    station_slug = re.sub(r"[^a-z0-9]+", "-", station_raw.lower()).strip("-")
    if station_slug and stem.endswith("-" + station_slug):
        stem = stem[: -(len(station_slug) + 1)]
    b_name = stem.replace("-", " ").title() if stem else station_raw

    if (
        b_name
        and station_raw
        and b_name.lower() != station_raw.lower()
        and station_raw.lower() not in b_name.lower()
    ):
        return f"{b_name} ({station_raw})"
    return b_name or station_raw
