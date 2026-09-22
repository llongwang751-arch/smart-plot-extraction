"""contextvars 工具结果回收：LangChain 工具的返回值只回给大模型，前端拿不到。

用 ContextVar 建一个收集器，工具执行时把产出的 GeoJSON、检索来源、调用轨迹同步写进来，
接口层再一起返回，于是 Agent 圈出的地块能直接画到右侧地图上。
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Iterator

_sink: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("agent_sink", default=None)


@contextmanager
def collecting() -> Iterator[dict[str, Any]]:
    sink: dict[str, Any] = {"plots": [], "sources": [], "calls": []}
    token = _sink.set(sink)
    try:
        yield sink
    finally:
        _sink.reset(token)


def emit_plots(geojson: Any) -> None:
    sink = _sink.get()
    if sink is not None and geojson:
        sink["plots"].append(geojson)


def emit_sources(hits: list[dict[str, Any]]) -> None:
    sink = _sink.get()
    if sink is not None:
        sink["sources"].extend(hits or [])


def emit_call(name: str, args: Any, result: Any, elapsed_ms: int = 0) -> None:
    sink = _sink.get()
    if sink is not None:
        sink["calls"].append({"name": name, "args": args, "result": _trim(result), "elapsed_ms": elapsed_ms})


def _trim(value: Any, limit: int = 600) -> Any:
    text = value if isinstance(value, str) else json_dumps(value)
    return text if len(text) <= limit else text[:limit] + "…(截断)"


def json_dumps(value: Any) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)
