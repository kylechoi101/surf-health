from datetime import date

import pandas as pd

from app.data.pipeline.solar_wind import solar_wind_backfill_plan

FULL = date(2020, 1, 1)


def _existing(rows):
    return pd.DataFrame(rows, columns=["station_id", "sample_date"])


def test_cells_that_joined_late_or_are_absent_get_backfilled():
    existing = _existing([
        ("34.0_-118.5", "2020-01-01"),
        ("34.0_-118.5", "2026-10-13"),
        ("37.7_-122.4", "2026-04-20"),
        ("37.7_-122.4", "2026-10-13"),
    ])
    locs = [(34.0, -118.5), (37.7, -122.4), (32.6, -117.1)]
    cells, _ = solar_wind_backfill_plan(existing, locs, FULL, date(2026, 10, 6))
    assert cells == [(32.6, -117.1), (37.7, -122.4)]


def test_ranges_are_calendar_years_ending_the_day_before_the_incremental_start():
    existing = _existing([("37.7_-122.4", "2026-04-20")])
    _, ranges = solar_wind_backfill_plan(existing, [(37.7, -122.4)], FULL, date(2026, 10, 6))
    assert ranges[0] == (date(2020, 1, 1), date(2020, 12, 31))
    assert ranges[-1] == (date(2026, 1, 1), date(2026, 10, 5))
    assert len(ranges) == 7


def test_nothing_to_do_when_every_cell_has_history():
    existing = _existing([("34.0_-118.5", "2020-01-01")])
    cells, ranges = solar_wind_backfill_plan(existing, [(34.0, -118.5)], FULL, date(2026, 10, 6))
    assert cells == [] and ranges == []


def test_a_cell_within_the_tolerance_is_not_refetched():
    existing = _existing([("34.0_-118.5", "2020-01-20")])
    cells, _ = solar_wind_backfill_plan(existing, [(34.0, -118.5)], FULL, date(2026, 10, 6))
    assert cells == []


def test_no_file_means_every_cell_is_backfilled():
    cells, ranges = solar_wind_backfill_plan(None, [(34.0, -118.5)], FULL, date(2020, 3, 1))
    assert cells == [(34.0, -118.5)]
    assert ranges == [(date(2020, 1, 1), date(2020, 2, 29))]
