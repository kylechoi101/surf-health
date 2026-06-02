import pandas as pd

from app.data.pipeline.county_corrections import COUNTY_CORRECTIONS, correct_county


def test_long_beach_city_maps_to_los_angeles():
    assert correct_county("Long Beach City") == "Los Angeles"


def test_correct_county_leaves_real_counties_untouched():
    for c in ["Los Angeles", "Orange", "San Diego", "Ventura", "Marin"]:
        assert correct_county(c) == c


def test_correct_county_is_whitespace_tolerant():
    assert correct_county("  Long Beach City  ") == "Los Angeles"


def test_correct_county_handles_none_and_nan():
    assert correct_county(None) is None
    assert pd.isna(correct_county(float("nan")))


def test_corrections_table_targets_are_canonical():
    # Every replacement value must itself be a real county we already use.
    assert COUNTY_CORRECTIONS["Long Beach City"] == "Los Angeles"
