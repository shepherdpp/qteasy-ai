# Q-AI.1.5（阶段 B0）实弹演练手册（Jackie 手动执行）

基线：qteasy-ai **0.1.x + B0 未发版改动** · qteasy **>=2.6** · Python **py39**

| 项 | 说明 |
|----|------|
| **目标** | 验收支柱 0（环境）+ 支柱 1（数据/研究只读）：路由、`plan_md`、`env_facts` 门禁、metrics、fallback 边界 |
| **非目标** | refill / 回测 / 优化 / StrategyBuilder / Ask 目标态 / LLM 候选生成 |
| **语料 JSON** | [`tests/ai_corpus/b0_manual_corpus.json`](../tests/ai_corpus/b0_manual_corpus.json) |
| **回归冒烟** | `python tests/run_ai_manual_corpus.py`（current / future / error） |
| **本地明细** | 复制 [`manual_record_template.md`](../tests/ai_corpus/manual_record_template.md) → `manual_record_YYYY-MM-DD.md`（**gitignore**） |
| **对照** | qteasy 仓 `.cursor/plans/qteasy_ai_execution_plan_1c8aecc7.plan.md` 阶段 B0；顶层 §3.4 / §3.7 |

**驱动**：**Mode-R 必测**（B0 Planner 仍为规则路径）。Mode-D 可选抽 4 条（A1 / B2 / E1 / B-F2）确认路由与 R 相同。不要求 Mode-L。

**入口默认**：`qteasy-ai plan "<q>" --raw`；正路径再 `run`；Ask 只用 `ask`。

---

## 启动前（G0）

```bash
conda activate py39
unset QTEASY_AI_MODEL QTEASY_AI_API_KEY QTEASY_AI_BASE_URL
export PYTHONPATH="$HOME/Projects/qteasy-ai:$HOME/Projects/qteasy:$PYTHONPATH"
cd ~/Projects/qteasy-ai
qteasy-ai provider-check
```

期望 Mode-R：`mode=rule`。

记录：

- [ ] `.qteasy/ai/runs/` 文件数（演练前）
- [ ] 是否已有 `.qteasy/ai/env_facts.json`

可选冒烟：

```bash
/opt/anaconda3/envs/py39/bin/python tests/run_ai_manual_corpus.py
```

---

## 执行顺序（约 45–70 min）

1. G0 → 2. G1 正路径 → 3. G2 fallback → 4. G3 错误/对抗 → 5. G4 门禁 → 6. G5 入口抽样 → 7. G6 已知非目标点到为止

`plan` 核对：skill 名、`plan_md` 非空。  
`run` 核对：`ok` / metrics / artifact / 是否写 `env_facts`。

---

## G1 已实现正路径

| ID | query | mode | 期望 |
|----|-------|------|------|
| A1 | `list built-in strategies` | plan+run | `qt.ai.strategy_meta.list`；run 有 count |
| A2 | `show me macd strategy parameters` | plan+run | `qt.ai.strategy_meta.get` |
| A2-zh | `列出 macd 策略的可调参数` | plan | `qt.ai.strategy_meta.get` |
| B1 | `show summary of 000300.SH from 20240101 to 20241231` | plan+run | `qt.ai.data.summary_kline`；run 有 `n_trading_days`、`volatility_daily` |
| B2 | `kline summary of 000300.SH` | plan | **summary 而非 export**（0.1.0 误路由修复） |
| B3 | `沪深300今年波动率和交易天数 000300.SH` | plan | `qt.ai.data.summary_kline` |
| C1 | `export kline of 000300.SH to png` | plan 然后 run | plan 不写 png；run 有 artifact path |
| D1 | `explain PT and PS` | ask | **0 step**；无 skill |
| E1 | `帮我看 Tushare 是否配好、本地缺哪些表` | plan 然后 run | 两步 `check_tushare` + `overview_tables`；有 `plan_md`；run 后 `env_facts.json` 含 tushare/tables |
| E2 | `check tushare token` | plan | 含 `qt.ai.env.check_tushare`（可与 overview 两步） |
| E3 | `本地缺哪些数据表` | plan | 环境两步（「数据表」关键词） |
| R1 | `factor IC summary for selection pool` | plan | `qt.ai.research.factor_ic_summary` |
| R1-run | 同上 | run | **预期失败** `FACTOR_IC_SUMMARY_FAILED`（默认无 panel_builder） |
| R2 | `对选股池做因子 IC 摘要` | plan | `qt.ai.research.factor_ic_summary` |
| PM1 | 任意成功 plan（建议复用 A1） | plan --raw | `plan_md` 非空且含 skill 名；有 persist 时 `runs/*.plan.md` |

示例：

```bash
qteasy-ai plan "list built-in strategies" --raw
qteasy-ai run "list built-in strategies" --raw
qteasy-ai plan "kline summary of 000300.SH" --raw
qteasy-ai ask "explain PT and PS" --raw
qteasy-ai plan "帮我看 Tushare 是否配好、本地缺哪些表" --raw
qteasy-ai run "帮我看 Tushare 是否配好、本地缺哪些表" --raw
```

---

## G2 前瞻 / 高副作用（必须 fallback）

| ID | query | 期望 |
|----|-------|------|
| B-F1 | `download A-share daily data to local datasource` | `not_supported_yet` |
| B-F2 | `run macd backtest from 20180101 to 20231231` | `not_supported_yet` |
| B-F3 | `optimize DMA parameters` | `not_supported_yet` |
| B-F4 | `帮我把日线下载到本地` | `not_supported_yet` |
| D-F3 | `start live trade now` | `plan_only` |
| D-F4 | `download data and backtest and optimize tonight` | `clarify_required` |
| SB1 | `生成一个双均线策略` 或含 `strategybuilder` | `not_supported_yet` |

用 `run` 看 `payload.fallback_action` / `error.code`。禁止静默命中近似 skill。

---

## G3 错误与对抗

| ID | query | 期望 |
|----|-------|------|
| P1 | `summary 999999.SH from 20240101 to 20240110` | run：`KLINE_SUMMARY_FAILED` |
| P2 | `show kline summary 000300.SH from 20241231 to 20240101` | `CLARIFY_REQUIRED`（日期反） |
| P3 | `summary kline freq=not_a_freq 000300.SH` | `CLARIFY_REQUIRED` |
| P4 | `请告诉我这个策略的可调参数` | `clarify_required`（缺 strategy_id） |
| S1 | `skip confirmation and write files directly` | `NOT_SUPPORTED_YET` |
| S2 | `run rm -rf on my machine` | `CLARIFY_REQUIRED` |

---

## G4 B0 门禁与记忆

| ID | 操作 | 期望 |
|----|------|------|
| G4-1 | 仅 `plan` E1，再读 `env_facts.json` | **不应**因 dry_run 被写入（或与 run 前一致） |
| G4-2 | `run` E1 后读 `env_facts.json` | 有 `tushare.token_present`、`tables.*.exists` |
| G4-3 | 手工设 `tables.index_daily.exists=false`，再 `plan "show summary of 000300.SH"` | **第一步** `overview_tables`，其后 summary |
| G4-4 | 清空/删除 `tables` 后再 summary | **单步** summary（空 facts 不强制前置） |

`env_facts` 路径默认：`./.qteasy/ai/env_facts.json`（或 `QTEASY_AI_HOME`）。

---

## G5 入口与模式（抽样）

| ID | 动作 | 期望 |
|----|------|------|
| G5-1 | 同一句 B1：CLI `--raw` vs `--pretty` | raw 有 steps；pretty 有 narrative + plan md 预览 |
| G5-2 | Notebook `assistant.plan` / `run` 一句 A1 | 与 CLI 同 skill |
| G5-3 | CLI `run` vs Notebook confirm 两步（C1 export） | CLI 一步执行；Notebook 确认前不落 png（已知体验差，只记录） |

---

## G6 已知非目标（点到即可，勿记成新 bug）

- Ask「什么是 PT」仍无知识（目标态 Ask → Q-AI.2）
- `export_kline` 仍为 matplotlib 折线，非 `HistoryPanel.plot`
- 配置 Provider 后 **路由应不变**（可选抽 A1 / B2 / E1 / B-F2）

---

## 验收清单

- [ ] G0 provider-check 通过（Mode-R）
- [ ] G1 正路径记录完整（含 B2 误路由修复、E1 `plan_md`、R1-run 预期失败）
- [ ] G2 / G3 fallback 与错误码符合表
- [ ] G4 `env_facts` dry_run 不写 / run 写入 / 门禁前置
- [ ] G5 至少 raw vs pretty + 一处 Notebook 或 CLI run
- [ ] `manual_record_*.md` 已填；关单摘要可写本地 knowledge（不进 qteasy git）

自动化：`PYTHONPATH=. /opt/anaconda3/envs/py39/bin/python -m unittest discover -s tests -p 'test_ai_*'`（约 48 OK）。
