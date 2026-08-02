"""Guard the map layer's advisory rendering.

``bake_conditions_map.py`` feeds the web map's bacteria field. It is curl'd
standalone by shorelife-web's deploy and cannot import the app package, so it
VENDORS the active-advisory rule from ``bake_web_static``. These tests pin the
two copies together and pin the behaviour the vendoring exists to produce.

The bug they lock down: `_wq_severity` gated full severity on
``band == "Advisory"``, but ``risk_band`` has not carried that value since
a2556455d made it "always the model's band" — the advisory moved to a separate
flag. The branch was dead, the baker never loaded advisories.parquet at all, and
no posted beach ever rendered purple on the map.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from scripts import bake_conditions_map as m
from scripts import bake_web_static as web


def _advisories(rows):
    return pd.DataFrame(
        [
            {
                "beach_id": bid,
                "status": status,
                "advisory_type": atype,
                "started_at": started,
                "advisory_website": None,
            }
            for bid, status, atype, started in rows
        ]
    )


def _days_ago(n):
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=n)


def test_vendored_active_set_matches_the_web_baker():
    """The two bakers must agree on who is posted, or the map and the beach
    cards will disagree — the same class of split that made Dillon Beach show
    High on the card and Low on the detail."""
    adv = _advisories(
        [
            ("fresh-posting", "active", "Posting", _days_ago(2)),
            ("stale-posting", "active", "Posting", _days_ago(40)),
            ("old-closure", "active", "Closure", _days_ago(300)),
            ("inactive", "historical", "Posting", _days_ago(1)),
        ]
    )
    mine = m._active_advisory_set(adv)
    theirs, _ = web._active_advisory_set(adv)
    assert mine == theirs, f"map baker {mine} disagrees with web baker {theirs}"


def test_window_and_closure_exemption():
    adv = _advisories(
        [
            ("fresh-posting", "active", "Posting", _days_ago(2)),
            ("stale-posting", "active", "Posting", _days_ago(40)),
            ("old-closure", "active", "Closure", _days_ago(300)),
            ("inactive", "historical", "Posting", _days_ago(1)),
        ]
    )
    got = m._active_advisory_set(adv)
    assert "fresh-posting" in got
    assert "old-closure" in got, "closures bypass the 14-day acute window"
    assert "stale-posting" not in got, "a 40-day-old posting is a zombie"
    assert "inactive" not in got


def test_window_constant_matches_the_web_baker():
    assert m.ACTIVE_WINDOW_DAYS == web.ACTIVE_WINDOW_DAYS


def test_empty_or_schemaless_advisories_are_safe():
    assert m._active_advisory_set(pd.DataFrame()) == set()
    assert m._active_advisory_set(pd.DataFrame({"beach_id": ["x"]})) == set()


def test_posted_beach_gets_full_severity_and_reaches_the_map(tmp_path):
    """End-to-end: a posted beach with NO other layer must still be emitted, or
    the purple has nothing to draw on."""
    pd.DataFrame(
        [
            {"beach_id": "posted", "name": "Posted Beach", "latitude": 33.0, "longitude": -118.0},
            {"beach_id": "clean", "name": "Clean Beach", "latitude": 33.1, "longitude": -118.1},
        ]
    ).to_parquet(tmp_path / "beaches.parquet")
    _advisories([("posted", "active", "Posting", _days_ago(1))]).to_parquet(
        tmp_path / "advisories.parquet"
    )
    pd.DataFrame(
        [
            {"beach_id": "posted", "risk_band": "Low", "p_exceed": 0.02},
            {"beach_id": "clean", "risk_band": "Low", "p_exceed": 0.02},
        ]
    ).to_parquet(tmp_path / "forecasts.parquet")

    rows = {r["id"]: r for r in m.bake_conditions(tmp_path)}

    assert "posted" in rows, "a posted beach must reach the map even with no other layer"
    assert rows["posted"]["has_advisory"] is True
    assert rows["posted"]["wq"] == 1.0, "an active posting pins severity to full"
    assert rows["clean"]["has_advisory"] is False
    assert rows["clean"]["wq"] < 1.0


def test_severity_comes_from_the_advisory_flag_not_the_band_string(tmp_path):
    """`risk_band` has not carried 'Advisory' since a2556455d, so severity must
    key off the flag. A row that somehow still carried that band string, with no
    active advisory behind it, must NOT be pinned to full severity."""
    pd.DataFrame(
        [{"beach_id": "b", "name": "B", "latitude": 33.0, "longitude": -118.0}]
    ).to_parquet(tmp_path / "beaches.parquet")
    _advisories([("other", "active", "Posting", _days_ago(1))]).to_parquet(
        tmp_path / "advisories.parquet"
    )
    pd.DataFrame(
        [{"beach_id": "b", "risk_band": "Advisory", "p_exceed": 0.02}]
    ).to_parquet(tmp_path / "forecasts.parquet")

    row = next(r for r in m.bake_conditions(tmp_path) if r["id"] == "b")
    assert row["has_advisory"] is False
    assert row["wq"] < 1.0, "the band string must not drive severity"
