# MinerU for Embedded — 嵌入式领域文档解析优化

> 本项目 Fork 自 [opendatalab/MinerU](https://github.com/opendatalab/MinerU)，核心目标是对嵌入式领域文档（数据手册、参考手册、硬件规格书、电路图说明等）进行针对性解析优化，使技术文档中的表格、公式、流程图、架构图等内容能被更准确地提取和结构化。

MinerU 是一个高性能多后端文档解析引擎，可将 **PDF / 图片 / DOCX / PPTX / XLSX** 转化为结构化 **Markdown** 和 **JSON**。本项目保留其全部核心能力，并在此基础上针对嵌入式领域文档做适配增强。

---

## 与原项目的差异

### 保留的核心能力

- **多后端解析**：Pipeline（传统 ML 模型，快速稳定）、VLM（视觉语言大模型，高精度）、Hybrid（VLM 布局 + ML 细化，精度最优）
- **多格式支持**：PDF / PNG / JPEG / WebP / DOCX / PPTX / XLSX
- **丰富输出**：公式转 LaTeX、表格转 HTML/Markdown、图片引用、自动页眉页脚去除
- **109 种语言 OCR** 识别
- **HTTP API 服务**：FastAPI 接口，支持远程调用

### 针对嵌入式领域的定制增强

- **在线多模态视觉模型集成**：接入在线 VLM（如 OpenAI 兼容接口），自动对文档中的技术图表、电路示意图、流程图、架构图等生成语义化文字描述，并以 Markdown 表格 / Mermaid 图表等多种形式呈现，弥补传统 OCR 对复杂技术图片的描述不足
- **精简非核心组件**：移除 Web UI、Docker、CI/CD、在线文档、Demo 等通用分发组件，聚焦核心解析链路，降低维护负担

---

## 架构概览

```
  CLI 入口层 (mineru/cli)
        │
  调度层 (backend 路由分发)
        │
  ┌─────┼─────────┬──────────┐
Pipeline   VLM    Hybrid    Office
(8原子模型) (视觉大模型) (VLM+ML)   (直接转换)
  └─────┴─────────┴──────────┘
        │
  模型层 (mineru/model)
        │
  数据与工具层 (mineru/data + mineru/utils)
```

- **Pipeline**：布局检测(RT-DETR) + OCR(PaddleOCR) + 公式识别(Unimernet) + 表格识别(SLANet+/UNet) → 适合快速批量处理
- **VLM**：视觉语言模型(1.2B–7B)直接逐页理解 → 复杂页面精度最高
- **Hybrid**：VLM 做布局检测 + Pipeline 模型做 OCR/公式/表格细化 → 精度与效率兼顾，默认推荐
- **Office**：DOCX/PPTX/XLSX 直接解析，不经 ML 模型

所有后端统一产出中间 JSON，再由后处理转换为 Markdown / ContentList JSON。

详见 `.codestable/architecture/ARCHITECTURE.md`。

---

## 快速开始

### 环境要求

- Python `>=3.10,<3.14`
- 推荐使用虚拟环境

### 安装

```bash
# 安装核心依赖（含 pipeline + vlm）
pip install -e ".[core]"

# 或按需安装
pip install -e ".[pipeline]"   # 仅传统 ML 后端
pip install -e ".[vlm]"       # 仅 VLM 后端
```

### 配置文件

将 `mineru.template.json` 复制到 `~/mineru.json` 并根据需要修改：

```bash
cp mineru.template.json ~/mineru.json
```

关键配置项：
- `models-dir.pipeline` / `models-dir.vlm` — 模型文件本地路径（首次运行自动下载）
- `llm-aided-config` — 在线 VLM 用于图片语义增强（本文本 Fork 新增特性）

### 模型下载

```bash
mineru-models-download
```

### 命令行使用

```bash
# 默认 Hybrid 后端（推荐）
mineru -p /path/to/document.pdf -o /path/to/output

# Pipeline 后端（快速、低资源）
mineru -p /path/to/document.pdf -o /path/to/output -b pipeline

# VLM 后端（高精度，需先启动推理服务）
mineru -p /path/to/document.pdf -o /path/to/output -b vlm-auto-engine
```

输出目录结构：`{output}/{filename}/{backend_mode}/`，包含 Markdown 文件和中间 JSON。

### 启动 HTTP API 服务

```bash
mineru-api
# 默认监听 http://0.0.0.0:8000
```

POST `/parse` 接口上传文件并获取解析结果。

---

## 项目结构

```
MinerU/
├── mineru/                  # 核心代码
│   ├── cli/                 # CLI 入口、调度层、FastAPI 服务
│   ├── backend/             # 四条解析流水线 (pipeline/vlm/hybrid/office)
│   │   └── vlm/
│   │       └── image_enhance.py  # 🆕 在线多模态 VLM 图片语义增强
│   ├── model/               # 模型推理层 (layout/ocr/mfr/table/vlm/office)
│   ├── data/                # 数据读写抽象层
│   └── utils/               # 工具层 (PDF处理/bbox/配置/枚举)
├── .codestable/             # CodeStable 工程工作流
│   ├── architecture/        # 系统架构文档
│   ├── requirements/        # 能力愿景索引
│   ├── compound/            # 知识沉淀 (explore/learning/trick)
│   └── features/            # 功能 spec
├── pyproject.toml           # 项目元数据与依赖
└── mineru.template.json     # 配置文件模板
```

---

## 二次开发过程：CodeStable 工作流驱动

本项目基于 [CodeStable](https://github.com/liuzhengdongfortest/CodeStable) —— 一个面向严肃工程的 AI 编码工作流体系——完成从 Fork 到定制增强的全过程。CodeStable 将开发活动建模为 **6 个实体**（需求、架构、路线图、特性、问题、知识）和 **3 条流程**（特性引入、问题修复、代码重构），围绕"人"而非 Agent 来编排软件生命周期。

以下按实际操作顺序，展示 CodeStable 如何驱动本次二次开发。

### 第一阶段：接入与认知建立

**`/cs-onboard`** — 在 Fork 后的仓库中初始化 `.codestable/` 骨架，建立工作流所需的目录结构和共享参考文档。

**`/cs-explore`** — 定向探索 MinerU 的全局代码结构。产出 `compound/2026-05-07-explore-system-overview.md`，理清了五层分层（CLI 入口 → 调度层 → 后端流水线 → 模型层 → 数据工具层）、四条解析流水线（Pipeline/VLM/Hybrid/Office）、8 种原子模型、中间 JSON 统一交换格式等核心架构要素。这一步是整个二次开发的认知基础——**不理解上游代码，就不敢动刀**。

**`/cs-arch`** — 基于探索成果回填架构文档。产出 `architecture/ARCHITECTURE.md`（341 行），覆盖五层分层图、7 个 CLI 入口、backend 路由逻辑、四条流水线差异、8 种原子模型列表、中间 JSON 结构、模型单例模式、配置系统、输出路径规则、已知约束等。这是一份"只记现状"的系统地图，后续改代码前必读。

**`/cs-req`** — 回填能力愿景索引。产出 `requirements/VISION.md` + 三份需求文档（`pdf-image-parsing.md`、`office-parsing.md`、`http-api-service.md`），将上游已有的三大核心能力以用户故事形式落档为 current status。

### 第二阶段：范围决策

**`/cs-decide`** — 归档"剥离非核心分发层"的项目级决策。产出 `compound/2026-05-07-decision-strip-non-core-artifacts.md`，明确移除 Web UI（gradio_app.py 1412 行、router.py 1559 行）、18 个 Dockerfile、5 个 GitHub Actions、中英文双语文档（178 个文件）、Demo 和测试框架——总计 -11390 行，聚焦核心解析链路。

### 第三阶段：核心功能开发

**`/cs-feat` → `cs-feat-design`** — 为"在线多模态视觉模型增强图片语义描述"起草方案。产出 `features/2026-05-06-image-semantic-enhancement/image-semantic-enhancement-design.md`，明确动机（本地 VLM 模型对嵌入式领域技术图表描述不足）、边界（不做版面分析替换、不做 Pipeline 集成、不做实时在线服务）、接口契约（`image-description-config` 配置段 + 单一公共函数 `enhance_image_descriptions()`）、主流程（收集 span → 预处理 → API 调用 → 结果回写，6 个挂载点）、验收场景（正常/降级/错误恢复共 15 条）。

**`/cs-feat-impl`** — 按方案写代码。产出：
- 新增 `mineru/backend/vlm/image_enhance.py`（343 行）—— 图片收集、预处理（最长边 2048px）、并发 API 调用（ThreadPoolExecutor max_workers=3）、重试与降级
- 修改 `mineru/utils/config_reader.py` —— 新增 `get_image_description_config()`
- 6 个挂载点接入：`vlm_analyze.py`（sync/async）、`hybrid_analyze.py`（sync/async）、`model_output_to_middle_json.py`、`hybrid_model_output_to_middle_json.py`

**`/cs-feat-accept`** — 验收闭环。产出 `image-semantic-enhancement-acceptance.md`，逐项核对 6 个挂载点接入状态、15 条验收场景、代码质量检查。

### 第四阶段：Bug 修复

**`/cs-issue-report`** — 发现并记录三个问题。产出 `issues/2026-05-06-image-enhance-fixes/image-enhance-fixes-report.md`：span 收集遗漏嵌套结构、Thinking 模型 API 参数不兼容、增强计数虚高——均附复现步骤。根因一眼可见，走快速通道直接进入修复。

**`/cs-issue-fix`** — 定点修复。产出 `image-enhance-fixes-fix-note.md`，单文件修改 `image_enhance.py`（+36/-22 行）：重构 `_collect_image_spans()` 为双路径适配两层嵌套、Thinking 模型名称检测、原始内容快照对比。

### 第五阶段：知识沉淀（复利工程）

开发过程中，CodeStable 的横切沉淀层持续积累可复用知识：

- **`cs-trick`**：
  - `trick-backend-strategy-dispatch` — 用字符串参数 + 条件分支做多后端策略分发模式
  - `trick-window-based-batch-processing` — 窗口式批量处理模式
  - `trick-thread-safe-model-singleton-with-lazy-caching` — 线程安全模型单例 + 延迟缓存模式
- **`cs-learning`**：`learning-middle-json-unified-exchange` — 中间 JSON 作为所有后端统一交换层的设计经验
- **`cs-explore`**：分别探索了 Pipeline、VLM、Hybrid 三个后端的内部实现 (`explore-pipeline-backend-internals`、`explore-vlm-backend-internals`、`explore-hybrid-backend-internals`)

这些沉淀会在后续特性开发和 Bug 修复中被 `cs-feat-design` 和 `cs-issue-analyze` 自动检索复用。

### 工作流全景

```
cs-onboard  →  cs-explore  →  cs-arch  →  cs-req
                                        ↘
                                  cs-decide (范围决策)
                                        ↘
  cs-feat-design  →  cs-feat-impl  →  cs-feat-accept
                                        ↘
  cs-issue-report  ──────────────→  cs-issue-fix (快速通道)
                                        ↓
        横切沉淀层: cs-trick / cs-learn / cs-explore (持续积累)
```

所有 spec、设计文档、验收报告、问题修复记录、架构文档、知识沉淀均持久化在 `.codestable/` 目录下，人和 AI 都能检索和引用。

---

## 许可证

本项目基于 MinerU Open Source License。上游项目地址：https://github.com/opendatalab/MinerU
