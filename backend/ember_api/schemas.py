"""Request/response models (the HTTP contract)."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_YM = re.compile(r"^(\d{4})-(\d{2})$")


def parse_ym(value: str) -> tuple[int, int]:
    m = _YM.match(value)
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ValueError("expected YYYY-MM")
    return int(m.group(1)), int(m.group(2))


class BBox(BaseModel):
    south: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)


class AnalyzeRequest(BaseModel):
    geometry: dict | None = Field(default=None, description="GeoJSON Polygon/MultiPolygon/Feature")
    bbox: BBox | None = None
    start: str = Field(default="2000-11", description="YYYY-MM")
    end: str = Field(default="2026-12", description="YYYY-MM")
    baseline: tuple[int, int] | None = Field(default=None, description="years used as climatology")
    target: str | None = Field(default=None, description="YYYY-MM to compare against the climatology")

    @field_validator("start", "end", "target")
    @classmethod
    def _check_ym(cls, v):
        if v is not None:
            parse_ym(v)
        return v

    def area(self) -> dict:
        if self.geometry is None and self.bbox is None:
            raise ValueError("provide geometry or bbox")
        if self.geometry is not None:
            return self.geometry
        b = self.bbox
        from .geometry import bbox_ring
        return {"type": "Polygon", "coordinates": [bbox_ring(b.south, b.west, b.north, b.east)]}
