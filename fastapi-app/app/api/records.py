"""提取记录接口：每次提取的需求原文、AOI、结果、统计、执行轨迹、结论都可回看。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_current_user
from app.db.gis_store import gis
from app.models.sys_tables import SysUser
from app.services.extraction import save_features_as_plots

router = APIRouter(prefix="/api/records", tags=["提取记录"])


@router.get("")
async def list_records(
    page: int = 1,
    size: int = 10,
    mode: str = "",
    user: SysUser = Depends(get_current_user),
) -> dict[str, Any]:
    items, total = await gis.list_tasks(page=page, size=size, mode=mode)
    if user.role != "admin":
        items = [item for item in items if not item.get("user_id") or int(item["user_id"]) == user.id]
    slim = []
    for item in items:
        slim.append(
            {
                "id": item["id"],
                "title": item["title"],
                "query": item["query"],
                "mode": item["mode"],
                "engine": item["engine"],
                "status": item["status"],
                "error": item["error"],
                "elapsed_ms": item["elapsed_ms"],
                "created_at": item["created_at"],
                "count": (item.get("statistics") or {}).get("count", 0),
                "total_area_mu": (item.get("statistics") or {}).get("total_area_mu", 0),
                "analysis": (item.get("analysis") or "")[:160],
            }
        )
    return {"total": total, "page": page, "size": size, "items": slim}


@router.get("/{task_id}")
async def get_record(task_id: int, user: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    task = await _owned(task_id, user)
    return task


@router.post("/{task_id}/save-plots")
async def save_plots(task_id: int, region: str = "", user: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    task = await _owned(task_id, user)
    features = [{**(f.get("properties") or {}), "geometry": f.get("geometry")} for f in (task.get("geojson") or {}).get("features", [])]
    if not features:
        raise HTTPException(status_code=400, detail="该记录没有可保存的地块")
    created = await save_features_as_plots(features, source_task=task_id, region=region)
    return {"created": created, "total": await gis.plot_count(), "message": f"已把 {created} 个地块存为正式地块"}


@router.delete("/{task_id}")
async def delete_record(task_id: int, user: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    await _owned(task_id, user)
    await gis.delete_task(task_id)
    return {"ok": True, "message": "记录已删除"}


async def _owned(task_id: int, user: SysUser) -> dict[str, Any]:
    task = await gis.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="提取记录不存在")
    if user.role != "admin" and int(task.get("user_id") or 0) not in (0, user.id):
        raise HTTPException(status_code=403, detail="无权查看他人的提取记录")
    return task
