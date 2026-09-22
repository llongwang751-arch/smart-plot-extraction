"""示例地块生成：给前端「生成示例数据」按钮和冷启动演示用。"""
from __future__ import annotations

import math
import random
from typing import Any

from app.db.gis_store import gis
from app.utils.units import M2_PER_MU, LAND_TYPES

REGIONS = ["朝阳区", "海淀区", "丰台区", "通州区", "大兴区"]
OWNERS = ["张建国", "李秀兰", "王守田", "赵春生", "集体流转", "绿源合作社"]
CENTERS = {
    "朝阳区": (116.486, 39.92),
    "海淀区": (116.310, 39.985),
    "丰台区": (116.287, 39.858),
    "通州区": (116.657, 39.909),
    "大兴区": (116.341, 39.726),
}


def _jittered_rect(lon: float, lat: float, mu_area: float, rng: random.Random) -> dict[str, Any]:
    side_m = math.sqrt(max(mu_area, 1.0) * M2_PER_MU)
    dlat = side_m / 111_320.0
    dlon = side_m / (111_320.0 * max(abs(math.cos(math.radians(lat))), 0.05))
    stretch = rng.uniform(0.6, 1.9)
    x0, y0 = lon - dlon / 2 + rng.uniform(-0.01, 0.01), lat - dlat / 2 + rng.uniform(-0.01, 0.01)
    x1, y1 = x0 + dlon * stretch, y0 + dlat / stretch
    if rng.random() < 0.35:  # 一部分画成不规则多边形，贴近真实边界
        return _hexagon(x0, y0, x1, y1, rng)
    return {
        "type": "Polygon",
        "coordinates": [[(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]],
    }


def _hexagon(x0: float, y0: float, x1: float, y1: float, rng: random.Random) -> dict[str, Any]:
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    ring = []
    for i in range(7):
        angle = (2 * math.pi * i) / 7 + rng.uniform(-0.12, 0.12)
        scale = rng.uniform(0.78, 1.05)
        ring.append((cx + rx * math.cos(angle) * scale, cy + ry * math.sin(angle) * scale))
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


async def generate_sample_plots(count: int = 60, seed: int | None = None, overwrite: bool = False) -> dict[str, Any]:
    rng = random.Random(seed if seed is not None else 20260922)
    if overwrite:
        await gis.clear_plots()
    existing = await gis.plot_count()
    created = 0
    for index in range(count):
        region = REGIONS[index % len(REGIONS)]
        lon, lat = CENTERS[region]
        land_type = LAND_TYPES[rng.randrange(len(LAND_TYPES))]
        mu_area = round(rng.uniform(1.5, 260), 2)
        code = f"SMP{existing + index + 1:04d}"
        try:
            await gis.create_plot(
                {
                    "code": code,
                    "name": f"{region}{land_type}示例地块{index + 1:03d}",
                    "land_type": land_type,
                    "region": region,
                    "owner": rng.choice(OWNERS),
                    "origin": "manual",
                    "geometry": _jittered_rect(lon, lat, mu_area, rng),
                }
            )
            created += 1
        except Exception as exc:  # pragma: no cover
            log.warning("示例地块生成失败（第 %d 个）：%s", index, exc)
    return {"created": created, "total": await gis.plot_count()}
