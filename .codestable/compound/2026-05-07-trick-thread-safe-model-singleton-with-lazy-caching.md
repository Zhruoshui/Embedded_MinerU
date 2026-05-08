---
doc_type: trick
type: pattern
date: 2026-05-07
slug: thread-safe-model-singleton-with-lazy-caching
topic: 用线程安全单例 + 字典懒加载缓存大型模型实例，按配置组合 key 避免重复初始化
language: python
tags: [singleton, model-cache, thread-safe, lazy-loading, pattern]
status: active
---

## 适用场景

模型加载开销大（秒到分钟级），同进程内多文档、多配置组合反复调用时需要避免重复加载。模型本身不包含请求级可变状态，适合进程级缓存。

## 做法

两层缓存：外层 `ModelSingleton` 缓存完整流水线实例，内层 `AtomModelSingleton` 缓存单个原子模型实例。都继承 `__new__` 实现线程安全单例，`get_model()` 方法按参数组合 key 查字典：

```python
# pipeline_analyze.py:33-58 — 外层模型单例
class ModelSingleton:
    _instance = None
    _models = {}
    _lock = PIPELINE_MODEL_INIT_LOCK

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def get_model(self, lang=None, formula_enable=None, table_enable=None):
        key = (lang, formula_enable, table_enable)
        with self._lock:
            if key not in self._models:
                self._models[key] = custom_model_init(
                    lang=lang, formula_enable=formula_enable, table_enable=table_enable
                )
        return self._models[key]
```

内层原子模型单例（`model_init.py:116-155`）更进一步：按 `(model_name, param1, param2, ...)` 构建 key，确保同一 OCR 引擎被 table/wireless/wired 三个模型复用。

## 为什么有效

- **线程安全**：`threading.RLock()` 确保多线程同时 `get_model()` 不会并发初始化同一 key
- **粒度合适**：按配置组合 key，同一个 `lang`+`formula_enable`+`table_enable` 三元组只用一份模型副本
- **懒加载**：首次调用才初始化，避免启动时加载所有模型
- **内层复用**：`AtomModelSingleton` 让 OCR 引擎等昂贵模型被多个上层模型共享

## 示例

VLM 后端采用完全相同的模式（`vlm_analyze.py:44-253`），按 `(backend, model_path, server_url)` key 缓存 `MinerUClient` 实例。Hybrid 有独立的 `HybridModelSingleton`（`model_init.py:263-286`）只初始化 OCR+Layout+MFR 三个模型。

## 已知坑

- key 必须是可哈希的（tuple），不能是可变对象
- 模型实例内部不能有请求级可变状态（单例是全局共享的）
- 多 GPU 场景下单例不适用——每个 GPU 需要独立模型实例

## 相关文档

- `mineru/backend/pipeline/pipeline_analyze.py:33-58`
- `mineru/backend/pipeline/model_init.py:116-155`
- `mineru/backend/vlm/vlm_analyze.py:44-253`
