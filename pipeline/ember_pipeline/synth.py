"""Synthetic `hotspots_monthly` generator for local development and demos.

Produces a plausible fire regime: a dry-season peak whose month depends on the
hemisphere, year-to-year variability, and platform sensitivities that mimic the
real MODIS/VIIRS gap. Not for science, only to exercise the pipeline and the app
before the global dataset is available.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .aggregate import OUTPUT_COLUMNS

PLATFORM_START = {"MODIS_Terra": (2000, 11), "MODIS_Aqua": (2002, 7),
                  "VIIRS_SNPP": (2012, 1), "VIIRS_NOAA20": (2018, 4)}
PLATFORM_END = {"VIIRS_SNPP": (2026, 11)}
# Expected detections relative to a "true" burning intensity.
SENSITIVITY = {"MODIS_Terra": 0.45, "MODIS_Aqua": 0.55, "VIIRS_SNPP": 4.0, "VIIRS_NOAA20": 3.8}
DAY_SHARE = {"MODIS_Terra": 0.9, "MODIS_Aqua": 0.85, "VIIRS_SNPP": 0.7, "VIIRS_NOAA20": 0.7}


def synthetic_monthly(bbox=(2.0, 9.0, 5.0, 12.0), resolution_deg=0.1, years=(2000, 2026),
                      country="Synthetic", seed=0, anomaly_year: int | None = 2024) -> pd.DataFrame:
    """bbox = (south, west, north, east). Returns a frame in the hotspots_monthly contract."""
    rng = np.random.default_rng(seed)
    s, w, n, e = bbox
    lats = np.round(np.arange(s, n, resolution_deg), 4)
    lons = np.round(np.arange(w, e, resolution_deg), 4)
    cells = pd.MultiIndex.from_product([lats, lons], names=["lat_cell", "lon_cell"]).to_frame(index=False)
    # Spatial intensity: smooth random field, a few hot corridors.
    base = rng.gamma(shape=1.2, scale=1.0, size=len(cells))
    base *= 1 + 2 * np.exp(-((cells["lat_cell"] - (s + n) / 2) ** 2) / 0.5)
    cells["intensity"] = base

    frames = []
    months = np.arange(1, 13)
    for year in range(years[0], years[1] + 1):
        year_factor = rng.lognormal(0, 0.35)
        if anomaly_year and year == anomaly_year:
            year_factor *= 2.5
        for month in months:
            ym = year * 100 + month
            # Northern-hemisphere style season: peak in January, ~zero in July.
            season = 0.02 + 0.98 * (0.5 * (1 + np.cos(2 * np.pi * (month - 1) / 12))) ** 3
            mu_true = cells["intensity"].values * 6.0 * season * year_factor
            for platform, sens in SENSITIVITY.items():
                y0, m0 = PLATFORM_START[platform]
                if ym < y0 * 100 + m0:
                    continue
                y1, m1 = PLATFORM_END.get(platform, (9999, 12))
                if ym > y1 * 100 + m1:
                    continue
                counts = rng.poisson(mu_true * sens)
                keep = counts > 0
                if not keep.any():
                    continue
                n_day = rng.binomial(counts[keep], DAY_SHARE[platform])
                frames.append(pd.DataFrame({
                    "platform": platform, "country": country, "year": np.int16(year), "month": np.int8(month),
                    "lat_cell": cells["lat_cell"].values[keep], "lon_cell": cells["lon_cell"].values[keep],
                    "n": counts[keep], "n_day": n_day, "n_night": counts[keep] - n_day,
                    "frp_sum": np.round(counts[keep] * rng.gamma(2.0, 8.0, size=keep.sum()), 1),
                }))
    return pd.concat(frames, ignore_index=True)[OUTPUT_COLUMNS]
