"""Serving-configuration provenance (app/ml/serving_config.py) — end-state E5.

Two properties are load-bearing and both are asserted here:

  * a change that alters served numbers CANNOT leave the fingerprint unchanged;
  * a change that does not alter them does not churn it.

The second is what makes the first useful. A fingerprint that moved on every
daily refit would partition the history into one regime per run, the
composition report would read 0% live regime by construction, and nobody would
be able to tell a real configuration change from a Tuesday.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from app.ml import calibration, serving_config
from app.ml.serving_config import (
    ERA_PERSISTENCE_FLOOR_PRE_FINGERPRINT,
    ERA_PRE_ROUTER,
    ERA_ROUTER_LOGGED,
    ERA_ROUTER_LOGGING_GAP_UNKNOWABLE,
    REGISTRY_FILE,
    ROUTER_TWO_TIER,
    SERVING_PATH_VERSION,
    build_serving_config,
    config_fingerprint,
    record_serving_config,
    regime_labels,
)

_POLICY = {
    "window_days": 120,
    "min_pairs": 500,
    "min_positives": 25,
    "min_top_step_support": 10,
    "forward_match_days": 3,
    "pin_era_exclusion": True,
    "applied": True,
}
_ROUTED = {
    "router": ROUTER_TWO_TIER,
    "models": ["xgb_undersample_ensemble", "xgb_undersample_offset"],
    "fresh_cutoff_days": 3,
    "blend_end_days": 5,
}


def _fingerprint(**overrides) -> str:
    kwargs = {
        "winner": "xgb_undersample_ensemble",
        "probability_source": dict(_ROUTED),
        "calibration_policy": dict(_POLICY),
    }
    kwargs.update(overrides)
    return config_fingerprint(build_serving_config(**kwargs))


# --------------------------------------------------------------------------
# It must move when the served number can move
# --------------------------------------------------------------------------


def test_fingerprint_is_deterministic_across_calls() -> None:
    assert _fingerprint() == _fingerprint()
    assert len(_fingerprint()) == serving_config.FINGERPRINT_LENGTH


@pytest.mark.parametrize(
    "constant",
    ["_LOW_THRESHOLD", "_HIGH_THRESHOLD", "_VERY_HIGH_THRESHOLD"],
)
def test_a_floor_or_band_constant_change_moves_the_fingerprint(monkeypatch, constant) -> None:
    """The persistence floor, the advisory floor and the band cutpoints all
    write straight into a served field (`p_exceed` or `risk_band`). Step 10 will
    move the Low/Moderate cut 0.20 -> 0.10; that MUST read as a new regime, not
    as more of the old one."""
    before = _fingerprint()
    monkeypatch.setattr(calibration, constant, getattr(calibration, constant) - 0.01)
    assert _fingerprint() != before, f"{constant} change did not move the fingerprint"


def test_a_router_cutoff_change_moves_the_fingerprint() -> None:
    """`_FRESH_ROUTE_CUTOFF_DAYS` / `_ROUTE_BLEND_END_DAYS` decide WHICH model
    serves a beach at a given lag, so they are configuration."""
    before = _fingerprint()
    assert _fingerprint(probability_source={**_ROUTED, "fresh_cutoff_days": 4}) != before
    assert _fingerprint(probability_source={**_ROUTED, "blend_end_days": 7}) != before


def test_turning_the_router_off_moves_the_fingerprint() -> None:
    """This is the 2026-07-22 boundary the log could not see at all. Rows from
    07-22..07-28 are router-served and logged identically to pre-router rows."""
    unrouted = {"router": None, "models": ["xgb_undersample_ensemble"]}
    assert _fingerprint(probability_source=unrouted) != _fingerprint()


def test_a_winner_change_moves_the_fingerprint() -> None:
    """Winner churn — 11 changes in 105 days — is a real serving change. Making
    it countable is what Step 9 needs."""
    assert _fingerprint(winner="hist_gbm") != _fingerprint()


def test_serve_path_version_moves_the_fingerprint() -> None:
    """The escape hatch for structural changes no constant captures (the
    override -> floor swap, the floor moving out of the calibration branch)."""
    before = _fingerprint()
    original = serving_config.SERVING_PATH_VERSION
    try:
        serving_config.SERVING_PATH_VERSION = original + 1
        assert _fingerprint() != before
    finally:
        serving_config.SERVING_PATH_VERSION = original


def test_losing_the_serving_calibration_moves_the_fingerprint() -> None:
    """A run too thin to fit a calibrator serves materially different numbers
    under the same code, so `applied` is part of the configuration."""
    assert _fingerprint(calibration_policy={**_POLICY, "applied": False}) != _fingerprint()


def test_serve_path_version_is_pinned() -> None:
    """`serving_path_version` is a human promise: a serve-path edit that changes
    numbers without touching any constant and without a bump would silently
    reuse a stale fingerprint. Pinning the version AND the fingerprint it
    produces makes the next such edit fail here, forcing the decision to be made
    rather than skipped.

    If this fails: decide whether your change alters a served number. If it
    does, bump SERVING_PATH_VERSION and update both values. If it does not,
    update the fingerprint only.
    """
    assert SERVING_PATH_VERSION == 4
    assert _fingerprint() == "6c28d645ca929f34"


# --------------------------------------------------------------------------
# It must NOT move when the served number cannot move
# --------------------------------------------------------------------------


def test_fitted_calibrator_knots_are_out_of_the_hash() -> None:
    """The serving isotonic is refit daily FROM THE LOG ITSELF. Hashing its
    knots would make every run its own regime and the composition report
    vacuous. It is also unnecessary: the calibration transform is already
    observable per row as p_exceed_precal -> p_exceed."""
    document = build_serving_config(
        winner="xgb_undersample_ensemble",
        probability_source=dict(_ROUTED),
        calibration_policy=dict(_POLICY),
    )
    flat = json.dumps(document)
    assert '"x"' not in flat and '"y"' not in flat
    assert "y_max" not in flat


def test_the_per_row_route_is_out_of_the_hash() -> None:
    """`served_offset_weight` is a function of DATA LAG, not configuration, and
    is already logged per row. One day of pipeline lag moves ~144 beaches onto a
    different model; that must not read as a configuration change."""
    document = build_serving_config(
        winner="xgb_undersample_ensemble",
        probability_source=dict(_ROUTED),
        calibration_policy=dict(_POLICY),
    )
    assert "served_offset_weight" not in json.dumps(document)


def test_a_constant_from_an_untaken_branch_does_not_churn_the_fingerprint() -> None:
    """The persistence-guard blend alpha only exists on that model's branch. On
    a run the ensemble won, changing it could not have moved a single served
    number, so it must not move the fingerprint."""
    guard = {"router": None, "models": ["hist_gbm_positive_persistence_guard"]}
    assert "persistence_blend_alpha" not in json.dumps(
        build_serving_config(
            winner="xgb_undersample_ensemble",
            probability_source=dict(_ROUTED),
            calibration_policy=dict(_POLICY),
        )
    )
    # ... but it IS hashed on the branch that uses it.
    with_alpha = _fingerprint(
        winner="hist_gbm_positive_persistence_guard",
        probability_source={**guard, "persistence_blend_alpha": 1.0},
    )
    without = _fingerprint(
        winner="hist_gbm_positive_persistence_guard",
        probability_source={**guard, "persistence_blend_alpha": 0.6},
    )
    assert with_alpha != without


def test_key_order_does_not_change_the_fingerprint() -> None:
    reordered = {
        "blend_end_days": 5,
        "fresh_cutoff_days": 3,
        "models": ["xgb_undersample_ensemble", "xgb_undersample_offset"],
        "router": ROUTER_TWO_TIER,
    }
    assert _fingerprint(probability_source=reordered) == _fingerprint()


# --------------------------------------------------------------------------
# Legacy-era reconstruction — honest about what it cannot know
# --------------------------------------------------------------------------


def _history_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2026-07-10",  # pre-router
                    "2026-07-24",  # router live, offset weight not yet logged
                    "2026-07-30",  # router logged
                    "2026-08-07",  # persistence floor era
                    "2026-08-08",  # fingerprinted
                ]
            ),
            "served_offset_weight": [None, None, 1.0, 1.0, 1.0],
            "persistence_floor_applied": [None, None, None, False, False],
            "serving_config_fingerprint": [None, None, None, None, "abc123def456aaaa"],
        }
    )


def test_eras_are_reconstructed_from_side_effects() -> None:
    labels = regime_labels(_history_frame()).tolist()
    assert labels[0] == f"legacy:{ERA_PRE_ROUTER}"
    assert labels[2] == f"legacy:{ERA_ROUTER_LOGGED}"
    assert labels[3] == f"legacy:{ERA_PERSISTENCE_FLOOR_PRE_FINGERPRINT}"
    assert labels[4] == "abc123def456aaaa", "a recorded fingerprint always wins"


def test_the_router_logging_gap_is_labelled_unknowable_not_back_dated() -> None:
    """2026-07-22..07-28 was router-served, but `served_offset_weight` only
    entered _HISTORY_COLUMNS on 07-29 (commit 2a4e6d1c4), so no side effect
    distinguishes those rows from pre-router ones. Labelling them
    `router_pre_persistence_floor` would be a fabricated retrospective claim;
    labelling them `pre_router` would be a known-false one. They get their own
    bucket, and it says so in its name."""
    labels = regime_labels(_history_frame()).tolist()
    assert labels[1] == f"legacy:{ERA_ROUTER_LOGGING_GAP_UNKNOWABLE}"
    assert labels[1] != f"legacy:{ERA_ROUTER_LOGGED}"
    assert labels[1] != f"legacy:{ERA_PRE_ROUTER}"


def test_regime_labels_survive_a_frame_with_no_provenance_columns() -> None:
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-05-01", "2026-07-25"])})
    labels = regime_labels(frame).tolist()
    assert labels == [
        f"legacy:{ERA_PRE_ROUTER}",
        f"legacy:{ERA_ROUTER_LOGGING_GAP_UNKNOWABLE}",
    ]


# --------------------------------------------------------------------------
# The decode table
# --------------------------------------------------------------------------


def test_registry_accumulates_runs_per_fingerprint(tmp_path) -> None:
    document = build_serving_config(
        winner="xgb_undersample_ensemble",
        probability_source=dict(_ROUTED),
        calibration_policy=dict(_POLICY),
    )
    fingerprint = config_fingerprint(document)
    record_serving_config(tmp_path, fingerprint, document, seen_at="2026-08-08T00:00:00+00:00")
    record_serving_config(tmp_path, fingerprint, document, seen_at="2026-08-09T00:00:00+00:00")
    registry = json.loads((tmp_path / REGISTRY_FILE).read_text())
    entry = registry["fingerprints"][fingerprint]
    assert entry["n_runs"] == 2
    assert entry["first_seen"] == "2026-08-08T00:00:00+00:00"
    assert entry["last_seen"] == "2026-08-09T00:00:00+00:00"
    # A bare hash is not provenance unless something can decode it.
    assert entry["document"]["probability_source"]["router"] == ROUTER_TWO_TIER


def test_registry_survives_a_corrupt_file(tmp_path) -> None:
    (tmp_path / REGISTRY_FILE).write_text("{not json")
    registry = record_serving_config(
        tmp_path, "deadbeefdeadbeef", {"a": 1}, seen_at="2026-08-08T00:00:00+00:00"
    )
    assert "deadbeefdeadbeef" in registry["fingerprints"]


def test_the_hashed_constants_are_the_ones_the_serve_path_uses() -> None:
    """`build_serving_config` reads the band/floor constants off
    `app.ml.calibration` at call time; `training` imports them by value. Both
    must resolve to the same numbers, or the fingerprint would describe a
    configuration the serve path is not running."""
    from app.ml import training

    assert training._LOW_THRESHOLD == calibration._LOW_THRESHOLD
    assert training._HIGH_THRESHOLD == calibration._HIGH_THRESHOLD
    assert training._CAL_VERY_HIGH == calibration._VERY_HIGH_THRESHOLD
