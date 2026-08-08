"""Tests for the forecast anomaly gate in ``scripts/validate_forecast.py``.

The pre-existing checks only reject bitwise-identical probabilities plus
shape/freshness, so a dependency-induced calibration squash to all-Low
(distinct values, in-range, full row count) used to pass and silently
under-warn. These tests lock in the anomaly checks — all-safe collapse,
distribution shift vs ``--previous``, band sanity — plus the
``SKIP_FORECAST_ANOMALY_CHECKS`` escape hatch bypassing ONLY those checks.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.ml import calibration
from scripts import validate_forecast as vf


_TODAY_PT = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def _write_forecast(directory: Path, probs, bands=None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "beach_id": [f"beach_{i}" for i in range(len(probs))],
            "forecast_date": [_TODAY_PT] * len(probs),
            "p_exceed": np.asarray(probs, dtype=float),
        }
    )
    if bands is not None:
        frame["risk_band"] = list(bands)
    path = directory / "forecasts.parquet"
    frame.to_parquet(path)
    return path


def _healthy_probs(n: int = 60, n_high: int = 10) -> np.ndarray:
    # Distinct, in-range, fresh-dated — passes every pre-existing check;
    # ~17% of rows above the Low threshold mirrors the live band mix.
    return np.concatenate(
        [np.linspace(0.01, 0.19, n - n_high), np.linspace(0.25, 0.85, n_high)]
    )


def test_low_threshold_read_from_calibration():
    assert vf._low_band_threshold() == calibration._LOW_THRESHOLD


def test_pass_path_with_previous(tmp_path, capsys):
    _write_forecast(tmp_path / "cur", _healthy_probs())
    previous = _write_forecast(tmp_path / "prev", _healthy_probs())
    assert vf.main(["--curated", str(tmp_path / "cur"), "--previous", str(previous)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_all_safe_collapse_fails_without_previous(tmp_path, capsys):
    # Distinct, in-range, full-count, fresh — only the new check can catch it.
    # Every row must sit below the CURRENT Low cut for the collapse check to
    # fire. The 2026-08-08 band reset moved it 0.20 -> 0.10, so the old
    # 0.01..0.19 sweep stopped being "all safe" and the check correctly passed.
    _write_forecast(tmp_path / "cur", np.linspace(0.01, 0.09, 60))
    assert vf.main(["--curated", str(tmp_path / "cur")]) == 1
    err = capsys.readouterr().err
    assert "[all-safe-collapse]" in err
    assert "0.0900" in err  # the max is printed


def test_mean_squash_vs_previous_fails(tmp_path, capsys):
    # One non-Low row so neither all-safe-collapse nor band-sanity fires;
    # the mean is still < 0.25x the previous run's.
    cur_probs = np.concatenate([np.linspace(0.001, 0.02, 59), [0.5]])
    _write_forecast(tmp_path / "cur", cur_probs)
    previous = _write_forecast(tmp_path / "prev", np.linspace(0.25, 0.45, 60))
    assert vf.main(["--curated", str(tmp_path / "cur"), "--previous", str(previous)]) == 1
    err = capsys.readouterr().err
    assert "[distribution-shift]" in err
    assert f"{cur_probs.mean():.4f}" in err
    assert "0.3500" in err
    assert "[all-safe-collapse]" not in err
    assert "[band-sanity]" not in err


def test_mean_explosion_vs_previous_fails(tmp_path, capsys):
    # Current mean 0.60 vs previous 0.055 — > 4x the previous mean.
    prev_probs = np.linspace(0.01, 0.10, 60)
    _write_forecast(tmp_path / "cur", np.linspace(0.3, 0.9, 60))
    previous = _write_forecast(tmp_path / "prev", prev_probs)
    prev_mean = prev_probs.mean()
    assert vf.main(["--curated", str(tmp_path / "cur"), "--previous", str(previous)]) == 1
    err = capsys.readouterr().err
    assert "[distribution-shift]" in err
    assert "0.6000" in err
    assert f"{prev_mean:.4f}" in err


def test_row_count_drop_vs_previous_fails(tmp_path, capsys):
    # 60 rows clears the absolute floor but is < 50% of the previous 200;
    # the distributions match so only the row-count clause fires.
    _write_forecast(tmp_path / "cur", _healthy_probs(60, 10))
    previous = _write_forecast(tmp_path / "prev", _healthy_probs(200, 33))
    assert vf.main(["--curated", str(tmp_path / "cur"), "--previous", str(previous)]) == 1
    err = capsys.readouterr().err
    assert "[distribution-shift]" in err
    assert "60" in err
    assert "200" in err


def test_band_collapse_with_healthy_probs_fails(tmp_path, capsys):
    # Banding/display regression: probabilities look fine but the served
    # risk_band column is all Low while the previous run had >= 5 non-Low.
    _write_forecast(tmp_path / "cur", _healthy_probs(), bands=["Low"] * 60)
    previous = _write_forecast(
        tmp_path / "prev", _healthy_probs(), bands=["High"] * 6 + ["Low"] * 54
    )
    assert vf.main(["--curated", str(tmp_path / "cur"), "--previous", str(previous)]) == 1
    err = capsys.readouterr().err
    assert "[band-sanity]" in err
    assert "6" in err
    assert "[all-safe-collapse]" not in err


def test_band_check_skipped_on_degenerate_previous_baseline(tmp_path, capsys):
    # Previous run served < MIN_PREVIOUS_NON_LOW non-Low rows — no baseline.
    _write_forecast(tmp_path / "cur", _healthy_probs(), bands=["Low"] * 60)
    previous = _write_forecast(
        tmp_path / "prev", _healthy_probs(), bands=["High"] * 2 + ["Low"] * 58
    )
    assert vf.main(["--curated", str(tmp_path / "cur"), "--previous", str(previous)]) == 0


def test_missing_previous_skips_comparison_checks(tmp_path, capsys):
    _write_forecast(tmp_path / "cur", _healthy_probs())
    missing = tmp_path / "nope" / "prev_forecasts.parquet"
    assert vf.main(["--curated", str(tmp_path / "cur"), "--previous", str(missing)]) == 0
    captured = capsys.readouterr()
    assert "skipping" in captured.err
    assert "PASS" in captured.out


def test_unparseable_previous_skips_comparison_checks(tmp_path, capsys):
    _write_forecast(tmp_path / "cur", _healthy_probs())
    garbage = tmp_path / "prev_forecasts.parquet"
    garbage.write_bytes(b"not a parquet file")
    assert vf.main(["--curated", str(tmp_path / "cur"), "--previous", str(garbage)]) == 0
    assert "skipping" in capsys.readouterr().err


def test_env_bypass_skips_anomaly_checks_with_loud_notice(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SKIP_FORECAST_ANOMALY_CHECKS", "1")
    _write_forecast(tmp_path / "cur", np.linspace(0.01, 0.19, 60))  # all-safe collapse
    assert vf.main(["--curated", str(tmp_path / "cur")]) == 0
    captured = capsys.readouterr()
    assert "BYPASSING" in captured.err
    assert "SKIP_FORECAST_ANOMALY_CHECKS" in captured.err
    assert "PASS" in captured.out


def test_env_bypass_does_not_disable_base_checks(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SKIP_FORECAST_ANOMALY_CHECKS", "1")
    _write_forecast(tmp_path / "cur", np.full(60, 0.5))  # degenerate constant output
    assert vf.main(["--curated", str(tmp_path / "cur")]) == 1
    assert "identical" in capsys.readouterr().err


def _write_stale_forecast(directory: Path, probs) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    yesterday = (
        datetime.now(ZoneInfo("America/Los_Angeles")).date() - pd.Timedelta(days=1)
    ).isoformat()
    frame = pd.DataFrame(
        {
            "beach_id": [f"beach_{i}" for i in range(len(probs))],
            "forecast_date": [yesterday] * len(probs),
            "p_exceed": np.asarray(probs, dtype=float),
        }
    )
    path = directory / "forecasts.parquet"
    frame.to_parquet(path)
    return path


def _write_health(directory: Path, *, enforced, published, fresh=True) -> None:
    import json
    from datetime import UTC

    stamp = datetime.now(UTC) if fresh else datetime(2020, 1, 1, tzinfo=UTC)
    payload = {
        "pipeline_freshness": stamp.isoformat(),
        "release_gate": {
            "enforced": enforced,
            "public_release_eligible": not enforced or published,
            "forecast_published": published,
            "blockers": [] if published else ["spatial gate regression"],
        },
    }
    (directory / "system_health.json").write_text(json.dumps(payload))


def test_stale_forecast_fails_without_gate_block(tmp_path):
    cur = tmp_path / "cur"
    _write_stale_forecast(cur, _healthy_probs())
    failures = vf.validate(cur)
    assert any("stale forecast" in message for message in failures)


def test_stale_forecast_tolerated_when_gate_blocked_this_run(tmp_path, capsys):
    # The release gate deliberately froze publication THIS run: the stale
    # forecast_date is expected and must not fail validation (the commit must
    # proceed so the blockers reach the repo; verify_release_gate.py fails the
    # job afterwards).
    cur = tmp_path / "cur"
    _write_stale_forecast(cur, _healthy_probs())
    _write_health(cur, enforced=True, published=False, fresh=True)
    failures = vf.validate(cur)
    assert not any("stale forecast" in message for message in failures)
    assert "release gate deliberately blocked" in capsys.readouterr().err


def test_stale_forecast_fails_when_gate_payload_is_old(tmp_path):
    # An OLD health payload (training crashed before writing health) must never
    # excuse a stale forecast — fail-closed.
    cur = tmp_path / "cur"
    _write_stale_forecast(cur, _healthy_probs())
    _write_health(cur, enforced=True, published=False, fresh=False)
    failures = vf.validate(cur)
    assert any("stale forecast" in message for message in failures)


def test_stale_forecast_fails_when_gate_published(tmp_path):
    # Gate enforced but publication went through: a stale date then means the
    # write itself failed — that must still fail validation.
    cur = tmp_path / "cur"
    _write_stale_forecast(cur, _healthy_probs())
    _write_health(cur, enforced=True, published=True, fresh=True)
    failures = vf.validate(cur)
    assert any("stale forecast" in message for message in failures)
