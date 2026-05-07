#!/usr/bin/env python3
import json
import re
from pathlib import Path

import pandas as pd


REGION_MAP = {
    "No RB": "North Coast",
}


def normalize_region(region: object) -> str:
    text = str(region or "").strip() or "Unknown"
    return REGION_MAP.get(text, text)


def clean_text(value: object, fallback: str = "") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return fallback
    text = str(value).strip()
    text = re.sub(r"\\+(['\"])", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text or fallback


def safe_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def to_iso(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


def to_driver_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        return [str(item) for item in value.tolist() if str(item).strip()]
    if value is None:
        return []
    try:
        if pd.isna(value):
            return []
    except Exception:
        pass
    return [str(value)]


def main() -> None:
    root_dir = Path(__file__).resolve().parent.parent
    curated_dir = root_dir / "data" / "curated"
    out_dir = root_dir / "web" / "public" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    beaches = pd.read_parquet(curated_dir / "beaches.parquet")
    parent_beaches = pd.read_parquet(curated_dir / "parent_beaches.parquet")

    forecast_path = curated_dir / "forecasts.parquet"
    forecasts = pd.read_parquet(forecast_path) if forecast_path.exists() else pd.DataFrame()

    advisories_path = curated_dir / "advisories.parquet"
    advisories = pd.read_parquet(advisories_path) if advisories_path.exists() else pd.DataFrame()
    active_advisory_ids: set[str] = set()
    if not advisories.empty and "status" in advisories.columns and "beach_id" in advisories.columns:
        active = advisories[advisories["status"] == "active"][["beach_id"]].drop_duplicates()
        active_advisory_ids = {str(v) for v in active["beach_id"].tolist()}

    env_path = curated_dir / "latest_env.parquet"
    latest_env = pd.read_parquet(env_path) if env_path.exists() else pd.DataFrame()

    forecast_lookup: dict[str, dict[str, object]] = {}
    if not forecasts.empty:
        for _, row in forecasts.iterrows():
            bid = str(row["beach_id"])
            base_forecast = {
                "risk_band": clean_text(row.get("risk_band")),
                "p_exceed": safe_float(row.get("p_exceed")),
                "p_exceed_lower": safe_float(row.get("p_exceed_lower")),
                "p_exceed_upper": safe_float(row.get("p_exceed_upper")),
                "model_version": clean_text(row.get("model_version")),
                "forecast_generated_at": to_iso(row.get("forecast_generated_at")),
                "top_drivers": to_driver_list(row.get("top_drivers")),
            }
            if bid in active_advisory_ids:
                base_forecast = {
                    **base_forecast,
                    "model_risk_band": base_forecast.get("risk_band"),
                    "official_advisory_active": True,
                    "risk_band": "Very High",
                    "top_drivers": [
                        "Official health advisory is active for this station.",
                        *to_driver_list(row.get("top_drivers")),
                    ][:5],
                }
            forecast_lookup[bid] = base_forecast

    env_lookup: dict[str, dict[str, object]] = {}
    if not latest_env.empty:
        for _, row in latest_env.iterrows():
            bid = str(row["beach_id"])
            env_lookup[bid] = {
                "wave_height_m": safe_float(row.get("wave_height_m")),
                "dominant_period_s": safe_float(row.get("dominant_period_s")),
                "water_temperature_c": safe_float(row.get("water_temperature_c")),
                "salinity_psu": safe_float(row.get("salinity_psu")),
                "uv_index": safe_float(row.get("uv_index")),
                "wind_speed_mps": safe_float(row.get("wind_speed_mps")),
                "wind_direction_deg": safe_float(row.get("wind_direction_deg")),
            }

    beaches_list: list[dict[str, object]] = []
    regional_data: dict[str, dict[str, float | int]] = {}

    for _, row in beaches.iterrows():
        bid = str(row["beach_id"])
        region = normalize_region(row.get("region"))
        forecast = forecast_lookup.get(bid)
        env = env_lookup.get(bid)
        support_status = clean_text(row.get("support_status"))
        if not forecast:
            support_status = "unsupported"
        has_active_advisory = bid in active_advisory_ids

        b_name = clean_text(row.get("beach_name"))
        s_name = clean_text(row.get("name"))
        
        if b_name and s_name and b_name.lower() != s_name.lower() and s_name.lower() not in b_name.lower():
            public_name = f"{b_name} ({s_name})"
        else:
            public_name = b_name or s_name or bid
            
        station_name = s_name or public_name

        beaches_list.append(
            {
                "id": bid,
                "name": public_name,
                "station_name": station_name,
                "county": clean_text(row.get("county")),
                "region": region,
                "latitude": safe_float(row.get("latitude")),
                "longitude": safe_float(row.get("longitude")),
                "support_status": support_status,
                "latest_official_sample_at": to_iso(row.get("latest_official_sample_at")),
                "has_active_advisory": has_active_advisory,
                "forecast": forecast,
                "env": env,
            }
        )

        bucket = regional_data.setdefault(
            region,
            {
                "monitored_site_count": 0,
                "modeled_site_count": 0,
                "temp_sum": 0.0,
                "temp_count": 0,
                "wave_sum": 0.0,
                "wave_count": 0,
                "high_risk_count": 0,
            },
        )
        bucket["monitored_site_count"] += 1

        if forecast:
            bucket["modeled_site_count"] += 1
            if forecast["risk_band"] in ("High", "Very High"):
                bucket["high_risk_count"] += 1

        if env and env.get("water_temperature_c") is not None:
            bucket["temp_sum"] += float(env["water_temperature_c"])
            bucket["temp_count"] += 1

        if env and env.get("wave_height_m") is not None:
            bucket["wave_sum"] += float(env["wave_height_m"])
            bucket["wave_count"] += 1

    beaches_list.sort(key=lambda item: (str(item["county"]), str(item["name"]), str(item["id"])))

    region_list: list[dict[str, object]] = []
    for region, data in regional_data.items():
        avg_temp = (
            float(data["temp_sum"]) / int(data["temp_count"])
            if int(data["temp_count"]) > 0
            else None
        )
        avg_wave = (
            float(data["wave_sum"]) / int(data["wave_count"])
            if int(data["wave_count"]) > 0
            else None
        )
        region_list.append(
            {
                "region": region,
                "monitored_site_count": int(data["monitored_site_count"]),
                "modeled_site_count": int(data["modeled_site_count"]),
                "avg_water_temp_c": avg_temp,
                "avg_wave_height_m": avg_wave,
                "high_risk_count": int(data["high_risk_count"]),
            }
        )

    region_list.sort(key=lambda item: str(item["region"]))

    parents_list: list[dict[str, object]] = []
    for _, row in parent_beaches.iterrows():
        parents_list.append(
            {
                "id": str(row["parent_beach_id"]),
                "name": clean_text(row.get("name")),
                "county": clean_text(row.get("county")),
                "region": normalize_region(row.get("region")),
                "latitude": safe_float(row.get("latitude")),
                "longitude": safe_float(row.get("longitude")),
                "station_count": int(row["station_count"]),
                "member_beach_ids": [str(item) for item in list(row["member_beach_ids"])],
                "latest_official_sample_at": to_iso(row.get("latest_official_sample_at")),
            }
        )

    parents_list.sort(key=lambda item: (str(item["county"]), str(item["name"]), str(item["id"])))

    with open(out_dir / "beaches.json", "w", encoding="utf-8") as handle:
        json.dump(beaches_list, handle, indent=2)

    with open(out_dir / "regional_summary.json", "w", encoding="utf-8") as handle:
        json.dump(region_list, handle, indent=2)

    with open(out_dir / "parent_beaches.json", "w", encoding="utf-8") as handle:
        json.dump(parents_list, handle, indent=2)


if __name__ == "__main__":
    main()
