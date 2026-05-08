---
doc_type: architecture
slug: ARCHITECTURE
scope: MinerU 全局系统架构——五层分层、四条解析流水线、模型层按任务划分
summary: MinerU 是一个多后端文档解析工具，将 PDF/图片/Office 文档转化为 Markdown/JSON。架构围绕"CLI 入口 → 调度层 → 后端流水线 → 模型推理"四层核心链路构建，通过中间 JSON 统一所有后端的输出格式。
status: current
last_reviewed: 2026-05-07
tags: [system-map, architecture, pipeline, vlm, hybrid, office, model]
depends_on: []
implements: []
---

# MinerU 架构总入口

## 0. 术语

| 术语 | 定义 | 区分 |
|------|------|------|
| **Middle JSON** | 所有后端产出的一致中间表示格式，由 `pdf_info` 列表构成，每个元素是一个页面的结构化解析结果 | 不同于最终 Markdown/ContentList 输出，是"模型输出 → 用户输出"之间的通用交换层 |
| **BlockType** | 页面布局级别的块类型（如 TEXT、TABLE、IMAGE、TITLE） | 与 ContentType 不同：BlockType 描述页面位置上的块，ContentType 描述最终输出的内容类型 |
| **ContentType / ContentTypeV2** | 细粒度内容类型（如 inline_equation、image、text） | ContentType 用于传统 pipeline，ContentTypeV2 用于 VLM/Hybrid 扩展类型 |
| **Backend** | 解析策略实现，决定用哪套模型、走哪条加工链路 | 本术语在代码中有时指 VLM 推理引擎名（如 `vllm-engine`），本架构文档后端指 `mineru/backend/` 下的四套流水线系统 |
| **VLM** | Vision-Language Model，视觉语言模型（1.2B–7B 参数） | 区别于 pipeline 的独立小模型（RT-DETR 布局 / PaddleOCR / Unimernet 公式） |
| **Magic Model** | 流水线最后一步的后处理"魔术模型"，负责从原始模型输出组装结构化页面内容 | 不同后端各有一个独立的 MagicModel 实现 |
| **Atom Model** | Pipeline 后端中的 8 种原子模型，每种负责一个独立任务（布局检测/OCR/公式/表格等） | Hybrid 从 pipeline 复用这些原子模型做精细化 |

## 1. 定位与受众

MinerU 是一个**多格式文档解析工具**，输入 PDF、图片（PNG/JPEG/WebP）、Office 文档（DOCX/PPTX/XLSX），输出 Markdown、ContentList JSON 和中间 JSON。

**架构读者**：
- `cs-feat-design`：新增后端流水线或模型时需要理解模块划分和接口契约
- `cs-issue-analyze`：根据错误现象沿调用链定位模块边界
- 新人上手：了解系统整体布局、入口点、核心数据流

**读完能干嘛**：定位任意功能的代码入口、理解四条流水线差异和选择依据、知道中间 JSON 的结构和各模块在流水线中的位置。

## 2. 结构与交互

### 2.1 五层分层

```
┌──────────────────────────────────────────────┐
│  CLI 入口层  (mineru/cli)                      │
│  client.py / fast_api.py / vlm_server.py       │
│  命令解析、服务生命周期、任务编排               │
├──────────────────────────────────────────────┤
│  调度层  (cli/common.py)                       │
│  do_parse() → 按 backend 参数分发              │
│  aio_do_parse() → 异步分发                     │
├──────────────┬──────────────┬─────────────────┤
│  Pipeline    │  VLM         │  Hybrid         │ ← Office
│  (传统ML模型) │  (视觉语言)   │  (VLM布局+ML细化) │ (直接转换)
├──────────────┴──────────────┴─────────────────┤
│  模型层  (mineru/model)                        │
│  layout / ocr / mfr / table / vlm / ori_cls    │
│  docx / pptx / xlsx                            │
├──────────────────────────────────────────────┤
│  数据与工具层  (mineru/data + mineru/utils)     │
│  文件读写抽象 / PDF处理 / 配置 / bbox / 枚举    │
└──────────────────────────────────────────────┘
```

**为什么这么分**：入口和调度分离使得 CLI `client.py`（用户命令）和 `fast_api.py`（HTTP 服务）共享同一套调度逻辑；后端流水线作为策略模式可插拔，新增一类后端只需增加 `_process_xxx` 函数而无需改动调度骨架；模型层独立使得每个 ML 任务（如表格识别）可以独立升级版本而不影响其他模型。

### 2.2 CLI 入口层

七个 CLI 脚本入口（`pyproject.toml:124-130`）：

| 命令 | 入口函数 | 用途 |
|------|----------|------|
| `mineru` | `mineru.cli.client:main` | 主解析命令，编排单/多文档解析任务 |
| `mineru-api` | `mineru.cli.fast_api:main` | 启动 FastAPI 解析服务（HTTP 上传接口） |
| `mineru-vllm-server` | `mineru.cli.vlm_server:vllm_server` | 启动 VLLM 推理服务 |
| `mineru-lmdeploy-server` | `mineru.cli.vlm_server:lmdeploy_server` | 启动 LMDeploy 推理服务 |
| `mineru-openai-server` | `mineru.cli.vlm_server:openai_server` | 启动 OpenAI 兼容推理服务 |
| `mineru-models-download` | `mineru.cli.models_download:download_models` | 下载模型文件 |

`client.py` 的工作流：将输入文件按后缀分类（`mineru/cli/client.py:50-56` — `InputDocument` dataclass），为每个文件启动本地 `fast_api.py` 子进程（`cli/api_client.py:407`），通过 HTTP 发送任务请求，等待完成。

`fast_api.py` 内部通过 `do_parse()` / `aio_do_parse()` 调用后端。

### 2.3 调度层：backend 路由

`mineru/cli/common.py:619-708` — `do_parse()` 按 `backend` 参数分发：

```
backend = "pipeline"  → _process_pipeline()       # line 664
backend = "vlm-*"     → _process_vlm()            # line 683
backend = "hybrid-*"  → _process_hybrid()         # line 703
输入后缀 ∈ {docx, pptx, xlsx} → _process_office_doc()  # line 641（先于 PDF 处理）
```

异步版本 `aio_do_parse()`（`mineru/cli/common.py:711`）对 vlm/hybrid 使用 `async` 版本的处理函数。

**调度层的依赖检查**：
- Hybrid 后端需要 `torch`（复用 pipeline 模型）：`mineru/cli/common.py:60-64` — `ensure_backend_dependencies()`
- VLM 推理引擎自动检测：`mineru/utils/engine_utils.py:34` — `get_vlm_engine()` 根据环境自动选择 vllm/lmdeploy/mlx

### 2.4 后端流水线层

#### Pipeline 后端（传统 ML 全链路）
`mineru/backend/pipeline/`

**工作流**：PDF → 图片化（`load_images_from_pdf_doc`，`pipeline_analyze.py:21`）→ 8 种原子模型并行推理 → 原始结果 → `MagicModel` 页面组装 → 中间 JSON → Markdown/ContentList

**8 种原子模型**（`mineru/backend/pipeline/model_list.py:2-10` — `AtomicModel` 类）：
1. `Layout` — DocLayoutV2 布局检测（RT-DETR）
2. `MFD` — 数学公式检测
3. `MFR` — 数学公式识别（Unimernet / FormulaNet）
4. `OCR` — PaddleOCR 文本检测+识别
5. `WirelessTable` — 无线表格识别（SLANet+）
6. `WiredTable` — 有线表格识别（UNet）
7. `TableCls` — 表格分类器
8. `ImgOrientationCls` — 图片方向分类

**模型初始化**：`mineru/backend/pipeline/model_init.py:33-90` — 每个模型有独立初始化函数，共享 OCR 引擎实例；`ModelSingleton`（`pipeline_analyze.py:33`）负责模型缓存，按 `(lang, formula_enable, table_enable)` 三元组 key 复用。

**中间 JSON 构造**：`mineru/backend/pipeline/model_json_to_middle_json.py:290` — `result_to_middle_json()` 是入口，将模型输出列表、图片列表、PDF 文档对象写入统一的 `pdf_info` 结构。

**后处理（MagicModel）**：`mineru/backend/pipeline/pipeline_magic_model.py:17` — `MagicModel` 类接收 `page_model_info`，处理 bbox 修正、span 合并、段落拆分、图片/表格截图等，最终产出结构化页面 block。

#### VLM 后端（视觉语言模型全链路）
`mineru/backend/vlm/`

**工作流**：PDF → 图片化 → 发送给 VLM 模型推理 → 模型输出 JSON → 中间 JSON → Markdown/ContentList

**与 pipeline 的本质区别**：不再拆分 8 种任务，而是让一个大 VLM（1.2B–7B）直接理解整个页面，一次性输出结构化布局+文本+公式+表格。

**核心入口**：`mineru/backend/vlm/vlm_analyze.py:44` — `ModelSingleton` 管理 VLM 模型实例；支持三种推理引擎后端：vllm（`model/vlm/vllm_server.py`）、lmdeploy（`model/vlm/lmdeploy_server.py`）、mlx（macOS）。

**模型输出转中间 JSON**：`mineru/backend/vlm/model_output_to_middle_json.py:110` — `init_middle_json()` 标记 `_backend: "vlm"`；页面信息通过 `append_page_blocks_to_middle_json()` 逐页追加。

#### Hybrid 后端（VLM 布局 + Pipeline 细化）
`mineru/backend/hybrid/`

**工作流**：PDF → VLM 做**布局检测** → Pipeline 模型做**OCR/MFR/表格细化** → 中间 JSON → Markdown/ContentList

**核心入口**：`mineru/backend/hybrid/hybrid_analyze.py:55` — `ocr_classify()` 判断是否需要 OCR；`mineru/backend/hybrid/hybrid_analyze.py:710` 附近 `logger.info("Hybrid processing-window run")` 标记窗口式批量处理。

**Hybrid 的独特价值**：VLM 的布局检测能力优于 DocLayoutV2，但 VLM 的 OCR/公式识别不如专用模型精确。Hybrid 结合两者优势——VLM 做布局，Pipeline 做精细化提取，精度最高。

**依赖关系**：Hybrid 同时导入 `pipeline/model_init.py`（`HybridModelSingleton`，line 21）和 `vlm/vlm_analyze.py`（`ModelSingleton`，line 22），是 pipeline 和 vlm 的上层组合。

#### Office 后端（Office 文档直接转换）
`mineru/backend/office/`

**不经过 ML 模型**，直接用文档解析库提取结构：
- `docx_analyze.py` — DOCX → MD（`python-docx` + `mammoth`）
- `pptx_analyze.py` — PPTX → MD（`pypptx-with-oxml`）
- `xlsx_analyze.py` — XLSX → MD/CSV（`openpyxl`）

**调度入口**：`mineru/cli/common.py:569-616` — `_process_office_doc()` 按文件后缀分发到对应分析器；Office 文档在 PDF 处理之前先被提取并从后续队列中移除（line 652-655）。

### 2.5 模型层

`mineru/model/` 按 ML 任务划分子目录，每个子目录是一个独立的推理模型实现：

| 子目录 | 模型 | 文件 |
|--------|------|------|
| `layout/` | DocLayoutV2 (RT-DETR) | `pp_doclayoutv2.py` |
| `ocr/` | PaddleOCR PyTorch 移植 | `pytorch_paddle.py` |
| `mfr/unimernet/` | Unimernet（公式识别） | `Unimernet.py` |
| `mfr/` | FormulaNet（中文公式） | `pp_formulanet_plus_m/` |
| `table/cls/` | 表格分类 | `paddle_table_cls.py` |
| `table/rec/slanet_plus/` | SLANet+ 无线表格 | `main.py` |
| `table/rec/unet_table/` | UNet 有线表格 | `main.py` |
| `vlm/` | VLM 推理服务 | `vllm_server.py` / `lmdeploy_server.py` |
| `ori_cls/` | 文档方向分类 | `paddle_ori_cls.py` |
| `docx/` `pptx/` `xlsx/` | Office 文档解析模型 | 各含 `__init__` + 处理逻辑 |

**为什么模型层独立于后端**：同一个模型（如 PaddleOCR）被 pipeline、hybrid 两个后端复用；模型实现可以独立升级（如替换 OCR 引擎）而不影响后端流水线编排逻辑。

跨后端共享：`model/utils/` 目录提供 PaddleOCR predictor 等共享工具。

### 2.6 数据读写抽象层

`mineru/data/data_reader_writer/base.py:6-52` — `DataReader` / `DataWriter` 两个抽象基类。

| 实现 | 文件 | 存储后端 |
|------|------|----------|
| `FileBasedDataReader` / `FileBasedDataWriter` | `filebase.py` | 本地文件系统 |
| `S3DataReader` / `S3DataWriter` | `s3.py` | 单桶 S3 |
| `MultiBucketS3DataReader` / `MultiBucketS3DataWriter` | `multi_bucket_s3.py` | 多租户多桶 S3 |
| `DummyDataWriter` | `dummy.py` | 空实现（测试用） |

所有实现通过 `data/data_reader_writer/__init__.py` 统一导出。

**为什么需要抽象**：同一套解析逻辑需要在三种部署场景下运行——本地文件、单桶 S3 云端处理、多用户多桶 SaaS 场景。抽象层让后端流水线只依赖 `DataWriter` 接口写图片和结果，不关心底层存储。

`mineru/data/io/` 子目录提供下载器抽象（`http.py`、`s3.py`），与写入器对称。

### 2.7 工具层

`mineru/utils/` 包含 30+ 个跨模块工具，按功能聚为几类：

- **PDF 处理**：`pdf_image_tools.py`（PDF→图片）、`pdf_reader.py`、`pdfium_guard.py`（生命周期管理）、`pdf_classify.py`（分类为扫描件/电子件）
- **布局/BBox**：`bbox_utils.py`、`boxbase.py`（bbox 距离/重叠计算）、`span_block_fix.py`（span→行/block 合并）
- **枚举定义**：`enum_class.py`（BlockType/ContentType/MakeMode/ModelPath 等）
- **配置**：`config_reader.py`（`mineru.json` 配置读写）
- **VLM 引擎**：`engine_utils.py`（自动选择推理引擎）、`vlm_server.py`
- **OCR 辅助**：`ocr_utils.py`（`OcrConfidence`、旋转修正）
- **其他**：`language.py`（语言列表）、`hash_utils.py`、`llm_aided.py`（LLM 辅助标题识别）、`char_utils.py`（全角半角转换）

## 3. 数据与状态

### 3.1 中间 JSON（Middle JSON）— 后端统一的交换格式

所有后端产出的中间 JSON 结构相同（以 pipeline 为例，`mineru/backend/pipeline/model_json_to_middle_json.py:286`）：

```python
{
    "pdf_info": [
        {
            "preproc_blocks": [...],   # 正文区块（文本/标题/列表/公式/表格/图片/图表/代码）
            "discarded_blocks": [...], # 被丢弃的区块（页眉/页脚/页码/旁注等）
            "page_size": [w, h],       # 页面物理尺寸
            "page_idx": 0,             # 页码（0-based）
            "image_spans": [...],      # 需要截图的 span（图片/表格区域裁剪）
        },
        ...
    ],
    "_backend": "pipeline" | "vlm" | "hybrid",  # 标记来源后端
    "_version_name": "x.y.z"
}
```

VLM 和 Hybrid 后端同样产出此结构，`_backend` 字段标记来源以支持差异化后处理。

### 3.2 核心枚举类型

**BlockType**（`mineru/utils/enum_class.py:4-51`）— 页面布局级别分类，包括正文（TEXT、TITLE、LIST 等）、媒体（IMAGE、TABLE、CHART）、公式（INTERLINE_EQUATION、EQUATION）、元数据（HEADER、FOOTER、PAGE_NUMBER）、VLM 扩展（CODE、ALGORITHM、REF_TEXT、ABSTRACT 等）。

**ContentType**（`mineru/utils/enum_class.py:52-61`）— 内容输出类型，比 BlockType 更细（如区分 interline_equation 和 inline_equation、IMAGE/TABLE/CHART/SEAL）。

**ContentTypeV2**（`mineru/utils/enum_class.py:64-89`）— VLM/Hybrid 后端的扩展内容类型，增加 CODE、ALGORITHM、TABLE_SIMPLE/TABLE_COMPLEX、PAGE_HEADER/FOOTER/FOOTNOTE/ASIDE_TEXT 等。

**MakeMode**（`mineru/utils/enum_class.py:92-96`）— 输出模式：
- `MM_MD` — 魔术模型 Markdown（默认）
- `NLP_MD` — NLP Markdown
- `CONTENT_LIST` / `CONTENT_LIST_V2` — 结构化 JSON 输出

**ModelPath**（`mineru/utils/enum_class.py:99-111`）— 模型下载路径定义（HuggingFace 和 ModelScope 两种源），包括 VLM 模型（`MinerU2.5-Pro-2604-1.2B`）和 Pipeline 模型包（`PDF-Extract-Kit-1.0`）。

### 3.3 模型单例（Model Singleton）

Pipeline 和 VLM 后端各自使用线程安全的单例模式缓存模型实例：

- **Pipeline**：`mineru/backend/pipeline/pipeline_analyze.py:33` — `ModelSingleton`，锁 `PIPELINE_MODEL_INIT_LOCK`（`model_init.py:21`），按 `(lang, formula_enable, table_enable)` key 缓存
- **VLM**：`mineru/backend/vlm/vlm_analyze.py:44` — `ModelSingleton`，锁 `threading.RLock()`，按 `(backend, model_path, server_url)` key 缓存

**为什么用单例**：模型加载开销大（秒级到分钟级），多文档批量处理时不应反复加载。单例模式确保同一进程生命周期内每个配置组合只加载一次。

### 3.4 配置系统

**配置文件** `~/mineru.json`（模板 `mineru.template.json` 在项目根目录）：`mineru/utils/config_reader.py:14` — 通过环境变量 `MINERU_TOOLS_CONFIG_JSON` 可覆盖路径。

配置包含：
- `bucket_info` — S3 多桶 AK/SK/Endpoint（`config_reader.py:33-48` — `get_s3_config()`）
- `models-dir` — 模型文件本地路径（pipeline 和 vlm 分开指定）
- `latex-delimiter-config` — LaTeX 公式定界符（`$$` / `$`）
- `llm-aided-config` — LLM 辅助标题识别（阿里云 DashScope API）
- `config_version` — 配置文件版本号

**设备选择**：`mineru/utils/config_reader.py:75` — `get_device()` 优先读 `MINERU_DEVICE_MODE` 环境变量，fallback 到 CUDA/MPS/NPU/CPU 自动检测。

### 3.5 输出路径规则

`mineru/cli/output_paths.py` 和 `mineru/cli/common.py:99-100` 定义了输出目录命名规则：`{output_dir}/{task_stem}/{backend_mode}/`，文件名 stem 截断到 200 UTF-8 字节以内（避免文件系统路径过长）。

## 4. 关键决策

> 当前无已落档的决策文档。以下方向性选择已在代码中体现，但尚未形成正式 decision：

- **中间 JSON 作为统一交换层**：所有后端产出相同结构，便于下游 Markdown 生成和 ContentList 转换统一处理。TODO: 应沉淀为 decision。
- **Pipeline 的 8 原子模型 vs VLM 的单模型**：精度-速度-资源三元权衡的设计选择。TODO: 应沉淀为 decision。
- **Hybrid 作为推荐默认后端**（`backend="hybrid-auto-engine"`）：在多数场景下精度最优。TODO: 应沉淀为 decision。

## 5. 代码锚点

想看代码从这里开始：

| 路径 | 函数/类 | 说明 |
|------|---------|------|
| `mineru/cli/client.py:main` | `main()` | 主 CLI 入口，命令行 `mineru` |
| `mineru/cli/fast_api.py:main` | `main()` | FastAPI 服务入口 |
| `mineru/cli/common.py:619` | `do_parse()` | 同步后端调度器 |
| `mineru/cli/common.py:711` | `aio_do_parse()` | 异步后端调度器 |
| `mineru/cli/common.py:663-708` | — | backend 参数分发逻辑 |
| `mineru/backend/pipeline/model_list.py:2` | `AtomicModel` | Pipeline 8 种原子模型枚举 |
| `mineru/backend/pipeline/model_init.py:33-90` | `*_model_init()` | 各模型初始化函数 |
| `mineru/backend/pipeline/pipeline_analyze.py:33` | `ModelSingleton` | Pipeline 模型单例缓存 |
| `mineru/backend/pipeline/model_json_to_middle_json.py:286` | `init_middle_json()` | 中间 JSON 结构定义 |
| `mineru/backend/pipeline/pipeline_magic_model.py:17` | `MagicModel` | Pipeline 后处理魔术模型 |
| `mineru/backend/vlm/vlm_analyze.py:44` | `ModelSingleton` | VLM 模型单例缓存 |
| `mineru/backend/vlm/model_output_to_middle_json.py:110` | `init_middle_json()` | VLM 中间 JSON 结构 |
| `mineru/backend/hybrid/hybrid_analyze.py` | `doc_analyze()` | Hybrid 流水线入口 |
| `mineru/utils/enum_class.py` | `BlockType` / `ContentType` / `ContentTypeV2` / `MakeMode` | 核心枚举定义 |
| `mineru/data/data_reader_writer/base.py:6` | `DataReader` / `DataWriter` | 数据读写抽象基类 |
| `mineru/data/data_reader_writer/__init__.py` | — | 所有读写器实现导出 |
| `mineru/utils/config_reader.py:17` | `read_config()` | 配置文件读取入口 |
| `mineru/utils/config_reader.py:75` | `get_device()` | 设备自动检测 |
| `mineru/utils/engine_utils.py:34` | `get_vlm_engine()` | VLM 推理引擎自动选择 |
| `pyproject.toml:124-130` | — | 7 个 CLI 脚本入口定义 |
| `pyproject.toml:70-115` | — | 可选依赖分组（vlm/pipeline/core/all） |

## 6. 已知约束 / 边界情况

### 硬约束

1. **Python 版本**：`>=3.10,<3.14`（`pyproject.toml:12`）
2. **Pipeline 后端必须有 torch**：包含在 `mineru[pipeline]` 可选依赖中（`pyproject.toml:93-105`）
3. **Hybrid 后端依赖 pipeline**：运行时动态 import，若 `torch` 不可用抛 `HybridDependencyError`（`mineru/cli/common.py:47-64`）
4. **CUDA 环境变量**：启动时自动设置 `TORCH_CUDNN_V8_API_DISABLED=1`（`mineru/cli/client.py:47`）
5. **VLM 推理引擎的自动检测**：`get_vlm_engine()` 按优先级检测可用引擎——`vllm` → `mlx`（只 macOS）→ `lmdeploy`（`mineru/utils/engine_utils.py:34`）
6. **模型文件先下载后使用**：`mineru/backend/pipeline/model_init.py:18` 引入 `auto_download_and_get_model_root_path`，自动从 ModelScope/HuggingFace 下载缺失的模型
7. **任务文件名限制**：输出目录的 task stem 截断为 200 UTF-8 字节（`mineru/cli/common.py:44` — `MAX_TASK_STEM_BYTES`）
8. **VLM 离线模式下无法自动下载**：VLM 模型（1.2B–7B 参数）需要提前下载到 `models-dir` 或依赖运行时下载
9. **MPS fallback**：Pipeline 后端自动设置 `PYTORCH_ENABLE_MPS_FALLBACK=1`（`pipeline_analyze.py:30`）

### 已知边界情况

1. **PDF 文本提取 vs OCR**：`parse_method='auto'` 模式下通过 `pdf_classify.py` 判断 PDF 是电子件（直接提取文本）还是扫描件（需 OCR）；来源 `mineru/utils/pdf_classify.py`
2. **跨页表格合并**：`mineru/backend/utils/runtime_utils.py` — `cross_page_table_merge()`，来源 `model_json_to_middle_json.py:10`
3. **VLM 并发控制**：FastAPI 模式下通过 `mineru/cli/api_protocol.py` 的 `DEFAULT_MAX_CONCURRENT_REQUESTS` 和 `DEFAULT_PROCESSING_WINDOW_SIZE` 控制并发
4. **内存清理策略**：Pipeline 每处理 ≥10 页触发一次显存清理（`mineru/backend/pipeline/model_json_to_middle_json.py:282-283`），可通过 `MINERU_DONOT_CLEAN_MEM` 环境变量禁用

## 7. 相关文档

- `.codestable/compound/2026-05-07-explore-system-overview.md` — 系统全局模块划分探索记录（更详细的文件级目录树）
- `.codestable/attention.md` — 项目注意事项（编译/运行/测试/命令陷阱）
- `.codestable/reference/shared-conventions.md` — CodeStable 共享口径
- `mineru/cli/client.py` — 主 CLI 入口（1124 行）
- `mineru/cli/common.py` — 调度核心（814 行）
- `mineru/backend/pipeline/model_list.py` — 8 种原子模型定义
- `mineru/utils/enum_class.py` — 所有核心枚举（136 行）
- `pyproject.toml` — 依赖/脚本/包配置

## 变更日志

- 2026-05-07：初始回填版本，基于 `compound/2026-05-07-explore-system-overview.md` 探索成果和代码验证。
