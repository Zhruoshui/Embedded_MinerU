---
doc_type: trick
type: pattern
date: 2026-05-07
slug: window-based-multi-document-batch-processing
topic: 用固定大小的处理窗口跨文档混合编批，分摊模型加载成本并控制显存峰值
language: python
tags: [batch-processing, window, multi-document, memory-management, pipeline]
status: active
---

## 适用场景

需要批量解析大量文档/页面，每次模型加载成本高但单页推理量小。不想每页都重新加载模型，也不想一次把全部页面加载进显存导致 OOM。

## 做法

固定窗口大小（默认 64 页），从多文档交叉提取页面编成一批，一次模型调用处理整批，结果按来源文档回填：

```python
# pipeline_analyze.py:196-259 — 窗口循环
window_size = get_processing_window_size(default=64)
while processed_pages < total_pages:
    batch_capacity = window_size
    for context in doc_contexts:
        if batch_capacity == 0:
            break
        # 从当前文档取待处理页面
        take_count = min(batch_capacity, context['page_count'] - page_start)
        # 渲染 + 收集
        batch_images.extend(render_pages(context, page_start, take_count))
        # 记录来源用于回填
        batch_payloads.append((context, page_start, take_count))
        batch_capacity -= take_count

    # 一次模型调用处理整批
    batch_results = batch_image_analyze(batch_images, ...)

    # 按来源回填到各文档的 middle_json
    for context, page_start, take_count in batch_payloads:
        context['middle_json'] += batch_results[...]
```

## 为什么有效

- **模型加载成本分摊**：窗口内的所有页面共享一次模型推理调用，页面数越多单页成本越低
- **显存可控**：窗口大小限制同时处理的页面数，显存占用可预测
- **跨文档公平**：多文档交替编批，不会出现先处理的文档占满显存导致后续文档饿死
- **进度可观测**：窗口作为进度的自然单位，日志清晰（`Processing window batch 3/8: 64/200 pages`）

## 示例

Pipeline 窗口流（`pipeline_analyze.py:140-320`）：
- 窗口大小：64 页（可配置）
- 多文档交替编批
- 一次 `batch_image_analyze()` 处理整批

Hybrid 窗口流（`hybrid_analyze.py:590-649`）：
- 窗口大小：64 页，单文档
- 窗口内 VLM 先做布局，Pipeline 模型做精细化
- batch_ratio 按 GPU 显存自适应

## 何时不适用

- 实时/交互式场景——单页实时解析不需要窗口批处理
- 模型推理很快且单页就占满显存——窗口没有收益

## 相关文档

- `mineru/backend/pipeline/pipeline_analyze.py:140-320`
- `mineru/backend/hybrid/hybrid_analyze.py:545-670`
- `mineru/utils/config_reader.py` — `get_processing_window_size`
