---
doc_type: trick
type: pattern
date: 2026-05-07
slug: backend-strategy-dispatch-with-string-parameter
topic: 用字符串参数 + 条件分支做多后端策略分发，调度层不依赖具体后端实现
language: python
tags: [strategy-pattern, backend-dispatch, routing, dependency-injection]
status: active
---

## 适用场景

一个系统有多个可替换的策略实现（后端/引擎/算法），用户通过配置参数选择，调度逻辑不依赖任何具体实现。新增策略只需加分支，不改调度骨架。

## 做法

调度函数接收 `backend` 字符串参数，按前缀/值匹配分发，各后端处理函数独立定义：

```python
# cli/common.py:619-708 — do_parse() 后端分发
def do_parse(..., backend="pipeline", ...):
    # Office 文档先提取（按文件后缀自动识别）
    _process_office_doc(...)

    if backend == "pipeline":
        _process_pipeline(...)
    elif backend.startswith("vlm-"):
        backend = backend[4:]  # 去掉 vlm- 前缀
        _process_vlm(...)
    elif backend.startswith("hybrid-"):
        ensure_backend_dependencies(backend)  # 可选依赖检查
        backend = backend[7:]
        _process_hybrid(...)
```

关键设计点：
- **前缀匹配** `backend.startswith("vlm-")` 让引擎名（`vlm-vllm-engine`）和策略名解耦
- **惰性导入** `ensure_backend_dependencies()` 在运行时检查可选依赖（`cli/common.py:60-64`），而不是在启动时挂
- **异步独立** `aio_do_parse()` 是同步版本的异步对偶，复用同一套 `_process_xxx` 逻辑

## 为什么有效

- **调度骨架稳定**：只加 `elif` 分支不改循环结构
- **可选依赖不阻塞**：`pipeline` 用户不需要装 `torch`/`vllm`，调度时检查依赖而不是 import 时
- **引擎透明**：VLM 和 Hybrid 内部的 `vllm-engine`/`lmdeploy-engine`/`auto-engine` 对调度层透明，由各自的 `get_vlm_engine()` 处理
- **异步对偶清晰**：同步版给 CLI 用，异步版给 FastAPI 用，逻辑镜像

## 示例

整个 MinerU 的后端分发链路：

```
用户 CLI: mineru --backend hybrid-auto-engine input.pdf
  → client.py 解析参数
  → fast_api.py 启动子进程
  → common.py: do_parse(backend="hybrid-auto-engine")
    → 匹配 backend.startswith("hybrid-") → True
    → ensure_backend_dependencies() → 检查 torch
    → 去掉 hybrid- 前缀 → backend = "auto-engine"
    → get_vlm_engine('auto') → 自动选 vllm/lmdeploy/mlx
    → _process_hybrid(backend="vllm-engine")
```

## 何时不适用

- 策略数量极多（10+）——考虑注册表模式（dict mapping）替代 if/elif
- 策略间有复杂依赖图——需要依赖注入容器

## 相关文档

- `mineru/cli/common.py:619-708` — `do_parse()` 同步分发
- `mineru/cli/common.py:711` — `aio_do_parse()` 异步对偶
- `mineru/utils/engine_utils.py:34` — `get_vlm_engine()` 引擎自动选择
