"""空间提取服务：矢量裁剪主路径 + 规则网格兜底 + 统计口径。

语义与文档一致：
- 主路径在 GIS 存储层执行（PostGIS 里是 ST_Intersection/ST_Area(::geography)）；
- 库中没有命中地块时，用规则网格把 AOI 切成候选地块，编号 TMP0001 起，origin=candidate。
"""
from __future__ import annotations

import logging
from typing import Any

from app.config.runtime import runtime
from app.db.base import feature_collection, summarize
from app.db.gis_store import gis
from app.utils.geo import bbox, geodetic_area_m2, make_grid, normalize_geom, polygons_only, simplify
from app.utils.units import MU_PER_M2, m2_to_mu

log = logging.getLogger(__name__)

CANDIDATE_TYPE = "待认定"
CANDIDATE_LIMIT = 500  # 网格候选只用于人工核查，不做批量入库，控制返回体量


async def run_extraction(
    aoi: Any,
    *,
    land_types: list[str] | None = None,
    min_area_mu: float = 0,
    use_grid_fallback: bool = True,
    limit: int | None = None,
    allow_empty_aoi: bool = False,
) -> dict[str, Any]:
    """返回 {features, statistics, origin, warnings}。features 已是可渲染的 plot 字典列表。"""
    geom = normalize_geom(aoi)
    if geom is None or geom.is_empty:
        if not allow_empty_aoi:
            raise ValueError("提取范围为空或无法解析，请在地图上框选范围")
        geom = normalize_geom(default_aoi())

    tol = runtime.get_float("extract.simplify", 0.0001)
    top = limit or runtime.get_int("extract.max_features", 2000)
    warnings: list[str] = []

    features = await gis.extract(
        geom,
        land_types=[t for t in (land_types or []) if t] or None,
        min_area_mu=float(min_area_mu or 0),
        simplify_tol=tol,
        limit=top,
    )
    origin = "vector"
    if not features and use_grid_fallback:
        features, grid_msg = build_grid_candidates(
            geom, min_area_mu=float(min_area_mu or 0), tol=tol, limit=min(top, CANDIDATE_LIMIT)
        )
        origin = "candidate"
        if grid_msg:
            warnings.append(grid_msg)
        if features:
            warnings.append(f"库中无命中地块，已按规则网格生成 {len(features)} 个候选地块（origin=candidate，需人工核查）")

    statistics = summarize(features, aoi=geom, engine=gis.mode, origin=origin)
    if not features:
        warnings.append("范围内没有满足条件的地块，可放宽地类或最小面积后重试")
    return {
        "features": features,
        "statistics": statistics,
        "origin": origin,
        "warnings": warnings,
        "aoi": geom.__geo_interface__,
        "geojson": feature_collection(features),
    }


def build_grid_candidates(geom, *, min_area_mu: float, tol: float, limit: int) -> tuple[list[dict[str, Any]], str | None]:
    """兜底路径：按 extract_grid_size 生成规则格网，与 AOI 求交后保留落在范围内的部分。"""
    size = runtime.get_int("extract.grid_size", 300)
    cells, edge_used = make_grid(geom, size, max_cells=6000)
    message = None
    if edge_used != size:
        message = f"格数超过 6000，网格边长自动由 {size} 米放大为 {edge_used:.0f} 米"
    out: list[dict[str, Any]] = []
    for index, cell in enumerate(cells, start=1):
        piece = polygons_only(cell.intersection(geom))
        if piece is None or piece.is_empty:
            continue
        piece = simplify(piece, tol)
        area_m2 = round(geodetic_area_m2(piece), 2)
        if area_m2 * MU_PER_M2 < float(min_area_mu or 0):
            continue
        out.append(
            {
                "id": 0,
                "code": f"TMP{index:04d}",
                "name": f"网格候选地块 {index:04d}",
                "land_type": CANDIDATE_TYPE,
                "region": "",
                "owner": "",
                "area_m2": area_m2,
                "area_mu": m2_to_mu(area_m2),
                "origin": "candidate",
                "source_task": 0,
                "geometry": piece.__geo_interface__,
                "created_at": "",
            }
        )
        if len(out) >= limit:
            break
    out.sort(key=lambda p: p["area_m2"], reverse=True)
    return out, message


def default_aoi() -> dict[str, Any]:
    """默认中心点兜底：没框选范围时按配置的中心点与跨度生成一个 AOI。"""
    raw = runtime.get_str("extract.default_center", "116.397,39.908")
    try:
        lon, lat = [float(v) for v in raw.replace("，", ",").split(",")[:2]]
    except ValueError:
        lon, lat = 116.397, 39.908
    half = max(runtime.get_float("extract.default_extent_km", 3), 0.5) / 100.0
    return {"type": "Polygon", "coordinates": [[
        [lon - half, lat - half * 0.8], [lon + half, lat - half * 0.8],
        [lon + half, lat + half * 0.8], [lon - half, lat + half * 0.8],
        [lon - half, lat + half * 0.8],
    ]]}


def aoi_bbox(aoi: Any) -> list[float] | None:
    geom = normalize_geom(aoi)
    return list(bbox(geom)) if geom is not None else None


async def save_features_as_plots(features: list[dict[str, Any]], *, source_task: int = 0, region: str = "") -> int:
    """把提取结果（含网格候选）另存为正式地块。"""
    created = 0
    for feature in features:
        if not feature.get("geometry"):
            continue
        try:
            await gis.create_plot(
                {
                    "code": feature.get("code") or "",
                    "name": feature.get("name") or "",
                    "land_type": feature.get("land_type") if feature.get("land_type") != CANDIDATE_TYPE else "未利用地",
                    "region": region or feature.get("region") or "",
                    "owner": feature.get("owner") or "",
                    "origin": "vector",
                    "source_task": source_task,
                    "geometry": feature["geometry"],
                }
            )
            created += 1
        except Exception as exc:  # 单个几何失败不影响整批
            log.warning("另存地块失败：%s", exc)
    return created
