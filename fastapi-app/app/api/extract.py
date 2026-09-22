"""地块提取接口：智能提取（LangGraph 五节点）与纯计算提取（不经大模型）。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.core.deps import get_current_user
from app.db.gis_store import gis
from app.models.schemas import ExtractReq, SavePlotsReq
from app.models.sys_tables import SysUser
from app.services.extraction import save_features_as_plots
from app.utils.geo import bbox
from app.utils.geo import normalize_geom
from app.workflows.graph import run_workflow

router = APIRouter(prefix="/api/extract", tags=["地块提取"])


@router.post("/run")
async def extract(req: ExtractReq, user: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    if req.mode == "space" and not req.aoi:
        raise HTTPException(status_code=400, detail="纯计算模式必须先框选提取范围（AOI）")
    if req.mode == "smart" and not (req.query or "").strip() and not req.aoi:
        raise HTTPException(status_code=400, detail="请描述提取需求或在地图上框选范围")

    result = await run_workflow(
        query=req.query,
        mode=req.mode,
        aoi=req.aoi,
        land_types=req.land_types,
        min_area_mu=req.min_area_mu,
        user_id=user.id,
    )
    result["task_id"] = 0
    if req.save:
        result["task_id"] = await gis.save_task(
            {
                "title": (req.query or ("纯计算提取" if req.mode == "space" else "智能提取"))[:100],
                "query": req.query,
                "mode": req.mode,
                "engine": result.get("engine", gis.mode),
                "aoi": result.get("aoi"),
                "land_types": (result.get("intent") or {}).get("land_types") or req.land_types,
                "min_area_mu": (result.get("intent") or {}).get("min_area_mu") or req.min_area_mu,
                "geojson": result.get("geojson"),
                "statistics": result.get("statistics"),
                "trace": result.get("trace"),
                "analysis": result.get("analysis"),
                "status": "failed" if result.get("error") else "ok",
                "error": result.get("error", ""),
                "elapsed_ms": result.get("elapsed_ms", 0),
                "user_id": user.id,
            }
        )
    return result


@router.post("/save-plots")
async def save_as_plots(req: SavePlotsReq, _: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    features = req.features
    source_task = req.task_id
    if not features and req.task_id:
        task = await gis.get_task(req.task_id)
        if not task:
            raise HTTPException(status_code=404, detail="提取记录不存在")
        features = [
            {**(f.get("properties") or {}), "geometry": f.get("geometry")}
            for f in (task.get("geojson") or {}).get("features", [])
        ]
    if not features:
        raise HTTPException(status_code=400, detail="没有可保存的地块")
    created = await save_features_as_plots(features, source_task=source_task, region=req.region)
    return {"created": created, "total": await gis.plot_count(), "message": f"已保存 {created} 个地块入库"}


@router.get("/geojson/{task_id}")
async def download_geojson(task_id: int, _: SysUser = Depends(get_current_user)) -> Response:
    task = await gis.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="提取记录不存在")
    payload = json.dumps(task.get("geojson") or {"type": "FeatureCollection", "features": []}, ensure_ascii=False)
    return Response(
        content=payload,
        media_type="application/geo+json",
        headers={"content-disposition": f'attachment; filename="plots-{task_id}.geojson"'},
    )


@router.get("/context")
async def extract_context(_: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    """进页面就带上：当前引擎、地块总览包围盒、可用的提取参数默认值。"""
    from app.config.runtime import runtime
    from app.services.extraction import default_aoi

    stats = await gis.plot_statistics()
    extent = await gis.plot_extent()
    center = runtime.get_str("extract.default_center", "116.397,39.908")
    try:
        lon, lat = [float(v) for v in center.replace("，", ",").split(",")[:2]]
    except ValueError:
        lon, lat = 116.397, 39.908
    aoi_geom = normalize_geom(default_aoi())
    return {
        "engine": gis.mode,
        "degraded": gis.mode != "postgis",
        "degrade_reason": gis.error,
        "plots": {"count": stats.get("count", 0), "total_area_mu": stats.get("total_area_mu", 0)},
        "extent": extent or bbox(aoi_geom),
        "default_aoi": default_aoi(),
        "land_types": ["耕地", "园地", "林地", "草地", "建设用地", "水域", "未利用地"],
        "min_area_mu": runtime.get_float("extract.min_area_mu", 0),
        "grid_size": runtime.get_int("extract.grid_size", 300),
        "llm": {"configured": runtime.llm_ready, "model": runtime.get_str("llm.chat_model")},
        "kb": await _kb_brief(),
    }


async def _kb_brief() -> dict[str, Any]:
    from app.models.sys_tables import KbDocument
    from app.rag import vectorstore

    backend = await vectorstore.backend_status()
    return {"docs": await KbDocument.all().count(), "backend": backend.get("backend"), "chunks": backend.get("chunks", 0)}
