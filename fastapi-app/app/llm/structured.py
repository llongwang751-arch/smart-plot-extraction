"""结构化输出四级降级：json_schema → function_calling → json_mode → 提示词 + JsonOutputParser。

各家模型对 JSON 输出模式支持程度不一，依次尝试即可做到换模型不改代码。
返回值带上实际生效的方式，便于执行轨迹里展示“走了哪条降级路径”。
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

METHODS = ("json_schema", "function_calling", "json_mode")


def parse_loose(text: Any) -> dict[str, Any] | None:
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        text = str(text)
    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", candidate, re.S)
    if fence:
        candidate = fence.group(1).strip()
    try:
        return json.loads(candidate)
    except (ValueError, TypeError):
        pass
    start, end = candidate.find("{"), candidate.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except (ValueError, TypeError):
            return None
    return None


def _dump(result: Any) -> dict[str, Any] | None:
    if isinstance(result, BaseModel):
        return result.model_dump()
    if isinstance(result, dict):
        return result
    if hasattr(result, "model_dump"):
        return result.model_dump()
    parsed = parse_loose(getattr(result, "content", result))
    return parsed


async def ask_json(model, system: str, user: str, schema: type[T], timeout_note: str = "") -> tuple[dict[str, Any] | None, str]:
    """返回 (数据, 生效方式)。model 为 None 时直接返回 (None, 'no-model')。"""
    if model is None:
        return None, "no-model"
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)

    for method in METHODS:
        started = time.perf_counter()
        try:
            runner = model.with_structured_output(schema, method=method)
            data = _dump(await runner.ainvoke(messages))
            if data is not None:
                log.info("结构化输出命中 %s（%d ms）", method, (time.perf_counter() - started) * 1000)
                return schema.model_validate(_merge(schema, data)).model_dump(), method
            log.debug("结构化输出 %s 无有效结果，继续降级", method)
        except Exception as exc:
            log.debug("结构化输出 %s 失败：%s", method, str(exc)[:160])

    try:  # 最后一级：提示词约束 + 容错解析
        raw = await model.ainvoke(
            messages + [HumanMessage(content=f"只输出一个 JSON 对象，严格符合该 Schema：{schema_json}")]
        )
        data = parse_loose(getattr(raw, "content", raw))
        if data is not None:
            return schema.model_validate(_merge(schema, data)).model_dump(), "prompt_json"
    except Exception as exc:
        log.debug("提示词 JSON 兜底失败：%s", str(exc)[:160])
    return None, "failed"


def _merge(schema: type[BaseModel], data: dict[str, Any]) -> dict[str, Any]:
    base = _defaults(schema)
    merged = dict(base)
    for key, value in data.items():
        if value is None and key in base:
            continue  # 模型回 null 时保留字段默认值，别让校验直接炸
        merged[key] = value
    return merged


def _defaults(schema: type[BaseModel]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, field in schema.model_fields.items():
        if field.default is not None and not isinstance(field.default, type(...)):
            out[name] = field.default
        elif field.default_factory is not None:  # type: ignore[misc]
            out[name] = field.default_factory()  # type: ignore[misc]
        else:
            out[name] = None
    return out
