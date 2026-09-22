"""运行期配置：数据库为唯一真源，改完下一行代码调用即生效（热更新）。

- 冷启动：用 .env 的默认值播种缺失项
- 读取：全部走内存缓存，避免每次 LLM 调用查库
- 变更：写库 + 刷新缓存 + 通知订阅方（连接池重建、模型工厂失效）
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from .schema import GROUPS, find_item, schema_items
from .env import env

log = logging.getLogger(__name__)

MASK = "******"
ChangeHook = Callable[[set[str]], Awaitable[None]]


def _coerce(item: dict[str, Any] | None, raw: Any) -> Any:
    if raw is None:
        return None
    kind = (item or {}).get("type", "string")
    if kind == "number":
        try:
            text = str(raw).strip()
            if text == "":
                return None
            return float(text) if "." in text or "e" in text.lower() else int(text)
        except ValueError:
            log.warning("配置项 %s 不是合法数字：%r，按默认值处理", (item or {}).get("key"), raw)
            return (item or {}).get("default")
    if kind == "boolean":
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in {"1", "true", "yes", "on", "是"}
    return str(raw)


class RuntimeConfig:
    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._hooks: list[ChangeHook] = []
        self._loaded = False

    # ---------------- 装载 ----------------
    async def load(self) -> None:
        from app.models.sys_tables import SysConfig

        defaults = {item["key"]: item["default"] for item in schema_items()}
        rows = await SysConfig.all()
        stored = {row.key: row.value for row in rows}

        for key, value in defaults.items():
            if key not in stored:
                await SysConfig.create(
                    key=key,
                    value="" if value is None else str(value),
                    group=(find_item(key) or {}).get("group", ""),
                )
                stored[key] = "" if value is None else str(value)

        self._cache = {key: _coerce(find_item(key), value) for key, value in stored.items()}
        for key, value in defaults.items():
            if self._cache.get(key) in (None, ""):
                self._cache[key] = value
        if env.app_secret_key and env.app_secret_key != "change-me-in-production-please":
            self._cache.setdefault("app.secret_key", env.app_secret_key)
        self._loaded = True
        log.info("运行配置装载完成，共 %d 项", len(self._cache))

    # ---------------- 读取 ----------------
    def get(self, key: str, default: Any = None) -> Any:
        value = self._cache.get(key, default)
        if value is None or value == "":
            item = find_item(key)
            if item is not None:
                fallback = item["default"]
                if fallback not in (None, ""):
                    return fallback
        return value

    def get_str(self, key: str, default: str = "") -> str:
        value = self.get(key, default)
        return "" if value is None else str(value)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(float(self.get(key, default)))
        except (TypeError, ValueError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.get(key, default))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        return bool(self.get(key, default))

    # ---------------- 写入 ----------------
    async def update(self, values: dict[str, Any]) -> set[str]:
        from app.models.sys_tables import SysConfig

        changed: set[str] = set()
        for key, raw in values.items():
            item = find_item(key)
            if item is None:
                continue
            if isinstance(raw, str) and raw.strip() == MASK and item.get("secret"):
                continue  # 前端提交 ****** 表示不修改
            text = "" if raw is None else ("true" if raw is True else "false" if raw is False else str(raw).strip())
            row = await SysConfig.get_or_none(key=key)
            if row is None:
                await SysConfig.create(key=key, value=text, group=item.get("group", ""))
            elif (row.value or "") != text:
                row.value = text
                await row.save()
            else:
                continue
            self._cache[key] = _coerce(item, text)
            if self._cache[key] in (None, "") and item["default"] not in (None, ""):
                self._cache[key] = item["default"]
            changed.add(key)

        if changed:
            for hook in self._hooks:
                try:
                    await hook(changed)
                except Exception as exc:  # 单个订阅方失败不影响配置保存
                    log.exception("配置变更回调失败：%s", exc)
        return changed

    def on_change(self, hook: ChangeHook) -> None:
        self._hooks.append(hook)

    # ---------------- 对外视图 ----------------
    def view(self) -> list[dict[str, Any]]:
        groups = []
        for group in GROUPS:
            items = []
            for item in group["items"]:
                value = self.get(item["key"], item["default"])
                payload = dict(item)
                if item.get("secret"):
                    payload["value"] = MASK if value else ""
                    payload["has_value"] = bool(value)
                else:
                    payload["value"] = "" if value is None else value
                items.append(payload)
            groups.append({"code": group["code"], "name": group["name"], "desc": group["desc"], "items": items})
        return groups

    def snapshot(self) -> dict[str, Any]:
        return dict(self._cache)

    # ---------------- 常用派生值 ----------------
    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def llm_ready(self) -> bool:
        return bool(self.get_str("llm.api_key") or "localhost" in self.get_str("llm.base_url"))

    @property
    def chat_base_url(self) -> str:
        return self.get_str("llm.base_url").rstrip("/")

    @property
    def embed_base_url(self) -> str:
        return (self.get_str("embed.base_url") or self.get_str("llm.base_url")).rstrip("/")

    @property
    def embed_api_key(self) -> str:
        return self.get_str("embed.api_key") or self.get_str("llm.api_key")

    @property
    def postgres_dsn(self) -> str:
        return self.get_str("gis.postgres_dsn")


runtime = RuntimeConfig()
