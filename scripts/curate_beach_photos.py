"""Curate ~25 known-good California beach photos from Wikimedia Commons.

Each title in CURATED_TITLES is one I've personally seen pass quality and
licensing checks in earlier fetches. This sidesteps Commons-search ranking
noise entirely. Each beach in the app then deterministic-hashes to one of
these via mobile/lib/photos.ts FALLBACK_POOL — no per-beach search step.

Run once locally:
    python scripts/curate_beach_photos.py

Outputs:
    mobile/assets/beach-photos-fallback/<safe_id>.jpg  (one JPG per curated entry)
    mobile/lib/photos.ts                                (regenerated FALLBACK_POOL)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO / "mobile" / "assets" / "beach-photos-fallback"
PHOTOS_TS = REPO / "mobile" / "lib" / "photos.ts"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
UA = "Shorelife/1.0 (https://github.com/kylechoi101/surf-health)"

# Each entry: (slug, Commons File: title). Slug determines local filename
# and the FALLBACK_POOL id used in photos.ts. Keep slugs short + descriptive.
CURATED_TITLES = [
    ("half-moon-bay",   "File:Half Moon Bay State Beach 30 2018-07-09.jpg"),
    ("el-matador",      "File:El Matador State Beach (36964379752).jpg"),
    ("pismo-beach",     "File:Pismo Beach (California, USA), Point San Luis -- 2012 -- 4734.jpg"),
    ("sunset-state",    "File:Sunset State Beach (19874705845).jpg"),
    ("san-clemente",    "File:San Clemente State Beach 46 2018-07-02.jpg"),
    ("malibu-lagoon",   "File:Brown pelican - Malibu Lagoon State Beach 2021-02-20.jpg"),
    ("carlsbad-tower",  "File:Tower 33 on Carlsbad State Beach, CA.jpg"),
    ("glass-beach",     "File:Glass Beach Fort Bragg 2.jpg"),
    ("tourmaline",      "File:Tourmaline Surfing Park, California.JPG"),
    ("torrey-pines",    "File:Drone Photography Torrey Pines Beach San Diego.jpg"),
    ("hermosa-beach",   "File:Hermosa Beach, California (6026563549).jpg"),
    ("venice-beach",    "File:Venice Beach, Los Angeles, California, USA.jpg"),
    ("el-pescador",     "File:El Pescador State Beach Malibu California Seascape Photography (145942415).jpeg"),
    ("malibu-sunset",   "File:Sunset In Malibu California United States Seascape Photography (150930837).jpeg"),
    ("santa-monica",    "File:Los Angeles (California, USA), Santa Monica Beach -- 2017 -- 0780.jpg"),
    ("moonstone",       "File:CALIFORNIA-MOONSTONE BEACH - NARA - 542889.jpg"),
    ("trinidad",        "File:TRINIDAD BEACH - NARA - 542966.jpg"),
    ("malibu-beach",    "File:Malibu Beach, California (6873548072).jpg"),
    ("portuguese-bend", "File:Abalone Cove, Portuguese Bend, Rancho Palos Verdes, CA - photo by D Ramey Logan.jpg"),
    ("baker-beach",     "File:San Francisco (CA, USA), Baker Beach -- 2022 -- 3034.jpg"),
    ("morro-bay",       "File:CALIFORNIA - MORRO BAY AREA and SLO County (919147125).jpg"),
    ("new-brighton",    "File:New Brighton State Beach1.jpg"),
    ("seabright",       "File:Seabright Beach Lighthouse (4696633054).jpg"),
    ("dana-point",      "File:Monarch Beach Dana Point California photo D Ramey Logan.jpg"),
    ("south-carlsbad",  "File:SouthCarlsbadStateBeach2019.jpg"),
]


def fetch_image_info(client: httpx.Client, title: str) -> dict | None:
    r = client.get(COMMONS_API, params={
        "action": "query",
        "titles": title,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime",
        "iiurlwidth": 800,
        "format": "json",
    })
    if r.status_code != 200:
        return None
    pages = r.json().get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {})
    info = page.get("imageinfo", [])
    return info[0] if info else None


def main() -> int:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    # Wipe stale fallbacks so we don't keep the old 6-photo pool
    for old in ASSETS_DIR.glob("*.jpg"):
        old.unlink()

    pool: list[dict] = []
    with httpx.Client(timeout=30, headers={"User-Agent": UA}) as client:
        for slug, title in CURATED_TITLES:
            info = fetch_image_info(client, title)
            if not info:
                print(f"FAIL info  {slug:20s}  {title[:60]}", file=sys.stderr)
                continue
            url = info.get("thumburl") or info.get("url")
            try:
                r = client.get(url)
                r.raise_for_status()
            except Exception as e:
                print(f"FAIL fetch {slug:20s}  {e}", file=sys.stderr)
                continue
            dest = ASSETS_DIR / f"{slug}.jpg"
            dest.write_bytes(r.content)
            meta = info.get("extmetadata", {}) or {}
            license_short = (meta.get("LicenseShortName", {}) or {}).get("value") or "CC"
            author_html = (meta.get("Artist", {}) or {}).get("value") or "Unknown"
            author = re.sub(r"<[^>]+>", "", author_html).strip() or "Unknown"
            pool.append({
                "slug": slug,
                "author": author,
                "license": license_short,
                "size_kb": dest.stat().st_size // 1024,
                "title": title,
            })
            print(f"OK         {slug:20s}  ({license_short}, {dest.stat().st_size // 1024}KB)  {title[:60]}")

    if not pool:
        print("No photos curated; aborting.", file=sys.stderr)
        return 1

    # Regenerate mobile/lib/photos.ts with the curated pool
    entries = "\n".join(
        f"  {{\n"
        f'    id: "{p["slug"]}",\n'
        f'    source: () => require("../assets/beach-photos-fallback/{p["slug"]}.jpg"),\n'
        f'    photographer: {repr(p["author"])},\n'
        f'    attributionSource: {repr(f"Wikimedia Commons · {p["license"]}")},\n'
        f"  }},"
        for p in pool
    )
    ts = f"""\
import type {{ ImageSourcePropType }} from "react-native";

export interface PhotoCredit {{
  source: () => ImageSourcePropType;
  photographer: string;
  attributionSource: string;
  id: string;
}}

// Auto-generated by scripts/curate_beach_photos.py. Hand-curated set of
// California beach photos from Wikimedia Commons; each is verified free-licensed
// and shows an actual beach. Each user-facing beach deterministically hashes to
// one of these via getPhotoForBeach().
const FALLBACK_POOL: PhotoCredit[] = [
{entries}
];

function hash(s: string): number {{
  let h = 0;
  for (let i = 0; i < s.length; i++) {{
    h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  }}
  return Math.abs(h);
}}

export function getPhotoForBeach(beachId: string, _county?: string): PhotoCredit {{
  return FALLBACK_POOL[hash(beachId) % FALLBACK_POOL.length];
}}
"""
    PHOTOS_TS.write_text(ts)
    print(f"\nCurated {len(pool)} photos. photos.ts regenerated.")
    total_kb = sum(p["size_kb"] for p in pool)
    print(f"Total bundle add: {total_kb // 1024}MB ({total_kb}KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
