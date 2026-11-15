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
        required = {"lat_cell", "lon_cell", "year", "month", "n_harm"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"harmonized table lacks columns {sorted(missing)}")
        frame = frame.copy()
        # Slim MODIS-only files carry counts only: fill the optional columns.
        frame["n_harm"] = frame["n_harm"].astype("float32")
        for col in ("n_low", "n_high"):
            if col not in frame.columns:
                frame[col] = frame["n_harm"]
        if "source" not in frame.columns:
            frame["source"] = "MODIS_raw"
        if "n_modis" not in frame.columns:
            frame["n_modis"] = frame["n_harm"]
        for col in ("n_viirs_snpp", "n_viirs_noaa20"):
            if col not in frame.columns:
                frame[col] = 0
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


class LazyHarmonizedStore:
    """Same interface as HarmonizedStore, but reads only the requested bbox from Parquet.

    The file must be sorted by lat_cell (scripts/ingest_kaggle.py does it) so row-group
    statistics let pyarrow skip most of the world on each request.
    """

    def __init__(self, path: Path, resolution_deg: float = CELL_RES, factors: pd.DataFrame | None = None):
        import pyarrow.dataset as ds
        import pyarrow.parquet as pq

        self.path = Path(path)
        self.res = resolution_deg
        self.factors = factors
        self._ds = ds.dataset(str(self.path), format="parquet")
        meta = pq.ParquetFile(str(self.path)).metadata
        self.num_rows = meta.num_rows
        self._coverage = self._scan_coverage(meta)

    def _scan_coverage(self, meta) -> Coverage:
        import pyarrow.dataset as ds

        names = meta.schema.names
        stats = {c: [meta.row_group(i).column(names.index(c)).statistics for i in range(meta.num_row_groups)]
                 for c in ("lat_cell", "lon_cell", "year")}
        lo = {c: min(s.min for s in v) for c, v in stats.items()}
        hi = {c: max(s.max for s in v) for c, v in stats.items()}
        first_m = self._ds.to_table(columns=["month"], filter=ds.field("year") == lo["year"]).column("month")
        last_m = self._ds.to_table(columns=["month"], filter=ds.field("year") == hi["year"]).column("month")
        report = self.path.with_name("harmonization_report.json")
        cells = -1
        if report.exists():
            import json
            cells = int(json.loads(report.read_text()).get("cells", -1))
        return Coverage(first=(int(lo["year"]), int(min(first_m.to_pylist()))),
                        last=(int(hi["year"]), int(max(last_m.to_pylist()))), cells=cells,
                        bounds=(float(lo["lat_cell"]), float(lo["lon_cell"]),
                                float(hi["lat_cell"]) + self.res, float(hi["lon_cell"]) + self.res))

    def coverage(self) -> Coverage:
        return self._coverage

    @property
    def df(self) -> pd.DataFrame:  # only used for its length by /api/health
        return pd.DataFrame(index=pd.RangeIndex(self.num_rows))

    def _read_bbox(self, s: float, w: float, n: float, e: float,
                   start: tuple[int, int] | None, end: tuple[int, int] | None) -> pd.DataFrame:
        import pyarrow.dataset as ds

        pad = self.res
        flt = ((ds.field("lat_cell") >= s - pad) & (ds.field("lat_cell") <= n) &
               (ds.field("lon_cell") >= w - pad) & (ds.field("lon_cell") <= e))
        if start:
            flt &= ds.field("year") >= start[0]
        if end:
            flt &= ds.field("year") <= end[0]
        return self._ds.to_table(filter=flt).to_pandas()

    def select(self, geometry: dict, start: tuple[int, int] | None = None,
               end: tuple[int, int] | None = None) -> pd.DataFrame:
        parts = []
        for ring in rings_of(geometry):
            s, w, n, e = bbox_of(ring)
            frame = self._read_bbox(s, w, n, e, start, end)
            if len(frame):
                parts.append(HarmonizedStore(frame, self.res).select(
                    {"type": "Polygon", "coordinates": [ring]}, start, end))
        if not parts:
            return HarmonizedStore(pd.DataFrame(columns=["lat_cell", "lon_cell", "year", "month", "n_harm",
                                                         "n_low", "n_high", "source", "n_modis",
                                                         "n_viirs_snpp", "n_viirs_noaa20"]), self.res).df
        out = pd.concat(parts, ignore_index=True)
        return out.drop_duplicates(subset=["lat_cell", "lon_cell", "year", "month"])

    def select_mask(self, frame: pd.DataFrame, geometry: dict) -> np.ndarray:
        return HarmonizedStore.select_mask(self, frame, geometry)


def open_store(path: Path, max_in_memory_rows: int = 3_000_000):
    """In-memory store for small tables, lazy bbox reads for large ones."""
    import pyarrow.parquet as pq

    path = Path(path)
    factors_path = path.with_name("calibration_factors.parquet")
    factors = pd.read_parquet(factors_path) if factors_path.exists() else None
    if pq.ParquetFile(str(path)).metadata.num_rows <= max_in_memory_rows:
        store = HarmonizedStore.from_parquet(path)
        return store
    return LazyHarmonizedStore(path, factors=factors)
