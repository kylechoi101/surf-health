from pathlib import Path

from app.data.connectors.official_sources import CEDEN_FIB_SITES_FILENAME
from app.data.pipeline.cli import (
    _ceden_results_resource_id_for_path,
    _ceden_results_url_for_path,
    _find_existing_ceden_resource_path,
    _resolve_ceden_resource_path,
)


def test_resolve_ceden_resource_prefers_existing_raw_file(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    existing = raw_dir / CEDEN_FIB_SITES_FILENAME
    existing.write_text("site-data")

    resolved = _resolve_ceden_resource_path(
        requested_path=Path("/tmp/safetoswim_sites_2025-03-25.csv"),
        raw_dir=raw_dir,
        default_raw_filename=CEDEN_FIB_SITES_FILENAME,
        resource_url="https://example.com/sites.csv",
    )

    assert resolved == existing


def test_resolve_ceden_resource_downloads_to_requested_path_when_missing(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    requested = tmp_path / "downloads" / "safetoswim_geomeans_2020-present.csv"
    calls: list[tuple[str, Path]] = []

    def fake_downloader(url: str, destination: Path) -> Path:
        calls.append((url, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("results-data")
        return destination

    resolved = _resolve_ceden_resource_path(
        requested_path=requested,
        raw_dir=raw_dir,
        default_raw_filename="safetoswim_geomeans_2020-present.csv",
        resource_url="https://example.com/results.csv",
        downloader=fake_downloader,
    )

    assert resolved == requested
    assert requested.read_text() == "results-data"
    assert calls == [("https://example.com/results.csv", requested)]


def test_ceden_results_url_defaults_to_2020_present():
    assert "2020-present" in _ceden_results_url_for_path(None)
    assert "2010-2020" in _ceden_results_url_for_path(Path("/tmp/safetoswim_geomeans_2010-2020.csv"))
    assert "before-2010" in _ceden_results_url_for_path(Path("/tmp/safetoswim_geomeans_before-2010.csv"))


def test_ceden_results_resource_id_defaults_to_2020_present():
    assert _ceden_results_resource_id_for_path(None) == "15a63495-8d9f-4a49-b43a-3092ef3106b9"
    assert _ceden_results_resource_id_for_path(Path("/tmp/safetoswim_geomeans_2010-2020.csv")) == (
        "04d98c22-5523-4cc1-86e7-3a6abf40bb60"
    )


def test_find_existing_ceden_resource_path_checks_requested_then_raw(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    existing = raw_dir / "safetoswim_geomeans_2020-present.csv"
    existing.write_text("cached")
    requested = tmp_path / "missing" / "safetoswim_geomeans_2020-present.csv"

    resolved = _find_existing_ceden_resource_path(
        requested_path=requested,
        raw_dir=raw_dir,
        default_raw_filename="safetoswim_geomeans_2020-present.csv",
    )

    assert resolved == existing
