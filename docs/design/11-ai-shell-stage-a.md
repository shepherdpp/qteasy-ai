# S1.4 阶段A：AI 外壳增强版设计

本文档描述 qteasy AI 外壳在 S1.4 阶段A（增强版）的实现边界与使用方式。

## 1. 阶段目标

- 提供统一交互链路：自然语言 -> ToolPlan -> 用户确认 -> 执行 -> 结构化结果
- 落地基础骨架：`SkillRegistry`、`Planner`、`PlanExecutor`
- 提供 3 个只读技能：策略知识、K 线摘要、K 线导出
- 同步支持 Notebook 与 CLI 两个入口
- 落地最小记忆：`profile` / `env_facts` / `runs`
- 支持至少一个真实 Provider 适配（OpenAI-compatible）

## 2. 目录结构

- `qteasy_ai/contracts.py`：统一契约
- `qteasy_ai/registry.py`：技能注册与发现
- `qteasy_ai/planner.py`：Hybrid 计划生成与规则校验
- `qteasy_ai/executor.py`：计划执行与 run 记录
- `qteasy_ai/provider.py`：Provider 抽象与 OpenAI-compatible 实现
- `qteasy_ai/memory_store.py`：本地记忆与执行记录
- `qteasy_ai/skills/*.py`：阶段A只读技能
- `qteasy_ai/cli.py`：CLI 入口
- `qteasy_ai/app.py`：Notebook/CLI 共享应用层

## 3. 运行模式

> **唯一定义**见 qteasy 仓 [qteasy_ai_top_level_design](https://github.com/shepherdpp/qteasy/blob/master/.cursor/plans/qteasy_ai_top_level_design.plan.md) §四。下表为 0.1.0 现状摘要。

- Ask（`ask`）：生成 ToolPlan，**不执行** skill
- Plan（`plan`）：默认 dry-run plan，供审阅
- Run（`run`）：生成 plan 后执行（产品语义对应目标态 **Agent**；profile 门控待 Q-AI.2）

## 4. 本地配置

### 4.1 记忆目录

- 默认：`./.qteasy/ai/`
- 可通过环境变量覆盖：`QTEASY_AI_HOME`

### 4.2 Provider 配置

- `QTEASY_AI_MODEL`
- `QTEASY_AI_API_KEY`
- `QTEASY_AI_BASE_URL`

当上述配置完整时，可通过 `OpenAICompatProvider` 发起真实请求。

## 5. CLI 用法

```bash
qteasy-ai ask "list built-in strategies"
qteasy-ai plan "show kline summary of 000300.SH"
qteasy-ai run "export kline of 000300.SH"
qteasy-ai provider-check
```

## 6. 输出契约摘要

技能统一返回字段：

- `ok`
- `skill_name`
- `run_id`
- `inputs_echo`
- `metrics`
- `data_summary`
- `artifacts`
- `warnings`
- `error`

用户可见错误信息保持英文，便于统一对外输出约定。
