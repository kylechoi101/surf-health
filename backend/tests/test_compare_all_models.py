import numpy as np
import pandas as pd
import pytest

from sklearn.metrics import roc_auc_score

from app.data.pipeline.features import build_inference_features
from app.ml.logit_challenger import ChallengerInputs, build_features
from app.ml.training import _build_forecast_candidates
from scripts.compare_all_models import (
    LOGIT_METHOD_FEATURE_COLUMNS,
    cluster_bootstrap_delta,
    compute_assays,
    derive_label_method_from_observations,
    fit_coefficients_custom,
    metrics,
    predict_custom,
    within_beach_auroc,
)


def _synthetic_beach_day() -> pd.DataFrame:
    """Synthetic beach_day frame for strictly-prior behavior testing."""
    return pd.DataFrame(
        {
            "beach_id": ["a", "a", "b", "b", "c"],
            "sample_date": pd.to_datetime(
                ["2026-01-01", "2026-01-10", "2026-01-05", "2026-01-10", "2026-01-02"]
            ),
            "exceeds_stv": [False, True, False, False, False],
            "enterococcus_action_ratio": [0.1, 5.0, 0.2, 0.1, 0.1],
            "latitude": [33.0, 33.0, 34.0, 34.0, 35.0],
            "longitude": [-118.0, -118.0, -119.0, -119.0, -120.0],
            "label_method": ["culture", "ddpcr", "culture", "culture", "culture"],
        }
    )


def test_pooled_strictly_prior_behaviour():
    """A sample on D must NOT enter the pooled statewide rate for D."""
    # Beach a has an exceedance ON 2026-01-10.
    # Prior to 2026-01-10:
    # 2026-01-01 (a): False
    # 2026-01-02 (c): False
    # 2026-01-05 (b): False
    # Rate before 2026-01-10: 0/3 = 0.0.
    # Including 2026-01-10: 1/5 = 0.20.
    bd = _synthetic_beach_day()
    inputs = ChallengerInputs(
        bd,
        pd.DataFrame(
            {
                "station_id": ["s"],
                "latitude": [33.0],
                "longitude": [-118.0],
                "sample_date": [pd.Timestamp("2026-01-10")],
                "precip_mm_72h": [0.0],
            }
        ),
        {"a": "s", "b": "s", "c": "s"},
    )
    feats = build_features(inputs, ["a", "b"], ["2026-01-10", "2026-01-10"])

    # Pooled rate g for 2026-01-10 must strictly evaluate rows before 2026-01-10.
    assert (feats["g"] == 0.0).all(), f"g was {feats['g']}, expected 0.0 (no exceedances before 01-10)"

    # If queried for 2026-01-11, the 01-10 exceedance is now strictly prior.
    feats_next = build_features(inputs, ["a", "b"], ["2026-01-11", "2026-01-11"])
    # 5 samples total in the 365d window, 1 exceedance -> 1/5 = 0.20.
    assert feats_next["g"].iloc[0] == pytest.approx(0.20)


def test_persistence_strictly_prior_behaviour():
    """A sample ON D must NOT enter persistence for D; sample before D does."""
    bd = _synthetic_beach_day()
    inputs = ChallengerInputs(
        bd,
        pd.DataFrame(
            {
                "station_id": ["s"],
                "latitude": [33.0],
                "longitude": [-118.0],
                "sample_date": [pd.Timestamp("2026-01-10")],
                "precip_mm_72h": [0.0],
            }
        ),
        {"a": "s", "b": "s", "c": "s"},
    )

    # On 2026-01-10, beach a has a sample ON this day that exceeded.
    # But strictly prior to 01-10, beach a's last sample was 01-01 (False).
    f_on_d = build_features(inputs, ["a"], ["2026-01-10"]).iloc[0]
    assert f_on_d["last_exceeds"] == 0.0
    p_persistence_raw = 1.0 if f_on_d["last_exceeds"] == 1 else f_on_d["g"]
    assert p_persistence_raw == pytest.approx(0.0)  # g is 0.0

    # On 2026-01-11, beach a's last sample strictly prior is 01-10 (True).
    f_after_d = build_features(inputs, ["a"], ["2026-01-11"]).iloc[0]
    assert f_after_d["last_exceeds"] == 1.0
    p_persistence_raw_after = 1.0 if f_after_d["last_exceeds"] == 1 else f_after_d["g"]
    assert p_persistence_raw_after == 1.0


def test_cluster_bootstrap_delta_identical_predictions():
    """Known answer: identical predictions yield delta CI [0, 0] across all metrics."""
    rng = np.random.default_rng(123)
    n = 200
    beach = rng.choice(["b1", "b2", "b3", "b4", "b5"], size=n)
    y = rng.binomial(1, 0.25, size=n)
    p = rng.uniform(0.01, 0.99, size=n)

    delta = cluster_bootstrap_delta(y, p, p, beach, reps=50, seed=42)

    assert set(delta.keys()) == {"within_beach_auroc", "auroc", "aucpr", "brier"}
    for k, ci in delta.items():
        assert ci == [0.0, 0.0], f"{k} CI was {ci}, expected [0.0, 0.0]"


def test_cluster_bootstrap_delta_keys_and_ordering():
    """Verify cluster_bootstrap_delta returns 95% CIs [lo, hi] with lo <= hi."""
    rng = np.random.default_rng(42)
    n = 300
    beach = rng.choice(["b1", "b2", "b3", "b4"], size=n)
    y = rng.binomial(1, 0.3, size=n)
    p_better = np.clip(y * 0.7 + rng.normal(0, 0.1, size=n), 0.01, 0.99)
    p_worse = np.clip(0.3 + rng.normal(0, 0.2, size=n), 0.01, 0.99)

    delta = cluster_bootstrap_delta(y, p_better, p_worse, beach, reps=100, seed=0)

    for k in ("within_beach_auroc", "auroc", "aucpr", "brier"):
        assert k in delta
        lo, hi = delta[k]
        assert lo <= hi
    # A clearly better model should have positive auroc delta CI
    assert delta["auroc"][0] > 0.0
    # and negative Brier delta CI (lower Brier is better)
    assert delta["brier"][1] < 0.0


def test_within_beach_auroc_metric():
    """Verify within-beach AUROC evaluates correctly and ignores single-class beaches."""
    # Beach 1: perfect ranking (AUC = 1.0), n1=1, n0=2 -> pairs = 2
    # Beach 2: reversed ranking (AUC = 0.0), n1=1, n0=1 -> pairs = 1
    # Beach 3: only negatives (single class -> ignored)
    y = np.array([0, 0, 1, 0, 1, 0, 0])
    p = np.array([0.1, 0.2, 0.9, 0.8, 0.3, 0.1, 0.2])
    beach = np.array(["b1", "b1", "b1", "b2", "b2", "b3", "b3"])

    # Expected: (2 * 1.0 + 1 * 0.0) / (2 + 1) = 2/3
    wb = within_beach_auroc(y, p, beach)
    assert wb == pytest.approx(2.0 / 3.0)

    m = metrics(y, p, beach)
    assert "within_beach_auroc" in m
    assert m["within_beach_auroc"] == pytest.approx(2.0 / 3.0)


def test_logit_method_fit_and_predict():
    """Verify fit_coefficients_custom and predict_custom with ddpcr and R_ddpcr terms."""
    rng = np.random.default_rng(0)
    n = 50_000
    L = rng.normal(-1.5, 0.8, n)
    R = rng.normal(-0.8, 0.6, n)
    RF = rng.normal(-0.2, 0.3, n)
    W = rng.exponential(0.3, n)
    S = rng.uniform(-1, 1, n)
    ddpcr = rng.binomial(1, 0.4, n).astype(float)
    R_ddpcr = R * ddpcr

    feats = pd.DataFrame({"L": L, "R": R, "RF": RF, "W": W, "S": S, "ddpcr": ddpcr, "R_ddpcr": R_ddpcr})
    truth = {
        "intercept": -0.1,
        "R": 0.4,
        "RF": 0.6,
        "W": 0.7,
        "S": 0.2,
        "ddpcr": 0.3,
        "R_ddpcr": 0.5,
    }
    p_true = predict_custom(feats, truth, LOGIT_METHOD_FEATURE_COLUMNS)
    y = (rng.random(n) < p_true).astype(int)

    fitted = fit_coefficients_custom(feats, y, LOGIT_METHOD_FEATURE_COLUMNS)
    for k, v in truth.items():
        assert fitted[k] == pytest.approx(v, abs=0.08)


def test_derive_label_method_from_observations(tmp_path):
    """Verify derive_label_method_from_observations picks worst sample and classifies assay."""
    bd = pd.DataFrame(
        {
            "beach_id": ["b1", "b2"],
            "sample_date": [pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-06")],
            "exceeds_stv": [True, False],
        }
    )
    # Observations: on b1, two samples: clean culture, exceeding ddPCR.
    # Worst sample rule picks the exceeding ddPCR.
    obs = pd.DataFrame(
        {
            "beach_id": ["b1", "b1", "b2"],
            "sample_date": [pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-06")],
            "sample_time": ["08:00", "09:00", "08:30"],
            "value": [10.0, 2000.0, 10.0],
            "exceeds_stv": [False, True, False],
            "method": ["Enterolert", "ddPCR", "Enterolert"],
            "units": ["MPN/100ml", "copies/100ml", "MPN/100ml"],
        }
    )
    obs.to_parquet(tmp_path / "observations.parquet", index=False)

    derived = derive_label_method_from_observations(tmp_path, bd)
    assert "label_method" in derived.columns
    assert derived.loc[derived["beach_id"] == "b1", "label_method"].iloc[0] == "ddpcr"
    assert derived.loc[derived["beach_id"] == "b2", "label_method"].iloc[0] == "culture"


def test_compute_assays_strictly_prior():
    """Verify compute_assays picks the most recent label_method strictly before D."""
    bd = pd.DataFrame(
        {
            "beach_id": ["b1", "b1", "b2"],
            "sample_date": pd.to_datetime(["2026-01-01", "2026-01-10", "2026-01-05"]),
            "label_method": ["culture", "ddpcr", "ddpcr"],
        }
    )
    # Query on 2026-01-10 for b1: strictly before 01-10 is culture.
    # Query on 2026-01-11 for b1: strictly before 01-11 is ddpcr.
    # Query for b3 (no samples): default culture.
    assays = compute_assays(
        bd,
        ["b1", "b1", "b2", "b3"],
        ["2026-01-10", "2026-01-11", "2026-01-06", "2026-01-10"],
    )
    assert assays.tolist() == ["culture", "ddpcr", "ddpcr", "culture"]


def test_xgb_served_regime_leak_check():
    """Verify nothing dated >= D enters features for D (leak check).

    A tiny frame with 3 clean samples before D and 1 massive exceeding sample ON D.
    Candidate features for D must strictly reflect only samples before D.
    """
    stations = pd.DataFrame({"beach_id": ["b1"], "latitude": [33.0], "longitude": [-118.0]})
    # 3 samples before D (Aug 1, 3, 5), and 1 sample ON D (Aug 10) that exceeded.
    df = pd.DataFrame(
        {
            "beach_id": ["b1", "b1", "b1", "b1"],
            "sample_date": pd.to_datetime(["2026-08-01", "2026-08-03", "2026-08-05", "2026-08-10"]),
            "sample_time": pd.to_datetime(
                ["2026-08-01 08:00:00", "2026-08-03 08:00:00", "2026-08-05 08:00:00", "2026-08-10 08:00:00"]
            ),
            "exceeds_stv": [False, False, False, True],
            "enterococcus_value": [10.0, 10.0, 10.0, 500.0],
            "enterococcus_action_ratio": [0.1, 0.1, 0.1, 5.0],
            "latitude": [33.0, 33.0, 33.0, 33.0],
            "longitude": [-118.0, -118.0, -118.0, -118.0],
        }
    )
    D = pd.Timestamp("2026-08-10").date()

    # Evaluation with frame_before_D (sample_date < D)
    frame_before_D = df.loc[df["sample_date"].dt.date < D].copy()
    hist, cands = _build_forecast_candidates(
        frame_before_D, stations, pd.DataFrame(), D, full_frame=frame_before_D
    )
    assert len(cands) == 1
    assert cands["sample_age_days"].iloc[0] == 5  # 2026-08-10 - 2026-08-05, NOT 0
    assert cands["latest_sample_date"].iloc[0] == "2026-08-05"  # NOT "2026-08-10"

    inf = build_inference_features(pd.concat([hist, cands], ignore_index=True))
    assert inf.feature_frame["days_since_enterococcus_value_obs"].iloc[0] == 5.0
    assert inf.feature_frame["enterococcus_action_ratio_last_obs"].iloc[0] == pytest.approx(0.1)
    assert inf.feature_frame["exceeds_stv_last_obs"].iloc[0] == pytest.approx(0.0)

    # Even if full df with the sample ON D is passed to _build_forecast_candidates,
    # it must still filter out rows >= D.
    hist_raw, cands_raw = _build_forecast_candidates(
        df, stations, pd.DataFrame(), D, full_frame=df
    )
    assert cands_raw["sample_age_days"].iloc[0] == 5
    assert cands_raw["latest_sample_date"].iloc[0] == "2026-08-05"
    inf_raw = build_inference_features(pd.concat([hist_raw, cands_raw], ignore_index=True))
    assert inf_raw.feature_frame["days_since_enterococcus_value_obs"].iloc[0] == 5.0
    assert inf_raw.feature_frame["enterococcus_action_ratio_last_obs"].iloc[0] == pytest.approx(0.1)
    assert inf_raw.feature_frame["exceeds_stv_last_obs"].iloc[0] == pytest.approx(0.0)


def test_served_log_check_calculation():
    """Verify served-log check computes AUROC and Pearson correlation correctly."""
    y = np.array([0, 0, 1, 1, 0, 1])
    p_xgb = np.array([0.1, 0.2, 0.8, 0.7, 0.3, 0.9])
    p_ml = np.array([0.15, 0.25, 0.75, 0.65, 0.35, 0.85])

    auroc_xgb = roc_auc_score(y, p_xgb)
    auroc_ml = roc_auc_score(y, p_ml)
    corr = np.corrcoef(p_xgb, p_ml)[0, 1]

    assert auroc_xgb == pytest.approx(1.0)
    assert auroc_ml == pytest.approx(1.0)
    assert corr > 0.99



# ---------------------------------------------------------------------------------------
# diff_comparisons.py
# ---------------------------------------------------------------------------------------
from app.ml.evaluation import sensitivity_at_specificity as _official_sens  # noqa: E402
from scripts import diff_comparisons as dc  # noqa: E402


def _run_pairs(beaches, dates, seed=0, arms=("pooled", "logit", "lookup")) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for b in beaches:
        for d in dates:
            y = int(rng.random() < 0.3)
            row = {
                "beach_id": b,
                "county": "San Diego" if b.startswith("sd") else "Marin",
                "date": pd.Timestamp(d),
                "outcome": "forward_1_3d",
                "y": y,
                "last_exceeds": False,
                "assay": "ddpcr" if b.startswith("sd") else "culture",
            }
            for a in arms:
                row[f"p_{a}"] = float(np.clip(0.2 + 0.4 * y * rng.random() + 0.2 * rng.random(), 0, 1))
            rows.append(row)
    return pd.DataFrame(rows)


def _dates(n=12):
    return pd.date_range("2026-08-01", periods=n).strftime("%Y-%m-%d").tolist()


def test_split_pairs_common_and_new_beaches():
    before = _run_pairs(["a", "b", "sd1"], _dates(4))
    after = _run_pairs(["a", "b", "sd1", "new1"], _dates(6), seed=1)
    ways = dc.split_pairs(before, after)
    cb, ca = ways["common"]
    assert len(cb) == len(ca) == 3 * 4
    assert (cb[["beach_id", "date"]].to_numpy() == ca[["beach_id", "date"]].to_numpy()).all()
    assert len(ways["full"][0]) == 12 and len(ways["full"][1]) == 24
    nb_before, nb_after = ways["new_beaches"]
    assert nb_before.empty
    assert set(nb_after["beach_id"]) == {"new1"} and len(nb_after) == 6


def test_split_pairs_shared_beach_new_dates_is_not_a_new_beach():
    before = _run_pairs(["a"], _dates(3))
    after = _run_pairs(["a"], _dates(6))
    ways = dc.split_pairs(before, after)
    assert len(ways["common"][1]) == 3
    assert ways["new_beaches"][1].empty


def test_bootstrap_delta_identical_predictions_is_exactly_zero():
    df = _run_pairs(["a", "b", "c", "d"], _dates())
    y, p, b = df["y"].to_numpy(), df["p_logit"].to_numpy(), df["beach_id"].to_numpy()
    ci = dc.bootstrap_delta(y, p, p.copy(), b, reps=20)
    assert set(ci) == set(dc.METRICS)
    assert all(v == [0.0, 0.0] for v in ci.values())


def test_bootstrap_delta_detects_a_better_model():
    rng = np.random.default_rng(3)
    n = 40
    beach = np.repeat([f"b{i}" for i in range(n)], 20)
    y = (rng.random(len(beach)) < 0.3).astype(int)
    good = np.clip(0.1 + 0.6 * y + 0.1 * rng.random(len(y)), 0, 1)
    bad = rng.random(len(y))
    ci = dc.bootstrap_delta(y, good, bad, beach, reps=60)
    assert ci["within_beach_auroc"][0] > 0
    assert ci["brier"][1] < 0


def test_sensitivity_matches_official_helper():
    rng = np.random.default_rng(5)
    y = (rng.random(500) < 0.25).astype(int)
    p = np.clip(0.2 + 0.4 * y * rng.random(500) + 0.3 * rng.random(500), 0, 1)
    ours = dc.sensitivity_at_specificity(y, p)
    assert ours == pytest.approx(_official_sens(y, p, 0.87)["sensitivity"])


def _stub(table):
    def fn(arm, ref, slice_name):
        return table[(arm, ref, slice_name)]

    return fn


_GOOD = {"within_beach_auroc": [0.01, 0.05], "brier": [-0.02, -0.001]}
_BAD_WB = {"within_beach_auroc": [-0.01, 0.05], "brier": [-0.02, -0.001]}
_BAD_BRIER = {"within_beach_auroc": [0.01, 0.05], "brier": [-0.02, 0.003]}


def test_promotion_pass_requires_both_metrics_on_both_slices():
    arms = ["pooled", "lookup", "logit", "xgb_offset"]
    table = {}
    for a in ("pooled", "lookup"):
        for s in dc.VERDICT_SLICES:
            table[(a, "logit", s)] = _BAD_WB
    table[("xgb_offset", "logit", "all")] = _GOOD
    table[("xgb_offset", "logit", "not San Diego")] = _GOOD
    v = dc.promotion_verdict(arms, _stub(table))
    assert v["challengers"]["xgb_offset"]["verdict"] == "PASS"
    assert v["challengers"]["pooled"]["verdict"] == "FAIL"
    assert v["promoted"] == "xgb_offset"
    assert "logit" not in v["challengers"]


def test_promotion_fails_when_one_slice_fails():
    for bad in (_BAD_WB, _BAD_BRIER):
        table = {
            ("lookup", "logit", "all"): _GOOD,
            ("lookup", "logit", "not San Diego"): bad,
        }
        v = dc.promotion_verdict(["lookup", "logit"], _stub(table))
        assert v["challengers"]["lookup"]["verdict"] == "FAIL"
        assert v["challengers"]["lookup"]["slices"] == {"all": True, "not San Diego": False}
        assert v["promoted"] is None


def test_promotion_nan_ci_fails():
    nan = {"within_beach_auroc": [float("nan")] * 2, "brier": [float("nan")] * 2}
    table = {("lookup", "logit", s): nan for s in dc.VERDICT_SLICES}
    assert dc.promotion_verdict(["lookup", "logit"], _stub(table))["challengers"]["lookup"]["verdict"] == "FAIL"


def test_promotion_tie_goes_to_simpler_unless_complex_beats_it():
    arms = ["logit", "logit_method", "xgb_offset"]
    table = {}
    for a in ("logit_method", "xgb_offset"):
        for s in dc.VERDICT_SLICES:
            table[(a, "logit", s)] = _GOOD
    for s in dc.VERDICT_SLICES:
        table[("xgb_offset", "logit_method", s)] = _BAD_WB
    assert dc.promotion_verdict(arms, _stub(table))["promoted"] == "logit_method"
    for s in dc.VERDICT_SLICES:
        table[("xgb_offset", "logit_method", s)] = _GOOD
    assert dc.promotion_verdict(arms, _stub(table))["promoted"] == "xgb_offset"


def test_band_rates_use_the_served_cutpoints():
    df = pd.DataFrame({"y": [0, 1, 0, 1, 1], "p_x": [0.19, 0.20, 0.29, 0.30, 0.70]})
    got = {name: (n, r) for name, n, r in dc.band_rates(df, "x")}
    assert got["Low"] == (1, 0.0)
    assert got["Moderate"] == (2, 0.5)
    assert got["High"] == (1, 1.0)
    assert got["Very High"] == (1, 1.0)


def test_report_same_run_has_zero_deltas_and_verdicts(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    _run_pairs(["a", "b", "c", "sd1", "sd2"], _dates(), arms=("pooled", "logit", "lookup")).to_parquet(
        run / "predictions.parquet"
    )
    report, verdicts = dc.build_report(run, run, reps=10)
    assert "## PROMOTION.md verdict" in report
    assert "INDICATIVE ONLY" in report  # 10 < 300 replicates
    assert "Decision is the same on full and common pairs." in report
    for arm in ("pooled", "lookup"):
        assert verdicts["full"]["challengers"][arm]["verdict"] == "FAIL"
        assert f"| {arm} |" in report
    # exact zero Δ everywhere on common pairs
    common = report.split("## Common pairs")[1].split("## Full pairs")[0]
    assert "Δ +0.000 [+0.000, +0.000]" in common
    assert "Δ +0.001" not in common and "Δ -0.0" not in common
