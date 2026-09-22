"""智能地块提取平台 · FastAPI 后端入口。

启动顺序：业务库建表 → 配置播种与装载 → 订阅配置变更 → 空间库（PostGIS 失败即降级）。
"""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.api import api_router  # noqa: E402
from app.config.env import env  # noqa: E402
from app.config.runtime import runtime  # noqa: E402
from app.db import gis_store, sys_db  # noqa: E402
from app.rag import vectorstore  # noqa: E402

APP_TITLE = "智能地块提取平台"
APP_VERSION = "1.0.0"
FRONTEND_DIST = BASE_DIR.parent / "vue" / "dist"


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        encoding="utf-8",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)


log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await sys_db.init_sys_db()
    await runtime.load()
    runtime.on_change(gis_store.on_config_change)
    runtime.on_change(vectorstore.on_config_change)
    await gis_store.gis.setup()
    status = await gis_store.gis.status()
    log.info(
        "%s v%s 就绪 | 空间引擎=%s | 地块=%s | 大模型=%s",
        APP_TITLE,
        APP_VERSION,
        status.get("mode"),
        status.get("plots"),
        runtime.get_str("llm.chat_model") if runtime.llm_ready else "未配置（走降级路径）",
    )
    if status.get("mode") != "postgis":
        log.warning("PostGIS 不可用，已降级到本地引擎：%s", gis_store.gis.error or "未配置 PostGIS DSN")
    yield
    await gis_store.gis.dispose()
    await sys_db.close_sys_db()


app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
    description="自然语言描述需求 + 地图框选范围 → LangGraph 五节点工作流 → PostGIS 空间提取 → 统计与结论",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=env.origin_list or ["*"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/api/health", tags=["概览"])
async def health() -> dict[str, object]:
    return {
        "app": APP_TITLE,
        "version": APP_VERSION,
        "gis": await gis_store.gis.status(),
        "vector": await vectorstore.backend_status(),
        "llm": {
            "configured": runtime.llm_ready,
            "model": runtime.get_str("llm.chat_model"),
            "base_url": runtime.get_str("llm.base_url"),
        },
        "docs": "/docs",
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("未处理异常：%s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"服务内部错误：{type(exc).__name__}: {str(exc)[:300]}"})


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        target = FRONTEND_DIST / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")
else:

    @app.get("/", include_in_schema=False)
    async def index() -> JSONResponse:
        return JSONResponse(
            {
                "app": APP_TITLE,
                "api_docs": "/docs",
                "hint": "前端开发服务器默认在 http://localhost:5173；执行 npm run build 后本服务会直接托管页面",
            }
        )


if __name__ == "__main__":
    uvicorn.run("main:app", host=env.app_host, port=env.app_port, reload=False, log_config=None)
