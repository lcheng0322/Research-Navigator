# 表格数据分析模块完整实现详解

> 本文档深入解析 Research Navigator 的表格数据分析功能——项目中**唯一不依赖 LLM**的分析模块，基于 scikit-learn + Plotly 实现统计描述、回归分析和可交互可视化。

---

## 目录

1. [架构总览](#1-架构总览)
2. [前端交互设计](#2-前端交互设计)
3. [数据读取层](#3-数据读取层)
4. [第一步：初始分析](#4-第一步初始分析)
5. [第二步 A：回归分析](#5-第二步-a回归分析)
6. [第二步 B：可视化](#6-第二步-b可视化)
7. [Redis 文件缓存机制](#7-redis-文件缓存机制)
8. [与文档入库流水线的关联](#8-与文档入库流水线的关联)
9. [完整调用链路图](#9-完整调用链路图)
10. [附录：与其他模块的对比](#10-附录与其他模块的对比)

---

## 1. 架构总览

```
用户上传 CSV/XLSX
    │
    ▼
POST /api/analyze/tabular-data/initiate
    │
    ├── 保存文件到 temp_files/ (UUID 命名)
    ├── pandas 读取 → DataFrame
    ├── 基础信息 + 描述性统计 + 相关性矩阵
    ├── Redis 缓存文件路径 (file_id, TTL 1h)
    └── return { file_info, descriptive_statistics, correlation_matrix, file_id }

用户交互选择变量
    │
    ├── POST /api/analyze/tabular-data/regression
    │     file_id + analysis_type + dependent_var + independent_vars
    │     → sklearn 线性回归 / 逻辑回归
    │     → return { coefficient, r_squared / accuracy, confusion_matrix }
    │
    └── POST /api/analyze/tabular-data/visualize
          file_id + vis_type + x_col + y_col?
          → Plotly 生成图表
          → return Plotly JSON (前端渲染)
```

**核心文件映射**：

| 层 | 文件 | 职责 |
|----|------|------|
| API 路由 | [`backend/api/analysis_routes.py`](backend/api/analysis_routes.py) 第 141–193 行 | 3 个端点 + 辅助函数 |
| 业务逻辑 | [`backend/services/tabular_data_service.py`](backend/services/tabular_data_service.py) | pandas/sklearn/plotly 调用封装 |
| 前端页面 | [`frontend/src/pages/TabularDataAnalysisPage.tsx`](frontend/src/pages/TabularDataAnalysisPage.tsx) | 上传 + Tab 切换 + Plotly 图表渲染 |

**本模块的核心特征**：

| 特征 | 说明 |
|------|------|
| 零 LLM 调用 | 纯统计计算，不依赖任何外部 AI API |
| 两阶段交互 | 初始分析 → 用户选择变量 → 回归/可视化 |
| Redis 文件缓存 | file_id 映射到临时文件路径，TTL 1h |
| 同步执行 | 全同步——sklearn 计算毫秒级，无需 Celery |

---

## 2. 前端交互设计

**文件**：[`frontend/src/pages/TabularDataAnalysisPage.tsx`](frontend/src/pages/TabularDataAnalysisPage.tsx)

### 2.1 页面布局

```
┌──────────────────────────────────────────────────────────────┐
│  Interactive Tabular Data Analysis                           │
├──────────────────────────────────────────────────────────────┤
│  1. Upload Data File                                         │
│  [Select CSV/XLSX File]                                      │
│  Selected: experiment_data.csv                               │
│                                          [Run Initial Analysis]
├──────────────────────────────────────────────────────────────┤
│  (初始分析完成后，Tab 切换)                                    │
│                                                              │
│  [Data Overview] [Descriptive Statistics] [Interactive Analysis]
│                                                              │
│  ┌─ Data Overview ──────────────────────────────────────────┐│
│  │ Row Count: 150          Column Count: 8                  ││
│  │ Columns: [tag][tag][tag][tag][tag][tag][tag][tag]        ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  ┌─ Descriptive Statistics ─────────────────────────────────┐│
│  │ [Numeric] [Categorical]                                  ││
│  │ ┌──────────────────────────────────────────────────┐     ││
│  │ │ Statistic │ dosage │ time │ yield │ temp │ ...    │     ││
│  │ │ count     │ 150    │ 150  │ 150   │ 150  │        │     ││
│  │ │ mean      │ 25.300 │ 12.5 │ 0.852 │ 350  │        │     ││
│  │ │ std       │ 5.120  │ 3.2  │ 0.034 │ 50   │        │     ││
│  │ │ min       │ 10.000 │ 5.0  │ 0.750 │ 250  │        │     ││
│  │ │ ...       │ ...    │ ...  │ ...   │ ...  │        │     ││
│  │ └──────────────────────────────────────────────────┘     ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  ┌─ Interactive Analysis ───────────────────────────────────┐│
│  │                                                          ││
│  │ ┌─ Regression Analysis ──┐  ┌─ Generate Visualization ──┐││
│  │ │ Analysis Type: [Linear]│  │ Type: [Scatter Plot]      │││
│  │ │ Dependent:    [yield]  │  │ X-Axis: [dosage]          │││
│  │ │ Independent:  [dosage] │  │ Y-Axis: [yield]           │││
│  │ │ [Run Regression]       │  │ [Generate Plot]           │││
│  │ │                        │  │                           │││
│  │ │ {                      │  │   📈 Plotly 交互式图表     │││
│  │ │   "type": "Linear",    │  │   散点图 / 直方图 / 箱线图 │││
│  │ │   "coefficient": 0.03, │  │                           │││
│  │ │   "r_squared": 0.87    │  │                           │││
│  │ │ }                      │  │                           │││
│  │ └────────────────────────┘  └───────────────────────────┘││
│  └──────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

### 2.2 状态管理

```typescript
const [selectedFile, setSelectedFile] = useState<UploadFile | null>(null);
const [baseAnalysis, setBaseAnalysis] = useState<any>(null);
const [fileId, setFileId] = useState<string | null>(null);

// 回归和可视化结果独立存储，不会相互覆盖
const [regressionResult, setRegressionResult] = useState<any>(null);
const [visResult, setVisResult] = useState<any>(null);
```

**关键交互**：

- 选择新文件 → 清空所有分析结果（`setBaseAnalysis(null)` 等）
- 初始分析按钮 `disabled={!selectedFile || !!baseAnalysis}` → 分析完成后按钮变灰
- 回归和可视化是两个独立 Form，共享同一个 `fileId`，互不影响
- 回归结果用 `<pre>` 展示 JSON，可视化结果用 `<Plot>` 组件渲染

### 2.3 上传组件配置

```typescript
<Upload
  onChange={handleFileChange}
  theme="custom"
  accept=".csv,.xlsx"      // 只接受表格文件
  autoUpload={false}        // 不自动上传
  showUploadProgress={false}
>
  <Button>Select CSV/XLSX File</Button>
</Upload>
```

`autoUpload={false}` 意味着文件选择后不立即发送请求——用户需要手动点击 "Run Initial Analysis"。这让用户可以先确认选中的文件再执行分析。

---

## 3. 数据读取层

**文件**：[`backend/services/tabular_data_service.py`](backend/services/tabular_data_service.py) 第 19–26 行

### 3.1 DataFrame 读取

```python
def _get_dataframe(self, file_path: Path) -> pd.DataFrame:
    if file_path.suffix.lower() == '.csv':
        return pd.read_csv(file_path)
    elif file_path.suffix.lower() in ['.xls', '.xlsx']:
        return pd.read_excel(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_path.suffix}")
```

**仅支持 CSV 和 Excel**。JSON、Parquet、Feather 等格式不在支持列表中。这是有意限制——科研数据最常见的两种格式就是 CSV 和 Excel。

### 3.2 缺失值处理策略

各分析方法对缺失值的处理各不相同：

| 方法 | 缺失值策略 | 说明 |
|------|-----------|------|
| `get_basic_info()` | 统计计数 | `df.isnull().sum()` 展示每列缺失数 |
| `get_descriptive_statistics()` | pandas 默认 | `describe()` 自动排除 NaN |
| `perform_linear_regression()` | **直接删除** | `df[[x, y]].dropna()` |
| `perform_logistic_regression()` | **直接删除** | `df[cols].dropna()` |
| `generate_visualizations()` | Plotly 默认 | Plotly 自动跳过 NaN |

> 线性回归和逻辑回归使用 `dropna()` 而非填充（imputation），这是统计上保守的做法——不假设缺失值的分布。

---

## 4. 第一步：初始分析

**端点**：`POST /api/analyze/tabular-data/initiate`
**方法**：`TabularDataService.get_full_analysis()`

### 4.1 请求与响应

```
请求:  POST /api/analyze/tabular-data/initiate
       Content-Type: multipart/form-data
       file: experiment_data.csv

响应:  {
         "file_info": {
           "row_count": 150,
           "column_count": 8,
           "column_names": ["dosage", "time", "yield", "temp", "catalyst", "solvent", "pH", "batch"],
           "numeric_columns": ["dosage", "time", "yield", "temp", "pH"],
           "categorical_columns": ["catalyst", "solvent", "batch"],
           "missing_values": {"pH": 3, "yield": 1}
         },
         "descriptive_statistics": {
           "numeric": {
             "dosage": {"count": 150, "mean": 25.3, "std": 5.12, ...},
             "time":   {"count": 150, "mean": 12.5, "std": 3.2, ...},
             ...
           },
           "categorical": {
             "catalyst": {"count": 150, "unique": 3, "top": "Pt/C", "freq": 60},
             ...
           }
         },
         "correlation_matrix": {
           "dosage": {"dosage": 1.0, "time": 0.12, "yield": 0.87, "temp": -0.34, "pH": 0.05},
           "time":   {"dosage": 0.12, "time": 1.0, ...},
           ...
         },
         "file_id": "a1b2c3d4-..."
       }
```

### 4.2 基础信息提取

```python
def get_basic_info(self, df: pd.DataFrame) -> Dict[str, Any]:
    numeric_cols = df.select_dtypes(include='number').columns.tolist()
    categorical_cols = df.select_dtypes(
        include=['object', 'category']
    ).columns.tolist()

    return {
        "row_count": len(df),
        "column_count": len(df.columns),
        "column_names": df.columns.tolist(),
        "numeric_columns": numeric_cols,
        "categorical_columns": categorical_cols,
        "missing_values": {
            k: int(v)
            for k, v in df.isnull().sum().to_dict().items()
            if v > 0                          # 只返回有缺失值的列
        }
    }
```

**列类型分类逻辑**：

```
DataFrame 列
  │
  ├── dtype = int64 / float64 → numeric_columns
  │     → 用于: 回归分析、相关性矩阵、直方图、散点图、箱线图
  │
  └── dtype = object / category → categorical_columns
        → 用于: 逻辑回归的因变量、分类统计
```

### 4.3 描述性统计

```python
def get_descriptive_statistics(self, df: pd.DataFrame) -> Dict[str, Any]:
    # 数值列: count, mean, std, min, 25%, 50%, 75%, max
    numeric_stats = df.describe(include='number').to_dict()

    # 分类列: count, unique, top, freq
    categorical_cols = df.select_dtypes(include=['object', 'category']).columns
    if not categorical_cols.empty:
        categorical_stats = df.describe(
            include=['object', 'category']
        ).to_dict()

    return {"numeric": numeric_stats, "categorical": categorical_stats}
```

`pandas.describe()` 的默认行为：

```
数值列输出: count, mean, std, min, 25%, 50%, 75%, max

    例: dosage 列
    ┌───────┬────────┐
    │ count │ 150    │
    │ mean  │ 25.3   │
    │ std   │ 5.12   │
    │ min   │ 10.0   │
    │ 25%   │ 22.1   │
    │ 50%   │ 25.5   │
    │ 75%   │ 28.9   │
    │ max   │ 40.0   │
    └───────┴────────┘

分类列输出: count, unique, top, freq

    例: catalyst 列
    ┌─────────┬────────┐
    │ count   │ 150    │
    │ unique  │ 3      │
    │ top     │ "Pt/C" │
    │ freq    │ 60     │
    └─────────┴────────┘
```

### 4.4 相关性矩阵

```python
correlation_matrix = None
if len(basic_info['numeric_columns']) > 1:
    correlation_matrix = df[
        basic_info['numeric_columns']
    ].corr().to_dict()
```

**条件**：至少有 2 个数值列才计算（单数值列的相关性没有意义）。

**方法**：pandas 默认使用 **Pearson 相关系数**（`method='pearson'`）。

```
相关性矩阵示例 (3 个数值列):

            dosage   time     yield
dosage      1.00     0.12     0.87
time        0.12     1.00    -0.23
yield       0.87    -0.23     1.00

解读:
  dosage ↔ yield:  r = 0.87  强正相关
  time ↔ yield:    r = -0.23 弱负相关
  dosage ↔ time:   r = 0.12  几乎无相关
```

---

## 5. 第二步 A：回归分析

**端点**：`POST /api/analyze/tabular-data/regression`
**方法**：`perform_linear_regression()` / `perform_logistic_regression()`

### 5.1 线性回归

```python
def perform_linear_regression(self, df, independent_var, dependent_var):
    temp_df = df[[independent_var, dependent_var]].dropna()
    if len(temp_df) < 2:
        return None                         # 数据不足

    X = temp_df[[independent_var]].values   # (n, 1)
    y = temp_df[dependent_var].values       # (n,)

    model = LinearRegression().fit(X, y)

    return {
        'type': 'Linear',
        'dependent_variable': dependent_var,
        'independent_variable': independent_var,
        'coefficient': model.coef_[0],       # 斜率
        'intercept': model.intercept_,       # 截距
        'r_squared': model.score(X, y)       # R²
    }
```

**模型解读**：

```
y = coefficient × X + intercept

例:
  因变量: yield (产率)
  自变量: dosage (剂量)

  结果:
    coefficient: 0.032    → 剂量每增加 1 单位，产率增加 3.2%
    intercept:   0.451     → 剂量为 0 时的理论产率
    r_squared:   0.872     → 87.2% 的产率变异可被剂量解释（拟合良好）
```

**限制**：只支持单变量线性回归（`independent_var` 只能是 1 个字符串）。API 层强制了这个限制：

```python
if analysis_type == 'linear':
    if len(independent_vars) != 1:
        raise HTTPException(400,
            "Linear regression requires exactly one independent variable.")
```

### 5.2 逻辑回归

```python
def perform_logistic_regression(self, df, independent_vars, dependent_var):
    cols_to_use = independent_vars + [dependent_var]
    temp_df = df[cols_to_use].dropna()

    if temp_df[dependent_var].nunique() < 2:
        return None      # 因变量至少需要 2 个类别

    # ① 分类自变量 → One-Hot 编码
    X = pd.get_dummies(temp_df[independent_vars], drop_first=True)

    # ② 因变量 → 数值标签
    le = LabelEncoder()
    y = le.fit_transform(temp_df[dependent_var])

    # ③ 70/30 训练测试分割
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42   # 固定随机种子确保可复现
    )

    # ④ 训练模型
    model = LogisticRegression(max_iter=1000).fit(X_train, y_train)

    return {
        'type': 'Logistic',
        'dependent_variable': dependent_var,
        'independent_variables': independent_vars,
        'accuracy': accuracy_score(y_test, model.predict(X_test)),
        'class_names': le.classes_.tolist(),
        'confusion_matrix': confusion_matrix(y_test, model.predict(X_test)).tolist()
    }
```

**数据预处理流水线**：

```
原始数据:
  catalyst  solvent  temp   yield_category
  "Pt/C"    "EtOH"   350    "high"
  "Fe"      "MeOH"   300    "low"
  "Pt/C"    "H2O"    400    "high"

  ↓ ① get_dummies(drop_first=True)

  catalyst_Fe  catalyst_Pt/C  solvent_MeOH  solvent_EtOH  temp
  0            1              0             1             350
  1            0              1             0             300
  0            1              0             0             400

  ↓ ② LabelEncoder

  y = ["high", "low", "high"] → [1, 0, 1]

  ↓ ③ train_test_split(70/30)

  X_train: 2 样本, X_test: 1 样本

  ↓ ④ LogisticRegression(max_iter=1000) → 模型

输出:
  accuracy: 0.85
  class_names: ["low", "high"]
  confusion_matrix: [[45, 5], [3, 47]]
  ↑                   TN   FP    FN   TP
```

**`max_iter=1000`**：逻辑回归默认的迭代次数可能不足以收敛，设置为 1000 提高收敛成功的概率。

---

## 6. 第二步 B：可视化

**端点**：`POST /api/analyze/tabular-data/visualize`
**方法**：`TabularDataService.generate_visualizations()`

### 6.1 三种图表类型

```python
def generate_visualizations(self, df, vis_type, x_col, y_col=None):
    if vis_type == 'histogram':
        fig = px.histogram(df, x=x_col,
                           title=f"Histogram of {x_col}")

    elif vis_type == 'scatter':
        fig = px.scatter(df, x=x_col, y=y_col,
                         title=f"Scatter Plot of {y_col} vs {x_col}")

    elif vis_type == 'boxplot':
        fig = px.box(df, y=x_col,
                     title=f"Box Plot of {x_col}")

    return fig.to_json()    # Plotly Figure → JSON → 前端 <Plot> 渲染
```

| 图表类型 | 所需参数 | 典型用途 |
|----------|---------|---------|
| Histogram | `x_col` | 单变量分布（如剂量分布、产率分布） |
| Scatter | `x_col` + `y_col` | 两变量关系（如剂量 vs 产率） |
| Box Plot | `x_col`（作为 y 轴） | 单变量离散程度（中位数、四分位数、离群点） |

### 6.2 Plotly JSON 传输

`fig.to_json()` 将 Plotly Figure 对象序列化为 JSON 字符串。前端使用 `react-plotly.js` 直接渲染：

```typescript
// 前端渲染
{visResult && <Plot data={visResult.data} layout={visResult.layout} />}
```

**为什么不返回图片而是 JSON？**
- JSON 可以交互（缩放、悬停提示、平移）
- 体积比 PNG 更小
- 前端可以自定义样式

---

## 7. Redis 文件缓存机制

**文件**：[`backend/api/analysis_routes.py`](backend/api/analysis_routes.py) 第 36 行（常量）、第 48–59 行（辅助函数）、第 142–155 行（initiate 端点）

### 7.1 文件生命周期

```
POST /api/analyze/tabular-data/initiate
  │
  ├── ① 保存文件
  │     temp_file_path = temp_files/{uuid4()}.csv
  │     (例如: temp_files/a1b2c3d4-e5f6-7890-abcd-ef1234567890.csv)
  │
  ├── ② pandas 读取 → 完整分析 → 返回结果
  │
  ├── ③ 缓存文件路径到 Redis
  │     file_id = uuid4()
  │     redis.setex(f"tabular_file:{file_id}", 3600, str(temp_file_path))
  │     return { ..., file_id }
  │
  └── ④ 文件保留在磁盘（等待后续回归/可视化请求）

POST /api/analyze/tabular-data/regression 或 /visualize
  │
  ├── file_path_str = redis.get(f"tabular_file:{file_id}")
  │   → null? HTTP 404 "File ID not found or expired."
  │
  └── pd.read_csv(file_path_str) 或 pd.read_excel(file_path_str)
      → 执行回归/可视化
```

### 7.2 缓存键设计

```
file_id: "a1b2c3d4-e5f6-..."
Redis key: "tabular_file:a1b2c3d4-e5f6-..."
Redis value: "temp_files/b1c2d3e4-f5a6-7890-abcd-ef1234567890.csv"

TTL: 3600 秒 (1 小时)
```

### 7.3 为什么不用 document ingestion 的文件？

表格数据分析与文档入库是**两条完全独立的路径**：

```
表格文件上传
  │
  ├── 文档入库路径: POST /api/upload/
  │     → backend/data/uploads/ (持久化)
  │     → 逐行文本化 → ChromaDB
  │     → 用于 RAG 搜索
  │
  └── 分析路径: POST /api/analyze/tabular-data/initiate
        → temp_files/ (临时, TTL 1h)
        → 保留原始 DataFrame 结构
        → 仅用于统计分析和可视化
```

**设计理由**：
- 入库路径将表格拆成"Row N contains: ..."的文本块，丢失了数值结构
- 分析路径保留原始 DataFrame，可以做数学运算（回归、相关性）
- 两条路径服务于不同的使用场景，互不干扰

### 7.4 文件清理

**当前实现没有自动清理机制**。`temp_files/` 目录会持续积累过期的临时文件。

理想情况下应该：
- 设置定时任务清理超过 1 小时的文件
- 或在 Redis key 过期时通过 keyspace notification 触发删除

---

## 8. 与文档入库流水线的关联

**文件**：[`backend/api/document_routes.py`](backend/api/document_routes.py) 第 55–128 行

`POST /api/upload/` 端点有一个 `analyze_only=true` 参数：

```python
@router.post("/upload/")
async def upload_file(file, analyze_only=False, db):
    if is_tabular and analyze_only:
        # 分支 A: 即时分析（不入库）
        analysis_result = tabular_data_service.get_full_analysis(file_path)
        # finally: 删除文件 ← 与 /initiate 不同！
        return analysis_result
    else:
        # 分支 B: 知识库入库
        task = ingest_document_task.delay(file_path, file_hash, file_size)
        return {"task_id": task.id, ...}
```

**三条路径对比**：

| 维度 | `POST /api/upload/` (入库) | `POST /api/upload/` (analyze_only) | `POST /api/analyze/tabular-data/initiate` |
|------|---------------------------|-------------------------------------|-------------------------------------------|
| 文件保留 | ✅ 持久化 | ❌ 用完即删 | ✅ 临时保留 (1h TTL) |
| 向量入库 | ✅ | ❌ | ❌ |
| 统计分析 | ❌ | ✅ 一次性 | ✅ 可交互 (回归/可视化) |
| 后续操作 | RAG 检索 | 无 | 回归 + 可视化 |
| 使用场景 | 构建知识库 | 快速看一眼数据 | 深入交互式分析 |

---

## 9. 完整调用链路图

```
用户选择 experiment_data.csv → 点击 "Run Initial Analysis"
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ Step 1: POST /api/analyze/tabular-data/initiate             │
│                                          [analysis_routes.py:142]
│                                                              │
│   save_upload_file(file) → temp_files/{uuid}.csv            │
│                                                              │
│   tabular_data_service.get_full_analysis(file_path)          │
│                         [tabular_data_service.py:117]         │
│     │                                                        │
│     ├── ① _get_dataframe(file_path)                         │
│     │     pd.read_csv() / pd.read_excel() → DataFrame        │
│     │                                                        │
│     ├── ② get_basic_info(df)                                │
│     │     row_count, column_count, column_names,             │
│     │     numeric_columns, categorical_columns,              │
│     │     missing_values                                     │
│     │                                                        │
│     ├── ③ get_descriptive_statistics(df)                     │
│     │     numeric: count/mean/std/min/25%/50%/75%/max        │
│     │     categorical: count/unique/top/freq                 │
│     │                                                        │
│     └── ④ 相关性矩阵 (条件: 数值列 ≥ 2)                       │
│           df[numeric_cols].corr().to_dict()                  │
│                                                              │
│   file_id = uuid4()                                         │
│   redis.setex(f"tabular_file:{file_id}", 3600,               │
│                str(temp_file_path))                          │
│                                                              │
│   return { file_info, descriptive_statistics,                │
│            correlation_matrix, file_id }                     │
└──────────────────────────────────────────────────────────────┘
    │
    │ 用户在交互式 Tab 中选择变量
    │
    ├─────────────────────────────────────────────────────────┐
    │                                                          │
    ▼                                                          ▼
┌──────────────────────────────┐  ┌──────────────────────────────┐
│ Step 2A: Regression         │  │ Step 2B: Visualization       │
│ [analysis_routes.py:176]    │  │ [analysis_routes.py:189]     │
│                              │  │                              │
│ ① _load_cached_df(file_id)  │  │ ① _load_cached_df(file_id)  │
│    redis.get(key) → path    │  │    redis.get(key) → path     │
│    pd.read_csv/excel(path)  │  │    pd.read_csv/excel(path)   │
│                              │  │                              │
│ ② 分支:                     │  │ ② 分支:                      │
│                              │  │                              │
│  linear:                    │  │  histogram:                  │
│    LinearRegression()       │  │    px.histogram(df, x=x_col)│
│    → coefficient/intercept  │  │                              │
│    → r_squared              │  │  scatter:                    │
│                              │  │    px.scatter(df, x, y)     │
│  logistic:                  │  │                              │
│    get_dummies()            │  │  boxplot:                    │
│    LabelEncoder()           │  │    px.box(df, y=x_col)       │
│    train_test_split(70/30)  │  │                              │
│    LogisticRegression()     │  │ ③ fig.to_json()              │
│    → accuracy               │  │    → 前端 <Plot> 渲染        │
│    → confusion_matrix       │  │                              │
│                              │  │                              │
│ ③ return JSON               │  │ return Plotly JSON           │
└──────────────────────────────┘  └──────────────────────────────┘
```

### 9.1 计算复杂度

| 操作 | 时间复杂度 | 实际耗时 |
|------|-----------|---------|
| `pd.read_csv()` | O(n) | ~10ms (150 行) |
| `df.describe()` | O(n·c) | ~5ms |
| `df.corr()` | O(n·c²) | ~5ms (8 列) |
| `LinearRegression().fit()` | O(n·c²) | ~1ms |
| `LogisticRegression().fit()` | O(iter·n·c) | ~50ms (max_iter=1000) |
| `px.scatter().to_json()` | O(n) | ~50ms |

> 全流程无 LLM 调用无网络请求，Excel 级别的数据量（数千行×数十列）通常在 **毫秒级** 完成。

---

## 10. 附录：与其他模块的对比

### 10.1 分析模块一览

| 维度 | 表格数据分析 | RAG 问答 | 文献综述 | 研究空白分析 | 实验设计 |
|------|-----------|---------|---------|------------|---------|
| 是否用 LLM | **❌** | ✅ (6次) | ✅ (N+4次) | ✅ (1次) | ✅ (2-4次) |
| 执行方式 | 同步 | 同步 | 异步 | 异步 | 同步 |
| 外部依赖 | sklearn, plotly | DeepSeek API | DeepSeek API | BERTopic + DeepSeek API | DeepSeek API |
| 计算模型 | 统计/ML | 语义检索 | 语义生成 | 主题建模 | 语义生成 |
| 数据量 | 数千行 | 知识库级 | 知识库级 | 全知识库 | Top-5 检索 |
| 交互模式 | 两阶段表单 | 单次问答 | 三步向导 | 一键触发 | 三步向导 |

### 10.2 设计亮点

1. **零 LLM 成本**：这是项目中唯一不依赖外部 AI API 的分析功能。所有计算都在本地完成（sklearn + plotly），无速率限制、无 Token 消耗。

2. **两阶段交互**：与"上传即分析"的一次性模式不同，本模块允许用户先看到所有列名和基础统计，再决定分析哪些变量——这种"先探索、再分析"的流程更符合数据科学的工作习惯。

3. **固定随机种子**：`train_test_split(random_state=42)` 确保同一份数据多次分析结果一致，这是科研可复现性的基本要求。

4. **Redis 间接寻址**：`file_id` → 文件路径的间接映射，隔离了前端与文件系统——前端从不知道文件的实际存储位置。

### 10.3 已知问题与改进方向

#### 问题 1：前端状态管理 bug — 回归和可视化共享 Form

**位置**：[TabularDataAnalysisPage.tsx:179-195](frontend/src/pages/TabularDataAnalysisPage.tsx#L179)

回归和可视化两个 Card 都使用同一个 `form` 实例：

```typescript
const [form] = Form.useForm();
// 回归: <Form form={form} onSubmit={...onRegressionSubmit}>
// 可视化: <Form form={form} onSubmit={...onVisSubmit}>
```

当用户在回归表单中选择 `dependent_var: "yield"`，然后切换到可视化表单——`form.getFieldsValue(true)` 会同时读取两个表单的所有值。这可能导致字段混淆。

**修复建议**：使用两个独立的 Form 实例：

```typescript
const [regressionForm] = Form.useForm();
const [visForm] = Form.useForm();
```

#### 问题 2：临时文件无自动清理

`temp_files/` 目录中的文件在 Redis key 过期后不会被自动删除，导致磁盘空间泄漏（虽然 CSV/XLSX 文件通常很小）。

#### 问题 3：逻辑回归无系数输出

线性回归返回 `coefficient` 和 `intercept`，但逻辑回归只返回 `accuracy` 和 `confusion_matrix`，没有返回各特征的系数（odds ratio）。对于有意义的模型解释，系数是重要的信息。

#### 问题 4：只支持 Pearson 相关

相关性矩阵只计算 Pearson 相关系数，不提供 Spearman（秩相关）或 Kendall 选项。对于非线性单调关系，Spearman 可能更合适。
