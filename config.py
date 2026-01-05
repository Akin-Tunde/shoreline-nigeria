"""Central configuration for the shoreline-nigeria study.

All paths, parameters, and geographic settings live here so that extending the
analysis to more years or a different coast segment is a config change only.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.resolve()
RAW_DIR = ROOT / "raw"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
FIGURES_DIR = ROOT / "figures"
CATALOG_PATH = DATA_DIR / "scene_catalog.json"
RATES_CSV = DATA_DIR / "shoreline_rates.csv"

for d in (RAW_DIR, DATA_DIR, OUTPUT_DIR, FIGURES_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Study area (Lagos–Lekki–Badagry coastal stretch, Nigeria)
# ---------------------------------------------------------------------------
BBOX = (2.9, 6.15, 4.35, 6.85)  # (minx, miny, maxx, maxy) in WGS84

# Fallback scene list in case the STAC catalog must be regenerated
START_DATE = "2015-01-01"
END_DATE = "2025-12-31"
MAX_CLOUD_COVER = 15.0  # % over full scene

# ---------------------------------------------------------------------------
# Imagery processing
# ---------------------------------------------------------------------------
LANDSAT_RESOLUTION = 30.0  # m (green/red/NIR surface-reflectance bands)

# NDWI (McFeeters 1996) and MNDWI (Xu 2006) use L2 surface reflectance (0-1)
GREEN_BAND = "green"
RED_BAND = "red"
BLUE_BAND = "blue"
NIR_BAND = "SR_B5"  # Landsat-8/9 OLI band 5 (865 nm)

NDWI_THRESHOLD_METHOD = "otsu"  # Otsu global threshold on index histogram
CLEAR_PIXEL_CLOUD_BITS = [3, 4, 5]  # QA_PIXEL bits: cloud, cloud shadow, cirrus

# ---------------------------------------------------------------------------
# Morphology cleanup (pixels)
# ---------------------------------------------------------------------------
MORPH_OPEN_KERNEL = 3  # remove thin spurious water fingers
MORPH_CLOSE_KERNEL = 5  # close small gaps in the water mask

# ---------------------------------------------------------------------------
# Transect setup
# ---------------------------------------------------------------------------
TRANSECT_SPACING = 500.0  # m along the baseline
N_TRANSECTS = 50  # target; actual number computed from baseline length
TRANSECT_LENGTH = 3000.0  # m seaward/landward reach from baseline

# ---------------------------------------------------------------------------
# Rate computation
# ---------------------------------------------------------------------------
MIN_VALID_SHORELINES = 4  # minimum scenes required for LRR at a transect
EROSION_THRESHOLD = -1.0  # m/yr below this -> eroding
ACCRETION_THRESHOLD = 1.0  # m/yr above this -> accreting
# (between the two thresholds the transect is classified as stable)

# ---------------------------------------------------------------------------
# Figure style
# ---------------------------------------------------------------------------
DPI = 300
FIGURE_STYLE = {
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.labelsize": 11,
    "axes.titlesize": 12,
    "figure.dpi": DPI,
    "savefig.dpi": DPI,
    "savefig.bbox": "tight",
    "axes.grid": False,
}
