"""Step 4 — Build a smoothed DSAS-style baseline and perpendicular
transects, then intersect every extracted shoreline with the transects.

Baseline
--------
Following DSAS conventions, the baseline is a smoothed reference line
placed landward of the shorelines. Here it is derived from the *median*
shoreline across all scenes (the median position is robust against the
seasonal wiggle of the beach and any single-scene outlier), smoothed with
a moving-average window, and offset 100 m landward (north) so that all
transects start in clear land.

Transects
---------
Transects are cast perpendicular to the smoothed baseline at 500 m
spacing along its length, extending 600 m seaward. For each
transect-shoreline pair we record the signed distance from the baseline
(negative = seaward of baseline). These distances become the time series
fed to the rate statistics in step 5.
"""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.signal import savgol_filter
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points

import config as cfg
from config import DATA_DIR

TO_4326 = Transformer.from_crs("EPSG:32631", "EPSG:4326", always_xy=True)
TO_32631 = Transformer.from_crs("EPSG:4326", "EPSG:32631", always_xy=True)

TRANSECT_SPACING = 500.0   # metres along the baseline
TRANSECT_LENGTH = 600.0    # metres seaward
BASELINE_OFFSET = 100.0    # metres landward of the median shoreline


def load_shorelines() -> gpd.GeoDataFrame:
    gdf = gpd.read_file(DATA_DIR / "shorelines_all.geojson")
    gdf["date"] = pd.to_datetime(gdf["date"])
    return gdf.sort_values("date").reset_index(drop=True)


def to_projected(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Work in UTM 31N so that all distances are in metres."""
    return gdf.to_crs("EPSG:32631").reset_index(drop=True)


def median_shoreline(gdf: gpd.GeoDataFrame, n: int = 500) -> LineString:
    """Robust median shoreline: resample every line to `n` points spaced
    along-track (nearest-point matching to the longest line), then take
    the median coordinate at each sample index."""
    lines = [l for l in gdf.geometry]
    lengths = np.array([l.length for l in lines])
    ref = lines[int(np.argmax(lengths))]
    # sample parameter along the reference line
    dists = np.linspace(0, ref.length, n)
    samples = []
    for d in dists:
        coords = [nearest_points(ref.interpolate(d), l)[1].coords[0]
                  for l in lines]
        samples.append(np.median(coords, axis=0))
    return LineString(samples)


def smooth(line: LineString, window: int = 31) -> LineString:
    xs = np.array([c[0] for c in line.coords])
    ys = np.array([c[1] for c in line.coords])
    # Savitzky-Golay needs window <= series length and odd
    w = min(window, (len(xs) // 2) * 2 - 1)
    if w < 3:
        return line
    xs = savgol_filter(xs, w, 3)
    ys = savgol_filter(ys, w, 3)
    return LineString(zip(xs, ys))


def transects_from_baseline(baseline: LineString) -> list:
    """Cast perpendicular transects at fixed spacing along the baseline.

    For each cast point, the transect direction is the normal to the
    baseline segment. One end is landward (offset into the continent),
    the other seaward.
    """
    segs = list(map(LineString,
                    zip(baseline.coords[:-1], baseline.coords[1:])))
    seg_len = np.array([s.length for s in segs])
    cum = np.concatenate([[0], np.cumsum(seg_len)])
    n = int(np.floor(baseline.length / TRANSECT_SPACING)) + 1
    casts = []
    for i in range(n):
        d = i * TRANSECT_SPACING
        j = int(np.searchsorted(cum, d, side="right") - 1)
        j = min(j, len(segs) - 1)
        s = segs[j]
        local_d = d - cum[j]
        t = min(max(local_d / s.length, 0.0), 1.0)
        pt = s.interpolate(t, normalized=True)
        (x0, y0), (x1, y1) = s.coords
        dx, dy = (x1 - x0), (y1 - y0)
        L = np.hypot(dx, dy) or 1.0
        # normal pointing south (seaward; the ocean is south of the coast)
        nx, ny = -(y1 - y0) / L, (x1 - x0) / L
        if ny > 0:  # ensure seaward = negative-y direction
            nx, ny = -nx, -ny
        sea = Point(pt.x + nx * TRANSECT_LENGTH, pt.y + ny * TRANSECT_LENGTH)
        land = Point(pt.x - nx * BASELINE_OFFSET, pt.y - ny * BASELINE_OFFSET)
        casts.append((i, LineString([land, sea]), pt))
    return casts


def signed_distance(transect: LineString, shoreline: LineString) -> float:
    """Signed distance from the transect's land end to the shoreline,
    measured along the transect. Negative = shoreline is seaward of the
    baseline (erosion direction). NaN if the line misses the transect."""
    hits = shoreline.intersection(transect)
    if hits.is_empty:
        return np.nan
    pts = []
    if hits.geom_type == "Point":
        pts = [hits]
    elif hits.geom_type == "MultiPoint":
        pts = list(hits.geoms)
    else:  # LineString: shoreline crossed the whole transect — take ends
        pts = [Point(hits.coords[0]), Point(hits.coords[-1])]
    d = [np.hypot(p.x - transect.coords[0][0],
                  p.y - transect.coords[0][1]) for p in pts]
    sea_d = np.hypot(transect.coords[-1][0] - transect.coords[0][0],
                     transect.coords[-1][1] - transect.coords[0][1])
    # signed: positive landward, negative seaward; nearest hit
    return float(min(d) - sea_d + (sea_d - np.mean(d)) if len(d) == 1
                 else min(d) - sea_d + 0.0)


def distance_from_land_end(transect: LineString,
                           shoreline: LineString) -> float:
    """Distance along the transect from its LAND end to the shoreline.
    Larger = more accreted (further seaward of baseline)."""
    hits = shoreline.intersection(transect)
    if hits.is_empty:
        return np.nan
    pts = []
    if hits.geom_type == "Point":
        pts = [hits]
    elif hits.geom_type == "MultiPoint":
        pts = list(hits.geoms)
    else:
        pts = [Point(hits.coords[0]), Point(hits.coords[-1])]
    # take the hit closest to the land end, preferring the outermost
    # (seaward-most) crossing if the line loops
    ds = [np.hypot(p.x - transect.coords[0][0],
                   p.y - transect.coords[0][1]) for p in pts]
    return float(np.median(ds))


def main():
    gdf = load_shorelines()
    proj = to_projected(gdf)

    med = median_shoreline(proj)
    base = smooth(med)
    base = smooth(base)  # double pass for a very smooth reference
    base_wgs = LineString([TO_4326.transform(*c) for c in base.coords])

    casts = transects_from_baseline(base)
    rows = []
    for idx, tr_line, anchor in casts:
        land_end = tr_line.coords[0]
        for _, row in proj.iterrows():
            d = distance_from_land_end(tr_line, row.geometry)
            rows.append({"transect_id": idx,
                         "date": row["date"].strftime("%Y-%m-%d"),
                         "scene_id": row["scene_id"],
                         "distance_m": d})
    df = pd.DataFrame(rows)

    # pivot to a wide time-series table
    wide = df.pivot(index="transect_id", columns="date",
                    values="distance_m").reset_index()

    geo_rows = []
    for idx, tr_line, anchor in casts:
        geo_rows.append({
            "geometry": tr_line,
            "transect_id": idx,
            "anchor_lon": TO_4326.transform(*anchor.coords[0])[0],
            "anchor_lat": TO_4326.transform(*anchor.coords[0])[1],
        })
    tr_gdf = gpd.GeoDataFrame(geo_rows, crs="EPSG:32631").to_crs("EPSG:4326")

    base_gdf = gpd.GeoDataFrame({"geometry": [base_wgs],
                                 "name": ["smoothed_baseline"]},
                                crs="EPSG:4326")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tr_gdf.to_file(DATA_DIR / "transects.geojson", driver="GeoJSON")
    base_gdf.to_file(DATA_DIR / "baseline.geojson", driver="GeoJSON")
    df.to_csv(DATA_DIR / "shoreline_distances.csv", index=False)
    wide.to_csv(DATA_DIR / "shoreline_distances_wide.csv", index=False)
    print(f"baseline length: {base.length / 1000:.1f} km")
    print(f"transects: {len(tr_gdf)} at {TRANSECT_SPACING:g} m spacing")
    print(f"distance table: {len(df)} transect-date pairs; "
          f"coverage {df.notna().sum().sum() / df.size * 100:.0f}%")


if __name__ == "__main__":
    main()
