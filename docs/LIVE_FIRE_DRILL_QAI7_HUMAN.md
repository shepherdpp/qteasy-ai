# Q-AI.7 G.8 人读卡实弹（Jackie 审阅）

**状态：编码已落地（2026-09-11）；等人读观感反馈。不关 G.6。不关 G.7。不升版。**

基线：qteasy-ai 工作台 extra · qteasy **>=2.6** · Python **py39** · **Mode-R**（可不配 Provider）

| 项 | 说明 |
|----|------|
| **目标** | 对照「原始载荷 / 错误」与对话区、CLI `--human` 的人读卡：是否像人话、数字是否只来自 JSON、三端是否同一套卡 |
| **非目标** | G.6 可用性签字、G.7 开放环 UI、Beginner Journey 全表、改 md 后执行、升版、第五模式 |
| **前手册** | [Q-AI.7 壳](LIVE_FIRE_DRILL_QAI7.md)（编码完成，1.0 待签）；开放环另页 [QAI7_OPEN](LIVE_FIRE_DRILL_QAI7_OPEN.md) Hang |
| **契约** | qteasy 仓 `knowledge/domain/qteasy-ai-human-card.md` |

本页「期望卡」是 **当前投影器原文**（可能仍不够人读）。请按观感栏打分，不要按「和 `--raw` 完全一致」打分。

---

## 怎么看、怎么记

**CLI（同一句建议连打两档）**

```bash
cd ~/Projects/qteasy-ai
export PYTHONPATH="$HOME/Projects/qteasy-ai:$HOME/Projects/qteasy:$PYTHONPATH"

# 人读卡（对话区同文）
qteasy-ai <subcommand> "…"                 # 默认 --human

# 原始载荷（对照用，不是给人读的）
qteasy-ai <subcommand> "…" --raw
```

`--raw` 里看：`human_cards[].kind` / `.text` / `.payload`，以及 `error`、`execution`、`plan.steps`、`clarification`。  
`--pretty` 仍是调试轨，**不要**当人读金标准。

**Web**

```bash
qteasy-ai serve --host 127.0.0.1 --port 8765
```

对话气泡 = 卡 `text`。Plan 审阅看 Artifact 页 `type=plan`（`plan.md`），**不要**指望对话区出现整份 `# ToolPlan`。TUI 无 Artifact 栏，确认仍看 DTO `plan_card`。

**建议 session**

| 入口 | session |
|------|---------|
| CLI 多轮 | `--session-id h8`（或每条换新 id，避免串槽） |
| Web | 新建 Session，模式点 Ask / Plan / Agent |

**观感栏（每条填一个）**

| 记号 | 含义 |
|------|------|
| **OK** | 人读够用，可关这条 |
| **TECH** | 太像内部字段 / skill 名堆砌 |
| **LONG** | 太长，对话区应再短 |
| **MISS** | 缺关键数字或下一步 |
| **WRONG** | 和原始事实不符，或像第五模式 |
| **REWRITE** | 请另写一句期望英文（贴在反馈里） |

禁止项（任一条出现即记 **WRONG**）：对话区出现 `gold_lock` / `hybrid_intent` / 整份 `# ToolPlan`；数字是卡里捏造的百分比；Ask 出现可 Confirm 执行的步骤；无子命令自动 `run`。

---

## 安全

- 默认 **ask / plan**。无日期全市场 refill **不要** Confirm / `run`。
- 一次性 `qteasy-ai run "<query>"` 仍是一次人确认（只读 list 可跑；回测/下载请先看 side-effects）。
- live **永不 auto**。

---

## Mode-R 清单：原始信息 → 人读卡

表中「原始」是 `--raw` 里应看到的事实；「人读卡」是 `--human` / Web 气泡 **当前**应打出的英文。CLI 与 Web **同文**（Web 可能多一行 Sources / 确认按钮，但不另编散文）。

### A. 入口与降级

| # | 操作 | 原始信息（`--raw` / 内核） | 人读卡（当前实现） | CLI | Web | 观感 |
|---|------|---------------------------|-------------------|-----|-----|------|
| H0 | 裸打 `qteasy-ai`（无子命令） | argparse **不再**是唯一出口；`command is None`；**不**创建 `runs/` | `[MODE: NOTICE]` + `mode_notice`：`qteasy-ai needs a subcommand. It does not run tasks by default.` 并含三行示例 `qteasy-ai ask` / `plan` / `run --plan-id`。exit 0 | ☐ | — |  |
| H1 | `ask "什么是 qteasy"` | `mode=ask`；`sources` 含 `what_is_qteasy`；**无** `execution` / 无可执行 `steps` | `[MODE: ASK]` + `ask`：英文 KB 答案（含 “qteasy”）；末行 `Sources: what_is_qteasy`。**无** `Confirm: qteasy-ai run --plan-id` | ☐ | ☐ Ask 模式 |  |
| H2 | `plan "什么是 qteasy"` | `intent_job=route_to_ask` → 转 Ask；`requested_mode=plan`；`effective_kind=ask`；`execution` 不是 `success` | 先 `mode_notice`：`You requested PLAN, but this is an Ask answer (no executable steps).` 再 H1 同款 `ask` 正文。`plan_card` 不可确认 | ☐ | ☐ **点 Plan** 再发同一句 |  |
| H3 | `run "什么是 qteasy"` | 同上，`requested_mode=run`；**不得** execute fallback | `You requested RUN, but this is an Ask answer (no executable steps).` + Ask 正文。无 execute success | ☐ | ☐ **点 Agent** 再发同一句 |  |

### B. Plan 审阅 vs Agent 结果

| # | 操作 | 原始信息 | 人读卡（当前实现） | CLI | Web | 观感 |
|---|------|----------|-------------------|-----|-----|------|
| H4 | `plan "list built-in strategies"` | `execution.status=dry_run`；`plan.steps[0].skill_name=qt.ai.strategy_meta.list`；磁盘 `{run_id}.json` **和** `{run_id}.plan.md`；`plan_id` ≠ `run_id` | `[MODE: PLAN]  dry_run — not executed` + `plan_ready` 以 `Plan ready.` 开头，含 `Job: strategy.meta`、`Steps: 1`、`Skill: qt.ai.strategy_meta.list`、`Calls: qteasy.built_in_list`、`Confirm: qteasy-ai run --plan-id <plan_id>`、`Storage:` 下 `plan_id` / `run_id`。对话**不含** `# ToolPlan`。Web Artifact 有 `type=plan`，正文才是 md | ☐ | ☐ Plan；打开 Artifact `plan` 页 |  |
| H5 | 同句 `run "list built-in strategies"`（一次性确认） | `execution.status=success`；steps 含 list skill；**无**新的 `{run_id}.plan.md`；JSON 仍在 | `[MODE: RUN]  executed` + 短卡 `executing`：`Running steps.` + `result`：`Status: success`、`N built-in ids`、若干策略 id（来自 JSON `payload.strategies` / `metrics.count`）。**无** `type=plan` Artifact。数字须能在 `--raw` 的 `metrics` / `payload` 对上 | ☐ | ☐ Agent 发同一句 |  |
| H6 | H4 之后 `run --plan-id <H4 的 plan_id>` | 只执行 JSON steps；与改磁盘 md 无关 | 同 H5 结果卡；`plan_id` 仍是 H4 那个 | ☐ | ☐ Artifact / 确认卡点 Run |  |

### C. 澄清中断（先停，再补槽）

| # | 操作 | 原始信息 | 人读卡（当前实现） | CLI | Web | 观感 |
|---|------|----------|-------------------|-----|-----|------|
| H7 | `plan "帮我下载日线" --session-id h8` | `clarify_required`；`pending_clarification.pending` 含 start/end；`execution=dry_run`；本轮**不** execute | `kind=clarify`，正文优先 `confirm_prompt`：`Reply with the missing fields, or say yes if the restatement is correct.`（或 restatement `You asked: 帮我下载日线`）。Web 是澄清表单，不是可 Confirm 执行卡 | ☐ | ☐ Plan |  |
| H8 | 同 session：`plan "start 20240101 end 20241231" --session-id h8` | `fill_slot`；`active_intent.job` 仍为 `data.refill`；`planner_trace.source=session`；**不要**当新 H′ | 槽齐后应出 **H4 同类** `plan_ready`（Job refill、skill `qt.ai.data.refill_basic_equity_and_index`、高风险 / Confirm）。**不要**再只停在 clarify。**不要 Confirm**（无 token / 全市场） | ☐ | ☐ 同一 Session 补日期 |  |
| H9 | 新 session：先 `plan "list built-in strategies" --session-id h8a`（不 run），再 `plan "download daily bars from 20180101 to 20201231" --session-id h8a` | 未完成任务 + 新意图 → `awaiting_abandon`；`clarification.options` 非空 | `clarify`：`Reply abandon to drop the current task. Session id and turns stay.`；`payload.options` 含 `{id: abandon}` / `{id: continue}`。Web 应能看见选项语义，不是空表单 | ☐ | ☐ |  |

### D. 错误、空结果、json_wins

| # | 操作 | 原始信息 | 人读卡（当前实现） | CLI | Web | 观感 |
|---|------|----------|-------------------|-----|-----|------|
| H10 | `run --plan-id plan_does_not_exist` | `ValueError` / `error.code=PLAN_ID_NOT_FOUND`；message 含 `Reviewed plan not found in runs/: plan_id='plan_does_not_exist'` | `error` 正文 = 上述英文 message（或 CLI 4xx 单行同一句）。`next_action` 约为：`Create or select a plan in this session, then Confirm.`（HTTP 4xx 可能是：`Create a plan first, then press Confirm. The plan_id lives in runs/, not as a filename.`）。**禁止**空 success | ☐ | ☐ 伪造 plan_id Confirm（若 UI 允许）或只测 CLI |  |
| H11 | `plan "list built-in strategies"` 成功后，把 `{run_id}.plan.md` 末尾改成 `# HACKED` + 假 skill 名，再 `run --plan-id <原 plan_id>` | 磁盘 md 已脏；JSON steps 仍是 `qt.ai.strategy_meta.list` | 结果卡 skill **仍是** list，**不是** backtest。对话不出现 `# HACKED`。此条验 **json_wins**，不是验文采 | ☐ | ☐ 可只 CLI |  |
| H12 | 新 session：先 Plan 金句「20/60 均线 + 2015–2020 沪深300 回测」，再 `plan "把慢线改成 50" --session-id h8b` | 跟进 `change_slot`；**新** `plan_id`；磁盘另一份 `{new_run_id}.plan.md`；旧 id 不执行新槽 | 第二条是新的 `plan_ready`（新 Confirm plan_id）。对话仍是短通知，不是把两份 md 贴进气泡 | ☐ | ☐ 同一 Session 改槽 |  |

H12 若走进开放环设计卡：记一笔「走了 design_card」，**不要**为了本表硬 Confirm 试错。开放环观感归 [QAI7_OPEN](LIVE_FIRE_DRILL_QAI7_OPEN.md)。

### E. 只读结果数字（Mode-R，须能对上 JSON）

| # | 操作 | 原始信息 | 人读卡（当前实现） | CLI | Web | 观感 |
|---|------|----------|-------------------|-----|-----|------|
| H13 | `run "show me bband strategy parameters"`（或 Plan + Confirm） | `qt.ai.strategy_meta.get`；`payload.strategy_id=bband`；`payload.doc` 非空 | `result` 含 `id=bband` 与 docstring 摘要（过长会截断并写 `… truncated; use --raw`）。**不要**编造夏普/回撤 | ☐ | ☐ |  |
| H14 | （可选，需本地库）`plan` 再 Confirm：`show summary of 000300.SH from 20240101 to 20241231` | `data.summary` / `metrics` 标量在 JSON | `result` 只回显 JSON 里已有的 `summary:` / `metrics:` `k=v`。对话区数字与 `--raw` **逐个对得上** | ☐ | ☐ |  |

### F. 对照与禁止项（抽查即可）

| # | 操作 | 期望 |
|---|------|------|
| H15 | 任意成功 Plan：对比 CLI `--human` 与 Web 气泡 | 同一套 `Plan ready.` / Job / Confirm；Web **多** Artifact `plan` 页，不把 md 塞回对话 |
| H16 | 任意成功 Ask / Plan：`--human` 与 `--raw` 的 `human_cards[].text` 拼接 | 除 `[MODE: …]` 与 Ask 的 `Sources:` 行外，正文一致 |
| H17 | 全文搜索对话 / `--human` | **无** `gold_lock`、`hybrid_intent`、`# ToolPlan` |
| H18 | TUI（可选）`qteasy-ai tui --session-id h8t` 再 Plan list | 确认卡仍是 steps / side-effects；**无** Artifact Tab；聊天可见 `plan_ready` 短文 |

---

## 反馈怎么写（直接贴回来即可）

每条一行即可，例如：

```text
H2 TECH：mode_notice 太像内部枚举，希望改成 “You clicked Plan, but this is a concept question.”
H4 LONG：Job/Calls/Expects/Storage 四段进对话太长，对话只留一行，细节去 Artifact
H5 MISS：策略 id 列表可以，但缺少 “N total”
H7 OK
```

请同时注明 **CLI 或 Web**（或都测了）。数字类请附 `--raw` 里对应字段名（如 `metrics.count=123`）。

---

## 交叉

- 用户说明：[USER_GUIDE.md](USER_GUIDE.md) §1.1、[WORKBENCH.md](WORKBENCH.md)
- 壳层手测：[LIVE_FIRE_DRILL_QAI7.md](LIVE_FIRE_DRILL_QAI7.md)（不在本页重签 G1–G10）
- 手测总入口：[MANUAL_TEST.md](MANUAL_TEST.md)
