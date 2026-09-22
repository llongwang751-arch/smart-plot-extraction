"""配置项 Schema：新增一项只需在这里加一行，前端由 /config/schema 自动渲染。"""
from __future__ import annotations

from typing import Any

from .env import env


def _item(
    key: str,
    label: str,
    kind: str = "string",
    default: Any = "",
    *,
    tip: str = "",
    placeholder: str = "",
    options: list[str] | None = None,
    secret: bool = False,
    group: str = "",
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "type": kind,
        "default": default,
        "tip": tip,
        "placeholder": placeholder,
        "options": options or [],
        "secret": secret,
        "group": group,
    }


GROUPS: list[dict[str, Any]] = [
    {
        "code": "llm",
        "name": "大模型",
        "desc": "OpenAI 兼容协议，换厂商只改地址与模型名，热生效不用改代码",
        "items": [
            _item("llm.base_url", "Base URL", default=env.llm_base_url,
                  placeholder="https://api.deepseek.com/v1",
                  tip="OpenAI / DeepSeek / 通义千问 / Ollama 均填各自的兼容地址", group="llm"),
            _item("llm.api_key", "API Key", "password", default=env.llm_api_key, secret=True, group="llm"),
            _item("llm.chat_model", "对话模型", default=env.llm_chat_model,
                  placeholder="deepseek-chat / qwen-plus / gpt-4o-mini", group="llm"),
            _item("llm.temperature", "温度", "number", default=env.llm_temperature,
                  tip="0 ~ 2，提取结论建议 0.2 以内", group="llm"),
            _item("llm.max_steps", "Agent 最大推理步数", "number", default=env.llm_max_steps,
                  tip="ReAct Agent 单次问答允许的工具调用轮数", group="llm"),
        ],
    },
    {
        "code": "rag",
        "name": "向量与 RAG",
        "desc": "嵌入模型与知识库切片、检索参数",
        "items": [
            _item("embed.base_url", "嵌入 Base URL", default=env.embed_base_url or env.llm_base_url,
                  tip="留空则复用大模型 Base URL", group="rag"),
            _item("embed.api_key", "嵌入 API Key", "password", default=env.embed_api_key, secret=True,
                  tip="留空则复用大模型 API Key", group="rag"),
            _item("embed.model", "嵌入模型", default=env.embed_model,
                  placeholder="text-embedding-v3 / text-embedding-3-small / bge-m3", group="rag"),
            _item("embed.dim", "向量维度", "number", default=env.embed_dim,
                  tip="text-embedding-3-small=1536，text-embedding-v3=1024，bge-m3=1024。变更后需重建索引", group="rag"),
            _item("rag.top_k", "检索 Top-K", "number", default=env.rag_top_k, group="rag"),
            _item("rag.chunk_size", "切片长度(字)", "number", default=env.chunk_size, group="rag"),
            _item("rag.chunk_overlap", "切片重叠(字)", "number", default=env.chunk_overlap, group="rag"),
        ],
    },
    {
        "code": "geovis",
        "name": "星图地图",
        "desc": "GEOVIS Earth 瓦片服务，鉴权错误会被伪装成 HTTP 200，接口层已单独识别",
        "items": [
            _item("geovis.token", "GEOVIS Token", "password", default=env.geovis_token, secret=True, group="geovis"),
            _item("geovis.image_url", "影像地址", default="https://image.geovisearth.com/base/v1/img/{z}/{x}/{y}?format=webp", group="geovis"),
            _item("geovis.vector_url", "矢量地址", default="https://vector.geovisearth.com/base/v1/vec/{z}/{x}/{y}?format=webp", group="geovis"),
            _item("geovis.terrain_url", "地形地址", default="https://terrain.geovisearth.com/base/v1/ter/{z}/{x}/{y}?format=webp", group="geovis"),
            _item("geovis.anno_url", "注记地址", default="https://image.geovisearth.com/base/v1/cta/{z}/{x}/{y}?format=webp", group="geovis"),
        ],
    },
    {
        "code": "tianditu",
        "name": "天地图",
        "desc": "标准 WMTS KVP 接口，Web Mercator 投影，支持安全密钥(sk)自动注入",
        "items": [
            _item("tianditu.token", "天地图 Token( tk )", "password", default=env.tianditu_token, secret=True, group="tianditu"),
            _item("tianditu.use_sk", "启用安全密钥", "boolean", default=env.tianditu_use_sk,
                  tip="开启后瓦片地址自动追加 sk 参数，旧配置无需手改", group="tianditu"),
            _item("tianditu.sk", "安全密钥 sk", "password", default=env.tianditu_sk, secret=True, group="tianditu"),
            _item("tianditu.img_url", "影像 WMTS", default="https://t{s}.tianditu.gov.cn/img_w/wmts", group="tianditu"),
            _item("tianditu.vec_url", "矢量 WMTS", default="https://t{s}.tianditu.gov.cn/vec_w/wmts", group="tianditu"),
            _item("tianditu.ter_url", "地形 WMTS", default="https://t{s}.tianditu.gov.cn/ter_w/wmts", group="tianditu"),
            _item("tianditu.cia_url", "影像注记", default="https://t{s}.tianditu.gov.cn/cia_w/wmts", group="tianditu"),
            _item("tianditu.cva_url", "矢量注记", default="https://t{s}.tianditu.gov.cn/cva_w/wmts", group="tianditu"),
        ],
    },
    {
        "code": "gis",
        "name": "空间数据库",
        "desc": "PostgreSQL + PostGIS + pgvector；连不上时自动降级到本地引擎（Shapely + 本地向量）",
        "items": [
            _item("gis.postgres_dsn", "PostGIS DSN", default=env.postgres_dsn,
                  placeholder="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/plot_gis",
                  tip="修改并测试通过后自动重建连接池、建扩展、建表", group="gis"),
            _item("gis.schema", "模式名", default="public", group="gis"),
        ],
    },
    {
        "code": "extract",
        "name": "提取参数",
        "desc": "空间提取的算法参数：AOI 裁剪叠加与网格兜底",
        "items": [
            _item("extract.grid_size", "网格边长(米)", "number", default=env.extract_grid_size,
                  tip="库中无命中地块时的兜底网格，按 cos(纬度) 修正经度方向；超过 6000 格自动放大", group="extract"),
            _item("extract.simplify", "几何简化容差(度)", "number", default=env.extract_simplify,
                  tip="ST_SimplifyPreserveTopology，0.0001 度约 10 米", group="extract"),
            _item("extract.min_area_mu", "默认最小面积(亩)", "number", default=env.extract_min_area_mu, group="extract"),
            _item("extract.default_center", "默认中心点(经,纬)", default=env.extract_default_center, group="extract"),
            _item("extract.default_extent_km", "默认范围(公里)", "number", default=env.extract_default_extent_km, group="extract"),
            _item("extract.max_features", "最大返回地块数", "number", default=2000, group="extract"),
        ],
    },
]


def schema_items() -> list[dict[str, Any]]:
    return [dict(item) for group in GROUPS for item in group["items"]]


def schema_keys() -> set[str]:
    return {item["key"] for item in schema_items()}


def default_map() -> dict[str, Any]:
    return {item["key"]: item["default"] for item in schema_items()}


def find_item(key: str) -> dict[str, Any] | None:
    for item in schema_items():
        if item["key"] == key:
            return item
    return None
