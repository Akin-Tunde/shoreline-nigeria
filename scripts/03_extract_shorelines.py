"""Step 3 — Extract shoreline polylines from each scene.

For every downloaded scene:

1. Read green (B03), SWIR (B11) at 20 m and the SCL mask, cropped to the
   study-area bounding box.
2. Build the clear-pixel mask from SCL (valid surface pixels only).
3. Compute MNDWI and classify water with Otsu (Xu 2006; Otsu 1979).
4. Morphological open/close cleanup, restoring pixels at the image edges
   that the opening operator would otherwise erase.
5. The Atlantic Ocean is the LARGEST connected water component. Because
   the open ocean fills the southern edge of every crop window, the
   coastline is recovered column by column: for each column whose bottom
   pixel is ocean, the shoreline is the southernmost clear-land pixel.
6. Outlier columns (lagoon edges, thin land fingers) are rejected with a
   median filter along-track; the line is smoothed with Douglas-Peucker
   and reprojected to WGS84.
"""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from scipy import ndimage
from skimage.filters import threshold_otsu
from shapely.geometry import LineString

import config as cfg
from config import CATALOG_PATH, DATA_DIR, RAW_DIR

STUDY_BBOX = cfg.BBOX  # (minx, miny, maxx, maxy) in EPSG:4326
BORDER_MARGIN = 4      # pixels whose classification is restored after
                       # morphological opening (opening erodes edges)


def crop_window(transform, bbox, height, width):
    """Rasterio window = intersection of the study bbox and the tile
    extent, so tiles only partially covering the bbox still work."""
    from rasterio.windows import from_bounds
    tr = Transformer.from_crs("EPSG:4326", "EPSG:32631", always_xy=True)
    minx, miny, maxx, maxy = bbox
    x0, y0 = tr.transform(minx, miny)
    x1, y1 = tr.transform(maxx, maxy)
    lo_x, hi_x = min(x0, x1), max(x0, x1)
    lo_y, hi_y = min(y0, y1), max(y0, y1)
    # tile extent in projected coordinates
    tx0, ty0 = transform * (0, 0)
    tx1, ty1 = transform * (width, height)
    lo_x = max(lo_x, min(tx0, tx1))
    hi_x = min(hi_x, max(tx0, tx1))
    lo_y = max(lo_y, min(ty0, ty1))
    hi_y = min(hi_y, max(ty0, ty1))
    return from_bounds(lo_x, lo_y, hi_x, hi_y, transform=transform)


def read_scene(scene: dict) -> dict:
    """Read bands cropped to the study area."""
    scene_dir = RAW_DIR / scene["tile"] / scene["datetime"][:10]
    with rasterio.open(scene_dir / "B03.jp2") as src:
        win = crop_window(src.transform, STUDY_BBOX, src.height, src.width)
        green = src.read(1, window=win).astype(np.float32) * 1e-4
        transform = src.window_transform(win)
    with rasterio.open(scene_dir / "B11.jp2") as src:
        swir = src.read(1, window=win).astype(np.float32) * 1e-4
    with rasterio.open(scene_dir / "SCL.jp2") as src:
        scl = src.read(1, window=win)
    return {"green": green, "swir": swir, "scl": scl,
            "transform": transform}


def clear_mask(scl: np.ndarray) -> np.ndarray:
    """True where the pixel is a valid clear-surface pixel.

    SCL classes: 0=nodata, 2=dark area, 3=cloud shadow, 8=cloud medium,
    9=cloud high, 10=cirrus, 11=snow — all excluded.
    """
    excluded = {0, 2, 3, 8, 9, 10, 11}
    return ~np.isin(scl, list(excluded))


def classify_water(green: np.ndarray, swir: np.ndarray,
                   scl: np.ndarray):
    """Binary water mask via Otsu on MNDWI over clear pixels.

    Returns (water, clear). `thr` is also returned so the cleanup step
    can restore border pixels consistently.
    """
    clear = clear_mask(scl)
    mndwi = (green - swir) / np.where(green + swir > 0, green + swir, 1e-6)
    valid = clear & np.isfinite(mndwi)
    idx = mndwi[valid]
    if idx.size < 1000:
        return np.zeros(mndwi.shape, dtype=bool), clear, 0.0
    try:
        thr = threshold_otsu(idx)
    except ValueError:
        thr = 0.0
    thr = max(thr, -0.15)  # guard against degenerate histograms
    water = clear & (mndwi > thr)
    return water, clear, thr


def cleanup(water: np.ndarray, clear: np.ndarray,
            mndwi: np.ndarray, thr: float) -> np.ndarray:
    """Morphological open/close, restoring the window-border pixels."""
    water = ndimage.binary_opening(water, structure=np.ones((3, 3)))
    water = ndimage.binary_closing(water, structure=np.ones((7, 7)))
    h, w = water.shape
    border = np.zeros((h, w), dtype=bool)
    border[:BORDER_MARGIN, :] = True
    border[-BORDER_MARGIN:, :] = True
    border[:, :BORDER_MARGIN] = True
    border[:, -BORDER_MARGIN:] = True
    water = water | (clear & (mndwi > max(thr, -0.15)) & border)
    return water


def coastal_line(water: np.ndarray, clear: np.ndarray,
                 transform) -> LineString | None:
    """Column-wise coastline of the largest (ocean) water component.

    The open ocean reaches the southern image edge in every column that
    crosses the beach, so for those columns the shoreline is simply the
    bottom edge of the clear-land class. Smooth along-track with a median
    filter and reject outlier columns (lagoon edges).
    """
    lab, n = ndimage.label(water)
    if n == 0:
        return None
    sizes = ndimage.sum(water, lab, range(1, n + 1))
    ocean = lab == (int(np.argmax(sizes)) + 1)
    h, w = ocean.shape

    # the open ocean fills the bottom edge of the window; require the
    # bottom 15 rows to be ocean so that shallow loops / inlet mouths
    # (where land re-appears at the window edge) are excluded
    bottom_ocean = ocean[-15:, :].all(axis=0)
    land = clear & ~ocean
    coast_row = np.full(w, np.nan)
    for c in range(w):
        if not bottom_ocean[c]:
            continue
        rows = np.where(land[:, c])[0]
        if rows.size == 0:
            continue
        coast_row[c] = rows.max() + 0.5

    valid = ~np.isnan(coast_row)
    if valid.sum() < 100:
        return None
    fill = pd.Series(coast_row).interpolate(method="linear",
                                            limit_direction="both").values
    smoothed = ndimage.median_filter(fill, size=201)
    # reject columns whose raw coast row deviates strongly from the
    # smoothed track (thin land fingers / lagoon-edge artefacts)
    keep = valid & (np.abs(fill - smoothed) < 300)
    # reject columns whose smoothed track deviates from the dominant
    # coastal latitude (drops ocean-side loops where the extraction
    # jumps far south of the beach)
    # iterative robust median: reject outliers from the band using a
    # median recomputed from survivors, so a large ocean-side loop
    # cannot bias the reference latitude
    ref = np.nanmedian(smoothed)
    for _ in range(5):
        keep = valid & (np.abs(fill - smoothed) < 300) & \
               (np.abs(smoothed - ref) < 400)
        if keep.sum() < 100:
            return None
        ref = np.nanmedian(smoothed[keep])
    if keep.sum() < 100:
        return None

    a, e, c, f = transform.a, transform.e, transform.c, transform.f
    xs = c + (np.arange(w) + 0.5) * a
    ys = f + smoothed * e  # e < 0 for north-up rasters
    pts = [(xs[i], ys[i]) for i in range(w) if keep[i]]
    line = LineString(pts).simplify(30.0, preserve_topology=True)
    if line.length < 5000:
        return None
    return line


def reproject_line(line: LineString) -> LineString:
    tr = Transformer.from_crs("EPSG:32631", "EPSG:4326", always_xy=True)
    return LineString([tr.transform(x, y) for x, y in line.coords])


def main():
    catalog = json.loads(CATALOG_PATH.read_text())
    gdf_rows = []
    for i, scene in enumerate(catalog["scenes"], 1):
        print(f"[{i}/{len(catalog['scenes'])}] {scene['id']}")
        data = read_scene(scene)
        mndwi = (data["green"] - data["swir"]) / np.where(
            data["green"] + data["swir"] > 0,
            data["green"] + data["swir"], 1e-6)
        water, clear, thr = classify_water(data["green"], data["swir"],
                                           data["scl"])
        water = cleanup(water, clear, mndwi, thr)
        line = coastal_line(water, clear, data["transform"])
        if line is None:
            print("    no shoreline extracted — skipping")
            continue
        line4326 = reproject_line(line)
        date = scene["datetime"][:10]
        gdf_rows.append({"geometry": line4326, "date": date,
                         "scene_id": scene["id"], "tile": scene["tile"],
                         "cloud_cover": scene["cloud_cover"]})
        out = DATA_DIR / "shorelines"
        out.mkdir(exist_ok=True)
        gpd.GeoDataFrame(gdf_rows[-1:], crs="EPSG:4326").to_file(
            out / f"shoreline_{date}.geojson", driver="GeoJSON")
        print(f"    coastline: {line4326.length * 111.32:.0f} km "
              f"({water.sum() / 1e6:.2f} M water px, "
              f"clear {clear.sum() / 1e6:.1f} M px)")

    summary = gpd.GeoDataFrame(gdf_rows, crs="EPSG:4326")
    summary.to_file(DATA_DIR / "shorelines_all.geojson", driver="GeoJSON")
    print(f"\nsaved {len(summary)} shorelines to data/shorelines_all.geojson")


if __name__ == "__main__":
    main()
