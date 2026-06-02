# 智能问答（RAG）功能完整实现详解

> 本文档深入解析 Research Navigator 的六阶段 RAG 问答管线，从用户输入问题到获得带引用的推理答案的完整链路。

---

## 目录

1. [架构总览](#1-架构总览)
2. [第一阶段：查询分析与意图识别](#2-第一阶段查询分析与意图识别)
3. [第二阶段：多集合检索](#3-第二阶段多集合检索)
4. [第三阶段：去重与过滤](#4-第三阶段去重与过滤)
5. [第四阶段：Cross-Encoder 重排序](#5-第四阶段cross-encoder-重排序)
6. [第五阶段：证据质量与一致性评估](#6-第五阶段证据质量与一致性评估)
7. [第六阶段：链式推理引擎](#7-第六阶段链式推理引擎)
8. [缓存策略](#8-缓存策略)
9. [查询历史持久化](#9-查询历史持久化)
10. [DOCX 导出](#10-docx-导出)
11. [完整调用链路图](#11-完整调用链路图)
12. [附录：配置参数速查](#12-附录配置参数速查)

---

## 1. 架构总览

```
POST /api/query/
  │  form: query="transformer 模型的注意力机制是如何工作的？"
  │  JWT 鉴权
  ▼
┌─────────────────────────────────────────────────────────────────┐
│                      六阶段 RAG 管线                              │
│                                                                  │
│  ① 查询分析                    ② 多集合检索                      │
│  ┌──────────┐                ┌──────────────────┐               │
│  │ LLM 分析 │                │ document_chunks  │               │
│  │ 意图识别 │───intent──────▶│ document_        │               │
│  │ 实体提取 │    策略选择     │   summaries      │───候选文档───▶│
│  │ 查询改写 │                │ document_chapter │               │
│  │ 复杂度   │                │   _summaries     │               │
│  │ 领域分类 │                └──────────────────┘               │
│  └──────────┘                                                    │
│                                                                  │
│  ③ 去重与过滤              ④ Cross-Encoder 重排序               │
│  ┌──────────────┐          ┌────────────────────┐               │
│  │ 按来源聚合    │          │ BGE-Reranker       │               │
│  │ 每源 ≤ 3 条  │─────────▶│ CrossEncoder       │───Top-K──────▶│
│  │ 过滤参考文献  │          │ 精排重打分          │               │
│  └──────────────┘          └────────────────────┘               │
│                                                                  │
│  ⑤ 证据评估                  ⑥ 推理引擎                         │
│  ┌──────────────┐          ┌────────────────────┐               │
│  │ 相关性 1-5   │          │ Step 1: 综合答案    │               │
│  │ 可信度 1-5   │─────────▶│ Step 2: 局限性分析  │───最终响应───▶│
│  │ 时效性 1-5   │          │ Step 3: 替代假设    │               │
│  │ 权威性 1-5   │          │ Step 5: 置信度评分  │               │
│  │ 一致性/冲突  │          └────────────────────┘               │
│  └──────────────┘                                                │
└─────────────────────────────────────────────────────────────────┘
  │
  ▼
Redis 缓存 (TTL 1h) + SQLite 历史记录 + DOCX 导出
```

**核心文件映射**：

| 阶段 | 文件 | 关键函数/类 |
|------|------|-----------|
| API 入口 | [`backend/api/query_routes.py`](backend/api/query_routes.py) | `query_system()` |
| ① 查询分析 | [`backend/services/query_analyzer.py`](backend/services/query_analyzer.py) | `analyze_query()` |
| ② 多集合检索 + ③ 去重过滤 | [`backend/services/query_service.py`](backend/services/query_service.py) | `retrieve_and_rank()` |
| ② 向量查询 | [`backend/services/vector_store_service.py`](backend/services/vector_store_service.py) | `VectorStoreService.query()` |
| ④ 重排序 | [`backend/services/reranker_service.py`](backend/services/reranker_service.py) | `RerankerService.rerank()` |
| ⑤ 证据评估 | [`backend/services/evidence_assessor_service.py`](backend/services/evidence_assessor_service.py) | `EvidenceAssessorService.assess_evidence()` |
| ⑥ 推理引擎 | [`backend/services/reasoning_engine_service.py`](backend/services/reasoning_engine_service.py) | `ReasoningEngineService.generate_reasoned_answer()` |
| LLM 调用 | [`backend/services/llm_service.py`](backend/services/llm_service.py) | `get_llm_response()` |
| 检索策略 | [`backend/config/retrieval_strategies.json`](backend/config/retrieval_strategies.json) | — |
| 缓存 | [`backend/core/cache.py`](backend/core/cache.py) | `redis_client` |
| 导出 | [`backend/services/query_export_service.py`](backend/services/query_export_service.py) | `QueryExportService.export_query_result_to_docx()` |

**LLM 模型分工**：

| 用途 | 模型 | 调用方 |
|------|------|--------|
| 查询分析 | `deepseek-chat` | `query_analyzer.py` |
| 证据评估 | `deepseek-chat` | `evidence_assessor_service.py` |
| 推理 Step 1–5 | `deepseek-chat` | `reasoning_engine_service.py` |
| 向量嵌入 | `BAAI/bge-large-en-v1.5` (本地) | `vector_store_service.py` |
| 重排序 | `BAAI/bge-reranker-base` (本地) | `reranker_service.py` |

> `deepseek-reasoner` 模型在问答管线中**不直接使用**——它被保留用于需要更强推理能力的其他功能（如实验设计）。所有问答 LLM 调用统一使用 `deepseek-chat`。

---

## 2. 第一阶段：查询分析与意图识别

**文件**：[`backend/services/query_analyzer.py`](backend/services/query_analyzer.py)
**函数**：`analyze_query(query: str) -> QueryAnalysisResult`

### 2.1 设计目的

原始用户查询往往是口语化的、模糊的、包含无关信息的。查询分析阶段将其转化为结构化的检索指令，为下游的**检索策略选择**提供依据。

### 2.2 输入输出

```
输入:  "transformer 里那个 Q、K、V 到底是怎么算的？跟 LSTM 比哪个好？"

输出:  QueryAnalysisResult(
           intent="comparison",                    # 比较类
           entities=["transformer", "QKV", "LSTM", "attention"],
           rewritten_query="How does the Q, K, V computation in Transformer attention compare to LSTM mechanisms?",
           complexity="moderate",
           domain="Computer Science"
       )
```

### 2.3 Pydantic 输出模型

```python
class QueryAnalysisResult(BaseModel):
    intent: Literal[
        "fact_checking",          # 事实核查：查找具体数据、数字、细节
        "conceptual_explanation", # 概念解释：解释概念、方法、理论
        "literature_review",      # 文献综述：研究主题的总结概述
        "comparison",             # 比较：对比两个或多个事物
        "other"                   # 其他
    ]

    entities: List[str]                     # 关键科学实体（化合物、方法、概念、设备）
    rewritten_query: str                    # 优化后的语义搜索查询（完整句子）
    complexity: Literal["simple", "moderate", "complex"]
    domain: Literal[
        "Computer Science", "Biology", "Chemistry",
        "Physics", "Medicine", "Engineering", "General/Interdisciplinary"
    ]
```

### 2.4 Domain 标准化

LLM 返回的 domain 可能不规范，`normalize_domain` validator 执行**两级标准化**：

```python
# 第一级：精确映射表
canonical_map = {
    "cs": "Computer Science",
    "bio": "Biology",
    "medical": "Medicine",
    # ...
}

# 第二级：子串启发式匹配（处理 LLM 自创的子领域名）
if "engineering" in s:       return "Engineering"    # "Environmental Engineering" → Engineering
if "biology" in s:           return "Biology"
if "chem" in s:              return "Chemistry"
if "physic" in s:            return "Physics"
if any(k in s for k in ["medicine", "medical", "clinical"]): return "Medicine"
```

### 2.5 容错机制

```python
# 三层容错
try:
    response_str = get_llm_response(prompt, use_reasoner=False)

    # ① 清理 markdown 代码块
    if "```json" in response_str:
        response_str = response_str.split("```json")[1].split("```")[0]

    # ② 先 json.loads → model_validate（容错解析）
    llm_json = json.loads(response_str)
    analysis_result = QueryAnalysisResult.model_validate(llm_json)

except (json.JSONDecodeError, ValidationError):
    # ③ 返回默认值（保证系统不崩溃）
    return QueryAnalysisResult(
        intent="other", entities=[],
        rewritten_query=query,
        complexity="moderate",
        domain="General/Interdisciplinary"
    )
```

### 2.6 本次 LLM 调用

| 属性 | 值 |
|------|-----|
| 模型 | `deepseek-chat` |
| 参数 | `use_reasoner=False` |
| `json_mode` | 未启用（通过 prompt 要求 JSON 格式） |
| `temperature` | 0.1（全局默认） |

---

## 3. 第二阶段：多集合检索

**文件**：[`backend/services/query_service.py`](backend/services/query_service.py) + [`backend/config/retrieval_strategies.json`](backend/config/retrieval_strategies.json)
**函数**：`retrieve_and_rank(query_text, intent, n_results)`

### 3.1 意图驱动的检索策略

检索策略不在代码中硬编码，而是配置在外部 JSON 文件中。

```json
{
    "fact_checking": [
        {"collection": "chunks", "multiplier": 5}
    ],
    "conceptual_explanation": [
        {"collection": "chunks", "multiplier": 4},
        {"collection": "chapter_summaries", "multiplier": 2}
    ],
    "literature_review": [
        {"collection": "summaries", "multiplier": 3},
        {"collection": "chapter_summaries", "multiplier": 3}
    ],
    "comparison": [
        {"collection": "chunks", "multiplier": 4},
        {"collection": "summaries", "multiplier": 2}
    ],
    "other": [
        {"collection": "chunks", "multiplier": 5},
        {"collection": "chapter_summaries", "multiplier": 2}
    ]
}
```

**策略设计哲学**：

| 意图 | 主检索集合 | 原因 |
|------|-----------|------|
| `fact_checking` | `chunks` ×5 | 事实藏在段落细节中，需要细粒度检索 |
| `conceptual_explanation` | `chunks` ×4 + `chapter_summaries` ×2 | 需要细节 + 章节级上下文 |
| `literature_review` | `summaries` ×3 + `chapter_summaries` ×3 | 综述需要宏观视角，摘要和章节总结更重要 |
| `comparison` | `chunks` ×4 + `summaries` ×2 | 既要细节对比，也要全局把握 |
| `other` | `chunks` ×5 + `chapter_summaries` ×2 | 默认偏向细节 |

### 3.2 检索数量计算

```python
# 给定 intent="conceptual_explanation", n_results=10
strategy = [
    {"name": "document_chunks",           "multiplier": 4},
    {"name": "document_chapter_summaries", "multiplier": 2},
]

collections_to_query = [
    {"name": "document_chunks",           "count": 10 * 4 = 40},
    {"name": "document_chapter_summaries", "count": 10 * 2 = 20},
]

# 总计召回 60 条候选，为后续去重和重排序提供充足的缓冲池
```

### 3.3 底层向量查询

```python
# VectorStoreService.query()
def query(self, query_text, n_results, collection_name):
    # ① 嵌入查询文本
    query_embedding = self.embedding_model.encode(query_text).tolist()

    # ② 检索 n_results * 2 条（内置去重缓冲）
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results * 2,       # 双倍召回
        include=["documents", "metadatas", "distances"]
    )

    # ③ 内容去重（同文档不同块的重复内容）
    unique_docs, unique_metadatas = [], []
    seen_docs = set()
    for doc, meta in zip(raw_docs, raw_metadatas):
        if doc not in seen_docs:
            unique_docs.append(doc)
            unique_metadatas.append(meta)
            seen_docs.add(doc)
        if len(unique_docs) >= n_results:  # 够了就停
            break

    return {"documents": [unique_docs], "metadatas": [unique_metadatas], ...}
```

**双倍召回 + 去重截断**：先取 `n_results * 2`，去重后截断至 `n_results`。这样即使部分内容重复，也能保证召回足够的**独特**文档。

---

## 4. 第三阶段：去重与过滤

**位置**：[`backend/services/query_service.py`](backend/services/query_service.py) 第 46–167 行（`retrieve_and_rank` 函数内部）

### 4.1 参考文献内容过滤

多集合检索完成后，并非所有召回内容都适合喂给 LLM。参考文献列表、致谢等噪声内容会被过滤。

**检测规则**（`is_reference_like` 函数）：

```python
def is_reference_like(meta, text):
    # 规则 1: 章节标题匹配
    ref_title_pattern = re.compile(
        r'^(references?|bibliography|acknowledgements?|acknowledgments?)\b',
        re.IGNORECASE
    )
    if ref_title_pattern.match(meta.get('title_h1', '').strip()):
        return True

    # 规则 2: 高密度学术引用指示词
    indicators = 0
    lower = text.lower()
    indicators += 1 if doi_pattern.search(text) else 0
    for token in ('vol.', 'pp.', 'journal', 'proceedings', 'http://', 'https://'):
        if token in lower:
            indicators += 1
    if indicators >= 2:      # 同时出现 ≥2 个指示词
        return True

    # 规则 3: 作者-年份格式开头
    author_year_dense_pattern = re.compile(
        r'^[\[\(]?\d+?[\]\)]?\s*[A-Z][a-z]+,\s*[A-Z]\.(?:,\s*[A-Z]\.)?\s*\(\d{4}\)'
    )
    if author_year_dense_pattern.search(text):
        return True

    return False
```

> 这个过滤在**每条候选文档**被加入 `all_candidates` 前执行，避免噪声内容进入后续重排序和 LLM 上下文。

### 4.2 来源级去重与上限控制

```python
# Step 1: 按 source 分组
by_source: Dict[str, List[Dict]] = {}
for cand in all_candidates:
    by_source.setdefault(cand["source"], []).append(cand)

# Step 2: 每源按 distance 排序，取 top-3
MAX_SNIPPETS_PER_SOURCE = 3
limited_candidates = []
for src, group in by_source.items():
    sorted_group = sorted(group, key=lambda x: x.get("distance", float("inf")))
    limited_candidates.extend(sorted_group[:MAX_SNIPPETS_PER_SOURCE])
```

**设计理由**：防止某一篇长文档的多个块垄断检索结果。即使一篇论文有 20 个段落相关，也只取其中最匹配的 3 段。

---

## 5. 第四阶段：Cross-Encoder 重排序

**文件**：[`backend/services/reranker_service.py`](backend/services/reranker_service.py)
**模型**：`BAAI/bge-reranker-base`（CrossEncoder）

### 5.1 为什么需要重排序

第一阶段使用 **Bi-Encoder**（SentenceTransformer）做嵌入检索，它的优势是速度快（向量可预计算），但精度有限——它独立编码 query 和 document，缺乏 token 级的交互。

**Cross-Encoder** 将 `[query, document]` 拼接后同时编码，能捕获细粒度的语义交互，但计算成本高（无法预计算）。因此采用两阶段策略：

```
Bi-Encoder (SentenceTransformer)    → 粗排，召回 60 条候选
    ↓ 去重过滤 → ~30 条
Cross-Encoder (BGE-Reranker)        → 精排，重打分排序
    ↓ 取 Top-K
最终 10 条结果
```

### 5.2 实现细节

```python
class RerankerService:
    def __init__(self):
        self.model = CrossEncoder(
            settings.CROSS_ENCODER_MODEL_NAME,  # "BAAI/bge-reranker-base"
            max_length=512,                      # 输入截断长度
            local_files_only=True               # 优先本地缓存
        )

    def rerank(self, query, documents):
        # 构建 [query, doc_content] 配对
        doc_contents = [(doc.get("text") or doc.get("content", ""))
                        for doc in documents]
        model_input = [[query, content] for content in doc_contents]

        # 批量预测（单次前向传播）
        scores = self.model.predict(model_input)

        # 注入分数并按降序排列
        for doc, score in zip(documents, scores):
            doc["rerank_score"] = float(score)

        return sorted(documents, key=lambda x: x["rerank_score"], reverse=True)
```

| 属性 | 值 |
|------|-----|
| 模型 | `BAAI/bge-reranker-base` |
| 最大输入长度 | 512 tokens |
| 输出 | 相关性分数（浮点数） |
| 运行方式 | 本地 CPU/GPU 推理 |

---

## 6. 第五阶段：证据质量与一致性评估

**文件**：[`backend/services/evidence_assessor_service.py`](backend/services/evidence_assessor_service.py)
**类**：`EvidenceAssessorService`

### 6.1 评估维度

每条证据（重排序后的 Top-10 文档）在 4 个维度上被 LLM 评分：

```
Source Quality Assessment
├── relevance:       1-5  （内容与查询的相关性）
├── trustworthiness: 1-5  （内容可信度与事实准确性）
├── timeliness:      1-5  （基于出版年份的时效性，5=很新，1=很旧）
└── authority:       1-5  （来源权威性，顶刊 vs 预印本）
```

### 6.2 上下文构建

评估时，多条证据按**来源**合并分组（与第三阶段的按 source 分组逻辑一致）：

```python
# 按 source 分组（每源最多 3 条 snippet）
grouped: Dict[str, List[Dict]] = {}
for d in documents:
    key = normalize(d)  # source → doi → document_id → title → 'Unknown'
    grouped.setdefault(key, []).append(d)

# 每个 source 构建一个 Source_N 块
for i, (source_key, group_docs) in enumerate(grouped.items(), 1):
    context_parts.append(f"""
--- Source_{i} ---
Content Snippets (merged):
{merged_snippets}
Metadata:
  - Publication Year: {pub_year}
  - Source Venue: {journal}
  - Authors: {authors}
""")
```

**独源特殊处理**：

```python
# 如果只有 1 个来源，覆盖一致性总结
if src_count <= 1:
    assessment.overall_consistency_summary = (
        "Only a single source was assessed; "
        "cross-source consistency cannot be determined."
    )
```

### 6.3 Pydantic 输出模型

```python
class SourceQuality(BaseModel):
    source_id: str                              # "Source_1"
    relevance: int = Field(..., ge=1, le=5)
    trustworthiness: int = Field(..., ge=1, le=5)
    timeliness: int = Field(..., ge=1, le=5)
    authority: int = Field(..., ge=1, le=5)
    justification: str                          # 评分理由

class EvidenceAssessment(BaseModel):
    overall_consistency_summary: str            # 总体一致性
    consistent_points: List[str]                # 多源支持的观点
    conflicting_points: List[str]               # 来源间冲突
    source_quality_assessments: List[SourceQuality]
```

### 6.4 本次 LLM 调用

| 属性 | 值 |
|------|-----|
| 模型 | `deepseek-chat` |
| `json_mode` | `True`（`response_format={"type": "json_object"}`） |
| `use_reasoner` | `False` |

---

## 7. 第六阶段：链式推理引擎

**文件**：[`backend/services/reasoning_engine_service.py`](backend/services/reasoning_engine_service.py)
**类**：`ReasoningEngineService`

这是整个 RAG 管线的**核心输出阶段**，采用四步链式推理（Chain-of-Thought）。

### 7.1 上下文格式化与引用索引

在推理开始前，证据被格式化为带 `Source_N` 标签的上下文块，同时建立**引用索引表**：

```python
def _format_context(self, evidence):
    # 按 source 分组 → Source_1, Source_2, ...
    for i, (source_key, docs) in enumerate(grouped_docs.items(), 1):
        # 每源 ≤ 3 snippets, 每个 ≤ 1000 字符
        context_parts.append(f"--- Source_{i} ({source_file}) ---\n{merged}\n")

        # 构建引用索引
        citation_index.append({
            "source_id": f"Source_{i}",
            "source_file": source_file,
            "doi": doi,
            "document_id": document_id,
            "title": title,
            "pages": [4, 5, 6]      # 去重排序后的页码列表
        })

    return {"context_str": ..., "citation_index": citation_index}
```

引用索引在 API 层被用于**反向映射**，让前端能将 LLM 生成的 `[Source_3, Page 4]` 标记链接回具体的文档 ID：

```python
# query_routes.py 第 114-118 行
citation_index = reasoned_answer.get("citation_index") or []
srcfile_to_id = {entry.get("source_file"): entry.get("source_id")
                 for entry in citation_index}
for item in ranked_results:
    item["source_id"] = srcfile_to_id.get(item.get("source"))
```

### 7.2 四步推理链

```
Step 1: 综合答案          Step 2: 局限性分析
┌──────────────────┐     ┌─────────────────────┐
│ 基于证据合成答案   │────▶│ 证据缺口？偏见？     │
│ 强制要求引用格式   │     │ 来源多样性不足？     │
│ [Source_N, Page X]│     │ 不能得出什么结论？   │
└──────────────────┘     └─────────────────────┘
                                    │
                                    ▼
                          Step 3: 替代假设
                          ┌─────────────────────┐
                          │ 是否有其他解释？     │
                          │ 替代假说 1-2 条      │
                          └─────────────────────┘
                                    │
                                    ▼
                          Step 5: 置信度评分
                          ┌─────────────────────┐
                          │ 综合答案 + 局限性    │
                          │ → 0.0 ~ 1.0        │
                          └─────────────────────┘
```

> **Step 4 被移除**：原设计中有一个"知识图谱增强"步骤，代码注释标注为 `# Temporary knowledge graph feature removed`。

#### Step 1: 综合答案（`_step_1_synthesize_answer`）

```python
prompt = '''
You are an expert scientific analyst.
Based ONLY on the provided evidence,
construct a comprehensive and neutral answer to the user's query.

You MUST cite the sources you use for each piece of information
with source ID AND page numbers when available.
Use this format:
  [Source_1, Page 3]
  [Source_1, Pages 3–4]           for a range of pages
  [Source_1, Page 3; Source_2, Page 5]  for multiple sources

USER QUERY: "{query}"
PROVIDED EVIDENCE:
{context_str}

Synthesized Answer:
'''
```

**强制引用格式**：prompt 明确要求 `[Source_N, Page X]` 格式的 inline citation，后端通过 `citation_index` 反向映射到具体文档 ID。

#### Step 2: 局限性分析（`_step_2_analyze_limitations`）

```python
# 输入：query + context + Step 1 的答案
prompt = '''
You are a critical reviewer.
Consider:
- Does the evidence fully answer the query?
- Are there gaps, biases, or a lack of diversity in the sources?
- What cannot be concluded?

Limitations Analysis:
'''
```

#### Step 3: 替代假设（`_step_3_propose_alternatives`）

```python
# 输入：仅 Step 2 的局限性分析
prompt = '''
Based on the following limitations analysis,
suggest one or two plausible alternative hypotheses or explanations.
If the analysis indicates no room for alternatives, return an empty list.

Respond with a JSON object:
{"alternative_hypotheses": ["<hypothesis_1>", "<hypothesis_2>"]}
'''

# json_mode=True，确保输出合法 JSON
response = get_llm_response(prompt, json_mode=True, use_reasoner=False)
return json.loads(response).get("alternative_hypotheses", [])
```

#### Step 5: 置信度评分（`_step_5_evaluate_confidence`）

```python
prompt = '''
Given the synthesized answer and its limitations analysis,
provide a confidence score between 0.0 and 1.0.

A high score (e.g., 0.9) = well-supported, few limitations.
A low score (e.g., 0.4) = significant limitations.

Respond with: {"confidence_score": <float>}
'''
```

**置信度计算依据**：LLM 综合衡量证据充分性（Step 1 的引用密度）和局限性严重程度（Step 2 的缺口数量），而非单纯的检索分数。

### 7.3 最终的 ReasonedAnswer 结构

```python
ReasonedAnswer(
    synthesized_answer="The Transformer attention mechanism computes... [Source_1, Page 3]",
    limitations_analysis="The evidence primarily covers the original 2017 paper...",
    alternative_hypotheses=[
        "Linear attention mechanisms may offer comparable performance...",
        "The effectiveness may be task-dependent rather than universal..."
    ],
    confidence_score=0.82
)
```

### 7.4 本阶段 LLM 调用汇总

| 步骤 | 模型 | json_mode | 输入 |
|------|------|-----------|------|
| Step 1 | `deepseek-chat` | False | query + 全部证据 |
| Step 2 | `deepseek-chat` | False | query + 证据 + Step 1 答案 |
| Step 3 | `deepseek-chat` | True | Step 2 局限性分析 |
| Step 5 | `deepseek-chat` | True | 答案 + 局限性 |

> 整个推理链共 **4 次 LLM 调用**。Step 2 必须等 Step 1 完成后才能执行（依赖其答案），Step 3 必须等 Step 2。因此这三次调用是串行的。理论上 Step 5 可以和 Step 3 并行（两者都只依赖 Step 2 的输出），但当前实现也是串行的。

---

## 8. 缓存策略

**文件**：[`backend/api/query_routes.py`](backend/api/query_routes.py) 第 40–53 行

### 8.1 缓存键设计

```python
# 基于 (user_id + query_text) 的 SHA-256 哈希
query_hash = hashlib.sha256(
    f"{current_user.id}:{query}".encode('utf-8')
).hexdigest()
cache_key = f"cache:query:{query_hash}"
```

**为什么包含 user_id？** 不同用户的知识库不同（虽然当前版本文档是全局共享的，但设计上预留了用户隔离）。

### 8.2 缓存流程

```
POST /api/query/
  │
  ├── 计算 cache_key = f"cache:query:{sha256(user_id:query)}"
  │
  ├── Redis GET cache_key
  │     │
  │     ├── 命中 → 直接返回 ✅（跳过全部 6 个阶段）
  │     │
  │     └── 未命中 → 执行完整管线
  │                    │
  │                    ├── 成功 → Redis SETEX cache_key 3600 秒
  │                    │          → 返回结果
  │                    │
  │                    └── 异常 → 不缓存错误 ❌
  │                              → HTTP 500
  └──
```

**关键设计决策**：

| 决策 | 理由 |
|------|------|
| TTL = 3600 秒（1 小时） | 平衡缓存命中率与结果新鲜度 |
| 不缓存"未找到"结果 | 实际代码中**会缓存**——`ranked_results` 为空时也会写入缓存。这样相同问题不会重复触发全管线 |
| 不缓存错误 | 避免缓存失效错误信息导致持续的 500 响应 |
| 缓存前缀 `cache:query:` | Redis 命名空间隔离，方便批量清除和监控 |

---

## 9. 查询历史持久化

**文件**：[`backend/api/query_routes.py`](backend/api/query_routes.py) + [`backend/models/query_history.py`](backend/models/query_history.py)

```python
# 每次查询结束后写入 SQLite
history_entry = QueryHistory(
    user_id=current_user.id,
    query_text=query,
    query_metadata={
        "query_analysis": query_analysis.model_dump(),
        "num_results": len(ranked_results),
        "context_count": len(ranked_results),
    },
    result_payload=final_response    # 完整响应 JSON
)
db.add(history_entry)
db.commit()
```

**数据结构**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `user_id` | INTEGER FK | 用户外键 |
| `query_text` | TEXT | 原始查询 |
| `created_at` | DATETIME | 创建时间（UTC，服务端默认） |
| `query_metadata` | JSON | 查询分析摘要（意图、实体、结果数） |
| `result_payload` | JSON | **完整响应负载**（含答案、评估、上下文） |

**时区处理**：返回给前端时转换为 `Asia/Shanghai`（UTC+8）：

```python
def _to_shanghai_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo('Asia/Shanghai')).isoformat()
```

**API 端点**：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/query/history` | 当前用户的查询历史（按时间倒序） |
| `DELETE` | `/api/query/history/{id}` | 删除指定历史（含权限校验：user_id 匹配） |

---

## 10. DOCX 导出

**文件**：[`backend/services/query_export_service.py`](backend/services/query_export_service.py)
**端点**：`POST /api/query/download`

### 10.1 导出内容结构

```
┌─────────────────────────────────┐
│  Smart Q&A Result               │  ← 一级标题
│  Query: <原始问题>               │
├─────────────────────────────────┤
│  Synthesized Answer             │  ← 综合答案（含 [Source_N] 引用）
├─────────────────────────────────┤
│  Confidence Score               │  ← 0.0 ~ 1.0
├─────────────────────────────────┤
│  Limitations                    │  ← 局限性分析
├─────────────────────────────────┤
│  Alternative Hypotheses         │  ← 替代假说列表
├─────────────────────────────────┤
│  Query Analysis                 │
│  - Intent, Complexity, Domain   │
│  - Rewritten Query, Entities    │
├─────────────────────────────────┤
│  Evidence Assessment            │
│  - Overall Summary              │
│  - Consistent Points            │
│  - Conflicting Points           │
│  - Quality per Source           │
│    (Relevance/Trustworthiness/  │
│     Timeliness/Authority/       │
│     Justification)              │
├─────────────────────────────────┤
│  Retrieved Context              │
│  - [Source_N, Title, Page]      │
│    Content snippet (≤1000 chars)│
└─────────────────────────────────┘
```

### 10.2 引用对齐

导出时，`context` 中的每条记录需要与 `citation_index` 对齐，确保显示的 `Source_N` 标签与推理答案中的引用一致：

```python
citation_index = data.get('reasoned_answer', {}).get('citation_index', [])
srcfile_to_id = {
    entry.get('source_file'): entry.get('source_id')
    for entry in citation_index
}

for item in context_items:
    file = item['metadata'].get('source', 'Unknown')
    source_id = item.get('source_id') or srcfile_to_id.get(file) or 'Source_?'
    doc.add_paragraph(f"[{source_id}, {title}, Page {page}] {content[:1000]}")
```

### 10.3 请求方式

```python
@router.post("/query/download")
async def download_query_result_docx(
    payload: dict = Body(...)  # {"query_text": "...", "result_payload": {...}}
):
    doc = query_export_service.export_query_result_to_docx(result_payload, query_text)
    return StreamingResponse(
        io.BytesIO(doc_bytes),
        media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': 'attachment; filename=smart_qa_result.docx'}
    )
```

> 导出不走缓存也不写历史——它接受前端已有的 `result_payload`，纯粹做格式转换。

---

## 11. 完整调用链路图

```
用户输入问题: "transformer 注意力机制如何工作？"
    │
    ▼
POST /api/query/                                  [query_routes.py:30]
    │
    ├── ① 尝试 Redis 缓存
    │     cache_key = f"cache:query:{sha256(user_id:query)}"
    │     命中? → 直接返回 JSON ✅
    │
    └── (未命中) 启动六阶段管线:

    ┌────────────────────────────────────────────────────────────┐
    │                                                            │
    │  ① analyze_query(query)                    [query_analyzer.py:77]
    │     ├── LLM (deepseek-chat) 分析
    │     ├── intent: 意图分类 (5 种)
    │     ├── entities: 实体提取
    │     ├── rewritten_query: 查询改写
    │     ├── complexity: 复杂度评估
    │     ├── domain: 领域分类 (7 类，含标准化)
    │     └── → QueryAnalysisResult (Pydantic 校验)
    │                                                            │
    │  ② retrieve_and_rank(rewritten_query, intent, n_results=10)
    │                              [query_service.py:46]
    │     │
    │     ├── 加载检索策略 (retrieval_strategies.json)
    │     │   例: "conceptual_explanation"
    │     │       → chunks×40 + chapter_summaries×20
    │     │
    │     ├── 遍历 collections_to_query:
    │     │   │
    │     │   ├── vector_store.query("document_chunks", 40)
    │     │   │   [vector_store_service.py:92]
    │     │   │   ├── embedding_model.encode(query)
    │     │   │   ├── collection.query(n_results=80)  # 双倍
    │     │   │   └── 去重截断 → 40 条独特文档
    │     │   │
    │     │   └── vector_store.query("document_chapter_summaries", 20)
    │     │
    │     ├── ③ 过滤 is_reference_like() + 每源 ≤ 3 条
    │     │      → limited_candidates (~20-30 条)
    │     │
    │     └── ④ reranker_service.rerank(query, limited_candidates)
    │          [reranker_service.py:33]
    │          ├── CrossEncoder.predict([[query, doc1], ...])
    │          ├── 注入 rerank_score
    │          └── 降序排列，取 Top-10
    │                                                            │
    │  ⑤ evidence_assessor_service.assess_evidence(query, top10)
    │                              [evidence_assessor_service.py:30]
    │     ├── 按 source 分组 (Source_1, Source_2, ...)
    │     ├── 每源 ≤ 3 snippets × ≤ 1000 chars
    │     ├── LLM (deepseek-chat, json_mode=True) 评分:
    │     │   ├── relevance: 1-5
    │     │   ├── trustworthiness: 1-5
    │     │   ├── timeliness: 1-5
    │     │   ├── authority: 1-5
    │     │   ├── consistent_points: [...]
    │     │   └── conflicting_points: [...]
    │     ├── Pydantic 校验 (EvidenceAssessment)
    │     └── 单源特殊处理: 覆盖一致性总结
    │                                                            │
    │  ⑥ reasoning_engine_service.generate_reasoned_answer(query, top10)
    │                              [reasoning_engine_service.py:163]
    │     │
    │     ├── _format_context() → context_str + citation_index
    │     │
    │     ├── Step 1: _step_1_synthesize_answer()
    │     │   LLM → 综合答案 (强制 [Source_N, Page X] 引用)
    │     │
    │     ├── Step 2: _step_2_analyze_limitations()
    │     │   LLM → 局限性分析 (证据缺口、偏见、多样性)
    │     │
    │     ├── Step 3: _step_3_propose_alternatives()
    │     │   LLM (json_mode=True) → 替代假说列表
    │     │
    │     └── Step 5: _step_5_evaluate_confidence()
    │         LLM (json_mode=True) → 置信度 0.0-1.0
    │                                                            │
    └────────────────────────────────────────────────────────────┘
    │
    ├── 对齐引用: citation_index → ranked_results.source_id
    │
    ├── 组装 FinalResponse:
    │     {
    │       reasoned_answer: { result: {...}, citation_index: [...], ... },
    │       query_analysis: { intent, entities, ... },
    │       assessment: { assessment: {...}, ... },
    │       context: [ { source_id, ... }, ... ]
    │     }
    │
    ├── validate_final_response() → 规范化 citation_index.pages
    │
    ├── Redis SETEX cache_key 3600 → 写入缓存
    │
    ├── QueryHistory → SQLite 持久化
    │
    └── 返回 JSON 给前端
```

### 11.1 LLM 调用次数统计

| 阶段 | 调用次数 | 模型 | json_mode |
|------|---------|------|-----------|
| 查询分析 | 1 | `deepseek-chat` | False |
| 证据评估 | 1 | `deepseek-chat` | True |
| 推理 Step 1 | 1 | `deepseek-chat` | False |
| 推理 Step 2 | 1 | `deepseek-chat` | False |
| 推理 Step 3 | 1 | `deepseek-chat` | True |
| 推理 Step 5 | 1 | `deepseek-chat` | True |
| **总计** | **6** | — | — |

---

## 12. 附录：配置参数速查

| 参数 | 默认值 | 影响阶段 | 说明 |
|------|--------|---------|------|
| `RAG_QUERY_TOP_K` | 10 | ② 检索 | 最终返回的文档数 |
| `EMBEDDING_MODEL_NAME` | `BAAI/bge-large-en-v1.5` | ② 检索 | 嵌入模型 |
| `CROSS_ENCODER_MODEL_NAME` | `BAAI/bge-reranker-base` | ④ 重排序 | Cross-Encoder 模型 |
| `CACHE_EXPIRATION_SECONDS` | 3600 | 缓存 | 查询结果缓存 TTL |
| `CHUNKS_COLLECTION_NAME` | `document_chunks` | ② 检索 | 段落块集合 |
| `SUMMARIES_COLLECTION_NAME` | `document_summaries` | ② 检索 | 全文摘要集合 |
| `CHAPTER_SUMMARIES_COLLECTION_NAME` | `document_chapter_summaries` | ② 检索 | 章节摘要集合 |
| `MAX_SNIPPETS_PER_SOURCE` | 3 | ③ 过滤 | 每源最大段落数 |
| CrossEncoder `max_length` | 512 | ④ 重排序 | 输入 token 截断 |

### 12.1 检索策略配置

[`backend/config/retrieval_strategies.json`](backend/config/retrieval_strategies.json)：

| 意图 | 集合 × 倍数 | 有效召回量 (n=10) |
|------|-------------|-------------------|
| `fact_checking` | chunks ×5 | 50 |
| `conceptual_explanation` | chunks ×4, chapter_summaries ×2 | 40 + 20 = 60 |
| `literature_review` | summaries ×3, chapter_summaries ×3 | 30 + 30 = 60 |
| `comparison` | chunks ×4, summaries ×2 | 40 + 20 = 60 |
| `other` | chunks ×5, chapter_summaries ×2 | 50 + 20 = 70 |

### 12.2 意图 → 检索策略推理

```
fact_checking:
  → 需要段落级细节 → chunks 主导
  → 不需要宏观摘要 → 仅 chunks

literature_review:
  → 需要宏观视角 → summaries + chapter_summaries
  → 不需要段落细节 → 不检索 chunks

conceptual_explanation:
  → 细节 + 上下文都需要 → chunks + chapter_summaries

comparison:
  → 细节对比 + 整体把握 → chunks + summaries
```

---

## 附录：错误处理的工程考量

整个 RAG 管线中每个 LLM 调用都有独立的重试机制（3 次，指数退避）。但各阶段的**失败容忍度**不同：

| 阶段 | 失败行为 | 理由 |
|------|---------|------|
| 查询分析 | 返回默认 `QueryAnalysisResult` | 保证检索可继续 |
| 检索 | 空结果返回"未找到"响应 | 诚实告知用户 |
| 证据评估 | 返回 `{"assessment_successful": False, "error": "..."}` | 推理仍可继续 |
| 推理引擎 | 返回 `{"reasoning_successful": False, "error": "..."}` | 整个问答的核心失败 |
| LLM 通用 | 3 次重试后抛出异常 → HTTP 500 | 不可恢复 |

这种**渐进式降级**设计确保即使某些辅助分析失败，核心的问答功能仍能给出部分结果。
