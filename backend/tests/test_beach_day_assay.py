"""Assay identity must survive the beach_day day-collapse.

``exceeds_stv`` pools two action values: culture rows against the 104 MPN/CFU
marine STV, San Diego ddPCR rows against the 1413 copies/100 mL BAV. Both are
correct and neither is changed here. What these tests pin is that the *identity*
of the assay reaches the label frame, so nothing downstream is method-blind by
construction.

Measured on the shipped frame (2026-08-07 replay): ddPCR is 15.4% of rows in the
1095d window but supplies 51.9% of positives, exceedance rate 0.592 vs 0.100 for
culture, and on the 1,172 beach-days carrying both assays the two agree only
50.4% of the time.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.data.pipeline import beachwatch
from app.data.pipeline.beachwatch import build_beach_day_frame

BEACH = "ca999-san-diego-test-beach-tb-010"

STATIONS = pd.DataFrame(
    [
        {
            "beach_id": BEACH,
            "name": "Test Beach",
            "county": "San Diego",
            "region": "San Diego",
            "support_status": "production",
            "latitude": 32.6,
            "longitude": -117.1,
            "usepa_id": "CA999",
            "water_body_class": "Saltwater",
            "water_body_type": "Open Coast",
            "agency_name": "County Lab",
        }
    ]
)

EMPTY_ADVISORIES = pd.DataFrame(
    {c: pd.Series(dtype="object") for c in ("beach_id", "started_at", "ended_at")}
)


def _observation(
    *,
    date: str,
    time: str,
    method: str,
    units: str,
    value: float,
    exceeds: bool,
    beach_id: str = BEACH,
) -> dict:
    return {
        "beach_id": beach_id,
        "sample_time": pd.Timestamp(f"{date}T{time}"),
        "sample_date": pd.Timestamp(date).date(),
        "analyte": "enterococcus",
        "method": method,
        "units": units,
        "value": value,
        "exceeds_stv": exceeds,
        "county": "San Diego",
        "station_name": "Test Beach",
        "beach_name": "Test Beach",
        "usepa_id": "CA999",
        "weather": None,
        "storm_drain_flow": None,
        "tidal_height": None,
        "surf_height_observed": None,
        "turbidity_observed": None,
        "odor": None,
        "water_color": None,
    }


def _beach_day(rows: list[dict]) -> pd.DataFrame:
    return build_beach_day_frame(pd.DataFrame(rows), STATIONS, EMPTY_ADVISORIES)


# --- single-assay days ---------------------------------------------------------


def test_ddpcr_beach_day_reports_pcr_assay():
    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="09:00:00",
                method="MCB-ddPCR SOP018-000",
                units="copies/100 mL",
                value=5000.0,
                exceeds=True,
            )
        ]
    )

    assert len(bd) == 1
    row = bd.iloc[0]
    assert bool(row["is_pcr"]) is True
    assert row["label_method"] == "MCB-ddPCR SOP018-000"
    assert row["label_units"] == "copies/100 mL"
    assert bool(row["assay_disagreement"]) is False


def test_culture_beach_day_reports_culture_assay():
    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="09:00:00",
                method="Enterolert",
                units="MPN/100ml",
                value=120.0,
                exceeds=True,
            )
        ]
    )

    assert len(bd) == 1
    row = bd.iloc[0]
    assert bool(row["is_pcr"]) is False
    assert row["label_method"] == "Enterolert"
    assert row["label_units"] == "MPN/100ml"
    assert bool(row["assay_disagreement"]) is False


def test_copies_units_alone_marks_the_row_pcr():
    """A row that declares only ``copies`` units is PCR even with a culture
    method label. Three such rows exist on disk (Mendocino, ``Enterolert`` +
    ``Copies/100ml``), and ``compute_exceeds_stv`` already judges them against
    1413 — so a narrower rule here would disagree with the label it describes.
    """
    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="09:00:00",
                method="Enterolert",
                units="Copies/100ml",
                value=20.0,
                exceeds=False,
            )
        ]
    )

    assert bool(bd.iloc[0]["is_pcr"]) is True


def test_ddpcr_method_alone_marks_the_row_pcr():
    """And the mirror case: the method says PCR while the unit string does not."""
    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="09:00:00",
                method="ddPCR",
                units="unknown",
                value=800.0,
                exceeds=False,
            )
        ]
    )

    assert bool(bd.iloc[0]["is_pcr"]) is True


# --- mixed-assay days ----------------------------------------------------------


def test_mixed_assay_day_records_disagreement():
    """Culture clean, ddPCR over its own action value -> disagreement, and the
    worst-sample rule hands the row to the ddPCR sample."""
    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="08:00:00",
                method="Enterolert",
                units="MPN/100ml",
                value=10.0,
                exceeds=False,
            ),
            _observation(
                date="2026-06-01",
                time="10:00:00",
                method="ddPCR",
                units="Copies/100ml",
                value=5000.0,
                exceeds=True,
            ),
        ]
    )

    assert len(bd) == 1
    row = bd.iloc[0]
    assert bool(row["assay_disagreement"]) is True
    assert bool(row["exceeds_stv"]) is True
    assert bool(row["is_pcr"]) is True
    assert row["label_method"] == "ddPCR"
    assert row["enterococcus_value"] == 5000.0


def test_mixed_assay_day_that_agrees_is_not_flagged():
    """Both assays clean -> no disagreement, even though the row is still
    labelled by whichever sample won the collapse."""
    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="08:00:00",
                method="Enterolert",
                units="MPN/100ml",
                value=10.0,
                exceeds=False,
            ),
            _observation(
                date="2026-06-01",
                time="10:00:00",
                method="ddPCR",
                units="Copies/100ml",
                value=800.0,
                exceeds=False,
            ),
        ]
    )

    assert len(bd) == 1
    assert bool(bd.iloc[0]["assay_disagreement"]) is False
    assert bool(bd.iloc[0]["exceeds_stv"]) is False


def test_mixed_assay_day_where_both_exceed_is_not_flagged():
    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="08:00:00",
                method="Enterolert",
                units="MPN/100ml",
                value=500.0,
                exceeds=True,
            ),
            _observation(
                date="2026-06-01",
                time="10:00:00",
                method="ddPCR",
                units="Copies/100ml",
                value=5000.0,
                exceeds=True,
            ),
        ]
    )

    assert bool(bd.iloc[0]["assay_disagreement"]) is False
    assert bool(bd.iloc[0]["exceeds_stv"]) is True


def test_label_method_follows_the_sample_that_won_the_collapse():
    """The rarer direction: culture flags, ddPCR does not. The worst-sample rule
    must hand the row to the CULTURE sample -- and ``label_method`` must say so,
    not report the numerically larger copies reading. 7 such beach-days exist on
    disk against 574 in the opposite direction.
    """
    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="08:00:00",
                method="Enterolert",
                units="MPN/100ml",
                value=500.0,
                exceeds=True,
            ),
            _observation(
                date="2026-06-01",
                time="10:00:00",
                method="ddPCR",
                units="Copies/100ml",
                value=900.0,  # below the 1413 BAV, but numerically larger
                exceeds=False,
            ),
        ]
    )

    assert len(bd) == 1
    row = bd.iloc[0]
    assert bool(row["assay_disagreement"]) is True
    assert bool(row["is_pcr"]) is False
    assert row["label_method"] == "Enterolert"
    assert row["enterococcus_value"] == 500.0


def test_disagreement_is_scoped_to_the_beach_day():
    """A culture-only day at one beach and a ddPCR-only day at another must not
    be paired into a phantom disagreement."""
    other = "ca998-san-diego-other-beach-ob-010"
    stations = pd.concat(
        [STATIONS, STATIONS.assign(beach_id=other, name="Other Beach")],
        ignore_index=True,
    )
    obs = pd.DataFrame(
        [
            _observation(
                date="2026-06-01",
                time="08:00:00",
                method="Enterolert",
                units="MPN/100ml",
                value=10.0,
                exceeds=False,
            ),
            _observation(
                date="2026-06-02",
                time="10:00:00",
                method="ddPCR",
                units="Copies/100ml",
                value=5000.0,
                exceeds=True,
                beach_id=other,
            ),
        ]
    )

    bd = build_beach_day_frame(obs, stations, EMPTY_ADVISORIES)

    assert len(bd) == 2
    assert not bd["assay_disagreement"].any()


# --- structural guards ---------------------------------------------------------


def test_assay_columns_are_boolean_and_always_present():
    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="09:00:00",
                method="Enterolert",
                units="MPN/100ml",
                value=10.0,
                exceeds=False,
            )
        ]
    )

    for column in ("label_method", "label_units", "is_pcr", "assay_disagreement"):
        assert column in bd.columns
    assert bd["is_pcr"].dtype == bool
    assert bd["assay_disagreement"].dtype == bool


def test_missing_method_and_units_columns_are_tolerated():
    """The national WQP path adds ``method``/``units`` as null; a caller that
    omits them entirely must get a culture-only frame, not a KeyError."""
    obs = pd.DataFrame(
        [
            _observation(
                date="2026-06-01",
                time="09:00:00",
                method="Enterolert",
                units="MPN/100ml",
                value=10.0,
                exceeds=False,
            )
        ]
    ).drop(columns=["method", "units"])

    bd = build_beach_day_frame(obs, STATIONS, EMPTY_ADVISORIES)

    assert len(bd) == 1
    assert bool(bd.iloc[0]["is_pcr"]) is False
    assert pd.isna(bd.iloc[0]["label_method"])
    assert bool(bd.iloc[0]["assay_disagreement"]) is False


def test_is_pcr_is_derived_via_the_shared_exceedance_predicate(monkeypatch):
    """``is_pcr`` must come from ``exceedance.is_pcr_measurement`` -- the same
    predicate that chose the threshold in ``compute_exceeds_stv`` -- and not from
    a bare string comparison written into this module.

    If ``build_beach_day_frame`` ever re-implements the test locally, the patched
    predicate below is ignored and the assertions fail. That failure is the point:
    two independent definitions of "is this PCR" would let the label and its own
    description drift apart silently.
    """
    calls: list[tuple[int, int]] = []

    def inverted(method: pd.Series, units: pd.Series) -> pd.Series:
        calls.append((len(method), len(units)))
        return ~beachwatch_original(method, units)

    beachwatch_original = beachwatch.is_pcr_measurement
    monkeypatch.setattr(beachwatch, "is_pcr_measurement", inverted)

    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="09:00:00",
                method="Enterolert",
                units="MPN/100ml",
                value=10.0,
                exceeds=False,
            )
        ]
    )

    assert calls, "build_beach_day_frame did not call exceedance.is_pcr_measurement"
    assert bool(bd.iloc[0]["is_pcr"]) is True, (
        "is_pcr did not follow the patched predicate -- it is being re-derived "
        "locally instead of delegating to exceedance.is_pcr_measurement"
    )


@pytest.mark.parametrize(
    ("method", "units"),
    [
        ("MCB-ddPCR SOP018-000", "Copies/100ml"),
        ("ddPCR", "copies/100 mL"),
        ("qPCR", "unknown"),
    ],
)
def test_real_pcr_spellings_all_classify(method: str, units: str):
    """The four PCR spellings that exist on disk plus qPCR. A ``== "ddPCR"``
    comparison would miss three of these."""
    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="09:00:00",
                method=method,
                units=units,
                value=2000.0,
                exceeds=True,
            )
        ]
    )

    assert bool(bd.iloc[0]["is_pcr"]) is True


# --- the day-collapse value tiebreak (step 7) ----------------------------------
#
# The worst-sample rule ranks same-day samples on (exceeds_stv, value). The
# second key used to be the RAW value, which compares ddPCR copies against
# culture MPN -- different units, no constant conversion. It is now
# `value / action_value`, each result as a multiple of the number it is judged
# against. The label never moved (key 1 dominates); what moved is which
# sample's NUMBER is seated in `enterococcus_value`, and that column feeds every
# lag / geomean / log_enterococcus feature.


def test_tiebreak_prefers_the_sample_worse_relative_to_its_own_action_value():
    """A clean ddPCR result must not outrank a nearly-exceeding culture result
    just because copy counts are numerically larger.

    800 copies is 0.57x its 1413 BAV. 100 MPN is 0.96x its 104 STV. Neither
    exceeds, so the tiebreak decides -- and the culture sample is the worse
    water. The raw-value rule picked the ddPCR row (800 > 100).
    """
    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="09:00:00",
                method="Enterolert",
                units="MPN/100ml",
                value=100.0,
                exceeds=False,
            ),
            _observation(
                date="2026-06-01",
                time="11:00:00",
                method="MCB-ddPCR SOP018-000",
                units="Copies/100ml",
                value=800.0,
                exceeds=False,
            ),
        ]
    )

    assert len(bd) == 1
    row = bd.iloc[0]
    assert bool(row["exceeds_stv"]) is False
    assert float(row["enterococcus_value"]) == 100.0
    assert bool(row["is_pcr"]) is False
    assert row["label_method"] == "Enterolert"


def test_tiebreak_still_prefers_ddpcr_when_it_is_genuinely_the_worse_reading():
    """The fix is a rescaling, not a culture preference. 1300 copies is 0.92x
    the 1413 BAV; 10 MPN is 0.10x the 104 STV -- ddPCR still wins."""
    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="09:00:00",
                method="Enterolert",
                units="MPN/100ml",
                value=10.0,
                exceeds=False,
            ),
            _observation(
                date="2026-06-01",
                time="11:00:00",
                method="ddPCR",
                units="Copies/100ml",
                value=1300.0,
                exceeds=False,
            ),
        ]
    )

    assert len(bd) == 1
    assert float(bd.iloc[0]["enterococcus_value"]) == 1300.0
    assert bool(bd.iloc[0]["is_pcr"]) is True


def test_tiebreak_never_overrides_the_exceedance_label():
    """Key 1 still dominates. An exceeding culture sample represents the day
    even when a non-exceeding ddPCR sample has a far larger ratio... it cannot,
    by construction: any ratio > 1 exceeds. So the case to pin is the reverse --
    an exceeding sample with the SMALLER ratio must still win over a
    non-exceeding one."""
    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="09:00:00",
                method="Enterolert",
                units="MPN/100ml",
                value=110.0,  # 1.06x the 104 STV -- exceeds
                exceeds=True,
            ),
            _observation(
                date="2026-06-01",
                time="11:00:00",
                method="ddPCR",
                units="Copies/100ml",
                value=1400.0,  # 0.99x the 1413 BAV -- does not exceed
                exceeds=False,
            ),
        ]
    )

    assert len(bd) == 1
    assert bool(bd.iloc[0]["exceeds_stv"]) is True
    assert float(bd.iloc[0]["enterococcus_value"]) == 110.0


def test_tiebreak_within_one_assay_is_unchanged():
    """Dividing every row of one assay by the same constant preserves order, so
    a single-assay day must pick exactly the sample the raw-value rule did."""
    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="09:00:00",
                method="Enterolert",
                units="MPN/100ml",
                value=10.0,
                exceeds=False,
            ),
            _observation(
                date="2026-06-01",
                time="11:00:00",
                method="Enterolert",
                units="MPN/100ml",
                value=90.0,
                exceeds=False,
            ),
        ]
    )

    assert float(bd.iloc[0]["enterococcus_value"]) == 90.0


def test_action_value_is_not_leaked_into_the_label_frame():
    """`_action_value` is collapse scaffolding. If it ever ships as a column it
    becomes a perfect `is_pcr` proxy in the feature frame under a name nothing
    excludes."""
    bd = _beach_day(
        [
            _observation(
                date="2026-06-01",
                time="09:00:00",
                method="ddPCR",
                units="Copies/100ml",
                value=2000.0,
                exceeds=True,
            )
        ]
    )

    assert "_action_value" not in bd.columns
    assert not [c for c in bd.columns if c.startswith("_")]
