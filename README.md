# qteasy-ai 介绍

**qteasy-ai** 是 [qteasy](https://github.com/shepherdpp/qteasy) 的 **独立 AI 编排外壳**：自然语言 → ToolPlan → 用户确认 → 调用 qteasy API → 结构化结果。  
它不修改 qteasy 回测/交易内核，仅作为可插拔的 skills + planner + executor 层。

> **当前版本：0.1.0**（Stage A 发版标签）。阶段 C（Q-AI.3）Ask 目标态 / preview / Hybrid LLM 已在主分支实现，发版标签由 Jackie 统一打出。  
> 用户指南：[docs/USER_GUIDE.md](docs/USER_GUIDE.md)。人工 smoke 见 [docs/MANUAL_TEST.md](docs/MANUAL_TEST.md)。  
> **协作规范与 Q-AI 计划真源**仍在 qteasy 仓库的 [`.cursor/rules/`](https://github.com/shepherdpp/qteasy/tree/master/.cursor/rules) 与 [`.cursor/plans/`](https://github.com/shepherdpp/qteasy/tree/master/.cursor/plans)。

## 与 qteasy 的关系

| 项目 | 职责 |
| --- | --- |
| **qteasy** | 数据、HistoryPanel、回测、优化、模拟实盘内核 |
| **qteasy-ai** | AI 外壳：SkillRegistry、Planner、PlanExecutor、只读/高副作用 skills |

- **依赖方向**：`qteasy-ai` → `qteasy`（pip 安装 `qteasy>=2.6.0`）
- **发布**：两项目 **独立 semver**；qteasy 新版本 API 可由 qteasy-ai skills 增量适配

## 安装

```bash
pip install qteasy>=2.6.0
pip install qteasy-ai
```

本地联调（两仓并列开发时）：

```bash
pip install -e /path/to/qteasy
pip install -e /path/to/qteasy-ai
```

## 配置

优先使用环境变量（与 Stage A 设计一致）：

- `QTEASY_AI_HOME` — 本地记忆目录（profile / env_facts / runs）
- `QTEASY_AI_MODEL` / `QTEASY_AI_API_KEY` / `QTEASY_AI_BASE_URL` — OpenAI-compatible Provider

详见 [docs/USER_GUIDE.md](docs/USER_GUIDE.md)、[docs/tutorials/quickstart.md](docs/tutorials/quickstart.md)。

## 开发

- 本地建议与 qteasy **同一 Cursor multi-root 工作区**（见 `qteasy-ecosystem.code-workspace`）
- 规范与测试约定：**沿用 qteasy** [`.cursor/rules/`](https://github.com/shepherdpp/qteasy/tree/master/.cursor/rules)（py39、unittest、用户可见信息英文等）
- 更多说明：[docs/dev-context.md](docs/dev-context.md)、[CONTRIBUTING.md](CONTRIBUTING.md)

## License

BSD-3-Clause（与 qteasy 相同）

## Changelog

见 [CHANGELOG.md](CHANGELOG.md)。
