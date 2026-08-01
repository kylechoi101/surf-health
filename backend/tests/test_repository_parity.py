"""Differential parity between the two interchangeable BeachRepository backends.

`factory.build_repository` serves `ServingSnapshotRepository` when
`serving.sqlite` exists and falls back to `CuratedBeachRepository` otherwise, so
both are live paths and must answer identically. They each carried private copies
of these helpers and two had already drifted in production:

    _safe_float("nan")  curated -> nan    serving -> None
    _safe_int("nan")    curated -> raises ValueError (uncaught)  serving -> None
    _derive_friendly_name  curated ignored beach_name entirely, so one station
        rendered as 'Long Beach City Long Beach B 10' on the parquet path and
        'Long Beach' on the sqlite path.

Nothing compared them, so the drift was invisible. This is the guard — modelled
on test_bake_web_static.py's vendored-vs-canonical sweep, which is the only other
parity test in the suite.
"""

import sqlite3

import pandas as pd
import pytest

from app.repositories import curated_repository as curated
from app.repositories import serving_repository as serving


COERCION_INPUTS = [
    None,
    "",
    "   ",
    "nan",
    "NaN",
    "inf",
    float("nan"),
    float("inf"),
    0,
    0.0,
    12.5,
    "12.5",
    -1,
    True,
    False,
    "true",
    "false",
    "no",
    "unknown",
    "Unknown",
    "https://example.gov/advisory",
    pd.NaT,
    pd.NA,
    object(),
]


@pytest.mark.parametrize("value", COERCION_INPUTS, ids=lambda v: repr(v)[:24])
def test_scalar_coercers_agree_across_backends(value):
    """Same input, same answer (or same exception) from either backend."""

    def call(fn):
        try:
            return ("ok", repr(fn(value)))
        except Exception as exc:  # noqa: BLE001 — parity includes failure modes
            return ("raise", type(exc).__name__)

    for name in ("_safe_float", "_safe_int", "_safe_bool", "_coerce_advisory_website"):
        got_curated = call(getattr(curated, name))
        got_serving = call(getattr(serving, name))
        assert got_curated == got_serving, (
            f"{name}({value!r}) diverged: curated={got_curated} serving={got_serving}"
        )


def test_safe_int_does_not_raise_on_the_string_nan():
    """The concrete regression: a 'nan' string in a parquet column made the
    curated path raise an uncaught ValueError where serving returned None."""
    assert curated._safe_int("nan") is None
    assert serving._safe_int("nan") is None
    assert curated._safe_float("nan") is None


NAME_ROWS = [
    # beach_id, county, station name, beach_name
    ("ca279698-long-beach-city-long-beach-b-10", "Los Angeles", "55th Place-Beach", "Long Beach"),
    ("ca133077-long-beach-city-alamitos-bay-beach-b-14", "Los Angeles", "B-14", "Alamitos Bay Beach"),
    # No explicit beach_name -> both must de-slug identically.
    ("ca123456-orange-main-beach-main-beach-pier", "Orange", "Main Beach Pier", ""),
    # County slug does not match the id stem (the corrected-county case).
    ("ca999999-long-beach-city-belmont-pier", "Los Angeles", "Belmont Pier", ""),
    # Degenerate rows.
    ("ca000001-orange-x", "Orange", "", ""),
]


@pytest.mark.parametrize("beach_id,county,station,beach_name", NAME_ROWS)
def test_friendly_name_agrees_across_backends(tmp_path, beach_id, county, station, beach_name):
    """The curated (dict/parquet) and serving (sqlite3.Row) wrappers must produce
    the same display name for the same underlying record."""
    curated_name = curated._derive_friendly_name(
        {"beach_id": beach_id, "county": county, "name": station, "beach_name": beach_name}
    )

    db = tmp_path / "rows.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "create table beaches (beach_id text, county text, name text, beach_name text)"
        )
        conn.execute(
            "insert into beaches values (?, ?, ?, ?)", (beach_id, county, station, beach_name)
        )
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("select * from beaches").fetchone()
    serving_name = serving._derive_friendly_name(row)

    assert curated_name == serving_name, (
        f"{beach_id}: curated={curated_name!r} serving={serving_name!r}"
    )


def test_friendly_name_prefers_explicit_beach_name_over_the_id_slug():
    """The user-visible half of the drift: beach_id is minted from the
    UNCORRECTED county ('long-beach-city') while county is later corrected to
    'Los Angeles', so slug-stripping alone leaks the jurisdiction into the name."""
    name = curated._derive_friendly_name(
        {
            "beach_id": "ca279698-long-beach-city-long-beach-b-10",
            "county": "Los Angeles",
            "name": "55th Place-Beach",
            "beach_name": "Long Beach",
        }
    )
    assert name == "Long Beach"
    assert "Long Beach City" not in name
