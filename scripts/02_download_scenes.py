"""Download Sentinel-2 L2A bands and SCL cloud masks for selected tiles.

Downloads anonymously from the public s3://sentinel-s2-l2a bucket
(Sinergise mirror of the Copernicus archive). Bands needed for shoreline
extraction at 20 m effective resolution:

- B03 (green) and B04 (red) for NDWI and MNDWI
- B11 (short-wave infrared) for MNDWI
- SCL (scene classification) for cloud / cloud-shadow masking

Fully rerunnable: existing files are skipped.
"""

import json
from pathlib import Path

import boto3
from botocore import UNSIGNED
from botocore.config import Config

from config import CATALOG_PATH, RAW_DIR

BUCKET = "sentinel-s2-l2a"
BANDS = ["B03", "B04", "B11", "SCL"]

s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED))


def load_catalog() -> list[dict]:
    return json.loads(CATALOG_PATH.read_text())["scenes"]


def bucket_prefix(scene: dict) -> str:
    date = scene["datetime"][:10]  # YYYY-MM-DD
    tile = scene["tile"]
    # The public bucket uses UNPADDED month/day directories (1, not 01)
    return (f"tiles/{tile[0:2]}/{tile[2]}/{tile[3:]}/"
            f"{date[:4]}/{int(date[5:7])}/{int(date[8:10])}/0/")


def main():
    scenes = load_catalog()
    print(f"downloading {len(scenes)} tiles x {len(BANDS)} bands ...")
    for i, scene in enumerate(scenes, 1):
        date = scene["datetime"][:10]
        scene_dir = RAW_DIR / scene["tile"] / date
        scene_dir.mkdir(parents=True, exist_ok=True)
        print(f"[{i}/{len(scenes)}] {scene['id']} ({scene['tile']}, {date})")
        prefix = bucket_prefix(scene)
        ok = True
        for band in BANDS:
            dest = scene_dir / f"{band}.jp2"
            if dest.exists() and dest.stat().st_size > 0:
                print(f"    {band}: already present")
                continue
            key = f"{prefix}R20m/{band}.jp2"
            try:
                s3.download_file(BUCKET, key, str(dest))
                print(f"    {band}: ok ({dest.stat().st_size / 1e6:.1f} MB)")
            except Exception as exc:  # noqa: BLE001
                print(f"    {band}: FAILED ({exc})")
                ok = False
        if ok:
            scene["local_path"] = str(scene_dir)
        else:
            print(f"    {scene['id']}: incomplete, removed from catalog")
    catalog = json.loads(CATALOG_PATH.read_text())
    catalog["scenes"] = [s for s in catalog["scenes"]
                         if (RAW_DIR / s["tile"] / s["datetime"][:10]).exists()]
    catalog["n_selected"] = len(catalog["scenes"])
    CATALOG_PATH.write_text(json.dumps(catalog, indent=2))
    print(f"catalog now has {len(catalog['scenes'])} complete scenes")


if __name__ == "__main__":
    main()
