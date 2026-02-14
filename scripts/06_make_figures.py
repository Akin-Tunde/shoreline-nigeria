"""Step 6 — Publication-quality figures.

Three figures:

1. `multiyear_shorelines_map.png` — all extracted shorelines on a
   satellite basemap with the baseline and transects.
2. `erosion_rates_chart.png` — LRR rate (m/yr) along the coast vs
   alongshore distance, with 90% confidence envelopes and city labels.
3. `hotspot_map.png` — choropleth of the net shoreline movement along
   transects with the strongest erosion/accretion hotspots marked.
"""

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd
import contextily as ctx

from config import DATA_DIR, FIGURES_DIR

FIG_DIR = FIGURES_DIR

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.labelsize": 11,
    "axes.titlesize": 13,
    "figure.dpi": 150,
})


def load():
    rates = pd.read_csv(DATA_DIR / "shoreline_rates.csv")
    trs = gpd.read_file(DATA_DIR / "transects.geojson")
    base = gpd.read_file(DATA_DIR / "baseline.geojson")
    shores = gpd.read_file(DATA_DIR / "shorelines_all.geojson")
    shores["date"] = pd.to_datetime(shores["date"])
    rates = rates.merge(
        trs[["transect_id", "anchor_lon", "anchor_lat"]],
        on="transect_id", how="left")
    # alongshore distance from the westernmost transect
    rates["alongshore_km"] = (rates["transect_id"] * 0.5)
    return rates, trs, base, shores


def figure_1(shores, base, trs):
    fig, ax = plt.subplots(figsize=(16, 6.2))
    cmap = plt.get_cmap("viridis", len(shores))
    for (date, g), color in zip(shores.groupby("date", sort=True),
                                cmap.colors):
        g.plot(ax=ax, color=color, linewidth=2.0,
               label=date.strftime("%d %b %Y"))
    base.plot(ax=ax, color="black", linewidth=2.2, zorder=5,
              label="Smoothed baseline")
    trs.plot(ax=ax, color="#e63946", linewidth=0.5, alpha=0.55, zorder=4)
    ax.set_title("Shoreline positions 2017–2025, Lagos–Lekki–Badagry "
                 "coast, Nigeria (Sentinel-2 L2A)", pad=12)
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles[::-1], labels[::-1], loc="lower left",
              title="Acquisition date", fontsize=9, title_fontsize=10)
    ax.set_xlabel("Longitude (°E)")
    ax.set_ylabel("Latitude (°N)")
    ctx.add_basemap(ax, source=ctx.providers.Esri.WorldImagery,
                    crs="EPSG:4326", zoom=12)
    plt.tight_layout()
    plt.savefig(FIG_DIR / "multiyear_shorelines_map.png", dpi=150)
    plt.close(fig)
    print("figure 1 saved")


def figure_2(rates):
    fig, ax = plt.subplots(figsize=(14, 6))
    r = rates.sort_values("alongshore_km")
    y = r["lrr_myr"]
    lo = y - 1.645 * r["lrr_se_myr"]
    hi = y + 1.645 * r["lrr_se_myr"]
    ax.fill_between(r["alongshore_km"], lo, hi, color="#e63946",
                    alpha=0.18, label="90% confidence interval")
    ax.plot(r["alongshore_km"], y, color="#b71c1c", linewidth=1.8,
            label="Linear regression rate (LRR)")
    # 25-transect rolling median (12.5 km window)
    med = r["lrr_myr"].rolling(25, center=True, min_periods=5).median()
    ax.plot(r["alongshore_km"], med, color="#1d3557", linewidth=2.4,
            linestyle="--", label="12.5 km rolling median")
    ax.axhline(0, color="gray", linewidth=0.9)
    ax.fill_between(r["alongshore_km"], -0.5, 0.5, color="gray",
                    alpha=0.08)
    # city labels (approximate alongshore positions)
    cities = [(2.0, "Badagry"), (18.0, "Tarkwa Bay"), (32.0, "Lagos / "
               "Victoria Island"), (58.0, "Lekki"), (80.0, "Epe")]
    for x, name in cities:
        ax.annotate(name, xy=(x, ax.get_ylim()[1] * 0.65 if False
                              else -5), xytext=(x, 22),
                    ha="center", fontsize=10, color="#333333",
                    arrowprops=dict(arrowstyle="-", color="#999999",
                                    lw=0.8))
    ax.set_xlabel("Alongshore distance from west end of study area (km)")
    ax.set_ylabel("Shoreline change rate (m/yr, negative = erosion)")
    ax.set_title("Shoreline change rate along the Lagos–Lekki–Badagry "
                 "coast, 2017–2025")
    ax.legend(loc="upper right", fontsize=10)
    plt.tight_layout()
    plt.savefig(FIG_DIR / "erosion_rates_chart.png", dpi=150)
    plt.close(fig)
    print("figure 2 saved")


def figure_3(rates):
    trs = gpd.read_file(DATA_DIR / "transects.geojson")
    trs["transect_id"] = trs["transect_id"].astype(int)
    rates = rates.drop(columns=[c for c in ("anchor_lon", "anchor_lat")
                                if c in rates.columns], errors="ignore")
    geo = trs[["transect_id", "anchor_lon", "anchor_lat"]]
    rates = rates.merge(geo, on="transect_id", how="left")
    merged = trs.drop(columns=["anchor_lon", "anchor_lat"]).merge(
        rates.set_index("transect_id"), left_on="transect_id",
        right_index=True, how="left")
    vmin, vmax = -20, 20
    fig, ax = plt.subplots(figsize=(16, 9))
    merged.plot(ax=ax, column="net_change_m", cmap="RdYlGn",
                vmin=vmin, vmax=vmax, linewidth=1.6,
                legend=True,
                legend_kwds={"label": "Net shoreline movement 2017–2025\n"
                                      "(m, negative = retreat)",
                             "shrink": 0.55})
    # hotspots: strongest erosion / accretion among well-sampled transects,
    # keeping only geographically distinct ones (>= 0.06° apart)
    erode = rates.nsmallest(6, "lrr_myr")
    accrete = rates.nlargest(6, "lrr_myr")

    def distinct(frames):
        kept, prev = [], None
        for _, h in frames.iterrows():
            if prev is None or abs(h["anchor_lon"] - prev) >= 0.06:
                kept.append(h)
                prev = h["anchor_lon"]
            if len(kept) == 3:
                break
        return kept

    erode_h, accrete_h = distinct(erode), distinct(accrete)
    labels = []
    for h in erode_h:
        labels.append((h["anchor_lon"], -0.02, "below"))
    for h in accrete_h:
        labels.append((h["anchor_lon"], 0.02, "above"))
    labels.sort(key=lambda t: t[0])
    er_idx = 0
    for h in erode_h:
        ax.plot(h["anchor_lon"], h["anchor_lat"], marker="o",
                markersize=10, markeredgecolor="black", markerfacecolor="none",
                markeredgewidth=1.8, zorder=6)
        ax.annotate(f"{h['lrr_myr']:.0f} m/yr",
                    xy=(h["anchor_lon"], h["anchor_lat"]),
                    xytext=(h["anchor_lon"], h["anchor_lat"] - 0.035),
                    ha="center", fontsize=9, color="#8b0000",
                    fontweight="bold")
    for h in accrete_h:
        ax.plot(h["anchor_lon"], h["anchor_lat"], marker="s",
                markersize=9, markeredgecolor="black", markerfacecolor="none",
                markeredgewidth=1.8, zorder=6)
        ax.annotate(f"+{h['lrr_myr']:.0f} m/yr",
                    xy=(h["anchor_lon"], h["anchor_lat"]),
                    xytext=(h["anchor_lon"], h["anchor_lat"] + 0.035),
                    ha="center", fontsize=9, color="#006400",
                    fontweight="bold")
    ax.set_title("Erosion and accretion hotspots, Lagos–Lekki–Badagry "
                 "coast, 2017–2025")
    ax.set_xlabel("Longitude (°E)")
    ax.set_ylabel("Latitude (°N)")
    ctx.add_basemap(ax, source=ctx.providers.Esri.WorldImagery,
                    crs="EPSG:4326", zoom=12)
    plt.tight_layout()
    plt.savefig(FIG_DIR / "hotspot_map.png", dpi=150)
    plt.close(fig)
    print("figure 3 saved")


def main():
    rates, trs, base, shores = load()
    figure_1(shores, base, trs)
    figure_2(rates)
    figure_3(rates)
    print("all figures saved to", FIG_DIR)


if __name__ == "__main__":
    main()
