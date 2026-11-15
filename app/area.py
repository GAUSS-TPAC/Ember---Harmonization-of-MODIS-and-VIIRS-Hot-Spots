from datetime import date
from math import cos, radians
from typing import Optional, Tuple, Union

from shapely.geometry import Polygon, box


BoundingBox = Tuple[float, float, float, float]
LatLon = Tuple[float, float]
PolygonCoordinates = Tuple[LatLon, ...]
Area = Union[BoundingBox, PolygonCoordinates]
AREA_LIMIT_KM2 = 2_000_000.0


def normalize_area(area: Area) -> Area:
    """Return a stable area key rounded to four decimal places."""
    if len(area) == 4 and all(isinstance(value, (int, float)) for value in area):
        return tuple(round(float(value), 4) for value in area)  # type: ignore[return-value]
    coordinates = tuple((round(float(lat), 4), round(float(lon), 4)) for lat, lon in area)
    if coordinates and coordinates[0] != coordinates[-1]:
        coordinates += (coordinates[0],)
    return coordinates


def area_bounds(area: Area) -> BoundingBox:
    if len(area) == 4 and all(isinstance(value, (int, float)) for value in area):
        return tuple(float(value) for value in area)  # type: ignore[return-value]
    coordinates = area
    latitudes = [lat for lat, _ in coordinates]
    longitudes = [lon for _, lon in coordinates]
    return min(latitudes), max(latitudes), min(longitudes), max(longitudes)


def area_polygon(area: Area) -> Polygon:
    min_lat, max_lat, min_lon, max_lon = area_bounds(area)
    if len(area) == 4 and all(isinstance(value, (int, float)) for value in area):
        return box(min_lon, min_lat, max_lon, max_lat)
    return Polygon([(lon, lat) for lat, lon in area])


def area_area_km2(area: Area) -> float:
    min_lat, max_lat, min_lon, max_lon = area_bounds(area)
    mean_latitude = radians((min_lat + max_lat) / 2)
    longitude_km = (max_lon - min_lon) * 111.32 * cos(mean_latitude)
    latitude_km = (max_lat - min_lat) * 111.32
    if len(area) == 4 and all(isinstance(value, (int, float)) for value in area):
        return max(0.0, longitude_km * latitude_km)

    polygon = area_polygon(area)
    projected = [
        (lon * 111.32 * cos(mean_latitude), lat * 111.32)
        for lon, lat in polygon.exterior.coords
    ]
    return abs(
        sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(projected, projected[1:])
        )
    ) / 2


def area_refusal_message(area: Area) -> Optional[str]:
    area_km2 = area_area_km2(area)
    if area_km2 > AREA_LIMIT_KM2:
        return (
            f"Selected area is approximately {area_km2:,.0f} km² and exceeds "
            f"the 2,000,000 km² limit. Choose a smaller area."
        )
    return None


def calendar_filename(area: Area, start: date, end: date) -> str:
    min_lat, max_lat, min_lon, max_lon = area_bounds(area)
    area_label = (
        f"lat{min_lat:g}-{max_lat:g}_lon{min_lon:g}-{max_lon:g}"
    )
    if not (len(area) == 4 and all(isinstance(value, (int, float)) for value in area)):
        area_label = f"polygon_{area_label}"
    return f"calendar_{area_label}_{start:%Y-%m}_{end:%Y-%m}.csv"
