"""业务库连接与初始化（Tortoise）。默认 SQLite 零依赖可跑，配 mysql:// 即切 MySQL。"""
from __future__ import annotations

import logging

from tortoise import Tortoise

from app.config.env import env
from app.config.schema import GROUPS  # noqa: F401  (保证配置组可用)
from app.models.sys_tables import MODEL_MODULES

log = logging.getLogger(__name__)

_sys_url = ""


def sys_db_url() -> str:
    return env.sys_db_url_abs


async def init_sys_db() -> None:
    global _sys_url
    _sys_url = sys_db_url()
    await Tortoise.init(
        db_url=_sys_url,
        modules={"models": MODEL_MODULES},
        use_tz=False,
        timezone="Asia/Shanghai",
        # lifespan 与请求不在同一个 task，需要开启全局上下文回退
        _enable_global_fallback=True,
    )
    await Tortoise.generate_schemas(safe=True)
    await seed_admin()
    log.info("业务库就绪：%s", _sys_url.split("://")[0])


async def close_sys_db() -> None:
    await Tortoise.close_connections()


async def seed_admin() -> None:
    from app.core.security import hash_password
    from app.models.sys_tables import SysUser

    if await SysUser.filter(username=env.admin_username).exists():
        return
    await SysUser.create(
        username=env.admin_username,
        password_hash=hash_password(env.admin_password),
        nickname="系统管理员",
        email="",
        role="admin",
        enabled=True,
    )
    log.info("已创建默认管理员 %s / %s（请尽快改密）", env.admin_username, env.admin_password)


async def ping_sys_db() -> str:
    from tortoise.connection import connections

    conn = connections.get("default")
    await conn.execute_query("SELECT 1")
    return _sys_url or sys_db_url()
