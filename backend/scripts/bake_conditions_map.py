"""Bake the data for the web "conditions" vector map:

  1. conditions.json — one row per beach with current wind / swell / UV / risk,
     for per-beach glyphs (Tier 1) + the bacteria/UV layers.
  2. wind_grid.json   — a REGULAR lat/lon grid of (u, v) wind components over the
     CA coastal ocean (Tier 2 particle field), fetched in bulk from Open-Meteo.

Run:
  .venv/bin/python -m scripts.bake_conditions_map --curated ../data/curated \
      --out ../../shorelife-web/public/data

Outputs are static JSON the Next.js static export ships as-is. Designed to be
called from the daily web bake so the field refreshes with the forecast.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

# CA coastal ocean bounding box for the wind field (slightly offshore-weighted).
GRID_WEST, GRID_EAST = -125.0, -117.0
GRID_SOUTH, GRID_NORTH = 32.3, 42.1
GRID_STEP = 0.5  # ~55 km cells — coarse but smooth enough for a particle field
_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


def _f(v) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def bake_conditions(curated: Path) -> list[dict]:
    """Per-beach current conditions for the glyph + bacteria + UV layers."""
    beaches = pd.read_parquet(curated / "beaches.parquet")
    env_path = curated / "latest_env.parquet"
    env = pd.read_parquet(env_path) if env_path.exists() else pd.DataFrame()
    env_by = {str(r["beach_id"]): r for _, r in env.iterrows()} if not env.empty else {}

    surf_path = curated / "surf_now.parquet"
    surf = pd.read_parquet(surf_path) if surf_path.exists() else pd.DataFrame()
    surf_by = {str(r["beach_id"]): r for _, r in surf.iterrows()} if not surf.empty else {}

    fc_path = curated / "forecasts.parquet"
    fc = pd.read_parquet(fc_path) if fc_path.exists() else pd.DataFrame()
    band_by = {str(r["beach_id"]): r.get("risk_band") for _, r in fc.iterrows()} if not fc.empty else {}
    pex_by = {str(r["beach_id"]): _f(r.get("p_exceed")) for _, r in fc.iterrows()} if not fc.empty else {}

    # Water-quality severity in [0,1]: 0 = good (green), 1 = bad/advisory (red).
    # The web draws a blurred gradient field from each station; this is the value
    # it colors. Prefer the continuous p_exceed; fall back to the risk band.
    _BAND_SEV = {"Low": 0.08, "Moderate": 0.38, "High": 0.66, "Very High": 0.9, "Advisory": 1.0}

    def _wq_severity(band, pex) -> float | None:
        if band == "Advisory":
            return 1.0
        if pex is not None:
            return min(1.0, max(0.04, pex / 0.45))  # p_exceed 0.45+ → full red
        if band:
            return _BAND_SEV.get(band)
        return None

    rows: list[dict] = []
    for _, b in beaches.iterrows():
        bid = str(b.get("beach_id") or "")
        lat, lon = _f(b.get("latitude")), _f(b.get("longitude"))
        if lat is None or lon is None:
            continue
        e = env_by.get(bid)
        s = surf_by.get(bid)
        # swell direction prefers the dedicated surf feed, else falls back to wave
        swell_dir = None
        swell_h = None
        swell_p = None
        if s is not None:
            swell_dir = _f(s.get("primary_swell_direction_deg")) or _f(s.get("wave_direction_deg"))
            swell_h = _f(s.get("wave_height_m"))
            swell_p = _f(s.get("wave_period_s"))
        rec = {
            "id": bid,
            "name": str(b.get("name") or b.get("beach_name") or ""),
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "risk_band": band_by.get(bid),
            "p_exceed": pex_by.get(bid),
            "wq": _wq_severity(band_by.get(bid), pex_by.get(bid)),
            "wind_speed_mps": _f(e.get("wind_speed_mps")) if e is not None else None,
            "wind_dir_deg": _f(e.get("wind_direction_deg")) if e is not None else None,
            "uv_index": _f(e.get("uv_index")) if e is not None else None,
            "wave_height_m": (_f(e.get("wave_height_m")) if e is not None else None) or swell_h,
            "swell_dir_deg": swell_dir,
            "swell_period_s": swell_p,
        }
        # keep only beaches that carry at least one vector/scalar to draw
        if any(rec[k] is not None for k in ("wind_speed_mps", "uv_index", "swell_dir_deg", "risk_band")):
            rows.append(rec)
    return rows


def bake_wind_grid() -> dict:
    """Regular (u, v) wind grid over the CA coast for the particle field.

    u = eastward m/s, v = northward m/s. Open-Meteo gives speed + the direction
    the wind is coming FROM (meteorological); convert to the vector the wind is
    going TO so particles drift downwind.
    """
    lats = np.round(np.arange(GRID_SOUTH, GRID_NORTH + 1e-9, GRID_STEP), 4)
    lons = np.round(np.arange(GRID_WEST, GRID_EAST + 1e-9, GRID_STEP), 4)
    width, height = len(lons), len(lats)

    # row-major (south->north rows, west->east cols) list of coords
    coord_lat: list[float] = []
    coord_lon: list[float] = []
    for la in lats:
        for lo in lons:
            coord_lat.append(float(la))
            coord_lon.append(float(lo))

    u = [0.0] * (width * height)
    v = [0.0] * (width * height)
    # Open-Meteo bulk: batch coords to stay under URL length limits.
    BATCH = 180
    with httpx.Client(headers={"User-Agent": "Shorelife/1.0"}, timeout=40.0) as client:
        for start in range(0, len(coord_lat), BATCH):
            la_b = coord_lat[start : start + BATCH]
            lo_b = coord_lon[start : start + BATCH]
            params = {
                "latitude": ",".join(f"{x:.3f}" for x in la_b),
                "longitude": ",".join(f"{x:.3f}" for x in lo_b),
                "current": "wind_speed_10m,wind_direction_10m",
                "wind_speed_unit": "ms",
            }
            resp = client.get(_OPEN_METEO, params=params)
            resp.raise_for_status()
            payload = resp.json()
            results = payload if isinstance(payload, list) else [payload]
            for j, loc in enumerate(results):
                cur = (loc or {}).get("current") or {}
                spd = _f(cur.get("wind_speed_10m")) or 0.0
                frm = _f(cur.get("wind_direction_10m"))
                idx = start + j
                if frm is None:
                    continue
                to = math.radians((frm + 180.0) % 360.0)  # going-TO direction
                # meteorological: 0=N, 90=E. u east, v north.
                u[idx] = spd * math.sin(to)
                v[idx] = spd * math.cos(to)

    return {
        "bounds": [float(GRID_WEST), float(GRID_SOUTH), float(GRID_EAST), float(GRID_NORTH)],
        "width": width,
        "height": height,
        "uMin": min(u), "uMax": max(u),
        "vMin": min(v), "vMax": max(v),
        "u": [round(x, 3) for x in u],
        "v": [round(x, 3) for x in v],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--curated", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--skip-grid", action="store_true", help="conditions only (no network grid)")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    conditions = bake_conditions(Path(args.curated))
    (out / "conditions.json").write_text(json.dumps(conditions, separators=(",", ":")))
    print(f"[conditions] wrote {len(conditions)} beaches -> {out/'conditions.json'}")

    if not args.skip_grid:
        grid = bake_wind_grid()
        (out / "wind_grid.json").write_text(json.dumps(grid, separators=(",", ":")))
        print(f"[wind_grid] wrote {grid['width']}x{grid['height']} grid "
              f"(u {grid['uMin']:.1f}..{grid['uMax']:.1f}, v {grid['vMin']:.1f}..{grid['vMax']:.1f}) "
              f"-> {out/'wind_grid.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
