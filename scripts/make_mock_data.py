from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.data import DATA_DIR

START = pd.Period("2000-01", freq="M")
END = pd.Period("2026-10", freq="M")
SEED = 20261114


def build_mock_data() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    year_factors = {
        year: max(0.9, 1 + 0.002 * (year - START.year) + rng.normal(0, 0.015))
        for year in range(START.year, END.year + 1)
    }
    cell_lats = np.round(np.arange(2.0, 13.0, 0.1), 1)
    cell_lons = np.round(np.arange(8.5, 16.2, 0.1), 1)
    cells = []
    for cell_lat in cell_lats:
        for cell_lon in cell_lons:
            center_lat = cell_lat + 0.05
            center_lon = cell_lon + 0.05
            if 11.5 <= center_lat <= 12.5 and 15.2 <= center_lon <= 16.2:
                continue
            if rng.random() < 0.055:
                cells.append((cell_lat, cell_lon, rng.uniform(0.55, 1.0)))

    records = []
    months = pd.period_range(START, END, freq="M")
    for cell_lat, cell_lon, intensity in cells:
        northness = (cell_lat - 2.0) / 11.0
        for period in months:
            month = period.month
            # Northern cells peak in the December-February dry season.
            if month in (12, 1, 2):
                season = 0.17 + 0.75 * northness
            elif month in (11, 3):
                season = 0.08 + 0.24 * northness
            elif month in (6, 7, 8):
                season = 0.025 + 0.035 * (1.0 - northness)
            else:
                season = 0.055 + 0.09 * northness

            annual_variation = rng.lognormal(mean=0.0, sigma=0.35)
            if rng.random() >= min(0.82, season * intensity * annual_variation):
                continue

            source = "modis" if period.year < 2012 else "viirs_scaled"
            base_count = rng.poisson(1.4 + 8.0 * season * intensity * year_factors[period.year])
            if base_count < 1:
                continue
            if period.year < 2012:
                n_modis = base_count
                n_viirs = None
                n_harmonized = float(base_count)
            else:
                calibration_k = 0.72 + period.month * 0.015
                n_modis = base_count
                n_viirs = int(max(1, round(base_count / calibration_k)))
                n_harmonized = float(n_viirs * calibration_k)

            records.append(
                {
                    "cell_lat": cell_lat,
                    "cell_lon": cell_lon,
                    "year": period.year,
                    "month": month,
                    "n_modis": n_modis,
                    "n_viirs": n_viirs,
                    "n_harmonized": n_harmonized,
                    "source": source,
                    "provisional": period >= END - 1,
                }
            )

    grid_schema = pa.schema(
        [
            pa.field("cell_lat", pa.float64()),
            pa.field("cell_lon", pa.float64()),
            pa.field("year", pa.int32()),
            pa.field("month", pa.int32()),
            pa.field("n_modis", pa.int32()),
            pa.field("n_viirs", pa.int32()),
            pa.field("n_harmonized", pa.float64()),
            pa.field("source", pa.string()),
            pa.field("provisional", pa.bool_()),
        ]
    )
    grid = pa.Table.from_pandas(pd.DataFrame.from_records(records), schema=grid_schema)
    pq.write_table(grid, DATA_DIR / "grid_monthly.parquet", compression="zstd")

    calibration_schema = pa.schema(
        [
            pa.field("block_lat", pa.int32()),
            pa.field("block_lon", pa.int32()),
            pa.field("month", pa.int32()),
            pa.field("k", pa.float64()),
            pa.field("n_viirs_overlap", pa.int32()),
            pa.field("fallback", pa.bool_()),
        ]
    )
    calibration_rows = [
        (lat, lon, month, 0.72 + month * 0.015, 120 + 7 * month, False)
        for lat in range(2, 13)
        for lon in range(8, 17)
        for month in range(1, 13)
    ]
    calibration = pa.Table.from_pandas(
        pd.DataFrame(
            calibration_rows,
            columns=["block_lat", "block_lon", "month", "k", "n_viirs_overlap", "fallback"],
        ),
        schema=calibration_schema,
    )
    pq.write_table(calibration, DATA_DIR / "calibration.parquet", compression="zstd")

    validation_schema = pa.schema(
        [
            pa.field("region", pa.string()),
            pa.field("holdout_years", pa.string()),
            pa.field("r", pa.float64()),
            pa.field("mape", pa.float64()),
        ]
    )
    validation = pa.Table.from_pandas(
        pd.DataFrame(
            [("Cameroon mock", "2018,2020", 0.83, 24.7)],
            columns=["region", "holdout_years", "r", "mape"],
        ),
        schema=validation_schema,
    )
    pq.write_table(validation, DATA_DIR / "validation.parquet", compression="zstd")
    print(f"Wrote {len(records):,} sparse monthly cell rows to {DATA_DIR}")


if __name__ == "__main__":
    build_mock_data()