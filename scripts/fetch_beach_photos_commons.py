"""Fetch a freely-licensed beach photo from Wikimedia Commons for each parent beach.

Wikimedia Commons hosts only free-licensed media (public domain, CC-BY, CC-BY-SA,
CC0). Bundling these in our app is legal as long as we display author + license
attribution per the CC license requirements.

Strategy per beach:
1. Search Commons for ``"<beach name>" California beach`` in the File namespace
2. Filter results to image extensions (.jpg/.jpeg/.png/.webp)
3. Fetch imageinfo for the top hit to get download URL + license metadata
4. Verify the license string indicates a free license
5. Download (downsized to 600px) and write to mobile/assets/beach-photos-cams/
6. Record author + license in a sidecar JSON for attribution

Beaches with no Commons match fall through to the curated stock pool in photos.ts.

Usage:
    python scripts/fetch_beach_photos_commons.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
API_URL = os.environ.get("API_URL", "https://surf-health-api.onrender.com")
PHOTOS_DIR = REPO / "mobile" / "assets" / "beach-photos-cams"
MANIFEST_PATH = REPO / "mobile" / "lib" / "bundledBeachPhotos.ts"
ATTRIBUTIONS_PATH = REPO / "mobile" / "lib" / "beachPhotoAttributions.ts"

UA = "Shorelife/1.0 (https://github.com/kylechoi101/surf-health; kylechoidsc@gmail.com)"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

FREE_LICENSE_PATTERNS = re.compile(
    r"(public.?domain|pd-|cc0|cc-by|cc by|creative commons attribution)",
    re.IGNORECASE,
)
IMAGE_EXT = re.compile(r"\.(jpe?g|png|webp)$", re.IGNORECASE)


def search(client: httpx.Client, beach_name: str, county: str | None) -> list[str]:
    """Return up to 5 candidate File: titles for this beach."""
    query = f'"{beach_name}" California'
    if county:
        query = f'"{beach_name}" {county} County California'
    r = client.get(COMMONS_API, params={
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srnamespace": 6,  # File namespace
        "srlimit": 5,
        "format": "json",
    })
    if r.status_code != 200:
        return []
    return [hit["title"] for hit in r.json().get("query", {}).get("search", [])]


def image_info(client: httpx.Client, title: str) -> dict | None:
    """Fetch URL + license + author for a File: title."""
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
    if not info:
        return None
    return info[0]


def is_usable(title: str, info: dict) -> tuple[bool, str | None, str | None]:
    """Returns (ok, license_short, author). Filters: image only, free license,
    width >= 600px (we'll downsize but want enough resolution).
    """
    if not IMAGE_EXT.search(title):
        return False, None, None
    if (info.get("mime") or "").startswith("image/") is False:
        return False, None, None
    if info.get("width", 0) < 600:
        return False, None, None

    meta = info.get("extmetadata", {}) or {}
    license_short = (meta.get("LicenseShortName", {}) or {}).get("value") or ""
    if not FREE_LICENSE_PATTERNS.search(license_short):
        return False, None, None

    author_html = (meta.get("Artist", {}) or {}).get("value") or ""
    # Strip HTML tags
    author = re.sub(r"<[^>]+>", "", author_html).strip() or "Unknown"
    return True, license_short, author


def main() -> int:
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=30, headers={"User-Agent": UA}) as client:
        beaches = client.get(f"{API_URL}/parent-beaches").json()
        print(f"Fetched {len(beaches)} parent beaches")

        covered: dict[str, dict] = {}
        skipped: int = 0

        for i, b in enumerate(beaches, 1):
            bid = b["id"]
            name = b["name"]
            county = b.get("county")

            titles = search(client, name, county)
            if not titles:
                # Fallback: search without county constraint
                titles = search(client, name, None)
            picked = None
            for title in titles:
                info = image_info(client, title)
                if not info:
                    continue
                ok, lic, author = is_usable(title, info)
                if ok:
                    picked = (title, info, lic, author)
                    break

            if not picked:
                skipped += 1
                if i % 25 == 0:
                    print(f"[{i}/{len(beaches)}] still going… covered={len(covered)} skipped={skipped}")
                continue

            title, info, lic, author = picked
            url = info.get("thumburl") or info.get("url")
            try:
                r = client.get(url)
                r.raise_for_status()
                dest = PHOTOS_DIR / f"{bid}.jpg"
                dest.write_bytes(r.content)
                covered[bid] = {
                    "title": title,
                    "author": author,
                    "license": lic,
                    "source": f"https://commons.wikimedia.org/wiki/{title.replace(' ', '_')}",
                }
                print(f"[{i}/{len(beaches)}] OK   {bid}  ← {title[:60]}  ({lic}, {dest.stat().st_size // 1024}KB)")
            except Exception as e:
                print(f"[{i}/{len(beaches)}] FAIL {bid}  ({e})")
                skipped += 1

            # Commons rate limit: be polite
            if i % 20 == 0:
                time.sleep(1)

    lines = ["// Auto-generated by scripts/fetch_beach_photos_commons.py. Do not edit."]
    lines.append("// Sourced from Wikimedia Commons; all photos are CC / public domain.")
    lines.append("export const BUNDLED_BEACH_PHOTOS: Record<string, number> = {")
    for bid in sorted(covered):
        lines.append(f'  "{bid}": require("../assets/beach-photos-cams/{bid}.jpg"),')
    lines.append("};")
    MANIFEST_PATH.write_text("\n".join(lines) + "\n")

    # Sidecar attribution file consumed by ImmersiveCard for the credit overlay.
    attr_lines = ["// Auto-generated. Attribution per Wikimedia Commons / CC license terms."]
    attr_lines.append("export interface PhotoAttribution {")
    attr_lines.append("  author: string;")
    attr_lines.append("  license: string;")
    attr_lines.append("  source: string;")
    attr_lines.append("}")
    attr_lines.append("export const BEACH_PHOTO_ATTRIBUTIONS: Record<string, PhotoAttribution> = {")
    for bid, meta in sorted(covered.items()):
        author = json.dumps(meta["author"])
        lic = json.dumps(meta["license"])
        src = json.dumps(meta["source"])
        attr_lines.append(f'  "{bid}": {{ author: {author}, license: {lic}, source: {src} }},')
    attr_lines.append("};")
    ATTRIBUTIONS_PATH.write_text("\n".join(attr_lines) + "\n")

    total_bytes = sum((PHOTOS_DIR / f"{b}.jpg").stat().st_size for b in covered)
    print(f"\nDone. Covered: {len(covered)}  Skipped: {skipped}")
    print(f"Bundle size: {total_bytes // (1024*1024)}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
