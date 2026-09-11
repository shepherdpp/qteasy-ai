# qteasy-ai 用户指南（Ask / Plan / Agent）

面向使用者的模式、安全边界与副作用说明。契约定义以 qteasy 仓产品顶层计划 §四 为准。

## 1. 三种模式（必须可见）

| 模式 | API / CLI | 会不会执行 skill | 典型用途 |
|------|-----------|------------------|----------|
| **Ask** | `assistant.ask()` / `qteasy-ai ask` | **否**。不调用 PlanExecutor，不写 `runs/` | 学习 qteasy：PT/PS/VS、`run_freq`、常见错误 |
| **Plan** | `assistant.plan()` / `qteasy-ai plan` | 否（dry-run）。只生成 ToolPlan | 审阅步骤、side-effects、假设 |
| **preview** | `assistant.preview()` / `qteasy-ai preview` / `plan --preview` | 与 Plan 相同 | 原 `ask()` 的「只看 plan 不执行」迁移入口 |
| **Agent（run）** | `assistant.run()` / `qteasy-ai run`；已审阅图用 `run --plan-id` | **是**（CLI 视为一次人在回路确认） | 下载/回测/优化等已确认任务 |

Notebook：`%%qtai --mode ask|plan|preview|run`。`run` 仍须 `%%qtai --confirm <plan_id>` 才真正执行。默认 **display 为 human**（对话区文本）；`--pretty` 为三通道卡片；`--raw` 为 JSON。

## 1.1 输出档位（CLI / Notebook）

| 档位 | CLI | Notebook | 内容 |
|------|-----|----------|------|
| **human（默认）** | `qteasy-ai plan "..."` | `%%qtai --mode plan` | 装配层人读卡：Ask 答案 / 澄清 / 英文错误 / `plan_ready` 短通知 / **run 结果卡**。数字只来自 JSON。 |
| **pretty** | `--pretty` | `--pretty` | 结构化 `narrative` + `python_code` + `result_preview`（JSON 或三通道 Markdown） |
| **raw** | `--raw` | `--raw` | 装配层 payload，供脚本与实弹 |

槽齐不会自动执行。`--human` **只打印内核已写好的卡**，三端禁止反解析卡或 `plan.md`。Plan dry-run 对话区是一句 `plan_ready` 短通知（已创建、`plan_id`、风险一句、Artifact 路径、两条模式缺口）；完整 `plan.md` 是工作台 Artifact（`type=plan`），JSON 才是执行金标准（**json_wins**：改磁盘 md 不会改变 `run --plan-id`）。**`run` / Agent 不创建、不展示 `plan.md`**；ToolPlan JSON 仍进 `runs/{run_id}.json`。磁盘文件名是 **`run_<id>.json`**（Plan 另有 **`run_<id>.plan.md`**），不是 `plan_<id>`。`plan_id` 只写在 JSON 里。无子命令时打印用法卡（`ask` / `plan` / `run --plan-id`），**不会**自动 `run`。概念题在 `plan`/`run` 里会降级为 Ask，并带 `mode_notice`。

Plan 成功即本句完成（保留当前 `plan_id`）。Workbench Confirm 是可选快捷，不阻塞输入。两条须先写在卡上的缺口：说「本次只讨论 / just discuss」→ Ask；在 Plan 里说「执行上面的计划 / 请运行计划 plan_xxx」→ 执行该计划。澄清中 `skip` / `跳过` 结束本句（失败），不会猜缺省槽。

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
- Hybrid Planner（方案 H′）：分类只出 **Job ID**（`planner_trace.intent_job` / `source` / `rationale`）；已知 Job 由代码菜谱出图。配置了 Provider 时，0 命中或冲突表未覆盖才让 LLM 选 Job；非法 JSON / 未知 id → `clarify`，禁止降级回扁平 skill 菜单。未配置 Provider 且 0 命中 → `clarify`。
- `profile.agent.allow_*` 只门控 session 内 `agent_auto`。一次性 `run "<query>"` 仍视为一次确认。

## 4. Provider

未设置 `QTEASY_AI_MODEL` 时：

- Ask：Offline KnowledgeBase。
- Plan：规则路由（不调用 LLM）。

设置 `QTEASY_AI_MODEL` / `QTEASY_AI_API_KEY` / `QTEASY_AI_BASE_URL` 后：Ask 可走 LLM 合成；Plan 可走 LLM 候选 + 规则门禁。默认请求超时 **120 秒**（`QTEASY_AI_TIMEOUT` / `ai_timeout` 可覆盖）。

```bash
qteasy-ai provider-check
```

## 5. Multi-turn session（Q-AI.6）

Use the same `session_id` on CLI and Notebook so a follow-up **revises** the last closed ToolPlan instead of starting a new one-shot classify.

```bash
qteasy-ai plan "帮我下载日线" --session-id demo
qteasy-ai plan "20240101 到 20241231" --session-id demo
qteasy-ai ask "what is qteasy"
qteasy-ai ask "explain PT vs PS" --session-id demo
```

```python
from qteasy_ai.app import QteasyAssistant

assistant = QteasyAssistant()
assistant.plan("帮我下载日线", session_id="demo", response_style="raw")
filled = assistant.plan("20240101 到 20241231", session_id="demo", response_style="raw")
assert filled["plan"]["planner_trace"]["source"] == "session"
```

Rules (user-facing):

- Without `--session-id` / `session_id`, each sentence is independent (same as today).
- Fill or change a slot: same Job, no new classify. Switching topic skips the previous closed job (`Previous topic skipped.`) without an abandon card. Session id and history stay. Open-loop abandon (trial / whole open job) is unchanged.
- Clarification pauses the turn. Reply with the missing field (next sentence fills the slot). `skip` / `跳过` ends this request as a failure. After 3 rounds on the same intent the response stays `clarify`.
- A successful Plan dry-run is complete; the current `plan_id` remains the artifact. Say so in Plan mode to run it, or use Confirm.
- Optional `profile.defaults` (shares / start / end / freq) may fill **optional** slots only. They show as defaults and stay unconfirmed until you say yes.
- `allow_refill` / `allow_backtest` / `allow_optimize` apply only to unattended `agent_auto`. A one-shot `run "<query>"` is still one human confirmation. Live trade is never auto.
- First init creates `user_kb/` (rules / raw / compiled + English README). Ask does **not** search it.

Notebook: `%%qtai --mode plan --session-id demo`.

## 6. Workbench Web / TUI（Q-AI.7）

Desktop three-pane Web and a minimal TUI wrap the same `QteasyAssistant` as CLI/Notebook. They share `runs/`. Completing slots still only shows a Plan card; Confirm is optional and does not block the composer. Cancel dismisses the card (it does not abandon a closed job). Chat panes **only render** kernel cards (`ask` / `plan_ready` / `clarify` / `result` / `error` / `mode_notice`). Web reviews `plan.md` as an Artifact (`type=plan`); the TUI still confirms from the DTO `plan_card` (no Artifact column). JSON wins over markdown.

```bash
pip install "qteasy-ai[workbench]"
qteasy-ai serve --host 127.0.0.1 --port 8765
qteasy-ai tui --session-id demo
```

Details: [WORKBENCH.md](WORKBENCH.md). Hand-off checklist: [LIVE_FIRE_DRILL_QAI7.md](LIVE_FIRE_DRILL_QAI7.md).

## 7. StrategyBuilder（Q-AI.4）

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

## 8. 更多

- 快速上手：[tutorials/quickstart.md](tutorials/quickstart.md)
- 阶段 A 设计备忘（含现状 vs 目标态）：[design/11-ai-shell-stage-a.md](design/11-ai-shell-stage-a.md)
- 阶段 D 手测：[LIVE_FIRE_DRILL_QAI4.md](LIVE_FIRE_DRILL_QAI4.md)
- 阶段 E 手测：[LIVE_FIRE_DRILL_QAI5.md](LIVE_FIRE_DRILL_QAI5.md)（Mode-R 全清单 + Mode-D 抽测；入口 `qteasy-ai plan "<q>" --raw`）
- 阶段 F 手测：[LIVE_FIRE_DRILL_QAI6.md](LIVE_FIRE_DRILL_QAI6.md)（**已关单 2026-09-07**；session / Ask「什么是 qteasy」/ user_kb 骨架）
- 阶段 G 工作台：[WORKBENCH.md](WORKBENCH.md)；手测 [LIVE_FIRE_DRILL_QAI7.md](LIVE_FIRE_DRILL_QAI7.md)（编码完成；1.0 标签待 Jackie）；人读卡审阅 [LIVE_FIRE_DRILL_QAI7_HUMAN.md](LIVE_FIRE_DRILL_QAI7_HUMAN.md)
- 官方 KB 目录：[KB_TIER1.md](KB_TIER1.md)
- 示例：`examples/ai_shell_stage_c_ask_demo.py`、`examples/ai_shell_stage_d_strategybuilder_demo.py`、`examples/ai_shell_stage_g_workbench_demo.py`
