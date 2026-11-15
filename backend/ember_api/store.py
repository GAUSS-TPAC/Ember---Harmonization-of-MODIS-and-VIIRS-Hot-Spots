"""Read-side access to the harmonized monthly table (a Repository over Parquet)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .geometry import bbox_of, points_in_ring, rings_of

CELL_RES = 0.1


@dataclass
class Coverage:
    first: tuple[int, int]
    last: tuple[int, int]
    cells: int
    bounds: tuple[float, float, float, float]  # south, west, north, east


class HarmonizedStore:
    """Holds the harmonized series in memory and answers spatial/temporal selections."""

    def __init__(self, frame: pd.DataFrame, resolution_deg: float = CELL_RES, factors: pd.DataFrame | None = None):
        required = {"lat_cell", "lon_cell", "year", "month", "n_harm", "n_low", "n_high", "source"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"harmonized table lacks columns {sorted(missing)}")
        self.res = resolution_deg
        self.factors = factors
        self.df = frame.reset_index(drop=True)
        self.df["ym"] = self.df["year"].astype(int) * 100 + self.df["month"].astype(int)
        self._lat_c = self.df["lat_cell"].to_numpy(dtype="float64") + resolution_deg / 2
        self._lon_c = self.df["lon_cell"].to_numpy(dtype="float64") + resolution_deg / 2
        self._lat_sorted = bool(np.all(self._lat_c[1:] >= self._lat_c[:-1])) if len(self._lat_c) > 1 else True

    @classmethod
    def from_parquet(cls, path: Path) -> "HarmonizedStore":
        factors_path = Path(path).with_name("calibration_factors.parquet")
        factors = pd.read_parquet(factors_path) if factors_path.exists() else None
        frame = pd.read_parquet(path)
        for col, dtype in (("lat_cell", "float32"), ("lon_cell", "float32"), ("n_harm", "float32"),
                           ("n_low", "float32"), ("n_high", "float32")):
            if col in frame.columns:
                frame[col] = frame[col].astype(dtype)
        if "source" in frame.columns:
            frame["source"] = frame["source"].astype("category")
        return cls(frame, factors=factors)

    def coverage(self) -> Coverage:
        ym = self.df["ym"]
        return Coverage(
            first=(int(ym.min() // 100), int(ym.min() % 100)),
            last=(int(ym.max() // 100), int(ym.max() % 100)),
            cells=int(self.df[["lat_cell", "lon_cell"]].drop_duplicates().shape[0]),
            bounds=(float(self.df["lat_cell"].min()), float(self.df["lon_cell"].min()),
                    float(self.df["lat_cell"].max() + self.res), float(self.df["lon_cell"].max() + self.res)),
        )

    def select_mask(self, frame: pd.DataFrame, geometry: dict) -> np.ndarray:
        """Boolean mask of `frame` rows (any cell table) whose centre is inside the geometry."""
        lat_c = frame["lat_cell"].to_numpy() + self.res / 2
        lon_c = frame["lon_cell"].to_numpy() + self.res / 2
        mask = np.zeros(len(frame), dtype=bool)
        for ring in rings_of(geometry):
            mask |= points_in_ring(lat_c, lon_c, ring)
        return mask

    def select(self, geometry: dict, start: tuple[int, int] | None = None,
               end: tuple[int, int] | None = None) -> pd.DataFrame:
        """Rows whose cell centre falls inside the geometry and whose month is in [start, end]."""
        mask = np.zeros(len(self.df), dtype=bool)
        for ring in rings_of(geometry):
            s, w, n, e = bbox_of(ring)
            if self._lat_sorted:  # contiguous latitude band, then lon filter inside it
                lo, hi = np.searchsorted(self._lat_c, [s, n], side="left")[0], np.searchsorted(self._lat_c, n, side="right")
                band = np.arange(lo, hi)
                idx = band[(self._lon_c[lo:hi] >= w) & (self._lon_c[lo:hi] <= e)]
            else:
                coarse = (self._lat_c >= s) & (self._lat_c <= n) & (self._lon_c >= w) & (self._lon_c <= e)
                idx = np.flatnonzero(coarse)
            if idx.size:
                mask[idx] |= points_in_ring(self._lat_c[idx], self._lon_c[idx], ring)
        if start:
            mask &= self.df["ym"].to_numpy() >= start[0] * 100 + start[1]
        if end:
            mask &= self.df["ym"].to_numpy() <= end[0] * 100 + end[1]
        return self.df.loc[mask]
