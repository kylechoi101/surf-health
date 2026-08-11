"""Action-value normalization of the bacteria-history features.

`beach_day.enterococcus_value` mixes two incompatible units in one numeric
column — culture MPN/CFU judged against 104, San Diego ddPCR copies/100mL
judged against 1413 — and every value-derived model feature was built from it.
These tests pin the four properties the fix rests on:

  1. a lag that crosses an assay boundary is continuous on the ratio scale;
  2. `exceeds_stv` — the label — does not move;
  3. the 35/104 geomean triggers stay put on culture and become proportional
     (rather than always-true) on ddPCR;
  4. no model feature is ever built from the raw mixed-unit column again.

See docs/ACTION_VALUE_NORMALIZATION.md.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from app.core.config import get_settings
from app.data.pipeline.beachwatch import build_beach_day_frame
from app.data.pipeline.exceedance import (
    PCR_ENTEROCOCCUS_THRESHOLD_COPIES,
    action_value_ratio,
    compute_exceeds_stv,
)
from app.data.pipeline.features import (
    CULTURE_ENTEROCOCCUS_STV,
    CULTURE_RATIO_SUBDETECTION_FLOOR,
    ENTEROCOCCUS_RATIO_COLUMN,
    PCR_RATIO_SUBDETECTION_FLOOR,
    RawEnterococcusFeatureError,
    _model_feature_columns,
    _regulatory_geomean_features,
    add_temporal_features,
    assert_no_raw_value_features,
)

CULTURE_METHOD = "Enterolert"
CULTURE_UNITS = "MPN/100ml"
PCR_METHOD = "MCB-ddPCR SOP018-000"
PCR_UNITS = "Copies/100ml"


def _observation(
    beach_id: str,
    date: str,
    value: float,
    *,
    method: str = CULTURE_METHOD,
    units: str = CULTURE_UNITS,
) -> dict:
    return {
        "beach_id": beach_id,
        "sample_date": date,
        "sample_time": pd.Timestamp(f"{date}T08:00:00"),
        "analyte": "enterococcus",
        "method": method,
        "units": units,
        "value": value,
        "weather": None,
        "storm_drain_flow": None,
        "tidal_height": np.nan,
        "surf_height_observed": np.nan,
        "turbidity_observed": np.nan,
        "odor": None,
        "water_color": None,
    }


def _observations(rows: list[dict], stv: float = 104.0) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["exceeds_stv"] = compute_exceeds_stv(
        frame["value"], frame["method"], frame["units"], stv
    )
    return frame


def _stations(beach_ids: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "name": beach_id,
                "county": "San Diego",
                "region": "San Diego",
                "latitude": 32.6,
                "longitude": -117.13,
                "support_status": "production",
            }
            for beach_id in beach_ids
        ]
    )


def _advisories() -> pd.DataFrame:
    return pd.DataFrame(columns=["beach_id", "advisory_type", "started_at", "ended_at", "status"])


# --------------------------------------------------------------------------- 1
def test_lag_crossing_an_assay_boundary_is_continuous_in_ratio_space():
    """The crux: a lag holds a PREVIOUS row's value, so no same-row assay flag
    can repair the unit mixing.

    Same water, two labs. A culture reading of 52 MPN and a ddPCR reading of
    706.5 copies are both exactly HALF their own action value — the same water
    quality. On the raw column those are 52 and 706.5, a 13.6x step change that
    enters `*_lag_1` with nothing in the feature set to explain it. On the ratio
    scale they are both 0.5 and the lag is flat.
    """
    beach = "boundary-beach"
    rows = [
        _observation(beach, "2026-04-01", 52.0),
        _observation(beach, "2026-04-02", 706.5, method=PCR_METHOD, units=PCR_UNITS),
        _observation(beach, "2026-04-03", 52.0),
    ]
    beach_day = build_beach_day_frame(_observations(rows), _stations([beach]), _advisories())
    enriched = add_temporal_features(beach_day.sort_values("sample_date"))

    ratio_lag = enriched["enterococcus_action_ratio_lag_1"].to_numpy(dtype=float)
    raw = enriched["enterococcus_value"].to_numpy(dtype=float)

    # Raw column: the assay switch is a 13.6x jump.
    assert math.isclose(raw[1] / raw[0], 706.5 / 52.0, rel_tol=1e-9)
    assert raw[1] / raw[0] > 13.0

    # Ratio lags: flat across the switch. Row 0 has no prior sample.
    assert np.isnan(ratio_lag[0])
    assert math.isclose(ratio_lag[1], 0.5, rel_tol=1e-9)  # prior culture 52/104
    assert math.isclose(ratio_lag[2], 0.5, rel_tol=1e-9)  # prior ddPCR 706.5/1413

    # And the carry-forward feature agrees.
    last_obs = enriched["enterococcus_action_ratio_last_obs"].to_numpy(dtype=float)
    assert math.isclose(last_obs[1], 0.5, rel_tol=1e-9)
    assert math.isclose(last_obs[2], 0.5, rel_tol=1e-9)


def test_action_value_ratio_uses_the_correct_threshold_per_assay():
    frame = pd.DataFrame(
        {
            "value": [104.0, 1413.0, 52.0, 706.5],
            "method": [CULTURE_METHOD, PCR_METHOD, CULTURE_METHOD, PCR_METHOD],
            "units": [CULTURE_UNITS, PCR_UNITS, CULTURE_UNITS, PCR_UNITS],
        }
    )
    ratio = action_value_ratio(frame["value"], frame["method"], frame["units"], 104.0)
    assert ratio.tolist() == pytest.approx([1.0, 1.0, 0.5, 0.5])


def test_unknown_method_falls_back_to_the_culture_action_value():
    """An unlabelled row is judged against 104 by compute_exceeds_stv, so the
    ratio must use the same divisor or the two would disagree."""
    frame = pd.DataFrame({"value": [104.0], "method": [None], "units": [None]})
    ratio = action_value_ratio(frame["value"], frame["method"], frame["units"], 104.0)
    assert ratio.iloc[0] == pytest.approx(1.0)


def test_culture_stv_constant_matches_the_configured_setting():
    assert CULTURE_ENTEROCOCCUS_STV == get_settings().epa_marine_enterococcus_stv


# --------------------------------------------------------------------------- 2
def test_exceeds_stv_does_not_move_and_the_raw_column_is_preserved():
    """The label is computed from the RAW value against the correct threshold
    and must be untouched by normalization. Includes the two rows that pin the
    thresholds: 1000 copies is CLEAN (below 1413) while 200 MPN exceeds."""
    beach = "label-beach"
    rows = [
        _observation(beach, "2026-04-01", 200.0),                                    # culture, over 104
        _observation(beach, "2026-04-02", 50.0),                                     # culture, under 104
        _observation(beach, "2026-04-03", 1000.0, method=PCR_METHOD, units=PCR_UNITS),  # ddPCR, under 1413
        _observation(beach, "2026-04-04", 2000.0, method=PCR_METHOD, units=PCR_UNITS),  # ddPCR, over 1413
    ]
    observations = _observations(rows)
    beach_day = build_beach_day_frame(observations, _stations([beach]), _advisories())
    beach_day = beach_day.sort_values("sample_date").reset_index(drop=True)

    assert beach_day["exceeds_stv"].tolist() == [True, False, False, True]
    assert beach_day["enterococcus_value"].tolist() == [200.0, 50.0, 1000.0, 2000.0]

    # The invariant that makes the two representations checkable against each
    # other: on the ratio scale, "exceeds" is exactly "> 1.0", for both assays.
    ratio = beach_day[ENTEROCOCCUS_RATIO_COLUMN]
    assert (ratio > 1.0).tolist() == beach_day["exceeds_stv"].tolist()
    assert ratio.tolist() == pytest.approx(
        [200 / 104, 50 / 104, 1000 / 1413, 2000 / 1413]
    )


def test_beach_day_keeps_the_raw_value_and_drops_the_assay_columns():
    """`enterococcus_value` stays raw because analysis tooling and the data-diff
    reports compare against it; method/units are consumed to resolve the action
    value and not persisted onto the beach-day frame."""
    beach = "schema-beach"
    beach_day = build_beach_day_frame(
        _observations([_observation(beach, "2026-04-01", 42.0)]),
        _stations([beach]),
        _advisories(),
    )
    assert "enterococcus_value" in beach_day.columns
    assert ENTEROCOCCUS_RATIO_COLUMN in beach_day.columns
    assert "method" not in beach_day.columns
    assert "units" not in beach_day.columns


# --------------------------------------------------------------------------- 3
def _ratio_history(
    beach_id: str,
    start: str,
    ratios: list[float],
    action_value: float = CULTURE_ENTEROCOCCUS_STV,
) -> pd.DataFrame:
    base = pd.Timestamp(start)
    rows = []
    for offset, ratio in enumerate(ratios):
        day = base + pd.Timedelta(days=offset)
        rows.append(
            {
                "beach_id": beach_id,
                "sample_date": day.strftime("%Y-%m-%d"),
                "sample_time": day.strftime("%Y-%m-%dT08:00:00-07:00"),
                "enterococcus_value": ratio * action_value,
                ENTEROCOCCUS_RATIO_COLUMN: ratio,
                "exceeds_stv": int(ratio > 1.0),
            }
        )
    return pd.DataFrame(rows)


def test_geomean_triggers_are_unchanged_for_culture_beaches():
    """104 -> 1.0 and 35 -> 35/104 are exactly the culture triggers restated on
    the ratio scale, so a culture beach's flags are bit-identical to before."""
    raw_values = [10.0, 100.0, 50.0, 200.0, 35.0, 1000.0, 80.0]
    frame = _ratio_history("culture", "2026-04-01", [v / 104.0 for v in raw_values])
    geomean = _regulatory_geomean_features(add_temporal_features(frame))

    # Prior six samples geomean ~90.6 MPN -> over 35, under 104.
    expected = 10 ** float(np.mean([math.log10(v) for v in raw_values[:6]]))
    assert float(geomean.iloc[6]["enterococcus_action_ratio_geomean_30d_lagged"]) == pytest.approx(
        expected / 104.0
    )
    assert geomean.iloc[6]["geomean_30d_exceeds_35_lagged"] == 1.0
    assert geomean.iloc[6]["geomean_30d_exceeds_104_lagged"] == 0.0


def test_geomean_35_trigger_is_proportional_not_always_true_for_ddpcr():
    """Before the fix the raw copy geomean was compared against 35, which every
    realistic ddPCR window clears — the "flag" was a constant 1 and the model
    could only read it as "this is San Diego". On the ratio scale it fires only
    above 35/104 of the molecular action value (~476 copies).
    """
    # A ddPCR beach sitting at 200 copies: ~14x the old 35 trigger, but only
    # 0.14 of its own action value, so it must NOT trip the 35-equivalent.
    quiet = _ratio_history("pcr-quiet", "2026-04-01", [200.0 / 1413.0] * 7)
    quiet_geo = _regulatory_geomean_features(add_temporal_features(quiet))
    assert quiet_geo.iloc[6]["geomean_30d_exceeds_35_lagged"] == 0.0
    assert quiet_geo.iloc[6]["geomean_30d_exceeds_104_lagged"] == 0.0

    # A ddPCR beach at 900 copies is above 35/104 of 1413 (~476) but below the
    # 1413 action value, so it trips the 35-equivalent only — the same shape a
    # culture beach at 90 MPN gets.
    busy = _ratio_history("pcr-busy", "2026-04-01", [900.0 / 1413.0] * 7)
    busy_geo = _regulatory_geomean_features(add_temporal_features(busy))
    assert busy_geo.iloc[6]["geomean_30d_exceeds_35_lagged"] == 1.0
    assert busy_geo.iloc[6]["geomean_30d_exceeds_104_lagged"] == 0.0

    # And above its own action value both trip.
    hot = _ratio_history("pcr-hot", "2026-04-01", [3000.0 / 1413.0] * 7)
    hot_geo = _regulatory_geomean_features(add_temporal_features(hot))
    assert hot_geo.iloc[6]["geomean_30d_exceeds_35_lagged"] == 1.0
    assert hot_geo.iloc[6]["geomean_30d_exceeds_104_lagged"] == 1.0


def test_geomean_averages_across_an_assay_switch_without_a_unit_jump():
    """A 30-day window that straddles an assay switch used to average MPN and
    copies into one number. Every reading here is half its own action value, so
    the geomean must be exactly 0.5 — not something between 52 and 706."""
    beach = "mixed-geomean"
    rows = []
    for offset in range(8):
        day = (pd.Timestamp("2026-04-01") + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")
        if offset % 2:
            rows.append(_observation(beach, day, 706.5, method=PCR_METHOD, units=PCR_UNITS))
        else:
            rows.append(_observation(beach, day, 52.0))
    beach_day = build_beach_day_frame(_observations(rows), _stations([beach]), _advisories())
    geomean = _regulatory_geomean_features(add_temporal_features(beach_day.sort_values("sample_date")))
    assert float(geomean.iloc[-1]["enterococcus_action_ratio_geomean_30d_lagged"]) == pytest.approx(0.5)


def test_subdetection_floor_is_one_reported_unit_of_the_rows_own_assay():
    """A zero reading must not send log10 to -inf, and the floor that replaces
    the old raw `clip(lower=1)` convention is ONE REPORTED UNIT — which is 1/104
    of a culture action value but 1/1413 of a molecular one. A single constant
    for both assays silently reclips one of them (see
    ``test_culture_only_ratio_geomeans_are_an_exact_rescale_of_the_raw_ones``).
    """
    assert CULTURE_RATIO_SUBDETECTION_FLOOR == pytest.approx(1.0 / CULTURE_ENTEROCOCCUS_STV)
    assert PCR_RATIO_SUBDETECTION_FLOOR == pytest.approx(
        1.0 / PCR_ENTEROCOCCUS_THRESHOLD_COPIES
    )

    culture = _ratio_history("nondetect-culture", "2026-04-01", [0.0, 0.0, 0.0, 0.0])
    culture_geo = _regulatory_geomean_features(add_temporal_features(culture))
    culture_value = float(culture_geo.iloc[-1]["enterococcus_action_ratio_geomean_30d_lagged"])
    assert np.isfinite(culture_value)
    assert culture_value == pytest.approx(CULTURE_RATIO_SUBDETECTION_FLOOR)

    # 0.5 copies/100mL is below one reported unit, so it floors — at the
    # MOLECULAR unit, recovered per row from raw / ratio.
    pcr = _ratio_history(
        "subunit-pcr",
        "2026-04-01",
        [0.5 / PCR_ENTEROCOCCUS_THRESHOLD_COPIES] * 4,
        action_value=PCR_ENTEROCOCCUS_THRESHOLD_COPIES,
    )
    pcr_geo = _regulatory_geomean_features(add_temporal_features(pcr))
    assert float(
        pcr_geo.iloc[-1]["enterococcus_action_ratio_geomean_30d_lagged"]
    ) == pytest.approx(PCR_RATIO_SUBDETECTION_FLOOR)

    # …and 0.5 MPN/100mL on a culture beach floors at the CULTURE unit, 13.59x
    # higher. Same number, different assay, different floor.
    culture_subunit = _ratio_history(
        "subunit-culture", "2026-04-01", [0.5 / CULTURE_ENTEROCOCCUS_STV] * 4
    )
    culture_subunit_geo = _regulatory_geomean_features(add_temporal_features(culture_subunit))
    assert float(
        culture_subunit_geo.iloc[-1]["enterococcus_action_ratio_geomean_30d_lagged"]
    ) == pytest.approx(CULTURE_RATIO_SUBDETECTION_FLOOR)


def _raw_convention_geomeans(raw_values: list[float], dates: pd.DatetimeIndex):
    """`main`'s derivation, reimplemented independently: geomean of the RAW value
    clipped at one reported unit, compared against the raw 35 / 104 triggers."""
    log_raw = pd.Series(
        np.log10(np.clip(np.asarray(raw_values, dtype=float), 1.0, None)), index=dates
    )
    mean_30d = log_raw.rolling("30D", min_periods=2, closed="left").mean()
    mean_42d = log_raw.rolling("42D", min_periods=2, closed="left").mean()
    flags = pd.DataFrame(
        {
            "geomean_30d_exceeds_35_lagged": (mean_30d >= np.log10(35.0)).astype(float),
            "geomean_30d_exceeds_104_lagged": (mean_30d >= np.log10(104.0)).astype(float),
            "geomean_42d_exceeds_35_lagged": (mean_42d >= np.log10(35.0)).astype(float),
        }
    ).reset_index(drop=True)
    return (
        (10.0**mean_30d).reset_index(drop=True),
        (10.0**mean_42d).reset_index(drop=True),
        flags,
    )


def test_culture_only_ratio_geomeans_are_an_exact_rescale_of_the_raw_ones():
    """THE property that makes this change safe, and the one a wrong floor breaks.

    On a beach that only ever used culture there is no assay mixing to repair,
    so moving the geomeans onto the ratio scale must be a **pure monotone
    rescale** by 1/104: every geomean exactly 1/104 of the raw-derived one, every
    trigger flag identical, and therefore every tree model provably invariant.
    "Monotone rescale => trees invariant => null result expected" is the
    load-bearing argument for this PR's measured null, so it has to hold exactly
    on the population where no mixing is possible.

    It only holds if the sub-detection floor is one reported unit of THIS row's
    action value. A flat molecular floor (1/1413) clips culture rows 13.59x lower
    than `clip(lower=1)` did, which both moves the geomean values and — the two
    zero readings below are what forces it — flips a trigger flag. Measured over
    full history on pure-culture beaches, a flat 1/1413 floor moves 29 / 6 / 52
    of the three flags and 3,519 30-day geomeans; per-assay moves none.
    """
    raw_values = [0.0, 100.0, 120.0, 90.0, 80.0, 110.0, 50.0, 0.0, 4.0, 260.0]
    frame = _ratio_history(
        "pure-culture", "2026-04-01", [v / CULTURE_ENTEROCOCCUS_STV for v in raw_values]
    )
    enriched = add_temporal_features(frame)
    geomean = _regulatory_geomean_features(enriched).reset_index(drop=True)

    dates = pd.DatetimeIndex(pd.to_datetime(frame["sample_date"]))
    expected_30d, expected_42d, expected_flags = _raw_convention_geomeans(raw_values, dates)

    for column, expected in (
        ("enterococcus_action_ratio_geomean_30d_lagged", expected_30d),
        ("enterococcus_action_ratio_geomean_42d_lagged", expected_42d),
    ):
        got = geomean[column]
        # min_periods=2, so only the first two rows are undefined.
        assert got.notna().sum() == len(raw_values) - 2
        pd.testing.assert_series_equal(
            got,
            expected / CULTURE_ENTEROCOCCUS_STV,
            check_names=False,
            rtol=1e-12,
            atol=0.0,
        )

    for column in expected_flags.columns:
        pd.testing.assert_series_equal(
            geomean[column], expected_flags[column], check_names=False
        )

    # Guard the guard: these values are chosen so a flat molecular floor is not
    # merely imprecise but changes a published trigger flag.
    assert expected_flags["geomean_30d_exceeds_35_lagged"].iloc[6] == 1.0


# --------------------------------------------------------------------------- 4
def test_guard_rejects_a_feature_built_from_the_raw_column():
    with pytest.raises(RawEnterococcusFeatureError) as excinfo:
        assert_no_raw_value_features(
            ["precip_mm_24h", "enterococcus_value_lag_1", "enterococcus_value_rolling_mean_7d"]
        )
    message = str(excinfo.value)
    assert "enterococcus_value_lag_1" in message
    assert "enterococcus_value_rolling_mean_7d" in message
    assert ENTEROCOCCUS_RATIO_COLUMN in message


def test_guard_allows_the_ratio_features_and_the_recency_feature():
    assert_no_raw_value_features(
        [
            "enterococcus_action_ratio_lag_1",
            "enterococcus_action_ratio_last_obs",
            "enterococcus_action_ratio_geomean_30d_lagged",
            # Recency uses the column's null pattern, never its magnitude, so it
            # is assay-independent and keeps the historical name.
            "days_since_enterococcus_value_obs",
        ]
    )


def test_guard_runs_on_the_real_feature_set_and_the_raw_column_is_absent():
    beach = "guard-beach"
    rows = [
        _observation(beach, f"2026-04-{day:02d}", 20.0 + day) for day in range(1, 12)
    ]
    beach_day = build_beach_day_frame(_observations(rows), _stations([beach]), _advisories())
    enriched = add_temporal_features(beach_day)
    columns = _model_feature_columns(enriched)  # raises if the guard trips

    assert "enterococcus_action_ratio_lag_1" in columns
    assert "enterococcus_action_ratio_last_obs" in columns
    assert "enterococcus_value_lag_1" not in columns
    assert "enterococcus_value_last_obs" not in columns
    assert "enterococcus_value" not in columns
    assert ENTEROCOCCUS_RATIO_COLUMN not in columns  # current-row value, still leaky
    assert "log_enterococcus" not in columns
    # Recency survives under its historical name.
    assert "days_since_enterococcus_value_obs" in columns


def test_log_enterococcus_stays_on_the_raw_scale():
    """Deliberate exception, pinned so it cannot drift silently: this is the
    density REGRESSION TARGET and it is published to users as
    ForecastRecord.predicted_log_enterococcus, with a serve-time fallback that
    computes log10 of the raw reading. Moving it to the ratio scale would change
    what a served number means. Recorded as the known remaining gap in
    docs/ACTION_VALUE_NORMALIZATION.md."""
    beach = "density-beach"
    beach_day = build_beach_day_frame(
        _observations([_observation(beach, "2026-04-01", 1000.0, method=PCR_METHOD, units=PCR_UNITS)]),
        _stations([beach]),
        _advisories(),
    )
    enriched = add_temporal_features(beach_day)
    assert float(enriched.iloc[0]["log_enterococcus"]) == pytest.approx(math.log10(1000.0))


def test_renamed_features_are_still_detected_as_bacteria_history():
    """The rename's sharpest risk. `is_bacteria_history_feature` drives the
    serve-time stale-censoring path (app/ml/stale_evaluation.py); if its regexes
    stopped matching the renamed columns, censoring would silently stop zeroing
    the bacteria history on between-sample rows — a leak with no error.
    """
    from app.ml.weather_delta import is_bacteria_history_feature

    for column in (
        "enterococcus_action_ratio_lag_1",
        "enterococcus_action_ratio_lag_28",
        "enterococcus_action_ratio_last_obs",
        "enterococcus_action_ratio_geomean_30d_lagged",
        "enterococcus_action_ratio_geomean_42d_lagged",
        "geomean_30d_exceeds_35_lagged",
        "samples_in_geomean_30d_lagged",
        "days_since_enterococcus_value_obs",
        # Legacy spellings stay matched so a persisted holdout artifact from
        # before the rename is still censored rather than leaking.
        "enterococcus_value_lag_1",
        "enterococcus_value_last_obs",
        "enterococcus_geomean_30d_lagged",
    ):
        assert is_bacteria_history_feature(column), column

    for column in ("precip_mm_24h", "wave_height_m_lag_1", "solar_inactivation_index"):
        assert not is_bacteria_history_feature(column), column


def test_persistence_fallback_prefers_the_ratio_and_is_method_correct():
    """The legacy `enterococcus_value_last_obs > 104` fallback is method-blind:
    it reads a clean San Diego copy count as an exceedance. With the ratio
    present, "exceeded" is `> 1.0` and is correct for either assay."""
    from app.ml.training import _persistence_probabilities

    # 1000 copies is CLEAN (below 1413) but 1000 > 104, so the raw rule would
    # have said "exceeded". 150 MPN genuinely exceeds.
    features = pd.DataFrame(
        {
            "enterococcus_action_ratio_last_obs": [1000 / 1413, 150 / 104, np.nan],
        }
    )
    assert _persistence_probabilities(features, 104.0).tolist() == [0.0, 1.0, 0.0]


def test_frame_without_a_ratio_column_falls_back_to_the_culture_action_value():
    """Legacy/fixture frames carry no assay information at all. They must not
    silently blank every bacteria-history feature; the culture action value is
    the documented fallback and is a pure rescale, so tree models are unchanged.
    """
    frame = pd.DataFrame(
        [
            {
                "beach_id": "legacy",
                "sample_date": f"2026-04-{day:02d}",
                "sample_time": f"2026-04-{day:02d}T08:00:00-07:00",
                "enterococcus_value": 100.0 + day,
                "exceeds_stv": 0,
            }
            for day in range(1, 5)
        ]
    )
    enriched = add_temporal_features(frame)
    assert enriched["enterococcus_action_ratio_lag_1"].iloc[1] == pytest.approx(
        101.0 / CULTURE_ENTEROCOCCUS_STV
    )
    assert enriched["enterococcus_action_ratio_lag_1"].notna().any()
