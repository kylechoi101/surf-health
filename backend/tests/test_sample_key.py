"""Unit tests for app.data.pipeline.sample_key."""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd

from app.data.pipeline.exceedance import is_pcr_measurement
from app.data.pipeline.sample_key import (
    CANONICAL_KEY,
    assay_kind,
    collapse_physical_duplicates,
    rebind_by_station_code,
    with_canonical_key,
)


def test_assay_kind_matches_is_pcr_measurement() -> None:
    methods = pd.Series([
        "ddPCR",
        "Enterolert",
        "MCB-ddPCR",
        "membrane filtration",
        "qPCR",
        None,
        "",
    ])
    units = pd.Series([
        "copies/100 mL",
        "MPN/100 mL",
        "copies/100mL",
        "CFU/100 mL",
        "copies",
        "MPN",
        "",
    ])
    kind = assay_kind(methods, units)
    expected_pcr = is_pcr_measurement(methods, units)
    assert (kind == "ddpcr").equals(expected_pcr)
    assert (kind == "culture").equals(~expected_pcr)


def test_with_canonical_key_structure_and_fallback() -> None:
    df = pd.DataFrame([
        {
            "beach_id": "beach-1",
            "sample_time": pd.to_datetime("2026-07-06 08:50:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "ddPCR",
            "units": "copies/100 mL",
        },
        {
            "beach_id": "beach-2",
            "sample_time": pd.NaT,
            "sample_date": datetime.date(2026, 7, 7),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
        },
    ])
    keyed = with_canonical_key(df)
    for col in CANONICAL_KEY:
        assert col in keyed.columns
    assert keyed.loc[0, "sample_day"] == pd.Timestamp("2026-07-06 00:00:00")
    assert keyed.loc[0, "assay_kind"] == "ddpcr"
    assert keyed.loc[1, "sample_day"] == pd.Timestamp("2026-07-07 00:00:00")
    assert keyed.loc[1, "assay_kind"] == "culture"


def test_collapse_safetoswim_and_live_close_time_same_value() -> None:
    # SafeToSwim 08:50 and Live 08:51, same value -> one row; merged_from lists both
    df = pd.DataFrame([
        {
            "beach_id": "beach-1",
            "sample_time": pd.to_datetime("2026-07-06 08:50:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 10.0,
            "exceeds_stv": False,
            "data_source": "BeachWatch.SafeToSwim",
        },
        {
            "beach_id": "beach-1",
            "sample_time": pd.to_datetime("2026-07-06 08:51:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 10.0,
            "exceeds_stv": False,
            "data_source": "BeachWatch.Live",
        },
    ])
    res = collapse_physical_duplicates(df)
    assert len(res) == 1
    assert res.iloc[0]["data_source"] == "BeachWatch.Live"
    assert res.iloc[0]["merged_from"] == "BeachWatch.Live;BeachWatch.SafeToSwim"


def test_collapse_safetoswim_and_live_revision_keeps_live_value() -> None:
    # Same pair, different value (a revision) -> one row, Live's value kept
    df = pd.DataFrame([
        {
            "beach_id": "beach-1",
            "sample_time": pd.to_datetime("2026-07-06 08:50:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 10.0,
            "exceeds_stv": False,
            "data_source": "BeachWatch.SafeToSwim",
        },
        {
            "beach_id": "beach-1",
            "sample_time": pd.to_datetime("2026-07-06 08:51:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 25.0,
            "exceeds_stv": False,
            "data_source": "BeachWatch.Live",
        },
    ])
    res = collapse_physical_duplicates(df)
    assert len(res) == 1
    assert res.iloc[0]["data_source"] == "BeachWatch.Live"
    assert res.iloc[0]["value"] == 25.0
    assert res.iloc[0]["merged_from"] == "BeachWatch.Live;BeachWatch.SafeToSwim"


def test_collapse_timed_samples_over_30_min_apart_kept_as_two_rows() -> None:
    # 08:50 and 14:10 same key, different values -> two rows
    df = pd.DataFrame([
        {
            "beach_id": "beach-1",
            "sample_time": pd.to_datetime("2026-07-06 08:50:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 10.0,
            "exceeds_stv": False,
            "data_source": "BeachWatch.Live",
        },
        {
            "beach_id": "beach-1",
            "sample_time": pd.to_datetime("2026-07-06 14:10:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 30.0,
            "exceeds_stv": False,
            "data_source": "BeachWatch.Live",
        },
    ])
    res = collapse_physical_duplicates(df)
    assert len(res) == 2
    assert res.iloc[0]["sample_time"] == pd.Timestamp("2026-07-06 08:50:00")
    assert res.iloc[1]["sample_time"] == pd.Timestamp("2026-07-06 14:10:00")
    assert res.iloc[0]["merged_from"] == "BeachWatch.Live"
    assert res.iloc[1]["merged_from"] == "BeachWatch.Live"


def test_collapse_sf_date_only_county_direct_alone_kept() -> None:
    # SF date-only (00:00) CountyDirect row alone -> kept
    df = pd.DataFrame([
        {
            "beach_id": "beach-sf",
            "sample_time": pd.to_datetime("2026-07-06 00:00:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 10.0,
            "exceeds_stv": False,
            "data_source": "CountyDirect",
        },
    ])
    res = collapse_physical_duplicates(df)
    assert len(res) == 1
    assert res.iloc[0]["data_source"] == "CountyDirect"
    assert res.iloc[0]["merged_from"] == "CountyDirect"


def test_collapse_sf_date_only_county_direct_with_state_timed_row() -> None:
    # SF date-only CountyDirect + state timed row same day -> state row kept, merged_from contains CountyDirect
    df = pd.DataFrame([
        {
            "beach_id": "beach-sf",
            "sample_time": pd.to_datetime("2026-07-06 00:00:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 10.0,
            "exceeds_stv": False,
            "data_source": "CountyDirect",
        },
        {
            "beach_id": "beach-sf",
            "sample_time": pd.to_datetime("2026-07-06 09:15:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 10.0,
            "exceeds_stv": False,
            "data_source": "BeachWatch",
        },
    ])
    res = collapse_physical_duplicates(df)
    assert len(res) == 1
    assert res.iloc[0]["data_source"] == "BeachWatch"
    assert "BeachWatch" in res.iloc[0]["merged_from"]
    assert "CountyDirect" in res.iloc[0]["merged_from"]


def test_collapse_ddpcr_and_culture_same_beach_day_two_rows() -> None:
    # ddPCR (method="ddPCR", units="copies/100 mL") and culture ("Enterolert", "MPN/100 mL") on same beach-day -> two rows
    df = pd.DataFrame([
        {
            "beach_id": "beach-sd",
            "sample_time": pd.to_datetime("2026-07-06 08:30:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "ddPCR",
            "units": "copies/100 mL",
            "value": 500.0,
            "exceeds_stv": False,
            "data_source": "BeachWatch",
        },
        {
            "beach_id": "beach-sd",
            "sample_time": pd.to_datetime("2026-07-06 08:30:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 35.0,
            "exceeds_stv": False,
            "data_source": "BeachWatch",
        },
    ])
    res = collapse_physical_duplicates(df)
    assert len(res) == 2


def test_collapse_different_analytes_same_beach_day_two_rows() -> None:
    # Different analytes same beach-day -> two rows
    df = pd.DataFrame([
        {
            "beach_id": "beach-1",
            "sample_time": pd.to_datetime("2026-07-06 08:30:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 10.0,
            "exceeds_stv": False,
            "data_source": "BeachWatch",
        },
        {
            "beach_id": "beach-1",
            "sample_time": pd.to_datetime("2026-07-06 08:30:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "fecal_coliform",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 20.0,
            "exceeds_stv": False,
            "data_source": "BeachWatch",
        },
    ])
    res = collapse_physical_duplicates(df)
    assert len(res) == 2


def test_collapse_two_beachwatch_date_only_different_values_both_kept() -> None:
    # C1: Two BeachWatch date-only rows, same key, values 50 and 200 -> BOTH kept
    df = pd.DataFrame([
        {
            "beach_id": "beach-1",
            "sample_time": pd.to_datetime("2026-07-06 00:00:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 50.0,
            "exceeds_stv": False,
            "data_source": "BeachWatch",
        },
        {
            "beach_id": "beach-1",
            "sample_time": pd.to_datetime("2026-07-06 00:00:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 200.0,
            "exceeds_stv": True,
            "data_source": "BeachWatch",
        },
    ])
    res = collapse_physical_duplicates(df)
    assert len(res) == 2
    vals = set(res["value"])
    assert vals == {50.0, 200.0}
    assert (res["data_source"] == "BeachWatch").all()
    assert (res["merged_from"] == "BeachWatch").all()


def test_collapse_two_beachwatch_date_only_same_value_collapsed() -> None:
    # C1: Two BeachWatch date-only rows, same key, both value 50 -> collapse to one
    df = pd.DataFrame([
        {
            "beach_id": "beach-1",
            "sample_time": pd.to_datetime("2026-07-06 00:00:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 50.0,
            "exceeds_stv": False,
            "data_source": "BeachWatch",
        },
        {
            "beach_id": "beach-1",
            "sample_time": pd.to_datetime("2026-07-06 00:00:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "value": 50.0,
            "exceeds_stv": False,
            "data_source": "BeachWatch",
        },
    ])
    res = collapse_physical_duplicates(df)
    assert len(res) == 1
    assert res.iloc[0]["value"] == 50.0
    assert res.iloc[0]["data_source"] == "BeachWatch"
    assert res.iloc[0]["merged_from"] == "BeachWatch"


def test_rebind_by_station_code_moves_misbound_row() -> None:
    stations = pd.DataFrame([
        {
            "beach_id": "ca604254-coronado-north-beach-eh-060",
            "county": "San Diego",
            "station_code": "EH-060",
        },
    ])
    obs = pd.DataFrame([
        {
            "beach_id": "ca604254-wrong-neighbour-beach",
            "county": "San Diego",
            "station_code": "EH-060",
            "data_source": "BeachWatch.SafeToSwim",
            "value": 10.0,
        },
    ])
    res = rebind_by_station_code(obs, stations)
    assert len(res) == 1
    assert res.iloc[0]["beach_id"] == "ca604254-coronado-north-beach-eh-060"


def test_rebind_by_station_code_leaves_correct_row_untouched() -> None:
    stations = pd.DataFrame([
        {
            "beach_id": "ca604254-coronado-north-beach-eh-060",
            "county": "San Diego",
            "station_code": "EH-060",
        },
    ])
    obs = pd.DataFrame([
        {
            "beach_id": "ca604254-coronado-north-beach-eh-060",
            "county": "San Diego",
            "station_code": "EH-060",
            "data_source": "BeachWatch.SafeToSwim",
            "value": 10.0,
        },
    ])
    res = rebind_by_station_code(obs, stations)
    assert len(res) == 1
    assert res.iloc[0]["beach_id"] == "ca604254-coronado-north-beach-eh-060"


def test_rebind_by_station_code_leaves_ambiguous_code_untouched() -> None:
    stations = pd.DataFrame([
        {
            "beach_id": "beach-a",
            "county": "Orange",
            "station_code": "AMBIG-1",
        },
        {
            "beach_id": "beach-b",
            "county": "Orange",
            "station_code": "AMBIG-1",
        },
    ])
    obs = pd.DataFrame([
        {
            "beach_id": "beach-orig",
            "county": "Orange",
            "station_code": "AMBIG-1",
            "data_source": "BeachWatch.SafeToSwim",
            "value": 10.0,
        },
    ])
    res = rebind_by_station_code(obs, stations)
    assert len(res) == 1
    assert res.iloc[0]["beach_id"] == "beach-orig"


def test_rebind_by_station_code_leaves_null_station_code_untouched() -> None:
    stations = pd.DataFrame([
        {
            "beach_id": "beach-a",
            "county": "Orange",
            "station_code": "EH-010",
        },
    ])
    obs = pd.DataFrame([
        {
            "beach_id": "beach-orig",
            "county": "Orange",
            "station_code": None,
            "data_source": "BeachWatch.SafeToSwim",
            "value": 10.0,
        },
        {
            "beach_id": "beach-orig-2",
            "county": None,
            "station_code": "EH-010",
            "data_source": "BeachWatch.SafeToSwim",
            "value": 20.0,
        },
    ])
    res = rebind_by_station_code(obs, stations)
    assert len(res) == 2
    assert res.iloc[0]["beach_id"] == "beach-orig"
    assert res.iloc[1]["beach_id"] == "beach-orig-2"


def test_collapse_preserves_original_columns_and_dtypes() -> None:
    df = pd.DataFrame({
        "beach_id": ["b1", "b1"],
        "sample_time": [pd.Timestamp("2026-07-06 08:50:00"), pd.Timestamp("2026-07-06 08:51:00")],
        "sample_date": [datetime.date(2026, 7, 6), datetime.date(2026, 7, 6)],
        "analyte": ["enterococcus", "enterococcus"],
        "method": ["Enterolert", "Enterolert"],
        "units": ["MPN/100 mL", "MPN/100 mL"],
        "value": np.array([10.0, 10.0], dtype=np.float64),
        "exceeds_stv": [False, False],
        "data_source": ["BeachWatch.Live", "BeachWatch.SafeToSwim"],
        "custom_meta": [123, 456],
    })
    res = collapse_physical_duplicates(df)
    assert set(df.columns).issubset(set(res.columns))
    assert "merged_from" in res.columns
    assert "sample_day" not in res.columns
    assert "assay_kind" not in res.columns
    for col in df.columns:
        assert res[col].dtype == df[col].dtype


def test_collapse_empty_dataframe() -> None:
    df = pd.DataFrame(columns=["beach_id", "sample_time", "analyte", "value", "data_source"])
    res = collapse_physical_duplicates(df)
    assert res.empty
    assert "merged_from" in res.columns


def test_cli_wiring_rebind_and_collapse_moves_exceedance_to_true_beach() -> None:
    from app.data.pipeline.cli import rebind_and_collapse_observations

    stations = pd.DataFrame([
        {
            "beach_id": "beach-true",
            "county": "Orange",
            "station_code": "EH-030",
            "name": "True Beach",
            "region": "South Coast",
            "latitude": 33.5,
            "longitude": -117.8,
            "support_status": "supported",
            "usepa_id": "CA123456",
        },
        {
            "beach_id": "beach-wrong",
            "county": "Orange",
            "station_code": "EH-033",
            "name": "Wrong Beach",
            "region": "South Coast",
            "latitude": 33.6,
            "longitude": -117.9,
            "support_status": "supported",
            "usepa_id": "CA123457",
        },
    ])
    observations = pd.DataFrame([
        {
            "beach_id": "beach-wrong",
            "county": "Orange",
            "station_code": "EH-030",
            "sample_time": pd.Timestamp("2026-07-06 08:50:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "value": 250.0,
            "exceeds_stv": True,
            "data_source": "BeachWatch.SafeToSwim",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "weather": "Clear",
            "storm_drain_flow": "None",
            "tidal_height": None,
            "surf_height_observed": None,
            "turbidity_observed": None,
            "odor": None,
            "water_color": None,
        },
        {
            "beach_id": "beach-true",
            "county": "Orange",
            "station_code": "EH-030",
            "sample_time": pd.Timestamp("2026-07-06 08:50:00"),
            "sample_date": datetime.date(2026, 7, 6),
            "analyte": "enterococcus",
            "value": 250.0,
            "exceeds_stv": True,
            "data_source": "BeachWatch",
            "method": "Enterolert",
            "units": "MPN/100 mL",
            "weather": "Clear",
            "storm_drain_flow": "None",
            "tidal_height": None,
            "surf_height_observed": None,
            "turbidity_observed": None,
            "odor": None,
            "water_color": None,
        },
    ])
    advisories = pd.DataFrame(columns=["beach_id", "start_date", "end_date", "advisory_type"])
    bundle = {
        "stations": stations,
        "observations": observations,
        "advisories": advisories,
    }

    out_bundle = rebind_and_collapse_observations(bundle)
    assert len(out_bundle["observations"]) == 1
    assert out_bundle["observations"].iloc[0]["beach_id"] == "beach-true"
    assert "BeachWatch.SafeToSwim" in out_bundle["observations"].iloc[0]["merged_from"]
    assert "BeachWatch" in out_bundle["observations"].iloc[0]["merged_from"]

    beach_day = out_bundle["beach_day"]
    # Final beach_day has the exceedance on the TRUE beach only
    assert "beach-true" in beach_day["beach_id"].to_numpy()
    true_beach_row = beach_day[beach_day["beach_id"] == "beach-true"].iloc[0]
    assert bool(true_beach_row["exceeds_stv"]) is True
    assert "beach-wrong" not in beach_day[beach_day["exceeds_stv"].fillna(False).astype(bool)]["beach_id"].to_numpy()

