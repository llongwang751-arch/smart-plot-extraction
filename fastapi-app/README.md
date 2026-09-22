# 智能地块提取平台 · 后端

FastAPI + LangGraph + LangChain + RAG + PostGIS/pgvector 的地块智能提取服务。
前端在 `../vue`，接口文档启动后访问 `http://localhost:9090/docs`。

## 快速开始

```bash
cd plot_extraction/fastapi-app
python -m venv ../.venv                       # 或指向已有虚拟环境
../.venv/Scripts/pip install -r requirements.txt   # Linux/Mac: source ../.venv/bin/activate && pip install -r requirements.txt
copy .env.example .env                         # 然后按需填写模型 / 底图密钥
../.venv/Scripts/python main.py                # 监听 0.0.0.0:9090
```

首次启动会：建表（`sys_config` / `sys_user` / `kb_document` / `chat_*`）→ 用 `.env` 默认值播种「系统配置」→
探测 PostGIS，可用则建 `plot` / `extract_task` + 空间索引 + `CREATE EXTENSION postgis/vector`，不可用则降级到本地引擎。

默认管理员 `admin / admin123`，第一个注册用户自动成为管理员，之后注册为普通用户。

### 不装 PostgreSQL 也能跑

`POSTGRES_DSN` 连不上时自动切到本地引擎（`.data/gis_local.db` + Shapely 空间计算 + numpy 余弦向量检索），
所有功能与接口契约完全一致，只有 `/api/health` 的 `gis.mode` 从 `postgis` 变成 `local`。
同理 `SYS_DB_URL` 默认 SQLite，换 MySQL 只改这一行（`mysql://user:pwd@host:3306/plot_sys`）。

## 目录

```
main.py                     应用装配：lifespan、CORS、静态托管、全局异常
app/
  config/  env.py schema.py runtime.py    冷启动默认值 → 配置项 schema → 数据库热更新
  models/  sys_tables.py gis_tables.py schemas.py
  db/      sys_db.py base.py local_store.py postgis_store.py gis_store.py
  llm/     provider.py structured.py                OpenAI 兼容协议 + 结构化输出四级降级
  rag/     loaders.py splitter.py vectorstore.py    多编码解析 / 中文分隔符切块 / 双向量后端
  services/ extraction.py seed.py knowledge.py tiles.py
  workflows/ intent.py locate.py graph.py agent.py sink.py
  api/     auth users config plots knowledge extract records maps chat dashboard
data/kb/   示例领域文档（地类认定与面积口径说明、操作手册与业务问答），在知识库页面上传即可
scripts/   api_check.py（43 项接口自检）
```

## 接口

| 前缀 | 能力 |
| :--- | :--- |
| `/api/auth` | 登录、注册、当前用户、改资料、改密码 |
| `/api/users` | 用户管理（仅管理员，含最后一个管理员保护） |
| `/api/config` | `GET /schema` 驱动前端表单、`PUT` 保存（`******` 表示不修改）、`GET /status`、`POST /test`（`llm/embed/sys_db/tiles/gis`） |
| `/api/plots` | 地块 CRUD、`/options` 下拉项、`/geojson` 全量导出、`/sample` 生成示例数据 |
| `/api/extract` | `POST /run`（`mode: smart` 走 LangGraph 五节点，`mode: space` 纯计算）、`/save-plots` 结果入库、`GET /geojson/{task_id}` 下载、`GET /context` 当前范围上下文 |
| `/api/records` | 提取记录列表 / 详情（含 LangGraph 轨迹）/ 另存地块 / 删除 |
| `/api/knowledge` | 文档列表、文本录入、文件上传（txt/md/csv/json/pdf）、删除、`POST /search` 检索测试 |
| `/api/chat` | 会话 CRUD + `POST /ask`（ReAct Agent，返回 `sources` / `calls` / `plots`） |
| `/api/maps` | `/basemaps` 底图清单、`/tile` 服务端代理瓦片、`/check` 连通性与错误码翻译 |
| `/api/dashboard` | 首页统计卡片 |
| `/api/health` | 运行态：gis / vector / llm 三方状态 |

鉴权：`Authorization: Bearer <token>`；`/api/maps/tile?token=` 与 `?url=` 供 `<img>` 直接引用。
登录凭证为 HMAC 签名 token（`APP_SECRET_KEY` 派生，7 天有效），口令 PBKDF2 加盐存储。

## 提取链路（LangGraph 五节点）

```
parse_intent → locate_area → retrieve_knowledge → run_extraction → analyze
   需求理解      范围定位         RAG 知识召回         空间提取          结论归纳
```

`run_extraction` 后接条件边：提取失败直接 `END`，不做无意义分析。
每个节点在 `trace` 里记录 `via`（`llm(json_schema)` / `degrade-1` / `local` / `pgvector` …）与耗时，前端渲染成时间线。

主路径 SQL 用 `ST_Intersection` + `ST_Area(...::geography)` + `ST_CollectionExtract(...,3)` +
`ST_SimplifyPreserveTopology`；库内无命中时按 `extract.grid_size`（默认 300 m，按 cos(纬度) 修正）生成规则格网兜底，
编号 `TMP0001` 起、标记 `origin: candidate`。

## 验证

```bash
PYTHONIOENCODING=utf-8 ../.venv/Scripts/python scripts/api_check.py    # 需先启动后端
```

覆盖鉴权与越权、配置读取与四连通测试、知识库入库与检索、地块 CRUD、智能/纯计算两种提取、记录回看、Agent 问答可追溯性、底图代理与错误码翻译。
Windows 控制台是 GBK，跑脚本前带 `PYTHONIOENCODING=utf-8`；含中文的请求体别用 curl，用该脚本。
