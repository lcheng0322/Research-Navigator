# Research Navigator

一个面向科研场景的 RAG 系统与分析平台，包含 FastAPI 后端、Celery 异步任务、Chroma 向量库、Redis 缓存与 React 前端（Vite）。本文档提供架构总览与本地/裸机 + Nginx 部署指南。

## 架构总览
- 后端：`FastAPI` + `SQLAlchemy` + `Redis` + `Celery`，按模块划分为认证、用户、文档、查询（RAG）、分析（文献综述、研究空白、表格数据、实验设计）、任务中心。
- 前端：`React` + `tdesign-react` + `Axios`，使用 Zustand 管理认证、全局加载与任务状态，轮询后端任务并展示结果。
- 数据与模型：`ChromaDB` 持久化于 `backend/data/chroma_db`；SQLite 数据库位于 `backend/data/research_navigator.db`；嵌入与重排模型可通过 `core/config.py` 配置。

## 端到端数据流（文本版）

1) 认证与状态
- 用户在前端 `LoginPage` 提交邮箱与密码，调用 `POST /api/token`。
- 后端校验密码（Argon2）并签发 `JWT`，前端保存 `token`（`authStore`）。
- 后续请求通过 Axios 拦截器自动附带 `Authorization: Bearer <token>`；401 自动登出并跳转 `/login`。

2) RAG 查询流水线（`POST /api/query/`）
- 输入：表单字段 `query`，需已登录。
- 缓存：基于 `sha256(user_id:query)` 的 `cache:query:<hash>` 在 Redis 命中则直接返回。
- 查询分析：`services/query_analyzer.py` 生成 `intent/rewritten_query/entities/complexity/domain`。
- 检索与重排：`services/query_service.py` 依策略 `config/retrieval_strategies.json` 从 `vector_store_service` 多集合检索，使用 `reranker_service` 为候选打分并去重。
- 证据评估：`services/evidence_assessor_service.py` 计算一致性/分歧/质量等指标。
- 推理生成：`services/reasoning_engine_service.py` 综合答案、局限分析、替代假设、知识图谱、信心分。
- 结果落库：写入 `models/query_history.QueryHistory` 并 `setex` 回写 Redis。
- 前端展示：`QueryPage` 展示四大块（答案、分析、评估、上下文）与知识图谱，可查看/删除查询历史。

3) 文献综述（异步）
- 生成大纲：`POST /api/generate/literature-review/outline`，返回 `outline` 与 `context_id`，上下文文档写入 Redis。
- 基于大纲生成：`POST /api/generate/literature-review/from-outline` 启动 Celery 任务（`tasks/analysis_tasks.py`），返回 `task_id`。
- 轮询/下载：前端 `useTaskPolling` 轮询 `/api/tasks/{task_id}`；完成后 `GET /api/generate/literature-review/download/{task_id}` 下载 DOCX。

4) 研究空白（异步）
- 启动任务：`POST /api/analyze/research-gaps/`，返回 `task_id`；后台 `research_gap_analyzer_service` 使用 BERTopic 分析主题与离群点。
- 前端轮询并展示主题簇、潜在空白文献与趋势统计。

5) 表格数据分析
- 上传与初步分析：`POST /api/analyze/tabular-data/initiate`（CSV/XLSX），缓存 `file_id` 到 Redis 并返回描述性统计。
- 回归分析：`POST /api/analyze/tabular-data/regression`（线性/逻辑），返回系数与拟合报告。
- 可视化：`POST /api/analyze/tabular-data/visualize`，返回 Plotly 图形数据。

6) 实验设计
- 创建会话：`POST /api/experiments` 返回 `session_id`。
- 生成设计：`POST /api/experiments/{session_id}/design`，可再通过 `POST /api/experiments/{session_id}/refine` 迭代优化。

## 本地开发运行

### 前置依赖
- Python 3.11/3.12（建议 3.11）
- Node.js 18+ 与 npm（或 pnpm/yarn）
- Redis（本机或远程服务）6+
  - Windows 可选：通过 WSL2 安装 `redis-server`，或使用 Memurai/KeyDB 兼容实现

### 后端（Windows 示例）
1. 创建并激活虚拟环境（可复用 `backend/venv`，或新建）
   - 在仓库根目录：
     - `python -m venv .venv`
     - `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`（首次在 PowerShell 使用 venv）
     - `./.venv/Scripts/Activate.ps1`
2. 安装依赖
   - `pip install -r backend/requirements.txt`
3. 配置环境（可选）
   - 编辑 `backend/.env`，按需设置 `DEEPSEEK_API_KEY`、向量模型、`REDIS_URL` 等。
4. 启动 Redis（如未运行）
   - 本机：`redis-server`（Windows 建议通过 WSL2 或使用 Memurai/KeyDB）
5. 启动后端与 Celery（从仓库根目录执行，使用包路径导入）
   - 后端：`uvicorn backend.main:app --reload`
   - 工作进程：`celery -A backend.worker worker --loglevel=info`

> 说明：使用 `backend.main:app`/`backend.worker` 的包路径可确保相对导入与命名空间包正常工作；不建议 `cd backend && uvicorn main:app`。

### 初始化用户
- 创建用户：
  - `POST /api/users/`
  - JSON 示例：`{"email":"test@example.com","password":"your_password"}`
- 登录获取 Token：
  - `POST /api/token`（表单）：`username=<email>&password=<password>`
- 查询当前用户：
  - `GET /api/users/me`（需 `Authorization: Bearer <token>`）

### 前端（开发模式）
1. 安装依赖：在 `frontend` 目录执行 `npm install`
2. 运行开发服务器：`npm run dev`
3. 访问：`http://localhost:5173`

> 开发模式：Vite 已代理到 `http://127.0.0.1:8000`（见 `vite.config.ts`）；Axios `baseURL` 建议使用相对路径 `/api`（由代理转发到后端），与后端 CORS (`http://localhost:5173`) 兼容。生产环境通过 Nginx 统一域名与端口，前端同样以 `/api` 访问。

## Nginx 部署（裸机）

以下示例在 Windows 上使用 Nginx 作为前端静态资源与后端 API 的反向代理，前端与后端在本机运行：

1) 构建前端静态产物
- 在 `frontend` 目录执行：`npm run build`
- 构建输出位于 `frontend/dist`

2) 启动后端（生产模式建议关闭 `--reload`）
- `uvicorn backend.main:app --host 127.0.0.1 --port 8000`

3) Nginx 配置（Windows 路径示例，按你的实际路径调整）：
```nginx
events {}
http {
  upstream backend {
    server 127.0.0.1:8000;
  }

  server {
    listen 80;
    server_name localhost;

    # 前端静态站点
    root  C:/Users/lansh/Desktop/Research Navigator/frontend/dist;
    index index.html;

    # 静态资源直出
    location /assets/ {
      try_files $uri =404;
    }

    # SPA 路由回退
    location / {
      try_files $uri $uri/ /index.html;
    }

    # 后端 API 反向代理
    location /api/ {
      proxy_pass http://backend/;
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;

      # WebSocket 支持（Uvicorn）
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection upgrade;
      proxy_read_timeout 86400;
    }

    # Prometheus 指标（可选）
    location /metrics {
      proxy_pass http://backend/metrics;
    }
  }
}
```

4) CORS 与前端地址对齐
- 若通过 Nginx 统一到 `http://localhost`，建议将后端 CORS `allow_origins` 更新为 `http://localhost`
- 前端 `Axios` 的 `baseURL` 可设为 `/api`，由 Nginx 转发到后端

5) 后端健康检查与监控
- 根路由：`GET /` 返回欢迎信息
- Prometheus 指标：`GET /metrics`

## API 速览
- 认证：`POST /api/token`、`GET /api/users/me`
- RAG 查询与历史：`POST /api/query/`、`GET /api/query/history`、`DELETE /api/query/history/{id}`
- 文献综述：`POST /api/generate/literature-review/outline`、`POST /api/generate/literature-review/from-outline`、`GET /api/generate/literature-review/download/{task_id}`
- 研究空白：`POST /api/analyze/research-gaps/`
- 表格分析：`POST /api/analyze/tabular-data/initiate`、`/regression`、`/visualize`
- 实验设计：`POST /api/experiments`、`POST /api/experiments/{session_id}/design`、`POST /api/experiments/{session_id}/refine`

## 常见问题（FAQ）
- 401 未授权：确认 Token 仍有效；前端会自动登出并跳转登录。
- Redis 连接失败：检查 `REDIS_URL` 配置与服务状态；后端启动日志包含 Redis 探活信息。
- 无检索结果：知识库为空或策略筛选过严；检查 `vector_store_service` 数据与检索策略。
- Docker Compose 启动异常：优先本地开发模式；或按上文建议修正 `worker` 命令与数据卷。

## 说明
- 生产环境务必通过环境变量设置 `SECRET_KEY`，并考虑收紧 `ACCESS_TOKEN_EXPIRE_MINUTES`。
- Prometheus 指标已通过 `prometheus_fastapi_instrumentator` 接入，可按需扩展业务级指标。
 - 本项目已移除 Docker 相关文件；如需容器化，请自行按上述 Nginx 结构与 `uvicorn`/`Celery` 启动命令调整。