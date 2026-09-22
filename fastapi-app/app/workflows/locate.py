"""范围定位四级降级：前端 AOI → 地块库已有范围 → 大模型包围盒 → 默认中心点。

大模型只允许给“大概在哪”，真正的裁剪始终按最终 AOI 几何在数据库里算。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.db.gis_store import gis
from app.llm.provider import chat_model
from app.llm.structured import ask_json
from app.services.extraction import default_aoi
from app.utils.geo import bbox_to_geom


class BBoxSpec(BaseModel):
    minx: float
    miny: float
    maxx: float
    maxy: float
    note: str = ""


SYSTEM = (
    "你是中国区划范围的粗定位助手。只给出目标区域的大致经纬度包围盒（WGS84，经度 73~135，纬度 3~54），"
    "宁可偏大也不要偏小，不要编造精确边界。"
)


async def locate_area(intent: dict[str, Any], aoi: Any) -> dict[str, Any]:
    if aoi:
        return {"aoi": aoi, "source": "前端框选 AOI", "level": 1}

    extent = await gis.plot_extent(
        land_types=[t for t in (intent.get("land_types") or []) if t] or None,
        region=intent.get("region") or "",
    )
    if extent and intent.get("region"):
        return {"aoi": _bbox_geojson(extent), "source": f"地块库已有范围（{intent['region']}）", "level": 2}

    model = chat_model(temperature=0.0)
    if model is not None and intent.get("region"):
        data, method = await ask_json(
            model, SYSTEM, f"请给出「{intent['region']}」的经纬度包围盒，用于地图提取范围。", BBoxSpec
        )
        if data and _sane_bbox(data):
            return {
                "aoi": _bbox_geojson([data["minx"], data["miny"], data["maxx"], data["maxy"]]),
                "source": f"大模型包围盒（{method}）",
                "level": 3,
            }

    return {"aoi": default_aoi(), "source": "默认中心点范围", "level": 4}


def _sane_bbox(data: dict[str, Any]) -> bool:
    try:
        minx, miny, maxx, maxy = float(data["minx"]), float(data["miny"]), float(data["maxx"]), float(data["maxy"])
    except (KeyError, TypeError, ValueError):
        return False
    return 73 <= minx <= 135 and 73 <= maxx <= 135 and 3 <= miny <= 54 and 3 <= maxy <= 54 and abs(maxx - minx) < 12


def _bbox_geojson(extent: list[float]) -> dict[str, Any]:
    geom = bbox_to_geom(*extent[:4]).__geo_interface__
    return {"type": "Polygon", "coordinates": geom["coordinates"]}
