"""Step 5 — Shoreline change rate statistics per transect.

Statistics follow the USGS DSAS definitions (Himmelstoss et al. 2018):

- **EPR** — End Point Rate: distance between the earliest and latest
  shoreline, divided by the elapsed time (m/yr).
- **LRR** — Linear Regression Rate: slope of the ordinary-least-squares
  regression of shoreline position versus time, with the standard error
  (LSE) and 90% confidence interval (LCE).
- **WLR** — Weighted Linear Regression rate, weighting each point by
  the inverse of its positional uncertainty; since all shorelines come
  from the same sensor and resolution, we weight by scene quality
  (inverse cloud cover) as a stand-in.

Distances are measured from the transect's land end, so *larger* values
mean the shoreline sits further seaward (accretion) and *smaller* values
mean erosion. Rates are therefore signed: **negative = erosion**.
"""

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

import config as cfg
from config import DATA_DIR

POS_UNCERTAINTY = 30.0  # m — combined geolocation + extraction uncertainty


def epr(series: pd.Series) -> float:
    s = series.dropna().sort_index()
    if len(s) < 2:
        return np.nan
    years = (s.index - s.index[0]).total_seconds() / 31557600.0
    return (s.iloc[-1] - s.iloc[0]) / years[-1]


def lrr(series: pd.Series):
    """Return (slope, standard_error_slope, r_squared)."""
    s = series.dropna().sort_index()
    if len(s) < 3:
        return np.nan, np.nan, np.nan
    x = (s.index - s.index[0]).total_seconds() / 31557600.0
    y = s.values
    slope, intercept, r, p, se = sp_stats.linregress(x, y)
    return slope, se, r ** 2


def wlr(series: pd.Series, weights: pd.Series):
    """Weighted linear regression; returns (slope, se_slope, r2)."""
    s = series.dropna().sort_index()
    w = weights.loc[s.index].dropna()
    common = s.index.intersection(w.index)
    if len(common) < 3:
        return np.nan, np.nan, np.nan
    x = (s.index - s.index[0]).total_seconds() / 31557600.0
    y = s.values
    ww = w.values
    X = np.column_stack([x, np.ones_like(x)])
    XtW = X.T @ np.diag(ww)
    cov = np.linalg.inv(XtW @ X)
    beta = cov @ XtW @ y
    resid = y - X @ beta
    chi2 = (ww * resid ** 2).sum()
    dof = len(common) - 2
    if dof < 1:
        return beta[0], np.nan, np.nan
    s2 = chi2 / dof
    slope, se = beta[0], np.sqrt(s2 * cov[0, 0])
    ss_tot = (ww * (y - np.average(y, weights=ww)) ** 2).sum()
    ss_res = (ww * resid ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    return slope, se, r2


def main():
    dist = pd.read_csv(DATA_DIR / "shoreline_distances.csv")
    cloud = {
        "2017-05-21": 3.8, "2018-01-01": 0.0, "2018-01-06": 0.0,
        "2019-01-06": 0.0, "2020-01-26": 1.3, "2021-01-20": 4.4,
        "2021-12-21": 5.2, "2022-12-26": 0.0, "2023-01-10": 0.0,
        "2024-12-20": 0.0, "2025-01-24": 11.3,
    }
    # weight = 1 / (cloud cover + 1) so near-clear scenes dominate slightly
    weight = pd.Series({pd.to_datetime(d): 1.0 / (c + 1.0)
                        for d, c in cloud.items()})

    wide = pd.read_csv(DATA_DIR / "shoreline_distances_wide.csv")
    if "transect_id" not in wide.columns:
        wide = wide.rename_axis("transect_id").reset_index()
    date_cols = [c for c in wide.columns if c != "transect_id"]
    rows = []
    for _, r in wide.iterrows():
        tid = r["transect_id"]
        dates = pd.to_datetime(date_cols)
        vals = r[date_cols].values.astype(float)
        mask = ~np.isnan(vals)
        if mask.sum() < 2:
            continue
        s = pd.Series(vals[mask], index=dates[mask], name=tid)
        ep = epr(s)
        slope, se, r2 = lrr(s)
        ws, wse, wr2 = wlr(s, weight)
        net = s.iloc[-1] - s.iloc[0]
        rows.append({"transect_id": tid,
                     "longitude": r.get("anchor_lon", np.nan)
                     if "anchor_lon" in wide.columns else np.nan,
                     "latitude": r.get("anchor_lat", np.nan)
                     if "anchor_lat" in wide.columns else np.nan,
                     "net_change_m": net,
                     "years": (s.index[-1] - s.index[0]).days / 365.25,
                     "epr_myr": ep,
                     "lrr_myr": slope,
                     "lrr_se_myr": se,
                     "lrr_r2": r2,
                     "wlr_myr": ws,
                     "wlr_se_myr": wse,
                     "n_shorelines": len(s)})
    rates = pd.DataFrame(rows)

    # attach geometry from the transects GeoDataFrame
    import geopandas as gpd
    trs = gpd.read_file(DATA_DIR / "transects.geojson")
    trs["transect_id"] = trs["transect_id"].astype(int)
    geo = trs[["transect_id", "anchor_lon", "anchor_lat"]
              ].set_index("transect_id")
    rates = rates.merge(geo, left_on="transect_id", right_index=True,
                        how="left")
    rates["lrr_90ci"] = 1.645 * rates["lrr_se_myr"]
    rates["wlr_90ci"] = 1.645 * rates["wlr_se_myr"]

    rates.to_csv(DATA_DIR / "shoreline_rates.csv", index=False)
    print(f"rates computed for {len(rates)} transects")
    print(rates[["epr_myr", "lrr_myr", "wlr_myr"]].describe()
          .round(2).to_string())
    eroding = (rates["lrr_myr"] < -0.5).sum()
    accreting = (rates["lrr_myr"] > 0.5).sum()
    stable = len(rates) - eroding - accreting
    print(f"eroding (<-0.5): {eroding} | stable: {stable} "
          f"| accreting (>+0.5): {accreting}")


if __name__ == "__main__":
    main()
