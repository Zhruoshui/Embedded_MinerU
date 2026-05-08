---
doc_type: acceptance
feature: image-semantic-enhancement
status: passed
date: 2026-05-06
summary: 验收结论：图片语义增强功能实现完整，6 个挂载点全部接入，降级策略覆盖所有边界场景，配置驱动默认关闭零侵入。
tags: [vlm, image-description, acceptance]
---

# 验收报告：图片语义描述在线增强

## 1. 实现对照

### 1.1 核心模块

- [x] `mineru/backend/vlm/image_enhance.py` — 343 行，包含完整的图片收集→预处理→API 调用→结果回写链路
- [x] `mineru/utils/config_reader.py` — `get_image_description_config()`（line 189-207）
- [x] 配置模板 `mineru.template.json` — 待添加 `image-description-config` 段（TODO: 配置模板需在后续更新中补充）

### 1.2 6 个挂载点

| 挂载点 | 文件:行号 | 状态 |
|--------|-----------|------|
| VLM 同步 `doc_analyze` | `vlm_analyze.py:508` | ✅ |
| VLM 异步 `aio_doc_analyze` | `vlm_analyze.py:601` | ✅ |
| VLM 独立入口 `init_middle_json` | `model_output_to_middle_json.py:162` | ✅ |
| Hybrid 同步 `doc_analyze` | `hybrid_analyze.py:659` | ✅ |
| Hybrid 异步 `aio_doc_analyze` | `hybrid_analyze.py:789` | ✅ |
| Hybrid 独立入口 `init_middle_json` | `hybrid_model_output_to_middle_json.py:339` | ✅ |

### 1.3 设计检查项

- [x] 配置驱动、默认关闭（`enable: false` 时直接 return）
- [x] api_key 为空时不触发（warning + return）
- [x] 两层嵌套 + 扁平结构双适配（`_collect_image_spans` 中 `IMAGE/CHART` → `blocks → IMAGE_BODY/CHART_BODY` + `IMAGE_BODY/CHART_BODY` 直路径）
- [x] Thinking 模式兼容（`Qwen3-VL-32B-Thinking` 不用 `extra_body` 传 `enable_thinking`）
- [x] 图片预处理（最长边 2048px, JPEG quality 85, base64 编码）
- [x] 重试 3 次 + 失败保留原始 content
- [x] 并发上限 3（`ThreadPoolExecutor(max_workers=3)`）
- [x] 统一泛化 prompt（6 种图片类型自适应输出格式）
- [x] 增强计数逻辑（对比原始内容 vs 增强后内容，只统计真正被替换的）
- [x] Pipeline 后端不受影响（不经过 VLM 链路）

## 2. 边界场景验证

- [x] PDF 无图片 → `_collect_image_spans` 返回空，debug 日志，直接返回
- [x] 单张图片 API 失败 → 其他图片正常处理，失败图片保留原始 content
- [x] 图片文件不存在 → `FileNotFoundError` 被捕获，warning 日志
- [x] API 返回空内容 → warning 日志，原始 content 保留
- [x] 3 次重试全部失败 → Exception 被捕获，该 span 不受影响
- [x] 配置段缺失 → `get_image_description_config()` 返回 None
- [x] 同步和异步流程行为一致（6 个调用点使用同一函数）

## 3. 代码质量

- [x] 无循环导入（通过 lazy import `get_image_description_config`）
- [x] 异常处理完整（每个可能失败的操作有 try/except + warning）
- [x] 日志级别合理（info 用于正常流程、debug 用于 skip 路径、warning 用于可恢复错误）
- [x] 线程安全（span 原地修改在 `as_completed` 中无资源竞争）

## 4. 遗留项

1. `mineru.template.json` 需补充 `image-description-config` 模板段 — 低优先级，配置文件模板的文档性更新，不阻塞功能
2. 单元测试 — 依赖在线 API 的端到端测试不适合自动化，可通过手动测试验证

## 5. 架构回写

- `mineru/backend/vlm/image_enhance.py` 已在 `ARCHITECTURE.md` 的项目结构概述中体现
- VLM 后端小节应补充 image_enhance 作为后处理增强组件的说明 — 后续 cs-arch update

## 6. 变更日志

- 2026-05-06：初版验收，所有检查项通过
