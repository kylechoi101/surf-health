from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.repositories.base import BeachRepository
from app.repositories.curated_repository import CuratedBeachRepository
from app.repositories.fixture_repository import FixtureBeachRepository


def build_repository(settings: Settings) -> BeachRepository:
    curated_dir = Path(settings.curated_dir)
    preferred = settings.preferred_repository.lower()
    curated_ready = (curated_dir / "beaches.parquet").exists() and (
        curated_dir / "observations.parquet"
    ).exists()

    if preferred == "fixture":
        return FixtureBeachRepository(settings.fixture_data_path)
    if preferred == "curated" and not curated_ready:
        raise FileNotFoundError(f"Curated repository requested but missing files in {curated_dir}")
    if preferred == "curated" or curated_ready:
        return CuratedBeachRepository(curated_dir, settings.epa_marine_enterococcus_stv)
    return FixtureBeachRepository(settings.fixture_data_path)

