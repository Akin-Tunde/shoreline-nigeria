"""Catalog cloud-filtered Sentinel-2 L2A tiles over the Lagos–Lekki–Badagry coast.

Data access: fully anonymous.

1. Search the Copernicus Data Space Ecosystem STAC API (no authentication)
   for clear scenes over the four MGRS tiles covering the coast.
2. Cross-check each candidate against the public s3://sentinel-s2-l2a bucket
   (Sinergise mirror), which only archives Sentinel-2 data from 2017 onward
   for this region — the demonstrable analysis period is therefore 2017–2025
   (9 years, with 2015–2016 noted as a documented limitation).
3. Keep the 2 clearest available scenes per year.

Output: data/scene_catalog.json
"""

import json

import boto3
import requests
from botocore import UNSIGNED
from botocore.config import Config

from config import CATALOG_PATH

STAC_URL = "https://stac.dataspace.copernicus.eu/v1/search"
BUCKET = "sentinel-s2-l2a"

# MGRS tiles covering the Lagos–Lekki–Badagry coastal stretch
TILES = ["31NEH", "31NFH", "31NEG", "31NFG"]

# Bucket coverage for this region starts in 2017
START = "2017-01-01T00:00:00Z"
END = "2025-12-31T23:59:59Z"
MAX_CLOUD = 20.0  # % scene cloud cover (coast subset usually clearer)

s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED))


def search_tile(tile: str) -> list[dict]:
    """Return all clear STAC features for one MGRS tile."""
    features = []
    token = None
    while True:
        payload = {
            "collections": ["sentinel-2-l2a"],
            "query": {
                "grid:code": {"eq": f"MGRS-{tile}"},
                "eo:cloud_cover": {"lt": MAX_CLOUD},
            },
            "datetime": f"{START}/{END}",
            "limit": 100,
        }
        if token:
            payload["token"] = token
        resp = requests.post(STAC_URL, json=payload, timeout=90)
        resp.raise_for_status()
        data = resp.json()
        features.extend(data.get("features", []))
        links = data.get("links", [])
        token = next((l.get("body", {}).get("token")
                      for l in links if l.get("rel") == "next"), None)
        if not token:
            break
    return features


def bucket_prefix(tile: str, date: str) -> str:
    # The public bucket uses UNPADDED month/day directories (1, not 01)
    return (f"tiles/{tile[0:2]}/{tile[2]}/{tile[3:]}/"
            f"{date[:4]}/{int(date[5:7])}/{int(date[8:10])}/0/")


def bucket_has(scene: dict) -> bool:
    """Check the scene's bands exist in the public bucket (head B03 only)."""
    key = bucket_prefix(scene["tile"], scene["datetime"][:10]) + "R20m/B03.jp2"
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def main():
    all_features = []
    for tile in TILES:
        feats = search_tile(tile)
        print(f"{tile}: {len(feats)} clear scenes in STAC")
        all_features.extend(feats)

    # De-duplicate across overlapping tiles
    seen = set()
    unique = []
    for f in all_features:
        key = f["properties"].get("datetime") or f["id"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)

    # Filter to bucket-verified scenes
    verified = []
    for f in unique:
        scene = {
            "tile": f["properties"]["grid:code"].replace("MGRS-", ""),
            "datetime": f["properties"]["datetime"],
        }
        if bucket_has(scene):
            verified.append(f)
        elif len(verified) < 12:
            print(f"bucket-miss: {f['id']} (continuing)")
    print(f"bucket-verified scenes: {len(verified)}")

    # Keep the 2 clearest scenes per year
    by_year = {}
    for f in verified:
        y = f["properties"]["datetime"][:4]
        by_year.setdefault(y, []).append(f)

    selected = []
    for y in sorted(by_year):
        pool = sorted(by_year[y],
                      key=lambda f: f["properties"]["eo:cloud_cover"])[:2]
        selected.extend(pool)
        for f in pool:
            print(f"{y}: {f['id']} tile={f['properties']['grid:code']} "
                  f"cloud={f['properties']['eo:cloud_cover']:.1f}%")

    catalog = {
        "source": ("Copernicus Data Space Ecosystem STAC + "
                   "public s3://sentinel-s2-l2a (anonymous access)"),
        "study_area": "Lagos–Lekki–Badagry coastal stretch, Nigeria",
        "bbox": [2.9, 6.15, 4.35, 6.85],
        "max_cloud_cover": MAX_CLOUD,
        "period_covered": ("2017-01-01 to 2025-12-31 "
                           "(public bucket coverage for the region)"),
        "n_selected": len(selected),
        "scenes": [],
    }
    for f in selected:
        props = f["properties"]
        catalog["scenes"].append({
            "id": f["id"],
            "tile": props["grid:code"].replace("MGRS-", ""),
            "datetime": props["datetime"],
            "cloud_cover": props["eo:cloud_cover"],
            "geometry": f.get("geometry"),
        })

    CATALOG_PATH.write_text(json.dumps(catalog, indent=2))
    print(f"saved {len(selected)} scenes to {CATALOG_PATH}")


if __name__ == "__main__":
    main()
