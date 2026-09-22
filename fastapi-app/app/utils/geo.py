"""几何工具：AOI 归一化、椭球面面积、规则网格、简化与 GeoJSON 互转。

本地降级引擎用它复刻 PostGIS 的语义（::geography 面积 / 求交 / 保拓扑简化）。
"""
from __future__ import annotations

import json
import math
from typing import Any, Iterable

from shapely.geometry import MultiPolygon, Polygon, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

EARTH_RADIUS = 6378137.0
M2_PER_DEG_LAT = 111_320.0  # 1 度纬度约为 111.32 km


def loads_geojson(raw: Any) -> Any:
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def to_geojson(geom) -> dict[str, Any]:
    from shapely.geometry import mapping

    return mapping(geom)


def normalize_geom(raw: Any):
    """把前端各种写法（GeoJSON / bbox / WKT 字符串）统一成 Shapely 面要素。"""
    if raw is None:
        return None
    if isinstance(raw, BaseGeometry):  # 内部调用直接传 Shapely 对象
        return polygons_only(raw)
    data = loads_geojson(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
    geom = None
    if isinstance(data, dict):
        if data.get("type") == "FeatureCollection":
            geoms = [shape(f["geometry"]) for f in data.get("features", []) if f.get("geometry")]
            geom = unary_union(geoms) if geoms else None
        elif data.get("type") == "Feature":
            geom = shape(data.get("geometry") or {})
        elif data.get("type") in {"Polygon", "MultiPolygon", "GeometryCollection"}:
            geom = shape(data)
        elif {"minx", "miny", "maxx", "maxy"} <= set(data):
            geom = box(data["minx"], data["miny"], data["maxx"], data["maxy"])
        elif {"xmin", "ymin", "xmax", "ymax"} <= set(data):
            geom = box(data["xmin"], data["ymin"], data["xmax"], data["ymax"])
    elif isinstance(data, (list, tuple)):
        numbers = [v for v in data if isinstance(v, (int, float))]
        if len(numbers) == 4:  # [minx, miny, maxx, maxy]
            geom = box(min(numbers[0], numbers[2]), min(numbers[1], numbers[3]),
                       max(numbers[0], numbers[2]), max(numbers[1], numbers[3]))
    if geom is None or geom.is_empty:
        return None
    return polygons_only(geom)


def polygons_only(geom):
    """丢弃求交产生的点、线残留，等价于 ST_CollectionExtract(geom, 3)。"""
    polys = [g for g in getattr(geom, "geoms", []) if isinstance(g, (Polygon, MultiPolygon))]
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon):
        return geom
    polys = list(polys)
    if not polys:
        rings = list(polygonize(geom.boundary if geom.geom_type.startswith("Line") else geom))
        polys = rings
    if not polys:
        return None
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


def keep_within(geom, clipper):
    inter = geom.intersection(clipper)
    return polygons_only(inter)


def bbox(geom) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = geom.bounds
    return round(minx, 6), round(miny, 6), round(maxx, 6), round(maxy, 6)


def ring_area_spherical(ring: Iterable[tuple[float, float]]) -> float:
    coords = list(ring)
    if len(coords) < 4:
        return 0.0
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        total += math.radians(lon2 - lon1) * (2 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2)))
    return abs(total * EARTH_RADIUS * EARTH_RADIUS / 2.0)


def geodetic_area_m2(geom) -> float:
    """球面近似面积，对应 PostGIS 的 ::geography 口径（避免高纬度平面面积低估）。"""
    if geom is None or geom.is_empty:
        return 0.0
    if isinstance(geom, MultiPolygon):
        return sum(geodetic_area_m2(g) for g in geom.geoms)
    if not isinstance(geom, Polygon):
        return 0.0
    area = ring_area_spherical(geom.exterior.coords)
    for inner in geom.interiors:
        area -= ring_area_spherical(inner.coords)
    return max(area, 0.0)


def deg_step_for(size_m: float, lat: float) -> tuple[float, float]:
    """米 → 度，经度方向按 cos(纬度) 修正实际距离。"""
    dlat = size_m / M2_PER_DEG_LAT
    cos_lat = max(abs(math.cos(math.radians(lat))), 0.05)
    dlon = size_m / (M2_PER_DEG_LAT * cos_lat)
    return dlon, dlat


def make_grid(geom, size_m: float, max_cells: int = 6000) -> tuple[list[Polygon], float]:
    """按网格边长切分 AOI 外接矩形；格数超限时自动放大边长，防止请求爆炸。"""
    minx, miny, maxx, maxy = bbox(geom)
    edge = max(size_m, 1.0)
    for _ in range(8):
        dlon, dlat = deg_step_for(edge, (miny + maxy) / 2)
        cols = max(int(math.ceil((maxx - minx) / dlon)), 1)
        rows = max(int(math.ceil((maxy - miny) / dlat)), 1)
        if cols * rows <= max_cells:
            break
        edge *= 2
    cells: list[Polygon] = []
    y = miny
    for _ in range(rows):
        x = minx
        y2 = min(y + dlat, maxy)
        for _ in range(cols):
            x2 = min(x + dlon, maxx)
            if x2 > x and y2 > y:
                cells.append(box(x, y, x2, y2))
            x = x2
        y = y2
    return cells, edge


def simplify(geom, tol: float):
    """Douglas-Peucker 保拓扑简化，对应 ST_SimplifyPreserveTopology。"""
    if not tol or geom is None:
        return geom
    try:
        out = geom.simplify(tol, preserve_topology=True)
    except Exception:
        return geom
    return polygons_only(out) or geom


def bbox_to_geom(minx: float, miny: float, maxx: float, maxy: float) -> Polygon:
    return box(min(minx, maxx), min(miny, maxy), max(minx, maxx), max(miny, maxy))


def buffer_km(center: tuple[float, float], km: float) -> Polygon:
    lon, lat = center
    half_deg = max(km, 0.1) / 100.0
    return box(lon - half_deg, lat - half_deg * 0.8, lon + half_deg, lat + half_deg * 0.8)


def feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}
