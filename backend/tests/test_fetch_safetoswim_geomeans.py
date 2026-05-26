"""Tests for scripts/fetch_safetoswim_geomeans.py.

The script replaces a `curl` of data.ca.gov's CKAN file-store, which
intermittently returns a malformed redirect (filename as host). We pull
from the datastore JSON API instead.
"""
from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import httpx


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch_safetoswim_geomeans.py"
_SPEC = importlib.util.spec_from_file_location("fetch_safetoswim_geomeans", _SCRIPT_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules["fetch_safetoswim_geomeans"] = _MODULE
_SPEC.loader.exec_module(_MODULE)


def _mock_response(records: list[dict]) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {"result": {"records": records}}
    response.raise_for_status.return_value = None
    return response


def test_build_sql_includes_bacteria_filter_and_pagination():
    sql = _MODULE.build_sql("res-123", limit=500, offset=1000)
    assert '"Program"' in sql and '"StationCode"' in sql
    assert 'FROM "res-123"' in sql
    assert "LIMIT 500 OFFSET 1000" in sql
    assert "enterococcus" in sql.lower()
    assert "coliform" in sql.lower()


def test_fetch_pages_stops_when_short_page_returned():
    client = MagicMock(spec=httpx.Client)
    client.get.side_effect = [
        _mock_response([{"StationCode": "A"} for _ in range(5)]),  # full page
        _mock_response([{"StationCode": "B"} for _ in range(2)]),  # short → stop
    ]
    pages = list(_MODULE.fetch_pages("res-1", client, page_size=5, max_pages=10))
    assert len(pages) == 2
    assert len(pages[0]) == 5 and len(pages[1]) == 2
    assert client.get.call_count == 2


def test_fetch_pages_stops_on_empty_page():
    client = MagicMock(spec=httpx.Client)
    client.get.side_effect = [
        _mock_response([{"StationCode": "A"} for _ in range(3)]),
        _mock_response([]),
    ]
    pages = list(_MODULE.fetch_pages("res-1", client, page_size=3, max_pages=10))
    assert len(pages) == 1


def test_fetch_pages_retries_on_transient_http_error(monkeypatch):
    monkeypatch.setattr(_MODULE.time, "sleep", lambda _s: None)
    client = MagicMock(spec=httpx.Client)
    transient = httpx.ConnectError("boom")
    ok = _mock_response([])  # empty page → loop exits
    client.get.side_effect = [transient, transient, ok]
    pages = list(_MODULE.fetch_pages("res-1", client, page_size=10, max_pages=2))
    assert pages == []
    assert client.get.call_count == 3


def test_main_writes_csv_with_expected_schema(monkeypatch, tmp_path):
    rows = [
        {
            "Program": "BeachWatch",
            "StationCode": "SD-001",
            "StationName": "Coronado, San Diego",
            "Analyte": "Enterococcus",
            "Result": "120",
            "TargetLatitude": "32.68",
            "TargetLongitude": "-117.19",
        },
        {
            "Program": "BeachWatch",
            "StationCode": "SD-002",
            "Analyte": "Coliform, Fecal",
            "Result": "33",
        },
    ]

    class _FakeClient:
        def __init__(self, *_a, **_kw): pass
        def __enter__(self): return self
        def __exit__(self, *_a): return False
        def get(self, *_a, **_kw): return _mock_response(rows)

    # Stand in for both httpx.Client (the script's context manager) and pagination:
    # first call returns 2 rows (less than page_size of 100), so loop exits after page 1.
    monkeypatch.setattr(_MODULE.httpx, "Client", _FakeClient)

    output = tmp_path / "safetoswim.csv"
    monkeypatch.setattr(sys, "argv", [
        "fetch_safetoswim_geomeans.py",
        "--output", str(output),
        "--page-size", "100",
    ])
    assert _MODULE.main() == 0
    assert output.exists()
    with output.open() as fh:
        reader = csv.DictReader(fh)
        written = list(reader)
    assert reader.fieldnames == _MODULE.COLUMNS
    assert len(written) == 2
    assert written[0]["StationCode"] == "SD-001"
    assert written[0]["Analyte"] == "Enterococcus"
    # Missing fields should write as empty (DictWriter default) and be tolerated downstream.
    assert written[1]["TargetLatitude"] == ""


def test_main_refuses_to_overwrite_with_empty_result(monkeypatch, tmp_path):
    class _FakeClient:
        def __init__(self, *_a, **_kw): pass
        def __enter__(self): return self
        def __exit__(self, *_a): return False
        def get(self, *_a, **_kw): return _mock_response([])

    monkeypatch.setattr(_MODULE.httpx, "Client", _FakeClient)
    output = tmp_path / "safetoswim.csv"
    # Pre-existing CSV that we don't want clobbered when CKAN returns 0 rows.
    output.write_text("Program\nPRE-EXISTING\n")
    monkeypatch.setattr(sys, "argv", [
        "fetch_safetoswim_geomeans.py",
        "--output", str(output),
    ])
    assert _MODULE.main() == 1
    assert output.read_text() == "Program\nPRE-EXISTING\n"
    assert not output.with_suffix(output.suffix + ".tmp").exists()


def test_main_skip_if_exists_short_circuits_before_http(monkeypatch, tmp_path):
    output = tmp_path / "safetoswim.csv"
    output.write_text("placeholder")

    # If the network was hit, this would raise — its presence guards correctness.
    def _explode(*_a, **_kw):
        raise AssertionError("should not have constructed httpx.Client")

    monkeypatch.setattr(_MODULE.httpx, "Client", _explode)
    monkeypatch.setattr(sys, "argv", [
        "fetch_safetoswim_geomeans.py",
        "--output", str(output),
        "--skip-if-exists",
    ])
    assert _MODULE.main() == 0
    assert output.read_text() == "placeholder"
