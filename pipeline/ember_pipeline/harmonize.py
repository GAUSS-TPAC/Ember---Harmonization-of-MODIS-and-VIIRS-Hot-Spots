"""Stage 2: put MODIS and VIIRS monthly counts on one VIIRS-equivalent scale.

Method (kept deliberately simple and explainable):

1. Reference sensor = VIIRS on Suomi-NPP. Where it observed, its counts are used as is.
2. For months outside the reference coverage, counts of another platform are
   multiplied by a transfer factor k = sum(reference) / sum(platform), estimated
   over the years both observed, in the same cell. Cells with too few detections
   fall back to a coarser block, then to the global factor (Protected Variations
   against sparsity).
3. The spread of the yearly ratios around k gives an uncertainty band.

Everything here works on the `hotspots_monthly` contract (see docs/DATA_CONTRACT.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

CELL = ["lat_cell", "lon_cell"]
MONTH_KEY = CELL + ["year", "month"]


@dataclass(frozen=True)
class Coverage:
    """First and last (year, month) a platform delivered data."""

    start: tuple[int, int]
    end: tuple[int, int] = (9999, 12)

    def contains(self, year: pd.Series, month: pd.Series) -> pd.Series:
        ym = year.astype(int) * 100 + month.astype(int)
        return (ym >= self.start[0] * 100 + self.start[1]) & (ym <= self.end[0] * 100 + self.end[1])


@dataclass(frozen=True)
class HarmonizationConfig:
    reference: str = "VIIRS_SNPP"
    # Platforms that can stand in for the reference, in order of preference, and
    # the sum of columns each one is built from (Terra+Aqua act as one "MODIS").
    fallbacks: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("VIIRS_NOAA20", ("VIIRS_NOAA20",)),
        ("MODIS", ("MODIS_Terra", "MODIS_Aqua")),
        ("MODIS_Terra", ("MODIS_Terra",)),
    )
    coverage: dict = field(default_factory=lambda: {
        "VIIRS_SNPP": Coverage((2012, 1), (2026, 11)),
        "VIIRS_NOAA20": Coverage((2018, 4)),
        "MODIS": Coverage((2002, 7)),
        "MODIS_Terra": Coverage((2000, 11)),
    })
    fit_years: tuple[int, int] = (2012, 2025)
    block_deg: float = 1.0
    min_platform_count: int = 50
    spread_quantiles: tuple[float, float] = (0.1, 0.9)


# --------------------------------------------------------------------------- shaping

def pivot_platforms(monthly: pd.DataFrame) -> pd.DataFrame:
    """hotspots_monthly -> one row per cell-month, one count column per platform."""
    wide = (
        monthly.groupby(MONTH_KEY + ["platform"], observed=True)["n"].sum()
        .unstack("platform", fill_value=0)
        .reset_index()
    )
    wide.columns.name = None
    for col in ("MODIS_Terra", "MODIS_Aqua", "VIIRS_SNPP", "VIIRS_NOAA20", "VIIRS_NOAA21"):
        if col not in wide.columns:
            wide[col] = 0
    return wide


def _group_count(wide: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    return wide[list(columns)].sum(axis=1)


def _block(values: pd.Series, block_deg: float) -> pd.Series:
    return np.floor(values / block_deg) * block_deg


# --------------------------------------------------------------------------- fitting

def fit_factors(monthly: pd.DataFrame, cfg: HarmonizationConfig = HarmonizationConfig()) -> pd.DataFrame:
    """Per-cell transfer factors reference/platform with hierarchical fallback.

    Returns one row per cell with, for each fallback platform P:
    k_P (factor), level_P ("cell" | "block" | "global"), lo_P and hi_P (multipliers
    bounding the uncertainty band).
    """
    wide = pivot_platforms(monthly)
    y0, y1 = cfg.fit_years
    ref_cov = cfg.coverage[cfg.reference]
    cells = wide[CELL].drop_duplicates().reset_index(drop=True)
    out = cells.copy()

    for name, columns in cfg.fallbacks:
        cov = cfg.coverage[name]
        both = wide["year"].between(y0, y1) & ref_cov.contains(wide["year"], wide["month"]) \
            & cov.contains(wide["year"], wide["month"])
        sub = wide.loc[both, MONTH_KEY + [cfg.reference]].copy()
        sub["p"] = _group_count(wide.loc[both], columns).values
        sub["r"] = sub[cfg.reference]
        sub["blat"], sub["blon"] = _block(sub["lat_cell"], cfg.block_deg), _block(sub["lon_cell"], cfg.block_deg)

        total_r, total_p = sub["r"].sum(), sub["p"].sum()
        k_global = total_r / total_p if total_p > 0 else np.nan

        by_cell = sub.groupby(CELL)[["r", "p"]].sum()
        by_block = sub.groupby(["blat", "blon"])[["r", "p"]].sum()
        yearly_block = sub.groupby(["blat", "blon", "year"])[["r", "p"]].sum()
        yearly_block = yearly_block[yearly_block["p"] > 0]
        yearly_block["ratio"] = yearly_block["r"] / yearly_block["p"]
        q_lo, q_hi = cfg.spread_quantiles
        if len(yearly_block):
            spread = yearly_block.groupby(["blat", "blon"])["ratio"].quantile([q_lo, q_hi]).unstack()
            spread.columns = ["lo", "hi"]
        else:
            spread = pd.DataFrame(columns=["lo", "hi"],
                                  index=pd.MultiIndex.from_arrays([[], []], names=["blat", "blon"]), dtype=float)
        g_spread = yearly_block.groupby("year")[["r", "p"]].sum()
        g_ratio = (g_spread["r"] / g_spread["p"]).replace([np.inf], np.nan).dropna()
        g_lo, g_hi = (g_ratio.quantile(q_lo), g_ratio.quantile(q_hi)) if len(g_ratio) else (np.nan, np.nan)

        cell_idx = pd.MultiIndex.from_frame(out[CELL])
        c = by_cell.reindex(cell_idx)
        blk_key = pd.MultiIndex.from_arrays([_block(out["lat_cell"], cfg.block_deg), _block(out["lon_cell"], cfg.block_deg)])
        b = by_block.reindex(blk_key)
        s = spread.reindex(blk_key)

        use_cell = (c["p"].values >= cfg.min_platform_count)
        use_block = ~use_cell & (b["p"].values >= cfg.min_platform_count)
        k = np.where(use_cell, c["r"].values / np.where(c["p"].values > 0, c["p"].values, np.nan),
            np.where(use_block, b["r"].values / np.where(b["p"].values > 0, b["p"].values, np.nan), k_global))
        level = np.where(use_cell, "cell", np.where(use_block, "block", "global"))
        lo = np.where(use_cell | use_block, s["lo"].values, g_lo)
        hi = np.where(use_cell | use_block, s["hi"].values, g_hi)
        with np.errstate(invalid="ignore", divide="ignore"):
            lo_mult = np.where(k > 0, lo / k, 1.0)
            hi_mult = np.where(k > 0, hi / k, 1.0)
        out[f"k_{name}"] = k
        out[f"level_{name}"] = level
        out[f"lo_{name}"] = np.nan_to_num(lo_mult, nan=1.0)
        out[f"hi_{name}"] = np.nan_to_num(hi_mult, nan=1.0)
    return out


# --------------------------------------------------------------------------- applying

HARMONIZED_COLUMNS = MONTH_KEY + ["n_harm", "n_low", "n_high", "source",
                                  "n_modis", "n_viirs_snpp", "n_viirs_noaa20"]


def apply_factors(monthly: pd.DataFrame, factors: pd.DataFrame,
                  cfg: HarmonizationConfig = HarmonizationConfig()) -> pd.DataFrame:
    """Build the harmonized monthly series for every cell-month with detections."""
    wide = pivot_platforms(monthly).merge(factors, on=CELL, how="left")
    n = len(wide)
    n_harm = np.full(n, np.nan)
    n_low = np.full(n, np.nan)
    n_high = np.full(n, np.nan)
    source = np.full(n, "none", dtype=object)

    ref_in = cfg.coverage[cfg.reference].contains(wide["year"], wide["month"]).values
    n_harm[ref_in] = wide.loc[ref_in, cfg.reference].values
    n_low[ref_in] = n_high[ref_in] = n_harm[ref_in]
    source[ref_in] = cfg.reference

    assigned = ref_in.copy()
    for name, columns in cfg.fallbacks:
        cov_in = cfg.coverage[name].contains(wide["year"], wide["month"]).values
        pick = ~assigned & cov_in
        if not pick.any():
            continue
        count = _group_count(wide.loc[pick], columns).values
        k = wide.loc[pick, f"k_{name}"].values
        est = count * k
        n_harm[pick] = est
        n_low[pick] = est * wide.loc[pick, f"lo_{name}"].values
        n_high[pick] = est * wide.loc[pick, f"hi_{name}"].values
        source[pick] = name
        assigned |= pick

    out = wide[MONTH_KEY].copy()
    out["n_harm"] = np.round(n_harm, 2)
    out["n_low"] = np.round(np.minimum(n_low, n_harm), 2)
    out["n_high"] = np.round(np.maximum(n_high, n_harm), 2)
    out["source"] = source
    out["n_modis"] = wide["MODIS_Terra"] + wide["MODIS_Aqua"]
    out["n_viirs_snpp"] = wide["VIIRS_SNPP"]
    out["n_viirs_noaa20"] = wide["VIIRS_NOAA20"]
    return out[HARMONIZED_COLUMNS]


def harmonize(monthly: pd.DataFrame, cfg: HarmonizationConfig = HarmonizationConfig()) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Convenience: fit then apply. Returns (harmonized, factors)."""
    factors = fit_factors(monthly, cfg)
    return apply_factors(monthly, factors, cfg), factors


# --------------------------------------------------------------------------- validation

def validate(monthly: pd.DataFrame, fit_years: tuple[int, int], test_years: tuple[int, int],
             cfg: HarmonizationConfig = HarmonizationConfig(), platform: str = "MODIS") -> dict:
    """Fit on `fit_years`, predict the reference from `platform` on `test_years`.

    Metrics are computed on block × month totals (what a user of the calendar sees).
    """
    fit_cfg = HarmonizationConfig(**{**cfg.__dict__, "fit_years": fit_years})
    factors = fit_factors(monthly, fit_cfg)
    wide = pivot_platforms(monthly).merge(factors, on=CELL, how="left")
    columns = dict(cfg.fallbacks)[platform]
    mask = wide["year"].between(*test_years) & cfg.coverage[cfg.reference].contains(wide["year"], wide["month"]) \
        & cfg.coverage[platform].contains(wide["year"], wide["month"])
    w = wide.loc[mask].copy()
    w["pred"] = _group_count(w, columns) * w[f"k_{platform}"]
    w["raw"] = _group_count(w, columns)
    w["obs"] = w[cfg.reference]
    w["blat"], w["blon"] = _block(w["lat_cell"], cfg.block_deg), _block(w["lon_cell"], cfg.block_deg)
    agg = w.groupby(["blat", "blon", "year", "month"])[["pred", "raw", "obs"]].sum()
    agg = agg[(agg["obs"] > 0) | (agg["pred"] > 0)]

    def metrics(pred: pd.Series, obs: pd.Series) -> dict:
        err = pred - obs
        r = float(np.corrcoef(pred, obs)[0, 1]) if len(obs) > 1 and obs.std() > 0 and pred.std() > 0 else float("nan")
        return {"n_points": int(len(obs)), "bias_ratio": float(pred.sum() / obs.sum()) if obs.sum() else float("nan"),
                "mae": float(err.abs().mean()), "pearson_r": r}

    return {"fit_years": fit_years, "test_years": test_years, "platform": platform,
            "raw": metrics(agg["raw"], agg["obs"]), "harmonized": metrics(agg["pred"], agg["obs"])}
