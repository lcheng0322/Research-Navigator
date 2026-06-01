# Research Navigator

Research Navigator 是一个面向科研文献管理、检索问答和分析生成的全栈应用。项目后端使用 FastAPI 提供 API，Celery + Redis 执行异步任务，SQLite 保存业务数据，ChromaDB 保存向量索引；前端使用 React、TypeScript、Vite 和 TDesign React 构建。

## 主要功能

- 用户注册、登录和 JWT 鉴权
- 文档上传、去重、解析、元数据提取、向量化入库
- 基于知识库的智能问答、证据评估、引用上下文展示和 DOCX 导出
- 查询历史管理
- 文献综述大纲生成、综述异步生成和 DOCX 导出
- 研究空白分析和 DOCX 导出
- CSV/XLS/XLSX 表格数据分析、回归分析和可视化
- 实验设计生成、优化和 DOCX 导出
- Celery 任务状态轮询与 WebSocket 推送
- `/api/health` 健康检查和 Prometheus 指标

## 技术栈

后端：

- FastAPI / Uvicorn
- SQLAlchemy / Alembic / SQLite
- ChromaDB
- Celery / Redis
- sentence-transformers、BERTopic、LangChain、LangGraph
- DeepSeek 兼容 OpenAI SDK 的 LLM 调用

前端：

- React 19 / TypeScript / Vite
- React Router
- Zustand
- TDesign React
- Plotly

## 目录结构

```text
Research-Navigator/
├── backend/                 # FastAPI 后端、Celery 任务、服务层、数据库模型
│   ├── api/                 # API 路由
│   ├── core/                # 配置、安全、缓存、Celery、日志
│   ├── database/            # SQLAlchemy 会话
│   ├── models/              # ORM 模型
│   ├── services/            # 文档处理、RAG、分析、导出等业务服务
│   ├── tasks/               # Celery 异步任务
│   ├── alembic/             # 数据库迁移
│   ├── main.py              # FastAPI 应用入口
│   └── requirements.txt
├── frontend/                # React 前端
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
├── reset_database.py        # 重置文档表和 ChromaDB 集合
└── README.md
```

## 环境要求

- Python 3.10+
- Node.js 20+ 和 npm
- Redis 6+
- 可访问 DeepSeek API 的网络环境

首次运行会下载嵌入模型和重排模型，默认模型为：

- `BAAI/bge-large-en-v1.5`
- `BAAI/bge-reranker-large`

## 需要自行安装的软件

本仓库不包含运行时软件本体，首次部署前需要在本机或服务器上自行安装以下软件。

必装：

| 软件 | 用途 | Windows 安装建议 |
| --- | --- | --- |
| Python 3.10+ | 运行 FastAPI 后端、Celery Worker 和数据处理脚本 | `winget install Python.Python.3.11` |
| Node.js 20+ | 安装前端依赖并运行 Vite/React | `winget install OpenJS.NodeJS.LTS` |
| Redis 6+ | Celery Broker/Result Backend、缓存、登录限流、任务状态 | 推荐用 Docker 或 WSL2 安装 Redis |
| Git | 克隆仓库、查看变更、提交代码 | `winget install Git.Git` |

Redis 推荐方式二选一：

```powershell
# Docker 方式
docker run --name research-navigator-redis -p 6379:6379 -d redis:7
```

```powershell
# WSL2 Ubuntu 方式
sudo apt update
sudo apt install redis-server
sudo service redis-server start
```

可选但推荐：

| 软件 | 用途 | 说明 |
| --- | --- | --- |
| Docker Desktop | 快速启动 Redis 或未来容器化部署 | 如果不用 Docker，需要自行提供 Redis 服务 |
| Tesseract OCR | 扫描版 PDF 或图片文字识别 | 文档 OCR 场景需要 |
| Poppler | PDF 页面渲染、版面解析辅助工具 | 复杂 PDF 解析场景建议安装 |
| LibreOffice | Office 文档转换和解析辅助 | 处理复杂 DOC/DOCX/PPT/PPTX 时更稳 |
| Microsoft C++ Build Tools | 某些 Python 包需要本地编译时使用 | 如果 `pip install` 出现编译错误再安装 |

如果只开发前端页面，通常只需要 Node.js；如果要完整运行文档入库、RAG 问答和异步分析，需要 Python、Redis、DeepSeek API Key，并保持后端 API 和 Celery Worker 同时运行。

## 后端配置

后端配置由 `backend/core/config.py` 管理，并从 `backend/.env` 读取环境变量。

在 `backend/.env` 中至少配置：

```env
SECRET_KEY=replace-with-a-long-random-secret
DEEPSEEK_API_KEY=replace-with-your-deepseek-api-key
```

可选配置：

```env
REDIS_URL=redis://localhost:6379/0
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_REASONER_MODEL_NAME=deepseek-reasoner
DEEPSEEK_CHAT_MODEL_NAME=deepseek-chat
LOG_LEVEL=INFO
SENTRY_DSN=
```

生成 `SECRET_KEY` 的示例：

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

默认数据目录位于 `backend/data/`：

- SQLite 数据库：`backend/data/research_navigator.db`
- 上传文件：`backend/data/uploads/`
- ChromaDB：`backend/data/chroma_db/`

这些运行期数据已在 `.gitignore` 中排除。

## 安装与启动

### 1. 安装后端依赖

```powershell
cd c:\myproject\Research-Navigator
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

### 2. 启动 Redis

确保 Redis 可通过 `redis://localhost:6379/0` 访问。可以使用本机 Redis、Docker 或已有 Redis 服务。

Docker 示例：

```powershell
docker run --name research-navigator-redis -p 6379:6379 -d redis:7
```

### 3. 初始化数据库

推荐使用 Alembic 执行迁移：

```powershell
cd c:\myproject\Research-Navigator\backend
alembic upgrade head
```

如果只想快速创建表并重置文档索引，可在项目根目录运行：

```powershell
cd c:\myproject\Research-Navigator
python reset_database.py
```

注意：`reset_database.py` 会清空文档相关表并重建 ChromaDB 集合，不适合保留已有文档数据的场景。

### 4. 启动后端 API

在项目根目录运行：

```powershell
cd c:\myproject\Research-Navigator
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

后端地址：

- API 根路径：`http://127.0.0.1:8000/`
- Swagger 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/health`
- 指标：`http://127.0.0.1:8000/metrics`

### 5. 启动 Celery Worker

文档入库、文献综述、研究空白分析等任务依赖 Celery Worker。另开一个终端，在项目根目录运行：

```powershell
cd c:\myproject\Research-Navigator
.\.venv\Scripts\Activate.ps1
celery -A backend.worker worker --loglevel=info
```

Windows 环境下如果 Celery 默认进程池出现兼容问题，可改用：

```powershell
celery -A backend.worker worker --loglevel=info --pool=solo
```

### 6. 安装并启动前端

另开一个终端：

```powershell
cd c:\myproject\Research-Navigator\frontend
npm install
npm run dev
```

前端默认地址：

```text
http://localhost:5173
```

前端 API 客户端默认请求：

```text
http://127.0.0.1:8000/api
```

## 常用开发命令

后端：

```powershell
# 启动 API
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

# 启动 Worker
celery -A backend.worker worker --loglevel=info

# 数据库迁移
cd backend
alembic upgrade head
```

前端：

```powershell
cd frontend
npm run dev
npm run build
npm run lint
npm run preview
```

## 主要 API

认证与用户：

- `POST /api/users/`：注册用户
- `POST /api/token`：登录并获取 Bearer Token
- `GET /api/users/me`：获取当前用户

文档：

- `GET /api/documents/`：文档列表
- `POST /api/upload/`：上传文档或表格
- `GET /api/documents/{document_id}/metadata`：获取元数据
- `GET /api/documents/{document_id}/content`：获取处理后的内容块
- `POST /api/documents/{document_id}/reprocess`：重新处理文档
- `DELETE /api/documents/{document_id}`：删除文档及向量数据

问答：

- `POST /api/query/`：知识库问答
- `GET /api/query/history`：查询历史
- `DELETE /api/query/history/{history_id}`：删除查询历史
- `POST /api/query/download`：导出问答结果为 DOCX

分析生成：

- `POST /api/generate/literature-review/outline`：生成文献综述大纲
- `POST /api/generate/literature-review/from-outline`：根据大纲异步生成综述
- `GET /api/generate/literature-review/download/{task_id}`：下载综述 DOCX
- `POST /api/analyze/research-gaps/`：启动研究空白分析
- `GET /api/analyze/research-gaps/download/{task_id}`：下载研究空白分析 DOCX
- `POST /api/analyze/tabular-data/initiate`：启动表格分析
- `POST /api/analyze/tabular-data/regression`：执行回归分析
- `POST /api/analyze/tabular-data/visualize`：生成可视化
- `POST /api/experiments`：创建实验设计会话
- `POST /api/experiments/{session_id}/design`：生成实验设计
- `POST /api/experiments/{session_id}/refine`：优化实验设计
- `GET /api/experiments/{session_id}/download`：下载实验设计 DOCX

任务：

- `GET /api/tasks/{task_id}`：查询异步任务状态
- `WS /api/tasks/ws/{task_id}?token=<jwt>`：订阅任务状态

## 前端页面

- `/login`：登录
- `/register`：注册
- `/dashboard`：仪表盘
- `/documents`：文档管理
- `/query`：智能问答
- `/literature-review`：文献综述
- `/gap-analysis`：研究空白分析
- `/tabular-analysis`：表格数据分析
- `/experiment-design`：实验设计
- `/tasks`：任务中心
- `/results/:taskId`：任务结果查看

## 排查问题

- `SECRET_KEY` 未配置：后端启动会因 Pydantic 配置校验失败而退出。请在 `backend/.env` 中设置。
- Redis 连接失败：登录限流、缓存、Celery 和任务状态都会受影响。检查 Redis 是否启动，以及 `REDIS_URL` 是否正确。
- LLM 调用失败：确认 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL` 和模型名配置正确。
- 前端无法请求后端：确认后端运行在 `http://127.0.0.1:8000`，前端运行在 `http://localhost:5173` 或 `http://127.0.0.1:5173`。
- 文档处理很慢：首次运行需要下载模型，PDF/OCR/大型文档也会增加处理时间。请保持 Celery Worker 运行。
- 数据库或向量索引状态异常：开发环境可运行 `python reset_database.py` 重置文档表和 ChromaDB 集合。
