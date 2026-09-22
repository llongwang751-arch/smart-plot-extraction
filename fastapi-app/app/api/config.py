"""系统配置接口：前端表单由 /api/config/schema 驱动自动渲染，新增配置只加一行 schema。"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.config.runtime import runtime
from app.core.deps import require_admin as _admin
from app.db.gis_store import gis
from app.llm.provider import test_chat, test_embedding
from app.models.schemas import ConfigUpdateReq, TestReq
from app.rag import vectorstore
from app.services import tiles

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/config", tags=["系统配置"], dependencies=[Depends(_admin)])


@router.get("/schema")
async def get_schema() -> dict[str, Any]:
    return {"groups": runtime.view(), "masked": "******", "hot_reload": True}


@router.put("")
async def update_config(req: ConfigUpdateReq) -> dict[str, Any]:
    changed = await runtime.update(req.values or {})
    return {
        "changed": sorted(changed),
        "groups": runtime.view(),
        "message": "已保存并热生效" if changed else "没有需要保存的变更",
    }


@router.get("/status")
async def config_status() -> dict[str, Any]:
    from app.db.sys_db import sys_db_url

    return {
        "gis": await gis.status(),
        "vector": await vectorstore.backend_status(),
        "sys_db": sys_db_url().split("://")[0],
        "postgres_configured": bool(runtime.postgres_dsn),
        "llm": {
            "configured": runtime.llm_ready,
            "base_url": runtime.get_str("llm.base_url"),
            "model": runtime.get_str("llm.chat_model"),
            "max_steps": runtime.get_int("llm.max_steps"),
        },
        "embed": {"model": runtime.get_str("embed.model"), "dim": runtime.get_int("embed.dim")},
        "chunks": await vectorstore.chunk_count(),
        "maps": {
            "tianditu": bool(runtime.get_str("tianditu.token")),
            "tianditu_sk": runtime.get_bool("tianditu.use_sk"),
            "geovis": bool(runtime.get_str("geovis.token")),
        },
    }


@router.post("/test")
async def run_test(req: TestReq) -> dict[str, Any]:
    if req.target == "llm":
        return {"target": "llm", "result": await test_chat()}
    if req.target == "embed":
        vectorstore.reset()
        return {"target": "embed", "result": await test_embedding()}
    if req.target == "sys_db":
        from app.db.sys_db import ping_sys_db

        try:
            url = await ping_sys_db()
            return {"target": "sys_db", "result": {"ok": True, "url": url.split("://")[0] + "://***", "message": "业务库连接正常"}}
        except Exception as exc:
            return {"target": "sys_db", "result": {"ok": False, "message": f"{type(exc).__name__}: {str(exc)[:200]}"}}
    if req.target == "gis":
        status = await gis.status()
        status["message"] = (
            "PostGIS + pgvector 主路径" if status.get("mode") == "postgis"
            else f"已降级到本地引擎（{status.get('error') or runtime.postgres_dsn or '未配置 PostGIS DSN'}）"
        )
        return {"target": "gis", "result": status}
    if req.target == "tiles":
        return {"target": "tiles", "result": await tiles.check_tiles()}
    raise HTTPException(status_code=400, detail="未知的测试目标")
