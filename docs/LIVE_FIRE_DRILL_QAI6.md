# Q-AI.6（阶段 F）实弹演练手册（Jackie 手动执行）

**状态：编码完成，待 Jackie 手测关单。不升版。不测开放环 / 设计环 / Catalog `workflow`。**

基线：qteasy-ai **0.1.x + 阶段 F 未发版改动** · qteasy **>=2.6** · Python **py39**

| 项 | 说明 |
|----|------|
| **目标** | 多轮 session 补槽/改槽/放弃确认；Ask「什么是 qteasy」命中官方 KB；`allow_*` 只门控 `agent_auto`；CLI `--session-id`；首次初始化后 `user_kb` 分区存在 |
| **非目标** | 开放环状态机、Catalog `workflow` 分叉、用户库检索、TUI/Web、场景三、升版 |
| **回归冒烟** | `python -m unittest tests.test_ai_session tests.test_ai_session_gate tests.test_ai_planner_f tests.test_ai_kb_tier1 tests.test_ai_user_kb_scaffold tests.test_ai_profile_agent tests.test_ai_cli_notebook_entry tests.test_ai_notebook_magic tests.test_ai_beginner_journey -v` |
| **KB 目录** | [`KB_TIER1.md`](KB_TIER1.md) |
| **前手册** | [Q-AI.5](LIVE_FIRE_DRILL_QAI5.md) **已关单** |

**入口**：`qteasy-ai plan "<q>" --session-id demo --raw`。Ask：`qteasy-ai ask "<q>"`。

---

## 安全协议

- 本手册默认 **plan / ask**。不要对无日期全市场 refill 做 `run`。
- 一次性 `qteasy-ai run "<query>"` 仍是 B：人敲了 run = 本轮确认。
- `run --session-id x --agent-auto` 才读 `profile.agent.allow_*`。live **永不 auto**。

---

## Mode-R 清单

| # | 操作 | 期望 |
|---|------|------|
| F1 | `plan "帮我下载日线" --session-id f6` | `clarify_required`；`clarification` 含 restatement / pending / confirm_prompt；`clarify_round=1` |
| F2 | 同 id：`plan "20240101 到 20241231" --session-id f6` | 同一 `data.refill`；steps 含 refill；`planner_trace.source=session` |
| F3 | `plan "把慢线改成 60" --session-id f6b` 先跑 D 金句再跟进 | 仍 `strategy.builder`，槽 slow=60；**不要**当新单句 |
| F4 | 无 `--session-id` 直接 `plan "把慢线改成 60"` | 今日单句：fallback / 不继承上一份 Spec |
| F5 | 未完成 refill 时 `plan "再帮我优化参数" --session-id f6` | 放弃确认；session_id / turns 仍在 |
| F6 | `ask "什么是qteasy"` / `什么是 qteasy` / `what is qteasy` | `sources` 含 `what_is_qteasy`；无 `execution` |
| F7 | profile `defaults.shares=000300.SH` 后 `plan "用 macd 做回测，2018 到 2023" --session-id f6d` | 选填 shares 来自 profile；pretty 可见 default |
| F8 | `run "用 macd 做回测，2018 到 2023" --session-id f6a --agent-auto` 且 `allow_backtest=false` | dry-run，不进 backtest handler |
| F9 | 一次性 `run "list built-in strategies"`（无 agent_auto） | 保持 B，只读 skill 仍执行 |
| F10 | 首次 `MemoryStore` / 任意 CLI | `.qteasy/ai/user_kb/rules`、`raw/{research,trades,factors,strategies}`、`compiled`、英文 README 存在 |

---

## 交叉

- 用户指南 session 小节：[`USER_GUIDE.md`](USER_GUIDE.md)
- 手测总入口：[`MANUAL_TEST.md`](MANUAL_TEST.md)
- 不在本手册打 1.0。
