"""智能问答：create_react_agent 构建的对话助手，最多 N 步推理，可调用 4 个工具。

系统提示词里硬性约束“数字必须来自工具返回结果”，Agent 圈出的地块经 contextvars
收集器直接回传前端上图，检索来源与工具轨迹一并返回，答案可追溯。
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from app.config.runtime import runtime
from app.db.gis_store import gis
from app.llm.provider import chat_model
from app.rag.vectorstore import search_knowledge as search_vectors
from app.services.extraction import run_extraction
from app.workflows.intent import clean_regions
from app.workflows.locate import locate_area
from app.workflows.sink import collecting, emit_call, emit_plots, emit_sources

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是自然资源地块数据助手，服务于“智能地块提取平台”。可用工具：
1. search_knowledge：检索知识库（政策法规、地类认定标准、数据说明）
2. plot_statistics：全库地块数量、面积、地类构成
3. search_plots_in_region：按区域 / 地类查询地块
4. extract_plots_in_area：按行政区（region）执行地块提取，范围由系统解析

硬性要求：
- 涉及面积、数量、占比等数字必须来自工具返回结果，不要编造，也不要自行换算出新口径；
- 用户问到认定标准、政策口径时先调用 search_knowledge，并在回答里注明依据；
- 需要空间范围时只传行政区名，由系统按地块库已有范围解析；绝对不要自己给出经纬度坐标；
- 工具返回“口径”说明结果是真实地块还是网格候选，回答里必须照实说明，不要把候选说成真实地块；
- 回答用中文 Markdown，200 字以内，先结论后依据；不要输出链接、图片或地图截图地址（地块由前端自动上图）。
"""


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _text(value: Any, sep: str = ",") -> str:
    """模型偶尔把字符串参数传成列表，统一收口成字符串再交给下游。"""
    if value in (None, ""):
        return ""
    if isinstance(value, (list, tuple, set)):
        return sep.join(str(item) for item in value if item not in (None, ""))
    return str(value)


@tool
async def search_knowledge(query: str, k: int = 4) -> str:
    """检索知识库：政策法规、地类认定标准、面积口径、数据说明。query 为检索问题，k 为返回条数。"""
    started = time.perf_counter()
    hits = await search_vectors(query, k)
    emit_sources(hits)
    payload = [
        {"来源": h.get("doc_name"), "相似度": h.get("score"), "片段": (h.get("content") or "")[:300]} for h in hits
    ]
    emit_call("search_knowledge", {"query": query, "k": k}, payload, int((time.perf_counter() - started) * 1000))
    return _json({"count": len(hits), "hits": payload} if hits else {"count": 0, "hits": [], "提示": "知识库无匹配内容"})


@tool
async def plot_statistics() -> str:
    """查询全库地块统计：数量、总面积（亩/平方米）、地类构成、区域构成。无需参数。"""
    started = time.perf_counter()
    stats = await gis.plot_statistics()
    slim = {k: v for k, v in stats.items() if k not in {"by_region"}}
    emit_call("plot_statistics", {}, slim, int((time.perf_counter() - started) * 1000))
    return _json(slim | {"区域构成": stats.get("by_region", [])[:8]})


@tool
async def search_plots_in_region(region: str = "", land_type: str = "", limit: int = 20) -> str:
    """按行政区与地类查询地块明细。region 如“朝阳区”，land_type 取七大类之一，limit 为最多返回条数。"""
    started = time.perf_counter()
    region, land_type = _text(region), _text(land_type)
    plots, total = await gis.list_plots(land_type=land_type, region=region, page=1, size=min(int(limit), 100))
    collection = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {k: v for k, v in p.items() if k != "geometry"}, "geometry": p.get("geometry")}
        for p in plots
    ]}
    emit_plots(collection)
    rows = [
        {"编号": p.get("code"), "名称": p.get("name"), "地类": p.get("land_type"), "区域": p.get("region"), "亩": p.get("area_mu")}
        for p in plots
    ]
    emit_call("search_plots_in_region", {"region": region, "land_type": land_type}, rows[:10], int((time.perf_counter() - started) * 1000))
    return _json({"total": total, "returned": len(rows), "plots": rows})


@tool
async def extract_plots_in_area(
    region: str = "",
    land_types: str = "",
    min_area_mu: float = 0,
    aoi_geojson: str = "",
) -> str:
    """按行政区做空间提取。region 如“朝阳区”或“朝阳区,海淀区”，land_types 逗号分隔（如“耕地,园地”），
    min_area_mu 为最小面积（亩）。范围由系统按地块库已有范围解析，只有用户自己给出坐标时才传 aoi_geojson，
    绝对不要编造经纬度。"""
    started = time.perf_counter()
    region = _text(region, "、")
    land_types = _text(land_types)
    aoi_geojson = _text(aoi_geojson)
    types = [t.strip() for t in land_types.replace("，", ",").split(",") if t.strip()]
    aoi: Any = None
    where = ""
    if aoi_geojson.strip():
        try:
            aoi = json.loads(aoi_geojson)
            where = "调用方给出的坐标范围"
        except json.JSONDecodeError:
            aoi = None
    if aoi is None:
        located = await locate_area({"region": ",".join(clean_regions(region)), "land_types": types}, None)
        aoi = located["aoi"]
        where = f"{located['source']}（第 {located['level']} 级）"
    try:
        result = await run_extraction(aoi, land_types=types, min_area_mu=float(min_area_mu or 0))
    except Exception as exc:
        return _json({"error": str(exc)})
    stats = result["statistics"]
    emit_plots(result["geojson"])
    args = {"region": region, "land_types": land_types, "min_area_mu": min_area_mu, "范围": where}
    emit_call("extract_plots_in_area", args, stats, int((time.perf_counter() - started) * 1000))
    origin = str(stats.get("origin") or "")
    return _json(
        {
            "范围": where,
            "统计": {k: v for k, v in stats.items() if k not in {"by_region"}},
            "样例": [
                {"编号": p.get("code"), "地类": p.get("land_type"), "亩": p.get("area_mu")} for p in result["features"][:10]
            ],
            "口径": "命中库内真实地块（矢量裁剪）" if origin == "vector" else "库内无命中，结果是规则网格候选地块，必须向用户说明不是真实地块",
            "提示": result["warnings"],
        }
    )


TOOLS = [search_knowledge, plot_statistics, search_plots_in_region, extract_plots_in_area]


DATA_SEEKING = re.compile(r"(多少|几块|几个|面积|亩|公顷|平方公里|数量|统计|分布|一共|总计|查询|查一下|提取|哪些)")


def _needs_data(question: str) -> bool:
    return bool(DATA_SEEKING.search(question or ""))


async def ask_agent(question: str, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    model = chat_model(temperature=0.0)
    if model is None:
        return await rag_fallback(question, why="未配置大模型")
    max_steps = runtime.get_int("llm.max_steps", 8)
    messages: list[Any] = []
    for item in (history or [])[-8:]:
        role, content = item.get("role"), str(item.get("content") or "")
        if not content:
            continue
        messages.append(HumanMessage(content=content) if role == "user" else AIMessage(content=content))
    messages.append(HumanMessage(content=question))

    started = time.perf_counter()
    with collecting() as sink:
        agent = create_react_agent(model, TOOLS, prompt=SYSTEM_PROMPT)
        config = {"recursion_limit": max_steps * 2 + 3}
        try:
            out = await agent.ainvoke({"messages": messages}, config=config)
            answer = _last_ai_text(out)
            # 护栏：小模型有时会跳过工具直接报数，这里强制补一轮“先查再答”
            if not sink["calls"] and _needs_data(question):
                log.info("Agent 未调用工具即给出回答，触发防幻觉重试")
                retry = [
                    *messages,
                    AIMessage(content=answer or ""),
                    HumanMessage(content="你刚才没有调用任何工具就给出了数字。请立即调用合适的工具取真实数据，然后只依据工具结果重新回答。"),
                ]
                out = await agent.ainvoke({"messages": retry}, config=config)
                answer = _last_ai_text(out) or answer
            if not answer:
                return await rag_fallback(question, why="模型未返回内容", sink=sink)
            if not sink["calls"] and _needs_data(question):
                return await rag_fallback(question, why="模型坚持不使用工具", sink=sink)
        except Exception as exc:
            log.warning("ReAct Agent 失败，退回 RAG 兜底问答：%s", exc, exc_info=True)
            fallback = await rag_fallback(question, why=f"{type(exc).__name__}", sink=sink)
            fallback["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
            return fallback
    return {
        "answer": answer,
        "sources": _dedup(sink["sources"]),
        "plots": sink["plots"][-1] if sink["plots"] else None,
        "calls": sink["calls"],
        "via": "react-agent",
        "steps": len(sink["calls"]),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def _last_ai_text(out: dict[str, Any]) -> str:
    for message in reversed(out.get("messages", []) if isinstance(out, dict) else []):
        if isinstance(message, AIMessage) and str(message.content or "").strip():
            return str(message.content).strip()
    return ""


def _dedup(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any]] = set()
    out = []
    for hit in hits:
        key = (hit.get("doc_id"), hit.get("chunk_index"))
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
    return out


async def rag_fallback(question: str, *, why: str = "", sink: dict[str, Any] | None = None) -> dict[str, Any]:
    """降级路径 1：不走 Agent，直接向量检索 + 模板组织答案；问数时补真实库统计。"""
    if sink is not None:
        return await _rag_answer(question, why=why, sink=sink)
    with collecting() as owned:
        return await _rag_answer(question, why=why, sink=owned)


async def _rag_answer(question: str, *, why: str, sink: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    hits = await search_vectors(question)
    sink["sources"].extend(hits or [])
    payload = sink
    stats_section = await _real_stats_section(question)

    if not hits:
        text = (
            f"当前未接入可用大模型（{why}），且知识库没有检索到相关内容。\n\n"
            "可在「系统配置 → 大模型」填写 Base URL / API Key / 模型名后重试；"
            "地块数量与面积等确定性数据不受影响，仍可在「地图提取」用纯计算模式获取。"
        )
        if stats_section:
            text += "\n\n" + stats_section
        return {
            "answer": text,
            "sources": _dedup(payload.get("sources") or hits),
            "plots": payload["plots"][-1] if payload.get("plots") else None,
            "calls": payload.get("calls", []),
            "via": f"提示未配置模型({why})",
            "steps": len(payload.get("calls", [])),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    lines = ["## 依据知识库的回答", f"> 未能启用智能体（{why}），以下为向量检索到的最相关片段整理。", ""]
    for index, hit in enumerate(hits[:3], start=1):
        excerpt = (hit.get("content") or "").strip().replace("\n", " ")
        lines.append(f"{index}. **{hit.get('doc_name') or '未知文档'}**（相似度 {hit.get('score')}）\n   {excerpt[:220]}")
    if stats_section:
        lines += ["", stats_section]
    calls = payload.get("calls", [])
    return {
        "answer": "\n".join(lines),
        "sources": _dedup(payload.get("sources") or hits),
        "plots": payload["plots"][-1] if payload.get("plots") else None,
        "calls": calls,
        "via": f"rag-fallback({why})",
        "steps": len(calls),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


async def _real_stats_section(question: str) -> str:
    """问数问题在降级路径下也要给出空间引擎算出的真实数字，绝不由模型编造。"""
    if not _needs_data(question):
        return ""
    started = time.perf_counter()
    try:
        stats = await gis.plot_statistics()
    except Exception as exc:
        log.warning("降级问答取统计失败：%s", exc)
        return ""
    emit_call("plot_statistics", {}, {k: v for k, v in stats.items() if k != "by_region"}, int((time.perf_counter() - started) * 1000))
    kinds = "、".join(
        f"{item['name']} {item['count']} 块/{item['area_mu']} 亩" for item in (stats.get("by_land_type") or [])[:7]
    )
    lines = [
        "## 真实库统计（来自空间引擎计算，非模型生成）",
        f"- 地块总数：**{stats.get('count', 0)}** 块",
        f"- 总面积：**{stats.get('total_area_mu', 0)}** 亩（{stats.get('total_area_m2', 0)} 平方米）",
        f"- 平均面积：{stats.get('avg_area_mu', 0)} 亩｜最大单块：{stats.get('max_area_mu', 0)} 亩",
    ]
    if kinds:
        lines.append(f"- 地类构成：{kinds}")
    return "\n".join(lines)
