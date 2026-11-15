"""Client for the FIRMS area API (near-real-time hotspots of the last ~2 months).

Endpoint: /api/area/csv/{MAP_KEY}/{SOURCE}/{west,south,east,north}/{DAY_RANGE<=5}/{YYYY-MM-DD}
Rate limit: 5000 requests per 10 minutes per key. We need 12 per source for 60 days.
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from datetime import date, timedelta

import httpx
import pandas as pd

FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov"
MAX_DAYS_PER_REQUEST = 5  # FIRMS: 'Invalid day range. Expects [1..5]' for area requests
DEFAULT_SOURCES = ("VIIRS_NOAA20_NRT",)

Fetcher = Callable[[str], str]  # url -> response body


class FirmsUnavailable(RuntimeError):
    pass


def _redact(text: str) -> str:
    """Never leak the map key through error messages or logs."""
    key = os.environ.get("FIRMS_MAP_KEY")
    return text.replace(key, "<key>") if key else text


def _http_fetch(url: str, timeout: float = 60.0) -> str:
    try:
        resp = httpx.get(url, timeout=timeout)
    except httpx.HTTPError as exc:
        raise FirmsUnavailable(_redact(f"FIRMS request failed: {exc}")) from exc
    text = resp.text
    if resp.status_code >= 400:
        raise FirmsUnavailable(f"FIRMS answered {resp.status_code}: {text[:120].strip()!r}")
    if text.lstrip().lower().startswith("invalid") or "<html" in text[:200].lower():
        raise FirmsUnavailable(f"FIRMS rejected the request: {text[:120]!r}")
    return text


class FirmsClient:
    """Fetches raw hotspots for a bounding box; the fetcher is injectable for tests."""

    def __init__(self, map_key: str | None = None, fetch: Fetcher = _http_fetch, base: str = FIRMS_BASE):
        self.map_key = map_key or os.environ.get("FIRMS_MAP_KEY")
        self.fetch = fetch
        self.base = base

    @property
    def configured(self) -> bool:
        return bool(self.map_key)

    def area_url(self, source: str, bbox: tuple[float, float, float, float], days: int, start: date) -> str:
        s, w, n, e = bbox
        return f"{self.base}/api/area/csv/{self.map_key}/{source}/{w:.3f},{s:.3f},{e:.3f},{n:.3f}/{days}/{start:%Y-%m-%d}"

    def area_csv(self, source: str, bbox: tuple[float, float, float, float], days: int, start: date) -> str:
        if not self.configured:
            raise FirmsUnavailable("FIRMS_MAP_KEY is not configured on the server")
        return self.fetch(self.area_url(source, bbox, min(max(days, 1), MAX_DAYS_PER_REQUEST), start))

    def hotspots(self, bbox: tuple[float, float, float, float], start: date, end: date,
                 sources: tuple[str, ...] = DEFAULT_SOURCES) -> pd.DataFrame:
        """All hotspots between start and end (inclusive), in windows of 10 days."""
        frames = []
        for source in sources:
            cursor = start
            while cursor <= end:
                days = min(MAX_DAYS_PER_REQUEST, (end - cursor).days + 1)
                text = self.area_csv(source, bbox, days, cursor)
                if text.strip() and "\n" in text.strip():
                    frames.append(pd.read_csv(io.StringIO(text)))
                cursor += timedelta(days=days)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)


def recent_hotspots_csv(bbox: tuple[float, float, float, float], days: int = 7,
                        source: str = "VIIRS_NOAA20_NRT", map_key: str | None = None) -> str:
    """Raw CSV of the last `days` days, as served by FIRMS (used by the export endpoint)."""
    client = FirmsClient(map_key)
    start = date.today() - timedelta(days=min(max(days, 1), MAX_DAYS_PER_REQUEST) - 1)
    return client.area_csv(source, bbox, days, start)
