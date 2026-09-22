"""PostGIS 主引擎：地块几何 + 提取 + 统计全部交给空间 SQL。

面积一律走 ::geography（椭球面），求交结果用 ST_CollectionExtract(...,3) 只保留面要素，
返回前 ST_SimplifyPreserveTopology 简化，避免高纬度低估与前端渲染爆炸。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import mu_of, plot_dict, summarize, task_dict
from app.models import gis_tables as _t
from app.utils.geo import geodetic_area_m2, normalize_geom
from app.utils.units import MU_PER_M2

PLOT = _t.gis_meta.tables["plot"]
TASK = _t.gis_meta.tables["extraction_task"]


class PostgisGisStore:
    mode = "postgis"

    def __init__(self, dsn: str, schema: str = "public") -> None:
        self.dsn = dsn
        self.schema = schema or "public"
        self._engine = None
        self._sm: async_sessionmaker | None = None

    # ---------------- 生命周期 ----------------
    async def connect(self) -> None:
        self._engine = create_async_engine(self.dsn, pool_size=5, max_overflow=10, pool_pre_ping=True, future=True)
        async with self._engine.begin() as conn:
            # 启动即自动建扩展，无需手工初始化
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            if self.schema != "public":
                await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"'))
                await conn.execute(text(f'SET search_path TO "{self.schema}", public'))
            await conn.run_sync(lambda c: _t.gis_meta.create_all(c, checkfirst=True))
        self._sm = async_sessionmaker(self._engine, expire_on_commit=False)

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sm = None

    async def health(self) -> dict[str, Any]:
        async with self._engine.connect() as conn:
            postgis = (await conn.execute(text("SELECT postgis_version()"))).scalar()
            try:
                vector = (await conn.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))).scalar()
            except Exception:
                vector = None
        count = await self.plot_count()
        chunks = await self.chunk_count()
        return {
            "mode": "postgis",
            "ok": True,
            "plots": count,
            "chunks": chunks,
            "postgis_version": str(postgis or "").strip() or None,
            "pgvector_version": vector,
            "note": "PostGIS + pgvector 主路径",
        }

    @property
    def engine(self):
        return self._engine

    @property
    def connection_string(self) -> str:
        return self.dsn

    # ---------------- 地块 ----------------
    def _geom_expr(self, param: str):
        return func.ST_SetSRID(func.ST_GeomFromGeoJSON(bindparam(param)), 4326)

    async def create_plot(self, data: dict[str, Any]) -> dict[str, Any]:
        geom = normalize_geom(data.get("geometry") or data.get("geojson"))
        if geom is None:
            raise ValueError("地块边界无法解析为面要素")
        geojson_text = json.dumps(geom.__geo_interface__, ensure_ascii=False)
        area_m2 = round(float(geom_area_pg(geom)), 2)
        payload = {
            "code": data.get("code") or f"PLT{datetime.now().strftime('%m%d%H%M%S')}",
            "name": data.get("name") or "",
            "land_type": data.get("land_type") or "未利用地",
            "region": data.get("region") or "",
            "owner": data.get("owner") or "",
            "area_m2": area_m2,
            "area_mu": mu_of(area_m2),
            "origin": data.get("origin") or "manual",
            "source_task": int(data.get("source_task") or 0),
            "created_at": datetime.now(),
            "geojson": geojson_text,
        }
        stmt = insert(PLOT).values(
            code=payload["code"], name=payload["name"], land_type=payload["land_type"], region=payload["region"],
            owner=payload["owner"], area_m2=payload["area_m2"], area_mu=payload["area_mu"],
            origin=payload["origin"], source_task=payload["source_task"], created_at=payload["created_at"],
            geom=self._geom_expr("geojson"),
        ).returning(PLOT.c.id)
        async with self._sm() as session:
            new_id = (await session.execute(stmt, {"geojson": geojson_text})).scalar()
            await session.commit()
        created = await self.get_plot(int(new_id))
        return created or payload | {"id": new_id, "geometry": geom.__geo_interface__}

    async def bulk_create(self, rows: list[dict[str, Any]]) -> int:
        created = 0
        for row in rows:
            await self.create_plot(row)
            created += 1
        return created

    async def get_plot(self, plot_id: int) -> dict[str, Any] | None:
        stmt = select(
            PLOT.c.id, PLOT.c.code, PLOT.c.name, PLOT.c.land_type, PLOT.c.region, PLOT.c.owner,
            PLOT.c.area_m2, PLOT.c.area_mu, PLOT.c.origin, PLOT.c.source_task, PLOT.c.created_at,
            func.ST_AsGeoJSON(PLOT.c.geom).label("geojson"),
        ).where(PLOT.c.id == plot_id)
        async with self._sm() as session:
            row = (await session.execute(stmt)).first()
        return _shape(row) if row else None

    async def list_plots(
        self, *, name: str = "", land_type: str = "", region: str = "", page: int = 1, size: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        page, size = max(page, 1), max(min(size, 500), 1)
        conds = []
        if name:
            conds.append(PLOT.c.name.like(f"%{name}%") | PLOT.c.code.like(f"%{name}%"))
        if land_type:
            conds.append(PLOT.c.land_type == land_type)
        if region:
            conds.append(PLOT.c.region == region)
        stmt = select(
            PLOT.c.id, PLOT.c.code, PLOT.c.name, PLOT.c.land_type, PLOT.c.region, PLOT.c.owner,
            PLOT.c.area_m2, PLOT.c.area_mu, PLOT.c.origin, PLOT.c.source_task, PLOT.c.created_at,
            func.ST_AsGeoJSON(PLOT.c.geom).label("geojson"),
        ).where(*conds).order_by(PLOT.c.id.desc()).limit(size).offset((page - 1) * size)
        async with self._sm() as session:
            total = (await session.execute(select(func.count()).select_from(PLOT).where(*conds))).scalar() or 0
            rows = (await session.execute(stmt)).all()
        return [_shape(r) for r in rows], int(total)

    async def update_plot(self, plot_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        if not await self.get_plot(plot_id):
            return None
        values = {k: data[k] for k in ("code", "name", "land_type", "region", "owner") if k in data}
        geom_raw = data.get("geometry") or data.get("geojson")
        if geom_raw:
            geom = normalize_geom(geom_raw)
            if geom is None:
                raise ValueError("地块边界无法解析为面要素")
            geojson_text = json.dumps(geom.__geo_interface__, ensure_ascii=False)
            area = round(geodetic_area_m2(geom), 2)
            values.update(area_m2=area, area_mu=mu_of(area), geom=self._geom_expr("geojson"))
            async with self._sm() as session:
                await session.execute(update(PLOT).where(PLOT.c.id == plot_id).values(**values), {"geojson": geojson_text})
                await session.commit()
        elif values:
            async with self._sm() as session:
                await session.execute(update(PLOT).where(PLOT.c.id == plot_id).values(**values))
                await session.commit()
        return await self.get_plot(plot_id)

    async def delete_plot(self, plot_id: int) -> bool:
        async with self._sm() as session:
            result = await session.execute(delete(PLOT).where(PLOT.c.id == plot_id))
            await session.commit()
        return result.rowcount > 0

    async def clear_plots(self) -> int:
        async with self._sm() as session:
            result = await session.execute(delete(PLOT))
            await session.commit()
        return result.rowcount

    async def plot_count(self) -> int:
        async with self._sm() as session:
            return int((await session.execute(select(func.count()).select_from(PLOT))).scalar() or 0)

    async def plot_statistics(self) -> dict[str, Any]:
        async with self._sm() as session:
            rows = (
                await session.execute(
                    select(PLOT.c.land_type, PLOT.c.region, PLOT.c.area_m2, PLOT.c.area_mu,
                           func.ST_AsGeoJSON(func.ST_Centroid(PLOT.c.geom)).label("c"))
                )
            ).all()
        dicts = [
            {"land_type": r.land_type, "region": r.region, "area_m2": float(r.area_m2 or 0), "area_mu": float(r.area_mu or 0)}
            for r in rows
        ]
        return summarize(dicts, engine=self.mode)

    async def plot_extent(self, *, land_types: list[str] | None = None, region: str = "") -> list[float] | None:
        conds = []
        if land_types:
            conds.append(PLOT.c.land_type.in_(land_types))
        regions = [r for r in re.split(r"[,，、;；/\s]+", region or "") if r]
        if regions:
            conds.append(PLOT.c.region.in_(regions))
        stmt = select(
            func.ST_XMin(func.ST_Extent(PLOT.c.geom)), func.ST_YMin(func.ST_Extent(PLOT.c.geom)),
            func.ST_XMax(func.ST_Extent(PLOT.c.geom)), func.ST_YMax(func.ST_Extent(PLOT.c.geom)),
        ).select_from(PLOT).where(*conds)
        async with self._sm() as session:
            row = (await session.execute(stmt)).first()
        if not row or row[0] is None:
            return None
        return [round(float(v), 6) for v in row]

    # ---------------- 空间提取（文档主路径 SQL） ----------------
    EXTRACT_SQL = """
        WITH aoi AS (
            SELECT ST_SetSRID(ST_GeomFromGeoJSON(:aoi), 4326) AS g
        )
        SELECT p.id, p.code, p.name, p.land_type, p.region, p.owner, p.origin,
               ST_Area(ST_Intersection(p.geom, aoi.g)::geography) AS area_m2,
               ST_AsGeoJSON(ST_SimplifyPreserveTopology(
                   ST_CollectionExtract(ST_Intersection(p.geom, aoi.g), 3), :simplify)) AS geojson
        FROM plot p, aoi
        WHERE ST_Intersects(p.geom, aoi.g)
          {land_cond}
          AND ST_Area(ST_Intersection(p.geom, aoi.g)::geography) * :mu_per_m2 >= :min_area_mu
        ORDER BY area_m2 DESC
        LIMIT :limit
    """

    async def extract(
        self,
        aoi,
        *,
        land_types: list[str] | None = None,
        min_area_mu: float = 0,
        simplify_tol: float = 0.0001,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        if aoi is None or aoi.is_empty:
            return []
        sql = self.EXTRACT_SQL.format(land_cond="AND p.land_type = ANY(:land_types)" if land_types else "")
        params: dict[str, Any] = {
            "aoi": json.dumps(aoi.__geo_interface__, ensure_ascii=False),
            "simplify": float(simplify_tol or 0),
            "mu_per_m2": MU_PER_M2,
            "min_area_mu": float(min_area_mu or 0),
            "limit": int(limit),
        }
        if land_types:
            params["land_types"] = list(land_types)
        async with self._sm() as session:
            rows = (await session.execute(text(sql), params)).all()
        out = []
        for row in rows:
            mapping = _shape(row)
            mapping["area_mu"] = mu_of(mapping["area_m2"])
            out.append(mapping)
        return out

    # ---------------- 提取记录 ----------------
    async def save_task(self, data: dict[str, Any]) -> int:
        async with self._sm() as session:
            result = await session.execute(insert(TASK).values(_task_values(data)))
            await session.commit()
        return int(result.inserted_primary_key[0])

    async def update_task(self, task_id: int, data: dict[str, Any]) -> None:
        async with self._sm() as session:
            await session.execute(update(TASK).where(TASK.c.id == task_id).values(**data))
            await session.commit()

    async def list_tasks(self, *, page: int = 1, size: int = 10, mode: str = "") -> tuple[list[dict[str, Any]], int]:
        conds = [TASK.c.mode == mode] if mode else []
        async with self._sm() as session:
            total = (await session.execute(select(func.count()).select_from(TASK).where(*conds))).scalar() or 0
            rows = (
                (await session.execute(select(TASK).where(*conds).order_by(TASK.c.id.desc()).limit(size).offset((max(page, 1) - 1) * size)))
                .all()
            )
            return [task_dict(r) for r in rows], int(total)

    async def get_task(self, task_id: int) -> dict[str, Any] | None:
        async with self._sm() as session:
            row = (await session.execute(select(TASK).where(TASK.c.id == task_id))).first()
        return task_dict(row) if row else None

    async def delete_task(self, task_id: int) -> bool:
        async with self._sm() as session:
            result = await session.execute(delete(TASK).where(TASK.c.id == task_id))
            await session.commit()
        return result.rowcount > 0

    # ---------------- 向量（pgvector 表由 PGVector 自行管理） ----------------
    async def add_chunks(self, rows: list[dict[str, Any]]) -> int:
        raise NotImplementedError("PostGIS 模式下向量由 pgvector 存储")

    async def delete_doc_chunks(self, doc_id: int) -> int:
        async with self._sm() as session:
            result = await session.execute(
                text("DELETE FROM langchain_pg_embedding WHERE cmetadata->>'doc_id' = :doc_id"), {"doc_id": str(doc_id)}
            )
            await session.commit()
        return int(result.rowcount or 0)

    async def all_chunks(self) -> list[dict[str, Any]]:
        raise NotImplementedError("PostGIS 模式下向量由 pgvector 存储")

    async def chunk_count(self) -> int:
        async with self._sm() as session:
            try:
                return int(
                    (await session.execute(text("SELECT count(*) FROM langchain_pg_embedding"))).scalar() or 0
                )
            except Exception:
                return 0


def _shape(row) -> dict[str, Any]:
    data = dict(row._mapping)
    raw = data.pop("geojson", None)
    geometry = None
    if raw:
        try:
            geometry = json.loads(raw)
        except (ValueError, TypeError):
            geometry = None
    created = data.pop("created_at", None)
    return {
        "id": int(data.get("id") or 0),
        "code": data.get("code") or "",
        "name": data.get("name") or "",
        "land_type": data.get("land_type") or "",
        "region": data.get("region") or "",
        "owner": data.get("owner") or "",
        "area_m2": float(data.get("area_m2") or 0),
        "area_mu": mu_of(data.get("area_m2") or 0),
        "origin": data.get("origin") or "vector",
        "source_task": int(data.get("source_task") or 0),
        "geometry": geometry,
        "created_at": created.strftime("%Y-%m-%d %H:%M:%S") if created else "",
    }


def geom_area_pg(geom) -> float:
    """入库面积先按球面算，PostGIS 内如需精确可用 ::geography 复算。"""
    return geodetic_area_m2(geom)


def _task_values(data: dict[str, Any]) -> dict[str, Any]:
    from app.db.local_store import _task_values as local_values

    return local_values(data)
