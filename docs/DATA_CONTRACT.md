# Data contract

The pipeline, the harmonization notebook and the web backend only share one table.
Anything upstream of it (raw CSV layouts, sensor quirks) stays inside `ember_pipeline`.

## Table `hotspots_monthly` (Parquet)

| column   | type    | meaning |
|----------|---------|---------|
| platform | str     | `MODIS_Terra`, `MODIS_Aqua`, `VIIRS_SNPP`, `VIIRS_NOAA20`, `VIIRS_NOAA21` |
| country  | str     | country of the FIRMS per-country file; `world` for global NRT pulls |
| year     | int16   | acquisition year (UTC) |
| month    | int8    | 1–12 |
| lat_cell | float64 | latitude of the cell's south-west corner (grid 0.1°) |
| lon_cell | float64 | longitude of the cell's south-west corner |
| n        | int64   | detections kept after quality filter |
| n_day    | int64   | subset with `daynight == D` |
| n_night  | int64   | `n - n_day` |
| frp_sum  | float64 | sum of fire radiative power (MW) over `n` |

Primary key: `(platform, country, year, month, lat_cell, lon_cell)`.

## Quality filter (applied before counting)

- MODIS: `confidence >= 30` (drops FIRMS "low" class).
- VIIRS: `confidence in {n, h}` (drops "low").
- `type == 0` (presumed vegetation fire) when the column exists; NRT rows have no
  `type` and are kept.

## Why these choices

- **Cells, not points.** A 375 m VIIRS pixel and a 1 km MODIS pixel can never be
  matched one to one; a 0.1° cell (about 11 km) absorbs the geolocation and
  footprint differences so that only sensitivity remains to calibrate.
- **Platform kept separate.** Aqua and Suomi-NPP share the 13:30 overpass; the
  harmonization step needs them distinguishable from Terra (10:30).
- **Day and night kept separate.** Detection sensitivity differs strongly between
  them; the calibration can be done per regime.
- **Counts and FRP only.** Everything the calendar and the anomaly score need; raw
  points are re-queried from FIRMS on demand for CSV export.
