# 智能地块提取平台

自然语言 → 空间范围 → 地块提取 → 结论归纳的一体化平台。用一句话描述需求（「提取朝阳区大于 5 亩的耕地」），
系统自动解析意图、定位范围、召回领域知识、执行空间计算，并给出带口径说明的统计结论。

后端 **FastAPI + LangGraph + LangChain + RAG + PostGIS/pgvector**，前端 **Vue 3 + Element Plus + Leaflet**（手写 AOI 绘制，无 Pinia / ECharts / markdown 库）。

- 后端：[`fastapi-app/`](fastapi-app/) · 接口文档 `http://localhost:9090/docs`
- 前端：[`vue/`](vue/) · 开发态 `http://localhost:5173`

## 架构

```
Vue 3 + Element Plus
  首页 · 智能提取 · 提取记录 · 地块管理 · 知识库 · 智能问答 · 系统配置 · 用户管理
  MapCanvas：Leaflet 手绘矩形/多边形 · 手写 markdown 渲染
    |
    |  HTTP /api/*   Authorization: Bearer <HMAC 签名 token，7 天有效>
    v
FastAPI
  ├ 系统配置：schema 驱动前端表单，.env 冷启动 -> 数据库热更新，密钥用 ****** 脱敏
  ├ 鉴权：登录/注册（注册账号默认普通用户，管理员在用户管理页提权），用户管理保护最后一个管理员
  ├ 底图代理：服务端注入 token，错误码翻译（天地图 30102x / 星图 124·128），连续 3 次失败切 OSM
  ├ ReAct Agent：create_react_agent + 4 个工具，contextvars sink 把地块/片段/轨迹推回前端上图
  └ LangGraph 五节点工作流
      parse_intent -> locate_area -> retrieve_knowledge -> run_extraction -> analyze
        需求理解        范围定位         RAG 知识召回          空间提取          结论归纳
        （run_extraction 后接条件边：提取失败直接 END，不做无意义分析）
                                        |                  |
                                        v                  v
                              知识引擎（双向量后端）   空间引擎（双后端，接口契约一致）
                              多编码解析 / 中文切块     PostGIS + GeoAlchemy2 + pgvector
                                                       连不上时降级 SQLite + Shapely + numpy 余弦

外部依赖：LLM（OpenAI 兼容协议，chat + embedding，结构化输出四级降级
          json_schema -> function_calling -> json_mode -> prompt）· 瓦片（天地图 / 星图云 GEOVIS / OSM）
```

提取主路径 SQL：`ST_Intersection` + `ST_Area(...::geography)` + `ST_CollectionExtract(...,3)` + `ST_SimplifyPreserveTopology`。

### 防幻觉的三条硬约束

1. **几何只由空间引擎算**：范围按四级解析（前端框选 → 地块库已有范围 → 模型包围盒 → 默认中心点），
   模型永远不许直接给经纬度。
2. **数字只来自工具**：结论里的面积、个数一律引用 `run_extraction` 返回的统计值，前端渲染成时间线可核对。
3. **口径必须照实说**：库内无命中时按网格（默认 300 m，按 cos(纬度) 修正）生成候选地块，编号 `TMP…`，
   工具返回值里带「这不是真实地块」的口径说明，Agent 必须在回答中转述。

## 快速开始

### 后端

```bash
cd plot_extraction/fastapi-app
python -m venv ../.venv
../.venv/Scripts/pip install -r requirements.txt        # Linux/Mac: source ../.venv/bin/activate && pip install -r requirements.txt
cp .env.example .env                                     # 填写 LLM_API_KEY / 底图 token（.env 不入库）
../.venv/Scripts/python main.py                          # 监听 0.0.0.0:9090
```

首次启动建表 → 用 `.env` 播种「系统配置」→ 探测 PostGIS（可用则建 `plot` / `extract_task` + 空间索引，不可用则用本地引擎）。
默认管理员 `admin / admin123`（启动时按 `.env` 播种）；自助注册的账号一律是普通用户，需要管理员在「用户管理」里改角色。

### 前端

```bash
cd plot_extraction/vue
npm install
npm run dev          # :5173，代理 /api → 127.0.0.1:9090
npm run build        # 产物由后端直接托管，访问 :9090 即为完整应用
```

### 验证

```bash
cd plot_extraction/fastapi-app
PYTHONIOENCODING=utf-8 ../.venv/Scripts/python -u scripts/api_check.py    # 需先启动后端，43 项自检
```

覆盖鉴权与越权、配置读取与四连通测试、知识库入库与检索、地块 CRUD、智能/纯计算两种提取、
范围定位的回归守卫、记录回看、Agent 问答可追溯性、底图代理与错误码翻译，并在结束时清理自检数据。

Windows 控制台是 GBK，跑脚本前必须带 `PYTHONIOENCODING=utf-8`；含中文的请求体用该脚本而不是 curl。

## 不装 PostgreSQL / 不配密钥也能跑

| 依赖缺失 | 降级行为 | 影响 |
| :--- | :--- | :--- |
| PostgreSQL + PostGIS | SQLite + Shapely 空间计算 + numpy 余弦向量检索（`.data/gis_local.db`） | 接口契约完全一致，仅 `/api/health` 的 `gis.mode` 变化 |
| 大模型 key | 规则解析 + 本地模板结论（trace 标记 `local`） | 意图解析与问答质量下降，流程不中断 |
| 天地图 / 星图 token | 底图自动切 OSM，配置页可查连通性与错误码 | 偏移、注记图层不可用 |
| MySQL | `SYS_DB_URL` 默认 SQLite，改这一行即切 MySQL | 无 |

`/api/config/test` 可对 `llm` / `embed` / `sys_db` / `tiles` / `gis` 五类依赖逐个连通性自检。

## 接口

| 前缀 | 能力 |
| :--- | :--- |
| `/api/auth` | 登录、注册、当前用户、改资料、改密码 |
| `/api/users` | 用户管理（仅管理员，含最后一个管理员保护） |
| `/api/config` | `GET /schema` 驱动前端表单、`PUT` 保存（`******` 表示不修改）、`GET /status`、`POST /test` |
| `/api/plots` | 地块 CRUD、`/options` 下拉项、`/geojson` 全量导出、`/sample` 生成示例数据 |
| `/api/extract` | `POST /run`（`mode: smart` 走五节点，`mode: space` 纯计算）、`/save-plots` 结果入库、`GET /geojson/{task_id}`、`GET /context` |
| `/api/records` | 提取记录列表 / 详情（含 LangGraph 轨迹）/ 另存地块 / 删除 |
| `/api/knowledge` | 文档列表、文本录入、文件上传（txt/md/csv/json/pdf）、删除、`POST /search` 检索测试 |
| `/api/chat` | 会话 CRUD + `POST /ask`（ReAct Agent，返回 `sources` / `calls` / `plots`） |
| `/api/maps` | `/basemaps` 底图清单、`/tile` 服务端代理瓦片、`/check` 连通性与错误码翻译 |
| `/api/dashboard` | 首页统计卡片 |
| `/api/health` | 运行态：gis / vector / llm 三方状态 |

鉴权：`Authorization: Bearer <token>`；`/api/maps/tile?token=` 与 `?url=` 供 `<img>` 直接引用，
底图凭证只在服务端注入，永不下发到浏览器。

## 主要模块

```
fastapi-app/
  main.py                     lifespan、CORS、静态托管、全局异常
  app/config/    env.py schema.py runtime.py      冷启动默认值 → 配置项 schema → 数据库热更新
  app/models/    sys_tables.py gis_tables.py schemas.py
  app/db/        sys_db.py local_store.py postgis_store.py gis_store.py   双引擎门面
  app/llm/       provider.py structured.py        OpenAI 兼容 + 结构化输出四级降级
  app/rag/       loaders.py splitter.py vectorstore.py
  app/services/  extraction.py seed.py knowledge.py tiles.py
  app/workflows/ intent.py locate.py graph.py agent.py sink.py
  app/api/       auth users config plots knowledge extract records maps chat dashboard
  scripts/       api_check.py（43 项接口自检）
  data/kb/       示例领域文档（地类认定与面积口径、操作手册与业务问答）

vue/
  src/main.js  App.vue
  src/views/       Home Extract Records Plots Knowledge Chat Settings Users Login Layout
  src/components/  MapCanvas（手绘 AOI）TraceTimeline StatCards MdView
  src/api/         index.js（axios 实例 + 全部接口封装 + token 注入）
  src/router/      index.js（hash 路由 + 登录/管理员守卫）
  src/store/       index.js（手写响应式单例，未引入 Pinia）
  src/utils/       geo.js（包围盒 / 面积 / GeoJSON） markdown.js（手写渲染，转义优先）
  src/styles/      index.css
```

后端实现细节、SQL 主路径与配置项清单见 [`fastapi-app/README.md`](fastapi-app/README.md)。

## 领域口径

地类采用七大类（`app/utils/units.py` 的 `LAND_TYPES`）：耕地、园地、林地、草地、建设用地、水域、未利用地。
面积默认亩制（1 亩 ≈ 666.67 m²），需求里的「公顷 / 平方米 / 平方公里」在 `parse_intent` 阶段统一换算成亩；
提取时以 `ST_Area(...::geography)` 计算真实地表面积，`ST_SimplifyPreserveTopology` 控制节点量，
碎片由 `EXTRACT_MIN_AREA_MU` 过滤。具体认定规则可写入知识库，由 `retrieve_knowledge` 节点召回后参与结论。
