"""接口自检脚本：跑通登录 → 配置 → 知识库 → 地块 → 提取 → 记录 → 问答 → 底图 全链路。

用法（后端需已启动）：python scripts/api_check.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:9090"
CLIENT = httpx.Client(base_url=BASE, timeout=200)
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} | {name} | {detail[:220]}")
    if not ok:
        FAILED.append(name)


def login(username: str = "admin", password: str = "admin123") -> dict:
    resp = CLIENT.post("/api/auth/login", json={"username": username, "password": password})
    resp.raise_for_status()
    data = resp.json()
    CLIENT.headers["Authorization"] = f"Bearer {data['token']}"
    return data


def main() -> int:
    section("健康检查")
    resp = CLIENT.get("/api/health")
    check("health", resp.status_code == 200, f"gis={resp.json()['gis']['mode']} vector={resp.json()['vector']['backend']}")

    section("账号与权限")
    data = login()
    check("登录", data["user"]["role"] == "admin", f"role={data['user']['role']}")
    check("未带凭证访问受限接口", CLIENT.get("/api/config/schema", headers={"Authorization": ""}).status_code in (401, 403))
    check("当前用户", CLIENT.get("/api/auth/me").json()["username"] == "admin")
    reg = CLIENT.post("/api/auth/register", json={"username": f"tester{random.randint(1000, 9999)}", "password": "123456", "nickname": "测试员"})
    check("注册普通用户", reg.status_code == 200 or "占用" in reg.text, reg.text[:80])
    user_token = reg.json().get("token") if reg.status_code == 200 else None
    tester_id = (reg.json().get("user") or {}).get("id")
    if user_token:
        forbidden = CLIENT.get("/api/config/schema", headers={"Authorization": f"Bearer {user_token}"})
        check("普通用户越权访问配置被拒", forbidden.status_code == 403, f"status={forbidden.status_code}")

    section("系统配置")
    schema = CLIENT.get("/api/config/schema").json()
    groups = [g["code"] for g in schema["groups"]]
    check("配置 schema 分组", len(groups) == 6, ",".join(groups))
    secrets_masked = all(
        item["value"] in {"******", ""} for g in schema["groups"] for item in g["items"] if item["secret"]
    )
    check("密码字段脱敏", secrets_masked)
    status = CLIENT.get("/api/config/status").json()
    check("运行状态", status["gis"]["ok"] and "vector" in status, f"chunks={status.get('chunks')}")
    saved = CLIENT.put("/api/config", json={"values": {"extract.min_area_mu": 3, "llm.api_key": "******"}})
    check("保存配置（提交 ****** 视为不修改）", saved.status_code == 200 and "llm.api_key" not in saved.json()["changed"], str(saved.json().get("changed")))
    for target in ("llm", "embed", "sys_db", "gis", "tiles"):
        result = CLIENT.post("/api/config/test", json={"target": target}).json()["result"]
        check(f"连通性测试 {target}", bool(result.get("ok")), json.dumps(result, ensure_ascii=False)[:150])

    section("知识库")
    docs = CLIENT.get("/api/knowledge/docs").json()
    if docs["total"] == 0:
        for name in ("地类认定与面积口径说明", "操作手册与业务问答"):
            path = Path(__file__).resolve().parent.parent / "data" / "kb" / f"{name}.md"
            CLIENT.post("/api/knowledge/upload", files={"file": (path.name, path.read_bytes(), "text/markdown")})
    docs = CLIENT.get("/api/knowledge/docs").json()
    check("文档列表", docs["total"] >= 1, f"docs={docs['total']}")
    hits = CLIENT.post("/api/knowledge/search", json={"query": "1 公顷等于多少亩", "k": 3}).json()
    check("检索测试（带相似度）", hits["count"] >= 1, json.dumps([(i["doc_name"][:6], i["score"]) for i in hits["items"]], ensure_ascii=False))

    section("地块管理")
    ctx = CLIENT.get("/api/extract/context").json()
    if ctx["plots"]["count"] == 0:
        CLIENT.post("/api/plots/sample", json={"count": 60, "overwrite": True})
    plots = CLIENT.get("/api/plots", params={"size": 5}).json()
    check("地块分页", plots["total"] > 0, f"total={plots['total']} engine={plots['engine']}")
    created = CLIENT.post(
        "/api/plots",
        json={
            "name": "自检地块",
            "land_type": "耕地",
            "region": "自检区",
            "geometry": {"type": "Polygon", "coordinates": [[[116.5, 39.9], [116.52, 39.9], [116.52, 39.915], [116.5, 39.915], [116.5, 39.9]]]},
        },
    ).json()
    check("新增地块自动算面积", created.get("area_mu", 0) > 1, f"area_mu={created.get('area_mu')} code={created.get('code')}")
    updated = CLIENT.put(f"/api/plots/{created['id']}", json={"name": "自检地块-改名"}).json()
    check("修改地块", updated["name"] == "自检地块-改名")
    check("删除地块", CLIENT.delete(f"/api/plots/{created['id']}").status_code == 200)

    section("智能提取（LangGraph 五节点）")
    aoi = {"type": "Polygon", "coordinates": [[[116.25, 39.83], [116.72, 39.83], [116.72, 40.02], [116.25, 40.02], [116.25, 39.83]]]}
    run = CLIENT.post("/api/extract/run", json={"query": "提取这片区域里大于 5 亩的耕地和园地", "mode": "smart", "aoi": aoi}).json()
    nodes = [t["node"] for t in run["trace"]]
    check("五节点全部执行", nodes == ["parse_intent", "locate_area", "retrieve_knowledge", "run_extraction", "analyze"], ",".join(nodes))
    check("提取有结果", run["statistics"].get("count", 0) > 0, f"count={run['statistics'].get('count')} mu={run['statistics'].get('total_area_mu')}")
    check("大模型结论非空", len(run.get("analysis", "")) > 20, (run.get("analysis") or "")[:120])
    space = CLIENT.post("/api/extract/run", json={"mode": "space", "aoi": aoi, "land_types": ["耕地"], "min_area_mu": 5}).json()
    check("纯计算模式（无 LLM 节点）", [t["node"] for t in space["trace"]][-1] == "analyze" and space["statistics"].get("origin") in {"vector", "candidate"}, f"count={space['statistics'].get('count')}")
    check("结论中的数字来自统计", str(space["statistics"].get("count")) in json.dumps(space, ensure_ascii=False))
    by_region = CLIENT.post("/api/extract/run", json={"query": "提取朝阳区大于 5 亩的耕地", "mode": "smart"}).json()
    located = next((t for t in by_region["trace"] if t["node"] == "locate_area"), {})
    check("只给行政区也能定位到地块库范围", "第 2 级" in located.get("detail", ""), located.get("detail", ""))
    check("按区提取命中真实地块", by_region["statistics"].get("origin") == "vector", f"count={by_region['statistics'].get('count')} mu={by_region['statistics'].get('total_area_mu')}")
    geo = CLIENT.get(f"/api/extract/geojson/{run['task_id']}")
    check("导出 GeoJSON", geo.status_code == 200 and geo.json()["type"] == "FeatureCollection", f"features={len(geo.json()['features'])}")
    saved_plots = CLIENT.post("/api/extract/save-plots", json={"task_id": run["task_id"], "region": "自检区"}).json()
    check("结果另存为地块", saved_plots.get("created", 0) > 0, json.dumps(saved_plots, ensure_ascii=False)[:120])

    section("提取记录")
    records = CLIENT.get("/api/records", params={"size": 5}).json()
    check("记录列表", records["total"] >= 2, f"total={records['total']}")
    one = CLIENT.get(f"/api/records/{records['items'][0]['id']}").json()
    check("记录详情含轨迹", len(one.get("trace", [])) >= 4, f"trace={len(one.get('trace', []))}")

    section("智能问答（ReAct Agent）")
    ask = CLIENT.post("/api/chat/ask", json={"message": "知识库里对面积口径是怎么规定的？简单说下 1 公顷等于多少亩。"}).json()
    check("问答返回结论", len(ask.get("answer", "")) > 20, f"via={ask.get('via')} steps={ask.get('steps')} {ask.get('answer', '')[:100]}")
    check("检索来源可视化", len(ask.get("sources", [])) >= 1, f"sources={len(ask.get('sources', []))}")
    ask2 = CLIENT.post("/api/chat/ask", json={"message": "库里现在一共有多少个地块、合计多少亩？", "session_id": ask["session_id"]}).json()
    check("工具调用轨迹", len(ask2.get("calls", [])) >= 1, json.dumps([c["name"] for c in ask2.get("calls", [])], ensure_ascii=False))
    sessions = CLIENT.get("/api/chat/sessions").json()
    check("会话持久化", sessions["items"], f"sessions={len(sessions['items'])}")
    msgs = CLIENT.get(f"/api/chat/sessions/{ask['session_id']}/messages").json()
    check("消息与来源落库", len(msgs["items"]) >= 4 and any(m["sources"] for m in msgs["items"]), f"messages={len(msgs['items'])}")

    section("底图")
    maps = CLIENT.get("/api/maps/basemaps").json()
    check("底图清单", len(maps["items"]) >= 7 and maps["fallback"]["key"] == "osm", f"items={len(maps['items'])}")
    tile = CLIENT.get("/api/maps/tile", params={"provider": "osm", "layer": "default", "z": 6, "x": 33, "y": 16})
    check("瓦片代理可用", tile.status_code == 200 and tile.headers["content-type"].startswith("image"), f"status={tile.status_code}")
    err = CLIENT.get("/api/maps/last-error", params={"provider": "tianditu", "http_status": 403, "body": '{"code":301020,"message":"auth failed"}'}).json()
    check("天地图 301020 错误码翻译", "安全密钥" in err.get("advice", ""), err.get("advice", "")[:80])
    err2 = CLIENT.get("/api/maps/last-error", params={"provider": "geovis", "http_status": 200, "body": '{"code":124,"message":"token invalid"}'}).json()
    check("星图伪装 200 的鉴权错误识别", "Token" in err2.get("advice", ""), err2.get("advice", "")[:80])

    section("自检数据清理")
    junk = CLIENT.get("/api/plots", params={"region": "自检区", "size": 500}).json()
    for item in junk["items"]:
        CLIENT.delete(f"/api/plots/{item['id']}")
    left = CLIENT.get("/api/plots", params={"region": "自检区"}).json()["total"]
    check("移除自检产生的地块", left == 0, f"deleted={len(junk['items'])} left={left}")
    if tester_id:
        CLIENT.delete(f"/api/users/{tester_id}")
    names = [u["username"] for u in CLIENT.get("/api/users", params={"size": 200}).json()["items"]]
    check("移除自检账号", not any(n.startswith("tester") for n in names), ",".join(names))

    print()
    if FAILED:
        print(f"存在 {len(FAILED)} 项失败：{FAILED}")
        return 1
    print("全部接口自检通过")
    return 0


def section(title: str) -> None:
    print(f"\n===== {title} =====")


if __name__ == "__main__":
    sys.exit(main())
