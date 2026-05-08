---
doc_type: decision
category: constraint
date: 2026-05-07
slug: strip-non-core-artifacts
topic: 移除通用分发组件（Web UI / Docker / CI / 在线文档 / Demo），项目聚焦嵌入式领域核心解析链路的长期维护
status: active
tags: [scope, embedded-domain, project-governance]
---

# 决策：剥离非核心分发层，聚焦核心解析链路

## 背景

本项目 Fork 自 [opendatalab/MinerU](https://github.com/opendatalab/MinerU)，上游是一个面向广泛用户群体的开源文档解析引擎，包含完整的分发生态：

- **Web UI**（`mineru/cli/gradio_app.py`, `mineru/cli/router.py`）—— Gradio 交互界面 + Web 路由，面向终端用户直接使用
- **Docker**（`docker/`）—— 18 个 Dockerfile + compose 编排，覆盖 10+ 国产 AI 芯片的容器化部署
- **CI/CD**（`.github/workflows/`）—— 5 个 GitHub Actions 流水线（CLA/CLI/Pages/Package/Rerun）
- **在线文档**（`docs/`, `mkdocs.yml`）—— 中英文双语文档，含产品介绍、快速开始、插件对接、国产卡加速指南等
- **Demo**（`demo/`）—— 示例 PDF/Office 文件 + demo 脚本
- **测试**（`tests/`）—— 单元测试（含测试 PDF）
- **版本发布脚本**（`update_version.py`）

此外，`pyproject.toml` 中注册了面向最终用户的 PyPI 发布配置（keywords 包含 SEO 标签、classifiers 标注 Python 版本、`project.urls` 指向官网和文档）。

## 决定

**剥离全部通用分发层组件，项目仅保留核心文档解析链路和本文 Fork 的嵌入式领域定制代码。**

具体移除清单：

| 类别 | 移除内容 | 理由 |
|------|----------|------|
| Web UI | `gradio_app.py` (1412行), `router.py` (1559行) | 嵌入式场景走 CLI/API，不需要 Web 交互 |
| Docker | 18 个 Dockerfile + compose | 不计划做多芯片容器化分发 |
| CI/CD | 5 个 GitHub Actions | 个人项目，不需要 CI 自动化 |
| 文档 | `docs/` 全部 + `mkdocs.yml` | 已有 `.codestable/` 知识库替代 |
| Demo | `demo/` 全部文件 | Demo PDF 与嵌入式领域无关 |
| 测试 | `tests/` 全部 + 测试 PDF | 暂不需要自动化测试框架 |
| 发布 | `update_version.py`, `pyproject.toml` 分发字段精简 | 不做 PyPI 发布 |

**保留的核心**：
- `mineru/` 全部代码（四条解析流水线 + 模型层 + 数据层 + 工具层）
- `pyproject.toml` 核心依赖和脚本入口
- `mineru.template.json` 配置模板
- `.codestable/` CodeStable 工作流体系

## 理由

1. **维护范围聚焦**：上游 MinerU 的分发生态（Web UI、Docker、国产卡适配文档）更新频繁，维护成本高且与嵌入式领域文档解析的核心目标无关
2. **减少干扰**：CI/CD 和测试框架对个人研究型项目性价比低，手动验证即可
3. **探索先行**：本次剥离前已通过 `cs-explore` 完成系统全局模块划分探索（`compound/2026-05-07-explore-system-overview.md`），确保理解每个模块的职责后再决定去留
4. **不丢核心**：剥离的仅为分发和辅助层，核心解析链路（Pipeline/VLM/Hybrid/Office 四条后端 + 模型层 + CLI/API 入口）完整保留

## 约束

- 后续不再接受 Web UI / Docker / CI 的代码回迁
- 上游 MinerU 的通用分发层更新不跟进
- 如需测试，采用手动端到端验证而非自动化框架
- `pyproject.toml` 的 `[project]` 元数据保留最低限度（名称/版本/描述/依赖），删除 SEO 和分发相关字段
- `pyproject.toml` 的 `readme` 字段指向本文 Fork 的自定义 `README.md`

## 相关

- `.codestable/compound/2026-05-07-explore-system-overview.md` — 剥离前的系统全局探索，确认各模块职责
- `.codestable/architecture/ARCHITECTURE.md` — 剥离后的系统架构文档
- 提交 `289bb806` — 执行剥离（178 文件，-11390/+227 行）
- 提交 `9a263c97` — 补充清理（删除遗留的非必要文档及测试文件）

## 变更日志

- 2026-05-07：决策制定并执行，文档落档
