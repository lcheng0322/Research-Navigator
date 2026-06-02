# 实验设计模块完整实现详解

> 本文档深入解析 Research Navigator 的交互式实验设计功能——一个三步同步流程，采用 Critic-Refiner 双代理模式，从研究主题到完整的实验方案并支持专家审查优化。

---

## 目录

1. [架构总览](#1-架构总览)
2. [前端交互设计](#2-前端交互设计)
3. [Pydantic 数据模型](#3-pydantic-数据模型)
4. [第一步：创建会话与假设生成](#4-第一步创建会话与假设生成)
5. [第二步：生成完整实验方案](#5-第二步生成完整实验方案)
6. [第三步：Critic-Refiner 双代理优化](#6-第三步critic-refiner-双代理优化)
7. [会话状态管理](#7-会话状态管理)
8. [DOCX 导出](#8-docx-导出)
9. [完整调用链路图](#9-完整调用链路图)
10. [附录：与其他模块的对比](#10-附录与其他模块的对比)

---

## 1. 架构总览

```
用户浏览器
  │
  ├── Step 1: POST /api/experiments
  │     { research_topic, variables?, constraints? }
  │     → 同步返回 { session_id, hypothesis }
  │
  ├── Step 2: POST /api/experiments/{session_id}/design
  │     → 同步返回 ExperimentDesign (9 字段完整方案)
  │
  ├── Step 3: POST /api/experiments/{session_id}/refine
  │     → Critic agent 审查 → Refiner agent 改进
  │     → 同步返回 优化后的 ExperimentDesign
  │
  └── Export: GET /api/experiments/{session_id}/download
        → DOCX 文件下载
```

**核心文件映射**：

| 层 | 文件 | 职责 |
|----|------|------|
| API 路由 | [`backend/api/analysis_routes.py`](backend/api/analysis_routes.py) 第 195–244 行 | 4 个端点（create / design / refine / download） |
| 数据模型 | [`backend/schemas/experiment_schemas.py`](backend/schemas/experiment_schemas.py) | 7 个 Pydantic 模型 |
| 业务逻辑 | [`backend/services/experiment_designer_service.py`](backend/services/experiment_designer_service.py) | 上下文检索 + 假设生成 + 方案生成 + 审查优化 + DOCX |
| 前端页面 | [`frontend/src/pages/ExperimentDesignPage.tsx`](frontend/src/pages/ExperimentDesignPage.tsx) | 三步向导 + 方案渲染 + 步骤表格 |

**本模块与其他模块的关键区别**：

| 维度 | 文献综述 | 研究空白分析 | **实验设计** |
|------|---------|------------|------------|
| 执行方式 | 异步 (Celery) | 异步 (Celery) | **同步** |
| 状态存储 | Redis 缓存 | Redis 缓存 | **服务器内存** |
| 步骤数 | 3 步 | 1 步 | **3 步 (可迭代)** |
| 代理模式 | 单代理 | 单代理 | **Critic-Refiner 双代理** |
| LLM 模型 | reasoner | reasoner | **chat** |

---

## 2. 前端交互设计

**文件**：[`frontend/src/pages/ExperimentDesignPage.tsx`](frontend/src/pages/ExperimentDesignPage.tsx)

### 2.1 三步向导

```
┌──────────────────────────────────────────────────────────────┐
│  Step 0: Define Topic    Step 1: Review Hypothesis           │
│  ┌────────────────────┐  ┌──────────────────────────────┐    │
│  │ Research Topic:    │  │ Generated Hypothesis:         │    │
│  │ [_______________]  │  │ "Caffeine at 200mg...         │    │
│  │                    │  │  will significantly improve   │    │
│  │ [Start Design      │  │  short-term memory recall..." │    │
│  │  Session]          │  │                               │    │
│  └────────────────────┘  │ Justification from KB:        │    │
│           │              │ "Studies show caffeine...     │    │
│           ▼              │  affects cognitive..."        │    │
│                          │                               │    │
│                          │ [Start Over] [Generate Full]  │    │
│                          └──────────────────────────────┘    │
│                                        │                     │
│                                        ▼                     │
│                          Step 2: Review and Refine Design    │
│                          ┌──────────────────────────────┐    │
│                          │ Title: "The Effect of..."    │    │
│                          │ Hypothesis: ...              │    │
│                          │ Methodology: ...             │    │
│                          │ ┌────────────────────────┐   │    │
│                          │ │ Materials & Groups     │   │    │
│                          │ │ Control: ...           │   │    │
│                          │ │ Experimental: ...      │   │    │
│                          │ │ [tag][tag][tag]        │   │    │
│                          │ └────────────────────────┘   │    │
│                          │ ┌────────────────────────┐   │    │
│                          │ │ Detailed Steps         │   │    │
│                          │ │ Step │ Desc │ Materials│   │    │
│                          │ │  1   │ ...  │ [tag]   │   │    │
│                          │ │  2   │ ...  │ [tag]   │   │    │
│                          │ └────────────────────────┘   │    │
│                          │ Data Analysis Plan: ...      │    │
│                          │ Potential Risks: ...         │    │
│                          │                              │    │
│                          │ ┌────────────────────────┐   │    │
│                          │ │ Refined Design         │   │    │
│                          │ │ (优化后的完整方案)      │   │    │
│                          │ └────────────────────────┘   │    │
│                          │                              │    │
│                          │ [Start Over]                 │    │
│                          │ [Review & Refine] [Download] │    │
│                          └──────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 关键交互限制

**Refine 只能执行一次**：

```typescript
<Button
  theme="primary"
  variant="outline"
  onClick={handleRefineDesign}
  loading={isLoading}
  disabled={!!refinedDesign}  // ← 已优化则禁用
>
  Review & Refine with AI Critic
</Button>
```

一旦 `refinedDesign` 有值，按钮即被禁用。这意味着用户不能多次迭代优化——如果想再次优化，只能点击 "Start Over" 重新开始。

### 2.3 状态管理

```
sessionId ────────────────→ 所有后续操作的凭证
researchTopic ─────────────→ 用户输入（用于重置 + DOCX 文件名）
initialHypothesis ─────────→ Step 1 展示
fullDesign ────────────────→ Step 2 展示（原始方案）
refinedDesign ─────────────→ Step 2 展示（优化后的方案，覆盖显示在下方）
```

---

## 3. Pydantic 数据模型

**文件**：[`backend/schemas/experiment_schemas.py`](backend/schemas/experiment_schemas.py)

本模块是整个项目中 **Pydantic 模型最多、嵌套最深** 的模块：

```
ExperimentDesignRequest          # 用户输入
    ├── research_topic: str
    ├── variables: List[str]?    # 可选，自由文本
    └── constraints: List[str]?  # 可选，自由文本

Hypothesis                       # 初步假设
    ├── hypothesis_text: str     # 可检验的假设
    └── context_summary: str     # 知识库依据的一句话摘要

ExperimentDesign                 # 完整实验方案（核心模型，9 个字段）
    ├── title: str
    ├── hypothesis: str
    ├── methodology: str
    ├── materials: List[str]
    ├── control_group: str
    ├── experimental_group: str
    ├── steps: List[ExperimentStep]
    │     └── ExperimentStep
    │           ├── step_number: int
    │           ├── description: str
    │           └── materials_needed: List[str]?
    ├── data_analysis_plan: str
    └── potential_risks: str?

Critique                         # 审查意见
    ├── potential_flaws: List[str]
    └── suggested_improvements: List[str]

DesignSession                    # 会话状态（服务器内存）
    ├── session_id: str (UUID4)
    ├── status: "hypothesis_generated" | "design_completed"
    ├── request: ExperimentDesignRequest
    ├── retrieved_context: str
    ├── hypothesis: Hypothesis
    └── final_design: ExperimentDesign?

CreateSessionResponse            # Step 1 响应
    ├── session_id: str
    └── hypothesis: Hypothesis
```

### 3.1 模型层级关系图

```
用户输入                    LLM 生成
ExperimentDesignRequest ──→ Hypothesis (Step 1)
                                    │
                                    ▼
                            ExperimentDesign (Step 2)
                            ┌─────────────────────┐
                            │ title               │
                            │ hypothesis          │
                            │ methodology         │
                            │ materials[]         │
                            │ control_group       │
                            │ experimental_group  │
                            │ steps[]             │
                            │  ├── ExperimentStep │
                            │  │   ├── step_number│
                            │  │   ├── description│
                            │  │   └── materials  │
                            │ data_analysis_plan  │
                            │ potential_risks     │
                            └─────────────────────┘
                                    │
                            Critique (Step 3a: Critic)
                            ┌─────────────────────┐
                            │ potential_flaws[]   │
                            │ suggested_          │
                            │   improvements[]    │
                            └─────────────────────┘
                                    │
                                    ▼
                            ExperimentDesign (Step 3b: Refiner)
                            (同结构，内容优化)
```

---

## 4. 第一步：创建会话与假设生成

**端点**：`POST /api/experiments`
**文件**：[`backend/api/analysis_routes.py`](backend/api/analysis_routes.py) 第 196–201 行
**方法**：`ExperimentDesignerService.create_session()`

### 4.1 请求与响应

```
请求:  POST /api/experiments
       {
         "research_topic": "The effect of caffeine on short-term memory recall in college students",
         "variables": ["caffeine dosage", "memory test type"],
         "constraints": ["Must use non-invasive methods"]
       }

响应:  {
         "session_id": "a1b2c3d4-...",
         "hypothesis": {
           "hypothesis_text": "Administration of 200mg caffeine...",
           "context_summary": "Previous studies indicate caffeine's role as an adenosine receptor antagonist..."
         }
       }
```

### 4.2 处理流程

```
create_session(request)
  │
  ├── ① 上下文检索: _retrieve_context(topic)
  │     │
  │     ├── vector_store.query(
  │     │     query_text=request.research_topic,
  │     │     n_results=5,
  │     │     collection_name="document_chunks"   ← 只查段落块
  │     │   )
  │     │
  │     └── _format_context() → 结构化上下文:
  │           """
  │           Relevant information from the knowledge base:
  │           
  │           --- Context 1 (Source: caffeine_study.pdf, Page: 3) ---
  │           Caffeine is a central nervous system stimulant...
  │           
  │           --- Context 2 (Source: memory_review.pdf, Page: 12) ---
  │           Short-term memory recall can be measured using...
  │           """
  │
  ├── ② LLM 假设生成
  │     prompt = f'''
  │       Based on the following research topic and context
  │       from a knowledge base, formulate a clear, testable
  │       research hypothesis and a brief summary of the
  │       context that informed it.
  │       
  │       Research Topic: {request.research_topic}
  │       Relevant Context: {formatted_context}
  │       
  │       Return a JSON object:
  │       {{
  │         "hypothesis_text": "...",
  │         "context_summary": "..."
  │       }}
  │     '''
  │     
  │     response = get_llm_response(prompt,
  │                     json_mode=True,
  │                     use_reasoner=False)     ← 使用 chat 模型
  │     
  │     hypothesis = Hypothesis.model_validate(json.loads(response))
  │
  └── ③ 创建内存会话
        session = DesignSession(
            session_id=uuid4(),
            status="hypothesis_generated",
            request=request,
            retrieved_context=formatted_context,
            hypothesis=hypothesis
        )
        design_sessions[session_id] = session  ← 存入内存字典
        return CreateSessionResponse(session_id, hypothesis)
```

**为什么只检索 5 条？** 实验设计的目标是生成一个**聚焦的、可执行的方案**，而非文献综述式的全面覆盖。5 条高度相关的段落足以提供方法论依据。

**为什么用 chat 模型而非 reasoner？** 假设生成需要的是创意性构思而非深度逻辑推理。chat 模型响应更快，且在结构化 JSON 输出方面表现稳定。

---

## 5. 第二步：生成完整实验方案

**端点**：`POST /api/experiments/{session_id}/design`
**方法**：`ExperimentDesignerService.generate_full_design()`

### 5.1 核心机制：JSON Schema 驱动的结构化生成

这是本模块最核心的设计模式——将 Pydantic 模型的 JSON Schema **直接注入 LLM prompt**：

```python
# 第 124 行
schema_json_string = json.dumps(
    ExperimentDesign.model_json_schema(),
    indent=2
)

final_design_prompt = f'''
You are an expert research assistant. Your task is to expand
a given hypothesis into a full experimental design.

Original User Request:
- Research Topic: {session.request.research_topic}
- Key Variables: {session.request.variables}
- Constraints: {session.request.constraints}

Approved Hypothesis: {session.hypothesis.hypothesis_text}
Relevant Context: {session.retrieved_context}

You MUST output a single, valid JSON object that strictly
adheres to the following schema.

JSON Schema:
{schema_json_string}
'''
```

**Pydantic → JSON Schema 转换示例**：

```python
ExperimentDesign.model_json_schema()
```

```json
{
  "title": "ExperimentDesign",
  "type": "object",
  "properties": {
    "title": {"type": "string", "description": "The title of the experimental plan."},
    "hypothesis": {"type": "string", "description": "The core research hypothesis being tested."},
    "methodology": {"type": "string", "description": "An overview of the primary research methodology."},
    "materials": {
      "type": "array",
      "items": {"type": "string"},
      "description": "A complete list of all materials and reagents needed."
    },
    "control_group": {"type": "string", "description": "..."},
    "experimental_group": {"type": "string", "description": "..."},
    "steps": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "step_number": {"type": "integer"},
          "description": {"type": "string"},
          "materials_needed": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["step_number", "description"]
      }
    },
    "data_analysis_plan": {"type": "string"},
    "potential_risks": {"type": "string"}
  },
  "required": ["title", "hypothesis", "methodology", "materials",
               "control_group", "experimental_group", "steps",
               "data_analysis_plan"]
}
```

**为什么用 JSON Schema 而不是自然语言描述结构？**

| 方式 | 优点 | 缺点 |
|------|------|------|
| 自然语言描述 | 灵活 | LLM 可能遗漏字段、类型不匹配 |
| JSON Schema | 结构精确、类型明确 | 增加 prompt 长度 |

实验设计的输出有 **9 个字段 + 嵌套数组**，结构复杂。JSON Schema 驱动能显著降低 Pydantic 校验失败的概率。

### 5.2 错误处理

```python
try:
    llm_json = json.loads(llm_response_str)
    design = ExperimentDesign.model_validate(llm_json)
except (json.JSONDecodeError, TypeError) as e:
    # LLM 返回了非法 JSON
    raise ValueError(f"Invalid JSON. Raw response: {llm_response_str}")
except Exception as e:
    # Pydantic 校验失败（字段缺失/类型错误）
    raise ValueError(f"Did not match required structure. Raw: {llm_response_str}")
```

两种异常分别处理，且都携带原始 LLM 响应在错误消息中，方便调试。前端通过 `err.response?.data?.detail` 提取错误信息展示给用户。

### 5.3 本次 LLM 调用

| 属性 | 值 |
|------|-----|
| 模型 | `deepseek-chat` |
| `json_mode` | **True** |
| `use_reasoner` | False |
| 输出大小 | 9 字段 × ~100-500 tokens/字段 ≈ 2000-4000 output tokens |

---

## 6. 第三步：Critic-Refiner 双代理优化

**端点**：`POST /api/experiments/{session_id}/refine`
**方法**：`ExperimentDesignerService.review_and_refine_design()`

这是整个实验设计模块最独特的设计——**两个 LLM 代理的接力协作**。

### 6.1 双代理架构

```
┌─────────────────────────────────────────────────────────────┐
│                  Critic-Refiner 双代理模式                    │
│                                                              │
│  原始方案 (ExperimentDesign)                                  │
│       │                                                      │
│       ▼                                                      │
│  ┌──────────────────────────────────────┐                   │
│  │         Critic Agent (审查者)          │                   │
│  │                                      │                   │
│  │  "You are a skeptical, rigorous,     │                   │
│  │   and experienced scientific         │                   │
│  │   reviewer."                         │                   │
│  │                                      │                   │
│  │  输入: 原始 ExperimentDesign           │                   │
│  │  输出: Critique                       │                   │
│  │    ├── potential_flaws: [...]         │                   │
│  │    └── suggested_improvements: [...]  │                   │
│  └──────────────────────────────────────┘                   │
│       │                                                      │
│       │ Critique (JSON)                                      │
│       ▼                                                      │
│  ┌──────────────────────────────────────┐                   │
│  │        Refiner Agent (改进者)          │                   │
│  │                                      │                   │
│  │  "You are an expert research         │                   │
│  │   assistant. Revise the design       │                   │
│  │   based on a critical review."       │                   │
│  │                                      │                   │
│  │  输入: 原始方案 + Critique             │                   │
│  │  输出: 优化后的 ExperimentDesign       │                   │
│  └──────────────────────────────────────┘                   │
│       │                                                      │
│       ▼                                                      │
│  优化方案 (ExperimentDesign)                                  │
│  → 覆盖 session.final_design                                 │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 Critic Agent 的实现

```python
critic_prompt = f'''
You are a skeptical, rigorous, and experienced scientific reviewer.
Your task is to find potential flaws and suggest improvements
for the following experimental design.

Experimental Design to Review:
```json
{original_design.model_dump_json(indent=2)}
```

Your Task:
Provide a critical review of this design. Focus on identifying
potential flaws, biases, missing controls, or areas where the
methodology could be more robust. Output a JSON object:
{{
  "potential_flaws": ["flaw 1", "flaw 2", ...],
  "suggested_improvements": ["improvement 1", "improvement 2", ...]
}}
'''

critique_response = get_llm_response(critic_prompt,
                         json_mode=True,
                         use_reasoner=False)

critique = Critique.model_validate_json(critique_response)
# 例:
# Critique(
#   potential_flaws=[
#     "No mention of blinding procedures for participants",
#     "Sample size justification is absent",
#     "Potential confounding variable: time of day effects on memory"
#   ],
#   suggested_improvements=[
#     "Implement a double-blind protocol...",
#     "Conduct a power analysis to determine minimum sample size...",
#     "Control for circadian rhythm by testing all participants at 9 AM..."
#   ]
# )
```

### 6.3 Refiner Agent 的实现

```python
refine_prompt = f'''
You are an expert research assistant. Your task is to revise
an experimental design based on a critical review.

Original Experimental Design:
```json
{original_design.model_dump_json(indent=2)}
```

Critical Review and Suggestions:
- Potential Flaws Found: {critique.potential_flaws}
- Suggested Improvements: {critique.suggested_improvements}

Your Task:
Generate a new, improved version of the experimental design
that addresses the points raised in the review. The revised
design should be more robust, clear, and scientifically sound.
You MUST output a single, valid JSON object that strictly
adheres to the original schema.
'''

refined_design_str = get_llm_response(refine_prompt,
                          json_mode=True,
                          use_reasoner=False)

refined_design = ExperimentDesign.model_validate_json(refined_design_str)
session.final_design = refined_design     # 覆盖原方案
```

### 6.4 为什么 Critic-Refiner 是串行的

```
Critic (审查) ──→ Refiner (改进)
  3-5s              5-10s
```

Critic 必须先完成——Refiner 的 prompt 直接引用 `critique.potential_flaws` 和 `critique.suggested_improvements`。这两个步骤**本质上是串行依赖**。

### 6.5 本阶段 LLM 调用

| 步骤 | 代理 | 模型 | json_mode | use_reasoner |
|------|------|------|-----------|-------------|
| 3a | Critic | `deepseek-chat` | True | False |
| 3b | Refiner | `deepseek-chat` | True | False |

---

## 7. 会话状态管理

**位置**：[`experiment_designer_service.py`](backend/services/experiment_designer_service.py) 第 22 行

```python
# In-memory storage for design sessions.
# For production, this would be replaced with a database or a Redis cache.
design_sessions: Dict[str, DesignSession] = {}
```

### 7.1 会话生命周期

```
create_session()
  │
  ├── 创建 DesignSession(status="hypothesis_generated")
  ├── 存入 design_sessions[session_id]
  │
  ▼
generate_full_design()
  │
  ├── 读取 design_sessions[session_id]
  ├── 生成 ExperimentDesign → session.final_design = design
  ├── session.status = "design_completed"
  │
  ▼
review_and_refine_design()
  │
  ├── 读取 design_sessions[session_id]
  ├── 验证: session.final_design 不为 None
  ├── Critic → Refiner → session.final_design = refined
  │
  ▼
(服务重启 → 会话丢失 ⚠️)
```

### 7.2 风险分析

| 风险 | 影响 | 严重程度 |
|------|------|---------|
| 服务重启 | 所有活跃会话丢失 | ⚠️ 中（开发环境常见） |
| 内存泄漏 | 长期运行的服务器会积累废弃会话 | ⚠️ 中（无 TTL 机制） |
| 并发访问 | 同一 session_id 被两个请求同时写入 | 低（单用户场景） |

**代码已标注改进方向**：

```python
# For production, this would be replaced with a database or a Redis cache.
```

迁移到 Redis 的方案：

```python
# 使用 Redis 替代内存字典
await redis_client.setex(
    f"session:{session_id}",
    3600,  # 1h TTL（自动清理）
    session.model_dump_json()
)
```

---

## 8. DOCX 导出

**端点**：`GET /api/experiments/{session_id}/download`
**方法**：`ExperimentDesignerService.export_design_to_docx()`

### 8.1 文档结构

```
┌─────────────────────────────────────────────┐
│  Experimental Design Title                  │  ← Level 0
├─────────────────────────────────────────────┤
│  Hypothesis                                 │  ← Level 1
│  The core research hypothesis text...       │
├─────────────────────────────────────────────┤
│  Methodology                                │  ← Level 1
│  Overview of the primary methodology...     │
├─────────────────────────────────────────────┤
│  Materials                                  │  ← Level 1
│  • Material 1                               │  ← Bullet List
│  • Material 2                               │
│  • ...                                      │
├─────────────────────────────────────────────┤
│  Groups                                     │  ← Level 1
│  Control Group: ...                         │
│  Experimental Group: ...                    │
├─────────────────────────────────────────────┤
│  Protocol Steps                             │  ← Level 1
│                                             │
│  Step 1                                     │  ← Level 2
│  Detailed description of step 1...          │
│  Materials Needed:                          │
│  • Item A                                   │
│  • Item B                                   │
│                                             │
│  Step 2                                     │  ← Level 2
│  Detailed description of step 2...          │
│  ...                                        │
├─────────────────────────────────────────────┤
│  Data Analysis Plan                         │  ← Level 1
│  The plan for data collection...            │
├─────────────────────────────────────────────┤
│  Potential Risks                            │  ← Level 1 (条件性)
│  Identified risks and mitigations...        │
└─────────────────────────────────────────────┘
```

### 8.2 关键实现

```python
def export_design_to_docx(self, design: ExperimentDesign):
    doc = Document()

    doc.add_heading(design.title or "Experimental Design", level=0)
    doc.add_heading("Hypothesis", level=1)
    doc.add_paragraph(design.hypothesis)

    # Materials 使用项目符号列表
    doc.add_heading("Materials", level=1)
    for item in design.materials:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(item)

    # Steps 使用嵌套结构：Step N (Level 2) → Description → Materials
    for step in design.steps:
        doc.add_heading(f"Step {step.step_number}", level=2)
        doc.add_paragraph(step.description)
        if step.materials_needed:
            doc.add_paragraph("Materials Needed:")
            for m in step.materials_needed:
                sp = doc.add_paragraph(style='List Bullet')
                sp.add_run(m)

    # potential_risks 是可选字段
    if design.potential_risks:
        doc.add_heading("Potential Risks", level=1)
        doc.add_paragraph(design.potential_risks)

    return doc
```

---

## 9. 完整调用链路图

```
用户输入 Research Topic
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ Step 1: POST /api/experiments                               │
│                                          [analysis_routes.py:196]
│                                                              │
│ experiment_designer_service.create_session(request)          │
│                          [experiment_designer_service.py:73]  │
│   │                                                          │
│   ├── ① 上下文检索                                           │
│   │   vector_store.query(                                    │
│   │     query_text=research_topic,                           │
│   │     n_results=5,                                         │
│   │     collection_name="document_chunks"                    │
│   │   )                                                      │
│   │   → 5 条最相关段落                                        │
│   │                                                          │
│   │   _format_context(docs) → 结构化文本:                     │
│   │   "--- Context 1 (Source: ..., Page: ...) ---\n..."     │
│   │                                                          │
│   ├── ② LLM (chat, json_mode) 假设生成:                       │
│   │   输入: topic + context                                  │
│   │   输出: {"hypothesis_text": ..., "context_summary": ...} │
│   │   → Hypothesis.model_validate()                         │
│   │                                                          │
│   └── ③ 创建内存会话                                          │
│       session = DesignSession(                               │
│         session_id=str(uuid4()),                             │
│         status="hypothesis_generated",                       │
│         request=request,                                     │
│         retrieved_context=formatted_context,                 │
│         hypothesis=hypothesis                                │
│       )                                                      │
│       design_sessions[session_id] = session                  │
│                                                              │
│   return { session_id, hypothesis }                          │
└──────────────────────────────────────────────────────────────┘
    │
    │ 用户审查假设，决定是否继续
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ Step 2: POST /api/experiments/{session_id}/design            │
│                                          [analysis_routes.py:205]
│                                                              │
│ experiment_designer_service.generate_full_design(session_id) │
│                          [experiment_designer_service.py:113] │
│   │                                                          │
│   ├── ① 验证 session 存在                                    │
│   │                                                          │
│   ├── ② 生成 JSON Schema                                     │
│   │   schema_json = ExperimentDesign.model_json_schema()     │
│   │                                                          │
│   ├── ③ LLM (chat, json_mode) 方案生成:                       │
│   │   输入: topic + variables + constraints                  │
│   │        + hypothesis + context + JSON Schema              │
│   │   输出: ExperimentDesign (9 字段完整 JSON)                │
│   │                                                          │
│   ├── ④ Pydantic 校验                                        │
│   │   ExperimentDesign.model_validate(llm_json)              │
│   │   失败 → ValueError (含原始 LLM 响应)                     │
│   │                                                          │
│   └── ⑤ 更新会话                                             │
│       session.final_design = design                          │
│       session.status = "design_completed"                    │
│                                                              │
│   return design (ExperimentDesign)                           │
└──────────────────────────────────────────────────────────────┘
    │
    │ 用户审查完整方案，可选择优化
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ Step 3: POST /api/experiments/{session_id}/refine            │
│                                          [analysis_routes.py:216]
│                                                              │
│ experiment_designer_service.review_and_refine_design(id)     │
│                          [experiment_designer_service.py:167] │
│   │                                                          │
│   ├── ① 验证: final_design 已存在                             │
│   │                                                          │
│   ├── ② 阶段 A: Critic Agent                                 │
│   │   LLM (chat, json_mode):                                 │
│   │     prompt = "You are a skeptical, rigorous,             │
│   │               and experienced scientific reviewer..."    │
│   │     输入: original_design.model_dump_json()              │
│   │     输出: Critique                                       │
│   │       ├── potential_flaws: [...]                         │
│   │       └── suggested_improvements: [...]                  │
│   │                                                          │
│   ├── ③ 阶段 B: Refiner Agent                                │
│   │   LLM (chat, json_mode):                                 │
│   │     prompt = "You are an expert research assistant.      │
│   │               Revise based on a critical review..."      │
│   │     输入: original_design + critique                     │
│   │     输出: 优化后的 ExperimentDesign                       │
│   │                                                          │
│   └── ④ 更新会话                                             │
│       session.final_design = refined_design                  │
│                                                              │
│   return refined_design (ExperimentDesign)                   │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ Export: GET /api/experiments/{session_id}/download           │
│                                          [analysis_routes.py:227]
│                                                              │
│ experiment_designer_service.export_design_to_docx(design)    │
│                          [experiment_designer_service.py:241] │
│   │                                                          │
│   ├── add_heading(title, level=0)                            │
│   ├── Hypothesis → Level 1 + paragraph                      │
│   ├── Methodology → Level 1 + paragraph                     │
│   ├── Materials → Level 1 + List Bullet                     │
│   ├── Groups → Level 1 + paragraphs                         │
│   ├── Steps → Level 1, 每步 Level 2 + description + materials│
│   ├── Data Analysis Plan → Level 1 + paragraph              │
│   └── Potential Risks → Level 1 (条件性)                     │
│                                                              │
│   → StreamingResponse(.docx)                                 │
└──────────────────────────────────────────────────────────────┘
```

### 9.1 LLM 调用次数统计

| 步骤 | 调用目的 | 次数 | 模型 | json_mode |
|------|---------|------|------|-----------|
| Step 1 | 假设生成 | 1 | `deepseek-chat` | True |
| Step 2 | 完整方案生成 | 1 | `deepseek-chat` | True |
| Step 3a | Critic 审查 | 1 | `deepseek-chat` | True |
| Step 3b | Refiner 改进 | 1 | `deepseek-chat` | True |
| **总计 (完整流程)** | | **4** | — | — |
| **总计 (跳过 refine)** | | **2** | — | — |

---

## 10. 附录：与其他模块的对比

### 10.1 执行模式对比

| 维度 | 文献综述 | 研究空白分析 | 实验设计 |
|------|---------|------------|---------|
| 同步/异步 | 异步 (Celery) | 异步 (Celery) | **全同步** |
| 原因 | 逐节生成耗时长 | BERTopic 全量建模耗时长 | 单次 LLM 调用 ~5-10s，可接受 |
| 状态存储 | Redis + Celery Result | Redis + Celery Result | **服务器内存 dict** |
| 数据持久性 | 高 | 高 | **低 (重启丢失)** |
| 迭代能力 | 大纲可编辑 | 无 | **Critic-Refiner 1 轮迭代** |

### 10.2 代理模式对比

```
文献综述:   Single Agent × N 次调用
             LLM ──→ Introduction
             LLM ──→ Body Section 1
             LLM ──→ Body Section 2
             ...

实验设计:   Critic-Refiner 双代理
             LLM₁ (Critic) ──→ Critique
                                 │
                                 ▼
             LLM₂ (Refiner) ──→ Improved Design
```

### 10.3 结构化输出策略对比

```
RAG 问答:        Pydantic 校验 + 自然语言 prompt 约束
文献综述:        Pydantic 校验 + JSON Schema 在 prompt 中手动描述
实验设计:        Pydantic 校验 + model_json_schema() 自动注入 ← 最精确
研究空白分析:    无结构化输出（自由文本 + 统计结果）
```

实验设计模块是项目中**唯一使用 `model_json_schema()` 自动生成输出规范**的模块。这减少了 prompt 工程中的手工错误——如果 ExperimentDesign 模型发生变化（如添加新字段），JSON Schema 会自动更新，无需手动修改 prompt。

### 10.4 已知问题与改进方向

#### 问题 1：内存会话无 TTL

**影响**：废弃会话永久驻留内存（直到服务重启）。

**建议**：使用 Redis 替代内存字典，设置 1 小时 TTL 自动过期。

#### 问题 2：Refine 仅限一次

前端强制 `disabled={!!refinedDesign}` 意味着用户只能迭代一轮。从 UX 角度，允许多轮迭代（Critic → Refiner → Critic → Refiner → ...）直到用户满意可能更有价值。

#### 问题 3：无用户隔离

`design_sessions` 是全局字典，不区分用户。如果多用户同时使用，session_id 可能被他人猜中（UUID4 概率极低但理论上存在）。

#### 问题 4：前端未传递 variables 和 constraints

前端页面的 Step 1 只有一个 `Textarea` 用于输入 `research_topic`，没有提供 variable 和 constraint 的输入字段。这是前后端之间的一个不一致——后端 Schema 支持这些字段，但前端没有暴露它们。
