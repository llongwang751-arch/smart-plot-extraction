"""GIS 表结构：PostGIS 版用 Geometry 列，本地降级版用 GeoJSON 文本列。

两边列名一致，切换引擎时上层代码零改动。SQLAlchemy 的 Column 不能被两张表复用，
所以列定义写成工厂。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, MetaData, String, Table, Text

try:  # GeoAlchemy2 只在走 PostGIS 时必需；缺失也要能起本地引擎
    from geoalchemy2 import Geometry
except Exception:  # pragma: no cover
    Geometry = None


def _plot_cols(*, with_geometry: bool) -> list[Column]:
    cols = [
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("code", String(64), default=""),
        Column("name", String(128), default=""),
        Column("land_type", String(32), default=""),
        Column("region", String(64), default=""),
        Column("owner", String(64), default=""),
        Column("area_m2", Float, default=0),
        Column("area_mu", Float, default=0),
        Column("origin", String(16), default="vector"),  # vector | candidate | manual
        Column("source_task", Integer, default=0),
        Column("created_at", DateTime, default=datetime.now),
    ]
    if with_geometry:
        cols.append(Column("geom", Geometry("MULTIPOLYGON", srid=4326, spatial_index=True)))
    else:
        cols.append(Column("geojson", Text))
    return cols


def _task_cols() -> list[Column]:
    return [
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("title", String(128), default=""),
        Column("query", Text, default=""),
        Column("mode", String(16), default="smart"),  # smart | space
        Column("engine", String(16), default="local"),
        Column("aoi", Text, default=""),
        Column("land_types", String(256), default=""),
        Column("min_area_mu", Float, default=0),
        Column("geojson", Text, default=""),
        Column("statistics", Text, default=""),
        Column("trace", Text, default="[]"),  # LangGraph 节点轨迹
        Column("analysis", Text, default=""),
        Column("status", String(16), default="ok"),  # ok | failed
        Column("error", Text, default=""),
        Column("elapsed_ms", Integer, default=0),
        Column("user_id", Integer, default=0),
        Column("created_at", DateTime, default=datetime.now),
    ]


gis_meta = MetaData()
local_meta = MetaData()

if Geometry is not None:
    Table("plot", gis_meta, *_plot_cols(with_geometry=True))
Table("extraction_task", gis_meta, *_task_cols())

Table("plot", local_meta, *_plot_cols(with_geometry=False))
Table("extraction_task", local_meta, *_task_cols())

# 本地向量表（pgvector 不可用时的降级实现）
Table(
    "kb_chunk",
    local_meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("doc_id", Integer, index=True),
    Column("doc_name", String(256), default=""),
    Column("chunk_index", Integer, default=0),
    Column("content", Text, default=""),
    Column("embedding", Text, default=""),  # JSON 数组
    Column("metadata", Text, default="{}"),
    Column("created_at", DateTime, default=datetime.now),
)
