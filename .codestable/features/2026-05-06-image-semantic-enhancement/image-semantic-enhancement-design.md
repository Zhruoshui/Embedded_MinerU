---
doc_type: design
feature: image-semantic-enhancement
status: approved
date: 2026-05-06
summary: 接入在线多模态视觉模型（OpenAI 兼容 API），在 VLM/Hybrid 后端解析完成后对文档中的 image/chart 块进行语义内容增强，替代本地 VLM 模型原始输出，提升嵌入式领域技术文档图片描述准确率。
tags: [vlm, image-description, multimodal, online-api, embedded-domain]
implements:
  - pdf-image-parsing
depends_on:
  - ARCHITECTURE
roadmap: ""
roadmap_item: ""
---

# 图片语义描述在线增强

## 1. 动机与范围

### 1.1 为什么需要

MinerU 的 VLM/Hybrid 后端会对文档中的图片、图表块输出文本描述，但本地 VLM 模型（1.2B–7B）受限于参数规模和训练数据分布，对嵌入式领域常见的技术图表（电路示意图、寄存器时序图、MCU 架构图、数据波形图等）描述质量不足——要么过于笼统，要么无法识别图中关键信息。

引入在线多模态大模型（如 Qwen3-VL-32B-Thinking）作为后处理增强步骤，利用更强的视觉理解能力重写图片描述，同时支持多种输出格式（Markdown 表格、Mermaid 流程图、自然语言）以匹配不同图片类型的语义需求。

### 1.2 边界（明确不做）

- **不做** 替换 VLM/Hybrid 后端的版面分析逻辑——在线模型仅增强图片块的 content 字段，不碰 layout、ocr、table 等核心解析
- **不做** 实时在线服务——本功能为离线批处理后增强，依赖用户自行配置 API key
- **不做** Pipeline 后端集成——Pipeline 后端不经过 VLM，无图片描述输出
- **不做** 在线模型的 prompt 自动优化——使用统一泛化 prompt，模型自行判断图片类型选择输出格式

## 2. 方案设计

### 2.1 对外接口

**配置接口**（`~/mineru.json` 新增 `image-description-config` 段）：

```json
{
  "image-description-config": {
    "enable": true,
    "api_key": "sk-xxx",
    "base_url": "https://api.siliconflow.cn/v1",
    "model": "Qwen/Qwen3-VL-32B-Thinking",
    "enable_thinking": true,
    "max_tokens": 4096,
    "temperature": 0.6
  }
}
```

- `enable: false` 时不触发增强（默认关闭，零侵入）
- `api_key` 为空时记录 warning 并跳过
- 所有字段有默认值，仅 `enable` + `api_key` 为实际必须手动配置项

**调用入口**（单一公共函数）：

```python
# mineru/backend/vlm/image_enhance.py
def enhance_image_descriptions(pdf_info_list: list, image_writer) -> None:
```

- 入参：中间 JSON 的 `pdf_info` 列表 + `DataWriter` 实例（用于读取已写入磁盘的图片文件）
- 出参：无返回值，原地修改 span 的 `content` 字段
- 调用方：VLM/Hybrid 后端的同步+异步共 6 个调用点，统一在此函数后处理环节

### 2.2 主流程

```
enhance_image_descriptions()
  1. 读配置 → enable=False / api_key 为空 → 直接返回
  2. _collect_image_spans(pdf_info_list)
     → 遍历所有页面的 preproc_blocks，收集 IMAGE/CHART 类型 span
     → 适配两种块结构：两层嵌套 (image → blocks → image_body → lines → spans)
                        和扁平结构 (image_body → lines → spans)
  3. 无图片 span → 直接返回
  4. 创建 OpenAI client(api_key, base_url)
  5. ThreadPoolExecutor(max_workers=3) 并发处理：
     for each span:
       a. _load_image_bytes(image_path, image_writer) → 从磁盘加载原图
       b. _preprocess_image() → 最长边缩放至 2048px, JPEG quality=85
       c. _image_to_base64() → base64 编码
       d. _call_vision_api_sync(client, base64, config) → OpenAI chat.completions.create
          - 统一 prompt：模型自动判断图片类型，选择最佳输出格式
          - retry 3 次，单次失败仅 warning 不中断
          - Thinking 模式：自动剥离 <think>...</think> 标签
          - API 调用失败：保留原始 content，只记 warning 日志
       e. 成功 → 修改 span["content"] = new_content
  6. 统计日志：enhanced_count / failed_count
```

**流程级约束**：
- **配置驱动，默认关闭**：用户显式 `enable: true` 并配置 `api_key` 才生效
- **降级安全**：任何步骤异常都不影响主解析流程，保留原始 content
- **仅后处理增强**：在版面分析完成、图片已写入磁盘后调用，发生在 `finalize_middle_json` 之前
- **并发上限 3**：避免触发 API rate limit，ThreadPoolExecutor 控制
- **图片尺寸限制**：最大 2048px 最长边，控制 token 消耗
- **所有调用点统一**：6 个调用点（vlm sync/async/middle_json + hybrid sync/async/middle_json）使用同一函数，行为一致

### 2.3 挂载点

在 VLM/Hybrid 后端中，`enhance_image_descriptions()` 挂载的位置：

| 后端 | 文件 | 挂载位置 |
|------|------|----------|
| VLM 同步 | `vlm_analyze.py:508` | `ModelSingleton.doc_analyze()` 内，MagicModel 构造 middle_json 后 |
| VLM 异步 | `vlm_analyze.py:601` | `ModelSingleton.aio_doc_analyze()` 内，异步 MagicModel 构造后 |
| VLM 独立入口 | `model_output_to_middle_json.py:162` | `init_middle_json()` 末尾 |
| Hybrid 同步 | `hybrid_analyze.py:659` | `doc_analyze()` 内，MagicModel 构造 middle_json 后 |
| Hybrid 异步 | `hybrid_analyze.py:789` | `aio_doc_analyze()` 内，异步 MagicModel 构造后 |
| Hybrid 独立入口 | `hybrid_model_output_to_middle_json.py:339` | `init_middle_json()` 末尾 |

所有挂载点满足：图片已写入磁盘 → 调用增强 → `finalize_middle_json`（后续步骤）。

## 3. 验收场景

### 3.1 正常路径

1. **配置文件 enable=true + 有效 api_key** → 解析含图片的 PDF → 图片块 content 被在线模型重写，长度显著增加，内容与图片语义相关
2. **多图片并发** → 10 张图片的 PDF → 3 个并发 worker 处理，所有图片 content 被增强，count 日志正确
3. **Thinking 模型** → 使用 `Qwen3-VL-32B-Thinking` → `<think>` 标签被剥离，仅保留实际回答
4. **图表类图片** → 柱状图/折线图 → 输出 Markdown 表格（prompt 自动选择）
5. **流程图类图片** → 流程图/架构图 → 输出 Mermaid 代码块
6. **普通图片** → 照片/截图 → 自然语言描述且不乱加"这张图片展示了"等开头语

### 3.2 边界/降级

1. **配置 enable=false** → 解析正常，无 API 调用，无额外日志
2. **配置 enable=true 但 api_key 为空** → warning 日志 "no api_key configured, skipping"，解析正常继续
3. **API 调用失败（网络/鉴权/超时）** → 单张图片失败仅 warning，不中断，其他图片继续处理，原始 content 保留
4. **图片文件不存在** → FileNotFoundError 被捕获，该 span 保持原始 content
5. **API 返回空内容** → warning 日志 "Empty response"，原始 content 保留
6. **PDF 无图片** → `_collect_image_spans` 返回空，debug 日志，直接返回
7. **VLM 后端 + Pipeline 后端混合处理** → Pipeline 不触发增强（不经过 VLM 链路），VLM/Hybrid 正常增强

### 3.3 错误恢复

1. **3 次重试全部失败** → Exception 被 `_process_single_image` 捕获，warning 日志，该 span 的 content 不变，其他 span 不受影响
2. **配置缺失 image-description-config 段** → `get_image_description_config()` 返回 None，直接返回不处理

## 4. 关键决策

- **配置驱动而非命令行参数**：图片增强是全局行为，不应每次 cli 传参；且配置已有的 `~/mineru.json` 模式（llm-aided-config）已为此范式提供先例
- **仅后处理增强而非替换 VLM 输出流程**：保持 MinerU 的中间 JSON 与上游一致，online 增强作为可选的最后一层润色
- **统一泛化 prompt 而非按文档类型定制 prompt**：避免 prompt 工程复杂度，利用大模型自身的图片理解能力做类型判别 + 格式选择
- **ThreadPoolExecutor 而非 asyncio**：同步处理图片文件 I/O + HTTP 调用，单函数兼容同步和异步两个后端入口
- **6 个调用点显式调用而非切面注入**：调用点虽多但位置明确、行为一致，切面注入（装饰器/hook）会隐藏副作用反而更难追踪

## 5. 涉及文件

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `mineru/backend/vlm/image_enhance.py` | **新增** | 核心逻辑：图片收集、预处理、API 调用、结果回写 |
| `mineru/utils/config_reader.py` | 修改 | 新增 `get_image_description_config()` |
| `mineru/backend/vlm/vlm_analyze.py` | 修改 | 同步/异步流程 2 个挂载点 |
| `mineru/backend/vlm/model_output_to_middle_json.py` | 修改 | 独立入口 1 个挂载点 |
| `mineru/backend/hybrid/hybrid_analyze.py` | 修改 | 同步/异步流程 2 个挂载点 |
| `mineru/backend/hybrid/hybrid_model_output_to_middle_json.py` | 修改 | 独立入口 1 个挂载点 |

## 6. 依赖

- `openai>=1.70.0`（已在 pyproject.toml 核心依赖中）
- `Pillow>=11.0.0`（已在核心依赖中）
- 用户自行提供的 OpenAI 兼容 API 端点（如 SiliconFlow）

## 7. 变更日志

- 2026-05-06：初始版本，用户确认通过
