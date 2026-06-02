# 文献综述模块完整实现详解

> 本文档深入解析 Research Navigator 的文献综述生成功能——一个三步异步流程，从用户输入主题到下载带完整引用的 DOCX 文档。

---

## 目录

1. [架构总览](#1-架构总览)
2. [前端交互设计](#2-前端交互设计)
3. [第一步：生成大纲](#3-第一步生成大纲)
4. [第二步：生成完整综述](#4-第二步生成完整综述)
5. [第三步：导出 DOCX](#5-第三步导出-docx)
6. [引用管理系统](#6-引用管理系统)
7. [Redis 上下文缓存](#7-redis-上下文缓存)
8. [完整调用链路图](#8-完整调用链路图)
9. [附录：已知限制与改进方向](#9-附录已知限制与改进方向)

---

## 1. 架构总览

```
用户浏览器
  │
  ├── Step 1: POST /api/generate/literature-review/outline
  │     topic: "Thermochemical treatment of sewage sludge ash"
  │     → 同步返回 outline + context_id
  │
  ├── Step 2: POST /api/generate/literature-review/from-outline
  │     outline + context_id
  │     → 异步返回 task_id (Celery)
  │     → 前端通过 WebSocket/轮询监听进度
  │
  └── Step 3: GET /api/generate/literature-review/download/{task_id}
        → StreamingResponse (DOCX 文件下载)
```

**核心文件映射**：

| 层 | 文件 | 职责 |
|----|------|------|
| API 路由 | [`backend/api/analysis_routes.py`](backend/api/analysis_routes.py) | 三个端点：outline / from-outline / download |
| 业务逻辑 | [`backend/services/literature_review_service.py`](backend/services/literature_review_service.py) | 上下文检索 + 大纲生成 + 逐节写作 + DOCX 导出 |
| 异步任务 | [`backend/tasks/analysis_tasks.py`](backend/tasks/analysis_tasks.py) | Celery 任务封装 |
| 前端页面 | [`frontend/src/pages/LiteratureReviewPage.tsx`](frontend/src/pages/LiteratureReviewPage.tsx) | 三步向导 UI |
| 前端 Hook | [`frontend/src/hooks/useTaskStream.ts`](frontend/src/hooks/useTaskStream.ts) | WebSocket 实时进度推送 |

**进程模型**：

```
FastAPI 进程                 Celery Worker 进程
  │                              │
  ├── Step 1: 同步执行            │
  │   (大纲生成, ~3-5s)          │
  │                              │
  ├── Step 2: 投递任务 ─────────▶ ├── Step 2: 异步执行
  │   (立即返回 task_id)          │   (综述生成, ~30-120s)
  │                              │
  └── Step 3: 同步读取结果 ◀───── ┘
      (DOCX 导出, ~1s)
```

---

## 2. 前端交互设计

**文件**：[`frontend/src/pages/LiteratureReviewPage.tsx`](frontend/src/pages/LiteratureReviewPage.tsx)

前端使用 TDesign 的 `Steps` 组件实现**三步向导**：

```
┌──────────────────────────────────────────────────────────────┐
│  Step 0: Enter Topic        Step 1: Review Outline           │
│  ┌────────────────────┐     ┌──────────────────────────┐     │
│  │ Topic: [________]  │     │ JSON Editor:             │     │
│  │                    │     │ {                        │     │
│  │ [Generate Outline] │     │   "review_title": "...", │     │
│  └────────────────────┘     │   "introduction": "...", │     │
│           │                 │   "body": [...],         │     │
│           ▼                 │   "conclusion": "..."    │     │
│                             │ }                        │     │
│                             │                          │     │
│                             │ [Back]  [Generate Full]  │     │
│                             └──────────────────────────┘     │
│                                        │                     │
│                                        ▼                     │
│                               Step 2: Generate & Download    │
│                               ┌──────────────────────────┐   │
│                               │ Task Status: SUCCESS     │   │
│                               │ ┌────────────────────┐   │   │
│                               │ │ Introduction       │   │   │
│                               │ │ ...section text... │   │   │
│                               │ │ Body Section 1     │   │   │
│                               │ │ ...section text... │   │   │
│                               │ │ Conclusion         │   │   │
│                               │ │ References         │   │   │
│                               │ └────────────────────┘   │   │
│                               │ [Download as DOCX]       │   │
│                               └──────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

**状态管理**：

```typescript
const [currentStep, setCurrentStep] = useState(0);
const [topic, setTopic] = useState('');           // Step 0 输入
const [outline, setOutline] = useState<any>(null); // Step 1 编辑
const [contextId, setContextId] = useState<string | null>(null); // Step 1→2 的桥梁
const [currentTaskId, setCurrentTaskId] = useState<string | null>(null); // Step 2 任务ID
```

**关键交互细节**：

- Step 1 的大纲编辑使用 **JSON Textarea**，允许用户手动修改 LLM 生成的结构后再提交
- Step 2 使用 `useTaskStream` hook（WebSocket）实时更新任务状态
- 下载使用 `file-saver` 库的 `saveAs()`，直接从 blob 响应触发浏览器下载
- 每次点击 "Generate Outline" 会**重置** `outline`、`contextId`、`currentTaskId`（防止跨请求状态污染）

---

## 3. 第一步：生成大纲

**端点**：`POST /api/generate/literature-review/outline`
**文件**：[`backend/api/analysis_routes.py`](backend/api/analysis_routes.py) 第 62–74 行
**服务**：[`backend/services/literature_review_service.py`](backend/services/literature_review_service.py) → `generate_outline()`

### 3.1 请求与响应

```
请求:  POST /api/generate/literature-review/outline
       Content-Type: application/x-www-form-urlencoded
       topic=Thermochemical treatment of sewage sludge ash

响应:  {
         "outline": {
           "review_title": "Thermochemical Treatment of Sewage Sludge Ash: A Comprehensive Review",
           "introduction": "Establish the importance of sewage sludge management...",
           "body": [
             {
               "section_title": "Composition and Properties of Sewage Sludge Ash",
               "description": "Overview of the chemical and physical properties..."
             },
             {
               "section_title": "Thermochemical Treatment Methods",
               "description": "Review of incineration, pyrolysis, gasification..."
             },
             ...
           ],
           "conclusion": "Synthesize findings and identify future research directions..."
         },
         "context_id": "a1b2c3d4-..."
       }
```

### 3.2 处理流程

```
generate_outline(topic)
  │
  ├── 阶段 A: _gather_context(topic)
  │     │
  │     ├── ① 主题扩展 (LLM reasoner)
  │     │     expansion_prompt = f'''
  │     │       Given the research topic "{topic}",
  │     │       generate 3 to 5 diverse and specific questions
  │     │       that a researcher might ask.
  │     │       These questions should cover different facets of the topic.
  │     │     '''
  │     │     sub_queries_str = get_llm_response(prompt, use_reasoner=True)
  │     │     sub_queries = parse_numbered_list(sub_queries_str)
  │     │     queries_to_run = [topic] + sub_queries
  │     │     # 例: ["Thermochemical treatment...",
  │     │     #       "What are the main thermochemical methods...",
  │     │     #       "How does temperature affect...",
  │     │     #       "What are the environmental impacts...",
  │     │     #       "How does sewage sludge ash composition..."]
  │     │
  │     ├── ② 多查询向量检索
  │     │     n_per_query = max(1, max_results // len(queries_to_run))
  │     │     # max_results=50, queries=5 → 每条查询检索 10 条
  │     │
  │     │     for query in queries_to_run:
  │     │         results = vector_store.query(
  │     │             query_text=query,
  │     │             n_results=n_per_query,
  │     │             collection_name="document_summaries"  ← 只查摘要！
  │     │         )
  │     │         # 按内容去重，合并到 all_context_data
  │     │
  │     └── ③ 返回去重后的文档字典
  │           {doc_content: metadata, ...}
  │           # 最多 50 条去重文档
  │
  ├── 阶段 B: 构建提示词并生成大纲
  │     context_summary = "\n".join([
  │         f"- {doc[:200]}..." for doc in list(context_docs.keys())[:10]
  │     ])  # 只用前 10 篇的摘要头 200 字符
  │
  │     prompt = f'''
  │       You are a research strategist.
  │       Based on the following document summaries,
  │       create a structured and logical outline
  │       for a literature review on the topic: "{topic}".
  │
  │       DOCUMENT SUMMARIES:
  │       {context_summary}
  │
  │       Respond with a single, valid JSON object:
  │       {{
  │         "review_title": "...",
  │         "introduction": "...",
  │         "body": [
  │           {{ "section_title": "...", "description": "..." }}
  │         ],
  │         "conclusion": "..."
  │       }}
  │     '''
  │     outline_str = get_llm_response(prompt,
  │                         json_mode=True,      ← 强制 JSON 输出
  │                         use_reasoner=True)   ← 使用推理模型
  │
  └── 阶段 C: Pydantic 校验 + 缓存
        outline = ReviewOutline.model_validate_json(outline_str)
        context_id = uuid4()
        redis.setex(f"context:{context_id}", 3600,
                     json.dumps(context_docs))
        return {"outline": outline.model_dump(), "context_id": context_id}
```

### 3.3 主题扩展策略

**为什么需要主题扩展？**

单一主题查询可能遗漏不同角度的文献。例如用户输入 "sewage sludge ash treatment"，如果只用这一个查询去检索，可能会错过关于 "phosphorus recovery"、"heavy metal immobilization"、"thermal decomposition kinetics" 等子主题的文献。

**扩展示例**：

```
输入: "Thermochemical treatment of sewage sludge ash"

LLM 生成:
  1. "What are the main thermochemical treatment methods for sewage sludge ash?"
  2. "How does incineration temperature affect the properties of sewage sludge ash?"
  3. "What are the environmental impacts of thermochemical treatment of sewage sludge?"
  4. "How can valuable elements be recovered from sewage sludge ash during thermal treatment?"
  5. "What are the recent advancements in pyrolysis and gasification of sewage sludge?"

检索策略:
  原始查询 → 10 条
  5 个子查询 → 各 10 条
  去重后 → ≤ 50 条独特文档摘要
```

### 3.4 Pydantic 数据模型

```python
class OutlineSection(BaseModel):
    section_title: str   # 章节标题
    description: str     # 章节内容描述（一句话）

class ReviewOutline(BaseModel):
    review_title: str                   # 综述总标题
    introduction: str                   # 引言部分的描述
    body: List[OutlineSection]          # 主体章节列表
    conclusion: str                     # 结论部分的描述
```

### 3.5 本次 LLM 调用汇总

| 调用目的 | 模型 | json_mode | use_reasoner |
|----------|------|-----------|-------------|
| 主题扩展（生成子查询） | `deepseek-reasoner` | False | **True** |
| 大纲生成 | `deepseek-reasoner` | **True** | **True** |

> 这一步使用 `deepseek-reasoner` 而非 `deepseek-chat`，因为大纲规划需要**深层次的结构化推理**——它需要理解多篇文献摘要之间的关系，并将其组织成逻辑连贯的章节结构。

---

## 4. 第二步：生成完整综述

**端点**：`POST /api/generate/literature-review/from-outline`
**文件**：[`backend/api/analysis_routes.py`](backend/api/analysis_routes.py) 第 76–89 行
**任务**：[`backend/tasks/analysis_tasks.py`](backend/tasks/analysis_tasks.py) → `generate_review_from_outline_task`
**服务**：[`backend/services/literature_review_service.py`](backend/services/literature_review_service.py) → `generate_review_from_outline()`

### 4.1 API 层

```python
@router.post("/generate/literature-review/from-outline")
async def generate_from_outline_endpoint(
    outline: Dict[str, Any] = Body(...),
    context_id: str = Body(...)
):
    # ① 从 Redis 取回缓存的上下文文档
    cached_context = await redis_client.get(f"context:{context_id}")
    if not cached_context:
        raise HTTPException(status_code=404,
            detail="Context ID not found or expired.")  # ← TTL 1h

    context_docs = json.loads(cached_context)

    # ② 投递 Celery 异步任务
    task = generate_review_from_outline_task.delay(outline, context_docs)
    return {
        "task_id": task.id,
        "status": "Accepted",
        "message": "Literature review generation task has been started."
    }
```

**为什么这一步是异步的？**

生成完整综述需要为每个章节（Introduction + N×body + Conclusion）分别调用 LLM。以 6 个章节为例，**至少 6 次 LLM 调用**，耗时 30-120 秒。HTTP 请求不宜同步等待这么长时间。

### 4.2 Celery 任务层

```python
@celery_app.task(name="tasks.generate_review_from_outline")
def generate_review_from_outline_task(outline: dict, context_docs: dict):
    review = literature_review_service.generate_review_from_outline(
        outline=outline,
        context_docs=context_docs
    )
    if review.get("error"):
        raise Exception(f"Failed: {review['error']}")
    return review  # 存入 Redis Result Backend
```

### 4.3 核心业务逻辑：`generate_review_from_outline()`

```
generate_review_from_outline(outline, context_docs)
  │
  ├── 阶段 A: 大纲校验
  │     validated_outline = ReviewOutline.model_validate(outline)
  │     # 确保前端可能修改过的 outline 仍然结构合法
  │
  ├── 阶段 B: 构建引用系统
  │     source_map: Dict[str, Dict] = {}
  │     doc_to_citation: Dict[str, str] = {}
  │
  │     for i, (doc_content, metadata) in enumerate(context_docs.items(), 1):
  │         tag = f"Source_{i}"
  │         source_map[tag] = metadata          # Source_1 → {authors, year, ...}
  │         doc_to_citation[doc_content] = tag  # "摘要文本..." → "Source_1"
  │
  ├── 阶段 C: 构建全文上下文
  │     context_str = "\n\n---\n\n".join([
  │         f"Context from [{tag}]:\n{doc_text}"
  │         for doc_text, tag in doc_to_citation.items()
  │     ])
  │     # LLM 可以看到所有文档摘要 + 引用标签
  │
  ├── 阶段 D: 逐节生成内容（串行循环）
  │     sections = [Introduction] + body + [Conclusion]
  │     generated_content = {}
  │
  │     for section in sections:
  │         section_prompt = f'''
  │           You are a research writer.
  │           Write the "{section_title}" section of a literature review
  │           on "{review_title}".
  │
  │           Base your writing *ONLY* on the provided CONTEXT.
  │           Cite sources using their tags (e.g., [Source_1])
  │           at the end of each sentence where information is used.
  │           Focus only on writing the content for this specific section.
  │           Do not write any other sections.
  │
  │           CONTEXT:
  │           {context_str}
  │
  │           Now, write the "{section_title}" section:
  │         '''
  │         section_content = get_llm_response(
  │             section_prompt,
  │             use_reasoner=True    ← 每个章节都用推理模型
  │         )
  │         generated_content[section_title] = section_content.strip()
  │
  └── 阶段 E: 动态构建参考文献列表
        # 扫描所有生成内容中的 [Source_N] 引用
        all_text = " ".join(generated_content.values())
        used_tags = set(re.findall(r'\[(Source_\d+)\]', all_text))
        # 只收录实际被引用的来源

        references = {}
        for tag in sorted(used_tags):
            meta = source_map[tag]
            references[tag] = _format_apa_citation(meta, tag)
            # "Smith et al. (2023). Title of the paper. *Journal Name*."

        return {
            "title": review_title,
            "content": generated_content,
            "references": references
        }
```

### 4.4 逐节生成的设计考量

**为什么是串行而非并行？**

```
串行 (当前实现)                  并行 (备选方案)
  时间: N × T                     时间: T
  优点: 简单可靠                   优点: 快 N 倍
  缺点: 慢                        缺点: 各节可能重复内容
       但每节独立，不互相干扰             引用格式不一致
                                      上下文窗口压力大

选择串行的原因: 每节的 LLM 调用使用完全相同的 context_str，
虽然串行执行慢，但各节在独立上下文中生成，质量更可控。
如果并行生成，总 token 消耗相同但需要管理并发 LLM 连接。
```

### 4.5 APA 引用格式化

```python
def _format_apa_citation(self, metadata, source_file):
    # 多作者处理: 只取第一作者 + "et al."
    authors = metadata.get('authors', 'N/A')
    if ';' in authors:
        authors = authors.split('; ')[0] + " et al."

    year = metadata.get('publication_year', 'n.d.')       # "no date"
    title = metadata.get('title', source_file)
    journal = metadata.get('journal', 'Source not specified')

    return f"{authors} ({year}). {title}. *{journal}*."
    # 例: "Smith et al. (2023). Thermochemical treatment of sewage sludge ash. *Waste Management*."
```

> 注意：这是简化的 APA 格式，斜体用 `*...*` 标记（Markdown 风格）。DOCX 导出时直接用纯文本渲染，实际没有斜体效果。

### 4.6 本次 LLM 调用汇总

| 调用目的 | 次数 | 模型 | use_reasoner |
|----------|------|------|-------------|
| 逐节内容生成 | N+2 次（Introduction + N×body + Conclusion） | `deepseek-reasoner` | **True** |

> 以 4 个正文章节为例，这一步共 **6 次 LLM 调用**。全部使用 reasoner 模型，确保学术写作的深度和质量。

---

## 5. 第三步：导出 DOCX

**端点**：`GET /api/generate/literature-review/download/{task_id}`
**文件**：[`backend/api/analysis_routes.py`](backend/api/analysis_routes.py) 第 91–106 行
**方法**：`LiteratureReviewService.export_review_to_docx()`

### 5.1 API 层

```python
@router.get("/generate/literature-review/download/{task_id}")
async def download_review_docx(task_id: str):
    task_result = AsyncResult(task_id)

    # 状态检查
    if not task_result.ready():
        raise HTTPException(404, "Task not found or not completed.")
    if task_result.failed():
        raise HTTPException(500, "Task failed to generate the review.")

    review_data = task_result.result
    doc = literature_review_service.export_review_to_docx(review_data)

    return StreamingResponse(
        io.BytesIO(doc_bytes),
        media_type='application/vnd.openxmlformats-officedocument...',
        headers={'Content-Disposition':
                 f'attachment; filename=literature_review_{task_id}.docx'}
    )
```

### 5.2 DOCX 生成结构

```
┌─────────────────────────────────────────────┐
│  Level 0 Heading                            │
│  "Thermochemical Treatment of Sewage..."     │
├─────────────────────────────────────────────┤
│  Level 1: Introduction                      │
│  Paragraph text...                          │
├─────────────────────────────────────────────┤
│  Level 1: Composition and Properties of...  │
│  Paragraph text...                          │
├─────────────────────────────────────────────┤
│  Level 1: Thermochemical Treatment Methods  │
│  Paragraph text...                          │
├─────────────────────────────────────────────┤
│  ... (更多 body 章节)                        │
├─────────────────────────────────────────────┤
│  Level 1: Conclusion                        │
│  Paragraph text...                          │
├─────────────────────────────────────────────┤
│  Level 1: References                        │
│  1. Smith et al. (2023). Title. *Journal*.  │
│  2. Jones et al. (2022). Title. *Journal*.  │
│  ...                                        │
└─────────────────────────────────────────────┘
```

### 5.3 引用重新编号

LLM 在第二步中生成的正文内引用使用 `[Source_N]` 格式。导出 DOCX 时，这些标签需要重新编号为学术论文中常见的 `[1]`, `[2]` 格式：

```python
# 重新编号映射
final_ref_map = {
    "Source_1": "[1]",
    "Source_3": "[2]",   # ← Source_2 可能未被引用，被跳过
    "Source_5": "[3]",
    ...
}

# 正文中的引用替换 (当前实现)
for section_title, section_text in content.items():
    for tag, num_ref in final_ref_map.items():
        content[section_title] = section_text.replace(
            f'[{tag}]',
            f' {num_ref}'
        )
```

**⚠️ 代码中的已知限制**：

```python
# 第 208-214 行的注释明确指出:
for p in doc.paragraphs:
    for tag, num_ref in final_ref_map.items():
        if f'[{tag}]' in p.text:
            # This is a simplification; robust replacement is complex.
            # A better approach would be to rebuild the document.
            pass  # Placeholder for more complex replacement logic
```

这里的 `pass` 意味着**段落级别的引用替换实际上未生效**。当前的替换只在 `content` 字典（内存中的字符串）上生效，但 `add_paragraph()` 之后新增的段落文本不会被回溯修改。这是一个待修复的 bug——正确做法应该是在 `add_paragraph()` 之前完成替换。

---

## 6. 引用管理系统

综述模块设计了一个**端到端的引用管理流程**：

```
Step 1: context_docs = {摘要文本: metadata}
              │
              ▼
Step 2: source_map = {                    doc_to_citation = {
          "Source_1": {authors, year,...},   "摘要文本1": "Source_1",
          "Source_2": {authors, year,...},   "摘要文本2": "Source_2",
          ...                              }
        }                                    │
              │                              ▼
              │                    context_str 中的标签
              │                    "Context from [Source_1]:\n摘要1"
              │                              │
              ▼                              ▼
        LLM 逐节生成，引用 [Source_1]
              │
              ▼
        used_tags = regex 扫描所有正文
        只收录实际被引用的来源
              │
              ▼
        references = _format_apa_citation(source_map[tag])
              │
              ▼
Step 3: [Source_N] → [1], [2], ... 重新编号
        同时出现在正文内联引用和文末参考文献列表中
```

**引用过滤**：只有实际被 LLM 引用的来源才会出现在参考文献列表中，未被引用的来源被丢弃。这是通过正则扫描所有生成内容来实现的：

```python
all_text = " ".join(generated_content.values())
used_tags = set(re.findall(r'\[(Source_\d+)\]', all_text))
```

---

## 7. Redis 上下文缓存

综述模块的两步之间通过 **Redis** 传递大量上下文数据：

```
Step 1: outline 端点
  │
  ├── context_id = uuid4()
  ├── redis.setex(
  │     f"context:{context_id}",
  │     3600,                           # 1 小时 TTL
  │     json.dumps(context_docs)        # 序列化 {摘要文本: metadata} 字典
  │   )
  └── return { outline, context_id }

Step 2: from-outline 端点
  │
  ├── cached = redis.get(f"context:{context_id}")
  ├── if not cached: → HTTP 404 "Context ID not found or expired."
  └── context_docs = json.loads(cached)
      → 投递 Celery 任务
```

**为什么用 Redis 而不是直接传参？**

| 方式 | 问题 |
|------|------|
| HTTP body 传 context_docs | 50 条摘要 + metadata 的 JSON 可能有 **数百 KB**，放在请求体中不现实 |
| 数据库存储 | 需要额外的表设计和清理逻辑 |
| Redis 缓存 | 天然 TTL 自动清理，读写都在毫秒级，无需维护额外表 |

**TTL 风险**：用户在 Step 1 拿到 `context_id` 后，如果超过 1 小时才执行 Step 2，`context_id` 将过期失效，需要重新执行 Step 1。

---

## 8. 完整调用链路图

```
用户输入 Topic
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ Step 1: POST /api/generate/literature-review/outline        │
│                                          [analysis_routes.py:62]
│                                                              │
│ literature_review_service.generate_outline(topic)            │
│                                          [literature_review_service.py:62]
│   │                                                          │
│   ├── _gather_context(topic, max_results=50)                │
│   │   │                                                     │
│   │   ├── ① LLM (reasoner) 主题扩展:                        │
│   │   │   topic → 3-5 个子查询                              │
│   │   │                                                     │
│   │   ├── ② 多查询检索:                                     │
│   │   │   for each query:                                   │
│   │   │     vector_store.query(                             │
│   │   │       collection="document_summaries",              │
│   │   │       n_results=n_per_query                         │
│   │   │     )                                               │
│   │   │   → 内容去重                                        │
│   │   │                                                     │
│   │   └── ③ return {doc_text: metadata, ...}                │
│   │                                                          │
│   ├── ④ LLM (reasoner, json_mode) 生成大纲:                  │
│   │   输入: topic + 前10篇摘要                               │
│   │   输出: ReviewOutline (JSON)                             │
│   │                                                          │
│   └── ⑤ Pydantic 校验 ReviewOutline                          │
│                                                              │
│   ├── context_id = uuid4()                                  │
│   ├── redis.setex(f"context:{context_id}", 3600,            │
│   │                json.dumps(context_docs))                 │
│   └── return { outline, context_id }                        │
└──────────────────────────────────────────────────────────────┘
    │
    │ 用户可编辑 outline JSON
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ Step 2: POST /api/generate/literature-review/from-outline   │
│                                          [analysis_routes.py:76]
│                                                              │
│   ├── redis.get(f"context:{context_id}")                    │
│   │   → null? HTTP 404                                       │
│   │                                                          │
│   ├── task = generate_review_from_outline_task               │
│   │           .delay(outline, context_docs)                  │
│   └── return { task_id, status: "Accepted" }                │
│                                                              │
│   ─ ─ ─ ─ ─ (Celery Worker 异步执行) ─ ─ ─ ─ ─              │
│                                                              │
│   generate_review_from_outline_task()                        │
│                          [analysis_tasks.py:35]              │
│     │                                                        │
│     └── literature_review_service                            │
│           .generate_review_from_outline()                    │
│                          [literature_review_service.py:114]  │
│         │                                                    │
│         ├── ① ReviewOutline.model_validate(outline)          │
│         │                                                    │
│         ├── ② 构建引用系统:                                   │
│         │    source_map:    Source_1 → {metadata}            │
│         │    doc_to_citation: doc_text → "Source_1"          │
│         │                                                    │
│         ├── ③ 构建全文上下文:                                 │
│         │    context_str = "Context from [Source_1]:\n..."   │
│         │                                                    │
│         ├── ④ 逐节生成 (Introduction → body → Conclusion):   │
│         │    for each section:                               │
│         │      section_content = get_llm_response(           │
│         │        section_prompt,                             │
│         │        use_reasoner=True                           │
│         │      )                                             │
│         │    → generated_content: Dict[str, str]             │
│         │                                                    │
│         ├── ⑤ 扫描引用标签:                                   │
│         │    used_tags = re.findall(r'\[(Source_\d+)\]')     │
│         │                                                    │
│         ├── ⑥ 构建参考文献:                                   │
│         │    references = {tag: _format_apa_citation(meta)}  │
│         │    (只包含实际被引用的来源)                          │
│         │                                                    │
│         └── return { title, content, references }            │
│                                                              │
│   → Redis Result Backend 存储任务结果                         │
└──────────────────────────────────────────────────────────────┘
    │
    │ 前端通过 WebSocket/轮询等待任务完成
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ Step 3: GET /api/generate/literature-review/download/{id}   │
│                                          [analysis_routes.py:91]
│                                                              │
│   ├── AsyncResult(task_id).ready()? → 否: HTTP 404           │
│   ├── AsyncResult(task_id).failed()? → 是: HTTP 500           │
│   │                                                          │
│   └── literature_review_service.export_review_to_docx()      │
│                          [literature_review_service.py:169]  │
│         │                                                    │
│         ├── ① Document() → 创建 Word 文档                     │
│         ├── ② add_heading → 综述标题                          │
│         ├── ③ add_paragraph → Introduction                    │
│         ├── ④ add_paragraph → Body 各章节                     │
│         ├── ⑤ add_paragraph → Conclusion                      │
│         ├── ⑥ 引用重新编号: [Source_N] → [1], [2], ...       │
│         ├── ⑦ add_paragraph → References (编号列表)           │
│         └── ⑧ return Document 对象                            │
│                                                              │
│   → StreamingResponse(.docx)                                 │
└──────────────────────────────────────────────────────────────┘
```

### 8.1 LLM 调用次数统计

| 步骤 | 调用目的 | 次数 | 模型 | json_mode |
|------|---------|------|------|-----------|
| Step 1 | 主题扩展 | 1 | `deepseek-reasoner` | False |
| Step 1 | 大纲生成 | 1 | `deepseek-reasoner` | **True** |
| Step 2 | 逐节内容生成 | N+2 | `deepseek-reasoner` | False |
| **总计** | | **N+4** | — | — |

> 以 4 个正文章节为例，共 **8 次 LLM 调用**，全部使用 reasoner 模型。

---

## 9. 附录：已知限制与改进方向

### 9.1 DOCX 引用替换不完整

**位置**：`export_review_to_docx()` 第 208-214 行

**问题**：`for p in doc.paragraphs` 循环中的引用替换逻辑是空操作（`pass`）。当前替换只在内存中的 `content` 字典上生效，但 `add_paragraph()` 已将文本写入 `Document` 对象——这两个数据源不同步。

**建议修复**：在 `add_paragraph()` 之前完成 `[Source_N]` → `[1]` 的替换：

```python
# 应该在 add_paragraph 之前替换
for section_title, section_text in content.items():
    for tag, num_ref in final_ref_map.items():
        section_text = section_text.replace(f'[{tag}]', f' {num_ref}')
    content[section_title] = section_text
    doc.add_paragraph(section_text)  # 此时文本已包含 [1] 格式引用
```

### 9.2 逐节生成可能导致内容重复

**问题**：每节独立调用 LLM，使用完全相同的 `context_str`。LLM 可能在 Introduction 和第一个 Body 章节中重复讨论相同的背景信息。

**改进方向**：
- 在每节的 prompt 中加入已生成章节的摘要，告诉 LLM "前面已经讨论了 X，本章节应聚焦于 Y"
- 或者在全部生成完成后，增加一个"去重审查"步骤

### 9.3 上下文窗口限制

**问题**：`context_str` 包含最多 50 条文档摘要，每条可能有数百字。全部传入每个章节的 LLM 调用中——当文档数量多时，可能超出 LLM 的上下文窗口。

**改进方向**：
- 根据章节主题动态筛选相关文档（而非传入全部 50 条）
- 在 prompt 中明确告知 LLM 优先使用与当前章节相关的来源

### 9.4 APA 格式简化

**问题**：`_format_apa_citation()` 只处理简单情况（取第一作者 + et al.），不处理：
- 两位作者（应使用 "&" 连接）
- 无作者的情况
- DOI 链接
- 斜体/缩进等排版格式

### 9.5 大纲编辑无校验反馈

**问题**：前端 Step 1→2 之间，用户可以在 JSON Textarea 中自由编辑 outline。如果用户删除了必需字段或破坏了 JSON 结构，只有在 Step 2 提交后才会收到错误。前端没有提供实时的 JSON Schema 校验。
