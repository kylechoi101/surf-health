"""Tests for the curated beach_day output-schema guard."""
import logging

import numpy as np
import pandas as pd
import pytest

from app.data.pipeline.schema_guard import (
    BeachDaySchemaError,
    EXPECTED_FEATURE_COLUMNS,
    validate_beach_day,
)


def _good_frame() -> pd.DataFrame:
    """A minimal structurally-valid beach_day frame with all expected features."""
    base = {
        "beach_id": ["b1", "b2"],
        "sample_date": ["2026-06-10", "2026-06-11"],
        "exceeds_stv": [False, True],
    }
    for col in EXPECTED_FEATURE_COLUMNS:
        base[col] = [1.0, 0.0]
    return pd.DataFrame(base)


def test_passes_on_good_frame():
    # Should not raise.
    validate_beach_day(_good_frame())


def test_raises_on_empty_frame():
    with pytest.raises(BeachDaySchemaError):
        validate_beach_day(pd.DataFrame())


def test_raises_on_none_frame():
    with pytest.raises(BeachDaySchemaError):
        validate_beach_day(None)


def test_raises_on_missing_primary_key():
    frame = _good_frame().drop(columns=["beach_id"])
    with pytest.raises(BeachDaySchemaError, match="primary key"):
        validate_beach_day(frame)


def test_raises_on_missing_sample_date():
    frame = _good_frame().drop(columns=["sample_date"])
    with pytest.raises(BeachDaySchemaError, match="primary key"):
        validate_beach_day(frame)


def test_raises_on_missing_label():
    frame = _good_frame().drop(columns=["exceeds_stv"])
    with pytest.raises(BeachDaySchemaError, match="label"):
        validate_beach_day(frame)


def test_warns_not_raises_on_missing_feature_column(caplog):
    frame = _good_frame().drop(columns=["solar_inactivation_index"])
    with caplog.at_level(logging.WARNING):
        validate_beach_day(frame)  # must NOT raise
    assert any("missing" in rec.message for rec in caplog.records)
    assert any("solar_inactivation_index" in rec.getMessage() for rec in caplog.records)


def test_warns_not_raises_on_all_nan_feature_column(caplog):
    """A connector outage legitimately yields an all-NaN feature column — warn, don't break the run."""
    frame = _good_frame()
    frame["uv_index_24h_max"] = np.nan
    with caplog.at_level(logging.WARNING):
        validate_beach_day(frame)  # must NOT raise
    assert any("entirely NaN" in rec.getMessage() for rec in caplog.records)
    assert any("uv_index_24h_max" in rec.getMessage() for rec in caplog.records)


def test_no_warning_on_fully_healthy_frame(caplog):
    with caplog.at_level(logging.WARNING):
        validate_beach_day(_good_frame())
    assert not [rec for rec in caplog.records if rec.levelno >= logging.WARNING]
