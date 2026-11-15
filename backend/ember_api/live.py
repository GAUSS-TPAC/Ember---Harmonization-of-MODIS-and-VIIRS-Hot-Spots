"""Bring the last weeks of near-real-time hotspots onto the harmonized calendar.

Flow: FIRMS NRT hotspots -> same aggregation as the archive (ember_pipeline) ->
scaled with the stored transfer factors -> months flagged `provisional`.
"""

from __future__ import annotations

import dataclasses
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ember_pipeline.aggregate import aggregate_frame
from ember_pipeline.grid import Grid
from ember_pipeline.harmonize import CELL, Coverage, HarmonizationConfig, apply_factors

from .firms import FirmsClient, FirmsUnavailable


def _month_before(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def live_config(first_live: tuple[int, int], base: HarmonizationConfig = HarmonizationConfig()) -> HarmonizationConfig:
    """Config where the reference sensor stops before the live window, so the
    NRT platform (NOAA-20, then MODIS) is scaled instead of trusted as reference."""
    coverage = dict(base.coverage)
    coverage[base.reference] = Coverage(coverage[base.reference].start, _month_before(*first_live))
    return dataclasses.replace(base, coverage=coverage)


def fill_missing_factors(factors: pd.DataFrame, cells: pd.DataFrame) -> pd.DataFrame:
    """Cells never seen in the archive get the median factor (no local history)."""
    merged = cells[CELL].drop_duplicates().merge(factors, on=CELL, how="left")
    for col in [c for c in factors.columns if c.startswith("k_")]:
        merged[col] = merged[col].fillna(factors[col].median())
        name = col[2:]
        merged[f"lo_{name}"] = merged.get(f"lo_{name}", pd.Series(1.0, index=merged.index)).fillna(1.0)
        merged[f"hi_{name}"] = merged.get(f"hi_{name}", pd.Series(1.0, index=merged.index)).fillna(1.0)
        merged[f"level_{name}"] = merged.get(f"level_{name}", pd.Series("global", index=merged.index)).fillna("global")
    return merged


class LiveHarmonizer:
    """Turns raw NRT hotspots into provisional harmonized cell-months."""

    def __init__(self, factors: pd.DataFrame, grid: Grid = Grid(0.1), cfg: HarmonizationConfig = HarmonizationConfig()):
        self.factors = factors
        self.grid = grid
        self.cfg = cfg

    @property
    def sources(self) -> tuple[str, ...]:
        """MODIS NRT when there is no calibration yet (same scale as the MODIS-only archive)."""
        return ("MODIS_NRT",) if self.factors is None else ("VIIRS_NOAA20_NRT",)

    def harmonize(self, hotspots: pd.DataFrame, first_live: tuple[int, int]) -> pd.DataFrame:
        if hotspots.empty:
            return pd.DataFrame()
        monthly = aggregate_frame(hotspots, self.grid, country="live")
        if monthly.empty:
            return pd.DataFrame()
        if self.factors is None:
            out = _modis_only(monthly)
            out["provisional"] = True
            return out
        factors = fill_missing_factors(self.factors, monthly)
        harmonized = apply_factors(monthly, factors, live_config(first_live, self.cfg))
        harmonized["provisional"] = True
        return harmonized


class LiveService:
    """Fetch + harmonize with a small in-memory cache (FIRMS allows 5000 req / 10 min)."""

    def __init__(self, client: FirmsClient, harmonizer: LiveHarmonizer, days: int = 60, ttl_seconds: int = 1800,
                 today: date | None = None):
        self.client = client
        self.harmonizer = harmonizer
        self.days = days
        self.ttl = ttl_seconds
        self._today = today
        self._cache: dict[tuple, tuple[float, pd.DataFrame]] = {}

    @property
    def enabled(self) -> bool:
        return self.client.configured

    def today(self) -> date:
        return self._today or date.today()

    def window(self) -> tuple[date, date]:
        end = self.today()
        return end - timedelta(days=self.days - 1), end

    def first_live_month(self) -> tuple[int, int]:
        start, _ = self.window()
        return start.year, start.month

    def recent(self, bbox: tuple[float, float, float, float]) -> pd.DataFrame:
        """Provisional harmonized cell-months for the bbox over the live window."""
        key = tuple(round(v, 2) for v in bbox)
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < self.ttl:
            return hit[1]
        start, end = self.window()
        raw = self.client.hotspots(bbox, start, end, sources=self.harmonizer.sources)
        out = self.harmonizer.harmonize(raw, self.first_live_month())
        self._cache[key] = (time.time(), out)
        return out


def _modis_only(monthly: pd.DataFrame) -> pd.DataFrame:
    from ember_pipeline.harmonize import HARMONIZED_COLUMNS, pivot_platforms
    wide = pivot_platforms(monthly)
    out = wide[["lat_cell", "lon_cell", "year", "month"]].copy()
    out["n_modis"] = wide["MODIS_Terra"] + wide["MODIS_Aqua"]
    out["n_harm"] = out["n_modis"].astype("float64")
    out["n_low"] = out["n_harm"]
    out["n_high"] = out["n_harm"]
    out["source"] = "MODIS_raw"
    out["n_viirs_snpp"] = wide["VIIRS_SNPP"]
    out["n_viirs_noaa20"] = wide["VIIRS_NOAA20"]
    return out[HARMONIZED_COLUMNS]


def merge_live(archive: pd.DataFrame, live: pd.DataFrame, first_live: tuple[int, int]) -> pd.DataFrame:
    """Archive rows before the live window + live rows from it on."""
    arch = archive.copy()
    if "provisional" not in arch.columns:
        arch["provisional"] = False
    ym_first = first_live[0] * 100 + first_live[1]
    arch_ym = arch["year"].astype(int) * 100 + arch["month"].astype(int)
    kept = arch.loc[arch_ym < ym_first]
    if live.empty:
        return kept
    cols = [c for c in kept.columns if c in live.columns]
    return pd.concat([kept[cols], live[cols]], ignore_index=True)


def last_complete_month(today: date) -> tuple[int, int]:
    return _month_before(today.year, today.month)


__all__ = ["FirmsUnavailable", "LiveHarmonizer", "LiveService", "merge_live", "live_config",
           "last_complete_month", "fill_missing_factors"]
