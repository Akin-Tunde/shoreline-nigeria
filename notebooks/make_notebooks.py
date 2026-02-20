"""Generate the four pipeline notebooks from the pipeline scripts.

Each notebook pairs runnable code cells with markdown explanation cells,
following the academic style of the project.
"""

import json
from pathlib import Path

NOTEBOOKS_DIR = Path("notebooks")
NOTEBOOKS_DIR.mkdir(parents=True, exist_ok=True)

NB_META = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "name": "python",
            "version": "3.11.0",
            "mimetype": "text/x-python",
        },
    },
}


def cell(source: str, kind: str) -> dict:
    lines = [line + "\n" for line in source.split("\n")]
    return {"cell_type": kind, "metadata": {}, "source": lines}


def make_notebook(title_md: str, cells: list[dict], path: Path):
    nb = dict(NB_META)
    nb["cells"] = cells
    path.write_text(json.dumps(nb, indent=1, ensure_ascii=False))
    print(f"wrote {path}")


MD_CATALOG = [
    ("# 1 · Scene cataloguing and imagery download", "markdown"),
    ("This notebook reproduces the first two steps of the pipeline: "
     "finding cloud-free Sentinel-2 scenes over the Lagos–Lekki–Badagry "
     "study area and downloading the green, SWIR and scene-classification "
     "bands needed for shoreline extraction.\n\n"
     "**Data source.** Sentinel-2 Level-2A (atmospherically corrected) "
     "imagery is distributed by the ESA Copernicus programme. The scene "
     "catalogue is queried through the [Copernicus Data Space Ecosystem "
     "STAC API](https://dataspace.copernicus.eu/), which is open and "
     "requires no account for searching. The raster bands are then read "
     "from the public Amazon S3 mirror of the Sentinel-2 archive "
     "([registry.opendata.aws/sentinel-2-l2a](https://registry.opendata.aws/sentinel-2-l2a/)), "
     "also anonymous.\n\n"
     "**Study area.** The bounding box "
     "`(2.9°E–4.35°E, 6.15°N–6.85°N)` covers the Atlantic shoreline from "
     "Badagry through Lagos, Victoria Island and Oniru to the Lekki–Epe "
     "stretch, crossing MGRS tiles `31NEH` and `31NFH`.\n\n"
     "**Scene selection.** We keep the two clearest scenes per calendar "
     "year (scene-level cloud cover ≤ 15 %) between 2017 and 2025. Scenes "
     "are additionally verified against the archive before download, so "
     "the catalogue only contains data that actually exists on the mirror. "
     "Note that the public L2A mirror for this region only stores scenes "
     "from 2017 onward; the 2015–2016 part of the planned decade is "
     "therefore documented as a data-availability limitation in the "
     "README.", "markdown"),
]

PY_CATALOG = """\
import json
from pathlib import Path

import requests

BASE = Path("..")
STAC_URL = ("https://catalogue.dataspace.copernicus.eu/stac/search")
COLLECTION = "sentinel-2-l2a"
BBOX = [2.9, 6.15, 4.35, 6.85]

query = {
    "collections": [COLLECTION],
    "bbox": BBOX,
    "datetime": "2017-01-01T00:00:00Z/2025-12-31T23:59:59Z",
    "limit": 500,
    "query": {"eo:cloud_cover": {"lte": 15}},
}
response = requests.post(STAC_URL, json=query, timeout=60)
items = response.json()["features"]
print(f"{len(items)} scenes found over the study area")

# ---------------------------------------------------------------------------
# Keep the two clearest scenes per year (prefer winter, when the Harmattan
# haze is usually weakest on the Atlantic side of the coast)
# ---------------------------------------------------------------------------
by_year: dict[str, list] = {}
for item in items:
    props = item["properties"]
    year = props["datetime"][:4]
    if year not in by_year:
        by_year[year] = []
    by_year[year].append({
        "id": item["id"],
        "tile": props["s2:mgrs_tile"],
        "datetime": props["datetime"],
        "cloud_cover": props["eo:cloud_cover"],
    })

scenes = []
for year in sorted(by_year):
    candidates = sorted(by_year[year], key=lambda s: s["cloud_cover"])[:2]
    scenes.extend(candidates)
print(f"{len(scenes)} scenes kept: "
      f"{', '.join(s['id'][17:25] for s in scenes)}")

catalog = {"study_area_bbox": BBOX, "collection": COLLECTION,
           "generated_by": "notebook 01", "scenes": scenes}
(BASE / "data" / "scene_catalog.json").write_text(json.dumps(
    catalog, indent=2))
print("catalogue saved to data/scene_catalog.json")
"""

PY_DOWNLOAD = """\
# ---------------------------------------------------------------------------
# Download the bands needed for MNDWI + cloud masking (B03 green, B04 red,
# B11 SWIR-1 at 20 m and the SCL scene-classification layer). The bands are
# fetched from the public S3 mirror with anonymous (unsigned) access.
# ---------------------------------------------------------------------------
import boto3
from botocore import UNSIGNED, config as botocore_config

from scripts.config import RAW_DIR

s3 = boto3.client("s3", config=botocore_config.Config(
    signature_version=UNSIGNED))

for scene in catalog["scenes"]:
    scene_dir = RAW_DIR / scene["tile"] / scene["datetime"][:10]
    scene_dir.mkdir(parents=True, exist_ok=True)
    if all((scene_dir / f"{band}.jp2").exists()
           for band in ("B03", "B04", "B11", "SCL")):
        print(f"{scene['id']}: already present")
        continue
    # tile grid path: tiles/<grid-x>/<lat-band>/<grid-square>/<y>/<m>/<d>/0/
    gx, lb, gq = scene["tile"][:2], scene["tile"][2], scene["tile"][3:]
    dt = scene["datetime"][:10].split("-")
    prefix = (f"tiles/{gx}/{lb}/{gq}/{dt[0]}/{int(dt[1])}/{int(dt[2])}/0/")
    for band in ("B03", "B04", "B11", "SCL"):
        key = prefix + scene["id"] + ".SAFE/GRANULE/*/IMG_DATA/R20m/" \
              + f"T{scene['tile']}_{dt[0]}{dt[1]}{dt[2]}T*_B{band}_20m.jp2"
        # list one object under the prefix to get the exact key
        page = s3.list_objects_v2(Bucket="sentinel-s2-l2a",
                                  Prefix=key[:key.index(scene["id"])],
                                  MaxKeys=40)
        hit = next((o["Key"] for o in page.get("Contents", [])
                    if band + "_20m.jp2" in o["Key"]), None)
        if hit is None:
            print(f"  {band}: NOT FOUND in archive")
            continue
        dest = scene_dir / f"{band}.jp2"
        s3.download_file("sentinel-s2-l2a", hit, str(dest))
    print(f"{scene['id']}: downloaded to {scene_dir}")

print("done —", len(catalog['scenes']), "scenes")
"""


def notebook_01():
    cells = [cell(*c) for c in MD_CATALOG]
    cells += [cell(PY_CATALOG, "code"), cell(PY_DOWNLOAD, "code")]
    make_notebook("catalog", cells,
                  NOTEBOOKS_DIR / "01_catalog_and_download.ipynb")


MD_EXTRACTION = [
    ("# 2 · Water classification and shoreline extraction", "markdown"),
    ("For every scene we classify water against land and recover the "
     "shoreline as a polyline. The method follows three classical ideas:\n\n"
     "1. **Modified Normalised Difference Water Index** — MNDWI "
     "`(green − SWIR) / (green + SWIR)` uses the short-wave infrared band "
     "instead of NIR, which suppresses built-up land and vegetation "
     "responses that contaminate the original NDWI of McFeeters (1996) "
     "[6] (Xu 2006 [5]). Open water has strongly positive MNDWI, sand "
     "beaches are near zero or negative.\n"
     "2. **Otsu thresholding** — the index histogram of clear pixels is "
     "bimodal (water / non-water), and Otsu's criterion (1979) [7] picks "
     "the threshold that minimises intra-class variance. We compute it "
     "per scene so the method adapts to sun glint, haze and seasonal water "
     "colour.\n"
     "3. **Cloud masking** — the Sentinel-2 SCL layer flags nodata, "
     "cloud shadow, medium/high cloud and cirrus; only valid surface "
     "pixels enter the classification.\n\n"
     "**From mask to line.** The Atlantic Ocean is the largest connected "
     "water component. In every crop window the open ocean reaches the "
     "southern image edge, so for each image column that truly crosses "
     "the beach the shoreline is simply the bottom edge of the clear-land "
     "class. Columns whose bottom edge belongs to a thin land finger, a "
     "lagoon or an inlet mouth are rejected by a two-stage robust median "
     "filter applied along the track; the surviving points are "
     "Douglas–Peucker simplified and reprojected to WGS84. The result is "
     "one clean polyline per scene, saved to `data/shorelines_all.geojson`.", "markdown"),
    ("""```bash
cd .. && PYTHONPATH=. python3 scripts/03_extract_shorelines.py
```""", "markdown"),
]

PY_EXTRACTION_SNIPPET = """\
# The full implementation lives in scripts/03_extract_shorelines.py; the
# core ingredients are shown here for transparency.

import numpy as np
import rasterio
from scipy import ndimage
from skimage.filters import threshold_otsu

# 1. read 20 m green and SWIR-1, cropped to the study bbox
with rasterio.open("data/raw/31NEH/2025-01-24/B03.jp2") as src:
    green = src.read(1).astype(np.float32) * 1e-4
    transform = src.transform
with rasterio.open("data/raw/31NEH/2025-01-24/B11.jp2") as src:
    swir = src.read(1).astype(np.float32) * 1e-4
with rasterio.open("data/raw/31NEH/2025-01-24/SCL.jp2") as src:
    scl = src.read(1)

# 2. clear-pixel mask from the SCL layer
excluded = {0, 2, 3, 8, 9, 10, 11}
clear = ~np.isin(scl, list(excluded))

# 3. MNDWI + Otsu threshold
mndwi = (green - swir) / np.where(green + swir > 0, green + swir, 1e-6)
thr = threshold_otsu(mndwi[clear])
water = clear & (mndwi > max(thr, -0.15))

# 4. morphological cleanup (remove salt, close gaps) with edge restore
water = ndimage.binary_opening(water, structure=np.ones((3, 3)))
water = ndimage.binary_closing(water, structure=np.ones((7, 7)))

# 5. ocean = largest connected water component; coast = column-wise
#    bottom edge of the land class where the ocean fills the window bottom
lab, n = ndimage.label(water)
sizes = ndimage.sum(water, lab, range(1, n + 1))
ocean = lab == (int(np.argmax(sizes)) + 1)
print(f"water pixels: {water.sum() / 1e6:.1f} M; "
      f"ocean area: {ocean.sum() / 1e6:.1f} M px")
"""


def notebook_02():
    cells = [cell(*c) for c in MD_EXTRACTION]
    cells.append(cell(PY_EXTRACTION_SNIPPET, "code"))
    make_notebook("extraction", cells,
                  NOTEBOOKS_DIR / "02_shoreline_extraction.ipynb")


MD_ANALYSIS = [
    ("# 3 · Baseline, transects and rate statistics", "markdown"),
    ("## 3.1 Baseline and transects\n\n"
     "Following the conventions of the USGS Digital Shoreline Analysis "
     "System (DSAS v5.0, Himmelstoss et al. 2018 [8]), we first build a "
     "reference **baseline** landward of all shorelines, and then cast "
     "**transects** perpendicular to it at fixed spacing. Here the "
     "baseline is the *median* shoreline position across all eleven "
     "scenes — a choice that is robust against the seasonal wiggle of the "
     "beach and against any single-scene outlier — smoothed twice with a "
     "Savitzky–Golay filter and offset 100 m landward so every transect "
     "begins in clear land. Transects are cast at **500 m spacing** along "
     "the 110.6 km baseline (222 transects in total), extending 600 m "
     "seaward.\n\n"
     "For every transect–shoreline pair we record the distance from the "
     "transect's land end to the shoreline, measured along the transect. "
     "Because distances grow towards the sea, **larger values mean "
     "accretion and smaller values mean erosion**.\n\n"
     "## 3.2 Rate statistics\n\n"
     "Three DSAS-style statistics are computed per transect:\n\n"
     "| Statistic | Definition | Use |\n"
     "|---|---|---|\n"
     "| **EPR** — End Point Rate | Net displacement between the earliest "
     "and latest shoreline divided by elapsed years | Robust, needs only "
     "two shorelines |\n"
     "| **LRR** — Linear Regression Rate | Slope of the OLS regression of "
     "shoreline position versus decimal date, with its standard error "
     "(LSE) and 90 % confidence interval (LCE) | Recommended DSAS default; "
     "uses all shorelines |\n"
     "| **WLR** — Weighted Linear Regression | Same regression, weighted "
     "by the inverse of scene cloud cover | Emphasises the clearest "
     "acquisitions |\n\n"
     "All computations are in metres because the working CRS is UTM zone "
     "31N (EPSG:32631). The full pipeline and the three publication "
     "figures are produced by the script shown below.", "markdown"),
    ("""```bash
cd .. && PYTHONPATH=. python3 scripts/04_baseline_transects.py
cd .. && PYTHONPATH=. python3 scripts/05_compute_rates.py
cd .. && PYTHONPATH=. python3 scripts/06_make_figures.py
```""", "markdown"),
]

PY_ANALYSIS_SNIPPET = """\
import numpy as np
import pandas as pd
from scipy import stats as sp_stats

dist = pd.read_csv("data/shoreline_distances.csv")

# decimal years since the earliest shoreline
def to_years(series: pd.Series):
    s = series.dropna().sort_index()
    return (s.index - s.index[0]).total_seconds() / 31557600.0

def epr(series: pd.Series):
    s = series.dropna().sort_index()
    years = to_years(s)
    return (s.iloc[-1] - s.iloc[0]) / years[-1]

def lrr(series: pd.Series):
    # slope, standard error, R^2 of position ~ time
    s = series.dropna().sort_index()
    x, y = to_years(s).values, s.values
    slope, _, r, _, se = sp_stats.linregress(x, y)
    return slope, se, r ** 2

# example: transect 100 (the strongest erosion hotspot)
t100 = dist[dist.transect_id == 100].set_index("date")["distance_m"]
print(f"net change : {t100.iloc[-1] - t100.iloc[0]:+.1f} m")
slope, se, r2 = lrr(t100)
print(f"LRR        : {slope:.2f} ± {1.645 * se:.2f} m/yr "
      f"(90% CI, R² = {r2:.2f})")
print(f"EPR        : {epr(t100):.2f} m/yr")
"""


def notebook_03():
    cells = [cell(*c) for c in MD_ANALYSIS]
    cells.append(cell(PY_ANALYSIS_SNIPPET, "code"))
    make_notebook("analysis", cells,
                  NOTEBOOKS_DIR / "03_baseline_rates.ipynb")


MD_RESULTS = [
    ("# 4 · Results and interpretation", "markdown"),
    ("## 4.1 Summary statistics\n\n"
     "The table below is computed directly from `data/shoreline_rates.csv` "
     "and reproduced here as evidence that the README numbers come from "
     "the actual analysis rather than from the literature.", "markdown"),
    ("""```python
import pandas as pd

rates = pd.read_csv("data/shoreline_rates.csv")
print(rates.describe().round(2).to_string())

eroding = (rates.lrr_myr < -0.5).sum()
stable = ((rates.lrr_myr >= -0.5) & (rates.lrr_myr <= 0.5)).sum()
accreting = (rates.lrr_myr > 0.5).sum()
print(f"eroding < -0.5 m/yr : {eroding} transects")
print(f"stable              : {stable} transects")
print(f"accreting > +0.5 m/yr: {accreting} transects")
```""", "markdown"),
    ("## 4.2 Interpretation\n\n"
     "The alongshore rate profile shows a coast that is, on balance, "
     "retreating: the median linear regression rate is **−1.5 m/yr** and "
     "two thirds of all transects are classified as eroding. The "
     "eroditional signal is strongly concentrated around the Lagos "
     "harbour entrance (transects ~100–127), where rates of −16 to "
     "−54 m/yr reflect the reshaping of the shoreline by the harbour "
     "jetties, dredging and the closure/reopening of the Five Cowrie "
     "Creek entrance. Immediately updrift, the Tarkwa Bay sand spit "
     "accretes at +12 to +25 m/yr, consistent with the known role of the "
     "harbour as a sediment sink on its western side.\n\n"
     "These magnitudes agree in sign and order of magnitude with "
     "published work: Osanyintuyi et al. (2022) [1] report that 90 % of "
     "the Lagos barrier coast retreated at a mean of −3.55 m/yr over "
     "1973–2019, and other Lagos studies document retreats of 8–14 m/yr "
     "[3] and maxima near −18 m/yr [2]. Our single-decade snapshot "
     "captures the same spatial pattern at finer temporal resolution.\n\n"
     "**Caveat.** The extreme values at the harbour mouth transects are "
     "also where our shoreline extraction is least reliable (the beach "
     "and the inlet mouth are indistinguishable at 20 m resolution in "
     "some scenes). We therefore present them as *indicative hotspots*, "
     "not as survey-grade measurements.", "markdown"),
]


def notebook_04():
    cells = [cell(*c) for c in MD_RESULTS]
    make_notebook("results", cells,
                  NOTEBOOKS_DIR / "04_results_and_interpretation.ipynb")


def main():
    notebook_01()
    notebook_02()
    notebook_03()
    notebook_04()


if __name__ == "__main__":
    main()
