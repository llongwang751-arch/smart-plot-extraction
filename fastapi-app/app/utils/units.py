"""单位换算：地类面积口径统一以“亩”为业务单位。1 亩 = 666.6667 平方米。"""
from __future__ import annotations

M2_PER_MU = 666.6666666667
MU_UNITS: dict[str, float] = {
    "亩": 1.0,
    "平方米": 1 / M2_PER_MU,
    "㎡": 1 / M2_PER_MU,
    "m2": 1 / M2_PER_MU,
    "公顷": 10000 / M2_PER_MU,
    "ha": 10000 / M2_PER_MU,
    "平方公里": 1_000_000 / M2_PER_MU,
    "km2": 1_000_000 / M2_PER_MU,
    "平方千米": 1_000_000 / M2_PER_MU,
}

MU_PER_M2 = 1.0 / M2_PER_MU

LAND_TYPES = ["耕地", "园地", "林地", "草地", "建设用地", "水域", "未利用地"]


def to_mu(value: float, unit: str | None) -> float:
    if value is None:
        return 0.0
    factor = MU_UNITS.get((unit or "亩").strip(), 1.0)
    return round(value * factor, 4)


def m2_to_mu(m2: float) -> float:
    return round(float(m2 or 0) * MU_PER_M2, 2)


def mu_to_m2(mu: float) -> float:
    return float(mu or 0) * M2_PER_MU


def fmt_area(m2: float) -> str:
    m2 = float(m2 or 0)
    if m2 >= 1_000_000:
        return f"{m2 / 1_000_000:.2f} 平方公里"
    if m2 >= 10_000:
        return f"{m2 / 10_000:.2f} 公顷"
    return f"{m2:.0f} 平方米"
