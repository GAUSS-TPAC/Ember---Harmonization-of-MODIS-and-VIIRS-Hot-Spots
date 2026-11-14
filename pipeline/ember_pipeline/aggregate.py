"""Streaming aggregation of raw hotspot files into cell x month x platform counts.

Output schema (the data contract shared with the harmonization notebook and the
backend, see docs/DATA_CONTRACT.md):

    platform   str      MODIS_Terra | MODIS_Aqua | VIIRS_SNPP | VIIRS_NOAA20 | VIIRS_NOAA21
    country    str      from the FIRMS per-country file name ("world" for global pulls)
    year       int16
    month      int8
    lat_cell   float64  south-west corner of the grid cell
    lon_cell   float64
    n          int64    confident vegetation-fire detections in the cell that month
    n_day      int64    subset acquired in daytime
    n_night    int64    subset acquired at night
    frp_sum    float64  sum of fire radiative power (MW) over the n detections
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path

import pandas as pd

from .grid import Grid
from .sensors import normalize

KEY_COLUMNS = ["platform", "country", "year", "month", "lat_cell", "lon_cell"]
OUTPUT_COLUMNS = KEY_COLUMNS + ["n", "n_day", "n_night", "frp_sum"]

_COUNTRY_FILE = re.compile(r"^(?P<sensor>[a-z0-9\-]+)_(?P<year>\d{4})_(?P<country>.+)\.csv$", re.I)


def country_from_name(file_name: str) -> str:
    """'modis_2020_Cameroon.csv' -> 'Cameroon'; anything else -> 'world'."""
    match = _COUNTRY_FILE.match(Path(file_name).name)
    return match.group("country") if match else "world"


def aggregate_frame(raw: pd.DataFrame, grid: Grid, country: str) -> pd.DataFrame:
    """Aggregate one raw FIRMS frame. Pure function, safe to call per chunk."""
    df = normalize(raw)
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    dates = pd.to_datetime(df["acq_date"], errors="coerce")
    df = df.loc[dates.notna()].copy()
    dates = dates.loc[df.index]
    df["year"] = dates.dt.year.astype("int16")
    df["month"] = dates.dt.month.astype("int8")
    df["lat_cell"], df["lon_cell"] = grid.snap(df["latitude"], df["longitude"])
    df["country"] = country

    out = (
        df.groupby(KEY_COLUMNS, sort=False, observed=True)
        .agg(n=("frp", "size"), n_day=("is_day", "sum"), frp_sum=("frp", "sum"))
        .reset_index()
    )
    out["n_night"] = out["n"] - out["n_day"]
    return out[OUTPUT_COLUMNS]


def merge_partials(parts: Iterable[pd.DataFrame]) -> pd.DataFrame:
    """Sum partial aggregates (from chunks or files) that share the same keys."""
    frames = [p for p in parts if not p.empty]
    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    merged = (
        pd.concat(frames, ignore_index=True)
        .groupby(KEY_COLUMNS, sort=True, observed=True)[["n", "n_day", "n_night", "frp_sum"]]
        .sum()
        .reset_index()
    )
    return merged[OUTPUT_COLUMNS]


def aggregate_csv(source, grid: Grid, country: str, chunksize: int = 1_000_000) -> pd.DataFrame:
    """Aggregate a CSV path or file-like object, reading it in chunks."""
    reader = pd.read_csv(source, chunksize=chunksize, low_memory=False)
    return merge_partials(aggregate_frame(chunk, grid, country) for chunk in reader)


def iter_csv_members(path: Path) -> Iterator[tuple[str, object]]:
    """Yield (member_name, binary file object) for a .csv, .csv.gz or .zip of CSVs."""
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().endswith(".csv"):
                    with archive.open(name) as member:
                        yield name, io.BytesIO(member.read())
    else:
        yield path.name, path


def aggregate_paths(paths: Iterable[Path], grid: Grid, chunksize: int = 1_000_000,
                    on_file=None) -> pd.DataFrame:
    """Aggregate every CSV found in the given files or zip archives."""
    partials = []
    for path in paths:
        for name, source in iter_csv_members(Path(path)):
            if on_file:
                on_file(name)
            partials.append(aggregate_csv(source, grid, country_from_name(name), chunksize))
    return merge_partials(partials)
