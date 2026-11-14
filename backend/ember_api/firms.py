"""Thin client for the FIRMS near-real-time area API (raw hotspots of the last days)."""

from __future__ import annotations

import os

import httpx

FIRMS_AREA = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{area}/{days}/{date}"


class FirmsUnavailable(RuntimeError):
    pass


def recent_hotspots_csv(bbox: tuple[float, float, float, float], days: int = 7,
                        source: str = "VIIRS_NOAA20_NRT", date: str | None = None,
                        map_key: str | None = None, timeout: float = 60.0) -> str:
    """Return the CSV text FIRMS serves for the bbox (south, west, north, east)."""
    key = map_key or os.environ.get("FIRMS_MAP_KEY")
    if not key:
        raise FirmsUnavailable("FIRMS_MAP_KEY is not configured on the server")
    s, w, n, e = bbox
    url = FIRMS_AREA.format(key=key, source=source, area=f"{w},{s},{e},{n}", days=min(max(days, 1), 10),
                            date=date or "")
    url = url.rstrip("/")
    try:
        resp = httpx.get(url, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise FirmsUnavailable(f"FIRMS request failed: {exc}") from exc
    return resp.text
