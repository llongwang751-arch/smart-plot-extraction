"""底图与瓦片接口：瓦片走后端代理，凭据不下发浏览器；错误码翻译成中文建议。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.core.deps import get_current_user
from app.models.sys_tables import SysUser
from app.services import tiles

router = APIRouter(prefix="/api/maps", tags=["底图"])


@router.get("/basemaps")
async def basemaps(_: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "items": tiles.basemaps(),
        "fallback": {
            "key": "osm",
            "name": "OpenStreetMap（备用）",
            "rule": "连续 3 张瓦片报错后自动切换，保证地图永远可见",
            "url": "/api/maps/tile?provider=osm&layer=default&z={z}&x={x}&y={y}",
        },
        "errors": {"tianditu": tiles.TIANDITU_CODES, "geovis": tiles.GEOVIS_CODES},
    }


@router.get("/tile")
async def tile(
    provider: str = Query(pattern="^(tianditu|geovis|osm)$"),
    layer: str = "img",
    z: int = Query(ge=0, le=20),
    x: int = Query(ge=0),
    y: int = Query(ge=0),
    _: SysUser = Depends(get_current_user),
) -> Response:
    status, ctype, body, error = await tiles.fetch_tile(provider, layer, z, x, y)
    if error:
        return Response(status_code=status, media_type="application/json", content=_json(error))
    return Response(status_code=status, media_type=ctype, content=body)


@router.post("/check")
async def check(_: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    return await tiles.check_tiles()


@router.get("/last-error")
async def last_error(
    provider: str = Query(pattern="^(tianditu|geovis|osm)$"),
    http_status: int = 403,
    body: str = "",
    _: SysUser = Depends(get_current_user),
) -> dict[str, Any]:
    """把上游返回的错误码/错误体翻译成中文排查建议，用于配置页与地图提示。"""
    error = tiles.translate_error(provider, http_status, body.encode("utf-8"), {}) or {
        "advice": "该响应看起来是正常瓦片，未识别到错误码",
    }
    return {"provider": provider, **error}


def _json(data: Any) -> bytes:
    import json

    return json.dumps(data, ensure_ascii=False).encode("utf-8")
