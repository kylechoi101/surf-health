"""The daily incremental branch must refresh state rows without destroying data.

Before this guard, ``cli.py``'s incremental BeachWatch branch ran::

    merged.drop_duplicates(subset=["beach_id", "sample_time"], keep="last")

That key is strictly coarser than the one the additive merges use to build the
same frame, so every ordinary daily run deleted rows those merges had just been
careful to keep. Measured on the shipped ``observations.parquet`` (503,766 rows):
**1,949 observations destroyed, 218 of them exceedances**, and every destroyed
row belonged to an additive source (1,908 ``BeachWatch.SafeToSwim``, 39
``CEDEN.SafeToSwim``, 2 ``BeachWatch.Live``) rather than to the state export the
branch exists to refresh. Losing an exceedance is a false negative.

The tests below pin both halves of the fix: what must still collapse (a
re-normalized state row landing on its own stale copy, including when the value
was revised) and what must not (a second assay at the same instant, and every
additive-source row).
"""

from __future__ import annotations

import pandas as pd

from app.data.pipeline.cli import dedupe_incremental_beachwatch_observations


def _row(**overrides: object) -> dict:
    base = {
        "beach_id": "ca000001-san-diego-test",
        "sample_time": pd.Timestamp("2026-08-01 09:00:00"),
        "sample_date": pd.Timestamp("2026-08-01").date(),
        "analyte": "enterococcus",
        "method": "Enterolert",
        "units": "MPN/100ml",
        "value": 10.0,
        "exceeds_stv": False,
        "data_source": "BeachWatch",
    }
    base.update(overrides)
    return base


def _frame(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


# ---------------------------------------------------------------- collapse


def test_renormalized_state_row_replaces_its_stale_self() -> None:
    """The one thing the branch exists to do."""
    merged = _frame(_row(value=10.0), _row(value=10.0))
    out = dedupe_incremental_beachwatch_observations(merged)
    assert len(out) == 1


def test_revised_state_value_replaces_rather_than_duplicating() -> None:
    """`value` is out of the key so a correction lands instead of stacking.

    With value IN the key the revised row would not match its predecessor, both
    would survive, and ``build_beach_day_frame``'s worst-sample collapse would
    then pick the higher of the two — so a *downward* revision could never take
    effect. Same reasoning the county-direct merge uses.
    """
    stale = _row(value=500.0, exceeds_stv=True)
    revised = _row(value=12.0, exceeds_stv=False)
    out = dedupe_incremental_beachwatch_observations(_frame(stale, revised))
    assert len(out) == 1
    assert out.iloc[0]["value"] == 12.0
    assert not bool(out.iloc[0]["exceeds_stv"])


def test_state_units_respelling_still_collapses() -> None:
    """"CFU/100 mL" and "CFU/100ml" are one unit, so they are one row."""
    merged = _frame(
        _row(method="EPA 1600", units="CFU/100 mL", value=88.0),
        _row(method="EPA 1600", units="CFU/100ml", value=88.0),
    )
    assert len(dedupe_incremental_beachwatch_observations(merged)) == 1


# ---------------------------------------------------------------- preserve


def test_two_assays_at_the_same_instant_are_two_observations() -> None:
    """The defect, in its purest form.

    San Diego runs culture and ddPCR on the same water. Under the old key the
    second one silently vanished — and because ddPCR reports copies, the one
    that vanished was usually the one that exceeded.
    """
    merged = _frame(
        _row(method="Enterolert", units="MPN/100ml", value=10.0, exceeds_stv=False),
        _row(method="ddPCR", units="Copies/100ml", value=5000.0, exceeds_stv=True),
    )
    out = dedupe_incremental_beachwatch_observations(merged)
    assert len(out) == 2
    assert bool(pd.to_numeric(out["exceeds_stv"]).sum() == 1)


def test_additive_source_replicates_survive() -> None:
    """1,211 SafeToSwim groups on the shipped frame are same-time replicates.

    They differ only in value, so a value-blind key would delete one of each —
    which is why the dedupe is confined to state rows.
    """
    merged = _frame(
        _row(data_source="BeachWatch.SafeToSwim", value=400.0, exceeds_stv=True),
        _row(data_source="BeachWatch.SafeToSwim", value=700.0, exceeds_stv=True),
    )
    assert len(dedupe_incremental_beachwatch_observations(merged)) == 2


def test_state_row_does_not_destroy_an_additive_mirror() -> None:
    """Cross-source collapse belongs to the merge functions, not here.

    They own the source-priority order and the value-matching mirror rule; this
    branch has neither and must not guess.
    """
    merged = _frame(
        _row(data_source="BeachWatch", value=400.0, exceeds_stv=True),
        _row(data_source="BeachWatch.Live", value=700.0, exceeds_stv=True),
        _row(data_source="CEDEN.SafeToSwim", value=430.0, exceeds_stv=True),
    )
    assert len(dedupe_incremental_beachwatch_observations(merged)) == 3


def test_exceedance_at_a_shared_timestamp_is_never_dropped() -> None:
    """The regression that mattered: 218 exceedances destroyed per run."""
    merged = _frame(
        _row(data_source="BeachWatch.SafeToSwim", value=2.0, exceeds_stv=False),
        _row(data_source="BeachWatch.SafeToSwim", value=5000.0, exceeds_stv=True),
    )
    out = dedupe_incremental_beachwatch_observations(merged)
    assert int(pd.to_numeric(out["exceeds_stv"]).sum()) == 1


def test_old_key_would_have_destroyed_what_the_new_one_keeps() -> None:
    """Pins the contrast, so a future 'simplification' back to the old key fails."""
    merged = _frame(
        _row(method="Enterolert", units="MPN/100ml", value=10.0, exceeds_stv=False),
        _row(method="ddPCR", units="Copies/100ml", value=5000.0, exceeds_stv=True),
        _row(data_source="BeachWatch.SafeToSwim", value=700.0, exceeds_stv=True),
    )
    old = merged.drop_duplicates(subset=["beach_id", "sample_time"], keep="last")
    assert len(old) == 1
    assert len(dedupe_incremental_beachwatch_observations(merged)) == 3


# ---------------------------------------------------------------- properties


def test_dedupe_is_idempotent() -> None:
    merged = _frame(
        _row(value=10.0),
        _row(value=10.0),
        _row(method="ddPCR", units="Copies/100ml", value=5000.0),
        _row(data_source="BeachWatch.Live", value=700.0),
    )
    once = dedupe_incremental_beachwatch_observations(merged)
    twice = dedupe_incremental_beachwatch_observations(once.copy())
    pd.testing.assert_frame_equal(once, twice)


def test_missing_data_source_is_treated_as_state() -> None:
    """Pre-additive vintages have no data_source; merge_live uses the same rule."""
    merged = _frame(_row(value=10.0), _row(value=10.0)).drop(columns=["data_source"])
    assert len(dedupe_incremental_beachwatch_observations(merged)) == 1


def test_empty_frame_passes_through() -> None:
    assert dedupe_incremental_beachwatch_observations(pd.DataFrame()).empty
