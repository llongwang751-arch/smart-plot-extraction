"""LangGraph 五节点提取工作流：需求理解 → 范围定位 → RAG 知识召回 → 空间提取 → 归纳结论。

每个节点都往 trace 里写自己做了什么、走了哪条降级路径、耗时多少；
run_extraction 之后有一条条件边：提取失败直接短路到 END，不做无意义的分析。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from app.config.runtime import runtime
from app.db.gis_store import gis
from app.llm.provider import chat_model
from app.rag.vectorstore import search_knowledge
from app.services.extraction import run_extraction
from app.workflows.intent import parse_intent
from app.workflows.locate import locate_area

log = logging.getLogger(__name__)

NODE_LABELS = {
    "parse_intent": "需求理解",
    "locate_area": "范围定位",
    "retrieve_knowledge": "知识召回",
    "run_extraction": "空间提取",
    "analyze": "结论归纳",
}


class ExtractState(TypedDict, total=False):
    query: str
    mode: str  # smart | space
    aoi: Any
    land_types: list[str]
    min_area_mu: float
    user_id: int
    intent: dict[str, Any]
    knowledge: list[dict[str, Any]]
    features: list[dict[str, Any]]
    statistics: dict[str, Any]
    geojson: dict[str, Any]
    warnings: list[str]
    analysis: str
    error: str
    trace: list[dict[str, Any]]


def _append(state: ExtractState, node: str, detail: str, started: float, via: str = "") -> list[dict[str, Any]]:
    entry = {
        "node": node,
        "label": NODE_LABELS[node],
        "detail": detail,
        "via": via,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
    return [*state.get("trace", []), entry]


async def parse_intent_node(state: ExtractState) -> dict[str, Any]:
    started = time.perf_counter()
    if state.get("mode") == "space":
        intent = {
            "region": "",
            "land_types": list(state.get("land_types") or []),
            "min_area_mu": float(state.get("min_area_mu") or 0),
            "keywords": list(state.get("land_types") or []),
            "summary": "纯计算模式：直接按参数提取，不经大模型",
        }
        return {"intent": intent, "trace": _append(state, "parse_intent", intent["summary"], started, "直接参数")}

    intent, via = await parse_intent(state.get("query", ""))
    detail = (
        f"地类：{'、'.join(intent['land_types']) or '不限'}；最小面积：{intent['min_area_mu'] or 0} 亩；"
        f"区域：{intent['region'] or '按框选范围'}"
    )
    return {"intent": intent, "trace": _append(state, "parse_intent", detail, started, via)}


async def locate_area_node(state: ExtractState) -> dict[str, Any]:
    started = time.perf_counter()
    if state.get("aoi"):
        aoi, source, level = state["aoi"], "前端框选 AOI", 1
    else:
        located = await locate_area(state.get("intent") or {}, state.get("aoi"))
        aoi, source, level = located["aoi"], located["source"], located["level"]
    return {
        "aoi": aoi,
        "trace": _append(
            state, "locate_area", f"范围来源：{source}（第 {level} 级）", started,
            "aoi-frontend" if level == 1 else f"degrade-{level}",
        ),
    }


async def retrieve_knowledge_node(state: ExtractState) -> dict[str, Any]:
    started = time.perf_counter()
    if state.get("mode") == "space":
        return {"knowledge": [], "trace": _append(state, "retrieve_knowledge", "纯计算模式跳过知识召回", started, "skip")}
    keywords = [k for k in (state.get("intent") or {}).get("keywords", []) if k]
    text = " ".join([state.get("query", ""), *keywords])
    hits = await search_knowledge(text)
    detail = f"召回 {len(hits)} 条知识片段" if hits else "知识库无匹配内容，跳过"
    via = "empty"
    if hits:
        try:
            from app.rag.vectorstore import vector_store

            via = vector_store().name
        except Exception:
            via = "vector"
    return {"knowledge": hits, "trace": _append(state, "retrieve_knowledge", detail, started, via)}


async def run_extraction_node(state: ExtractState) -> dict[str, Any]:
    started = time.perf_counter()
    intent = state.get("intent") or {}
    land_types = intent.get("land_types") or state.get("land_types") or []
    min_area = float(intent.get("min_area_mu") or state.get("min_area_mu") or 0)
    try:
        result = await run_extraction(state.get("aoi"), land_types=land_types, min_area_mu=min_area)
    except Exception as exc:
        log.exception("空间提取失败")
        return {
            "error": f"{type(exc).__name__}: {exc}",
            "features": [],
            "geojson": {"type": "FeatureCollection", "features": []},
            "statistics": {},
            "trace": _append(state, "run_extraction", f"提取失败：{exc}", started, "failed"),
        }
    stats = result["statistics"]
    detail = (
        f"引擎 {stats.get('engine')}｜命中 {stats.get('count', 0)} 个地块｜合计 {stats.get('total_area_mu', 0)} 亩"
        f"｜来源 {'矢量裁剪' if result['origin'] == 'vector' else '网格候选'}"
    )
    update: dict[str, Any] = {
        "features": result["features"],
        "statistics": stats,
        "geojson": result["geojson"],
        "aoi": result["aoi"],
        "warnings": result["warnings"],
        "trace": _append(state, "run_extraction", detail, started, stats.get("engine", "")),
    }
    return update


def route_after_extraction(state: ExtractState) -> str:
    return "end" if state.get("error") or not state.get("features") else "analyze"


ANALYZE_SYSTEM = (
    "你是自然资源地块分析助手。请基于给定的统计结果与知识片段写一段中文分析结论。"
    "硬性要求：涉及面积、数量、占比等数字必须逐字来自给定统计，禁止编造或自行换算成新口径；"
    "结论控制在 200 字以内，用 Markdown，不要重复罗列全部地块。"
)


async def analyze_node(state: ExtractState) -> dict[str, Any]:
    started = time.perf_counter()
    if state.get("mode") == "space":
        text = template_analysis(state)
        return {"analysis": text, "trace": _append(state, "analyze", "纯计算模式：模板结论", started, "template")}

    model = chat_model(temperature=0.1)
    if model is None:
        text = template_analysis(state)
        return {"analysis": text, "trace": _append(state, "analyze", "未配置模型：模板结论", started, "template")}

    stats = state.get("statistics") or {}
    knowledge = state.get("knowledge") or []
    user = json.dumps(
        {
            "需求原文": state.get("query", ""),
            "解析参数": state.get("intent", {}),
            "统计结果": {k: v for k, v in stats.items() if k not in {"by_region"}},
            "区域构成": stats.get("by_region", [])[:6],
            "知识片段": [{"来源": h.get("doc_name"), "片段": (h.get("content") or "")[:180], "相似度": h.get("score")} for h in knowledge],
        },
        ensure_ascii=False,
    )
    try:
        reply = await model.ainvoke([SystemMessage(content=ANALYZE_SYSTEM), HumanMessage(content=user)])
        text = str(getattr(reply, "content", reply)).strip() or template_analysis(state)
        via = "llm"
    except Exception as exc:
        log.warning("结论归纳失败，退回模板：%s", exc)
        text, via = template_analysis(state), "template(模型失败)"
    return {"analysis": text, "trace": _append(state, "analyze", f"结论生成（{via}）", started, via)}


def template_analysis(state: ExtractState) -> str:
    stats = state.get("statistics") or {}
    types = "、".join(f"{t['name']} {t['count']} 个/{t['area_mu']} 亩" for t in stats.get("by_land_type", [])[:7]) or "无"
    aoi_mu = stats.get("aoi_area_mu")
    lines = [
        "## 提取结论",
        f"- 共命中 **{stats.get('count', 0)}** 个地块，合计 **{stats.get('total_area_mu', 0)} 亩**"
        + (f"，约占提取范围（{aoi_mu} 亩）的 {round((stats.get('total_area_mu') or 0) / aoi_mu * 100, 1)}%" if aoi_mu else ""),
        f"- 平均单块 **{stats.get('avg_area_mu', 0)} 亩**，最大 **{stats.get('max_area_mu', 0)} 亩**",
        f"- 地类构成：{types}",
        f"- 计算引擎：{'PostGIS 空间叠加' if stats.get('engine') == 'postgis' else '本地空间引擎（Shapely）'}"
        + ("，结果为规则网格候选地块，需人工核查" if stats.get("origin") == "candidate" else ""),
    ]
    if state.get("error"):
        lines.append(f"- 提取失败：{state['error']}")
    return "\n".join(lines)


def build_graph():
    builder = StateGraph(ExtractState)
    builder.add_node("parse_intent", parse_intent_node)
    builder.add_node("locate_area", locate_area_node)
    builder.add_node("retrieve_knowledge", retrieve_knowledge_node)
    builder.add_node("run_extraction", run_extraction_node)
    builder.add_node("analyze", analyze_node)
    builder.add_edge("__start__", "parse_intent")
    builder.add_edge("parse_intent", "locate_area")
    builder.add_edge("locate_area", "retrieve_knowledge")
    builder.add_edge("retrieve_knowledge", "run_extraction")
    builder.add_conditional_edges("run_extraction", route_after_extraction, {"analyze": "analyze", "end": END})
    builder.add_edge("analyze", END)
    return builder.compile()


_graph = build_graph()


async def run_workflow(
    *,
    query: str,
    mode: str = "smart",
    aoi: Any = None,
    land_types: list[str] | None = None,
    min_area_mu: float = 0,
    user_id: int = 0,
) -> dict[str, Any]:
    started = time.perf_counter()
    state: ExtractState = {
        "query": query,
        "mode": mode,
        "aoi": aoi,
        "land_types": land_types or [],
        "min_area_mu": float(min_area_mu or 0),
        "user_id": user_id,
        "trace": [],
        "warnings": [],
    }
    final: ExtractState = await _graph.ainvoke(state, config={"recursion_limit": 20})
    return {
        "query": query,
        "mode": mode,
        "engine": gis.mode,
        "intent": final.get("intent", {}),
        "aoi": final.get("aoi"),
        "knowledge": final.get("knowledge", []),
        "features": final.get("features", []),
        "statistics": final.get("statistics", {}),
        "geojson": final.get("geojson", {"type": "FeatureCollection", "features": []}),
        "analysis": final.get("analysis", ""),
        "warnings": final.get("warnings", []),
        "error": final.get("error", ""),
        "trace": final.get("trace", []),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "llm_ready": runtime.get_str("llm.chat_model") if chat_model() else "",
    }
