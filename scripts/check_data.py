from datetime import date
import math
import os
from pathlib import Path
import sys
from unittest.mock import patch

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.data import (
    DATA_DIR,
    get_calendar,
    get_data_month_range,
    get_latest_anomaly,
    open_database,
)
from app.area import area_refusal_message, calendar_filename
from app.config import get_data_mode


EXPECTED_SCHEMAS = {
    "grid_monthly.parquet": pa.schema(
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
    ),
    "calibration.parquet": pa.schema(
        [
            pa.field("block_lat", pa.int32()),
            pa.field("block_lon", pa.int32()),
            pa.field("month", pa.int32()),
            pa.field("k", pa.float64()),
            pa.field("n_viirs_overlap", pa.int32()),
            pa.field("fallback", pa.bool_()),
        ]
    ),
    "validation.parquet": pa.schema(
        [
            pa.field("region", pa.string()),
            pa.field("holdout_years", pa.string()),
            pa.field("r", pa.float64()),
            pa.field("mape", pa.float64()),
        ]
    ),
}


def check_data() -> None:
    for filename, expected_schema in EXPECTED_SCHEMAS.items():
        actual_schema = pq.read_schema(DATA_DIR / filename)
        assert actual_schema.equals(expected_schema), (
            f"{filename} schema mismatch: expected {expected_schema}, got {actual_schema}"
        )

    validation = pq.read_table(DATA_DIR / "validation.parquet").to_pandas()
    expected_validation_columns = ["region", "holdout_years", "r", "mape"]
    assert validation.columns.tolist() == expected_validation_columns
    assert validation["r"].between(-1, 1).all(), validation["r"].tolist()
    correlation_min = float(validation["r"].min())
    correlation_max = float(validation["r"].max())
    print(
        f"Validation schema: {validation.columns.tolist()}; "
        f"r range: {correlation_min:.3f} to {correlation_max:.3f}"
    )

    banner_text = (
        "DEMO DATA: synthetic values, not real fire observations. "
        "Validation numbers shown are placeholders."
    )
    placeholder_caption = (
        "PLACEHOLDER values from synthetic data. Not a real validation result."
    )
    app_pages = {
        "main": Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py",
        "method": Path(__file__).resolve().parents[1] / "app" / "pages" / "1_Method.py",
    }
    for mode in ("mock", "real"):
        for page_name, page_path in app_pages.items():
            with patch.dict(os.environ, {"DATA_MODE": mode}):
                app = AppTest.from_file(str(page_path)).run(timeout=30)
            assert not app.exception, (mode, page_name, app.exception)
            warnings = [element.value for element in app.warning]
            captions = [element.value for element in app.caption]
            if mode == "mock":
                assert banner_text in warnings, (mode, page_name, warnings)
                if page_name == "method":
                    assert placeholder_caption in captions, captions
            else:
                assert banner_text not in warnings, (mode, page_name, warnings)
                if page_name == "method":
                    assert placeholder_caption not in captions, captions
            print(f"AppTest {mode} mode, {page_name} page: banner behavior passed")

    with patch.dict(os.environ, {"DATA_MODE": "invalid"}):
        try:
            get_data_mode()
        except ValueError as error:
            assert "DATA_MODE" in str(error) and "mock" in str(error) and "real" in str(error)
            print(f"Invalid DATA_MODE error: {error}")
        else:
            raise AssertionError("Invalid DATA_MODE should raise ValueError")

    connection = open_database()
    assert get_data_month_range(connection) == (date(2000, 1, 1), date(2026, 10, 1))
    expected_filename = "calendar_lat2-13_lon8.5-16.2_2000-01_2026-10.csv"
    actual_filename = calendar_filename(
        (2.0, 13.0, 8.5, 16.2), date(2000, 1, 1), date(2026, 10, 1)
    )
    assert actual_filename == expected_filename, actual_filename
    print(f"Calendar CSV filename: {actual_filename}")
    grid_path = str(DATA_DIR / "grid_monthly.parquet")
    duplicates = connection.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT cell_lat, cell_lon, year, month
            FROM read_parquet(?)
            GROUP BY ALL
            HAVING COUNT(*) > 1
        )
        """,
        [grid_path],
    ).fetchone()[0]
    assert duplicates == 0, f"Found {duplicates} duplicate cell-month keys"

    annual_totals = connection.execute(
        """
        SELECT year, SUM(n_harmonized) AS total
        FROM read_parquet(?)
        WHERE year BETWEEN 2006 AND 2017
        GROUP BY year
        ORDER BY year
        """,
        [grid_path],
    ).fetchall()
    totals_by_year = {year: total for year, total in annual_totals}
    mean_2006_2011 = sum(totals_by_year.get(year, 0) for year in range(2006, 2012)) / 6
    mean_2012_2017 = sum(totals_by_year.get(year, 0) for year in range(2012, 2018)) / 6
    step_difference = abs(mean_2012_2017 - mean_2006_2011) / mean_2006_2011
    print(
        f"Mean annual total 2006-2011: {mean_2006_2011:.2f}; "
        f"2012-2017: {mean_2012_2017:.2f}; "
        f"difference: {step_difference:.2%}"
    )
    assert step_difference <= 0.10, f"2012 level difference is {step_difference:.2%}"

    direct_checks = [
        (2007, 1, (2.0, 6.0, 8.5, 16.2)),
        (2015, 12, (8.0, 13.0, 8.5, 16.2)),
        (2026, 10, (2.0, 13.0, 8.5, 16.2)),
    ]
    for year, month, bbox in direct_checks:
        calendar = get_calendar(
            connection, bbox, date(year, month, 1), date(year, month, 1)
        )
        calendar_count = float(calendar.loc[0, "count"])
        min_lat, max_lat, min_lon, max_lon = bbox
        direct_count = connection.execute(
            """
            SELECT COALESCE(SUM(n_harmonized), 0)
            FROM read_parquet(?)
            WHERE year = ? AND month = ?
              AND cell_lat + 0.05 BETWEEN ? AND ?
              AND cell_lon + 0.05 BETWEEN ? AND ?
            """,
            [grid_path, year, month, min_lat, max_lat, min_lon, max_lon],
        ).fetchone()[0]
        assert math.isclose(calendar_count, direct_count, rel_tol=1e-12, abs_tol=1e-9), (
            f"Calendar/direct SQL mismatch for {year}-{month:02}: "
            f"{calendar_count} != {direct_count}"
        )
        print(
            f"Calendar/direct SQL {year}-{month:02} {bbox}: "
            f"{calendar_count:.2f} == {direct_count:.2f}"
        )

    cameroon_box = (2.0, 13.0, 8.5, 16.2)
    cameroon_rectangle = (
        (2.0, 8.5),
        (2.0, 16.2),
        (13.0, 16.2),
        (13.0, 8.5),
        (2.0, 8.5),
    )
    rectangle_calendar = get_calendar(
        connection, cameroon_rectangle, date(2000, 1, 1), date(2026, 10, 1)
    )
    box_calendar = get_calendar(
        connection, cameroon_box, date(2000, 1, 1), date(2026, 10, 1)
    )
    rectangle_total = float(rectangle_calendar["count"].sum())
    box_total = float(box_calendar["count"].sum())
    assert math.isclose(rectangle_total, box_total, rel_tol=1e-12, abs_tol=1e-9), (
        f"Rectangle polygon total {rectangle_total} differs from box total {box_total}"
    )
    print(f"Rectangle polygon versus box total: {rectangle_total:.2f} == {box_total:.2f}")

    triangle = ((2.0, 8.5), (2.0, 16.2), (13.0, 12.35), (2.0, 8.5))
    triangle_calendar = get_calendar(
        connection, triangle, date(2000, 1, 1), date(2026, 10, 1)
    )
    triangle_total = float(triangle_calendar["count"].sum())
    assert 0 < triangle_total <= box_total, (
        f"Triangle total must be positive and no greater than the box: {triangle_total}, {box_total}"
    )
    print(f"Triangle total: {triangle_total:.2f} (Cameroon box: {box_total:.2f})")

    ocean_polygon = (
        (0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)
    )
    ocean_calendar = get_calendar(
        connection, ocean_polygon, date(2000, 1, 1), date(2026, 10, 1)
    )
    ocean_total = float(ocean_calendar["count"].sum())
    assert ocean_total == 0, f"Expected no fires for ocean polygon, got {ocean_total}"
    print(f"Ocean polygon no-fires state: total={ocean_total:.2f}; query completed")

    oversized_polygon = (
        (0.0, -20.0), (0.0, 20.0), (50.0, 20.0), (50.0, -20.0), (0.0, -20.0)
    )
    refusal = area_refusal_message(oversized_polygon)
    assert refusal is not None and "2,000,000 km²" in refusal, refusal
    print(f"Oversized polygon refusal: {refusal}")

    south_box = (2.0, 6.0, 8.5, 16.2)
    north_box = (8.0, 13.0, 8.5, 16.2)
    regional_totals = []
    for bbox in (south_box, north_box):
        min_lat, max_lat, min_lon, max_lon = bbox
        total = connection.execute(
            """
            SELECT COALESCE(SUM(n_harmonized), 0)
            FROM read_parquet(?)
            WHERE cell_lat + 0.05 BETWEEN ? AND ?
              AND cell_lon + 0.05 BETWEEN ? AND ?
            """,
            [grid_path, min_lat, max_lat, min_lon, max_lon],
        ).fetchone()[0]
        regional_totals.append(float(total))
    print(
        f"South box total {south_box}: {regional_totals[0]:.2f}; "
        f"north box total {north_box}: {regional_totals[1]:.2f}"
    )
    assert regional_totals[0] != regional_totals[1], (
        f"South and north totals unexpectedly match: {regional_totals}"
    )

    zero_area = (11.5, 12.5, 15.2, 16.2)
    anomaly = get_latest_anomaly(
        connection,
        zero_area,
        date(2000, 1, 1),
        date(2026, 10, 1),
        today=date(2026, 11, 14),
    )
    assert anomaly is not None, "Expected a latest complete month in the mock data"
    assert anomaly["label"] == "no baseline", anomaly

    full_area_anomaly = get_latest_anomaly(
        connection,
        (2.0, 13.0, 8.5, 16.2),
        date(2000, 1, 1),
        date(2026, 10, 1),
        today=date(2026, 11, 14),
    )
    assert full_area_anomaly is not None, "Expected a populated-area anomaly"
    assert (full_area_anomaly["year"], full_area_anomaly["month"]) == (2026, 10)
    assert full_area_anomaly["provisional"] is True, full_area_anomaly
    assert full_area_anomaly["baseline_years"] == 26, full_area_anomaly

    shorter_range_anomaly = get_latest_anomaly(
        connection,
        (2.0, 13.0, 8.5, 16.2),
        date(2000, 1, 1),
        date(2020, 12, 1),
        today=date(2026, 11, 14),
    )
    assert shorter_range_anomaly is not None, "Expected the latest data month outside the selected range"
    assert (shorter_range_anomaly["year"], shorter_range_anomaly["month"]) == (2026, 10)

    calendar = get_calendar(
        connection,
        (2.0, 13.0, 8.5, 16.2),
        date(2000, 1, 1),
        date(2026, 10, 1),
    )
    expected_months = (2026 - 2000) * 12 + (10 - 1) + 1
    assert len(calendar) == expected_months, (
        f"Expected {expected_months} calendar months, got {len(calendar)}"
    )
    assert not calendar.duplicated(["year", "month"]).any(), "Calendar has duplicate year-month rows"

    connection.close()
    print("Data checks passed: schemas, unique cell-months, no-baseline area, complete calendar.")


if __name__ == "__main__":
    check_data()