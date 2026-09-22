"""GIS 存储层公共部分：两种引擎（PostGIS / 本地）产出的行结构在此统一。"""
from __future__ import annotations

import json
from typing import Any, Iterable

from app.utils.geo import bbox as geom_bbox
from app.utils.geo import geodetic_area_m2
from app.utils.units import MU_PER_M2, m2_to_mu

PLOT_FIELDS = ("id", "code", "name", "land_type", "region", "owner", "area_m2", "area_mu", "origin", "source_task")


def plot_dict(row, geometry: dict | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {key: getattr(row, key) for key in PLOT_FIELDS if hasattr(row, key)}
    for key in ("area_m2", "area_mu"):
        out[key] = float(out.get(key) or 0)
    raw = geometry if geometry is not None else getattr(row, "geojson", None)
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = None
    out["geometry"] = raw
    created = getattr(row, "created_at", None)
    out["created_at"] = created.strftime("%Y-%m-%d %H:%M:%S") if created else ""
    return out


def feature(plot: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {k: v for k, v in plot.items() if k != "geometry"},
        "geometry": plot.get("geometry"),
    }


def feature_collection(plots: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": [feature(p) for p in plots if p.get("geometry")]}


def summarize(plots: list[dict[str, Any]], *, aoi=None, engine: str = "local", origin: str = "vector") -> dict[str, Any]:
    """统计口径：数量、面积（平方米/亩）、地类构成、区域构成、包围盒。"""
    by_type: dict[str, dict[str, float]] = {}
    by_region: dict[str, dict[str, float]] = {}
    total_m2 = 0.0
    boxes: list[tuple[float, float, float, float]] = []
    for plot in plots:
        area = float(plot.get("area_m2") or 0)
        total_m2 += area
        for key, bucket in (("land_type", by_type), ("region", by_region)):
            name = plot.get(key) or "未标注"
            slot = bucket.setdefault(name, {"count": 0, "area_m2": 0.0})
            slot["count"] += 1
            slot["area_m2"] += area

    def _group(bucket: dict) -> list[dict[str, Any]]:
        rows = [
            {"name": name, "count": int(v["count"]), "area_m2": round(v["area_m2"], 2), "area_mu": m2_to_mu(v["area_m2"])}
            for name, v in bucket.items()
        ]
        return sorted(rows, key=lambda r: r["area_m2"], reverse=True)

    areas = [float(p.get("area_mu") or 0) for p in plots]
    result: dict[str, Any] = {
        "count": len(plots),
        "total_area_m2": round(total_m2, 2),
        "total_area_mu": m2_to_mu(total_m2),
        "avg_area_mu": round(sum(areas) / len(areas), 2) if areas else 0.0,
        "max_area_mu": round(max(areas), 2) if areas else 0.0,
        "by_land_type": _group(by_type),
        "by_region": _group(by_region),
        "engine": engine,
        "origin": origin,
    }
    if aoi is not None and not aoi.is_empty:
        result["bbox"] = list(geom_bbox(aoi))
        result["aoi_area_m2"] = round(geodetic_area_m2(aoi), 2)
        result["aoi_area_mu"] = m2_to_mu(geodetic_area_m2(aoi))
    return result


def parse_json(raw: Any, fallback: Any) -> Any:
    if raw in (None, ""):
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return fallback


def task_dict(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "query": row.query,
        "mode": row.mode,
        "engine": row.engine,
        "aoi": parse_json(row.aoi, None),
        "land_types": [t for t in (row.land_types or "").split(",") if t],
        "min_area_mu": float(row.min_area_mu or 0),
        "geojson": parse_json(row.geojson, {"type": "FeatureCollection", "features": []}),
        "statistics": parse_json(row.statistics, {}),
        "trace": parse_json(row.trace, []),
        "analysis": row.analysis or "",
        "status": row.status,
        "error": row.error or "",
        "elapsed_ms": int(row.elapsed_ms or 0),
        "user_id": int(row.user_id or 0),
        "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else "",
    }


def mu_of(m2: float) -> float:
    return round(float(m2 or 0) * MU_PER_M2, 2)
