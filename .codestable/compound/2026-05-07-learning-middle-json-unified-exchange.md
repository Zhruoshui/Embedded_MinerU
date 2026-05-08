---
doc_type: learning
track: knowledge
date: 2026-05-07
slug: middle-json-as-unified-exchange-layer
topic: 所有后端产出统一中间 JSON 格式，使 Markdown/ContentList 生成逻辑与具体后端无关
tags: [middle-json, architecture, exchange-format, pluggable-backend]
status: active
---

## 情境

MinerU 有 4 套后端流水线（pipeline/vlm/hybrid/office），每套用不同的模型和技术栈处理文档。如果不做统一，每套后端各自生成 Markdown 的代码会大量重复且行为不一致。

## 发现的做法

所有后端产出相同结构 `middle_json`：`{"pdf_info": [...], "_backend": "xxx", "_version_name": "..."}`。每个 `pdf_info` 元素是一个页面，包含 `preproc_blocks`（正文 block）、`discarded_blocks`（丢弃 block）、`page_size`、`page_idx`。

**代码体现**：
- Pipeline: `model_json_to_middle_json.py:286` — `init_middle_json()` 标记 `_backend: "pipeline"`
- VLM: `model_output_to_middle_json.py:110` — 同样 `_backend: "vlm"`
- Hybrid: `hybrid_model_output_to_middle_json.py` — 复用 pipeline 结构

**边界处理**：不同后端产出的 block 类型不同——Pipeline 用 `ContentType`（`enum_class.py:52`），VLM/Hybrid 用 `ContentTypeV2`（`enum_class.py:64`，多了 CODE/ALGORITHM/TABLE_SIMPLE 等）。Markdown 生成时按 `_backend` 区分处理。

## 为什么有价值

- **后端可插拔**：新增一个后端只需实现 `init_middle_json()` + `append_xxx_to_middle_json()` + `finalize_middle_json()` 三个函数
- **输出格式统一**：Markdown/ContentList 生成代码只依赖 `pdf_info` 结构，不知道数据来自哪个后端
- **中间格式可调试**：`f_dump_middle_json=True` 时所有后端都输出相同格式的 JSON，方便对比和调试

## 不这样做会出什么问题

- 每个后端各自写一套 Markdown 生成，行为不一致（公式格式、表格样式不同）
- 新增输出格式（如 HTML）需要每个后端都实现一遍
- 调试时不知道不同后端产出的区别在哪一层

## 相关文档

- `mineru/backend/pipeline/model_json_to_middle_json.py:286`
- `mineru/backend/vlm/model_output_to_middle_json.py:110`
- `mineru/utils/enum_class.py` — ContentType / ContentTypeV2 定义
- `.codestable/architecture/ARCHITECTURE.md` — 架构总入口 §3.1
