"""需求理解：语义归大模型，几何与数字归数据库。

主路径用结构化输出把口语化需求转成 {region, land_types, min_area_mu}；
大模型不可用或解析失败时，退回到正则规则解析（地类词典 + 单位换算 + 行政区抽取）。
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.config.runtime import runtime
from app.llm.provider import chat_model
from app.llm.structured import ask_json
from app.utils.units import LAND_TYPES, MU_UNITS, to_mu

SYSTEM = (
    "你是自然资源领域的需求解析助手，只负责把用户的自然语言提取需求转成结构化参数。"
    "严格规则：不得编造面积、数量或地理坐标；无法确定的字段留空或给保守默认值；"
    "地类只能取 耕地、园地、林地、草地、建设用地、水域、未利用地；面积阈值统一换算成亩。"
)

TYPE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "耕地": ("耕地", "农田", "水田", "旱地", "菜地", "基本农田", "稻田"),
    "园地": ("园地", "果园", "茶园", "桑园", "橡胶园"),
    "林地": ("林地", "树林", "森林", "灌木", "林地林", "竹海"),
    "草地": ("草地", "草原", "草场", "牧草地"),
    "建设用地": ("建设用地", "建房", "住宅", "工厂", "厂房", "道路", "矿区", "城镇"),
    "水域": ("水域", "河流", "湖泊", "水库", "坑塘", "水面", "湿地"),
    "未利用地": ("未利用地", "荒地", "裸地", "沙地", "盐碱地"),
}

UNIT_PATTERN = "|".join(sorted((re.escape(u) for u in MU_UNITS), key=len, reverse=True))
AREA_RE = re.compile(rf"(\d+(?:\.\d+)?)\s*(?:平方)?({UNIT_PATTERN})")
REGION_RE = re.compile(r"([\u4e00-\u9fa5]{2,8}?(?:自治区|自治州|地区|新区|区|县|市|州|盟|镇|乡|村|街道|旗))")
REGION_HEAD = re.compile(r"^(提取|统计|查询|查看|计算|汇总|分析|请在|请帮我|请|帮我|给我|在|把|对|关于|范围内|范围|全部|所有|任意)+")
REGION_TAIL = re.compile(r"(范围内|范围|以内|区域|内|的|等)+$")
REGION_SPLIT = re.compile(r"[、,，;；\s]+|以及|和|与|及|或")


def clean_regions(value: Any) -> list[str]:
    """把“提取朝阳区和海淀区”这类脏值还原成规范行政区名，避免范围定位白降级一级。

    小模型有时把 region 传成列表，这里一并兼容，免得正则直接抛 TypeError。
    """
    if isinstance(value, (list, tuple, set)):
        value = "、".join(str(item) for item in value if item not in (None, ""))
    out: list[str] = []
    for part in REGION_SPLIT.split(str(value or "")):
        part = REGION_TAIL.sub("", REGION_HEAD.sub("", part.strip()))
        if REGION_RE.fullmatch(part) and part not in out:
            out.append(part)
    return out


def pick_regions(text: str) -> list[str]:
    return clean_regions("、".join(REGION_RE.findall(text or "")))


class IntentSpec(BaseModel):
    region: str = Field(default="", description="目标行政区或区域名，未提到则留空")
    land_types: list[str] = Field(default_factory=list, description="地类列表，取值限于七大地类")
    min_area_mu: float = Field(default=0, description="最小面积阈值，单位亩")
    keywords: list[str] = Field(default_factory=list, description="用于知识检索的关键词")
    summary: str = Field(default="", description="一句话复述解析出的需求")


def rule_parse(query: str) -> dict[str, Any]:
    text = query or ""
    land_types: list[str] = []
    for canon, words in TYPE_SYNONYMS.items():
        if any(word in text for word in words) and canon not in land_types:
            land_types.append(canon)

    min_area = 0.0
    unit_hits = list(AREA_RE.finditer(text))
    for match in unit_hits:
        number, unit = float(match.group(1)), match.group(2)
        tail = text[match.end() : match.end() + 8]
        if any(word in tail for word in ("以上", "大于", "超过", "不低于", "至少", "之上")) or any(
            word in text[max(0, match.start() - 6) : match.start()] for word in ("大于", "超过", "不低于", "至少")
        ):
            min_area = max(min_area, to_mu(number, unit))

    regions = pick_regions(text)
    region = ",".join(regions)
    keywords = list(dict.fromkeys([*land_types, *regions, "地块提取", "地类认定"]))
    return {
        "region": region,
        "land_types": land_types,
        "min_area_mu": round(min_area, 4),
        "keywords": [k for k in keywords if k],
        "summary": (
            f"区域：{region or '按框选范围'}；"
            f"地类：{'、'.join(land_types) if land_types else '不限'}；"
            f"最小面积：{min_area or 0} 亩"
        ),
    }


async def parse_intent(query: str) -> tuple[dict[str, Any], str]:
    """返回 (intent, 生效方式)。降级路径记在轨迹里，界面上能看到是哪条路走的。"""
    fallback = rule_parse(query)
    model = chat_model(temperature=0.0)
    if model is None:
        return fallback, "rule(未配置模型)"
    user = (
        f"需求原文：{query}\n"
        f"可选地类：{LAND_TYPES}\n"
        "请解析出目标区域、地类、最小面积（亩）。原文未提到的字段不要臆造。"
    )
    data, method = await ask_json(model, SYSTEM, user, IntentSpec)
    if not data:
        return fallback, "rule(模型解析失败)"

    merged = IntentSpec.model_validate({**fallback, **{k: v for k, v in data.items() if v not in (None, "", [])}})
    intent = merged.model_dump()
    intent["region"] = ",".join(clean_regions(merged.region)) or fallback["region"]
    intent["land_types"] = [t for t in intent["land_types"] if t in LAND_TYPES] or fallback["land_types"]
    if not intent["keywords"]:
        intent["keywords"] = fallback["keywords"]
    if not intent["summary"]:
        intent["summary"] = fallback["summary"]
    return intent, f"llm({method})" if runtime.get_str("llm.api_key") else f"llm({method}/local)"
