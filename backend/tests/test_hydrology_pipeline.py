"""Tests for streamflow aggregation: cutoff safety, deduplication, provisional flags."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.data.connectors.hydrology_sources import _atomic_to_parquet
from app.data.pipeline.hydrology import (
    _forecast_cutoff_utc,
    aggregate_streamflow_windows,
    build_beach_hydrology_daily,
)


class TestAtomicToParquet:
    def test_write_produces_readable_parquet(self, tmp_path):
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        target = tmp_path / "cache.parquet"
        _atomic_to_parquet(df, target)
        assert target.exists()
        pd.testing.assert_frame_equal(pd.read_parquet(target), df)

    def test_no_leftover_tmp_after_success(self, tmp_path):
        target = tmp_path / "cache.parquet"
        _atomic_to_parquet(pd.DataFrame({"a": [1]}), target)
        # The .tmp staging file is renamed away on success — it must not shadow the real file.
        assert not (tmp_path / "cache.parquet.tmp").exists()
        assert list(tmp_path.glob("*.tmp")) == []

    def test_overwrite_replaces_atomically(self, tmp_path):
        target = tmp_path / "cache.parquet"
        _atomic_to_parquet(pd.DataFrame({"a": [1]}), target)
        _atomic_to_parquet(pd.DataFrame({"a": [9, 9]}), target)
        out = pd.read_parquet(target)
        assert out["a"].tolist() == [9, 9]

    def test_leftover_tmp_does_not_shadow_real_file(self, tmp_path):
        """A corrupt/leftover .tmp from a prior crash must not affect reads of the real file."""
        target = tmp_path / "cache.parquet"
        _atomic_to_parquet(pd.DataFrame({"a": [1, 2]}), target)
        # Simulate a leftover staging file from a crashed prior write.
        (tmp_path / "cache.parquet.tmp").write_bytes(b"garbage-not-parquet")
        out = pd.read_parquet(target)
        assert out["a"].tolist() == [1, 2]


def _make_iv_row(gage_id: str, time_utc: str, discharge_cfs: float, provisional: bool = False) -> dict:
    return {
        "gage_id": gage_id,
        "time_utc": time_utc,
        "discharge_cfs": discharge_cfs,
        "gage_height_ft": np.nan,
        "provisional": provisional,
        "source_name": "usgs_nwis",
    }


class TestAggregateStreamflowWindows:
    def test_empty_input_returns_correct_columns(self):
        result = aggregate_streamflow_windows(pd.DataFrame())
        expected = {
            "gage_id", "sample_date", "streamflow_cfs_latest",
            "streamflow_cfs_mean_6h", "streamflow_cfs_mean_24h",
            "streamflow_cfs_max_24h", "streamflow_cfs_mean_72h",
            "streamflow_rising_flag",
        }
        assert set(result.columns) == expected
        assert len(result) == 0

    def test_timestamps_normalize_from_iso_utc(self):
        rows = [
            _make_iv_row("11076000", "2026-01-10T06:00:00+00:00", 150.0),
            _make_iv_row("11076000", "2026-01-10T09:00:00+00:00", 160.0),
        ]
        result = aggregate_streamflow_windows(pd.DataFrame(rows))
        assert len(result) > 0
        assert result["gage_id"].iloc[0] == "11076000"

    def test_post_cutoff_data_excluded_from_features(self):
        """Readings at or after the 5 AM PT cutoff must not appear in features.

        January date used so PST applies (5 AM PST = 13:00 UTC, unambiguous).
        """
        test_date = date(2026, 1, 10)
        cutoff = _forecast_cutoff_utc(test_date)  # 13:00 UTC in January (PST)
        before = (cutoff - pd.Timedelta(hours=1)).isoformat()
        at_cutoff = cutoff.isoformat()
        after = (cutoff + pd.Timedelta(hours=1)).isoformat()
        rows = [
            _make_iv_row("11076000", before, 100.0),
            _make_iv_row("11076000", at_cutoff, 9999.0),   # at cutoff — excluded
            _make_iv_row("11076000", after, 9999.0),        # after cutoff — excluded
        ]
        result = aggregate_streamflow_windows(pd.DataFrame(rows))
        day_row = result[result["sample_date"] == test_date]
        assert len(day_row) == 1
        assert day_row.iloc[0]["streamflow_cfs_latest"] == pytest.approx(100.0)

    def test_dst_cutoff_is_earlier_in_summer(self):
        """In PDT (summer), 5 AM PT = 12:00 UTC — one hour earlier than in PST."""
        winter = _forecast_cutoff_utc(date(2026, 1, 15))  # PST: 5 AM PST = 13:00 UTC
        summer = _forecast_cutoff_utc(date(2026, 7, 15))  # PDT: 5 AM PDT = 12:00 UTC
        assert winter.hour == 13
        assert summer.hour == 12

    def test_duplicate_gage_timestamp_rows_removed(self):
        rows = [
            _make_iv_row("11076000", "2026-01-10T06:00:00+00:00", 100.0),
            _make_iv_row("11076000", "2026-01-10T06:00:00+00:00", 200.0),  # duplicate ts
        ]
        result = aggregate_streamflow_windows(pd.DataFrame(rows))
        assert len(result) >= 1
        day_row = result[result["sample_date"] == date(2026, 1, 10)]
        assert day_row.iloc[0]["streamflow_cfs_latest"] == pytest.approx(200.0)  # keep-last

    def test_provisional_flags_preserved_passthrough(self):
        """Provisional flag is a passthrough column; rows with provisional=True must not be dropped."""
        rows = [
            _make_iv_row("11076000", "2026-01-10T06:00:00+00:00", 100.0, provisional=True),
            _make_iv_row("11076000", "2026-01-10T08:00:00+00:00", 110.0, provisional=False),
        ]
        df = pd.DataFrame(rows)
        # aggregate_streamflow_windows processes discharge from any row; provisional is stored separately
        result = aggregate_streamflow_windows(df)
        assert len(result) >= 1

    def test_rising_flag_set_when_latest_exceeds_24h_mean(self):
        rows = [
            _make_iv_row("11076000", "2026-01-10T00:00:00+00:00", 50.0),
            _make_iv_row("11076000", "2026-01-10T06:00:00+00:00", 50.0),
            _make_iv_row("11076000", "2026-01-10T12:00:00+00:00", 200.0),  # spike before cutoff
        ]
        result = aggregate_streamflow_windows(pd.DataFrame(rows))
        day_row = result[result["sample_date"] == date(2026, 1, 10)]
        assert day_row.iloc[0]["streamflow_rising_flag"] == 1

    def test_missing_discharge_sentinel_becomes_nan(self):
        rows = [
            {
                "gage_id": "11076000",
                "time_utc": "2026-01-10T06:00:00+00:00",
                "discharge_cfs": np.nan,
                "gage_height_ft": np.nan,
                "provisional": False,
                "source_name": "usgs_nwis",
            }
        ]
        result = aggregate_streamflow_windows(pd.DataFrame(rows))
        # NaN discharge rows are dropped; no rows should appear for this date
        day_rows = result[result["sample_date"] == date(2026, 1, 10)]
        assert len(day_rows) == 0


class TestBuildBeachHydrologyDaily:
    def test_empty_links_returns_correct_columns(self):
        result = build_beach_hydrology_daily(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        assert "beach_id" in result.columns
        assert len(result) == 0

    def test_unmatched_gage_yields_nan_not_dropped(self):
        links = pd.DataFrame([{
            "beach_id": "scripps-pier",
            "hydrologic_unit_id": "180702030801",
            "pour_point_id": "pp_180702030801",
            "pour_point_latitude": 32.87,
            "pour_point_longitude": -117.25,
            "distance_to_pour_point_km": 0.0,
            "nearest_stream_gage_id": "NONEXISTENT",
            "distance_to_gage_km": 5.0,
            "watershed_area_km2": None,
            "mapping_confidence": "high",
        }])
        streamflow = pd.DataFrame([{
            "gage_id": "11076000",
            "sample_date": date(2026, 4, 10),
            "streamflow_cfs_latest": 100.0,
            "streamflow_cfs_mean_24h": 90.0,
            "streamflow_cfs_max_24h": 120.0,
            "streamflow_rising_flag": 1,
        }])
        result = build_beach_hydrology_daily(links, streamflow, pd.DataFrame())
        assert len(result) >= 1
        # Beach links to a nonexistent gage → streamflow columns are NaN, row is still present
        row = result[result["beach_id"] == "scripps-pier"].iloc[0]
        assert pd.isna(row["streamflow_cfs_latest"])
