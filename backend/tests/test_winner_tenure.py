"""Winner-tenure hysteresis (Step 9).

The statistical swap tests in `_spatially_qualified_production_winner` are
per-run: they answer "is the challenger better today" and cannot bound how OFTEN
the answer changes. Measured over the 105 forecast dates to 2026-08-07 the served
winner changed 11 times (~every 10 days) while a clean single-regime serving
calibrator needs ~7 days of history to accumulate — so no serving configuration
ever outlived its own calibrator, and the live fit window measured 0.0% live-regime
rows.

These tests pin the tenure layer that bounds the swap RATE, and in particular pin
the two escape hatches, because both are places where a well-meaning edit would
silently restore daily churn.
"""
import inspect
import json
from datetime import UTC, datetime, timedelta

from app.ml.training import (
    _WINNER_EMERGENCY_CONFIRMATION_RUNS,
    _WINNER_MIN_TENURE_DAYS,
    _WINNER_SWAP_CONFIRMATION_RUNS,
    _WINNER_TENURE_KEY,
    WinnerTenure,
    _apply_winner_tenure,
    _read_production_model_registry,
    _run_winner_only,
    _tenure_days_held,
    _write_production_model_registry,
)

T0 = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _held(days: float) -> datetime:
    return T0 + timedelta(days=days)


def _state(**kwargs) -> WinnerTenure:
    base = {"winner": "hist_gbm", "promoted_at": T0}
    base.update(kwargs)
    return WinnerTenure(**base)


def _apply(*, statistical_choice, tenure, now, passing=True, **kwargs):
    return _apply_winner_tenure(
        incumbent="hist_gbm",
        statistical_choice=statistical_choice,
        tenure=tenure,
        now=now,
        incumbent_passing=passing,
        **kwargs,
    )


# --------------------------------------------------------------------------
# The floor itself
# --------------------------------------------------------------------------


def test_tenure_floor_suppresses_a_statistically_justified_swap():
    """The statistical tests already said "swap". Inside the floor we do not."""
    winner, state, record = _apply(
        statistical_choice="xgb_undersample_ensemble",
        tenure=_state(challenger="xgb_undersample_ensemble", challenger_streak=99),
        now=_held(_WINNER_MIN_TENURE_DAYS - 1),
    )
    assert winner == "hist_gbm"
    assert record["suppressed_swap"] is True
    assert any("tenure" in str(r) for r in record["suppressed_because"])
    # The incumbent keeps its ORIGINAL promotion date — a suppressed swap must not
    # restart the clock, or the floor could be held open indefinitely.
    assert state.promoted_at == T0


def test_swap_takes_effect_once_tenure_elapsed_and_confirmed():
    winner, state, record = _apply(
        statistical_choice="xgb_undersample_ensemble",
        tenure=_state(
            challenger="xgb_undersample_ensemble",
            challenger_streak=_WINNER_SWAP_CONFIRMATION_RUNS - 1,
        ),
        now=_held(_WINNER_MIN_TENURE_DAYS + 1),
    )
    assert winner == "xgb_undersample_ensemble"
    assert record["swap_reason"] == "tenure_elapsed_and_confirmed"
    # The clock restarts on the NEW winner, so the next swap is another 60 days out.
    assert state.winner == "xgb_undersample_ensemble"
    assert state.promoted_at == _held(_WINNER_MIN_TENURE_DAYS + 1)
    assert state.challenger is None


def test_tenure_elapsed_alone_does_not_swap_without_confirmation():
    """Otherwise the floor would merely reschedule the churn: on the first
    eligible day the winner becomes whatever leads that single noisy backtest."""
    winner, _, record = _apply(
        statistical_choice="xgb_undersample_ensemble",
        tenure=_state(),  # no streak yet — this is the challenger's first lead
        now=_held(_WINNER_MIN_TENURE_DAYS + 30),
    )
    assert winner == "hist_gbm"
    assert record["challenger_streak"] == 1
    assert any("confirmation streak" in str(r) for r in record["suppressed_because"])


# --------------------------------------------------------------------------
# The confirmation streak
# --------------------------------------------------------------------------


def test_confirmation_streak_accrues_during_the_lockout():
    """A genuinely better challenger pays NO extra latency for the floor: it
    banks its streak while locked out and swaps the day the floor expires."""
    tenure = _state()
    for run in range(_WINNER_SWAP_CONFIRMATION_RUNS):
        winner, tenure, record = _apply(
            statistical_choice="xgb_undersample_ensemble",
            tenure=tenure,
            now=_held(run),  # every one of these is deep inside the floor
        )
        assert winner == "hist_gbm"
        assert record["challenger_streak"] == run + 1

    # Streak is already satisfied when the floor lifts -> swap on that very run.
    winner, _, record = _apply(
        statistical_choice="xgb_undersample_ensemble",
        tenure=tenure,
        now=_held(_WINNER_MIN_TENURE_DAYS),
    )
    assert winner == "xgb_undersample_ensemble"
    assert record["swap_reason"] == "tenure_elapsed_and_confirmed"


def test_streak_resets_when_the_challenger_stops_leading():
    tenure = _state(challenger="xgb_undersample_ensemble", challenger_streak=5)
    _, tenure, _ = _apply(
        statistical_choice="hist_gbm",  # incumbent led this run
        tenure=tenure,
        now=_held(1),
    )
    assert tenure.challenger is None
    assert tenure.challenger_streak == 0


def test_streak_resets_when_a_DIFFERENT_challenger_leads():
    """Two candidates alternating in the lead must not pool their evidence."""
    _, tenure, record = _apply(
        statistical_choice="hist_gbm_persistence_blend",
        tenure=_state(challenger="xgb_undersample_ensemble", challenger_streak=6),
        now=_held(_WINNER_MIN_TENURE_DAYS + 1),
    )
    assert record["challenger_streak"] == 1
    assert tenure.challenger == "hist_gbm_persistence_blend"


# --------------------------------------------------------------------------
# The emergency bypass — the deliberate escape hatch
# --------------------------------------------------------------------------


def test_emergency_bypass_does_not_fire_on_a_single_failing_run():
    """`hist_gbm`'s public_release_eligible verdict flipped 22 times in 186
    recovered runs. A one-run bypass turns the safety valve into a second churn
    channel — measured, it produced 5 replay swaps instead of 2."""
    winner, state, record = _apply(
        statistical_choice="xgb_undersample_ensemble",
        tenure=_state(),
        now=_held(1),
        passing=False,
    )
    assert winner == "hist_gbm"
    assert state.incumbent_fail_streak == 1
    assert record["suppressed_swap"] is True


def test_emergency_bypass_fires_after_confirmed_consecutive_failures():
    tenure = _state()
    winner = "hist_gbm"
    for _ in range(_WINNER_EMERGENCY_CONFIRMATION_RUNS):
        winner, tenure, record = _apply(
            statistical_choice="xgb_undersample_ensemble",
            tenure=tenure,
            now=_held(1),
            passing=False,
        )
    assert winner == "xgb_undersample_ensemble"
    assert record["swap_reason"] == "emergency_incumbent_failed_spatial_gates"


def test_emergency_bypass_ignores_the_tenure_floor():
    """An unreleasable incumbent must never be pinned by tenure — the release
    gate would otherwise freeze publication for the rest of the 60 days."""
    tenure = _state(incumbent_fail_streak=_WINNER_EMERGENCY_CONFIRMATION_RUNS - 1)
    winner, _, record = _apply(
        statistical_choice="xgb_undersample_ensemble",
        tenure=tenure,
        now=_held(0),  # zero days of tenure
        passing=False,
    )
    assert winner == "xgb_undersample_ensemble"
    assert record["swap_reason"] == "emergency_incumbent_failed_spatial_gates"


def test_incumbent_fail_streak_resets_on_a_passing_run():
    _, tenure, _ = _apply(
        statistical_choice="hist_gbm",
        tenure=_state(incumbent_fail_streak=2),
        now=_held(1),
        passing=True,
    )
    assert tenure.incumbent_fail_streak == 0


def test_fail_streak_survives_when_there_is_nothing_to_swap_to():
    """When the incumbent fails and no sibling passes, the selector returns the
    incumbent. The failure evidence must still accumulate, or a broken model with
    no immediate replacement resets its own counter every run."""
    _, tenure, _ = _apply(
        statistical_choice="hist_gbm",  # nothing passed; selector fell back
        tenure=_state(incumbent_fail_streak=1),
        now=_held(1),
        passing=False,
    )
    assert tenure.incumbent_fail_streak == 2


def test_there_is_no_large_gap_bypass():
    """Deliberate: every historical oscillation was driven by county-AUCPR gaps
    of +0.08..+0.11 on folds whose cluster-bootstrap 95% half-width is ~0.136, so
    no daily point gap can be trusted as "decisively better". A challenger that
    the statistical tests love is STILL held by the floor."""
    winner, _, _ = _apply(
        statistical_choice="xgb_undersample_ensemble",
        tenure=_state(challenger="xgb_undersample_ensemble", challenger_streak=1000),
        now=_held(_WINNER_MIN_TENURE_DAYS - 0.5),
    )
    assert winner == "hist_gbm"


# --------------------------------------------------------------------------
# State handling
# --------------------------------------------------------------------------


def test_unknown_or_drifted_state_seeds_the_clock_rather_than_waiving_it():
    """Fail-safe toward stability: no trustworthy promotion date means the floor
    applies from NOW, never that the floor is skipped."""
    for tenure in (None, WinnerTenure(), _state(winner="some_other_model")):
        winner, state, record = _apply(
            statistical_choice="xgb_undersample_ensemble",
            tenure=tenure,
            now=T0,
        )
        assert winner == "hist_gbm"
        assert record.get("tenure_seeded") is True
        assert state.promoted_at == T0


def test_tenure_state_round_trips_through_the_registry(tmp_path):
    tenure = WinnerTenure(
        winner="xgb_undersample_ensemble",
        promoted_at=T0,
        challenger="hist_gbm",
        challenger_streak=3,
        challenger_first_seen_at=_held(2),
        incumbent_fail_streak=1,
    )
    _write_production_model_registry(
        tmp_path, winner="xgb_undersample_ensemble", regressor="hist_gbm_regressor",
        tenure=tenure,
    )
    raw = json.loads((tmp_path / "production_model.json").read_text())
    assert raw["winner"] == "xgb_undersample_ensemble"
    restored = WinnerTenure.from_json(
        _read_production_model_registry(tmp_path)[_WINNER_TENURE_KEY]
    )
    assert restored == tenure


def test_registry_without_tenure_still_reads(tmp_path):
    """Every registry on disk today predates this field."""
    (tmp_path / "production_model.json").write_text(
        json.dumps({"winner": "xgb_undersample_ensemble", "regressor": "hist_gbm_regressor"})
    )
    registry = _read_production_model_registry(tmp_path)
    assert WinnerTenure.from_json(registry.get(_WINNER_TENURE_KEY)) == WinnerTenure()


def test_days_held_tolerates_mixed_timezone_awareness():
    naive = datetime(2026, 6, 1, 12, 0)
    assert _tenure_days_held(naive, T0 + timedelta(days=10)) == 10.0
    assert _tenure_days_held(T0, naive + timedelta(days=10)) == 10.0
    assert _tenure_days_held(None, T0) == 0.0
    # Never negative: a clock skew must not read as "tenure already elapsed".
    assert _tenure_days_held(T0 + timedelta(days=5), T0) == 0.0


# --------------------------------------------------------------------------
# Wiring — the daily path is the one that churns
# --------------------------------------------------------------------------


def test_daily_winner_only_path_is_tenure_gated_and_persists_its_decision():
    """The measured churn was 11 served-winner changes in 105 days, of which only
    4 reached `production_model.json`: the daily gate swapped ephemerally and the
    next run re-litigated the identical comparison from the identical start. Both
    halves of the fix live in `_run_winner_only` — gate the swap, then persist the
    state — and dropping either one silently restores daily oscillation."""
    source = inspect.getsource(_run_winner_only)
    assert "_apply_winner_tenure(" in source
    assert "_write_production_model_registry(" in source
    assert _WINNER_TENURE_KEY in source
