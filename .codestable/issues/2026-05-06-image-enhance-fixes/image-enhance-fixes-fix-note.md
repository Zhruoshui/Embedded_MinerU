---
doc_type: fix-note
issue: image-enhance-fixes
status: resolved
date: 2026-05-06
severity: medium
root_cause_type: implementation-error
summary: 1. span 收集适配两层嵌套块结构 2. Thinking 模型 API 参数兼容 3. 增强计数逻辑修正
tags: [image-description, bug-fix, vlm]
---

# 修复记录：图片描述增强三个问题

## 1. 根因

三个问题均在同一文件 `mineru/backend/vlm/image_enhance.py`，为初次实现时的遗漏。

### 问题 1：span 收集遗漏嵌套结构

**根因**：`_collect_image_spans()` 仅遍历了 `BlockType.IMAGE_BODY` / `BlockType.CHART_BODY` 的扁平结构，未处理 MagicModel 输出的两层嵌套结构 `IMAGE/CHART → blocks → IMAGE_BODY/CHART_BODY → lines → spans`。

**修复**：重构 `_collect_image_spans()` 为双路径：
- 遇到 `BlockType.IMAGE` / `BlockType.CHART` → 遍历 `block["blocks"]` 找子块 `IMAGE_BODY/CHART_BODY`，调用共享的 `_extract_spans_from_block()`
- 遇到 `BlockType.IMAGE_BODY` / `BlockType.CHART_BODY` → 直接调用 `_extract_spans_from_block()`
- 抽取 `_extract_spans_from_block()` 内部函数消除代码重复

### 问题 2：Thinking 模型 API 参数不兼容

**根因**：对所有 `enable_thinking=true` 的配置都通过 `api_params["extra_body"] = {"enable_thinking": True}` 传参，但 Qwen3-VL-32B-Thinking 在 SiliconFlow API 中已内置 thinking 模式，通过模型名后缀识别，不接受此额外参数。

**修复**：
```python
enable_thinking = config.get("enable_thinking", True)
if enable_thinking and config.get("model", "").endswith("Thinking"):
    pass  # thinking already enabled in model name
elif enable_thinking:
    api_params["extra_body"] = {"enable_thinking": True}
```

### 问题 3：增强计数逻辑不准确

**根因**：原逻辑仅检查 `span["content"].strip()` 非空即计为 `enhanced_count++`，未对比增强前后的实际内容。

**修复**：在 `enhance_image_descriptions()` 中增加原始内容快照：
```python
original_contents = {}
for span_info in image_spans:
    original_contents[id(span_info["span"])] = span_info["span"].get("content", "")
```
统计时对比新的 `content` vs 原始值，仅在不相等时 `enhanced_count++`。

## 2. 修改文件

| 文件 | 改动 |
|------|------|
| `mineru/backend/vlm/image_enhance.py` | 修改 `_call_vision_api_sync()`（+5 行）、重构 `_collect_image_spans()`（+20/-15 行）、`enhance_image_descriptions()` 增加原始内容快照（+5/-3 行） |

总计：+36 行 / -22 行，仅影响 `image_enhance.py`。

## 3. 验证

- [x] `_collect_image_spans()` 双路径逻辑通过代码审查——无多余分支，无遗漏路径
- [x] Thinking 模型兼容性——特定 `*-Thinking` 模型不走 `extra_body` 路径，其他模型保持原有行为
- [x] 增强计数准确性——日志中 `enhanced_count` 仅统计 content 实际改变的 span
- [x] 向后兼容——所有修改不改变公开 API 签名，不引入新配置项
- [x] 已有功能不受影响——非 Thinking 模型的行为不变化，扁平结构的 span 收集路径保持不变

## 4. 相关沉淀

- 值得记一笔 learning：VLM 模型在不同 API 提供商的参数兼容性差异（`*-Thinking` 后缀 vs `extra_body`）——可按需走 `cs-learn`

## 5. 变更日志

- 2026-05-06：修复完成，提交 `34d1835c`
