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

    def __init__(self, frame: pd.DataFrame, resolution_deg: float = CELL_RES):
        required = {"lat_cell", "lon_cell", "year", "month", "n_harm", "n_low", "n_high", "source"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"harmonized table lacks columns {sorted(missing)}")
        self.res = resolution_deg
        self.df = frame.reset_index(drop=True)
        self.df["ym"] = self.df["year"].astype(int) * 100 + self.df["month"].astype(int)
        self._lat_c = self.df["lat_cell"].to_numpy() + resolution_deg / 2
        self._lon_c = self.df["lon_cell"].to_numpy() + resolution_deg / 2

    @classmethod
    def from_parquet(cls, path: Path) -> "HarmonizedStore":
        return cls(pd.read_parquet(path))

    def coverage(self) -> Coverage:
        ym = self.df["ym"]
        return Coverage(
            first=(int(ym.min() // 100), int(ym.min() % 100)),
            last=(int(ym.max() // 100), int(ym.max() % 100)),
            cells=int(self.df[["lat_cell", "lon_cell"]].drop_duplicates().shape[0]),
            bounds=(float(self.df["lat_cell"].min()), float(self.df["lon_cell"].min()),
                    float(self.df["lat_cell"].max() + self.res), float(self.df["lon_cell"].max() + self.res)),
        )

    def select(self, geometry: dict, start: tuple[int, int] | None = None,
               end: tuple[int, int] | None = None) -> pd.DataFrame:
        """Rows whose cell centre falls inside the geometry and whose month is in [start, end]."""
        mask = np.zeros(len(self.df), dtype=bool)
        for ring in rings_of(geometry):
            s, w, n, e = bbox_of(ring)
            coarse = (self._lat_c >= s) & (self._lat_c <= n) & (self._lon_c >= w) & (self._lon_c <= e)
            idx = np.flatnonzero(coarse)
            if idx.size:
                mask[idx] |= points_in_ring(self._lat_c[idx], self._lon_c[idx], ring)
        if start:
            mask &= self.df["ym"].to_numpy() >= start[0] * 100 + start[1]
        if end:
            mask &= self.df["ym"].to_numpy() <= end[0] * 100 + end[1]
        return self.df.loc[mask]
