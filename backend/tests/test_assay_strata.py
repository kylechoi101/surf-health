"""Every published metric carries its culture/ddPCR pair (end-state E3).

The failure this guards against is silent: a pooled AUCPR over a mixture of two
labelling universes (culture at base rate ~0.10, San Diego ddPCR at ~0.59) looks
like a normal metric, reads like a normal metric, and moves whenever the assay
MIX moves even at perfectly constant skill. Nothing about the number announces
that it describes no population.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.ml.assay_strata import (
    CULTURE_KEY,
    MIN_STRATUM_ROWS,
    PCR_KEY,
    as_pcr_mask,
    assay_composition,
    attach_stratified_metrics,
    stratified_metrics,
    stratified_scalar,
)


def _population(n_culture: int = 200, n_pcr: int = 200, seed: int = 3):
    """Two strata with deliberately different base rates, as on disk."""
    rng = np.random.default_rng(seed)
    culture = rng.random(n_culture) < 0.10
    pcr = rng.random(n_pcr) < 0.60
    labels = np.concatenate([culture, pcr]).astype(int)
    is_pcr = np.concatenate([np.zeros(n_culture, bool), np.ones(n_pcr, bool)])
    # Real but imperfect signal inside each stratum -- overlapping, so AUCPR is
    # not saturated at 1.0 and can actually respond to the mix.
    probs = np.clip(0.20 + 0.30 * labels + rng.normal(0.0, 0.18, len(labels)), 0.01, 0.99)
    return labels, probs, is_pcr


# --- mask coercion -------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        np.array([True, False, True]),
        np.array([1.0, 0.0, 1.0]),  # how it travels through the numeric matrix
        np.array([1, 0, 1]),
        np.array([True, None, True], dtype=object),  # null -> culture
    ],
)
def test_as_pcr_mask_accepts_every_on_disk_encoding(raw):
    assert as_pcr_mask(raw, 3).tolist() == [True, False, True]


def test_as_pcr_mask_rejects_a_length_mismatch_rather_than_truncating():
    """A silently misaligned mask attributes rows to the WRONG regime, which is
    strictly worse than publishing no stratification -- the number would still
    look stratified."""
    assert as_pcr_mask(np.array([True, False]), 5) is None


def test_as_pcr_mask_of_none_is_none():
    assert as_pcr_mask(None, 4) is None


# --- the core cut --------------------------------------------------------------


def test_strata_are_scored_on_their_own_rows_only():
    labels, probs, is_pcr = _population()
    out = stratified_metrics(labels, probs, is_pcr)

    assert out[CULTURE_KEY]["n_rows"] == 200.0
    assert out[PCR_KEY]["n_rows"] == 200.0
    assert out[CULTURE_KEY]["n_positive"] == float(labels[~is_pcr].sum())
    assert out[PCR_KEY]["n_positive"] == float(labels[is_pcr].sum())
    # The whole point: the two base rates are far apart, and the pooled number
    # sits between them describing neither.
    assert out[CULTURE_KEY]["base_rate"] < 0.25
    assert out[PCR_KEY]["base_rate"] > 0.45


def test_composition_is_published_because_the_pooled_number_moves_with_it():
    labels, _, is_pcr = _population(n_culture=300, n_pcr=100)
    comp = assay_composition(is_pcr, labels)

    assert comp["n_rows"] == 400.0
    assert comp["pcr_row_fraction"] == pytest.approx(0.25)
    # ddPCR is a quarter of the rows but supplies most of the positives -- the
    # exact asymmetry (15% of rows / 52% of positives on disk) that makes a
    # pooled AUCPR uninterpretable.
    assert comp["pcr_positive_fraction"] > comp["pcr_row_fraction"]
    assert comp["pcr_base_rate"] > comp["culture_base_rate"]


def test_a_thin_stratum_reports_support_not_a_metric():
    """An AUCPR off a handful of rows is worse than no AUCPR: it gets cited."""
    n_pcr = MIN_STRATUM_ROWS - 1
    labels = np.concatenate([np.zeros(100, int), np.array([1, 0] * (n_pcr // 2 + 1))[:n_pcr]])
    labels[:20] = 1
    probs = np.full(len(labels), 0.3)
    is_pcr = np.concatenate([np.zeros(100, bool), np.ones(n_pcr, bool)])

    out = stratified_metrics(labels, probs, is_pcr)
    assert out[PCR_KEY]["insufficient_support"] is True
    assert "aucpr" not in out[PCR_KEY]
    assert "aucpr" in out[CULTURE_KEY]


def test_a_single_class_stratum_reports_support_not_a_metric():
    """average_precision_score over an all-negative slice is meaningless."""
    labels = np.concatenate([np.zeros(100, int), np.ones(100, int)])
    labels[:30] = 1  # culture has contrast; pcr is all-positive
    probs = np.linspace(0.05, 0.95, 200)
    is_pcr = np.concatenate([np.zeros(100, bool), np.ones(100, bool)])

    out = stratified_metrics(labels, probs, is_pcr)
    assert out[PCR_KEY]["insufficient_support"] is True
    assert out[PCR_KEY]["base_rate"] == 1.0


def test_missing_assay_indicator_yields_none_not_a_fake_cut():
    labels, probs, _ = _population()
    assert stratified_metrics(labels, probs, None) is None


# --- the attachment contract ---------------------------------------------------


def test_attach_leaves_the_pooled_figure_intact_and_adds_its_pair():
    labels, probs, is_pcr = _population()
    metrics = {"aucpr": 0.5, "brier": 0.2}
    attach_stratified_metrics(metrics, labels, probs, is_pcr)

    assert metrics["aucpr"] == 0.5, "the pooled figure must survive -- the gate reads it"
    assert set(metrics["by_assay"]) == {CULTURE_KEY, PCR_KEY, "composition"}


def test_attach_marks_an_impossible_cut_explicitly_rather_than_omitting_the_key():
    """An ABSENT by_assay reads as 'not stratified yet'; an explicit marker reads
    as 'attempted, and here is why it failed'. Only the second survives a
    consumer grepping system_health.json for E3 compliance."""
    labels, probs, _ = _population()
    metrics: dict = {}
    attach_stratified_metrics(metrics, labels, probs, None)

    assert metrics["by_assay"] == {"unavailable": "no_assay_indicator"}


def test_a_failing_metric_function_never_takes_down_a_training_run():
    labels, probs, is_pcr = _population()

    def _explode(_y, _p):
        raise RuntimeError("boom")

    out = stratified_metrics(labels, probs, is_pcr, metric_fn=_explode)
    assert out[CULTURE_KEY]["error"] == "metric_computation_failed"
    assert out[PCR_KEY]["error"] == "metric_computation_failed"


# --- the non-classification_metrics path (within-beach AUROC, the headline) ----


def test_stratified_scalar_slices_every_extra_array_alongside_the_labels():
    """within_beach_auroc needs per-row beach ids. If `extra` were not sliced with
    the same mask the ids would be misaligned against the labels and the reported
    within-beach number would be computed over the wrong grouping."""
    labels, probs, is_pcr = _population()
    beach_ids = np.array(["culture-beach"] * 200 + ["pcr-beach"] * 200)

    seen: dict[str, set] = {}

    def _capture(y, p, groups):
        seen[str(sorted(set(groups))[0])] = set(groups)
        return {"n": float(len(y))}

    out = stratified_scalar(labels, _capture, probs, is_pcr, extra={"groups": beach_ids})
    assert out[CULTURE_KEY]["n"] == 200.0
    assert out[PCR_KEY]["n"] == 200.0
    assert seen["culture-beach"] == {"culture-beach"}
    assert seen["pcr-beach"] == {"pcr-beach"}


# --- the property the whole module exists for ---------------------------------


def test_the_pooled_metric_moves_with_the_assay_MIX_at_constant_skill():
    """Demonstrates why E3 is not cosmetic.

    Hold both strata's rows and probabilities fixed, change only how many ddPCR
    rows are in the pool, and the pooled AUCPR moves a long way while neither
    stratum's AUCPR moves at all.
    """
    labels, probs, is_pcr = _population(n_culture=400, n_pcr=400)
    from app.ml.evaluation import classification_metrics

    heavy = np.concatenate([np.flatnonzero(~is_pcr)[:400], np.flatnonzero(is_pcr)[:400]])
    light = np.concatenate([np.flatnonzero(~is_pcr)[:400], np.flatnonzero(is_pcr)[:40]])

    pooled_heavy = classification_metrics(labels[heavy], probs[heavy])["aucpr"]
    pooled_light = classification_metrics(labels[light], probs[light])["aucpr"]
    strat_heavy = stratified_metrics(labels[heavy], probs[heavy], is_pcr[heavy])
    strat_light = stratified_metrics(labels[light], probs[light], is_pcr[light])

    assert abs(pooled_heavy - pooled_light) > 0.10, (
        "the pooled figure should be strongly mix-dependent -- that is the bug"
    )
    assert strat_heavy[CULTURE_KEY]["aucpr"] == pytest.approx(
        strat_light[CULTURE_KEY]["aucpr"]
    ), "the culture stratum is the same rows in both, so its metric must not move"


def test_served_outcomes_carry_the_assay_of_the_sample_that_scored_them():
    """The served-metric cut keys on the LABEL's assay, and any molecular sample
    that day marks the day molecular -- not the assay of whichever sample was
    worst, which would flip regime for reasons unrelated to the programme."""
    from app.ml.served_metrics import daily_outcomes

    observations = pd.DataFrame(
        [
            # ddPCR day where the CULTURE sample happens to be the worse one.
            {"beach_id": "b1", "sample_date": "2026-06-01", "exceeds_stv": True,
             "method": "Enterolert", "units": "MPN/100ml"},
            {"beach_id": "b1", "sample_date": "2026-06-01", "exceeds_stv": False,
             "method": "MCB-ddPCR SOP018-000", "units": "Copies/100ml"},
            {"beach_id": "b2", "sample_date": "2026-06-01", "exceeds_stv": False,
             "method": "EPA 1600", "units": "CFU/100ml"},
        ]
    )
    out = daily_outcomes(observations).set_index("beach_id")

    assert bool(out.loc["b1", "outcome_is_pcr"]) is True
    assert bool(out.loc["b2", "outcome_is_pcr"]) is False
    assert int(out.loc["b1", "exceeded"]) == 1


def test_daily_outcomes_without_method_columns_still_returns_outcomes():
    """A caller holding a slimmer frame gets unstratifiable outcomes, not a crash."""
    from app.ml.served_metrics import daily_outcomes

    out = daily_outcomes(
        pd.DataFrame(
            [{"beach_id": "b1", "sample_date": "2026-06-01", "exceeds_stv": True}]
        )
    )
    assert int(out.iloc[0]["exceeded"]) == 1
    assert bool(out.iloc[0]["outcome_is_pcr"]) is False


# --- the wiring, not just the helper ------------------------------------------
#
# The helper being correct is worth nothing if a publication site forgets to call
# it. These pin the contract at the boundaries that actually write
# system_health.json.


def test_the_training_feature_matrix_carries_is_pcr_as_a_number():
    """`select_dtypes(include=["number"])` -- how every model here takes its
    feature matrix -- EXCLUDES bool. A bool `is_pcr` would be carried all the way
    to the fit and then silently dropped, and every measurement of "is_pcr as a
    feature" would secretly be measuring its absence."""
    from app.data.pipeline.features import _model_feature_columns, add_temporal_features

    frame = pd.DataFrame(
        {
            "beach_id": ["b1"] * 6,
            "county": ["San Diego"] * 6,
            "region": ["San Diego"] * 6,
            "sample_date": pd.to_datetime(
                ["2026-01-01", "2026-01-08", "2026-01-15", "2026-01-22", "2026-02-01", "2026-02-08"]
            ),
            "sample_time": pd.to_datetime(
                ["2026-01-01", "2026-01-08", "2026-01-15", "2026-01-22", "2026-02-01", "2026-02-08"]
            ),
            "enterococcus_value": [10.0, 20.0, 2000.0, 30.0, 40.0, 50.0],
            "exceeds_stv": [0, 0, 1, 0, 0, 0],
            "is_pcr": [0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
            "label_method": ["Enterolert"] * 2 + ["ddPCR"] + ["Enterolert"] * 3,
            "label_units": ["MPN/100ml"] * 2 + ["Copies/100ml"] + ["MPN/100ml"] * 3,
            "assay_disagreement": [False] * 6,
            "latitude": [32.6] * 6,
            "longitude": [-117.1] * 6,
        }
    )
    enriched = add_temporal_features(frame)
    columns = _model_feature_columns(enriched)
    numeric = enriched[columns].select_dtypes(include=["number"])

    assert "is_pcr" in numeric.columns, (
        "is_pcr must survive select_dtypes -- it is dropped if it is a bool"
    )


@pytest.mark.parametrize("column", ["label_method", "label_units", "assay_disagreement"])
def test_the_non_feature_assay_columns_stay_out_of_the_model(column):
    """`assay_disagreement` in particular is TARGET LEAKAGE: it is computed from
    the same-day exceedance of both assays, and one of those is the label."""
    from app.data.pipeline.features import _model_feature_columns

    enriched = pd.DataFrame(
        {
            "beach_id": ["b1"],
            "county": ["San Diego"],
            "region": ["San Diego"],
            "sample_date": pd.to_datetime(["2026-01-01"]),
            "sample_time": pd.to_datetime(["2026-01-01"]),
            "exceeds_stv": [0],
            "is_pcr": [1.0],
            "label_method": ["ddPCR"],
            "label_units": ["Copies/100ml"],
            "assay_disagreement": [True],
        }
    )
    assert column not in _model_feature_columns(enriched)


def test_spatial_holdout_metrics_publish_their_stratified_pair():
    """The spatial county/beach AUCPR is the headline generalisation number and
    the one leave-one-county-out on San Diego makes meaningless. It must never
    ship pooled-only."""
    from app.ml import training

    n = 240
    rng = np.random.default_rng(5)
    metadata = pd.DataFrame(
        {
            "beach_id": [f"b{i % 8}" for i in range(n)],
            "county": ["San Diego" if i % 8 < 3 else "Orange" for i in range(n)],
            "sample_date": pd.to_datetime("2026-01-01") + pd.to_timedelta(np.arange(n) % 60, "D"),
            "is_pcr": [1.0 if i % 8 < 3 else 0.0 for i in range(n)],
        }
    )
    labels = (rng.random(n) < np.where(metadata["is_pcr"] > 0.5, 0.6, 0.1)).astype(int)
    features = pd.DataFrame({"x": rng.random(n), "y": rng.random(n)})

    metrics = training._spatial_holdout_metrics(
        features,
        labels,
        metadata,
        model_name="persistence",
        group_column="county",
        stv_threshold=104.0,
        min_rows=8,
    )

    assert "aucpr" in metrics, "the pooled figure is still published"
    assert set(metrics["by_assay"]) == {CULTURE_KEY, PCR_KEY, "composition"}
    assert metrics["by_assay"]["composition"]["pcr_row_fraction"] == pytest.approx(3 / 8)


def test_spatial_holdout_without_an_assay_column_says_so_explicitly():
    from app.ml import training

    n = 120
    metadata = pd.DataFrame(
        {
            "beach_id": [f"b{i % 4}" for i in range(n)],
            "county": ["Orange" if i % 2 else "Ventura" for i in range(n)],
            "sample_date": pd.to_datetime("2026-01-01") + pd.to_timedelta(np.arange(n) % 40, "D"),
        }
    )
    labels = (np.arange(n) % 5 == 0).astype(int)
    features = pd.DataFrame({"x": np.linspace(0, 1, n)})

    metrics = training._spatial_holdout_metrics(
        features, labels, metadata,
        model_name="persistence", group_column="county",
        stv_threshold=104.0, min_rows=8,
    )
    assert metrics["by_assay"] == {"unavailable": "no_assay_indicator"}


def test_serve_time_candidate_rows_carry_the_beach_assay():
    """The bug class CLAUDE.md already records for `exceeds_stv_last_obs`.

    `_export_forecasts` reindexes serve-time features onto the TRAINING columns
    with `fill_value=0.0`. If `is_pcr` failed to reach the candidate frame it
    would silently arrive as 0 for every beach -- i.e. the model would score
    every San Diego ddPCR beach as if its history were culture MPN, with no
    error anywhere. The assay is a monitoring-PROGRAMME property, so cloning it
    from the beach's most recent sample is both correct and forecast-safe.
    """
    from datetime import date as _date

    from app.ml.training import _build_forecast_candidates

    dates = pd.date_range("2026-05-01", periods=8, freq="7D")
    frame = pd.DataFrame(
        {
            "beach_id": ["pcr-beach"] * 8 + ["culture-beach"] * 8,
            "county": ["San Diego"] * 8 + ["Orange"] * 8,
            "region": ["San Diego"] * 8 + ["Santa Ana"] * 8,
            "sample_date": list(dates) * 2,
            "sample_time": list(dates) * 2,
            "enterococcus_value": [2000.0] * 8 + [15.0] * 8,
            "exceeds_stv": [1] * 8 + [0] * 8,
            "is_pcr": [1.0] * 8 + [0.0] * 8,
            "label_method": ["ddPCR"] * 8 + ["Enterolert"] * 8,
            "label_units": ["Copies/100ml"] * 8 + ["MPN/100ml"] * 8,
            "latitude": [32.6] * 8 + [33.6] * 8,
            "longitude": [-117.1] * 8 + [-117.9] * 8,
        }
    )
    stations = pd.DataFrame(
        {
            "beach_id": ["pcr-beach", "culture-beach"],
            "zip_code": ["92118", "92651"],
            "county": ["San Diego", "Orange"],
        }
    )

    _history, candidates = _build_forecast_candidates(
        frame, stations, pd.DataFrame(), _date(2026, 6, 20), full_frame=frame
    )

    assert not candidates.empty
    by_beach = candidates.set_index("beach_id")["is_pcr"]
    assert float(by_beach.loc["pcr-beach"]) == 1.0, (
        "a ddPCR beach must forecast as a ddPCR beach"
    )
    assert float(by_beach.loc["culture-beach"]) == 0.0
