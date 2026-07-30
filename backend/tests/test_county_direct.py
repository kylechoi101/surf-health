"""County-direct sample source: normalization, gap-fill merge, recency stamp."""

from __future__ import annotations

import pandas as pd

from app.data.pipeline.cli import refresh_latest_official_sample_at
from app.data.pipeline.county_direct import (
    DATA_SOURCE,
    merge_county_direct_into_observations,
    normalize_county_direct_samples,
)


def _stations():
    return pd.DataFrame(
        [
            {"beach_id": "sf-alpha", "station_code": "OCEAN#18_SL", "usepa_id": "CA1",
             "county": "San Francisco", "beach_name": "Ocean Beach"},
            {"beach_id": "sf-beta", "station_code": "BAY#301.2_SL", "usepa_id": "CA2",
             "county": "San Francisco", "beach_name": "Jack Rabbit Beach"},
        ]
    )


def _direct(beach_id, date, value, analyte="ENTEROCOCCUS", county="San Francisco",
            station="OCEAN#18_SL"):
    return {
        "county": county, "beach_id": beach_id, "area": station, "station_code": station,
        "sample_date": pd.Timestamp(date), "analyte": analyte, "value": value,
        "exceeds_limit": False, "source_url": "https://data.sfgov.org/resource/v3fv-x3ux.json",
    }


def _observation(beach_id, sample_time, value, source="BeachWatch.SafeToSwim"):
    return {
        "beach_id": beach_id, "sample_time": pd.Timestamp(sample_time),
        "sample_date": pd.Timestamp(sample_time).date(), "analyte": "enterococcus",
        "method": "SM 9230 D", "units": "MPN/100ml", "value": value, "exceeds_stv": False,
        "county": "San Francisco", "station_name": "OCEAN#18_SL", "beach_name": "Ocean Beach",
        "usepa_id": "CA1", "data_source": source,
    }


def test_normalizes_to_the_culture_threshold_not_the_molecular_one():
    """The feed reports MPN/100mL, so 201 must exceed the 104 culture STV.

    Units are asserted because compute_exceeds_stv is method-aware: a row that
    failed to declare culture units would be judged against the 1413-copies
    molecular threshold and silently stop flagging real exceedances.
    """
    raw = pd.DataFrame([
        _direct("sf-beta", "2026-07-27", 201.0, station="BAY#301.2_SL"),
        _direct("sf-alpha", "2026-07-27", 10.0),
    ])
    out = normalize_county_direct_samples(raw, _stations(), 104.0, now=pd.Timestamp("2026-07-30"))
    assert out["units"].eq("MPN/100mL").all()
    by_beach = out.set_index("beach_id")["exceeds_stv"]
    assert bool(by_beach["sf-beta"]) is True
    assert bool(by_beach["sf-alpha"]) is False
    assert out["data_source"].eq(DATA_SOURCE).all()


def test_keeps_enterococcus_only_and_allowlisted_counties_only():
    raw = pd.DataFrame([
        _direct("sf-alpha", "2026-07-27", 10.0),
        _direct("sf-alpha", "2026-07-27", 4200.0, analyte="FECAL_COLIFORM"),
        _direct("sf-alpha", "2026-07-27", 50.0, analyte="TOTAL_COLIFORM"),
        _direct("other", "2026-07-27", 10.0, county="Sonoma"),
    ])
    out = normalize_county_direct_samples(raw, _stations(), 104.0, now=pd.Timestamp("2026-07-30"))
    assert len(out) == 1
    assert out.iloc[0]["analyte"] == "enterococcus"
    assert out.iloc[0]["county"] == "San Francisco"


def test_drops_unknown_beach_ids_and_bad_values():
    raw = pd.DataFrame([
        _direct("not-in-beaches", "2026-07-27", 10.0),
        _direct("sf-alpha", "2026-07-27", -1000.0),
        _direct("sf-beta", "2026-08-30", 10.0, station="BAY#301.2_SL"),  # future
        _direct("sf-alpha", "2026-07-20", 33.0),
    ])
    out = normalize_county_direct_samples(raw, _stations(), 104.0, now=pd.Timestamp("2026-07-30"))
    assert len(out) == 1
    assert out.iloc[0]["value"] == 33.0


def test_mirror_of_an_existing_sample_is_skipped_despite_a_different_clock_time():
    """THE regression this source can cause.

    The state feed carries real collection times; this feed is date-only. Keyed
    on sample_time the same physical sample hashes apart, which would have
    inserted 206 duplicate SF rows over the measured overlap window. The key is
    the DATE, so the existing row must survive alone and untouched.
    """
    observations = pd.DataFrame([_observation("sf-alpha", "2026-06-29 10:25:00", 52.0)])
    direct = normalize_county_direct_samples(
        pd.DataFrame([_direct("sf-alpha", "2026-06-29", 52.0)]),
        _stations(), 104.0, now=pd.Timestamp("2026-07-30"),
    )
    merged = merge_county_direct_into_observations(observations, direct)
    assert len(merged) == 1
    assert merged.iloc[0]["data_source"] == "BeachWatch.SafeToSwim"
    assert merged.iloc[0]["sample_time"] == pd.Timestamp("2026-06-29 10:25:00")


def test_mirror_is_skipped_even_when_the_reported_value_disagrees():
    """A revised value is still the same sample, not a second one.

    Value is deliberately OUT of the merge key: including it would let a
    re-reported result slip in as a duplicate beach-day.
    """
    observations = pd.DataFrame([_observation("sf-alpha", "2026-06-29 10:25:00", 52.0)])
    direct = normalize_county_direct_samples(
        pd.DataFrame([_direct("sf-alpha", "2026-06-29", 71.0)]),
        _stations(), 104.0, now=pd.Timestamp("2026-07-30"),
    )
    merged = merge_county_direct_into_observations(observations, direct)
    assert len(merged) == 1
    assert merged.iloc[0]["value"] == 52.0


def test_fills_beach_days_no_other_source_covers():
    observations = pd.DataFrame([_observation("sf-alpha", "2026-06-29 10:25:00", 52.0)])
    direct = normalize_county_direct_samples(
        pd.DataFrame([
            _direct("sf-alpha", "2026-06-29", 52.0),   # mirror -> skipped
            _direct("sf-alpha", "2026-07-06", 10.0),   # new
            _direct("sf-alpha", "2026-07-27", 201.0),  # new, exceeds
        ]),
        _stations(), 104.0, now=pd.Timestamp("2026-07-30"),
    )
    merged = merge_county_direct_into_observations(observations, direct)
    assert len(merged) == 3
    added = merged.loc[merged["data_source"] == DATA_SOURCE]
    assert sorted(pd.to_datetime(added["sample_time"]).dt.strftime("%Y-%m-%d")) == [
        "2026-07-06", "2026-07-27",
    ]
    assert bool(added.loc[added["value"] == 201.0, "exceeds_stv"].iloc[0]) is True


def test_empty_direct_frame_leaves_observations_identical():
    observations = pd.DataFrame([_observation("sf-alpha", "2026-06-29 10:25:00", 52.0)])
    merged = merge_county_direct_into_observations(observations, pd.DataFrame())
    pd.testing.assert_frame_equal(merged, observations)


def test_refresh_latest_official_sample_at_advances_a_stale_stamp():
    """Guards the 63-day Orange County regression.

    A source merged in after bundle construction leaves this stamp frozen at
    whatever history existed at build time -- and it is what the apps render as
    "last sampled", so a stale stamp shows users a two-month-old date next to a
    fresh forecast.
    """
    stations = pd.DataFrame([
        {"beach_id": "sf-alpha", "latest_official_sample_at": pd.Timestamp("2026-06-29 10:25:00")},
        {"beach_id": "sf-beta", "latest_official_sample_at": pd.Timestamp("2026-06-29 11:00:00")},
    ])
    observations = pd.DataFrame([
        _observation("sf-alpha", "2026-06-29 10:25:00", 52.0),
        _observation("sf-alpha", "2026-07-27 00:00:00", 201.0, source=DATA_SOURCE),
    ])
    out = refresh_latest_official_sample_at(stations, observations)
    stamps = out.set_index("beach_id")["latest_official_sample_at"]
    assert stamps["sf-alpha"] == pd.Timestamp("2026-07-27 00:00:00")
    # A beach with no observations keeps its previous stamp rather than nulling.
    assert stamps["sf-beta"] == pd.Timestamp("2026-06-29 11:00:00")
    assert list(out.columns) == list(stations.columns)
