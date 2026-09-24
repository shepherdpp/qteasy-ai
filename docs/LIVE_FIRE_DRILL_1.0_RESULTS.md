# 1.0 发版前实弹结果（空白）

**手续真源：** [`LIVE_FIRE_DRILL_1.0.md`](LIVE_FIRE_DRILL_1.0.md)。本文件只记结果，不改步骤。

| 项 | 填写 |
|----|------|
| 日期 | |
| 环境 | py39 · qteasy-ai extra · Mode-R / 其它： |
| 记录人 | |
| 备注 | |

任一 FAIL 不得打 `1.0.0`。David 不改 semver。

## Status

| 块 | 日期 | 结果（PASS / FAIL / SKIP / PENDING） | 记录人 | 备注 |
|----|------|--------------------------------------|--------|------|
| **A1** 全量 `test_ai_*.py` | | | | |
| **A2** CLI 22 skill | | | | |
| **A3** CLI 18 KB Ask | | | | |
| **B0** Workbench 可用性壳 | | | | |
| **B1** Workbench 18 KB | | | | |
| **B2** Workbench 22 skill | | | | |
| **关单** G.6 + 能力边界 | | | | |

## A2. CLI skill

| # | skill | 结果 | plan_id / run_id | 备注 |
|---|-------|------|------------------|------|
| 1 | `qt.ai.env.check_tushare` | | | |
| 2 | `qt.ai.env.overview_tables` | | | |
| 3 | `qt.ai.strategy_meta.list` | | | |
| 4 | `qt.ai.strategy_meta.get` | | | |
| 5 | `qt.ai.data.summary_kline` | | | |
| 6a | `qt.ai.data.read` history | | | |
| 6b | `qt.ai.data.read` reference | | | |
| 6c | `qt.ai.data.read` static | | | |
| 7 | `qt.ai.visual.export_kline` | | | |
| 8 | `qt.ai.data.refill_basic_equity_and_index` | | | |
| 8n | 无界 refill 负例 | | | |
| 9 | `qt.ai.research.factor_ic_summary` | | | |
| 10 | `qt.ai.research.universe_filter` | | | |
| 11 | `qt.ai.research.price_predicate` | | | |
| 12 | `qt.ai.research.project_universe` | | | |
| 13 | `qt.ai.research.screen_stocks`（负例） | | | |
| 14 | `qt.ai.backtest.run_builtin` | | | |
| 15 | `qt.ai.insight.summarize_backtest` | | | |
| 16 | `qt.ai.optimize.run_builtin` | | | |
| 17 | `qt.ai.strategy.spec_from_nl` | | | |
| 18 | `qt.ai.strategy.codegen_hybrid` | | | |
| 19 | `qt.ai.strategy.sanity_check` | | | |
| 20 | `qt.ai.operator.build_from_spec` | | | |
| 21 | `qt.ai.pipeline.live_trade_plan_only` | | | |
| 22a | `qt.ai.system.fallback` clarify | | | |
| 22b | `qt.ai.system.fallback` route_to_ask | | | |

## A3. CLI Ask（18）

| id | 语料 | sources | 结果 | 备注 |
|----|------|---------|------|------|
| `what_is_qteasy` | `what is qteasy` | | | |
| `getting_started` | `getting started` | | | |
| `data_three_entries` | `三入口` | | | |
| `backtest_intro` | `回测入门` | | | |
| `optimize_intro` | `优化入门` | | | |
| `refill_bounded` | `date_range` | | | |
| `strategy_builder_intro` | `strategybuilder` | | | |
| `env_ready` | `check table` | | | |
| `notebook_cli` | `%%qtai` | | | |
| `live_plan_only` | `live plan never auto` | | | |
| `official_vs_user_kb` | `official kb` | | | |
| `pt_ps_vs` | `signal type` | | | |
| `operator_run_freq` | `run_freq` | | | |
| `ask_plan_agent` | `ask vs plan` | | | |
| `side_effects_safety` | `side effect confirm` | | | |
| `common_errors_nan` | `NaN halt` | | | |
| `common_errors_run_freq` | `not a built-in parameter` | | | |
| `common_errors_date_window` | `at least one of start` | | | |

## B0. Workbench 可用性壳

| # | 操作 | 结果 | 备注 |
|---|------|------|------|
| B0.1 | 模式徽章；槽齐不自动 Agent | | |
| B0.2 | 澄清选项卡；Skip = 失败结束 | | |
| B0.3 | `plan_ready` + 只读 `plan.md`；改 md 不执行 | | |
| B0.4 | Confirm → steps / N/M / elapsed；Stop = 停观望 | | |
| B0.5 | Artifact + `run_id`；切 Session 不串 tab；改名/删除不删 `runs/` | | |
| B0.6 | 无界 refill 拒绝；live 不 auto；Ask 不搜 `user_kb`；失败英文可行动 | | |

## B1. Workbench Ask（18）

| id | 语料 | 结果 | 备注 |
|----|------|------|------|
| `what_is_qteasy` | `what is qteasy` | | |
| `getting_started` | `getting started` | | |
| `data_three_entries` | `三入口` | | |
| `backtest_intro` | `回测入门` | | |
| `optimize_intro` | `优化入门` | | |
| `refill_bounded` | `date_range` | | |
| `strategy_builder_intro` | `strategybuilder` | | |
| `env_ready` | `check table` | | |
| `notebook_cli` | `%%qtai` | | |
| `live_plan_only` | `live plan never auto` | | |
| `official_vs_user_kb` | `official kb` | | |
| `pt_ps_vs` | `signal type` | | |
| `operator_run_freq` | `run_freq` | | |
| `ask_plan_agent` | `ask vs plan` | | |
| `side_effects_safety` | `side effect confirm` | | |
| `common_errors_nan` | `NaN halt` | | |
| `common_errors_run_freq` | `not a built-in parameter` | | |
| `common_errors_date_window` | `at least one of start` | | |

## B2. Workbench skill（22）

| # | skill | 结果 | 备注 |
|---|-------|------|------|
| 1 | `qt.ai.env.check_tushare` | | |
| 2 | `qt.ai.env.overview_tables` | | |
| 3 | `qt.ai.strategy_meta.list` | | |
| 4 | `qt.ai.strategy_meta.get` | | |
| 5 | `qt.ai.data.summary_kline` | | |
| 6a | `qt.ai.data.read` history | | |
| 6b | `qt.ai.data.read` reference | | |
| 6c | `qt.ai.data.read` static | | |
| 7 | `qt.ai.visual.export_kline` | | |
| 8 | `qt.ai.data.refill_basic_equity_and_index` | | |
| 9 | `qt.ai.research.factor_ic_summary` | | |
| 10 | `qt.ai.research.universe_filter` | | |
| 11 | `qt.ai.research.price_predicate` | | |
| 12 | `qt.ai.research.project_universe` | | |
| 13 | `qt.ai.research.screen_stocks`（负例） | | |
| 14 | `qt.ai.backtest.run_builtin` | | |
| 15 | `qt.ai.insight.summarize_backtest` | | |
| 16 | `qt.ai.optimize.run_builtin` | | |
| 17 | `qt.ai.strategy.spec_from_nl` | | |
| 18 | `qt.ai.strategy.codegen_hybrid` | | |
| 19 | `qt.ai.strategy.sanity_check` | | |
| 20 | `qt.ai.operator.build_from_spec` | | |
| 21 | `qt.ai.pipeline.live_trade_plan_only` | | |
| 22 | `qt.ai.system.fallback`（clarify + route_to_ask） | | |

## B3. 关单

| 项 | 成立？ | 签字 / 日期 |
|----|--------|-------------|
| 可用性：不看内部手册，能在 Workbench 走完闭合 Beginner（G.6） | | |
| 能力边界：B1 全部 18 KB + B2 全部 22 skill（FAIL 清零或可接受 SKIP） | | |
