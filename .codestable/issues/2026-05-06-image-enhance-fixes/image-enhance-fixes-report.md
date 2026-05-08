---
doc_type: report
issue: image-enhance-fixes
status: confirmed
date: 2026-05-06
severity: medium
summary: 图片语义增强功能首次运行发现三个问题：图片 span 收集遗漏嵌套结构、Thinking 模型 API 参数兼容性、增强计数虚高。
tags: [image-description, bug, vlm]
---

# Bug 报告：图片描述增强三个问题

## 1. 现象

上线图片语义增强功能后首次测试，发现三个问题：

### 问题 1：部分图片块的 span 未被收集

`_collect_image_spans()` 函数未找到某些文档中的图片 span，导致这些图片的 content 没有被在线模型增强，保留了本地 VLM 的原始低质量描述。

- **触发条件**：MagicModel 生成的 image/chart 块采用两层嵌套结构 `image → blocks → image_body → lines → spans`（而非扁平 `image_body → lines → spans`）
- **影响范围**：VLM 和 Hybrid 后端中由 MagicModel 构造的中间 JSON 页面——即所有正式解析场景
- **表面现象**：`Enhancing descriptions for 0 image/chart spans` 或数量明显偏少

### 问题 2：Thinking 模型 API 调用失败

使用 `Qwen/Qwen3-VL-32B-Thinking` 模型时，API 调用返回错误。

- **触发条件**：`enable_thinking=true`（默认） + model 为 `*-Thinking` 后缀 + SiliconFlow API
- **根因**：代码对所有 `enable_thinking=true` 的情况都通过 `extra_body: {"enable_thinking": True}` 传参，但 Qwen3-VL-32B-Thinking 在硅基流动 API 中已内置 thinking 模式，不接受此参数
- **表面现象**：全部图片增强失败，日志中 `Vision API call failed`

### 问题 3：增强计数虚高

日志显示 `X enhanced, 0 failed`，但实际部分图片的 content 未被改写。

- **触发条件**：span 原始 content 非空（本地 VLM 已有输出）
- **根因**：增强后的计数逻辑仅检查 `content.strip()` 非空即计为 enhanced，未对比原始内容是否真的被改写
- **表面现象**：统计日志不准确，无法判断哪些图片真正被在线模型改了内容

## 2. 复现

### 问题 1 复现

1. 配置文件 `image-description-config.enable = true` + 有效 api_key
2. 解析任意包含图片的 PDF（使用 VLM 或 Hybrid 后端）
3. 观察日志中的 span 数量：预期 `N` 个图片 span，实际为 `0` 或远小于 `N`

### 问题 2 复现

1. 配置 `model = "Qwen/Qwen3-VL-32B-Thinking"` + `enable_thinking = true`
2. 使用 SiliconFlow API (`base_url = "https://api.siliconflow.cn/v1"`)
3. 全部图片增强请求返回错误

### 问题 3 复现

1. 处理含图片的 PDF
2. 观察日志 `X enhanced, Y failed` 中 X 的数字
3. 对比增强前后 span content 内容——部分计数为 enhanced 的 span 实际 content 不变
