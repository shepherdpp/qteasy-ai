# 1.0 发版前测试手册（G.5 + G.6）

**状态：手册已冻结（2026-09-24）。Part A 未关闸（A3 3 条 Ask 未命中）。Part B 未签。任一 FAIL 不得打** `1.0.0`**。David 不改 semver。**

基线：qteasy-ai 工作台 extra · qteasy **>=2.6** · Python **py39** · **Mode-R**（可不配 Provider）


| 项       | 说明                                                                                                                                      |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **闸门**  | 1.0 = G.5 非 UI 包 + G.6。本手册是发版前测试真源                                                                                                      |
| **覆盖**  | 现行 **全部 18 条**官方 KB + **全部 22 个** registry skill（含负例 `screen_stocks`）                                                                   |
| **非目标** | 全站文档 RAG、Tutorial 6/7 / HP 2.6+ 深能力、ingest / Plan 队列、场景三 H、升版                                                                           |
| **契约**  | 执行层 G.6；Catalog `[OFFICIAL_SKILL_CATALOG.md](OFFICIAL_SKILL_CATALOG.md)`；KB `[KB_TIER1.md](KB_TIER1.md)`；`[WORKBENCH.md](WORKBENCH.md)` |
| **前手册** | [Q-AI.7 壳](LIVE_FIRE_DRILL_QAI7.md)（雏形）；人读卡 [QAI7_HUMAN](LIVE_FIRE_DRILL_QAI7_HUMAN.md)                                                 |




## Status


| 块                         | 日期         | 结果                                                                                              | 记录人    |
| ------------------------- | ---------- | ----------------------------------------------------------------------------------------------- | ------ |
| **A1** 全量 `test_ai_*.py`  | 2026-09-24 | PASS · 349 tests · 45.5s · exit 0                                                               | David  |
| **A2** CLI 22 skill       | 2026-09-24 | PASS · 22 行均 PASS（含 8n / 13 负例 / 22a+22b）                                                       | David  |
| **A3** CLI 18 KB Ask      | 2026-09-24 | FAIL · 15/18；`backtest_intro` / `optimize_intro` / `strategy_builder_intro` 命中 `ask_plan_agent` | David  |
| **B0** Workbench 可用性壳     | —          | PENDING                                                                                         | Jackie |
| **B1** Workbench 18 KB    | —          | PENDING                                                                                         | Jackie |
| **B2** Workbench 22 skill | —          | PENDING                                                                                         | Jackie |
| **关单** G.6 + 能力边界         | —          | 未签                                                                                              | Jackie |


**关闸顺序：** A1+A2+A3 全绿（或合法 SKIP）→ Jackie 做 B0–B2 → 两项签字成立 → Jackie 可打 `1.0.0`。

**A 记录（2026-09-24，Mode-R，隔离** `QTEASY_AI_HOME`**）：**

- A1：`unittest discover -s tests -p 'test_ai_*.py'`。首跑 2 FAIL + 1 ERROR 为断言漂移（G.6 时钟 `formatRunClock("Working")`；G.9 clarify 可空 `execution.steps`），对齐后重跑全绿。
- A2：CLI `plan --raw` 全员；只读/低副作用另 `run`。22b `explain PT and PS`：`plan` 转 Ask（`mode=ask`，`sources` 含 `pt_ps_vs`，零办事 step），按手册 route_to_ask 记 PASS。
- A3：手册语料原句。三败因 Ask 把「回测/优化/strategybuilder」当可执行请求，检索落到 `ask_plan_agent`。属 1.0.x Ask 覆盖，本轮不改检索。

---



## 安全协议

- 默认 `ask` **/** `plan`。无日期 / 全市场 refill **禁止** `run`。
- 高副作用（refill / backtest / optimize / codegen 写盘）：有界日期 + Confirm / `--plan-id` 后才执行。缺 token / 缺表记 **SKIP + 原因**，不得静默当 PASS。
- `live` **永不 auto**。`live_trade_plan_only` 只验证「出清单、不执行下单」。
- `qt.ai.research.screen_stocks` 是 **负例**：菜谱不得以其为主步。
- Ask 不检索 `user_kb/`。

入口：

```bash
cd ~/Projects/qteasy-ai
export PYTHONPATH="$HOME/Projects/qteasy-ai:$HOME/Projects/qteasy:$PYTHONPATH"
# Web（Part B）
qteasy-ai serve --host 127.0.0.1 --port 8765
```

CLI 判定用 `--raw`（看 `sources` / `plan.steps[].skill_name` / `execution`）。`--human` 给人读，不是 A 的金标准。

---



## Part A — David 自动化（必跑）



### A1. 全量 unittest

```bash
cd ~/Projects/qteasy-ai
/opt/anaconda3/envs/py39/bin/python -m unittest discover -s tests -p 'test_ai_*.py' -v
```

- 范围：仓库内 **全部** `test_ai_*.py`。禁止只跑定向子集冒充发版门禁。
- 判据：exit 0、零 FAIL/ERROR。



### A2. CLI 全 skill 矩阵（22）

对 Catalog §3 每一个注册名至少一条可判定 CLI 路径。Mode-R。`plan --raw` 全员必过；只读/低副作用再 `run` 或 `--plan-id`；高副作用有界 + 显式确认后才 `run`。

DAG 可合并执行（例如 screen 三步、StrategyBuilder 四步），**勾选表仍逐行勾**。不得因 Journey 已覆盖而跳过未点名 skill。


| #   | skill                                      | 语料                                                               | 期望                                                   | run 政策            | A    | 备注                       |
| --- | ------------------------------------------ | ---------------------------------------------------------------- | ---------------------------------------------------- | ----------------- | ---- | ------------------------ |
| 1   | `qt.ai.env.check_tushare`                  | `帮我看 Tushare 是否配好、本地缺哪些表`                                        | Job `env.ready`；steps 含本 skill                       | run 允许            | PASS | run 已执行                  |
| 2   | `qt.ai.env.overview_tables`                | 同上（同 DAG）                                                        | steps 含本 skill                                       | run 允许            | PASS | 同 DAG                    |
| 3   | `qt.ai.strategy_meta.list`                 | `list built-in strategies`                                       | Job `strategy.meta`                                  | run 允许            | PASS |                          |
| 4   | `qt.ai.strategy_meta.get`                  | `show me macd strategy parameters`                               | Job `strategy.meta`                                  | run 允许            | PASS |                          |
| 5   | `qt.ai.data.summary_kline`                 | `kline summary of 000300.SH`                                     | Job `data.summary`                                   | run 允许            | PASS |                          |
| 6a  | `qt.ai.data.read` history                  | `get_history_data close for 000300.SH from 20240101 to 20240131` | Job `data.read`；channel=history                      | run 允许            | PASS |                          |
| 6b  | `qt.ai.data.read` reference                | `get_reference_data cn_gdp from 20240101 to 20240131`            | channel=reference                                    | run 允许            | PASS |                          |
| 6c  | `qt.ai.data.read` static                   | `get_static_data industry for 000001.SZ`                         | channel=static                                       | run 允许            | PASS |                          |
| 7   | `qt.ai.visual.export_kline`                | `export kline of 000300.SH to png`                               | Job `data.export`                                    | run 允许（写图）        | PASS |                          |
| 8   | `qt.ai.data.refill_basic_equity_and_index` | `download daily data from 20180101 to 20231231`                  | Job `data.refill`                                    | 有界才可 Confirm；无界须拒 | PASS | plan_only（高副作用未 Confirm） |
| 8n  | （无界负例）                                     | `download A-share daily data to local datasource`                | `clarify_required` / missing `date_range`；**不得** run | plan only         | PASS | skill=`fallback`；未 run   |
| 9   | `qt.ai.research.factor_ic_summary`         | `factor IC summary for selection pool`                           | Job `research.factor_ic`                             | run 允许            | PASS |                          |
| 10  | `qt.ai.research.universe_filter`           | `请搜索过去半年内所有跌幅>20%，且行业属于制造业的股票。`                                  | Job `research.screen`                                | run 允许            | PASS |                          |
| 11  | `qt.ai.research.price_predicate`           | 同上                                                               | 同 DAG                                                | run 允许            | PASS |                          |
| 12  | `qt.ai.research.project_universe`          | 同上                                                               | 同 DAG                                                | run 允许            | PASS |                          |
| 13  | `qt.ai.research.screen_stocks`             | 同上（负例）                                                           | **steps 不得**以本 skill 为主路径                            | 负例                | PASS | 菜谱无此主步                   |
| 14  | `qt.ai.backtest.run_builtin`               | `用 macd 在沪深300上跑 2018–2023 回测，给我看年化与最大回撤`                        | Job `backtest.builtin`                               | 有界 Confirm 后可 run | PASS | plan_only                |
| 15  | `qt.ai.insight.summarize_backtest`         | `总结上次回测`（先有回测 run 更佳）                                            | Job `insight.last_backtest`                          | run 允许            | PASS |                          |
| 16  | `qt.ai.optimize.run_builtin`               | `optimize DMA parameters`                                        | Job `optimize.builtin`                               | 有界 Confirm 后可 run | PASS | plan_only                |
| 17  | `qt.ai.strategy.spec_from_nl`              | `帮我写一个基于 20/60 日均线金叉死叉的择时策略，并用 2015–2020 年沪深300做回测`              | Job `strategy.builder`                               | 写盘须确认             | PASS | plan_only                |
| 18  | `qt.ai.strategy.codegen_hybrid`            | 同上                                                               | 同 DAG                                                | 写盘须确认             | PASS | 同 DAG                    |
| 19  | `qt.ai.strategy.sanity_check`              | 同上                                                               | 同 DAG                                                | 随 DAG             | PASS | 同 DAG                    |
| 20  | `qt.ai.operator.build_from_spec`           | 同上                                                               | 同 DAG                                                | 随 DAG             | PASS | 同 DAG                    |
| 21  | `qt.ai.pipeline.live_trade_plan_only`      | `start live trade now`                                           | Job `live.plan_only`；只出清单                            | plan / run 均不得下单  | PASS | run 只出清单                 |
| 22a | `qt.ai.system.fallback` clarify            | 8n 同句                                                            | fallback / `clarify_required`                        | plan only         | PASS | 同 8n                     |
| 22b | `qt.ai.system.fallback` route_to_ask       | `explain PT and PS`                                              | Job `route_to_ask`                                   | 转 Ask；零办事 step    | PASS | `mode=ask` · `pt_ps_vs`  |


每行记：`command`、`plan_id`/`run_id`、**PASS | FAIL | SKIP**。SKIP 必须写原因（缺 token / 缺表 / 本机无数据）。

### A3. CLI 全 KB Ask（18）

`qteasy-ai ask "<语料>" --raw` → `sources` 含该 `id`；零 skill；无 `execution` 办事步。


| id                          | 语料                         | A                               |
| --------------------------- | -------------------------- | ------------------------------- |
| `what_is_qteasy`            | `what is qteasy`           | PASS                            |
| `getting_started`           | `getting started`          | PASS                            |
| `data_three_entries`        | `三入口`                      | PASS                            |
| `backtest_intro`            | `回测入门`                     | FAIL · sources=`ask_plan_agent` |
| `optimize_intro`            | `优化入门`                     | FAIL · sources=`ask_plan_agent` |
| `refill_bounded`            | `date_range`               | PASS                            |
| `strategy_builder_intro`    | `strategybuilder`          | FAIL · sources=`ask_plan_agent` |
| `env_ready`                 | `check table`              | PASS                            |
| `notebook_cli`              | `%%qtai`                   | PASS                            |
| `live_plan_only`            | `live plan never auto`     | PASS                            |
| `official_vs_user_kb`       | `official kb`              | PASS                            |
| `pt_ps_vs`                  | `signal type`              | PASS                            |
| `operator_run_freq`         | `run_freq`                 | PASS                            |
| `ask_plan_agent`            | `ask vs plan`              | PASS                            |
| `side_effects_safety`       | `side effect confirm`      | PASS                            |
| `common_errors_nan`         | `NaN halt`                 | PASS                            |
| `common_errors_run_freq`    | `not a built-in parameter` | PASS                            |
| `common_errors_date_window` | `at least one of start`    | PASS                            |


**Part A 关闸：** A1 全绿 + A2 每行 PASS/合法 SKIP + A3 18 行均命中。

---



## Part B — Jackie 手动（仅 Workbench）

入口：`qteasy-ai serve` → 桌面 Web 三栏。每条：模式、输入原文、期望、Jackie 栏 **OK | FAIL | 备注**。

TUI 不作为签字主路径（CLI/自动化已覆盖契约）。可选一行 TUI 冒烟，不挡签字。

### B0. G.6 可用性壳（签字前提）


| #    | 操作                                                     | 期望                                                            | Jackie |
| ---- | ------------------------------------------------------ | ------------------------------------------------------------- | ------ |
| B0.1 | 打开 Web                                                 | Ask/Plan/Agent 徽章可见；默认 Plan；槽齐 **不**自动 Agent                  |        |
| B0.2 | Plan `download A-share daily data to local datasource` | 澄清选项卡；Skip = 失败结束                                             |        |
| B0.3 | Plan `list built-in strategies`                        | `plan_ready` 短通知；Artifact 只读 `plan.md`；改 md **不**执行           |        |
| B0.4 | Confirm 只读 plan                                        | `steps[]` / 进度 N/M / elapsed；Stop = 停观望（服务端可能仍跑）              |        |
| B0.5 | 执行后                                                    | Artifact + `run_id` 可导出；切 Session 不串 tab；改名/删除 **不**删 `runs/` |        |
| B0.6 | 安全                                                     | 无界 refill 拒绝；live 不 auto；Ask 不搜 `user_kb`；失败英文提示可行动           |        |




### B1. 语料清单 — 全部 KB（18）

Workbench **Ask 模式**逐条。期望：Ask 卡 + sources 含对应 id；无 Confirm/execute。


| id                          | 语料                         | Jackie |
| --------------------------- | -------------------------- | ------ |
| `what_is_qteasy`            | `what is qteasy`           |        |
| `getting_started`           | `getting started`          |        |
| `data_three_entries`        | `三入口`                      |        |
| `backtest_intro`            | `回测入门`                     |        |
| `optimize_intro`            | `优化入门`                     |        |
| `refill_bounded`            | `date_range`               |        |
| `strategy_builder_intro`    | `strategybuilder`          |        |
| `env_ready`                 | `check table`              |        |
| `notebook_cli`              | `%%qtai`                   |        |
| `live_plan_only`            | `live plan never auto`     |        |
| `official_vs_user_kb`       | `official kb`              |        |
| `pt_ps_vs`                  | `signal type`              |        |
| `operator_run_freq`         | `run_freq`                 |        |
| `ask_plan_agent`            | `ask vs plan`              |        |
| `side_effects_safety`       | `side effect confirm`      |        |
| `common_errors_nan`         | `NaN halt`                 |        |
| `common_errors_run_freq`    | `not a built-in parameter` |        |
| `common_errors_date_window` | `at least one of start`    |        |




### B2. 语料清单 — 全部 Skill（22）

Workbench **Plan**（必要时 Confirm）。每个 registry skill 至少被点到一次。DAG 可合并，勾选仍 22 行。语料与 A2 同源。


| #     | skill                                      | 语料                                                               | 期望                                 | Jackie |
| ----- | ------------------------------------------ | ---------------------------------------------------------------- | ---------------------------------- | ------ |
| 1     | `qt.ai.env.check_tushare`                  | `帮我看 Tushare 是否配好、本地缺哪些表`                                        | `env.ready`                        |        |
| 2     | `qt.ai.env.overview_tables`                | 同上                                                               | 同 DAG                              |        |
| 3     | `qt.ai.strategy_meta.list`                 | `list built-in strategies`                                       | Confirm 后 Artifact/`run_id`        |        |
| 4     | `qt.ai.strategy_meta.get`                  | `show me macd strategy parameters`                               | `strategy.meta`                    |        |
| 5     | `qt.ai.data.summary_kline`                 | `kline summary of 000300.SH`                                     | `data.summary`                     |        |
| 6a    | `qt.ai.data.read` history                  | `get_history_data close for 000300.SH from 20240101 to 20240131` | 三通道之一                              |        |
| 6b    | `qt.ai.data.read` reference                | `get_reference_data cn_gdp from 20240101 to 20240131`            |                                    |        |
| 6c    | `qt.ai.data.read` static                   | `get_static_data industry for 000001.SZ`                         |                                    |        |
| 7     | `qt.ai.visual.export_kline`                | `export kline of 000300.SH to png`                               | 写图可见                               |        |
| 8     | `qt.ai.data.refill_basic_equity_and_index` | `download daily data from 20180101 to 20231231`                  | 确认门可见 side-effects                 |        |
| 9     | `qt.ai.research.factor_ic_summary`         | `factor IC summary for selection pool`                           |                                    |        |
| 10–12 | screen L1 DAG                              | `请搜索过去半年内所有跌幅>20%，且行业属于制造业的股票。`                                  | universe + predicate + project     |        |
| 13    | `qt.ai.research.screen_stocks`             | 同上（负例）                                                           | **不应**出现为菜谱主步                      |        |
| 14    | `qt.ai.backtest.run_builtin`               | `用 macd 在沪深300上跑 2018–2023 回测，给我看年化与最大回撤`                        | 无 Confirm 不执行                      |        |
| 15    | `qt.ai.insight.summarize_backtest`         | `总结上次回测`                                                         |                                    |        |
| 16    | `qt.ai.optimize.run_builtin`               | `optimize DMA parameters`                                        | 确认门                                |        |
| 17–20 | StrategyBuilder DAG                        | `帮我写一个基于 20/60 日均线金叉死叉的择时策略，并用 2015–2020 年沪深300做回测`              | spec → codegen → sanity → operator |        |
| 21    | `qt.ai.pipeline.live_trade_plan_only`      | `start live trade now`                                           | 只出清单                               |        |
| 22    | `qt.ai.system.fallback`                    | 缺槽 refill + `explain PT and PS`                                  | clarify + route_to_ask             |        |




### B3. 关单句

Jackie 签两项均成立：

1. **可用性**：不看内部开发手册，能在 Workbench 走完闭合 Beginner 体验（G.6）。
2. **能力边界**：B1 全部 18 KB + B2 全部 22 skill 勾选完成（FAIL 清零或已记录可接受 SKIP）。

然后 Jackie 可打 **1.0.0** + CHANGELOG。David **不**改 semver。

---



## 交叉

- Catalog：`[OFFICIAL_SKILL_CATALOG.md](OFFICIAL_SKILL_CATALOG.md)`
- KB：`[KB_TIER1.md](KB_TIER1.md)`
- 工作台：`[WORKBENCH.md](WORKBENCH.md)`
- 手测总入口：`[MANUAL_TEST.md](MANUAL_TEST.md)`
- 空白结果表（Jackie 填写）：[`LIVE_FIRE_DRILL_1.0_RESULTS.md`](LIVE_FIRE_DRILL_1.0_RESULTS.md)
- 执行层 G.6 / §七：qteasy 仓 `.cursor/plans/qteasy_ai_execution_plan_1c8aecc7.plan.md`
- 顶层 §3.9：`.cursor/plans/qteasy_ai_top_level_design.plan.md`

