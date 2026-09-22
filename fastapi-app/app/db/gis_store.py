"""GIS 引擎路由：PostGIS 可用走主路径，连不上自动降级到本地引擎，并把原因暴露给前端。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config.env import env
from app.config.runtime import runtime
from app.db.local_store import LocalGisStore
from app.db.postgis_store import PostgisGisStore

log = logging.getLogger(__name__)


class GisManager:
    def __init__(self) -> None:
        self.store: Any = None
        self.mode: str = ""
        self.error: str = ""
        self.dsn: str = ""

    async def setup(self) -> None:
        dsn = runtime.postgres_dsn
        if dsn:
            try:
                store = PostgisGisStore(dsn, runtime.get_str("gis.schema", "public"))
                await asyncio.wait_for(store.connect(), timeout=8)
                self.store = store
                self.mode = "postgis"
                self.dsn = dsn
                self.error = ""
                log.info("空间库：PostGIS 主路径已就绪")
                return
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
                log.warning("PostGIS 不可用（%s），降级到本地引擎", self.error)
        store = LocalGisStore(env.local_gis_url_abs)
        await store.connect()
        self.store = store
        self.mode = "local"
        self.dsn = env.local_gis_url_abs
        log.info("空间库：本地引擎（Shapely）就绪")

    async def dispose(self) -> None:
        if self.store is not None:
            try:
                await self.store.dispose()
            except Exception:  # pragma: no cover
                pass
            self.store = None

    async def rebuild(self) -> None:
        """配置里改了 PostGIS 连接：重建连接池 + 建扩展 + 建表。"""
        await self.dispose()
        await self.setup()

    async def status(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode, "degraded": self.mode != "postgis", "error": self.error}
        if self.store is not None:
            try:
                payload.update(await self.store.health())
            except Exception as exc:  # pragma: no cover
                payload["ok"] = False
                payload["error"] = str(exc)[:200]
        return payload

    def __getattr__(self, name: str):
        store = self.__dict__.get("store")
        if store is None:
            raise RuntimeError("GIS 存储层尚未初始化")
        return getattr(store, name)


gis = GisManager()


async def on_config_change(changed: set[str]) -> None:
    if any(key.startswith("gis.") for key in changed):
        await gis.rebuild()
