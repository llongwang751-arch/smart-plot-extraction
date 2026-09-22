"""系统首页概览数据。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.config.runtime import runtime
from app.core.deps import get_current_user
from app.core.deps import user_out
from app.db.gis_store import gis
from app.models.sys_tables import KbDocument, SysUser
from app.rag import vectorstore

router = APIRouter(prefix="/api/dashboard", tags=["概览"])


@router.get("")
async def dashboard(user: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    stats = await gis.plot_statistics()
    _tasks, task_total = await gis.list_tasks(page=1, size=5)
    recent, _ = await gis.list_tasks(page=1, size=5)
    vector = await vectorstore.backend_status()
    return {
        "user": user_out(user),
        "plots": {
            "count": stats.get("count", 0),
            "total_area_mu": stats.get("total_area_mu", 0),
            "total_area_m2": stats.get("total_area_m2", 0),
            "avg_area_mu": stats.get("avg_area_mu", 0),
            "max_area_mu": stats.get("max_area_mu", 0),
            "by_land_type": stats.get("by_land_type", []),
            "by_region": stats.get("by_region", [])[:6],
        },
        "records": {"total": task_total, "recent": [
            {
                "id": t["id"],
                "title": t["title"],
                "mode": t["mode"],
                "status": t["status"],
                "count": (t.get("statistics") or {}).get("count", 0),
                "total_area_mu": (t.get("statistics") or {}).get("total_area_mu", 0),
                "created_at": t["created_at"],
            }
            for t in recent
        ]},
        "knowledge": {
            "docs": await KbDocument.all().count(),
            "chunks": vector.get("chunks", 0),
            "backend": vector.get("backend"),
            "ok": bool(vector.get("ok")),
            "message": vector.get("message", ""),
        },
        "engine": {"mode": gis.mode, "degraded": gis.mode != "postgis", "error": gis.error},
        "llm": {"configured": runtime.llm_ready, "model": runtime.get_str("llm.chat_model"), "max_steps": runtime.get_int("llm.max_steps")},
        "maps": {
            "tianditu": bool(runtime.get_str("tianditu.token")),
            "geovis": bool(runtime.get_str("geovis.token")),
        },
    }
