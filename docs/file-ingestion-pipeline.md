# 文件上传至入库完整流水线详解

> 本文档详细解析 Research Navigator 中文件从用户上传到最终存入知识库的完整流程，涵盖 HTTP API、Celery 任务、文档处理引擎、元数据提取、向量化存储五大环节。

---

## 目录

1. [架构总览](#1-架构总览)
2. [第零层：基础设施准备](#2-第零层基础设施准备)
3. [第一层：HTTP API — 文件接收与路由](#3-第一层http-api--文件接收与路由)
4. [第二层：Celery 任务调度](#4-第二层celery-任务调度)
5. [第三层：文档处理引擎](#5-第三层文档处理引擎)
   - [5.1 创建数据库记录](#51-创建数据库记录)
   - [5.2 文件解析（Partition）](#52-文件解析partition)
   - [5.3 三层元数据提取](#53-三层元数据提取)
   - [5.4 内容处理分叉](#54-内容处理分叉)
   - [5.5 状态终结](#55-状态终结)
6. [第四层：向量化入库](#6-第四层向量化入库)
7. [错误处理与容错机制](#7-错误处理与容错机制)
8. [重新处理流程](#8-重新处理流程)
9. [删除流程](#9-删除流程)
10. [数据模型](#10-数据模型)
11. [完整调用链路图](#11-完整调用链路图)

---

## 1. 架构总览

整个入库流水线横跨 **4 个进程** 和 **3 个存储系统**：

```
用户浏览器
  │  POST /api/upload/ (multipart/form-data)
  ▼
FastAPI (端口 8000)
  │  ① 计算 SHA-256 → 查重
  │  ② 保存文件到 disk
  │  ③ 投递 Celery 任务 → 立即返回 task_id
  ▼
Redis (消息队列)
  │  任务排队，等待 Worker 拉取
  ▼
Celery Worker (独立进程)
  │  ④ 拉取任务
  │  ⑤ process_document() 主处理流程
  │  ⑥ 写入数据库 + 向量库
  ▼
┌──────────────┬──────────────────┐
│   SQLite     │    ChromaDB      │
│  Document    │  document_chunks │
│  Document    │  document_       │
│  Metadata    │  summaries       │
│              │  document_chapter│
│              │  _summaries      │
└──────────────┴──────────────────┘
```

**文件流向**：`浏览器 → FastAPI 内存 → 磁盘(backend/data/uploads/) → unstructured 解析 → 内存(处理) → SQLite + ChromaDB(持久化)`

---

## 2. 第零层：基础设施准备

### 2.1 目录初始化

```python
# backend/core/config.py — 模块导入时自动执行

def setup_directories():
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)       # backend/data/uploads/
    settings.CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True) # backend/data/chroma_db/
    settings.DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True) # backend/data/
```

三个关键路径在 `core/config.py` 导入时自动创建，无需手动干预。

### 2.2 ChromaDB 集合初始化

```python
# backend/services/vector_store_service.py — VectorStoreService.__init__()

self.collections = {
    "document_chunks":            self.db_client.get_or_create_collection(name="document_chunks"),
    "document_summaries":         self.db_client.get_or_create_collection(name="document_summaries"),
    "document_chapter_summaries": self.db_client.get_or_create_collection(name="document_chapter_summaries")
}
```

| 集合名称 | 存储内容 | 粒度 |
|----------|---------|------|
| `document_chunks` | 文档段落文本块 | 段落级（~3000 字符/块） |
| `document_summaries` | 全文摘要 | 文档级（1条/文档） |
| `document_chapter_summaries` | 章节摘要 | 章节级（N条/文档） |

### 2.3 模型加载

VectorStoreService 初始化时加载两个模型（均从本地缓存优先）：

```
BAAI/bge-large-en-v1.5   → SentenceTransformer → 文本嵌入（~1.3GB）
BAAI/bge-reranker-base   → CrossEncoder        → 检索重排序（按需加载于 RerankerService）
```

### 2.4 NLTK 数据

```python
# backend/services/document_processor.py — 模块导入时自动下载

nltk.download('punkt_tab', quiet=True)
nltk.download('punkt', quiet=True)
```

---

## 3. 第一层：HTTP API — 文件接收与路由

**入口**：[`backend/api/document_routes.py`](backend/api/document_routes.py) → `POST /api/upload/`

### 3.1 完整处理流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                    POST /api/upload/                                │
│                                                                     │
│  入参: file (UploadFile) + analyze_only (bool, 默认 False)          │
│  鉴权: JWT Bearer Token (via get_current_active_user 依赖注入)       │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌──────────────────────────────┐
              │ ① 读取文件内容到内存           │
              │   file_content = await        │
              │   file.read()                 │
              └──────────────────────────────┘
                              │
                              ▼
              ┌──────────────────────────────┐
              │ ② SHA-256 哈希去重            │
              │   file_hash = hashlib         │
              │   .sha256(file_content)       │
              │   .hexdigest()                │
              │                              │
              │   查询: Document.filter(      │
              │     Document.file_hash        │
              │     == file_hash)             │
              │   → 找到? HTTP 409 冲突       │
              └──────────────────────────────┘
                              │ (未重复)
                              ▼
              ┌──────────────────────────────┐
              │ ③ 持久化文件到磁盘             │
              │   file_path =                 │
              │   UPLOAD_DIR / file.filename  │
              │                              │
              │   with file_path.open("wb")   │
              │     as buffer:                │
              │     buffer.write(file_content)│
              └──────────────────────────────┘
                              │
                              ▼
                   ┌─────────────────┐
                   │ file_type 判断   │
                   └─────────────────┘
                   /                  \
           tabular +                 其他类型 /
       analyze_only=true              默认行为
                 /                        \
                ▼                          ▼
    ┌──────────────────┐      ┌──────────────────────────┐
    │ 即时分析分支       │      │ 知识库入库分支             │
    │                   │      │                          │
    │ tabular_data_     │      │ ingest_document_task     │
    │ service.          │      │ .delay(                  │
    │ get_full_analysis │      │   str(file_path),        │
    │ (file_path)       │      │   file_hash,             │
    │                   │      │   file_size              │
    │ 直接返回 JSON      │      │ )                        │
    │ 分析结果           │      │                          │
    │                   │      │ return { task_id,         │
    │ finally: 删除文件  │      │   status: "Accepted" }   │
    └──────────────────┘      └──────────────────────────┘
```

### 3.2 关键细节

**去重策略**：基于 **文件内容的 SHA-256 哈希**，而非文件名。这意味着：
- 即使文件被重命名，内容相同的文件会被识别为重复
- `file_hash` 列在数据库中有唯一索引，提供数据库级别的保证

**两分支行为差异**：

| 维度 | 入库分支 | 分析分支 |
|------|---------|---------|
| 触发条件 | 所有文件类型 | CSV/XLSX + `analyze_only=true` |
| 文件保留 | ✅ 持久化 | ❌ `finally` 块自动删除 |
| 是否入向量库 | ✅ | ❌ |
| 是否创建 Document 记录 | ✅ | ❌ |
| 返回方式 | 异步（task_id） | 同步（直接返回 JSON） |

**协议设计考量**：API 层只做「轻量」工作（读文件、算哈希、存磁盘、投递任务），将「重量」的解析与嵌入工作异步化。这使得 HTTP 响应时间 < 1 秒，用户体验流畅。

---

## 4. 第二层：Celery 任务调度

**入口**：[`backend/tasks/ingestion_tasks.py`](backend/tasks/ingestion_tasks.py) → `ingest_document_task`

### 4.1 Celery 配置

```python
# backend/core/celery_app.py

celery_app = Celery(
    "research_navigator",
    broker=settings.REDIS_URL,    # Redis 作为消息队列
    backend=settings.REDIS_URL,   # Redis 作为结果后端
    include=_task_modules,        # 自动发现 backend/tasks/ 下所有模块
)
```

关键配置：
- **Broker**：Redis，存储待执行的任务消息
- **Result Backend**：Redis，存储任务执行结果
- **自动发现**：`find_task_modules()` 扫描 `backend/tasks/` 目录，无需手动注册新任务
- **Windows 兼容**：启动 Worker 时必须使用 `--pool=solo`（Windows 不支持 fork）

### 4.2 任务执行流程

```python
@celery_app.task(name="tasks.ingest_document")
def ingest_document_task(file_path: str, file_hash: str, file_size: int):
    db = SessionLocal()              # ① 独立数据库会话
    try:
        # ② 调用核心处理函数
        document_id, chunks, full_summary, chapter_summaries = \
            document_processor.process_document(db, path_obj, file_size, file_hash)

        # ③ 向量化入库
        if chunks:
            vector_store_service.add_chunks(chunks)

        summaries = []
        if full_summary:
            summaries.append(full_summary)
        if chapter_summaries:
            summaries.extend(chapter_summaries)
        if summaries:
            vector_store_service.add_summaries(summaries)

        return {
            "status": "success",
            "document_id": document_id,
            "chunks_count": len(chunks),
            "summaries_count": len(summaries),
        }
    except Exception:
        logger.error(...)
        raise          # Celery 自动将任务标记为 FAILURE
    finally:
        db.close()     # ④ 确保数据库连接关闭
```

**设计要点**：

1. **独立 DB 会话**：Celery Worker 运行在独立进程中，不能共享 FastAPI 的依赖注入会话。使用 `SessionLocal()` 手动创建和关闭。
2. **异常传播**：任务中的未捕获异常会被 Celery 捕获并标记任务状态为 `FAILURE`，前端可通过 `GET /api/tasks/{task_id}` 或 WebSocket 获知。
3. **任务结果**：return 的字典被序列化存储到 Redis Result Backend，HTTP 轮询时可以获取。

---

## 5. 第三层：文档处理引擎

**入口**：[`backend/services/document_processor.py`](backend/services/document_processor.py) → `process_document()`

这是整个流水线的核心，包含 6 个子步骤。

### 5.1 创建数据库记录

```python
db_document = Document(
    file_name=file_name,
    file_type=file_type,
    file_path=str(file_path.resolve()),
    file_hash=file_hash,
    file_size=file_size,
    status="processing"       # ← 初始状态
)
db.add(db_document)
db.commit()
db.refresh(db_document)
document_id = db_document.id
```

**状态机**：

```
processing ──┬──→ completed
             │
             └──→ failed (附带 error_message 元数据)
```

`status` 字段在数据库中有索引，前端可按状态筛选文档列表。

### 5.2 文件解析（Partition）

```python
from unstructured.partition.auto import partition

elements = partition(
    filename=str(file_path),
    strategy="hi_res",             # 高精度模式（需要 PDF → 图片 → OCR）
    languages=['eng'],
    include_page_breaks=True,       # 保留分页信息
    pdf_image_output_dir_path=temp_dir,  # 临时图片输出目录
    infer_table_structure=True      # 自动识别表格结构
)
```

**`unstructured` 库** 是一个文档解析框架，`partition()` 函数自动检测文件类型并抽取结构化元素。返回 `List[Element]`，每个元素包含：

| 属性 | 说明 |
|------|------|
| `element.text` | 文本内容 |
| `element.metadata.page_number` | 页码 |
| `element.category` | 元素类别（Title / NarrativeText / Table / Header / Footer 等） |
| `element.metadata.text_as_html` | 表格专用：HTML 格式的表格结构 |

**支持的文件格式**：

| 格式 | 处理方式 |
|------|---------|
| PDF | `hi_res` 策略：渲染为图片 → OCR 识别文本 + 表格检测 |
| DOCX | 直接解析 XML 结构 |
| MD / TXT | 按段落分割 |
| CSV / XLSX | 使用 pandas 读取（不走 unstructured） |

**临时目录**：`pdf_image_output_dir_path` 指向 `tempfile.TemporaryDirectory()`，在 `with` 块退出后自动清理。

### 5.3 三层元数据提取

```
Tier 1: DOI 正则扫描
  ↓ (失败)
Tier 2: CrossRef API 查询
  ↓ (失败)
Tier 3: LLM 推断
```

#### Tier 1：DOI 正则扫描（`_extract_and_store_metadata`）

```
策略：从前 20 个元素（primary_text）和前 120 个元素（extended_text）中
      用 3 个正则模式提取 DOI 候选，按得分排序选出最优。
```

**3 种正则模式**：

```python
# 模式1: 裸 DOI 格式
doi_pattern = r'\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b'

# 模式2: URL 格式
doi_url_pattern = r'https?://doi\.org/(10\.\d{4,9}/[-._;()/:A-Z0-9]+)'

# 模式3: "doi:" 前缀格式
doi_with_prefix_pattern = r'doi[:\s]*(10\.\d{4,9}/[-._;()/:A-Z0-9]+)'
```

**DOI 规范化**：去除 `https://doi.org/` 前缀、`doi:` 前缀、尾部标点、空格。

**评分模型**（`_score_doi`）：

```
基础分 = location_score (primary_text: 1.0, extended_text: 0.6)
+ 包含 "."  +0.2
+ 包含 "/"  +0.2
+ 长度适中  +0.4 (min(len/50, 0.4))
+ 匹配 10.XXXX/ 格式 +0.2
```

候选 DOI 按得分降序排列，取最高分且通过合理性检查的作为最终结果。

#### Tier 2：CrossRef API 查询

```
GET https://api.crossref.org/works/{doi}
→ 解析 JSON 响应
→ 提取: title, authors, publication_year, journal, abstract
→ 写入 DocumentMetadata 表
```

重试策略：最多 3 次，每次间隔 1 秒，超时 `PROCESSOR_CROSSREF_TIMEOUT` 秒（默认 10s）。

**提取的字段**：

| CrossRef 字段路径 | 存入 key |
|-------------------|---------|
| `message.title[]` | `title` |
| `message.author[].given + family` | `authors` |
| `message.published-print/online/issued/created.date-parts` | `publication_year` |
| `message.container-title[]` | `journal` |
| `message.abstract` | `abstract` |
| `message.DOI` | `doi` |

若 CrossRef 查询成功且提取到有效数据，**直接 return**，跳过 Tier 3。

#### Tier 3：LLM 推断

```python
prompt = '''
As a specialist librarian, analyze the text from the first page
of a research paper and extract its core metadata.
Respond ONLY with a single, valid JSON object containing:
"title", "authors" (list), "publication_year" (int),
"journal", "abstract". If not found, use null.

Text:
---
{first_page_text[:4000]}    # 仅使用第 1 页的前 4000 字符
---

JSON Output:
'''
response = get_llm_response(prompt, use_reasoner=False)  # 使用 chat 模型
```

**LLM 配置**：
- 模型：`deepseek-chat`（默认，`DEEPSEEK_CHAT_MODEL_NAME` 可配）
- 输入截断：`PROCESSOR_LLM_METADATA_TRUNCATION` = 4000 字符
- 输出解析：正则提取 `{...}` JSON 块 → `json.loads()`

**元数据持久化**：所有三层提取的结果统一通过 `_store_metadata_entries()` 写入 `DocumentMetadata` 表，每条记录为 `(document_id, key, value)` 的键值对。

### 5.4 内容处理分叉

根据文件类型，分为 **表格文件处理** 和 **非结构化文件处理** 两条路径。

#### 路径 A：表格文件处理（`_process_tabular_file`）

适用格式：`.csv`, `.xls`, `.xlsx`

```
pandas 读取 DataFrame
  │
  ├─→ 宽表检测: 列数 > PROCESSOR_WIDE_TABLE_THRESHOLD (8)?
  │     └─→ 生成 Markdown 表格块 (category: "TabularMarkdown")
  │
  ├─→ 逐行转换:
  │     "Row N contains: 'Column1' is 'value1'; 'Column2' is 'value2'; ..."
  │     (category: "TabularRow", 元数据含 row_index)
  │
  └─→ 统计摘要:
        df.describe(include='all').to_string()
        (is_summary=True, summary_type="full")
```

关键实现：

```python
for index, row in df.iterrows():
    row_description = f"Row {index+2} contains: " + \
        "; ".join([f"'{col}' is '{val}'"
                   for col, val in row.items() if pd.notna(val)]) + "."
    chunks.append({"text": row_description, "metadata": chunk_metadata})
```

> 注意：Excel 行号从 `index+2` 开始（+1 因为 pandas 0-indexed，+1 因为 header 行），与用户看到的电子表格行号对齐。

#### 路径 B：非结构化文件处理（`_process_unstructured_file_new`）

适用格式：PDF, DOCX, MD, TXT

这是系统中最复杂的内容处理逻辑，包含以下子阶段：

##### B1. 元素过滤（`_filter_elements`）

**过滤目标**：

| 过滤规则 | 检测方式 |
|----------|---------|
| 参考文献/致谢/附录章节 | 标题正则匹配（支持中/英/法/德/葡/西 7 种语言） |
| 无标题的参考文献区域 | 连续 3 个元素匹配引用格式 → 触发熔断，回溯删除前 2 个 |
| 页眉/页脚/分页符 | `element.category in ["Header", "Footer", "PageBreak"]` |
| 疑似参考文献的散落内容 | 括号密度 + 年份 + 指示词（doi:, http://, vol., pp. 等）组合检测 |

**关键设计 — 无标题参考文献熔断机制**：

```python
reference_content_pattern = re.compile(
    r'^\s*\[?\d+\]?\s*[A-Z][^.]*\.\s*[A-Z][^.]*\.\s*\(\d{4}\)|'  # [1] Author, A. (2024)
    r'^\s*[A-Z][a-z]+,\s*[A-Z]\.\s*[A-Z]?\.\s*\(\d{4}\)|'        # Smith, J. (2024)
    r'^\s*\[?\d+\]?\s*[A-Z][^,]*,\s*[^,]*,\s*\d{4}',              # [1] Author, Title, 2024
    re.MULTILINE
)

# 连续 3 个元素匹配 → 判定为参考文献区
if consecutive_reference_like >= 3:
    filtered_elements = filtered_elements[:-2]  # 回溯删除前 2 个
    in_low_value_section = True
```

##### B2. 表格元素处理（`_process_table_element_new`）

每个被 `unstructured` 识别为 `Table` 的元素：

```
提取 table_element.metadata.text_as_html (HTML 格式)
  │
  ▼
LLM 生成自然语言摘要:
  "As a data analyst, analyze the following table from a research paper..."
  → 说明表格目的、关键发现、列间关系
  │
  ▼
存储为 chunk (category: "TableSummary", 含 original_table_html)
```

如果 `text_as_html` 不可用（罕见），则回退到存储原始文本。

##### B3. 层次化分块（核心分块逻辑）

这是系统中最精巧的部分。利用文档中的 **标题层级** 来构建上下文感知的文本块：

```
数据结构:
  title_path_stack:  [(level_1, "Introduction"), (level_2, "Background")]
  current_texts:     ["段落1文本", "段落2文本", ...]
  current_page:      3
```

**算法流程**：

```
遍历所有非表格文本元素:
  │
  ├── 遇到 Title 元素:
  │     │
  │     ├── 忽略: 图表标题 (Table/Figure/Fig. + 数字)
  │     ├── 忽略: 参考文献/致谢标题
  │     ├── 忽略: DOI/URL 标题（作为普通文本保留）
  │     │
  │     └── 正常标题:
  │           │
  │           ├── 计算标题层级 (_get_title_level):
  │           │      "1.2.3" → level 3
  │           │      有 category_depth 属性 → 使用该值
  │           │      否则 → level 1
  │           │
  │           ├── 弹出栈中 >= 当前层级的标题:
  │           │     title_path_stack.pop() + create_chunk_from_stack()
  │           │
  │           ├── 将当前缓冲区 flush 为一个 chunk:
  │           │     create_chunk_from_stack(page_number)
  │           │     → text_block = "\n\n".join(current_texts)
  │           │     → metadata 注入 title_h1, title_h2, ... 等路径信息
  │           │
  │           └── 新标题入栈: title_path_stack.append((level, title_text))
  │
  └── 遇到普通文本:
        current_texts.append(text)
```

**超长块二次分割**：

```python
if len(text_block) > text_splitter._chunk_size:  # 超过 3000 字符
    sub_chunks = text_splitter.split_text(text_block)  # NLTKTextSplitter
    for i, sub_chunk_text in enumerate(sub_chunks):
        metadata['sub_chunk_index'] = i
        all_chunks.append({"text": sub_chunk_text, "metadata": metadata})
```

> **NLTKTextSplitter 参数**（来自 config）：
> - `chunk_size` = 3000 字符
> - `chunk_overlap` = 300 字符（确保跨块连续性）
> - 底层使用 NLTK punkt 分词器进行句子边界分割

**分块元数据示例**：

```json
{
  "document_id": "42",
  "source": "attention-is-all-you-need.pdf",
  "title": "Attention Is All You Need",
  "authors": "Vaswani et al.",
  "publication_year": 2017,
  "title_h1": "3 Model Architecture",
  "title_h2": "3.2 Attention",
  "title_h3": "3.2.1 Scaled Dot-Product Attention",
  "page_number": "4",
  "category": "NarrativeText"
}
```

##### B4. 全文摘要生成（`_generate_summary`）

```python
full_text = "\n\n".join(full_text_parts)  # 拼接所有块的文本

prompt = '''
Based on the following text from a document, please provide
a concise, comprehensive summary of the entire document.
The summary should capture the key points, arguments, and conclusions.

Text:
---
{text_to_summarize[:15000]}    # PROCESSOR_LLM_SUMMARY_TRUNCATION
---

Concise Summary:
'''

summary_dict = {
    "text": summary_text,          # LLM 生成的摘要文本
    "metadata": {
        ...core_metadata,          # 继承文档级元数据
        "is_summary": True,
        "summary_type": "full",
        "page_number": "-1"        # 摘要不对应具体页码
    }
}
```

> **注意**：当前实现中，章节级摘要的生成逻辑存在但实际调用时传入空列表 `[]`。未来可在识别到章节标题后调用 `_generate_summary(text, metadata, "chapter", chapter_title="...")` 来填充。这是代码中的一处待完善点（参见 `process_document()` 第 692 行 `_process_unstructured_file_new` 的返回值始终为 `[]`）。

### 5.5 状态终结

```python
# 成功
db_document.status = "completed"
db.commit()
return document_id, chunks, summary, chapter_summaries

# 失败
db_document.status = "failed"
db.add(DocumentMetadata(
    document_id=document_id,
    key="error_message",
    value=str(e)
))
db.commit()
return document_id, [], None, []   # 空结果，不会触发向量入库
```

失败时不抛异常（在 Celery 任务层面），而是将错误信息写入元数据表，前端可在文档列表中展示失败原因。

---

## 6. 第四层：向量化入库

**入口**：[`backend/services/vector_store_service.py`](backend/services/vector_store_service.py)

回到 Celery 任务中，处理完的结果分两条路径进入向量库：

### 6.1 Chunks 入库（`add_chunks`）

```python
def add_chunks(chunks: List[Dict[str, Any]]):
    texts = [chunk['text'] for chunk in chunks]
    metadatas = [chunk['metadata'] for chunk in chunks]
    vector_store.add_texts(texts, metadatas, "document_chunks")
```

### 6.2 Summaries 入库（`add_summaries`）

```python
def add_summaries(summaries: List[Dict[str, Any]]):
    # 按 summary_type 分流
    full_texts = [s['text'] for s in summaries if s['metadata']['summary_type'] == 'full']
    full_metas = [s['metadata'] for s in summaries if s['metadata']['summary_type'] == 'full']

    chapter_texts = [s['text'] for s in summaries if s['metadata']['summary_type'] == 'chapter']
    chapter_metas = [s['metadata'] for s in summaries if s['metadata']['summary_type'] == 'chapter']

    if full_texts:
        vector_store.add_texts(full_texts, full_metas, "document_summaries")
    if chapter_texts:
        vector_store.add_texts(chapter_texts, chapter_metas, "document_chapter_summaries")
```

### 6.3 底层嵌入与写入（`add_texts`）

```python
def add_texts(self, texts, metadatas, collection_name):
    # ① 元数据清洗：只保留 str/int/float/bool 类型
    sanitized_metadatas = [_sanitize_metadata(meta) for meta in metadatas]

    # ② 批量嵌入
    embeddings = self.embedding_model.encode(texts, show_progress_bar=True)
    #    SentenceTransformer → 1024 维向量

    # ③ 生成唯一 ID
    start_id = collection.count()
    ids = [f"{collection_name}_{i}" for i in range(start_id, start_id + len(texts))]

    # ④ 写入 ChromaDB
    collection.add(
        embeddings=embeddings.tolist(),
        documents=texts,
        metadatas=sanitized_metadatas,
        ids=ids
    )
```

**元数据清洗规则**（`_sanitize_metadata`）：

```python
def _sanitize_metadata(metadata):
    sanitized = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            sanitized[key] = value   # ✅ 原生支持的类型
        elif value is not None:
            sanitized[key] = str(value)  # ⚠️ 强制转字符串
        # value is None → 丢弃该字段
    return sanitized
```

> ChromaDB 的 metadata 字段只接受 `str | int | float | bool` 四种类型。`None` 值会被静默丢弃，列表/字典会被强制转为字符串。

---

## 7. 错误处理与容错机制

整个流水线有 **4 层错误处理**：

```
┌──────────────────────────────────────────────────────────────┐
│ 层级             │ 错误处理策略                               │
├──────────────────────────────────────────────────────────────┤
│ API 层           │ try/except 捕获 → HTTP 500 / 409          │
│ Celery 任务层    │ try/except → 日志 → raise（Celery 标记     │
│                  │   FAILURE）→ finally: db.close()         │
│ 文档处理引擎层   │ try/except → status="failed" + 写入        │
│                  │   error_message 元数据 → 返回空结果        │
│ 元数据提取子层   │ 每 Tier 独立 try/except → 失败则降级       │
│                  │   到下一 Tier                              │
│ 分块/摘要子层    │ 独立 try/except → 日志错误但继续处理       │
│                  │   其他部分                                 │
└──────────────────────────────────────────────────────────────┘
```

**关键容错点**：

1. **元数据提取失败** → 不影响文档处理继续（日志 error + rollback）
2. **摘要生成失败** → 仅日志记录，不阻止 chunks 入库
3. **向量写入失败** → 摘要失败仅日志记录；chunks 失败 propagate 到任务层
4. **DB 会话泄漏** → `finally: db.close()` 确保连接归还

---

## 8. 重新处理流程

**入口**：[`backend/api/document_routes.py`](backend/api/document_routes.py) → `POST /api/documents/{id}/reprocess`

与首次处理的核心区别：

| 维度 | 首次处理 | 重新处理 |
|------|---------|---------|
| Document 记录 | 新建 | 复用已有记录 |
| 元数据 | 直接写入 | **先清空**，再重新提取 |
| 向量数据 | 直接写入 | **先删除**，再重新写入 |
| 源文件 | 从 upload 读取 | 从已有 `file_path` 读取 |
| 任务方式 | Celery 异步 | **同步执行**（HTTP 等待结果） |

```python
def reprocess_document_endpoint(document_id, db):
    # ① 验证文档存在
    # ② 删除旧向量（避免重复）
    vector_store_service.delete_document_vectors(document_id)
    # ③ 同步重新处理
    chunks, full_summary, chapter_summaries = \
        document_processor.reprocess_document(db, document_id)
    # ④ 写入新向量
    vector_store_service.add_chunks(chunks)
    vector_store_service.add_summaries(summaries)
```

> 重新处理是**同步**的（不走 Celery），因为 API 层需要立即知道结果以返回给用户。

---

## 9. 删除流程

**入口**：[`backend/api/document_routes.py`](backend/api/document_routes.py) → `DELETE /api/documents/{id}`

```python
def delete_document(document_id, db):
    # ① 验证文档存在
    # ② 先删向量（容错：失败则中断，不删 DB 记录）
    vector_store_service.delete_document_vectors(document_id)
    # ③ 再删数据库记录（cascade 自动清除 DocumentMetadata）
    db.delete(db_document)
    db.commit()
```

**删除顺序的设计考量**：先删向量，再删 DB 记录。如果向量删除失败，DB 记录保留以确保一致性（用户可重试）。DB 记录的删除通过 SQLAlchemy 的 `cascade="all, delete-orphan"` 自动级联清除所有关联的 `DocumentMetadata`。

> **注意**：当前实现**不会**删除磁盘上的源文件（`backend/data/uploads/` 下的文件）。这是有意为之，便于重新处理。

---

## 10. 数据模型

### 10.1 SQLite 关系模型

```
┌──────────────────────────┐
│        Document           │
├──────────────────────────┤
│ id (PK, INTEGER)         │
│ file_name (STRING)       │
│ file_type (STRING)       │
│ file_path (STRING, UNIQ) │
│ file_hash (STRING, UNIQ) │◄── 去重索引
│ file_size (INTEGER)      │
│ upload_timestamp (DATETIME)│
│ status (STRING, INDEX)   │◄── "processing"|"completed"|"failed"
└──────────────────────────┘
            │ 1:N
            ▼
┌──────────────────────────┐
│    DocumentMetadata       │
├──────────────────────────┤
│ id (PK, INTEGER)         │
│ document_id (FK)         │
│ key (STRING, INDEX)      │
│ value (STRING)           │
│ extra (JSON)             │
└──────────────────────────┘
```

### 10.2 ChromaDB 向量模型

三个集合共享同一结构：

```
┌─────────────────────────────────────────────┐
│  ChromaDB Collection                        │
├─────────────────────────────────────────────┤
│  id: "document_chunks_0",                   │
│       "document_chunks_1", ...              │
│  embedding: [0.023, -0.145, ...] (1024维)   │
│  document: "The transformer architecture..." │
│  metadata: {                                │
│    document_id: "42",                       │
│    source: "attention-is-all-you-need.pdf",  │
│    title: "Attention Is All You Need",      │
│    publication_year: 2017,                  │
│    title_h1: "3 Model Architecture",        │
│    page_number: "4",                        │
│    category: "NarrativeText",               │
│    ...                                      │
│  }                                          │
└─────────────────────────────────────────────┘
```

---

## 11. 完整调用链路图

```
用户点击上传
    │
    ▼
POST /api/upload/                          [document_routes.py:55]
    │
    ├── file.read() → file_content (bytes)
    ├── hashlib.sha256(file_content) → file_hash
    ├── Document.filter(file_hash).first() → 409 or continue
    ├── file_path.write_bytes(file_content)
    ├── file_path.stat().st_size → file_size
    │
    └── ingest_document_task.delay(file_path, file_hash, file_size)
            │
            ▼  (Redis 消息队列)
            │
    ┌───────────────────────────────────────────────┐
    │  Celery Worker 拉取任务                         │
    │  ingest_document_task()                       │  [ingestion_tasks.py:13]
    │      │                                         │
    │      ├── db = SessionLocal()                  │
    │      │                                         │
    │      └── process_document(db, file_path,       │
    │              file_size, file_hash)             │  [document_processor.py:635]
    │              │                                  │
    │              ├── ① Document(status="processing")│
    │              │      db.add() → db.commit()      │
    │              │                                  │
    │              ├── ② partition(file_path,         │
    │              │       strategy="hi_res",         │
    │              │       infer_table_structure=True)│
    │              │    → List[Element]               │
    │              │                                  │
    │              ├── ③ _extract_and_store_metadata()│
    │              │    ├── DOI regex scan (前120元素) │
    │              │    ├── CrossRef API (最多3次重试) │
    │              │    └── LLM inference (第1页4000字)│
    │              │    → DocumentMetadata 键值对      │
    │              │                                  │
    │              ├── ④ _get_metadata_as_dict()      │
    │              │    → core_metadata (注入到每块)   │
    │              │                                  │
    │              ├── ⑤ 分叉处理:                     │
    │              │    ├── Tabular:                  │
    │              │    │   _process_tabular_file()   │
    │              │    │   → 逐行文本 + 宽表Markdown  │
    │              │    │   → 统计摘要                 │
    │              │    │                              │
    │              │    └── Unstructured:              │
    │              │        _process_unstructured_     │
    │              │        file_new()                 │
    │              │        ├── _filter_elements()     │
    │              │        │   → 去参考文献/页眉页脚   │
    │              │        ├── _process_table_element │
    │              │        │   _new() → LLM表格摘要   │
    │              │        ├── 层次化分块             │
    │              │        │   (title_path_stack +    │
    │              │        │    NLTKTextSplitter)     │
    │              │        └── _generate_summary()    │
    │              │            → 全文摘要             │
    │              │                                  │
    │              └── ⑥ status="completed"            │
    │                  db.commit()                     │
    │                                                  │
    │      ┌── vector_store_service.add_chunks()      │  [vector_store_service.py:221]
    │      │   ├── embedding_model.encode(texts)       │
    │      │   ├── _sanitize_metadata()               │
    │      │   └── collection.add(embeddings,          │
    │      │       documents, metadatas, ids)          │
    │      │       → document_chunks                  │
    │      │                                          │
    │      └── vector_store_service.add_summaries()   │  [vector_store_service.py:232]
    │          ├── full → document_summaries          │
    │          └── chapter → document_chapter_summaries│
    │                                                  │
    │      return {"status": "success", ...}           │
    │                                                  │
    └──────────────────────────────────────────────────┘
            │
            ▼
    前端轮询 GET /api/tasks/{task_id}
    或 WebSocket 实时推送
    → status: "SUCCESS" → 文档可用
```

---

## 附录：关键配置参数速查

| 参数 | 默认值 | 影响阶段 | 说明 |
|------|--------|---------|------|
| `PROCESSOR_DOI_PRIMARY_SCAN_LIMIT` | 20 | 元数据 Tier 1 | 主要 DOI 扫描的前 N 个元素 |
| `PROCESSOR_DOI_EXTENDED_SCAN_LIMIT` | 120 | 元数据 Tier 1 | 扩展 DOI 扫描的前 N 个元素 |
| `PROCESSOR_CROSSREF_TIMEOUT` | 10 | 元数据 Tier 2 | CrossRef API 超时秒数 |
| `PROCESSOR_LLM_METADATA_TRUNCATION` | 4000 | 元数据 Tier 3 | LLM 元数据提取的最大字符数 |
| `PROCESSOR_LLM_SUMMARY_TRUNCATION` | 15000 | 摘要生成 | LLM 摘要生成的最大字符数 |
| `PROCESSOR_CHUNK_SIZE` | 3000 | 文本分块 | NLTKTextSplitter 块大小 |
| `PROCESSOR_CHUNK_OVERLAP` | 300 | 文本分块 | 相邻块的重叠字符数 |
| `PROCESSOR_WIDE_TABLE_THRESHOLD` | 8 | 表格处理 | 触发 Markdown 渲染的列数阈值 |
| `CHUNKS_COLLECTION_NAME` | `document_chunks` | 向量入库 | 段落块集合名 |
| `SUMMARIES_COLLECTION_NAME` | `document_summaries` | 向量入库 | 全文摘要集合名 |
| `CHAPTER_SUMMARIES_COLLECTION_NAME` | `document_chapter_summaries` | 向量入库 | 章节摘要集合名 |
| `EMBEDDING_MODEL_NAME` | `BAAI/bge-large-en-v1.5` | 向量化 | 嵌入模型名 |
