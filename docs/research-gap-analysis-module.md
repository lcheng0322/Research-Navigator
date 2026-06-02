# 研究空白分析模块完整实现详解

> 本文档深入解析 Research Navigator 的研究空白分析功能——基于 BERTopic 主题建模的全知识库分析，自动识别核心研究主题、检测离群文档（潜在研究空白），并生成研究方向建议。

---

## 目录

1. [架构总览](#1-架构总览)
2. [前端交互设计](#2-前端交互设计)
3. [数据准备阶段](#3-数据准备阶段)
4. [BERTopic 主题建模](#4-bertopic-主题建模)
5. [趋势分析](#5-趋势分析)
6. [离群文档与 LLM 研究方向建议](#6-离群文档与-llm-研究方向建议)
7. [结果缓存策略](#7-结果缓存策略)
8. [DOCX 导出](#8-docx-导出)
9. [完整调用链路图](#9-完整调用链路图)
10. [附录：技术栈说明与已知问题](#10-附录技术栈说明与已知问题)

---

## 1. 架构总览

```
用户点击 "Start Gap Analysis"
    │
    ▼
POST /api/analyze/research-gaps/            [analysis_routes.py:109]
    │
    ├── analyze_research_gaps_task.delay()   [analysis_tasks.py:13]
    │     ↓  (Redis 消息队列)
    │   Celery Worker 拉取
    │     ↓
    │   perform_gap_analysis(collection_names)
    │                         [research_gap_analyzer_service.py:160]
    │     │
    │     ├── ① 全量数据获取
    │     │     vector_store.get_all_documents() × 2 集合
    │     │     → 所有文档的文本 + 元数据
    │     │
    │     ├── ② BERTopic 主题建模
    │     │     topic_model.fit_transform(texts)
    │     │     → 主题分配 + 主题信息
    │     │
    │     ├── ③ 趋势分析
    │     │     topic_model.topics_over_time(docs, timestamps)
    │     │     → 主题流行度时间序列
    │     │
    │     ├── ④ 离群检测 + LLM 方向建议
    │     │     提取 topic == -1 的文档
    │     │     → LLM (reasoner) 分析 → 研究方向建议
    │     │
    │     └── ⑤ 缓存结果 (Redis, 24h TTL)
    │
    └── 前端 WebSocket/轮询 → 展示结果
```

**核心文件映射**：

| 层 | 文件 | 职责 |
|----|------|------|
| API 路由 | [`backend/api/analysis_routes.py`](backend/api/analysis_routes.py) 第 109–116 行 | 触发分析 + DOCX 下载端点 |
| 任务封装 | [`backend/tasks/analysis_tasks.py`](backend/tasks/analysis_tasks.py) 第 13–32 行 | 外层 Celery 任务包装 |
| 核心服务 | [`backend/services/research_gap_analyzer_service.py`](backend/services/research_gap_analyzer_service.py) | BERTopic 建模 + 趋势 + 离群分析 |
| 前端页面 | [`frontend/src/pages/GapAnalysisPage.tsx`](frontend/src/pages/GapAnalysisPage.tsx) | 统计卡片 + 主题表格 + 离群列表 + Plotly 趋势图 |

**关键依赖**：

| 组件 | 用途 |
|------|------|
| `BERTopic` | 主题建模（聚类 + 关键词提取） |
| `SentenceTransformer` | BERTopic 的嵌入模型（复用 `BAAI/bge-large-en-v1.5`） |
| `CountVectorizer` | BERTopic 的文本向量化器（含学术领域自定义停用词） |
| `Plotly.js` | 前端主题趋势折线图 |

---

## 2. 前端交互设计

**文件**：[`frontend/src/pages/GapAnalysisPage.tsx`](frontend/src/pages/GapAnalysisPage.tsx)

### 2.1 页面布局

```
┌──────────────────────────────────────────────────────────────┐
│  Research Gap Analysis                                       │
│  Identify thematic clusters and potential research gaps...   │
├──────────────────────────────────────────────────────────────┤
│  [Start Gap Analysis]                                        │
├──────────────────────────────────────────────────────────────┤
│  (分析中: Loading spinner + Status 显示)                      │
├──────────────────────────────────────────────────────────────┤
│  (完成后:)                                                    │
│                                                              │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐      │
│  │ 42       │  │ 8            │  │ 12                │      │
│  │Documents │  │Core Topics   │  │Potential Gaps     │      │
│  └──────────┘  └──────────────┘  └───────────────────┘      │
│                                      [Download as DOCX]      │
├──────────────────────────────────────────────────────────────┤
│  Research Direction Suggestion                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ "Based on the outlier analysis, the following        │    │
│  │  emerging research directions were identified..."    │    │
│  └──────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────┤
│  Potential Research Gaps & Emerging Areas                    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ ▶ View all 12 outlier documents                      │    │
│  │   [paper1.pdf, Page 3] ...outlier snippet text...    │    │
│  │   [paper2.pdf, Page 7] ...outlier snippet text...    │    │
│  └──────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────┤
│  Core Research Themes                                        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐            │
│  │ Topic 0     │ │ Topic 1     │ │ Topic 2     │ ...        │
│  │ Keyword tags │ │ Keyword tags │ │ Keyword tags │           │
│  │ 15 docs     │ │ 8 docs      │ │ 6 docs      │            │
│  └─────────────┘ └─────────────┘ └─────────────┘            │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ Topic ID │ Keywords          │ Document Count       │    │
│  │ Topic 0  │ Keyword1 & KW2... │ 15                   │    │
│  │ Topic 1  │ Keyword1 & KW2... │ 8                    │    │
│  │ ...      │ ...               │ ...                  │    │
│  └──────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────┤
│  Topic Trend Analysis                                       │
│  ┌──────────────────────────────────────────────────────┐    │
│  │   📈 Plotly 折线图: Topic Popularity Over Time       │    │
│  │   多条彩色曲线，X=年份，Y=Frequency                    │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 状态持久化

前端使用 `sessionStorage` 在页面刷新后恢复 `currentTaskId`，避免用户刷新页面后丢失对正在运行任务的跟踪：

```typescript
const SESSION_STORAGE_KEY = 'gapAnalysisPage_currentTaskId';

const [currentTaskId, setCurrentTaskId] = useState<string | null>(
    () => sessionStorage.getItem(SESSION_STORAGE_KEY)  // 懒初始化
);

useEffect(() => {
    if (currentTaskId) {
        sessionStorage.setItem(SESSION_STORAGE_KEY, currentTaskId);
    } else {
        sessionStorage.removeItem(SESSION_STORAGE_KEY);
    }
}, [currentTaskId]);
```

### 2.3 Topic Name 格式化

BERTopic 生成的主题名称形如 `0_keyword1_keyword2_keyword3`，前端将其格式化为可读标题：

```typescript
const formatTopicName = (name: string): string => {
    return name
        .split('_')
        .slice(1)                     // 去掉前导的数字 ID
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' & ');                 // 用 & 连接关键词
};

// 例:
// "0_thermochemical_treatment_ash" → "Thermochemical & Treatment & Ash"
```

---

## 3. 数据准备阶段

**位置**：[`research_gap_analyzer_service.py`](backend/services/research_gap_analyzer_service.py) 第 170–188 行

### 3.1 全量数据获取

```python
# 从两个集合拉取全部文档
all_docs_with_meta = []
for name in ["document_chunks", "document_summaries"]:
    docs = vector_store.get_all_documents(collection_name=name)
    # get_all_documents() → [{"text": "...", "metadata": {...}}, ...]
    all_docs_with_meta.extend(docs)

# 过滤：只保留有 'source' 元数据的非 CSV 文档
narrative_docs = [
    doc for doc in all_docs_with_meta
    if 'source' in doc.get('metadata', {})
    and not doc['metadata']['source'].endswith('.csv')
]
```

> **为什么过滤 CSV？** CSV 文件入库时被拆成了逐行的 "Row N contains: ..." 格式。这种高度结构化的文本会引入噪声，干扰主题建模的质量。

### 3.2 文本与时间戳提取

```python
texts = [doc['text'] for doc in narrative_docs]
timestamps = [doc['metadata'].get('publication_year') for doc in narrative_docs]

# 趋势分析需要有效的年份数据
docs_for_trends = [
    (text, ts) for text, ts in zip(texts, timestamps)
    if isinstance(ts, int) and 1900 < ts <= datetime.date.today().year
]
# 例: 过滤掉 None、'2023a'、1800 等无效年份
```

**数据量级**：这是全量操作。一个有 50 篇文档的知识库，可能产生数千个文本块（paragraph chunks）。这也是为什么此功能必须是异步的——BERTopic 在数千条文本上的拟合可能需要数分钟。

---

## 4. BERTopic 主题建模

**位置**：[`research_gap_analyzer_service.py`](backend/services/research_gap_analyzer_service.py) 第 42–46 行（初始化）、第 190–193 行（执行）

### 4.1 模型配置

```python
class ResearchGapAnalyzerService:
    def __init__(self):
        # 自定义停用词
        stop_words = list(ENGLISH_STOP_WORDS) + ACADEMIC_STOP_WORDS

        self.vectorizer_model = CountVectorizer(
            stop_words=stop_words,
            ngram_range=(1, 3)      # unigram + bigram + trigram
        )

        self.topic_model = BERTopic(
            embedding_model=SentenceTransformer(
                settings.EMBEDDING_MODEL_NAME,   # "BAAI/bge-large-en-v1.5"
                local_files_only=True
            ),
            vectorizer_model=self.vectorizer_model
        )
```

**学术领域自定义停用词**（`ACADEMIC_STOP_WORDS`）：

```python
ACADEMIC_STOP_WORDS = [
    'introduction', 'background', 'method', 'results', 'discussion',
    'conclusion', 'abstract', 'summary', 'references',
    'study', 'paper', 'research', 'article',
    'data', 'model', 'system',
    'et', 'al', 'however', 'therefore'
]
```

> 这些词在学术论文中出现频率极高但几乎没有主题区分度——几乎每篇论文都有 method、results、discussion 等章节。将它们加入停用词能显著提升主题关键词的区分度。

### 4.2 BERTopic 工作流程

```python
# 拟合 + 转换
topics, _ = service.topic_model.fit_transform(texts)

# 获取主题信息
topic_info = service.topic_model.get_topic_info()
```

**BERTopic 内部流程**：

```
文本列表
  │
  ├── ① SentenceTransformer 嵌入 → 1024 维向量
  │
  ├── ② UMAP 降维 → 低维空间（默认 5 维）
  │
  ├── ③ HDBSCAN 聚类
  │     ├── 紧密簇 → 分配 Topic ID (0, 1, 2, ...)
  │     └── 无法归类的点 → Topic = -1 ("噪声"/"离群")
  │
  └── ④ c-TF-IDF 关键词提取
        对每个簇，提取区分度最高的 n-gram 作为主题关键词
        Topic 0: "thermochemical_treatment_ash_heavy_metal"
        Topic 1: "phosphorus_recovery_nutrient_soil"
        ...
```

### 4.3 topic_info 输出结构

```python
topic_info.to_dict('records') →
[
    {
        "Topic": 0,
        "Count": 15,
        "Name": "0_thermochemical_treatment_ash",
        "Representation": ["thermochemical", "treatment", "ash", ...]
    },
    {
        "Topic": 1,
        "Count": 8,
        "Name": "1_phosphorus_recovery_nutrient",
        "Representation": ["phosphorus", "recovery", "nutrient", ...]
    },
    ...
    {
        "Topic": -1,
        "Count": 12,
        "Name": "-1_noise_outlier_documents",
        "Representation": [...]
    },
]
```

**Topic = -1 的含义**：HDBSCAN 将无法分配到任何簇的点标记为 -1。在学术文献分析的语境下，这些"噪声"文档可能代表：

- 研究领域中尚未形成共识的新兴方向
- 来自不同领域的交叉研究
- 真正的研究空白——很少有文献覆盖的方向

---

## 5. 趋势分析

**位置**：[`research_gap_analyzer_service.py`](backend/services/research_gap_analyzer_service.py) 第 196–203 行

### 5.1 执行条件

趋势分析要求文档具有有效的出版年份：

```python
if trend_texts:  # 至少有一条带有效年份的数据
    topics_over_time = service.topic_model.topics_over_time(
        docs=list(trend_texts),
        timestamps=list(trend_timestamps)
    )
    trends = topics_over_time.to_dict('records')
```

**topics_over_time 原理**：对于每个时间点（年份），统计该年份中各主题的文档频率。如果某主题在近年的频率显著上升，说明这是"热门方向"；如果某主题的频率下降或几乎没有文档，可能是"饱和领域"或"待探索的空白"。

### 5.2 输出结构

```python
trends = [
    {"Timestamp": "2020", "Topic": 0, "Frequency": 0.15},
    {"Timestamp": "2020", "Topic": 1, "Frequency": 0.08},
    {"Timestamp": "2021", "Topic": 0, "Frequency": 0.22},
    {"Timestamp": "2021", "Topic": 1, "Frequency": 0.10},
    ...
]
```

### 5.3 前端可视化

前端使用 Plotly.js 绘制多线折线图：

```typescript
// 每个 Topic 一条曲线
{
    x: ['2020', '2021', '2022', ...],    // 年份
    y: [0.15, 0.22, 0.18, ...],          // 频率
    type: 'scatter',
    mode: 'lines+markers',
    name: 'Thermochemical & Treatment & Ash'  // 格式化后的主题名
}
```

---

## 6. 离群文档与 LLM 研究方向建议

**位置**：[`research_gap_analyzer_service.py`](backend/services/research_gap_analyzer_service.py) 第 206–236 行

### 6.1 离群文档提取

```python
outlier_docs = [
    {
        "text": narrative_docs[i].get("text", ""),
        "metadata": {
            "source": narrative_docs[i].get("metadata", {}).get("source", "Unknown"),
            "page_number": narrative_docs[i].get("metadata", {}).get("page_number"),
        },
    }
    for i, topic in enumerate(topics)
    if topic == -1 and i < len(narrative_docs)
]
```

### 6.2 LLM 研究方向建议

```python
# 取前 10 个离群文档的头 300 字符
outlier_summary = "\n".join([
    f"- {doc.get('text', '')[:300]}..."
    for doc in outlier_docs[:10]
])

prompt = f'''
You are a research strategist. The following text snippets are
outliers from a topic modeling analysis of a large document set.
This means they do not fit into any of the main identified themes.

Analyze these outlier snippets to identify potential nascent
trends or unexplored research gaps.

OUTLIER SNIPPETS:
{outlier_summary}

Based on this, provide a concise summary of potential research
directions or novel ideas suggested by these outliers.
'''

direction_suggestion = get_llm_response(prompt, use_reasoner=True)
```

**本次 LLM 调用**：

| 属性 | 值 |
|------|-----|
| 模型 | `deepseek-reasoner` |
| use_reasoner | **True**（需要深度推理来识别研究趋势） |
| json_mode | False（自由文本输出） |
| 输入 | 前 10 个离群文档的摘要（各 ≤300 字符） |
| 输出 | 自然语言段落：潜在研究方向建议 |

**LLM 在研究空白分析中的角色**：

BERTopic 负责**识别**离群（"哪些文档不属于任何主流主题"），LLM 负责**解读**离群（"这些离群文档暗示了什么研究方向"）。这是统计方法 + 语义理解的互补：

```
BERTopic (统计)          LLM (语义)
  "这 12 篇文档              "这些文档涉及
   不属于任何主题"           磷回收的微生物机制
      │                     和低温热解耦合，
      │                     可能是一个被忽视
      ▼                     的交叉研究方向。"
  outlier_docs  ──────────▶ direction_suggestion
```

---

## 7. 结果缓存策略

**位置**：[`research_gap_analyzer_service.py`](backend/services/research_gap_analyzer_service.py) 第 31–32 行、第 166 行、第 251 行

### 7.1 缓存设计

```python
CACHE_KEY_PREFIX = "gap_analysis_"
CACHE_EXPIRATION = 3600 * 24  # 24 小时

cache_key = f"gap_analysis_document_chunks_document_summaries"
#                        ↑ 集合名按字母排序后拼接

# 存入缓存
redis_client.set(cache_key, json.dumps(result), ex=86400)

# 读取缓存
cached_result = redis_client.get(cache_key)
```

### 7.2 为什么 TTL 是 24 小时

| 考量 | 说明 |
|------|------|
| 计算成本 | BERTopic 全量建模耗时数分钟，频繁重跑浪费资源 |
| 数据新鲜度 | 个人知识库的文档增加频率通常不高（不是实时流式场景） |
| 缓存键设计 | 基于集合名的组合——如果集合配置变了，缓存键也变，自动失效 |

### 7.3 ⚠️ Redis 客户端兼容性问题

```python
# cache.py 使用异步客户端
import redis.asyncio as aioredis
redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

# research_gap_analyzer_service.py 中的同步调用
cached_result = redis_client.get(cache_key)    # 返回 coroutine，不是字符串！
redis_client.set(cache_key, ..., ex=...)       # 返回 coroutine，不会实际写入
```

Celery Worker 运行在同步上下文中，`redis_client.get()` 返回的是一个未执行的协程对象（coroutine），而非实际值。这导致：

- 缓存检查永远不会命中（coroutine object ≠ None，但也不是有效数据）
- 缓存写入永远不会实际执行

**影响**：每次分析都会重新运行 BERTopic（即使上次结果仍在有效期内）。这是一个需要修复的 bug——应使用同步 Redis 客户端（`redis.Redis`）或 `asyncio.run()` 包装。

---

## 8. DOCX 导出

**端点**：`GET /api/analyze/research-gaps/download/{task_id}`
**方法**：`ResearchGapAnalyzerService.export_gap_analysis_to_docx()`

### 8.1 文档结构

```
┌─────────────────────────────────────────────┐
│  Research Gap Analysis Report               │  ← Level 0
├─────────────────────────────────────────────┤
│  Summary                                    │  ← Level 1
│  Total Documents Analyzed: 42               │
│  Core Topics Found: 8                       │
│  Potential Gaps (Outliers): 12              │
├─────────────────────────────────────────────┤
│  Research Direction Suggestion              │  ← Level 1
│  "Based on the analysis of outlier          │
│   documents, several emerging research      │
│   directions can be identified..."          │
├─────────────────────────────────────────────┤
│  Core Research Themes                       │  ← Level 1
│  ┌──────────┬──────────────────┬─────────┐  │
│  │ Topic ID │ Topic Keywords   │ Count   │  │
│  ├──────────┼──────────────────┼─────────┤  │
│  │ 0        │ Thermochemical.. │ 15      │  │
│  │ 1        │ Phosphorus Reco..│ 8       │  │
│  │ ...      │ ...              │ ...     │  │
│  └──────────┴──────────────────┴─────────┘  │
│  (最多 20 行)                                │
├─────────────────────────────────────────────┤
│  Potential Research Gaps (Outliers)         │  ← Level 1
│  These documents were identified as         │
│  outliers because their content does not    │
│  fit into any of the main research themes.  │
│                                             │
│  1. [paper1.pdf, Page 3]                    │
│  snippet text (≤500 chars)...               │
│                                             │
│  2. [paper2.pdf, Page 7]                    │
│  snippet text (≤500 chars)...               │
│  (最多 10 条)                                │
├─────────────────────────────────────────────┤
│  Topic Trend Analysis                       │  ← Level 1
│  Trend data available with N records.       │
│  Refer to the application for interactive   │
│  charts.                                    │
└─────────────────────────────────────────────┘
```

> 注意：DOCX 中的趋势分析部分是**纯文本说明**，不含实际图表——Plotly 交互式图表无法嵌入 DOCX。文档中建议用户回到应用查看交互式图表。

### 8.2 Topic Name 格式化

```python
name = str(t.get('Name', ''))
# 例: "0_thermochemical_treatment_ash"
formatted = ' '.join(word.capitalize()
                      for word in name.split('_')[1:]) or name
# → "Thermochemical Treatment Ash"
```

---

## 9. 完整调用链路图

```
用户点击 "Start Gap Analysis"
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ POST /api/analyze/research-gaps/                             │
│                                          [analysis_routes.py:109]
│                                                              │
│   analyze_research_gaps_task.delay()                         │
│   → task_id → 返回给前端                                      │
│                                                              │
│   ─ ─ ─ ─ ─ (Celery Worker 异步执行) ─ ─ ─ ─ ─              │
│                                                              │
│   analyze_research_gaps_task()              [analysis_tasks.py:13]
│     │                                                        │
│     └── perform_gap_analysis(collection_names)               │
│                         [research_gap_analyzer_service.py:160]
│         │                                                    │
│         ├── ① 全量数据获取                                    │
│         │   for name in ["document_chunks",                  │
│         │                 "document_summaries"]:              │
│         │     docs = vector_store.get_all_documents(name)    │
│         │     all_docs_with_meta.extend(docs)                │
│         │                                                    │
│         │   过滤: 有 'source' 元数据 + 非 .csv 文件           │
│         │   → narrative_docs                                 │
│         │                                                    │
│         │   texts = [doc['text'] for doc in narrative_docs]  │
│         │   timestamps = [doc['metadata']['publication_year']│
│         │                 for doc in narrative_docs]         │
│         │                                                    │
│         ├── ② BERTopic 主题建模                               │
│         │   topics, _ = topic_model.fit_transform(texts)     │
│         │   │                                                │
│         │   │  BERTopic 内部流程:                             │
│         │   │  SentenceTransformer embedding                 │
│         │   │  → UMAP 降维                                   │
│         │   │  → HDBSCAN 聚类                                │
│         │   │  → c-TF-IDF 关键词提取                          │
│         │   │                                                │
│         │   └── topic_info = get_topic_info()                │
│         │       → [{"Topic": 0, "Count": 15, "Name": ...}]  │
│         │                                                    │
│         ├── ③ 趋势分析 (条件执行)                              │
│         │   if trend_texts (有有效年份):                       │
│         │     topics_over_time = topic_model                 │
│         │       .topics_over_time(                           │
│         │         docs=trend_texts,                          │
│         │         timestamps=trend_timestamps                │
│         │       )                                            │
│         │     trends = .to_dict('records')                   │
│         │                                                    │
│         ├── ④ 离群检测 + LLM 研究方向建议                      │
│         │   outlier_docs = [                                 │
│         │     doc for i, doc in enumerate(narrative_docs)    │
│         │     if topics[i] == -1                             │
│         │   ]                                                │
│         │                                                    │
│         │   if outlier_docs:                                 │
│         │     outlier_summary = "\n".join([                  │
│         │       doc['text'][:300] for doc in outlier_docs    │
│         │     ])                                             │
│         │                                                    │
│         │     prompt = "You are a research strategist..."    │
│         │     direction_suggestion = get_llm_response(       │
│         │       prompt,                                      │
│         │       use_reasoner=True    ← 推理模型               │
│         │     )                                              │
│         │                                                    │
│         └── ⑤ 编译结果 + 缓存                                  │
│             result = {                                       │
│               "total_documents_analyzed": ...,               │
│               "total_topics_found": ...,                     │
│               "topics": [...],                               │
│               "trends": [...],                               │
│               "outlier_documents_count": ...,                │
│               "outlier_documents": [...],                    │
│               "research_gap_suggestion": "..."               │
│             }                                                │
│                                                              │
│             redis_client.set(cache_key, result, ex=86400)    │
│             return result                                    │
│                                                              │
│   ← Redis Result Backend 存储任务结果                         │
└──────────────────────────────────────────────────────────────┘
    │
    │ 前端 WebSocket/轮询检测到 SUCCESS
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ 前端渲染                                                      │
│                                                              │
│  ├── 统计卡片: Documents / Topics / Outliers                  │
│  ├── 研究方向建议 Alert                                       │
│  ├── 离群文档 Collapse 列表                                   │
│  ├── 核心主题卡片 + 表格                                      │
│  └── Plotly 趋势折线图                                        │
│                                                              │
│  [Download as DOCX] → GET /.../download/{task_id}            │
│                                          [analysis_routes.py:118]
│    └── export_gap_analysis_to_docx(analysis_data)            │
│        → DOCX → StreamingResponse                            │
└──────────────────────────────────────────────────────────────┘
```

---

## 10. 附录：技术栈说明与已知问题

### 10.1 BERTopic 技术栈

| 组件 | 在此项目中的角色 |
|------|-----------------|
| `SentenceTransformer` | 将文档文本转为 1024 维向量（复用 BGE-large） |
| `UMAP` | 将高维向量降至低维空间，保留局部结构 |
| `HDBSCAN` | 基于密度的聚类，自动确定簇数量 |
| `c-TF-IDF` | 为每个簇提取最具区分性的 n-gram |
| `CountVectorizer` | 文本 → n-gram 计数矩阵 |

### 10.2 Celery 任务双层包装

项目中有两个 `@celery_app.task` 装饰的函数：

```python
# 外层: analysis_tasks.py
@celery_app.task(name="tasks.analyze_research_gaps")
def analyze_research_gaps_task():
    return perform_gap_analysis(collection_names)  # 同步调用

# 内层: research_gap_analyzer_service.py
@celery_app.task(name="perform_gap_analysis")
def perform_gap_analysis(collection_names):
    # 实际分析逻辑
```

**为什么有两层？** 内层 `perform_gap_analysis` 同时可以被 `ResearchGapAnalyzerService.trigger_analysis()` 调用（预留的另一种触发路径）。外层 `analyze_research_gaps_task` 提供了一层**配置封装**——它固定了 `collection_names` 参数，API 端点不需要关心应该分析哪些集合。

由于内层函数被同步调用（不是 `.delay()`），它实际上不会作为独立的 Celery 任务执行，而是在外层任务的 Worker 进程中直接运行。

### 10.3 已知问题

#### 问题 1：异步 Redis 客户端在同步上下文中调用

**位置**：[`research_gap_analyzer_service.py`](backend/services/research_gap_analyzer_service.py) 第 67 行、第 251 行

**问题**：`redis_client` 是 `redis.asyncio` 的异步客户端，但在 Celery Worker（同步上下文）中被直接调用。`redis_client.get()` 和 `redis_client.set()` 返回的是协程对象而非实际值。

**影响**：
- `trigger_analysis()` 的缓存检查逻辑失效（协程对象 truthy，永远认为"有缓存"）
- 结果缓存从不实际写入 Redis
- 每次分析都重新运行 BERTopic

**修复建议**：使用同步 Redis 客户端，或在任务中使用 `asyncio.run()`：

```python
import redis
sync_redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
```

#### 问题 2：trigger_analysis 未被 API 端点使用

**位置**：[`research_gap_analyzer_service.py`](backend/services/research_gap_analyzer_service.py) 第 58–74 行

`trigger_analysis()` 方法包含缓存检查逻辑和 Celery 任务触发，但 API 端点 `start_research_gap_analysis()` 直接调用 `analyze_research_gaps_task.delay()`，绕过了这个方法。这意味着：

- `trigger_analysis()` 的设计意图（先查缓存、缓存命中则直接返回）未被实际使用
- 缓存逻辑虽然在 `perform_gap_analysis` 的末尾有写入，但读取逻辑未被调用

#### 问题 3：DOCX 导出中的趋势数据无图表

**位置**：[`research_gap_analyzer_service.py`](backend/services/research_gap_analyzer_service.py) 第 150–156 行

```python
doc.add_heading('Topic Trend Analysis', level=1)
if trends and len(trends) > 0:
    doc.add_paragraph("Trend data available...")
    doc.add_paragraph("Refer to the application for interactive charts.")
```

DOCX 中只能放置文字说明，无法包含 Plotly 交互式图表。这是 DOCX 格式的固有限制。可能的改进方向是将 Plotly 导出为静态图片（PNG）后再嵌入 DOCX。
