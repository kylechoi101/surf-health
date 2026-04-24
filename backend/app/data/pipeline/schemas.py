from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class CuratedBeachDay:
    beach_id: str
    target_date: date
    sample_time: datetime | None
    enterococcus_value: float | None
    exceeds_stv: int | None
    wave_height_m: float | None
    dominant_period_s: float | None
    water_temperature_c: float | None
    salinity_psu: float | None
    uv_index: float | None
    wind_speed_mps: float | None
    wind_direction_deg: float | None

