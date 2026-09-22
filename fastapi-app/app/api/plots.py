"""地块管理接口：CRUD + 组合查询 + GeoJSON 导出 + 示例数据。面积由存储层入库时计算。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_current_user
from app.db.base import feature_collection
from app.db.gis_store import gis
from app.models.schemas import PlotReq, PlotUpdateReq, SampleReq
from app.models.sys_tables import SysUser
from app.services.seed import generate_sample_plots
from app.utils.units import LAND_TYPES

router = APIRouter(prefix="/api/plots", tags=["地块管理"])


@router.get("")
async def list_plots(
    name: str = "",
    land_type: str = "",
    region: str = "",
    page: int = 1,
    size: int = Query(default=20, le=500),
    _: SysUser = Depends(get_current_user),
) -> dict[str, Any]:
    items, total = await gis.list_plots(name=name, land_type=land_type, region=region, page=page, size=size)
    return {"total": total, "page": page, "size": size, "engine": gis.mode, "items": items}


@router.get("/options")
async def plot_options(_: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    stats = await gis.plot_statistics()
    regions = []
    rows, _total = await gis.list_plots(page=1, size=500)
    for row in rows:
        if row.get("region") and row["region"] not in regions:
            regions.append(row["region"])
    return {
        "land_types": LAND_TYPES,
        "regions": regions,
        "count": stats.get("count", 0),
        "total_area_mu": stats.get("total_area_mu", 0),
        "by_land_type": stats.get("by_land_type", []),
        "engine": gis.mode,
    }


@router.get("/geojson")
async def plots_geojson(
    land_type: str = "",
    region: str = "",
    limit: int = Query(default=1000, le=5000),
    _: SysUser = Depends(get_current_user),
) -> dict[str, Any]:
    rows, total = await gis.list_plots(land_type=land_type, region=region, page=1, size=500)
    rows = rows[:limit]
    return {"total": total, "returned": len(rows), **feature_collection(rows)}


@router.post("/sample")
async def create_sample(req: SampleReq, _: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    result = await generate_sample_plots(count=req.count, seed=req.seed, overwrite=req.overwrite)
    return {**result, "message": f"已生成 {result['created']} 个示例地块，当前库中共 {result['total']} 个"}


@router.get("/{plot_id}")
async def get_plot(plot_id: int, _: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    plot = await gis.get_plot(plot_id)
    if not plot:
        raise HTTPException(status_code=404, detail="地块不存在")
    return plot


@router.post("")
async def create_plot(req: PlotReq, _: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    if req.geometry is None:
        raise HTTPException(status_code=400, detail="请先在地图上绘制地块边界")
    try:
        plot = await gis.create_plot(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return plot


@router.put("/{plot_id}")
async def update_plot(plot_id: int, req: PlotUpdateReq, _: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        plot = await gis.update_plot(plot_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not plot:
        raise HTTPException(status_code=404, detail="地块不存在")
    return plot


@router.delete("/{plot_id}")
async def delete_plot(plot_id: int, _: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    if not await gis.delete_plot(plot_id):
        raise HTTPException(status_code=404, detail="地块不存在")
    return {"ok": True, "message": "地块已删除"}
