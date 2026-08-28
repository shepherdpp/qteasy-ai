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

> **唯一定义**见 qteasy 仓 [qteasy_ai_top_level_design](https://github.com/shepherdpp/qteasy/blob/master/.cursor/plans/qteasy_ai_top_level_design.plan.md) §四。

| 概念 | 阶段 A 现状（已废弃于 Ask） | 阶段 C 目标态（Q-AI.3） |
|------|---------------------------|------------------------|
| **Ask** | `ask()` 生成空步 ToolPlan，`dry_run`，不执行 skill | `ask()` = LLMClient + KnowledgeBase，**无 steps / 无 Executor**；无 Provider 时 Offline KB |
| **preview** | （无独立入口） | `preview()` / `plan --preview` = 原「只看 plan」语义，等于 `plan()` dry-run |
| **Plan** | dry-run ToolPlan | 不变；有 Provider 时 LLM 候选 + RuleValidator / env_facts 门禁 |
| **Run / Agent** | 生成 plan 后执行 | 不变；实盘永远 plan_only |

用户指南：[USER_GUIDE.md](../USER_GUIDE.md)。

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
qteasy-ai ask "explain PT vs PS"
qteasy-ai preview "list built-in strategies"
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

## 7. Stage B0 增量（Q-AI.1.5）

在阶段A骨架上，B0 交付：

| 能力 | 说明 |
|------|------|
| `skill_kind` | L1 子标签：`api`（默认）/ `guide`（环境引导） |
| env skills | `qt.ai.env.check_tushare`、`qt.ai.env.overview_tables`（只读探针，不联网、不全库 overview） |
| `env_facts` 门禁 | Planner 读取 MemoryStore；已知核心行情表 `exists=False` 时前置 overview |
| data/research | summary 增加交易天数与波动率；`qt.ai.research.factor_ic_summary` |
| plan 双轨 | ToolPlan JSON + 单向 `plan.md`（`plan_md` / `runs/{run_id}.plan.md`） |

设计决议（qteasy 仓执行层 B0.0）：规则 + env_facts 为主；B0 **不做** LLM 候选生成；不做 md→plan 反解析。Hybrid LLM 候选归 **阶段 C**。

## 8. Stage C 增量（Q-AI.3）

- Ask 目标态：`AskEngine` + 策展 `qteasy_ai/kb/*.json`；策略元数据直接读 `qteasy.built_in_*`（不经 skill）。
- `preview()` / CLI `preview` / `plan --preview` 承接原 ask 空步预览。
- `explanation_depth`：`brief` / `standard` / `deep`。
- Hybrid Planner：有 Provider 时 LLM 生成候选 JSON；未知 skill / 非法 JSON 降级规则路径；refill 缺日期与 env_facts 门禁在候选之后共用。

