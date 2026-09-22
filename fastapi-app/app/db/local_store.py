"""本地降级引擎：几何存 GeoJSON 文本，空间计算交给 Shapely。

与 PostGIS 引擎实现同一套接口，语义保持一致：
ST_Area(::geography) → 球面面积；ST_Intersection → shapely.intersection；
ST_SimplifyPreserveTopology → shapely.simplify(preserve_topology=True)；
ST_CollectionExtract(...,3) → polygons_only()。
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import mu_of, plot_dict, summarize, task_dict
from app.models import gis_tables as _t
from app.utils.geo import bbox as geom_bbox
from app.utils.geo import geodetic_area_m2, normalize_geom, polygons_only
from app.utils.geo import simplify as shp_simplify
from app.utils.units import MU_PER_M2

PLOT = _t.local_meta.tables["plot"]
TASK = _t.local_meta.tables["extraction_task"]
CHUNK = _t.local_meta.tables["kb_chunk"]


class LocalGisStore:
    mode = "local"

    def __init__(self, url: str) -> None:
        self.url = url
        self._engine = None
        self._sm: async_sessionmaker | None = None

    # ---------------- 生命周期 ----------------
    async def connect(self) -> None:
        from app.config.env import async_sqlite_url

        self._engine = create_async_engine(async_sqlite_url(self.url), future=True)
        async with self._engine.begin() as conn:
            await conn.run_sync(lambda c: _t.local_meta.create_all(c, checkfirst=True))
        self._sm = async_sessionmaker(self._engine, expire_on_commit=False)

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sm = None

    async def health(self) -> dict[str, Any]:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        count = await self.plot_count()
        return {"mode": "local", "ok": True, "plots": count, "note": "本地引擎（Shapely 空间计算 + 本地向量检索）"}

    @property
    def engine(self):
        return self._engine

    # ---------------- 地块 ----------------
    async def create_plot(self, data: dict[str, Any]) -> dict[str, Any]:
        geom = normalize_geom(data.get("geometry") or data.get("geojson"))
        if geom is None:
            raise ValueError("地块边界无法解析为面要素")
        area_m2 = round(geodetic_area_m2(geom), 2)
        payload = {
            "code": data.get("code") or _auto_code(),
            "name": data.get("name") or "",
            "land_type": data.get("land_type") or "未利用地",
            "region": data.get("region") or "",
            "owner": data.get("owner") or "",
            "area_m2": area_m2,
            "area_mu": mu_of(area_m2),
            "origin": data.get("origin") or "manual",
            "source_task": int(data.get("source_task") or 0),
            "geojson": json.dumps(geom.__geo_interface__, ensure_ascii=False),
        }
        async with self._sm() as session:
            result = await session.execute(insert(PLOT).values(**payload))
            await session.commit()
            payload["id"] = result.inserted_primary_key[0]
        payload["geometry"] = geom.__geo_interface__
        payload["created_at"] = ""
        return payload

    async def bulk_create(self, rows: list[dict[str, Any]]) -> int:
        created = 0
        for row in rows:
            await self.create_plot(row)
            created += 1
        return created

    async def get_plot(self, plot_id: int) -> dict[str, Any] | None:
        async with self._sm() as session:
            row = (await session.execute(select(PLOT).where(PLOT.c.id == plot_id))).first()
        return plot_dict(row) if row else None

    async def list_plots(
        self, *, name: str = "", land_type: str = "", region: str = "", page: int = 1, size: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        page, size = max(page, 1), max(min(size, 500), 1)
        conds = _plot_filters(name, land_type, region)
        async with self._sm() as session:
            total = (await session.execute(select(func.count()).select_from(PLOT).where(*conds))).scalar() or 0
            rows = (
                (await session.execute(select(PLOT).where(*conds).order_by(PLOT.c.id.desc()).limit(size).offset((page - 1) * size)))
                .all()
            )
        return [plot_dict(r) for r in rows], int(total)

    async def iter_geoms(self, *, land_types: list[str] | None = None, region: str = "") -> list[dict[str, Any]]:
        conds = []
        if land_types:
            conds.append(PLOT.c.land_type.in_(land_types))
        cond = _region_cond(region)
        if cond is not None:
            conds.append(cond)
        async with self._sm() as session:
            rows = (await session.execute(select(PLOT).where(*conds))).all()
        return [plot_dict(r) for r in rows]

    async def update_plot(self, plot_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        current = await self.get_plot(plot_id)
        if not current:
            return None
        values = {k: data[k] for k in ("code", "name", "land_type", "region", "owner") if k in data}
        geom = normalize_geom(data.get("geometry") or data.get("geojson")) if (data.get("geometry") or data.get("geojson")) else None
        if geom is not None:
            area = round(geodetic_area_m2(geom), 2)
            values.update({"geojson": json.dumps(geom.__geo_interface__, ensure_ascii=False), "area_m2": area, "area_mu": mu_of(area)})
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
            plots = (await session.execute(select(PLOT))).all()
        dicts = [plot_dict(r) for r in plots]
        return summarize(dicts, engine=self.mode)

    async def plot_extent(self, *, land_types: list[str] | None = None, region: str = "") -> list[float] | None:
        plots = await self.iter_geoms(land_types=land_types, region=region)
        boxes = [geom_bbox(normalize_geom(p["geometry"])) for p in plots if p.get("geometry")]
        if not boxes:
            return None
        return [round(min(b[0] for b in boxes), 6), round(min(b[1] for b in boxes), 6),
                round(max(b[2] for b in boxes), 6), round(max(b[3] for b in boxes), 6)]

    # ---------------- 空间提取 ----------------
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
        candidates = await self.iter_geoms(land_types=land_types)
        out: list[dict[str, Any]] = []
        for plot in candidates:
            geom = normalize_geom(plot.get("geometry"))
            if geom is None or not geom.intersects(aoi):
                continue
            clipped = polygons_only(geom.intersection(aoi))
            if clipped is None or clipped.is_empty:
                continue
            clipped = shp_simplify(clipped, simplify_tol)
            area_m2 = round(geodetic_area_m2(clipped), 2)
            if area_m2 * MU_PER_M2 < float(min_area_mu or 0):
                continue
            plot["area_m2"] = area_m2
            plot["area_mu"] = mu_of(area_m2)
            plot["geometry"] = clipped.__geo_interface__
            out.append(plot)
        out.sort(key=lambda p: p["area_m2"], reverse=True)
        return out[: max(1, int(limit))]

    # ---------------- 提取记录 ----------------
    async def save_task(self, data: dict[str, Any]) -> int:
        async with self._sm() as session:
            result = await session.execute(insert(TASK).values(**_task_values(data)))
            await session.commit()
        return int(result.inserted_primary_key[0])

    async def update_task(self, task_id: int, data: dict[str, Any]) -> None:
        async with self._sm() as session:
            await session.execute(update(TASK).where(TASK.c.id == task_id).values(**_task_values(data, partial=True)))
            await session.commit()

    async def list_tasks(self, *, page: int = 1, size: int = 10, mode: str = "") -> tuple[list[dict[str, Any]], int]:
        conds = [TASK.c.mode == mode] if mode else []
        async with self._sm() as session:
            total = (await session.execute(select(func.count()).select_from(TASK).where(*conds))).scalar() or 0
            rows = (
                (
                    await session.execute(
                        select(TASK).where(*conds).order_by(TASK.c.id.desc()).limit(size).offset((max(page, 1) - 1) * size)
                    )
                )
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

    # ---------------- 本地向量表 ----------------
    async def add_chunks(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        async with self._sm() as session:
            await session.execute(insert(CHUNK).values(rows))
            await session.commit()
        return len(rows)

    async def delete_doc_chunks(self, doc_id: int) -> int:
        async with self._sm() as session:
            result = await session.execute(delete(CHUNK).where(CHUNK.c.doc_id == doc_id))
            await session.commit()
        return result.rowcount

    async def all_chunks(self) -> list[dict[str, Any]]:
        async with self._sm() as session:
            rows = (await session.execute(select(CHUNK))).all()
        return [
            {
                "id": r.id,
                "doc_id": r.doc_id,
                "doc_name": r.doc_name,
                "chunk_index": r.chunk_index,
                "content": r.content,
                "embedding": json.loads(r.embedding or "[]"),
                "metadata": json.loads(r.metadata or "{}"),
            }
            for r in rows
        ]

    async def chunk_count(self) -> int:
        async with self._sm() as session:
            return int((await session.execute(select(func.count()).select_from(CHUNK))).scalar() or 0)


def _plot_filters(name: str, land_type: str, region: str):
    conds = []
    if name:
        conds.append(PLOT.c.name.like(f"%{name}%") | PLOT.c.code.like(f"%{name}%"))
    if land_type:
        conds.append(PLOT.c.land_type == land_type)
    cond = _region_cond(region)
    if cond is not None:
        conds.append(cond)
    return conds


def _region_cond(region: str):
    """需求里的“朝阳区,海淀区”这类多区域写法，一律按 IN 处理。"""
    regions = [r for r in re.split(r"[,，、;；/\s]+", region or "") if r]
    if not regions:
        return None
    return PLOT.c.region.in_(regions) if len(regions) > 1 else PLOT.c.region == regions[0]


def _task_values(data: dict[str, Any], partial: bool = False) -> dict[str, Any]:
    values = {
        "title": data.get("title", ""),
        "query": data.get("query", ""),
        "mode": data.get("mode", "smart"),
        "engine": data.get("engine", ""),
        "aoi": json.dumps(data.get("aoi"), ensure_ascii=False) if data.get("aoi") else "",
        "land_types": ",".join(data.get("land_types") or []),
        "min_area_mu": float(data.get("min_area_mu") or 0),
        "geojson": json.dumps(data.get("geojson") or {"type": "FeatureCollection", "features": []}, ensure_ascii=False),
        "statistics": json.dumps(data.get("statistics") or {}, ensure_ascii=False),
        "trace": json.dumps(data.get("trace") or [], ensure_ascii=False),
        "analysis": data.get("analysis", ""),
        "status": data.get("status", "ok"),
        "error": data.get("error", ""),
        "elapsed_ms": int(data.get("elapsed_ms") or 0),
        "user_id": int(data.get("user_id") or 0),
    }
    return values if not partial else {k: v for k, v in values.items() if data.get(k) is not None}


def _auto_code() -> str:
    import random

    return f"PLT{random.randint(100000, 999999)}"
