from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.repositories.base import BeachRepository
from app.repositories.curated_repository import CuratedBeachRepository
from app.repositories.fixture_repository import FixtureBeachRepository
from app.repositories.serving_repository import ServingSnapshotRepository


def build_repository(settings: Settings) -> BeachRepository:
    curated_dir = Path(settings.curated_dir)
    serving_snapshot = curated_dir / "serving.sqlite"
    preferred = settings.preferred_repository.lower()
    serving_ready = serving_snapshot.exists()
    curated_ready = (curated_dir / "beaches.parquet").exists() and (
        curated_dir / "observations.parquet"
    ).exists()

    if preferred == "fixture":
        return FixtureBeachRepository(settings.fixture_data_path)
    if preferred in {"serving", "sqlite"}:
        if not serving_ready:
            raise FileNotFoundError(f"Serving snapshot requested but missing {serving_snapshot}")
        return ServingSnapshotRepository(serving_snapshot, settings.epa_marine_enterococcus_stv)
    if (preferred == "curated" or preferred == "auto") and serving_ready:
        return ServingSnapshotRepository(serving_snapshot, settings.epa_marine_enterococcus_stv)
    if preferred == "curated" and not curated_ready:
        raise FileNotFoundError(f"Curated repository requested but missing files in {curated_dir}")
    if preferred == "curated" or curated_ready:
        return CuratedBeachRepository(curated_dir, settings.epa_marine_enterococcus_stv)
    return FixtureBeachRepository(settings.fixture_data_path)
