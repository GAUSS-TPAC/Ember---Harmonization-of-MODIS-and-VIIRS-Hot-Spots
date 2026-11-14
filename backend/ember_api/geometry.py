"""Minimal planar geometry on lat/lon, enough to select grid cells by polygon.

Cells are tested by their centre. No shapely dependency so the API runs anywhere.
"""

from __future__ import annotations

import numpy as np


def bbox_of(ring: list[list[float]]) -> tuple[float, float, float, float]:
    """(south, west, north, east) of a GeoJSON ring [[lon, lat], ...]."""
    arr = np.asarray(ring, dtype="float64")
    return float(arr[:, 1].min()), float(arr[:, 0].min()), float(arr[:, 1].max()), float(arr[:, 0].max())


def points_in_ring(lats: np.ndarray, lons: np.ndarray, ring: list[list[float]]) -> np.ndarray:
    """Even-odd ray casting, vectorised over points. `ring` is a GeoJSON ring (lon, lat)."""
    poly = np.asarray(ring, dtype="float64")
    if len(poly) < 3:
        return np.zeros(len(lats), dtype=bool)
    x, y = np.asarray(lons, dtype="float64"), np.asarray(lats, dtype="float64")
    inside = np.zeros(len(x), dtype=bool)
    px, py = poly[:, 0], poly[:, 1]
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi, xj, yj = px[i], py[i], px[j], py[j]
        crosses = (yi > y) != (yj > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            x_at_y = (xj - xi) * (y - yi) / (yj - yi) + xi
        inside ^= crosses & (x < x_at_y)
        j = i
    return inside


def rings_of(geometry: dict) -> list[list[list[float]]]:
    """Outer rings of a GeoJSON Polygon or MultiPolygon (holes are ignored)."""
    kind = geometry.get("type")
    if kind == "Polygon":
        return [geometry["coordinates"][0]]
    if kind == "MultiPolygon":
        return [poly[0] for poly in geometry["coordinates"]]
    if kind == "Feature":
        return rings_of(geometry["geometry"])
    raise ValueError(f"unsupported geometry type: {kind}")


def bbox_ring(south: float, west: float, north: float, east: float) -> list[list[float]]:
    return [[west, south], [east, south], [east, north], [west, north], [west, south]]
