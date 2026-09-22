"""地图瓦片服务：服务端代理注入 tk/sk，并把各家错误码翻译成中文排查建议。

星图会把鉴权错误伪装成 HTTP 200 + JSON，这里专门识别；天地图返回错误码时也不再是
一串数字，而是能直接照着做的建议。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config.runtime import runtime

log = logging.getLogger(__name__)

TIANDITU_CODES: dict[str, str] = {
    "301020": "应用开启了安全密钥，瓦片请求必须带 sk 参数。请在「系统配置 → 天地图」启用“启用安全密钥”并填写 sk。",
    "301021": "找不到对应的 Key（tk 无效）。请核对其与请求域名是否为同一个天地图应用。",
    "301022": "Key 已被禁用或过期。请到天地图控制台启用或删除后重新申请。",
    "301023": "该 Key 的日访问配额已用尽。请提升配额或降低瓦片请求频率。",
    "301024": "该 Key 未开通此服务/图层权限。请在控制台勾选对应的瓦片服务（如 img_w、cia_w）。",
    "301025": "该 Key 的 IP 白名单限制了来源，请把服务器出口 IP 加入白名单。",
}

GEOVIS_CODES: dict[str, str] = {
    "124": "GEOVIS Token 校验失败（无效、过期，或未开通该图层服务）。",
    "128": "访问被风控拦截或超出配额。请确认 Token 用途为「地图服务」，稍后重试。",
}

PROVIDERS = {
    "tianditu": {
        "name": "天地图",
        "layers": {"img": "img_url", "vec": "vec_url", "ter": "ter_url", "cia": "cia_url", "cva": "cva_url"},
        "layer_codes": {"img": "img", "vec": "vec", "ter": "ter", "cia": "cia", "cva": "cva"},
    },
    "geovis": {
        "name": "星图云 GEOVIS",
        "layers": {"img": "geovis.image_url", "vec": "geovis.vector_url", "ter": "geovis.terrain_url", "cta": "geovis.anno_url"},
    },
    "osm": {"name": "OpenStreetMap（备用底图）", "layers": {"default": "https://tile.openstreetmap.org/{z}/{x}/{y}.png"}},
}


def _inject_sk(url: str) -> str:
    """开启安全密钥后自动在瓦片地址上追加 sk，旧配置不用手动改。"""
    if not runtime.get_bool("tianditu.use_sk", False):
        return url
    sk = runtime.get_str("tianditu.sk")
    if not sk or "sk=" in url:
        return url
    return url + ("&" if "?" in url else "?") + f"sk={sk}"


def tianditu_url(layer: str, z: int, x: int, y: int) -> str:
    code = PROVIDERS["tianditu"]["layer_codes"].get(layer, layer)
    base = runtime.get_str(f"tianditu.{layer}_url") or _default_tianditu(layer)
    base = base.replace("{s}", "0")
    token = runtime.get_str("tianditu.token")
    url = (
        f"{base}?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER={code}"
        f"&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk={token}"
    )
    return _inject_sk(url)


def _default_tianditu(layer: str) -> str:
    return f"https://t0.tianditu.gov.cn/{layer}_w/wmts"


def geovis_url(layer: str, z: int, x: int, y: int) -> str:
    template = runtime.get_str(PROVIDERS["geovis"]["layers"].get(layer, "geovis.image_url"))
    token = runtime.get_str("geovis.token")
    url = template.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
    return (url + ("&" if "?" in url else "?") + f"token={token}") if token else url


def osm_url(z: int, x: int, y: int) -> str:
    return f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"


def upstream_url(provider: str, layer: str, z: int, x: int, y: int) -> str:
    if provider == "tianditu":
        return tianditu_url(layer, z, x, y)
    if provider == "geovis":
        return geovis_url(layer, z, x, y)
    return osm_url(z, x, y)


def translate_error(provider: str, status: int, body: bytes, headers: dict[str, str]) -> dict[str, Any] | None:
    """返回 None 表示这是一张正常瓦片；否则返回结构化错误信息与中文建议。"""
    ctype = (headers.get("content-type") or "").lower()
    text = body.decode("utf-8", errors="replace") if len(body) < 8192 else ""
    codes = TIANDITU_CODES if provider == "tianditu" else GEOVIS_CODES

    if "json" in ctype or text.lstrip().startswith("{"):
        try:
            import json

            payload = json.loads(text)
        except (ValueError, TypeError):
            payload = None
        if payload:
            code = str(payload.get("code", payload.get("status", "")))
            message = str(payload.get("message", payload.get("msg", "")))
            if code or status >= 400:
                return {
                    "http_status": status,
                    "code": code or None,
                    "message": message or None,
                    "advice": codes.get(code) or _generic_advice(provider, status),
                    "raw": text[:200],
                }
    if status == 403 or status == 401:
        code = _scan_code(text)
        return {
            "http_status": status,
            "code": code,
            "advice": codes.get(code) or _generic_advice(provider, status),
            "raw": text[:200],
        }
    if status >= 400:
        return {"http_status": status, "code": None, "advice": _generic_advice(provider, status), "raw": text[:200]}
    return None


def _scan_code(text: str) -> str:
    for code in (*TIANDITU_CODES, *GEOVIS_CODES):
        if code in text:
            return code
    return ""


def _generic_advice(provider: str, status: int) -> str:
    if provider == "tianditu":
        return "天地图瓦片请求失败。请检查 tk 是否正确、服务器能否访问 t0.tianditu.gov.cn，以及该 Key 是否开通了瓦片服务。"
    if provider == "geovis":
        return "星图云瓦片请求失败。注意其鉴权错误会伪装成 HTTP 200 + JSON，请核对本系统配置里的 GEOVIS Token。"
    return "备用底图（OpenStreetMap）请求失败，通常是网络不通或被限频。"


async def fetch_tile(provider: str, layer: str, z: int, x: int, y: int) -> tuple[int, str, bytes, dict[str, Any] | None]:
    url = upstream_url(provider, layer, z, x, y)
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            resp = await client.get(url, headers={"user-agent": "plot-extraction-platform/1.0", "referer": "localhost"})
    except Exception as exc:
        return 502, "application/json", b"", {
            "http_status": 0,
            "code": None,
            "advice": f"请求上游瓦片失败：{type(exc).__name__}: {str(exc)[:120]}",
            "url": _safe_url(url),
        }
    error = translate_error(provider, resp.status_code, resp.content, dict(resp.headers))
    if error:
        error["url"] = _safe_url(url)
        return 424, "application/json", b"", error
    return resp.status_code, resp.headers.get("content-type", "application/octet-stream"), resp.content, None


async def check_tiles() -> dict[str, Any]:
    """一键瓦片测试：每类底图各取一瓦，返回可用性、错误码与建议。"""
    targets = [
        ("tianditu", "img", "天地图影像 img_w"),
        ("tianditu", "vec", "天地图矢量 vec_w"),
        ("tianditu", "cia", "天地图注记 cia_w"),
        ("geovis", "img", "星图影像"),
        ("geovis", "vec", "星图矢量"),
        ("osm", "default", "OpenStreetMap 备用"),
    ]
    results = await asyncio.gather(*[_probe(p, l, name) for p, l, name in targets])
    ok = sum(1 for r in results if r["ok"])
    return {
        "ok": ok > 0,
        "summary": f"{ok}/{len(results)} 类瓦片可访问",
        "degrade_hint": "前端连续 3 张瓦片报错会自动切到 OpenStreetMap 备用底图",
        "items": list(results),
    }


async def _probe(provider: str, layer: str, name: str) -> dict[str, Any]:
    started = asyncio.get_running_loop().time()
    status, _ctype, _body, error = await fetch_tile(provider, layer, 6, 33, 16)
    elapsed = int((asyncio.get_running_loop().time() - started) * 1000)
    configured = bool(runtime.get_str("tianditu.token")) if provider == "tianditu" else (
        bool(runtime.get_str("geovis.token")) if provider == "geovis" else True
    )
    return {
        "provider": provider,
        "layer": layer,
        "name": name,
        "ok": error is None and status == 200,
        "status": status,
        "elapsed_ms": elapsed,
        "configured": configured,
        "message": None if configured else "该项未在系统配置中填写凭据",
        "error": error,
    }


def _safe_url(url: str) -> str:
    for key in ("tk=", "token=", "sk="):
        if key in url:
            head, _, tail = url.partition(key)
            token = tail.split("&", 1)[0]
            url = f"{head}{key}{token[:3]}***(已脱敏)"
            break
    return url


def basemaps() -> list[dict[str, Any]]:
    """前端底图清单：瓦片统一走后端代理，凭据不下发到浏览器。"""
    items = [
        {"key": "tianditu_img", "name": "天地图影像", "provider": "tianditu", "layer": "img", "anno": "cia",
         "url": "/api/maps/tile?provider=tianditu&layer=img&z={z}&x={x}&y={y}", "attribution": "© 天地图"},
        {"key": "tianditu_vec", "name": "天地图矢量", "provider": "tianditu", "layer": "vec", "anno": "cva",
         "url": "/api/maps/tile?provider=tianditu&layer=vec&z={z}&x={x}&y={y}", "attribution": "© 天地图"},
        {"key": "tianditu_ter", "name": "天地图地形", "provider": "tianditu", "layer": "ter", "anno": "cia",
         "url": "/api/maps/tile?provider=tianditu&layer=ter&z={z}&x={x}&y={y}", "attribution": "© 天地图"},
        {"key": "geovis_img", "name": "星图云影像", "provider": "geovis", "layer": "img", "anno": "cta",
         "url": "/api/maps/tile?provider=geovis&layer=img&z={z}&x={x}&y={y}", "attribution": "© 星图云 GEOVIS Earth"},
        {"key": "geovis_vec", "name": "星图云矢量", "provider": "geovis", "layer": "vec", "anno": "cva",
         "url": "/api/maps/tile?provider=geovis&layer=vec&z={z}&x={x}&y={y}", "attribution": "© 星图云 GEOVIS Earth"},
        {"key": "geovis_ter", "name": "星图云地形", "provider": "geovis", "layer": "ter", "anno": "cta",
         "url": "/api/maps/tile?provider=geovis&layer=ter&z={z}&x={x}&y={y}", "attribution": "© 星图云 GEOVIS Earth"},
        {"key": "tianditu_anno", "name": "天地图注记层", "provider": "tianditu", "layer": "cia",
         "url": "/api/maps/tile?provider=tianditu&layer=cia&z={z}&x={x}&y={y}", "attribution": "© 天地图"},
        {"key": "osm", "name": "OpenStreetMap（备用）", "provider": "osm", "layer": "default",
         "url": "/api/maps/tile?provider=osm&layer=default&z={z}&x={x}&y={y}", "attribution": "© OpenStreetMap"},
    ]
    for item in items:
        item["configured"] = bool(runtime.get_str("tianditu.token")) if item["provider"] == "tianditu" else (
            bool(runtime.get_str("geovis.token")) if item["provider"] == "geovis" else True
        )
    return items
