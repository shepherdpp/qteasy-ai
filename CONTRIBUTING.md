# Contributing to qteasy-ai

## 协作模型

qteasy-ai 在 **GitHub / PyPI 上独立发布**，但在 Jackie 与 AI 助手（David）的本地工作流中与 **qteasy 共用同一 Cursor 工作区与规范**：

| 真源 | 位置 |
| --- | --- |
| 项目规则（always apply） | qteasy 仓 [`.cursor/rules/`](../qteasy/.cursor/rules/) |
| Q-AI 执行计划 | qteasy 仓 [`.cursor/plans/`](../qteasy/.cursor/plans/)（`qteasy_ai_*.plan.md`、`s1.4a_*.plan.md` 等） |
| 顶层战略交叉索引 | qteasy [master-plan §7](../qteasy/.cursor/plans/量化工具对比与qteasy展望_f384dd4a.plan.md) |

**请勿**在 qteasy-ai 仓复制一整套 `.cursor/rules/`，以免与 qteasy 漂移。本仓仅维护代码、用户文档与 `docs/dev-context.md`。

## 环境

- Python：**3.9**（与 qteasy 一致，推荐 `/opt/anaconda3/envs/py39/bin/python`）
- 依赖：`pip install -e ../qteasy` + `pip install -e .`
- 测试：`python -m unittest discover -s tests -v`（Session 2 迁入 `test_ai_*` 后）

## 架构原则（迁移首版不变）

- AI **不改** qteasy 内核语义
- 高副作用操作（下载、写库、回测、实盘）默认 **Plan 优先、用户确认**
- skills 通过依赖注入调用 `qteasy.*` entrypoints

详见 qteasy 仓 [`s1.4_剥离_qteasy-ai_10ba0551.plan.md` §2.1](../qteasy/.cursor/plans/s1.4_剥离_qteasy-ai_10ba0551.plan.md)。

## 提 PR

1. 在 `qteasy-ai` 仓开 feature 分支
2. 定向跑相关 `unittest`（不必每次全量 discover 两仓）
3. 用户可见错误/日志保持 **英文**
