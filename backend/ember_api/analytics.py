"""Pure computations on a selection of harmonized cell-months.

Every function takes the frame returned by HarmonizedStore.select and returns
plain Python structures ready for JSON. No I/O here, so it is trivially testable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MONTHS = list(range(1, 13))


def monthly_series(sel: pd.DataFrame) -> pd.DataFrame:
    """Sum over cells -> one row per year-month, with band and dominant source."""
    if sel.empty:
        return pd.DataFrame(columns=["year", "month", "n_harm", "n_low", "n_high", "n_modis", "n_viirs", "provisional", "source"])
    sel = sel.copy()
    sel["source"] = sel["source"].astype(str)
    if "provisional" not in sel.columns:
        sel["provisional"] = False
    g = sel.groupby(["year", "month"], sort=True)
    out = g.agg(n_harm=("n_harm", "sum"), n_low=("n_low", "sum"), n_high=("n_high", "sum"),
                n_modis=("n_modis", "sum"), n_viirs=("n_viirs_snpp", "sum"),
                provisional=("provisional", "any")).reset_index()
    dominant = g["source"].agg(lambda s: s.value_counts().idxmax()).reset_index(name="source")
    out = out.merge(dominant, on=["year", "month"])
    out[["n_harm", "n_low", "n_high"]] = out[["n_harm", "n_low", "n_high"]].round(1)
    return out


def complete_series(series: pd.DataFrame, start: tuple[int, int], end: tuple[int, int]) -> pd.DataFrame:
    """Fill the months with no detections with zeros so calendars have no holes."""
    idx = pd.period_range(f"{start[0]}-{start[1]:02d}", f"{end[0]}-{end[1]:02d}", freq="M")
    frame = pd.DataFrame({"year": idx.year, "month": idx.month})
    out = frame.merge(series, on=["year", "month"], how="left")
    for col in ("n_harm", "n_low", "n_high", "n_modis", "n_viirs"):
        out[col] = out[col].fillna(0)
    out["source"] = out["source"].fillna("none")
    if "provisional" not in out.columns:
        out["provisional"] = False
    out["provisional"] = out["provisional"].fillna(False).astype(bool)
    return out


def calendar(series: pd.DataFrame) -> dict:
    """year x month matrix of harmonized counts."""
    years = sorted(series["year"].unique().tolist())
    pivot = series.pivot_table(index="year", columns="month", values="n_harm", aggfunc="sum").reindex(index=years, columns=MONTHS)
    return {"years": years, "months": MONTHS,
            "values": [[None if pd.isna(v) else float(v) for v in row] for row in pivot.to_numpy()]}


def climatology(series: pd.DataFrame, baseline_years: tuple[int, int] | None = None) -> dict:
    """Per calendar month: median, quartiles, min, max over the baseline years."""
    base = series if baseline_years is None else series[series["year"].between(*baseline_years)]
    stats = base.groupby("month")["n_harm"].agg(median="median", p25=lambda s: s.quantile(.25),
                                                p75=lambda s: s.quantile(.75), min="min", max="max", years="size")
    stats = stats.reindex(MONTHS).fillna(0)
    return {"months": MONTHS, **{k: [float(x) for x in stats[k]] for k in ("median", "p25", "p75", "min", "max")},
            "n_years": [int(x) for x in stats["years"]],
            "baseline_years": list(baseline_years) if baseline_years else [int(base["year"].min()), int(base["year"].max())] if len(base) else None}


def anomaly(series: pd.DataFrame, year: int, month: int, baseline_years: tuple[int, int] | None = None) -> dict:
    """How the target month compares with the same month of other years."""
    row = series[(series["year"] == year) & (series["month"] == month)]
    value = float(row["n_harm"].sum()) if len(row) else 0.0
    others = series[(series["month"] == month) & (series["year"] != year)]
    if baseline_years:
        others = others[others["year"].between(*baseline_years)]
    hist = others["n_harm"].to_numpy(dtype="float64")
    if hist.size == 0:
        return {"year": year, "month": month, "value": value, "median": None, "ratio": None,
                "percentile": None, "n_years": 0, "label": "no baseline"}
    median = float(np.median(hist))
    percentile = float((hist < value).mean() * 100 + (hist == value).mean() * 50)
    ratio = value / median if median > 0 else None
    if percentile >= 90:
        label = "exceptionally high"
    elif percentile >= 75:
        label = "above normal"
    elif percentile <= 10:
        label = "exceptionally low"
    elif percentile <= 25:
        label = "below normal"
    else:
        label = "near normal"
    return {"year": year, "month": month, "value": value, "median": median,
            "ratio": None if ratio is None else round(ratio, 2), "percentile": round(percentile, 1),
            "n_years": int(hist.size), "label": label,
            "band": {"low": float(row["n_low"].sum()) if len(row) else 0.0,
                     "high": float(row["n_high"].sum()) if len(row) else 0.0}}


def season(clim: dict, threshold_share: float = 0.2) -> dict:
    """Fire season = contiguous months around the peak whose median stays above
    `threshold_share` of the peak median (cyclic). Returns onset, peak, end (1-12)."""
    med = np.asarray(clim["median"], dtype="float64")
    total = med.sum()
    if total <= 0:
        return {"onset": None, "peak": None, "end": None, "peak_share": None, "length_months": None}
    peak = int(np.argmax(med))
    threshold = threshold_share * med[peak]
    onset = peak
    while med[(onset - 1) % 12] >= threshold and (onset - 1) % 12 != peak:
        onset = (onset - 1) % 12
    end = peak
    while med[(end + 1) % 12] >= threshold and (end + 1) % 12 != onset:
        end = (end + 1) % 12
    length = (end - onset) % 12 + 1
    return {"onset": onset + 1, "peak": peak + 1, "end": end + 1,
            "peak_share": round(float(med[peak] / total), 3), "length_months": int(length)}


def yearly_ranking(series: pd.DataFrame, top: int = 5) -> list[dict]:
    yearly = series.groupby("year")["n_harm"].sum().sort_values(ascending=False)
    return [{"year": int(y), "n_harm": float(round(v, 1))} for y, v in yearly.head(top).items()]


def cell_summary(sel: pd.DataFrame, max_cells: int = 5000) -> list[dict]:
    """Mean yearly harmonized count per cell, for map shading (capped for payload size)."""
    if sel.empty:
        return []
    n_years = max(1, sel["year"].nunique())
    cells = sel.groupby(["lat_cell", "lon_cell"])["n_harm"].sum().div(n_years).round(1)
    cells = cells.sort_values(ascending=False).head(max_cells)
    return [{"lat": float(lat), "lon": float(lon), "n_per_year": float(v)} for (lat, lon), v in cells.items()]
