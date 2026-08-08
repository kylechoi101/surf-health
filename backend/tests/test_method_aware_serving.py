"""API responses must agree with ``exceeds_stv`` on the row they came from.

A San Diego ddPCR reading of 800 copies/100mL is **below** its 1413 action
value. Until this change both repositories told the user it was "above the
marine threshold" — computed as ``800 > 104`` — while ``exceeds_stv`` in the
very same row said ``False``, and the same comparison drove the derived
forecast's probability to the 0.97 cap. Both thresholds are correct; picking
between them at the call site was not.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from app.data.pipeline.exceedance import (
    compute_exceeds_stv,
    describe_sample_vs_action_value,
    is_pcr_sample,
    sample_action_value,
    sample_exceeds_stv,
)
from app.repositories.curated_repository import CuratedBeachRepository

STV = 104.0
PCR_BAV = 1413.0

# (value, method, units, expect_exceeds, expected substring)
CASES = [
    (800.0, "ddPCR", "Copies/100ml", False, "remains below the 1413 ddPCR action value"),
    (2000.0, "ddPCR", "Copies/100ml", True, "is above the 1413 ddPCR action value"),
    (120.0, "Enterolert", "MPN/100ml", True, "is above the 104 culture action value"),
    (10.0, "Enterolert", "MPN/100ml", False, "remains below the 104 culture action value"),
    # Units alone are sufficient evidence of a molecular method — the arm that
    # exists because some genuinely-molecular rows carry a non-obvious method.
    (800.0, "MCB-ddPCR SOP018-000", "Copies/100ml", False, "1413 ddPCR"),
]


@pytest.mark.parametrize("value,method,units,expect_exceeds,fragment", CASES)
def test_single_sample_helpers_match_the_series_predicate(
    value: float, method: str, units: str, expect_exceeds: bool, fragment: str
) -> None:
    series_answer = bool(
        compute_exceeds_stv(
            pd.Series([value]), pd.Series([method]), pd.Series([units]), STV
        ).iloc[0]
    )
    assert series_answer is expect_exceeds
    # The scalar wrappers delegate; they must never disagree with the Series form.
    assert sample_exceeds_stv(value, method, units, STV) is expect_exceeds
    assert fragment in describe_sample_vs_action_value(value, method, units, STV)


def test_action_value_selection() -> None:
    assert sample_action_value("ddPCR", "Copies/100ml", STV) == PCR_BAV
    assert sample_action_value("Enterolert", "MPN/100ml", STV) == STV
    assert is_pcr_sample("ddPCR", "Copies/100ml") is True
    assert is_pcr_sample("Enterolert", "MPN/100ml") is False


def test_driver_text_never_says_the_bare_marine_threshold() -> None:
    """Which threshold applies is the whole question; the string must say."""
    for value, method, units, _, _ in CASES:
        text = describe_sample_vs_action_value(value, method, units, STV)
        assert "the marine threshold" not in text
        assert ("104" in text) or ("1413" in text)


def _write_curated(tmp_path, value: float, method: str, units: str):
    curated = tmp_path / "curated"
    curated.mkdir(parents=True, exist_ok=True)
    beach_id = "ca000001-san-diego-imperial-beach"
    pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "name": "Imperial Beach",
                "county": "San Diego",
                "latitude": 32.58,
                "longitude": -117.13,
            }
        ]
    ).to_parquet(curated / "beaches.parquet", index=False)
    sample_time = datetime.now() - timedelta(days=1)
    exceeds = sample_exceeds_stv(value, method, units, STV)
    pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "sample_time": sample_time.isoformat(),
                "sample_date": sample_time.date().isoformat(),
                "analyte": "enterococcus",
                "method": method,
                "units": units,
                "value": value,
                "exceeds_stv": exceeds,
                "weather": None,
                "storm_drain_flow": None,
            }
        ]
    ).to_parquet(curated / "observations.parquet", index=False)
    return curated, beach_id, exceeds


@pytest.mark.parametrize("value,method,units,expect_exceeds,fragment", CASES)
def test_derived_forecast_driver_agrees_with_exceeds_stv_in_the_same_row(
    tmp_path, value: float, method: str, units: str, expect_exceeds: bool, fragment: str
) -> None:
    curated, beach_id, stored_exceeds = _write_curated(tmp_path, value, method, units)
    repository = CuratedBeachRepository(curated, stv_threshold=STV)
    forecast = repository.get_forecast(beach_id, date.today())

    driver = forecast.top_drivers[0]
    assert fragment in driver
    # The exact property that was broken: the prose and the stored label agree.
    assert ("is above" in driver) is bool(stored_exceeds)


def test_ddpcr_below_its_action_value_is_not_served_as_a_certainty(tmp_path) -> None:
    """The probability heuristic divided by 104 too, not just the prose.

    800 copies against 104 is a ratio of ~7.7, which pins the derived forecast
    at its 0.97 cap. Against the 1413 that actually applies it is 0.57 — a
    beach that is *below* its action value must not serve as near-certain.
    """
    curated, beach_id, _ = _write_curated(tmp_path, 800.0, "ddPCR", "Copies/100ml")
    forecast = CuratedBeachRepository(curated, stv_threshold=STV).get_forecast(
        beach_id, date.today()
    )
    assert forecast.p_exceed < 0.5
