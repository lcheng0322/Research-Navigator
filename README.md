# Research Navigator

面向科研工作者的全栈文献管理与 AI 辅助分析平台。上传文献构建个人知识库，进行智能问答、文献综述、研究空白分析、表格数据分析和实验设计。

## 架构概览

```
┌─────────────────────┐       ┌──────────────────────────────────────────┐
│   React 前端 (5173)  │─────▶│          FastAPI 后端 (8000)               │
│   TDesign UI         │      │                                            │
│   Zustand 状态管理    │      │  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
└─────────────────────┘      │  │ REST API │  │ WebSocket│  │ /metrics│ │
                              │  └────┬─────┘  └────┬─────┘  └─────────┘ │
                              │       │              │                     │
                              │  ┌────▼──────────────▼──────────────────┐ │
                              │  │           服务层                      │ │
                              │  │  文档处理 │ RAG 问答 │ 综述/分析/实验  │ │
                              │  └────┬───────┬───────┬─────────────────┘ │
                              │       │       │       │                    │
                              │  ┌────▼──┐ ┌──▼───┐ ┌─▼──────────┐       │
                              │  │SQLite │ │Redis │ │ ChromaDB   │       │
                              │  └───────┘ └──┬───┘ └────────────┘       │
                              └───────────────┼──────────────────────────┘
                                              │
                                      ┌───────▼────────┐
                                      │  Celery Worker  │
                                      │  异步任务处理    │
                                      └────────────────┘
```

- **前端** (port 5173) 通过 Axios 调用 REST API，WebSocket 订阅任务进度
- **后端** (port 8000) 协调所有业务逻辑，依赖 SQLite（业务数据）、ChromaDB（向量索引）、Redis（缓存/队列）
- **Celery Worker** 独立进程，执行文档入库、文献综述生成、研究空白分析等耗时任务
- **DeepSeek API** 提供 LLM 推理（reasoner + chat 双模型）

## 功能

### 用户与认证
- 邮箱注册 / 登录，JWT (HS256) 鉴权，7 天有效期
- 登录频率限制（Redis 实现，默认 10 次/分钟/IP）

### 文档管理
- 上传 PDF、DOCX、MD、TXT、CSV、XLS、XLSX
- 基于 SHA-256 内容哈希去重
- 三层元数据提取策略：DOI 正则 → CrossRef API → LLM 推断
- `unstructured` 库解析文档 → 文本分块 → sentence-transformers 嵌入 → ChromaDB 存储
- 三类向量集合：`document_chunks`（段落级）、`document_summaries`（全文摘要）、`document_chapter_summaries`（章节摘要）
- 支持重新处理和删除（级联清理向量数据）

### 智能问答 (RAG)
六阶段管线：

1. **查询分析** — LLM 识别意图（事实核查 / 概念解释 / 文献综述 / 比较 / 其他）、提取实体、改写查询、评估复杂度、分类领域
2. **多集合检索** — 根据意图选择检索策略，从 chunks + summaries + chapter_summaries 中召回候选
3. **去重与过滤** — 按来源聚合，每源最多 3 条，滤除参考文献式内容
4. **Cross-Encoder 重排序** — BGE-Reranker 精排
5. **证据评估** — LLM 评估每条来源的相关性、可信度、时效性、权威性，分析一致性/冲突
6. **推理引擎** — 四步链式推理：综合答案 → 局限性分析 → 替代假设 → 置信度评分

结果可导出 DOCX，含答案、置信度、局限性、替代假设、来源评估和引用上下文。查询历史和结果自动保存，支持 Redis 缓存（TTL 1 小时）。

### 文献综述

三步异步流程：

| 步骤 | API | 输入 | 输出 |
|------|-----|------|------|
| 1. 生成大纲 | `POST .../outline` | `topic` | `outline` + `context_id`（Redis 缓存，1h TTL） |
| 2. 生成综述 | `POST .../from-outline` | `outline` + `context_id` | `task_id`（Celery 异步） |
| 3. 下载 DOCX | `GET .../download/{task_id}` | `task_id` | `.docx` 文件流 |

第 1 步从向量库检索相关文献摘要，LLM 据此生成结构化大纲（标题、引言、若干正文章节、结论）。第 2 步为每个章节逐段生成内容并自动管理引用 `[Source_n]`。第 3 步导出为含标题、章节、参考文献列表的 Word 文档。

### 研究空白分析

启动 Celery 异步任务，对整个知识库运行 BERTopic 主题建模：

- 识别核心研究主题及其关键词
- 检测离群文档（不属于任何主题的文档 → 潜在研究空白）
- 趋势分析（基于出版年份的时间序列）
- LLM 根据离群文档生成研究方向建议
- 结果以 DOCX 导出，含主题表格和离群文档摘要
- 结果缓存到 Redis（TTL 24 小时）

### 表格数据分析

两步流程：

| 步骤 | API | 说明 |
|------|-----|------|
| 1. 初始化 | `POST .../initiate` | 上传 CSV/XLSX → 返回统计摘要 + 相关性矩阵 + `file_id` |
| 2a. 回归 | `POST .../regression` | 用 `file_id` + 变量名执行线性回归或逻辑回归 |
| 2b. 可视化 | `POST .../visualize` | 用 `file_id` + 图表类型生成直方图/散点图/箱线图 |

`file_id` 存储在 Redis 中（TTL 1 小时），关联到服务器端临时文件。

> **注意**：`POST /api/upload/` 也有表格处理能力。传 `analyze_only=true` 可直接对 CSV/XLSX 做即时分析而不入库，结果直接返回（文件用完即删）。

### 实验设计

三步交互流程：

| 步骤 | API | 说明 |
|------|-----|------|
| 1. 创建会话 | `POST /api/experiments` | 输入研究主题、变量、约束 → 检索知识库上下文 → LLM 生成初步假设 → 返回 `session_id` + hypothesis |
| 2. 生成方案 | `POST .../{session_id}/design` | 基于假设 + 上下文生成完整实验方案（标题、方法、材料、分组、步骤、数据分析计划） |
| 3. 优化方案 | `POST .../{session_id}/refine` | Critic agent 审查 → Refiner agent 改进 → 返回优化后的方案 |
| 导出 | `GET .../{session_id}/download` | 导出为 DOCX |

> 会话状态存储在服务器内存中，服务重启后丢失。

### 任务系统与实时推送
- `GET /api/tasks/{task_id}` — HTTP 轮询任务状态
- `WS /api/tasks/ws/{task_id}?token=<jwt>` — WebSocket 推送，每 2 秒更新，任务完成后自动关闭
- 前端 `TaskCenterPage` 展示所有异步任务；`TaskWatcher` 组件可嵌入各页面

## 技术栈

| 层 | 技术 |
|----|------|
| **后端框架** | FastAPI, Uvicorn, Starlette |
| **数据库** | SQLAlchemy ORM + Alembic 迁移 + SQLite |
| **向量存储** | ChromaDB（PersistentClient，三个集合） |
| **任务队列** | Celery + Redis（Broker & Result Backend） |
| **嵌入模型** | `BAAI/bge-large-en-v1.5` (SentenceTransformer) |
| **重排序** | `BAAI/bge-reranker-base` (CrossEncoder) |
| **主题建模** | BERTopic + CountVectorizer |
| **文档解析** | `unstructured` + `langchain-text-splitters` (NLTKTextSplitter) |
| **LLM 调用** | DeepSeek API（兼容 OpenAI SDK），reasoner + chat 双模型 |
| **认证** | python-jose (JWT HS256) + passlib (argon2) |
| **监控** | Prometheus 指标 + 可选 Sentry |
| **前端框架** | React 19, TypeScript, Vite |
| **UI 组件** | TDesign React |
| **可视化** | Plotly.js / react-plotly.js |
| **状态管理** | Zustand |
| **路由** | React Router v7 |

## 目录结构

```
Research-Navigator/
├── backend/
│   ├── api/                     # API 路由层
│   │   ├── auth_routes.py       #   POST /api/token
│   │   ├── user_routes.py       #   POST /api/users/ , GET /api/users/me
│   │   ├── document_routes.py   #   GET/POST/DELETE /api/documents/, /api/upload/
│   │   ├── query_routes.py      #   POST /api/query/, /api/query/history, /api/query/download
│   │   ├── analysis_routes.py   #   综述、空白分析、表格分析、实验设计
│   │   ├── task_routes.py       #   GET /api/tasks/{id}, WS /api/tasks/ws/{id}
│   │   └── health_routes.py    #   GET /api/health
│   ├── core/                    # 基础设施
│   │   ├── config.py            #   Pydantic Settings（从 backend/.env 加载）
│   │   ├── security.py          #   JWT 生成/验证, argon2 密码哈希
│   │   ├── dependencies.py      #   FastAPI 依赖注入（当前用户、数据库会话）
│   │   ├── cache.py             #   Redis 异步客户端
│   │   ├── celery_app.py        #   Celery 实例 + 任务自动发现
│   │   └── logging.py           #   JSON 结构化日志配置
│   ├── database/
│   │   └── session.py           #   SQLAlchemy engine + session factory
│   ├── models/                  # SQLAlchemy ORM 模型
│   │   ├── user.py              #   User
│   │   ├── document.py          #   Document + DocumentMetadata
│   │   └── query_history.py     #   QueryHistory
│   ├── schemas/                 # Pydantic 请求/响应 Schema
│   │   ├── user_schemas.py
│   │   ├── document_schemas.py
│   │   ├── experiment_schemas.py
│   │   └── response_schemas.py
│   ├── services/                # 业务逻辑层
│   │   ├── document_processor.py          # 文档解析、元数据提取、分块
│   │   ├── vector_store_service.py        # ChromaDB CRUD 封装
│   │   ├── llm_service.py                 # DeepSeek LLM 调用（含重试）
│   │   ├── query_analyzer.py              # 查询意图分析
│   │   ├── query_service.py               # 多集合检索 + 重排序
│   │   ├── reranker_service.py            # CrossEncoder 重排序
│   │   ├── evidence_assessor_service.py   # 证据质量与一致性评估
│   │   ├── reasoning_engine_service.py    # 链式推理引擎
│   │   ├── query_export_service.py        # 问答结果 DOCX 导出
│   │   ├── literature_review_service.py   # 文献综述生成
│   │   ├── research_gap_analyzer_service.py # BERTopic 研究空白分析
│   │   ├── tabular_data_service.py        # 表格统计 + 回归 + 可视化
│   │   └── experiment_designer_service.py # 实验设计生成与优化
│   ├── tasks/                   # Celery 异步任务
│   │   ├── ingestion_tasks.py   #   文档入库
│   │   ├── analysis_tasks.py    #   空白分析 / 综述生成
│   │   └── analysis.py          #   （保留文件，含示例任务）
│   ├── alembic/                 # 数据库迁移
│   │   ├── env.py
│   │   └── versions/            #   4 个迁移脚本
│   ├── config/
│   │   └── retrieval_strategies.json  # 意图 → 检索策略映射
│   ├── main.py                  # FastAPI 应用入口
│   ├── worker.py                # Celery Worker 入口
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/               # 11 个页面组件
│   │   ├── components/          # 通用组件（TaskWatcher, StatusBadge, etc.）
│   │   ├── hooks/               # useTaskPolling, useTaskStream
│   │   ├── services/api.ts      # Axios 客户端（baseURL: http://127.0.0.1:8000/api）
│   │   ├── store/               # Zustand stores (auth, app, task)
│   │   └── router/              # 路由配置 + ProtectedRoute 守卫
│   ├── package.json
│   └── vite.config.ts
├── reset_database.py            # 开发用：清空文档表 + 重建 ChromaDB 集合
└── README.md
```

## 快速开始

### 前置条件

| 组件 | 最低版本 | 用途 |
|------|----------|------|
| Python | 3.10+ | 后端运行环境 |
| Node.js | 20+ | 前端构建 |
| Redis | 6+ | 消息队列、缓存、限流 |
| DeepSeek API Key | — | LLM 推理 |

推荐安装（文档解析增强，非必需）：
- **Tesseract OCR** — 扫描版 PDF / 图片 OCR
- **Poppler** — 复杂 PDF 页面渲染
- **LibreOffice** — 复杂 Office 文档兼容

### 1. 准备 Redis

Windows 推荐通过 WSL2：

```bash
sudo apt update && sudo apt install redis-server
sudo service redis-server start
redis-cli ping   # 应返回 PONG
```

### 2. 安装后端

```powershell
cd C:\myproject\Research-Navigator
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

### 3. 配置环境变量

```powershell
Copy-Item backend\.env.example backend\.env
```

编辑 `backend\.env`，至少填写三项：

```env
SECRET_KEY=<运行 python -c "import secrets; print(secrets.token_hex(32))" 生成>
DEEPSEEK_API_KEY=<你的 DeepSeek API Key>
REDIS_URL=redis://localhost:6379/0
```

> `.env` 文件**必须放在 `backend/` 目录下**。完整配置项见 `backend/.env.example`。

### 4. 初始化数据库

```powershell
cd backend
alembic upgrade head
```

开发环境如需重置：

```powershell
python reset_database.py   # 清空文档表 + 重建 ChromaDB 集合
```

### 5. 启动后端 API

```powershell
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

- API 根路径：http://127.0.0.1:8000/
- Swagger 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/health
- Prometheus 指标：http://127.0.0.1:8000/metrics

### 6. 启动 Celery Worker

**另开一个终端**：

```powershell
.\.venv\Scripts\Activate.ps1
celery -A backend.worker worker --loglevel=info --pool=solo
```

> `--pool=solo` 是 Windows 兼容所需。

### 7. 安装并启动前端

**另开一个终端**：

```powershell
cd frontend
npm install
npm run dev
```

前端地址：http://localhost:5173

## API 参考

所有需要认证的接口在请求头携带 `Authorization: Bearer <token>`。

### 认证与用户

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/users/` | 注册（`email` + `password`） |
| `POST` | `/api/token` | 登录，返回 JWT（form: `username`=email, `password`） |
| `GET` | `/api/users/me` | 获取当前用户信息 |

### 文档

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/documents/` | 文档列表（含元数据和状态） |
| `POST` | `/api/upload/` | 上传文件。支持 `analyze_only=true` 对 CSV/XLSX 做即时分析不入库 |
| `GET` | `/api/documents/{id}/metadata` | 获取文档元数据 |
| `GET` | `/api/documents/{id}/content` | 获取向量库中该文档的全部文本块 |
| `POST` | `/api/documents/{id}/reprocess` | 重新处理（清空旧向量 → 重新解析 → 入库） |
| `DELETE` | `/api/documents/{id}` | 删除文档及所有关联向量 |

### 问答

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/query/` | 知识库问答（form: `query`）。结果缓存 1 小时，基于 query+user 的哈希 |
| `GET` | `/api/query/history` | 当前用户的查询历史（按时间倒序，Asia/Shanghai 时区） |
| `DELETE` | `/api/query/history/{id}` | 删除指定历史记录 |
| `POST` | `/api/query/download` | 导出问答结果为 DOCX（body: `query_text` + `result_payload`） |

### 文献综述

三步流程，`context_id` 在 Redis 中缓存 1 小时：

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/generate/literature-review/outline` | 输入 `topic` → 返回 `outline` + `context_id` |
| `POST` | `/api/generate/literature-review/from-outline` | 输入 `outline` + `context_id` → 返回 `task_id` |
| `GET` | `/api/generate/literature-review/download/{task_id}` | 下载综述 DOCX |

### 研究空白分析

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/analyze/research-gaps/` | 启动异步分析 → 返回 `task_id`。结果缓存 24h |
| `GET` | `/api/analyze/research-gaps/download/{task_id}` | 下载分析报告 DOCX |

### 表格数据分析

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/analyze/tabular-data/initiate` | 上传 CSV/XLSX → 返回统计摘要 + `file_id`（Redis 1h） |
| `POST` | `/api/analyze/tabular-data/regression` | `file_id` + `analysis_type`(linear/logistic) + `dependent_var` + `independent_vars` |
| `POST` | `/api/analyze/tabular-data/visualize` | `file_id` + `vis_type`(histogram/scatter/boxplot) + `x_col` [+ `y_col`] |

### 实验设计

会话存储在服务器内存中：

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/experiments` | 创建会话（`research_topic`, `variables`, `constraints`）→ `session_id` + hypothesis |
| `POST` | `/api/experiments/{session_id}/design` | 生成完整实验方案 |
| `POST` | `/api/experiments/{session_id}/refine` | Critic + Refiner 双代理优化方案 |
| `GET` | `/api/experiments/{session_id}/download` | 导出实验方案 DOCX |

### 任务状态

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/tasks/{task_id}` | 轮询任务状态（PENDING/STARTED/SUCCESS/FAILURE） |
| `WS` | `/api/tasks/ws/{task_id}?token=<jwt>` | WebSocket 推送，每 2 秒更新一次 |

## 前端页面

| 路由 | 页面 | 功能 |
|------|------|------|
| `/login` | LoginPage | 登录 |
| `/register` | RegisterPage | 注册 |
| `/dashboard` | DashboardPage | 仪表盘总览 |
| `/documents` | DocumentsPage | 文档上传、列表、元数据查看、删除、重处理 |
| `/query` | QueryPage | 智能问答 + 历史记录 + DOCX 导出 |
| `/literature-review` | LiteratureReviewPage | 三步文献综述 |
| `/gap-analysis` | GapAnalysisPage | 研究空白分析 |
| `/tabular-analysis` | TabularDataAnalysisPage | 表格上传 → 统计 → 回归 → 可视化 |
| `/experiment-design` | ExperimentDesignPage | 实验设计会话 |
| `/tasks` | TaskCenterPage | 所有异步任务状态总览 |
| `/results/:taskId` | ResultViewerPage | 单个任务详情与结果 |

## 常用命令

```powershell
# === 后端 ===

# API 服务
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

# Celery Worker (Windows)
celery -A backend.worker worker --loglevel=info --pool=solo

# 数据库迁移
cd backend && alembic upgrade head

# 重置文档数据（开发环境）
python reset_database.py

# 生成密钥
python -c "import secrets; print(secrets.token_hex(32))"

# === 前端 ===

cd frontend
npm run dev       # 开发服务器
npm run build     # 生产构建
npm run lint      # 代码检查
npm run preview   # 预览生产构建
```

## 排错指南

| 问题 | 检查 |
|------|------|
| 后端无法启动，提示 `SECRET_KEY` 校验失败 | 确认 `backend/.env` 存在且 `SECRET_KEY` 已填写 |
| Redis 连接失败 | `redis-cli ping` 确认 Redis 运行中；检查 `REDIS_URL` |
| LLM 调用失败 | 检查 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、网络可达性 |
| 前端请求后端 404 | 后端默认 `127.0.0.1:8000`；前端 `api.ts` 中 baseURL 是否匹配 |
| 文档处理很慢 | 首次运行需下载 BGE 嵌入/重排模型（~1.3GB）；大型 PDF 解析耗时较长 |
| Celery 任务不执行 | Worker 是否运行中？Windows 是否使用 `--pool=solo`？ |
| 文献综述第二步 404 | `context_id` 已过期（TTL 1h），需重新调用第一步 |
| 表格回归/可视化 404 | `file_id` 已过期，需重新上传 |
| 上传提示重复 | 基于文件内容 SHA-256 去重，确认是否已上传过相同文件 |
| 数据库状态异常 | 开发环境运行 `python reset_database.py` 重置 |

## 数据目录

运行时数据默认位于 `backend/data/`（被 `.gitignore` 排除）：

```
backend/data/
├── research_navigator.db   # SQLite 数据库
├── uploads/                # 上传文件持久化存储
└── chroma_db/              # ChromaDB 向量索引
```
