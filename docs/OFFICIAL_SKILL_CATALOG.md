# Official Skill Catalog v1

**状态：E.4 起草；Phase E 已关单（2026-09-05）。** G.5 自动化对照（2026-09-07）无 P0 缺口。**1.0 标签仍由 Jackie 打。** 不升版。

对照：产品顶层 §3.8 / §3.9；意图门 **H′**；Registry = `build_default_registry()`（61 个 skill，0.4 A4 后）。本目录按 **Job 出图**，不是扁平 skill 菜单。

| 项 | 说明 |
|----|------|
| **用户轨** | [Beginner Journey](../tests/ai_corpus/beginner_journey.json)（18 步） |
| **Mode-R 精确锁** | [`gold.json`](../qteasy_ai/intents/gold.json)（含三入口 `data.read`） |
| **Ask FAQ** | `qteasy_ai/kb/`（[KB_TIER1.md](KB_TIER1.md)，18 条）。Journey `BJ-ASK-WHAT` 命中 `what_is_qteasy` |
| **教程根** | qteasy 仓 `docs/source/` |

每行：`Ask` 或 `Plan`、Job、主 skill、副作用、教程、Journey id。`run` 政策：Beginner 默认 **只 plan**（高副作用不在本轨执行）。

---

## 1. 官方 Job（13）

| Job | 模式 | 菜谱 skill（顺序） | 副作用 | 教程 | Journey |
|-----|------|-------------------|--------|------|---------|
| `env.ready` | Plan | `qt.ai.env.check_tushare` → 四次 `qt.ai.datasource.table_info`（`stock_daily` / `index_daily` / `trade_calendar` / `stock_basic`） | 只读 guide | `getting_started.md`；`tutorials/1-get-started.md` | BJ-ENV |
| `data.refill` | Plan | `qt.ai.data.refill_basic_equity_and_index` | 网络 + 写库；无日期 → clarify | `tutorials/2.0-get-data.md` | BJ-REFILL；缺槽 BJ-REFILL-C |
| `data.read` | Plan | 按 channel：`qt.ai.data.history` / `qt.ai.data.reference` / `qt.ai.data.static` | 只读三入口 | `2.0-get-data.md`；DataType 三入口 | BJ-READ-H / R / S |
| `data.summary` | Plan | `qt.ai.data.kline` → `qt.ai.hp.volatility` 与 `qt.ai.hp.describe` | 只读 | `2.4-historypanel-basics.md`；`2.5-historypanel-data-analysis.md` | BJ-SUM |
| `data.export` | Plan | `qt.ai.data.kline` → `qt.ai.hp.plot` | 写图文件 | 同上 / getting started 看 K 线 | BJ-EXP |
| `research.screen` | Plan | `universe_filter` → 可选 `price_predicate` → `project_universe` | 只读；**无**申万 DSL | 2.5 入门 | BJ-SCR（有谓语） |
| `research.factor_ic` | Plan | `qt.ai.research.factor_ic_summary` | 只读；缺代码/日期/列名 → clarify | 2.5 / `qteasy.research` | BJ-IC |
| `strategy.meta` | Plan | `strategy_meta.list` 或 `.get` | 只读 | `3-start-first-strategy.md`；`4-build-in-strategies.md` | BJ-META-L / G |
| `backtest.builtin` | Plan | `backtest.run_builtin`；`with_insight` 时再 `insight.summarize_backtest` | 回测写日志 / 曲线 | 3 / 4 | BJ-BT（只 plan） |
| `strategy.builder` | Plan | spec → codegen → sanity → operator → 可选 backtest | codegen 写盘 | `5-first-self-defined-strategy.md` | BJ-SB（只 plan） |
| `optimize.builtin` | Plan | `qt.ai.optimize.run_builtin` | 重计算 / 写结果 | `tutorials/Tutorial 06 - 交易策略的优化.md` | BJ-OPT（只 plan） |
| `insight.last_backtest` | Plan | `qt.ai.insight.summarize_backtest` | 只读 | 3 / 4 结果解读 | BJ-INS |
| `live.plan_only` | Plan | `qt.ai.pipeline.live_trade_plan_only` | 只出清单，**永不 auto** | `8-live-trade-risk-and-broker-walkthrough.md` | **不进** Beginner |

---

## 2. 系统出口（5）

均经 `qt.ai.system.fallback`（`open` 另走合法边短 DAG）。只读。

| Job | 模式 | 含义 | Journey |
|-----|------|------|---------|
| `clarify` | Plan | 拆句 / 补槽 | BJ-REFILL-C（intent 仍可为 `data.refill`） |
| `not_supported` | Plan | 1.0 明确不做 | 不进 Journey |
| `unsafe` | Plan | shell / 跳过确认 | 不进 Journey |
| `route_to_ask` | Plan→Ask | 纯概念，装配层转 Ask | BJ-ASK-PT |
| `open` | Plan | 低副作用短 DAG | 不进 Journey；Mode-R 无 Provider 不开 |

`BJ-ASK-WHAT`（`qteasy 是什么`）标 **Ask**；KB 金答案归 **F.5**。

---

## 3. Registry skill（61）

| # | skill | 层 | 副作用摘要 | 由哪个 Job 带出 |
|---|-------|----|------------|-----------------|
| 1 | `qt.ai.env.check_tushare` | L1 guide | 只读 | `env.ready` |
| 2 | `qt.ai.env.overview_tables` | L1 guide | 只读 | 缺表门禁前置；仍注册 |
| 3 | `qt.ai.strategy_meta.list` | L1 | 只读 | `strategy.meta` |
| 4 | `qt.ai.strategy_meta.get` | L1 | 只读 | `strategy.meta` |
| 5 | `qt.ai.data.kline` | L1 | 只读 | `data.summary`；`data.export` |
| 6 | `qt.ai.data.history` | L1 | 只读 | `data.read`（history） |
| 7 | `qt.ai.data.reference` | L1 | 只读 | `data.read`（reference） |
| 8 | `qt.ai.data.static` | L1 | 只读 | `data.read`（static） |
| 9 | `qt.ai.data.statement` | L1 | 只读 | 已注册；闭合菜谱待金路径 |
| 10 | `qt.ai.dtype.find` | L1 | 只读 | 已注册；闭合菜谱待金路径 |
| 11 | `qt.ai.datasource.table_info` | L1 | 只读 | `env.ready` |
| 12 | `qt.ai.datasource.table_overview` | L1 | 只读 | 已注册；默认不扫全库 |
| 13 | `qt.ai.hp.volatility` | L1 | 只读 | `data.summary` |
| 14 | `qt.ai.hp.describe` | L1 | 只读 | `data.summary` |
| 15 | `qt.ai.hp.plot` | L1 | 写图 | `data.export` |
| 16 | `qt.ai.hp.slice` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 17 | `qt.ai.hp.drop` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 18 | `qt.ai.hp.rename` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 19 | `qt.ai.hp.fill` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 20 | `qt.ai.hp.dropna` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 21 | `qt.ai.hp.resample` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 22 | `qt.ai.hp.assign` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 23 | `qt.ai.hp.align` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 24 | `qt.ai.hp.join` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 25 | `qt.ai.hp.returns` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 26 | `qt.ai.hp.shift` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 27 | `qt.ai.hp.diff` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 28 | `qt.ai.hp.pct_change` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 29 | `qt.ai.hp.rank` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 30 | `qt.ai.hp.zscore` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 31 | `qt.ai.hp.rolling` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 32 | `qt.ai.hp.agg` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 33 | `qt.ai.hp.corr` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 34 | `qt.ai.hp.compare` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 35 | `qt.ai.hp.combine_mask` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 36 | `qt.ai.hp.where` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 37 | `qt.ai.hp.expr` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 38 | `qt.ai.hp.indicator` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 39 | `qt.ai.hp.candle_pattern` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 40 | `qt.ai.hp.research_preset` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 41 | `qt.ai.hp.portfolio` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 42 | `qt.ai.hp.cum_return` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 43 | `qt.ai.hp.normalize` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 44 | `qt.ai.hp.alpha_beta` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 45 | `qt.ai.hp.performance` | L1 | 只读 | 已注册；open 合法边待 A5 |
| 46 | `qt.ai.data.read` | L1 | 只读 | 仍注册；菜谱已改按 channel 叶子 |
| 47 | `qt.ai.data.refill_basic_equity_and_index` | L2 | 网络+写库 | `data.refill` |
| 48 | `qt.ai.research.factor_ic_summary` | L1 | 只读 | `research.factor_ic` |
| 49 | `qt.ai.research.universe_filter` | L1 | 只读 | `research.screen` |
| 50 | `qt.ai.research.price_predicate` | L1 | 只读 | `research.screen`（有谓语） |
| 51 | `qt.ai.research.project_universe` | L1 | 只读 | `research.screen` |
| 52 | `qt.ai.research.screen_stocks` | 遗留 L2 | — | **菜谱不再出图**（负例） |
| 53 | `qt.ai.backtest.run_builtin` | L2 | 写 trade_log / 曲线 | `backtest.builtin`；builder 可选末步 |
| 54 | `qt.ai.insight.summarize_backtest` | L3 | 只读 | `insight.last_backtest`；P0 第二步 |
| 55 | `qt.ai.optimize.run_builtin` | L2 | 重计算 | `optimize.builtin` |
| 56 | `qt.ai.strategy.spec_from_nl` | L2 | 只读 | `strategy.builder` |
| 57 | `qt.ai.strategy.codegen_hybrid` | L2 | 写 `.py` | `strategy.builder` |
| 58 | `qt.ai.strategy.sanity_check` | L2 | 只读 | `strategy.builder` |
| 59 | `qt.ai.operator.build_from_spec` | L2 | 内存组装 | `strategy.builder` |
| 60 | `qt.ai.pipeline.live_trade_plan_only` | L2 | 只读清单 | `live.plan_only` |
| 61 | `qt.ai.system.fallback` | 系统 | 只读 | 系统出口 / 缺槽 |

门禁插步（token / 缺表）**不是** Job。

---

## 4. 不要用 / 不进 0.2.0

- **不要用**：`qt.ai.research.screen_stocks`（选股已拆 L1 DAG）。
- **已移出默认注册表**：`qt.ai.data.summary_kline`、`qt.ai.visual.export_kline`（0.4 A0 改由 `data.kline` + `hp.*` 菜谱出图）。
- **0.4 A1 已注册、open 白名单未扩**：`data.history` / `reference` / `static` / `statement`、`dtype.find`、`datasource.table_*`、面板整形 `hp.slice`…`hp.join`。闭合菜谱已接 `data.read` 与 `env.ready`；其余金路径与 open 合法边留到后续步。
- **0.4 A2 已注册、open 白名单未扩**：变换与比较 `hp.returns`、`hp.shift`、`hp.diff`、`hp.pct_change`、`hp.rank`、`hp.zscore`、`hp.rolling`、`hp.agg`、`hp.corr`、`hp.compare`、`hp.combine_mask`、`hp.where`、`hp.expr`。
- **不进 0.2.0**：申万 / PE DSL、无界下载、HP 2.6+ 深 skill、导入任意 `.py`、多模板 codegen 族、场景三、长文本 ingest、全文档 KB 镜像。
- **Beginner 不做**：`live.plan_only`、`unsafe`、`not_supported`、`open`、无谓语枚举筛股（见 QAI5 `E-SCR-EN`）、Mode-D 改写（E.8 语料）。

G.5 对照本表与 Registry，无 P0 空洞即可签字。
