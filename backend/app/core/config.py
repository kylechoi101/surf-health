from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]
WORKSPACE_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    timezone: str = "America/Los_Angeles"
    data_dir: Path = WORKSPACE_DIR / "data"
    curated_dir: Path = WORKSPACE_DIR / "data/curated"
    research_dir: Path = WORKSPACE_DIR / "data/research"
    fixture_data_path: Path = BACKEND_DIR / "app/fixtures/sample_data.json"
    database_url: str = Field(
        default="postgresql+psycopg://surf_health:surf_health@localhost:5432/surf_health"
    )
    preferred_repository: str = "auto"
    california_bacteria_dataset_slug: str = "beach-water-quality-postings-and-closures"
    california_ceden_fib_dataset_slug: str = "surface-water-fecal-indicator-bacteria-results"
    epa_marine_enterococcus_stv: float = 104.0
    public_alert_probability_threshold: float = 0.38
    
    # Phase 1: Hydrology & Weather
    forecast_issue_hour_local: int = 5
    usgs_nwis_base_url: str = "https://waterservices.usgs.gov/nwis"
    cnrfc_base_url: str = "https://www.cnrfc.noaa.gov"
    nhdplus_data_dir: Path = WORKSPACE_DIR / "data/raw/nhdplus"
    hydrology_cache_dir: Path = WORKSPACE_DIR / "data/raw/usgs_streamflow"
    precip_cache_dir: Path = WORKSPACE_DIR / "data/raw/cnrfc"
    default_precip_lookback_days: int = 14
    default_streamflow_lookback_days: int = 14
    cnrfc_observed_station_allowlist_path: Path | None = None
    usgs_gage_allowlist_path: Path | None = None
    hydrologic_mapping_path: Path | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
