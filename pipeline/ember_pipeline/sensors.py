"""Sensor-specific knowledge: platform naming and quality filters.

This is the only module that knows how MODIS and VIIRS CSVs differ. Everything
downstream works on the normalized frame it produces (Protected Variations).
"""

from __future__ import annotations

import pandas as pd

# (instrument, satellite code as written in FIRMS archive or NRT files) -> platform
_PLATFORMS: dict[tuple[str, str], str] = {
    ("MODIS", "Terra"): "MODIS_Terra",
    ("MODIS", "T"): "MODIS_Terra",
    ("MODIS", "Aqua"): "MODIS_Aqua",
    ("MODIS", "A"): "MODIS_Aqua",
    ("VIIRS", "N"): "VIIRS_SNPP",
    ("VIIRS", "NPP"): "VIIRS_SNPP",
    ("VIIRS", "1"): "VIIRS_NOAA20",
    ("VIIRS", "N20"): "VIIRS_NOAA20",
    ("VIIRS", "2"): "VIIRS_NOAA21",
    ("VIIRS", "N21"): "VIIRS_NOAA21",
}

# FIRMS "type" attribute (archive rows only): 0 = presumed vegetation fire.
VEGETATION_FIRE = 0

# MODIS confidence is 0-100; FIRMS calls < 30 "low".
MODIS_MIN_CONFIDENCE = 30
# VIIRS confidence is categorical: l(ow) / n(ominal) / h(igh).
VIIRS_KEPT_CONFIDENCE = {"n", "h", "nominal", "high"}

REQUIRED_COLUMNS = (
    "latitude", "longitude", "acq_date", "satellite", "instrument",
    "confidence", "frp", "daynight",
)


class SchemaError(ValueError):
    """Raised when an input frame does not look like a FIRMS hotspot file."""


def platform_of(instrument: pd.Series, satellite: pd.Series) -> pd.Series:
    keys = list(zip(instrument.astype(str).str.strip(), satellite.astype(str).str.strip()))
    return pd.Series([_PLATFORMS.get(k) for k in keys], index=instrument.index, dtype="object")


def quality_mask(df: pd.DataFrame) -> pd.Series:
    """True for rows worth counting: confident detections of vegetation fires."""
    instrument = df["instrument"].astype(str).str.strip().str.upper()
    conf = df["confidence"]

    is_modis = instrument.eq("MODIS")
    modis_ok = pd.to_numeric(conf, errors="coerce").ge(MODIS_MIN_CONFIDENCE)
    viirs_ok = conf.astype(str).str.strip().str.lower().isin(VIIRS_KEPT_CONFIDENCE)
    keep = (is_modis & modis_ok) | (~is_modis & viirs_ok)

    if "type" in df.columns:
        fire_type = pd.to_numeric(df["type"], errors="coerce")
        # NRT rows have no type: keep them rather than drop the whole recent window.
        keep &= fire_type.isna() | fire_type.eq(VEGETATION_FIRE)
    return keep


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Validate, filter and reduce a raw FIRMS frame to the columns the grid needs.

    Output columns: platform, latitude, longitude, acq_date, frp, is_day.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaError(f"missing columns: {missing}")

    kept = df.loc[quality_mask(df)]
    platform = platform_of(kept["instrument"], kept["satellite"])
    unknown = platform.isna()
    if unknown.any():
        bad = kept.loc[unknown, ["instrument", "satellite"]].drop_duplicates().values.tolist()
        raise SchemaError(f"unknown instrument/satellite pairs: {bad}")

    return pd.DataFrame({
        "platform": platform.values,
        "latitude": kept["latitude"].astype("float64").values,
        "longitude": kept["longitude"].astype("float64").values,
        "acq_date": kept["acq_date"].values,
        "frp": pd.to_numeric(kept["frp"], errors="coerce").fillna(0.0).astype("float64").values,
        "is_day": kept["daynight"].astype(str).str.strip().str.upper().eq("D").values,
    })
