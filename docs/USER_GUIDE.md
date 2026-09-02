# qteasy-ai 用户指南（Ask / Plan / Agent）

面向使用者的模式、安全边界与副作用说明。契约定义以 qteasy 仓产品顶层计划 §四 为准。

## 1. 三种模式（必须可见）

| 模式 | API / CLI | 会不会执行 skill | 典型用途 |
|------|-----------|------------------|----------|
| **Ask** | `assistant.ask()` / `qteasy-ai ask` | **否**。不调用 PlanExecutor，不写 `runs/` | 学习 qteasy：PT/PS/VS、`run_freq`、常见错误 |
| **Plan** | `assistant.plan()` / `qteasy-ai plan` | 否（dry-run）。只生成 ToolPlan | 审阅步骤、side-effects、假设 |
| **preview** | `assistant.preview()` / `qteasy-ai preview` / `plan --preview` | 与 Plan 相同 | 原 `ask()` 的「只看 plan 不执行」迁移入口 |
| **Agent（run）** | `assistant.run()` / `qteasy-ai run`；已审阅图用 `run --plan-id` | **是**（CLI 视为一次人在回路确认） | 下载/回测/优化等已确认任务 |

Notebook：`%%qtai --mode ask|plan|preview|run`。`run` 仍须 `%%qtai --confirm <plan_id>` 才真正执行。

## 2. Ask 目标态（Q-AI.3）

Ask 只走 **LLMClient + KnowledgeBase**：

- 无 Provider 时用离线 KB 检索 + **英文**模板答案（仍可用）。
- 有 Provider 时用检索片段接地再合成：`answer` **跟随你的问句语言**（中文问中文答、英文问英文答）。代码、skill 名、`python_code` 保持英文/原文。
- KB 未命中不会空库瞎编，返回英文 `NOT_FOUND` 并建议改用 Plan（此路径不调用 LLM，故即使用中文提问也是英文提示）。
- 「列出策略 / 下载 / 回测 / 优化 / 导出」等执行型请求会提示改用 Plan（同样是英文罐头、不调 LLM），**不**生成可执行 steps。

**Breaking（相对阶段 A）**：`ask()` 不再返回空步 `ToolPlan` dry-run。若你需要审阅 steps，请改用 `preview()` / `plan()`。

```bash
qteasy-ai ask "explain PT vs PS"
qteasy-ai ask "explain PT vs PS" --depth brief
qteasy-ai preview "list built-in strategies"
```

```python
from qteasy_ai.app import QteasyAssistant

assistant = QteasyAssistant()
ask_out = assistant.ask("explain PT vs PS", response_style="raw")
assert ask_out["mode"] == "ask"
assert "execution" not in ask_out
preview = assistant.preview("list built-in strategies", response_style="raw", persist="none")
print(preview["plan"]["steps"][0]["skill_name"])
```

解释层深度 `explanation_depth`：`brief`（无 python_code）/ `standard`（默认，三通道）/ `deep`（追加风险/假设）。Ask 与 Plan `--pretty` 共用同一套模板。

## 3. 安全边界与 side-effects

用户可见错误与警告为**英文**。

- 高副作用（网络下载、写库、回测、优化、改策略文件）必须先出现在 Plan 的 `side_effects` 中，确认后再 `run`。
- **实盘**走 `qt.ai.pipeline.live_trade_plan_only`：只出前置清单，`execution_forbidden`，永不 auto-execute。
- StrategyBuilder（阶段 D）：自然语言 → StrategySpec → 模板骨架写入 `.qteasy/ai/strategies/` → 静态校验 → 复用 `backtest.run_builtin`。Ask 不写策略文件。
- 无日期或超长区间的全市场 refill：Plan 会 `clarify_required` / `date_range`，禁止无界下载。
- 无匹配 skill 时返回 `clarify_required` / `not_supported_yet`，**禁止**静默落到 `summary_kline`。
- Hybrid Planner（方案 H）：分类只出 **Job ID**（`planner_trace.intent_job` / `source` / `rationale`）；已知 Job 由代码菜谱出图。配置了 Provider 时，0 命中或冲突表未覆盖才让 LLM 选 Job；非法 JSON / 未知 id → `clarify`，禁止降级回扁平 skill 菜单。未配置 Provider 且 0 命中 → `clarify`。

## 4. Provider

未设置 `QTEASY_AI_MODEL` 时：

- Ask：Offline KnowledgeBase。
- Plan：规则路由（不调用 LLM）。

设置 `QTEASY_AI_MODEL` / `QTEASY_AI_API_KEY` / `QTEASY_AI_BASE_URL` 后：Ask 可走 LLM 合成；Plan 可走 LLM 候选 + 规则门禁。默认请求超时 **120 秒**（`QTEASY_AI_TIMEOUT` / `ai_timeout` 可覆盖）。

```bash
qteasy-ai provider-check
```

## 5. 更多

- 快速上手：[tutorials/quickstart.md](tutorials/quickstart.md)
- 阶段 A 设计备忘（含现状 vs 目标态）：[design/11-ai-shell-stage-a.md](design/11-ai-shell-stage-a.md)
- 阶段 D 手测：[LIVE_FIRE_DRILL_QAI4.md](LIVE_FIRE_DRILL_QAI4.md)
- 示例：`examples/ai_shell_stage_c_ask_demo.py`、`examples/ai_shell_stage_d_strategybuilder_demo.py`

## 6. StrategyBuilder（Q-AI.4）

自然语言写策略走 **Plan**，不是 Ask。本阶段只支持 **RuleIterator 双均线择时** 模板（如 20/60 金叉死叉）。生成源码写入 `.qteasy/ai/strategies/`，不写 qteasy 安装包、默认不写 `examples/`。

```bash
qteasy-ai plan "帮我写一个基于 20/60 日均线金叉死叉的择时策略，并用 2015–2020 年沪深300做回测" --raw
```

实盘：

```bash
qteasy-ai plan "start live trade now" --raw
```

期望 skill：`qt.ai.pipeline.live_trade_plan_only`（只出计划）。

演示脚本：`examples/ai_shell_stage_d_strategybuilder_demo.py`。
