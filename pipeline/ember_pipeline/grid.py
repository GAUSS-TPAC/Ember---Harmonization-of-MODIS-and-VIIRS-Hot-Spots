"""Regular lat/lon grid used to make MODIS and VIIRS detections comparable."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Grid:
    """Equal-angle grid; a cell is identified by its south-west corner."""

    resolution_deg: float = 0.1

    def __post_init__(self) -> None:
        if not 0 < self.resolution_deg <= 10:
            raise ValueError("resolution must be in (0, 10] degrees")

    @property
    def _decimals(self) -> int:
        return max(0, int(np.ceil(-np.log10(self.resolution_deg))) + 1)

    def snap(self, lat: pd.Series, lon: pd.Series) -> tuple[np.ndarray, np.ndarray]:
        """Return (lat_cell, lon_cell): the SW corner of the cell containing each point."""
        res = self.resolution_deg
        iy = np.floor((np.asarray(lat, dtype="float64") + 90.0) / res)
        ix = np.floor((np.asarray(lon, dtype="float64") + 180.0) / res)
        lat_cell = np.round(-90.0 + iy * res, self._decimals)
        lon_cell = np.round(-180.0 + ix * res, self._decimals)
        return lat_cell, lon_cell
