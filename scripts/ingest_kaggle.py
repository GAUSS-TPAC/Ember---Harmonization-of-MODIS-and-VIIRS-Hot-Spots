"""Download notebook 01 output from Kaggle, harmonize it and install it for the app.

Usage:
  PYTHONPATH=pipeline python scripts/ingest_kaggle.py [--kernel alantchapda/ember-01-aggregate-firms-archives]
  PYTHONPATH=pipeline python scripts/ingest_kaggle.py --monthly path/to/hotspots_monthly.parquet

Writes to data/processed/:
  hotspots_monthly.parquet     raw aggregate (as produced on Kaggle)
  harmonized_monthly.parquet   what the API serves, sorted by (lat_cell, lon_cell) for range reads
  calibration_factors.parquet  only when VIIRS S-NPP overlaps MODIS
  harmonization_report.json    mode, platforms, validation metrics
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from ember_pipeline.harmonize import HARMONIZED_COLUMNS, harmonize, pivot_platforms, validate  # noqa: E402

OUT = ROOT / "data" / "processed"
MIN_OVERLAP_DETECTIONS = 10_000


def download(kernel: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable if "3.12" in sys.version else "/usr/bin/python3.12", "-m", "kaggle",
           "kernels", "output", kernel, "-p", str(dest), "--file-pattern", r".*\.parquet$"]
    subprocess.run(cmd, check=True)
    return dest / "hotspots_monthly.parquet"


def modis_only(monthly: pd.DataFrame) -> pd.DataFrame:
    """No VIIRS overlap yet: serve raw MODIS (Terra + Aqua) counts, flagged as such."""
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


def modis_only_banded(src: Path, dest: Path, band_deg: float = 10.0) -> int:
    """Memory-lean MODIS-only build: one latitude band at a time, streamed to Parquet."""
    import pyarrow.dataset as ds
    dataset = ds.dataset(str(src), format="parquet")
    cols = ["platform", "year", "month", "lat_cell", "lon_cell", "n"]
    writer, rows = None, 0
    lat = -90.0
    while lat < 90.0:
        flt = (ds.field("lat_cell") >= lat) & (ds.field("lat_cell") < lat + band_deg)
        part = dataset.to_table(columns=cols, filter=flt).to_pandas()
        lat += band_deg
        if part.empty:
            continue
        part["platform"] = part["platform"].astype("category")
        table = compact(modis_only(part))
        writer = writer or pq.ParquetWriter(str(dest), table.schema, compression="zstd")
        writer.write_table(table.cast(writer.schema), row_group_size=200_000)
        rows += table.num_rows
        print(f"  band <{lat:+.0f}: {table.num_rows:,} rows", flush=True)
        del part, table
    if writer:
        writer.close()
    return rows


def compact(df: pd.DataFrame) -> pa.Table:
    """Small dtypes + spatial sort so the API can read a bbox without loading the world."""
    df = df.sort_values(["lat_cell", "lon_cell", "year", "month"]).reset_index(drop=True)
    df = df.astype({"lat_cell": "float32", "lon_cell": "float32", "year": "int16", "month": "int8",
                    "n_harm": "float32", "n_low": "float32", "n_high": "float32",
                    "n_modis": "int32", "n_viirs_snpp": "int32", "n_viirs_noaa20": "int32"})
    df["source"] = df["source"].astype("category")
    return pa.Table.from_pandas(df, preserve_index=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", default="alantchapda/ember-01-aggregate-firms-archives")
    ap.add_argument("--monthly", help="use a local hotspots_monthly.parquet instead of downloading")
    args = ap.parse_args()

    t0 = time.time()
    src = Path(args.monthly) if args.monthly else download(args.kernel, OUT / "kaggle")
    platforms = pq.read_table(src, columns=["platform", "year", "n"]).to_pandas()
    has_overlap = platforms.loc[(platforms["platform"] == "VIIRS_SNPP") & platforms["year"].between(2012, 2025), "n"].sum() >= MIN_OVERLAP_DETECTIONS
    if not has_overlap:
        totals = platforms.groupby("platform", observed=True)["n"].sum()
        print(f"no VIIRS S-NPP overlap ({totals.to_dict()}): building MODIS-only table by latitude band")
        (OUT / "calibration_factors.parquet").unlink(missing_ok=True)
        rows = modis_only_banded(src, OUT / "harmonized_monthly.parquet")
        cells = pq.read_table(OUT / "harmonized_monthly.parquet", columns=["lat_cell", "lon_cell"]).to_pandas().drop_duplicates().shape[0]
        report = {"mode": "modis_only", "platforms": {k: int(v) for k, v in totals.items()}, "rows_out": rows, "cells": int(cells)}
        (OUT / "harmonization_report.json").write_text(json.dumps(report, indent=2))
        print(f"modis_only: {rows:,} rows ({time.time()-t0:.0f}s)")
        return
    del platforms
    monthly = pd.read_parquet(src)
    totals = monthly.groupby("platform")["n"].sum().to_dict()
    print(f"loaded {len(monthly):,} rows from {src}: {totals}")

    overlap = monthly[(monthly["platform"] == "VIIRS_SNPP") & monthly["year"].between(2012, 2025)]["n"].sum()
    report = {"platforms": {k: int(v) for k, v in totals.items()}, "rows_in": int(len(monthly))}
    if overlap >= MIN_OVERLAP_DETECTIONS:
        harmonized, factors = harmonize(monthly)
        pq.write_table(pa.Table.from_pandas(factors, preserve_index=False), OUT / "calibration_factors.parquet")
        report["mode"] = "harmonized"
        report["factor_levels"] = factors["level_MODIS"].value_counts().to_dict()
        report["validation"] = validate(monthly, fit_years=(2012, 2018), test_years=(2019, 2025))
        print("validation:", json.dumps(report["validation"], default=str))
    else:
        harmonized = modis_only(monthly)
        (OUT / "calibration_factors.parquet").unlink(missing_ok=True)
        report["mode"] = "modis_only"
        print("no VIIRS S-NPP overlap yet: serving raw MODIS counts (no calibration possible)")

    table = compact(harmonized)
    pq.write_table(table, OUT / "harmonized_monthly.parquet", row_group_size=200_000, compression="zstd")
    if not args.monthly:
        (OUT / "hotspots_monthly.parquet").write_bytes(src.read_bytes())
    report["rows_out"] = table.num_rows
    (OUT / "harmonization_report.json").write_text(json.dumps(report, indent=2, default=str))
    size = (OUT / "harmonized_monthly.parquet").stat().st_size / 1e6
    print(f"{report['mode']}: {table.num_rows:,} rows, {size:.1f} MB -> {OUT} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
