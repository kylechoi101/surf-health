"""Tests for pure functions in scripts.lookup_baseline."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lookup_baseline import (  # noqa: E402
    advisory_active,
    assign_band,
    build_comparison_report,
    build_lookup_forecast,
    evaluate_beaches,
    evaluate_slices,
    identify_ddpcr_beaches,
    last_sample,
    lookup_rate,
    match_forward_lab_results,
    rain_station_key,
)


def test_sample_on_or_after_d_never_counted():
    """Requirement 1: A sample ON date D or after is never counted (strictly prior)."""
    forecast_date = "2026-09-22"
    # Three samples for beach-1:
    # 1. 2026-09-20 (prior: must be counted)
    # 2. 2026-09-22 (ON date D: must NOT be counted)
    # 3. 2026-09-25 (after date D: must NOT be counted)
    df = pd.DataFrame(
        {
            "beach_id": ["beach-1", "beach-1", "beach-1"],
            "sample_date": ["2026-09-20", "2026-09-22", "2026-09-25"],
            "exceeds_stv": [True, True, True],
            "enterococcus_value": [104.0, 500.0, 600.0],
        }
    )

    # With g=0.0:
    # If only 2026-09-20 is counted, pos=1, n=1 -> p_lookup = (1 + 0*5) / (1 + 5) = 1/6
    rate = lookup_rate(df, forecast_date, g=0.0, beach_id="beach-1")
    assert np.isclose(rate, 1.0 / 6.0)

    # last_sample must pick 2026-09-20, ignoring samples on or after 2026-09-22
    ls = last_sample(df, forecast_date, beach_id="beach-1")
    assert ls["last_sample_date"] == "2026-09-20"
    assert ls["sample_age_days"] == 2
    assert ls["last_sample_value"] == 104.0
    assert ls["last_sample_exceeds"] is True


def test_shrinkage_zero_samples_gets_exactly_g():
    """Requirement 2: Shrinkage: a beach with 0 samples gets exactly g."""
    # Scalar form: pos=0, n=0 with g=0.179
    rate_scalar = lookup_rate(0, 0, g=0.179)
    assert np.isclose(rate_scalar, 0.179)

    # DataFrame form: beach-A has samples, beach-B has 0 samples
    forecast_date = "2026-09-22"
    df = pd.DataFrame(
        {
            "beach_id": ["beach-A", "beach-A"],
            "sample_date": ["2026-08-01", "2026-08-15"],
            "exceeds_stv": [True, False],
            "enterococcus_value": [150.0, 10.0],
        }
    )
    # Global g is 1/2 = 0.50
    rate_b = lookup_rate(df, forecast_date, beach_id="beach-B")
    assert np.isclose(rate_b, 0.50)

    # With explicit g and beaches list
    rates_all = lookup_rate(
        df,
        forecast_date,
        g=0.25,
        beaches=["beach-A", "beach-B"],
    )
    row_b = rates_all[rates_all["beach_id"] == "beach-B"].iloc[0]
    assert row_b["n"] == 0
    assert row_b["n_365d"] == 0
    assert row_b["pos"] == 0
    assert np.isnan(row_b["rate_365d"])
    assert np.isclose(row_b["p_lookup"], 0.25)


def test_band_precedence():
    """Requirement 3: Band precedence Unmonitored > Posted > Elevated > Low."""
    # 1. Unmonitored beats Posted (sample age > 30 days)
    assert assign_band(sample_age_days=31, advisory_active=True, p_lookup=0.50) == "Unmonitored"
    # Never sampled (sample_age_days is None or NaN)
    assert assign_band(sample_age_days=None, advisory_active=True, p_lookup=0.50) == "Unmonitored"
    assert assign_band(sample_age_days=np.nan, advisory_active=True, p_lookup=0.50) == "Unmonitored"

    # 2. Posted beats Elevated (monitored within 30 days, advisory active, p >= 0.10)
    assert assign_band(sample_age_days=5, advisory_active=True, p_lookup=0.50) == "Posted"
    assert assign_band(sample_age_days=5, advisory_active=True, p_lookup=0.01) == "Posted"

    # 3. Elevated beats Low (monitored, no advisory, p >= 0.10)
    assert assign_band(sample_age_days=5, advisory_active=False, p_lookup=0.10) == "Elevated"
    assert assign_band(sample_age_days=5, advisory_active=False, p_lookup=0.25) == "Elevated"

    # 4. Low (monitored, no advisory, p < 0.10)
    assert assign_band(sample_age_days=5, advisory_active=False, p_lookup=0.099) == "Low"
    assert assign_band(sample_age_days=30, advisory_active=False, p_lookup=0.00) == "Low"

    # Also test row/dict input format
    row = {"sample_age_days": 10, "advisory_active": False, "p_lookup": 0.15}
    assert assign_band(row=row) == "Elevated"


def test_rain_station_key_rounding():
    """Requirement 4: Rain station key rounding (e.g. lat 32.4499, lon -117.1499 -> 32.4_-117.1)."""
    assert rain_station_key(32.4499, -117.1499) == "32.4_-117.1"
    assert rain_station_key(32.4, -117.1) == "32.4_-117.1"
    assert rain_station_key(34.01, -118.49) == "34.0_-118.5"
    assert rain_station_key(37.0, -122.0) == "37.0_-122.0"


def test_advisory_active():
    """Advisory active conditions on forecast_date D."""
    advisories = pd.DataFrame(
        {
            "beach_id": [
                "b-active-open",
                "b-historical-open",
                "b-active-window",
                "b-ended",
                "b-future",
            ],
            "started_at": [
                "2026-09-01",
                "2026-09-01",
                "2026-09-15",
                "2026-09-01",
                "2026-09-25",
            ],
            "ended_at": [None, None, "2026-09-22", "2026-09-20", None],
            "status": ["active", "historical", "active", "historical", "active"],
        }
    )
    forecast_date = "2026-09-22"

    assert advisory_active(advisories, forecast_date, beach_id="b-active-open") is True
    # Ended null and status == "historical" is NOT active (per spec correction)
    assert advisory_active(advisories, forecast_date, beach_id="b-historical-open") is False
    # Ended on D itself is still active on D
    assert advisory_active(advisories, forecast_date, beach_id="b-active-window") is True
    # Ended strictly before D is not active
    assert advisory_active(advisories, forecast_date, beach_id="b-ended") is False
    # Starting after D is not active
    assert advisory_active(advisories, forecast_date, beach_id="b-future") is False

    # Multi-beach Series output
    active_series = advisory_active(advisories, forecast_date)
    assert active_series["b-active-open"] is True or active_series["b-active-open"] == 1
    assert not active_series.get("b-historical-open", False)
    assert active_series["b-active-window"] is True or active_series["b-active-window"] == 1
    assert not active_series.get("b-ended", False)
    assert not active_series.get("b-future", False)


def test_last_sample_never_sampled():
    """Beaches with no samples before D return None fields."""
    forecast_date = "2026-09-22"
    df = pd.DataFrame(
        {
            "beach_id": ["beach-future"],
            "sample_date": ["2026-09-23"],
            "exceeds_stv": [True],
            "enterococcus_value": [300.0],
        }
    )
    res = last_sample(df, forecast_date, beach_id="beach-future")
    assert res["last_sample_date"] is None
    assert res["last_sample_exceeds"] is None
    assert res["last_sample_value"] is None
    assert res["sample_age_days"] is None


def test_build_lookup_forecast_synthetic():
    """Verify build_lookup_forecast end-to-end on synthetic frames."""
    forecast_date = "2026-09-22"
    beaches = pd.DataFrame(
        {
            "beach_id": ["b-elevated", "b-posted", "b-unmonitored"],
            "name": ["Elevated Beach", "Posted Beach", "Unmonitored Beach"],
            "county": ["CountyA", "CountyB", "CountyC"],
            "latitude": [32.44, 33.12, 34.01],
            "longitude": [-117.14, -117.29, -118.49],
        }
    )
    beach_day = pd.DataFrame(
        {
            "beach_id": ["b-elevated", "b-posted", "b-unmonitored"],
            "sample_date": ["2026-09-17", "2026-09-15", "2026-08-01"],
            "exceeds_stv": [True, False, True],
            "enterococcus_value": [120.0, 10.0, 350.0],
        }
    )
    advisories = pd.DataFrame(
        {
            "beach_id": ["b-posted"],
            "started_at": ["2026-09-10"],
            "ended_at": [None],
            "status": ["active"],
        }
    )
    precip = pd.DataFrame(
        {
            "station_id": ["33.1_-117.3"],  # matches b-posted
            "sample_date": ["2026-09-22"],
            "precip_mm_72h": [12.5],
        }
    )

    fc = build_lookup_forecast(
        Path("/unused"),
        forecast_date,
        beaches=beaches,
        beach_day=beach_day,
        advisories=advisories,
        precip=precip,
    )

    assert len(fc) == 3
    expected_cols = [
        "beach_id",
        "name",
        "county",
        "forecast_date",
        "n_365d",
        "rate_365d",
        "p_lookup",
        "last_sample_date",
        "last_sample_exceeds",
        "last_sample_value",
        "sample_age_days",
        "advisory_active",
        "rain_flag",
        "band",
    ]
    for col in expected_cols:
        assert col in fc.columns

    row_elevated = fc[fc["beach_id"] == "b-elevated"].iloc[0]
    assert row_elevated["sample_age_days"] == 5
    assert row_elevated["band"] == "Elevated"
    assert row_elevated["rain_flag"] is None or pd.isna(row_elevated["rain_flag"])

    row_posted = fc[fc["beach_id"] == "b-posted"].iloc[0]
    assert bool(row_posted["advisory_active"]) is True
    assert row_posted["band"] == "Posted"
    assert bool(row_posted["rain_flag"]) is True

    row_unmonitored = fc[fc["beach_id"] == "b-unmonitored"].iloc[0]
    assert row_unmonitored["sample_age_days"] > 30
    assert row_unmonitored["band"] == "Unmonitored"


def test_identify_ddpcr_beaches():
    """Verify ddPCR identification on method containing pcr or units containing opies."""
    obs = pd.DataFrame(
        {
            "beach_id": ["beach-pcr", "beach-copies", "beach-culture", "beach-none"],
            "method": ["qPCR EPA 1611", "Standard Plate", "Enterolert", None],
            "units": ["MPN/100ml", "Copies/100mL", "MPN/100ml", "MPN/100ml"],
        }
    )
    ddpcr = identify_ddpcr_beaches(obs)
    assert "beach-pcr" in ddpcr
    assert "beach-copies" in ddpcr
    assert "beach-culture" not in ddpcr
    assert "beach-none" not in ddpcr


def test_match_forward_lab_results():
    """Verify deduplication of forecast_history and first lab matching in D+1..D+3."""
    fh = pd.DataFrame(
        {
            "beach_id": ["b-1", "b-1", "b-2"],
            "forecast_date": ["2026-09-01", "2026-09-01", "2026-09-01"],
            "forecast_generated_at": ["2026-09-01 06:00:00", "2026-09-01 08:00:00", "2026-09-01 06:00:00"],
            "p_exceed": [0.10, 0.20, 0.30],  # for b-1, 0.20 should win by latest generated_at
        }
    )
    bd = pd.DataFrame(
        {
            "beach_id": [
                "b-1",  # D+0: same day, must NOT be matched
                "b-1",  # D+1: must be matched (first in D+1..D+3)
                "b-1",  # D+2: later than D+1, should not be picked
                "b-2",  # D+3: within window, should be picked
                "b-2",  # D+4: outside window
            ],
            "sample_date": [
                "2026-09-01",
                "2026-09-02",
                "2026-09-03",
                "2026-09-04",
                "2026-09-05",
            ],
            "exceeds_stv": [False, True, False, True, False],
        }
    )

    verifiable = match_forward_lab_results(fh, bd)
    assert len(verifiable) == 2

    row_b1 = verifiable[verifiable["beach_id"] == "b-1"].iloc[0]
    assert row_b1["p_exceed"] == 0.20  # latest issue
    assert row_b1["delta_days"] == 1  # picked D+1
    assert row_b1["exceeds_stv"] is True or row_b1["exceeds_stv"] == 1

    row_b2 = verifiable[verifiable["beach_id"] == "b-2"].iloc[0]
    assert row_b2["delta_days"] == 3  # picked D+3
    assert row_b2["exceeds_stv"] is True or row_b2["exceeds_stv"] == 1


def test_build_comparison_report():
    """Verify comparison report crosstab, unmonitored count, and diff ranking."""
    forecast_date = "2026-09-22"
    served_df = pd.DataFrame(
        {
            "beach_id": ["b-1", "b-2", "b-3"],
            "risk_band": ["Low", "High", "Low"],
            "p_exceed": [0.05, 0.40, 0.08],
            "sample_age_days": [2, 5, 45],
            "advisory_floor_applied": [False, True, False],
        }
    )
    lookup_df = pd.DataFrame(
        {
            "beach_id": ["b-1", "b-2", "b-3"],
            "name": ["Beach 1", "Beach 2", "Beach 3"],
            "county": ["County 1", "County 2", "County 3"],
            "band": ["Low", "Elevated", "Unmonitored"],
            "p_lookup": [0.06, 0.15, 0.18],
            "sample_age_days": [2, 5, 45],
            "last_sample_date": ["2026-09-20", "2026-09-17", "2026-08-08"],
            "last_sample_exceeds": [False, False, True],
            "last_sample_value": [10.0, 20.0, 300.0],
            "advisory_active": [False, False, False],
            "rain_flag": [False, False, False],
            "n_365d": [20, 25, 0],
            "rate_365d": [0.05, 0.12, np.nan],
        }
    )

    md_text, comp_df = build_comparison_report(served_df, lookup_df, forecast_date)

    assert len(comp_df) == 3
    # Top diff is b-2 (|0.40 - 0.15| = 0.25)
    assert comp_df.iloc[0]["beach_id"] == "b-2"
    assert np.isclose(comp_df.iloc[0]["abs_diff"], 0.25)
    # Check unmonitored count is 1
    assert "Unmonitored" in md_text
    assert "**1**" in md_text
    # Check label for ddPCR copies / MPN
    assert "Last Sample Value (MPN or copies/100ml)" in md_text


def test_evaluate_slices_and_beaches():
    """Verify slice metrics and beach-level persistence baseline evaluation."""
    scored_df = pd.DataFrame(
        {
            "beach_id": ["b-1"] * 10 + ["b-2"] * 10,
            "forecast_date": ["2026-09-01"] * 20,
            "forecast_date_dt": [pd.Timestamp("2026-09-01")] * 20,
            "p_exceed": [0.1] * 5 + [0.8] * 5 + [0.8] * 5 + [0.1] * 5,
            "p_lookup": [0.8] * 5 + [0.1] * 5 + [0.1] * 5 + [0.8] * 5,
            "last_sample_exceeds": [False] * 5 + [True] * 5 + [True] * 5 + [False] * 5,
            "exceeds_stv": [False] * 5 + [True] * 5 + [False] * 5 + [True] * 5,
            "is_ddpcr": [False] * 10 + [True] * 10,
        }
    )
    slices_df = evaluate_slices(scored_df, pd.Timestamp("2026-09-01"))
    assert len(slices_df) == 5
    assert set(slices_df["Slice"]) == {
        "All rows",
        "Last 90 days",
        "Last 30 days",
        "Culture beaches",
        "ddPCR beaches",
    }

    beaches = pd.DataFrame(
        {
            "beach_id": ["b-1", "b-2"],
            "name": ["Beach One", "Beach Two"],
            "county": ["County A", "County B"],
        }
    )
    b_df = evaluate_beaches(scored_df, beaches)
    assert len(b_df) == 2
    assert list(b_df.columns) == [
        "beach_id",
        "name",
        "county",
        "n",
        "positives",
        "auroc_ml",
        "auroc_persistence",
    ]
    # For b-1: ML has perfect correlation (0.1 for False, 0.8 for True), Persistence has perfect correlation
    row_b1 = b_df[b_df["beach_id"] == "b-1"].iloc[0]
    assert row_b1["auroc_ml"] == 1.0
    assert row_b1["auroc_persistence"] == 1.0
    assert row_b1["n"] == 10
    assert row_b1["positives"] == 5

    # For b-2: ML has inverse correlation, Persistence has inverse correlation
    row_b2 = b_df[b_df["beach_id"] == "b-2"].iloc[0]
    assert row_b2["auroc_ml"] == 0.0
    assert row_b2["auroc_persistence"] == 0.0



