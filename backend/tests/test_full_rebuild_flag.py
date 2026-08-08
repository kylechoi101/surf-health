"""``--full-rebuild`` must be opt-in, and the daily job must never take it.

Background (Step 4 of the rebuild programme). Whenever ``observations.parquet``
and ``beaches.parquet` both exist and no ``--start-date`` is given, the pipeline
re-normalizes only rows newer than ``max(sample_time) - 7 days``. The daily
workflow passes neither flag, so it takes that branch — which is correct for a
daily refresh (the state export is 1.7 GB / 2.4M rows and a full pass does not
fit the workflow's budget) and catastrophic for a change to the *label
definition*: it relabels one week and leaves three years on the previous
definition, silently, passing every gate.

``--full-rebuild`` is the escape hatch. These tests pin both halves of the
contract: the flag forces a full pass, and the daily invocation as it is
actually written in the workflow YAML still does not.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pandas as pd
import pytest

from app.data.pipeline.beachwatch import normalize_bacteria_results
from app.data.pipeline.cli import (
    build_arg_parser,
    normalize_beachwatch_bundle,
    normalize_beachwatch_results_full,
    preserve_prior_additive_observations,
    use_incremental_beachwatch_normalization,
)

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "daily-forecast.yml"

BASE_ARGV = [
    "--normalize-beachwatch",
    "--stations-csv",
    "/tmp/bw_stations.csv",
    "--results-csv",
    "/tmp/bw_results.csv",
    "--advisories-csv",
    "/tmp/bw_advisories.csv",
]


def _daily_workflow_pipeline_argv() -> list[str]:
    """The real argv the daily workflow hands to ``app.data.pipeline.cli``.

    Parsed out of the YAML rather than restated here, so the test cannot drift
    away from the thing it is protecting.
    """
    text = WORKFLOW.read_text()
    start = text.find("python -m app.data.pipeline.cli")
    assert start != -1, "daily workflow no longer invokes app.data.pipeline.cli"
    lines = text[start:].split("\n")
    command = [lines[0]]
    for line in lines[1:]:
        if not command[-1].rstrip().endswith("\\"):
            break
        command.append(line)
    body = "\n".join(command).replace("\\\n", " ")
    # drop the `python -m app.data.pipeline.cli` prefix
    return shlex.split(body)[3:]


def test_daily_workflow_invocation_takes_the_incremental_branch():
    argv = _daily_workflow_pipeline_argv()
    assert "--normalize-beachwatch" in argv

    args = build_arg_parser().parse_args(argv)

    assert args.full_rebuild is False, "the daily job must not pass --full-rebuild"
    assert args.start_date is None, "the daily job must not pass --start-date"
    assert use_incremental_beachwatch_normalization(args, True, True) is True


def test_daily_workflow_yaml_does_not_mention_full_rebuild():
    assert "--full-rebuild" not in WORKFLOW.read_text()


def test_full_rebuild_flag_forces_the_full_branch():
    args = build_arg_parser().parse_args([*BASE_ARGV, "--full-rebuild"])
    assert args.full_rebuild is True
    assert use_incremental_beachwatch_normalization(args, True, True) is False


def test_start_date_still_forces_the_full_branch():
    args = build_arg_parser().parse_args([*BASE_ARGV, "--start-date", "2020-01-01"])
    assert use_incremental_beachwatch_normalization(args, True, True) is False


@pytest.mark.parametrize(
    ("observations_exists", "stations_exists"),
    [(False, True), (True, False), (False, False)],
)
def test_missing_artifacts_force_the_full_branch(observations_exists, stations_exists):
    """First-ever run: nothing to be incremental against."""
    args = build_arg_parser().parse_args(BASE_ARGV)
    assert use_incremental_beachwatch_normalization(args, observations_exists, stations_exists) is False


# --------------------------------------------------------------------------
# The chunked full normalizer must be indistinguishable from the whole-frame one
# --------------------------------------------------------------------------

_RAW_ROWS = [
    {
        "SampleDate": "07/01/2024",
        "StartTime": "10:15:00",
        "Parameter": "Enterococcus",
        "Result": "180",
        "Unit": "MPN/100ml",
        "AnalysisMethod": "Enterolert",
        "CountyName": "San Diego",
        "USEPAID": "CA111111",
        "Beach_Name": "Test Beach",
        "Station_Name": "TB-010",
        "WaterBodyType": "Open Coast",
        "WaterBodyClass": "Saltwater",
    },
    {
        "SampleDate": "07/02/2024",
        "StartTime": "09:00:00",
        "Parameter": "Enterococcus",
        "Result": "2500",
        "Unit": "Copies/100ml",
        "AnalysisMethod": "ddPCR",
        "CountyName": "San Diego",
        "USEPAID": "CA111111",
        "Beach_Name": "Test Beach",
        "Station_Name": "TB-010",
        "WaterBodyType": "Open Coast",
        "WaterBodyClass": "Saltwater",
    },
    {
        "SampleDate": "07/03/2024",
        "StartTime": "08:30:00",
        "Parameter": "Total Coliform",
        "Result": "40",
        "Unit": "MPN/100ml",
        "AnalysisMethod": "Enterolert",
        "CountyName": "San Diego",
        "USEPAID": "CA111111",
        "Beach_Name": "Test Beach",
        "Station_Name": "TB-010",
        "WaterBodyType": "Open Coast",
        "WaterBodyClass": "Saltwater",
    },
    {
        "SampleDate": "07/04/2024",
        "StartTime": "11:00:00",
        "Parameter": "Enterococcus",
        "Result": "55",
        "Unit": "MPN/100ml",
        "AnalysisMethod": "Enterolert",
        "CountyName": "Sacramento",
        "USEPAID": "CA222222",
        "Beach_Name": "Freshwater Pond",
        "Station_Name": "FP-001",
        "WaterBodyType": "Lake",
        "WaterBodyClass": "Freshwater",
    },
    {
        "SampleDate": "07/05/2024",
        "StartTime": "12:00:00",
        "Parameter": "Enterococcus",
        "Result": "-1000",
        "Unit": "MPN/100ml",
        "AnalysisMethod": "Enterolert",
        "CountyName": "Orange",
        "USEPAID": "CA333333",
        "Beach_Name": "Other Beach",
        "Station_Name": "OB-020",
        "WaterBodyType": "Open Coast",
        "WaterBodyClass": "Saltwater",
    },
    {
        "SampleDate": "07/06/2024",
        "StartTime": "13:00:00",
        "Parameter": "Enterococcus",
        "Result": "12",
        "Unit": "MPN/100ml",
        "AnalysisMethod": "Enterolert",
        "CountyName": "Orange",
        "USEPAID": "CA333333",
        "Beach_Name": "Other Beach",
        "Station_Name": "OB-020",
        "WaterBodyType": "Open Coast",
        "WaterBodyClass": "Saltwater",
    },
]


@pytest.fixture()
def results_csv(tmp_path: Path) -> Path:
    path = tmp_path / "bw_results.csv"
    pd.DataFrame(_RAW_ROWS).to_csv(path, index=False)
    return path


@pytest.mark.parametrize("chunksize", [1, 2, 5, 10_000])
def test_chunked_full_normalization_matches_whole_frame(results_csv: Path, chunksize: int):
    """Chunk boundaries must not change a single row.

    ``normalize_bacteria_results`` is row-wise, so this holds -- but it is the
    assumption the whole flag rests on, and a future cross-row step added to the
    normalizer would break it silently.
    """
    whole = normalize_bacteria_results(
        pd.read_csv(results_csv, dtype=str), 104.0
    ).sort_values(["beach_id", "sample_time"]).reset_index(drop=True)

    chunked = normalize_beachwatch_results_full(results_csv, 104.0, chunksize=chunksize)

    pd.testing.assert_frame_equal(chunked, whole)


def test_full_normalization_applies_the_pcr_threshold_and_the_negative_guard(results_csv: Path):
    frame = normalize_beachwatch_results_full(results_csv, 104.0, chunksize=2)

    # freshwater station dropped, non-enterococcus parameter dropped,
    # -1000 sentinel dropped by the dropna on `value`
    assert len(frame) == 3

    ddpcr = frame.loc[frame["method"] == "ddPCR"].iloc[0]
    assert ddpcr["value"] == 2500.0
    # 2500 copies exceeds the 1413 BAV. What matters is that the chunked path
    # routes through compute_exceeds_stv, not a bare `> 104`.
    assert bool(ddpcr["exceeds_stv"]) is True

    culture = frame.loc[frame["value"] == 180.0].iloc[0]
    assert bool(culture["exceeds_stv"]) is True


def test_bundle_uses_supplied_observations_without_reading_the_results_csv(tmp_path: Path):
    """``observations_normalized`` short-circuits the 1.7 GB whole-frame read.

    Passing a results path that does not exist proves the CSV is never opened.
    """
    stations_csv = tmp_path / "stations.csv"
    pd.DataFrame(
        [
            {
                "USEPAID": "CA111111",
                "CountyName": "San Diego",
                "Beach_Name": "Test Beach",
                "Station_Name": "TB-010",
                "Station_Description": "Test Beach at the pier",
                "Station_UpperLat": "32.6",
                "Station_UpperLon": "-117.1",
                "WaterBodyType": "Open Coast",
                "WaterBodyClass": "Saltwater",
                "Status": "Active",
            }
        ]
    ).to_csv(stations_csv, index=False)

    advisories_csv = tmp_path / "advisories.csv"
    pd.DataFrame(
        [
            {
                "USEPAID": "CA111111",
                "CountyName": "San Diego",
                "Beach_Name": "Test Beach",
                "Station_Name": "TB-010",
                "DateofAdvisory": "07/01/2024",
                "TimeofAdvisory": "10:00:00",
                "DateOpened": "07/03/2024",
                "TimeOpened": "10:00:00",
                "WaterBodyType": "Open Coast",
                "WaterBodyClass": "Saltwater",
            }
        ]
    ).to_csv(advisories_csv, index=False)

    observations = normalize_bacteria_results(pd.DataFrame(_RAW_ROWS[:2]), 104.0)
    assert not observations.empty

    bundle = normalize_beachwatch_bundle(
        stations_path=stations_csv,
        results_path=tmp_path / "does-not-exist.csv",
        advisories_path=advisories_csv,
        observations_normalized=observations,
    )

    assert len(bundle["observations"]) == len(observations)
    assert set(bundle["beach_day"]["label_method"]) == {"Enterolert", "ddPCR"}


# --------------------------------------------------------------------------
# A full rebuild must not destroy the additive sources' accumulated history
# --------------------------------------------------------------------------
#
# The data.ca.gov results export is frozen at sample date 2026-03-05. Everything
# newer reaches observations.parquet only through --with-beachwatch-live (a
# 30-day *entered* window), the CEDEN slice, and the county-direct scrape, all
# of which the daily job accumulates one run at a time. A rebuild that re-derives
# only what one run can fetch drops five months of the newest data.


def _obs_row(beach_id, when, value, source, method="Enterolert", units="MPN/100ml"):
    ts = pd.Timestamp(when)
    return {
        "beach_id": beach_id,
        "sample_time": ts,
        "sample_date": ts.date(),
        "analyte": "enterococcus",
        "method": method,
        "units": units,
        "value": value,
        "exceeds_stv": False,
        "data_source": source,
    }


def test_full_rebuild_preserves_additive_rows_the_state_export_never_had():
    rebuilt = pd.DataFrame([_obs_row("b1", "2026-01-05 10:00", 50.0, "BeachWatch")])
    prior = pd.DataFrame(
        [
            _obs_row("b1", "2026-06-01 10:00", 500.0, "BeachWatch.Live"),
            _obs_row("b1", "2026-07-01 10:00", 20.0, "BeachWatch.SafeToSwim"),
            _obs_row("b1", "2026-07-15 10:00", 30.0, "CountyDirect"),
        ]
    )

    out = preserve_prior_additive_observations(rebuilt, prior, 104.0)

    assert len(out) == 4
    assert set(out["data_source"]) == {
        "BeachWatch",
        "BeachWatch.Live",
        "BeachWatch.SafeToSwim",
        "CountyDirect",
    }


def test_full_rebuild_does_not_resurrect_prior_beachwatch_rows():
    """Only the additive sources are preserved.

    A BeachWatch row that the current export no longer carries must stay gone —
    otherwise the rebuild can never remove anything and the flag is useless.
    """
    rebuilt = pd.DataFrame([_obs_row("b1", "2026-01-05 10:00", 50.0, "BeachWatch")])
    prior = pd.DataFrame(
        [
            _obs_row("b1", "2020-01-01 10:00", -99.0, "BeachWatch"),
            _obs_row("b1", "2019-01-01 10:00", 12.0, "BeachWatch"),
        ]
    )

    out = preserve_prior_additive_observations(rebuilt, prior, 104.0)

    assert len(out) == 1
    assert out.iloc[0]["sample_time"] == pd.Timestamp("2026-01-05 10:00")


def test_preserved_rows_are_relabelled_under_todays_exceedance_rule():
    """Preservation must not smuggle a stale label definition past the rebuild.

    A ddPCR reading of 800 copies is BELOW the 1413 BAV. If it arrives carrying a
    stale ``exceeds_stv=True`` (judged against the 104 culture STV), the rebuild
    has to correct it — that correction is the entire reason the flag exists.
    """
    rebuilt = pd.DataFrame([_obs_row("b1", "2026-01-05 10:00", 50.0, "BeachWatch")])
    stale = _obs_row("b1", "2026-06-01 10:00", 800.0, "BeachWatch.Live", "ddPCR", "Copies/100ml")
    stale["exceeds_stv"] = True  # what a pre-1413 vintage recorded
    prior = pd.DataFrame([stale])

    out = preserve_prior_additive_observations(rebuilt, prior, 104.0)

    preserved = out.loc[out["data_source"] == "BeachWatch.Live"].iloc[0]
    assert preserved["value"] == 800.0
    assert bool(preserved["exceeds_stv"]) is False


def test_rebuilt_state_row_wins_over_a_preserved_mirror_of_the_same_sample():
    """Same physical sample, two source spellings ("1600" vs "EPA 1600")."""
    rebuilt = pd.DataFrame(
        [_obs_row("b1", "2026-01-05 10:00", 50.0, "BeachWatch", method="1600")]
    )
    prior = pd.DataFrame(
        [_obs_row("b1", "2026-01-05 10:00", 50.0, "BeachWatch.Live", method="EPA 1600")]
    )

    out = preserve_prior_additive_observations(rebuilt, prior, 104.0)

    assert len(out) == 1
    assert out.iloc[0]["data_source"] == "BeachWatch"


def test_preservation_is_a_noop_without_prior_observations():
    rebuilt = pd.DataFrame([_obs_row("b1", "2026-01-05 10:00", 50.0, "BeachWatch")])
    assert len(preserve_prior_additive_observations(rebuilt, pd.DataFrame(), 104.0)) == 1
    only_state = pd.DataFrame([_obs_row("b1", "2019-01-01 10:00", 12.0, "BeachWatch")])
    assert len(preserve_prior_additive_observations(rebuilt, only_state, 104.0)) == 1
