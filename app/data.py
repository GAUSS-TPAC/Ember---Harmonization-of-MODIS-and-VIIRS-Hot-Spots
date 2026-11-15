from datetime import date
from pathlib import Path
from typing import Dict, Optional, Tuple

import duckdb
import pandas as pd
import streamlit as st
from shapely import covers, points

from app.anomaly import classify_anomaly
from app.area import Area, area_bounds, area_polygon, normalize_area
from app.config import DATA_DIR, PARQUET_PATHS


def open_database() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(database=":memory:")


def get_validation_table() -> pd.DataFrame:
    return pd.read_parquet(PARQUET_PATHS["validation"])[
        ["region", "holdout_years", "r", "mape"]
    ]


def get_data_month_range(
    connection: duckdb.DuckDBPyConnection,
) -> Optional[Tuple[date, date]]:
    """Return the earliest and latest year-month present in the grid data."""
    return _get_data_month_range_cached(_data_file_version())


def _data_file_version() -> Tuple[str, int, int]:
    path = _parquet_path("grid_monthly")
    stat = path.stat()
    return str(path), stat.st_mtime_ns, stat.st_size


@st.cache_data(show_spinner=False)
def _get_data_month_range_cached(
    file_version: Tuple[str, int, int],
) -> Optional[Tuple[date, date]]:
    connection = open_database()
    try:
        row = connection.execute(
            f"""
            SELECT MIN(make_date(year, month, 1)), MAX(make_date(year, month, 1))
            FROM {_grid_sql()}
            """,
            [file_version[0]],
        ).fetchone()
    finally:
        connection.close()
    if row is None or row[0] is None or row[1] is None:
        return None
    return row[0], row[1]


def _month_text(value: date) -> str:
    return value.strftime("%Y-%m-01")


def _parquet_path(table: str) -> Path:
    return PARQUET_PATHS[table]


def _validate_months(start_month: date, end_month: date) -> None:
    if start_month.day != 1 or end_month.day != 1:
        raise ValueError("Start and end must be the first day of a month.")
    if start_month > end_month:
        raise ValueError("Start month must not be after end month.")


def _grid_sql() -> str:
    return "read_parquet(?)"


def get_calendar(
    connection: duckdb.DuckDBPyConnection,
    area: Area,
    start_month: date,
    end_month: date,
) -> pd.DataFrame:
    """Return one zero-filled row for every month in the inclusive range."""
    _validate_months(start_month, end_month)
    return _get_calendar_cached(
        normalize_area(area), start_month, end_month, _data_file_version()
    )


@st.cache_data(show_spinner=False)
def _get_calendar_cached(
    area: Area,
    start_month: date,
    end_month: date,
    file_version: Tuple[str, int, int],
) -> pd.DataFrame:
    min_lat, max_lat, min_lon, max_lon = area_bounds(area)
    connection = open_database()
    try:
        cells = connection.execute(
            f"""
            SELECT cell_lat, cell_lon, year, month, n_harmonized, source, provisional
            FROM {_grid_sql()} AS g
            WHERE g.cell_lat + 0.05 BETWEEN ? AND ?
              AND g.cell_lon + 0.05 BETWEEN ? AND ?
              AND make_date(g.year, g.month, 1) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
            """,
            [
                file_version[0],
                min_lat,
                max_lat,
                min_lon,
                max_lon,
                _month_text(start_month),
                _month_text(end_month),
            ],
        ).fetchdf()
    finally:
        connection.close()

    polygon = area_polygon(area)
    if not cells.empty:
        is_inside = covers(
            polygon,
            points(
                cells["cell_lon"].to_numpy() + 0.05,
                cells["cell_lat"].to_numpy() + 0.05,
            ),
        )
        cells = cells.loc[is_inside].copy()
        cells["month_date"] = pd.to_datetime(
            dict(year=cells["year"], month=cells["month"], day=1)
        )
        totals = (
            cells.groupby("month_date", as_index=False)
            .agg(
                count=("n_harmonized", "sum"),
                source=("source", lambda values: ", ".join(sorted(set(values)))),
                provisional=("provisional", "any"),
            )
        )
    else:
        totals = pd.DataFrame(
            {
                "month_date": pd.Series(dtype="datetime64[ns]"),
                "count": pd.Series(dtype="float64"),
                "source": pd.Series(dtype="object"),
                "provisional": pd.Series(dtype="bool"),
            }
        )

    months = pd.DataFrame(
        {"month_date": pd.date_range(start_month, end_month, freq="MS")}
    )
    calendar = months.merge(totals, on="month_date", how="left")
    calendar["year"] = calendar["month_date"].dt.year.astype("int32")
    calendar["month"] = calendar["month_date"].dt.month.astype("int32")
    calendar["count"] = pd.to_numeric(calendar["count"], errors="coerce").fillna(0.0)
    calendar["source"] = calendar["source"].fillna("no detections")
    calendar["provisional"] = (
        calendar["provisional"].astype("boolean").fillna(False).astype(bool)
    )
    calendar["terra_only"] = calendar["month_date"].between(
        pd.Timestamp("2000-01-01"), pd.Timestamp("2002-06-01")
    )
    return calendar[
        ["year", "month", "count", "source", "provisional", "terra_only"]
    ]


def get_seasonal_profile(
    connection: duckdb.DuckDBPyConnection,
    area: Area,
    start_month: date,
    end_month: date,
) -> pd.DataFrame:
    """Return month-of-year quantiles over zero-filled monthly area totals."""
    _validate_months(start_month, end_month)
    return _get_seasonal_profile_cached(
        normalize_area(area), start_month, end_month, _data_file_version()
    )


@st.cache_data(show_spinner=False)
def _get_seasonal_profile_cached(
    area: Area,
    start_month: date,
    end_month: date,
    file_version: Tuple[str, int, int],
) -> pd.DataFrame:
    calendar = _get_calendar_cached(area, start_month, end_month, file_version)
    profile = (
        calendar.groupby("month")["count"]
        .agg(
            median="median",
            p25=lambda values: values.quantile(0.25),
            p75=lambda values: values.quantile(0.75),
        )
        .reset_index()
    )
    peak_month = int(profile.loc[profile["median"].idxmax(), "month"])
    profile["peak_month"] = peak_month
    return profile


def get_latest_anomaly(
    connection: duckdb.DuckDBPyConnection,
    area: Area,
    start_month: date,
    end_month: date,
    today: Optional[date] = None,
) -> Optional[Dict[str, object]]:
    """Compare the latest complete month with other years' same-month totals."""
    _validate_months(start_month, end_month)
    today = today or date.today()
    return _get_latest_anomaly_cached(
        normalize_area(area), start_month, end_month, today, _data_file_version()
    )


@st.cache_data(show_spinner=False)
def _get_latest_anomaly_cached(
    area: Area,
    start_month: date,
    end_month: date,
    today: date,
    file_version: Tuple[str, int, int],
) -> Optional[Dict[str, object]]:
    connection = open_database()
    try:
        tested_month = connection.execute(
            f"""
            SELECT MAX(make_date(year, month, 1))
            FROM {_grid_sql()}
            WHERE make_date(year, month, 1) < CAST(? AS DATE)
            """,
            [file_version[0], _month_text(date(today.year, today.month, 1))],
        ).fetchone()[0]
    finally:
        connection.close()
    if tested_month is None:
        return None

    tested_month = tested_month.date() if hasattr(tested_month, "date") else tested_month
    tested = _get_calendar_cached(area, tested_month, tested_month, file_version).iloc[0]
    calendar = _get_calendar_cached(area, start_month, end_month, file_version)
    baseline = calendar.loc[
        (calendar["month"] == tested_month.month)
        & (calendar["year"] != tested_month.year),
        "count",
    ]
    count = float(tested["count"])
    median = float(baseline.median()) if not baseline.empty else 0.0
    ratio, label = classify_anomaly(count, median)
    percentile = float((baseline <= count).mean()) if not baseline.empty else None
    return {
        "year": tested_month.year,
        "month": tested_month.month,
        "count": count,
        "median": median,
        "p25": float(baseline.quantile(0.25)) if not baseline.empty else None,
        "p75": float(baseline.quantile(0.75)) if not baseline.empty else None,
        "ratio": ratio,
        "percentile": percentile,
        "label": label,
        "provisional": bool(tested["provisional"]),
        "baseline_years": int(len(baseline)),
    }