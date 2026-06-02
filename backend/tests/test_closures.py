import pandas as pd

from app.data.pipeline.closures import build_closures_feed, closure_id


def _beaches():
    return pd.DataFrame(
        [
            {"beach_id": "ca1-a", "name": "Black's Beach", "county": "San Diego",
             "latitude": 32.89, "longitude": -117.25},
            {"beach_id": "ca2-b", "name": "Doheny", "county": "Orange",
             "latitude": 33.46, "longitude": -117.68},
        ]
    )


def _advisories():
    return pd.DataFrame(
        [
            {"beach_id": "ca1-a", "advisory_type": "Closure", "started_at": "2026-05-30T08:00:00",
             "ended_at": None, "status": "active", "cause": "Sewage", "county": "San Diego",
             "advisory_website": "https://sd.example/adv"},
            {"beach_id": "ca2-b", "advisory_type": "Posting", "started_at": "2020-01-01T08:00:00",
             "ended_at": "2020-01-05T08:00:00", "status": "historical", "cause": "X",
             "county": "Orange", "advisory_website": None},
        ]
    )


def test_feed_contains_only_active_closures_with_coords():
    feed = build_closures_feed(_advisories(), _beaches())
    assert len(feed) == 1
    row = feed[0]
    assert row["beach_id"] == "ca1-a"
    assert row["name"] == "Black's Beach"
    assert row["latitude"] == 32.89 and row["longitude"] == -117.25
    assert row["advisory_type"] == "Closure"
    assert row["cause"] == "Sewage"
    assert row["advisory_website"] == "https://sd.example/adv"


def test_closure_id_is_stable_and_present():
    feed = build_closures_feed(_advisories(), _beaches())
    cid = feed[0]["closure_id"]
    # stable: recomputing from the same (beach_id, started_at) gives the same id
    assert cid == closure_id("ca1-a", "2026-05-30T08:00:00")
    assert isinstance(cid, str) and len(cid) >= 8


def test_closure_id_differs_by_beach_and_start():
    assert closure_id("ca1-a", "2026-05-30T08:00:00") != closure_id("ca2-b", "2026-05-30T08:00:00")
    assert closure_id("ca1-a", "2026-05-30T08:00:00") != closure_id("ca1-a", "2026-06-01T08:00:00")


def test_active_closure_without_coords_is_dropped():
    # A closure whose beach isn't in the roster has no lat/lon → can't do proximity → excluded.
    adv = _advisories().iloc[[0]].assign(beach_id="ghost-beach")
    feed = build_closures_feed(adv, _beaches())
    assert feed == []


def test_empty_inputs_return_empty_feed():
    assert build_closures_feed(pd.DataFrame(), _beaches()) == []
