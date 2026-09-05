# qteasy-ai Stage A / B / C / D / E — Manual test guide (Gold Standard)

Jackie-only smoke checklist. Automated regression: `python -m unittest discover -s tests -p 'test_ai_*' -v`.

**Q-AI.1.5（阶段 B0）手测**：见 [`LIVE_FIRE_DRILL_QAI15.md`](LIVE_FIRE_DRILL_QAI15.md) + 语料 [`tests/ai_corpus/b0_manual_corpus.json`](../tests/ai_corpus/b0_manual_corpus.json)。

**Q-AI.2（阶段 B）实弹**：**已关单（2026-08-28）**。手册 [`LIVE_FIRE_DRILL_QAI2.md`](LIVE_FIRE_DRILL_QAI2.md) + 语料 [`tests/ai_corpus/b_manual_corpus.json`](../tests/ai_corpus/b_manual_corpus.json)。摘要：qteasy 仓 `knowledge/runlog/qteasy-ai-qai2-stage-b-checkpoint-2026-08.md`。

**Q-AI.3（阶段 C）实弹**：**已关单（2026-08-28）**。手册 [`LIVE_FIRE_DRILL_QAI3.md`](LIVE_FIRE_DRILL_QAI3.md) + 语料 [`tests/ai_corpus/c_manual_corpus.json`](../tests/ai_corpus/c_manual_corpus.json)。摘要：qteasy 仓 `knowledge/runlog/qteasy-ai-qai3-stage-c-tdd-2026-08.md`。

**Q-AI.4（阶段 D）实弹**：**已关单（2026-08-31）**。手册 [`LIVE_FIRE_DRILL_QAI4.md`](LIVE_FIRE_DRILL_QAI4.md) + 语料 [`tests/ai_corpus/d_manual_corpus.json`](../tests/ai_corpus/d_manual_corpus.json)。

**Q-AI.5（阶段 E）实弹**：**已关单（2026-09-05，现行 H）**。手册 [`LIVE_FIRE_DRILL_QAI5.md`](LIVE_FIRE_DRILL_QAI5.md) + 语料 [`tests/ai_corpus/e_manual_corpus.json`](../tests/ai_corpus/e_manual_corpus.json)。**E.8 H′ 已编码**：补页 [`LIVE_FIRE_DRILL_QAI5_H_PRIME.md`](LIVE_FIRE_DRILL_QAI5_H_PRIME.md)。下一主线 E.4 起草。

Plan source (qteasy repo): `.cursor/plans/s1.4a人工测试金标准_6d66df64.plan.md`.

## 1. Environment

```bash
conda activate py39   # /opt/anaconda3/envs/py39
# 若 pip 因网络失败，可用 PYTHONPATH（与 Jackie 2026-08-08 验收一致）：
export PYTHONPATH="$HOME/Projects/qteasy-ai:$HOME/Projects/qteasy:$PYTHONPATH"
# 或：pip install -e ~/Projects/qteasy && pip install -e ~/Projects/qteasy-ai --no-build-isolation
```

- Python: **3.9** (project standard)
- Data: minimal local qteasy datasource (e.g. `000300.SH` daily)

## 2. Three modes (must verify config, not full LLM quality)

| Mode | Setup | Expected `debug_config()` |
|------|--------|---------------------------|
| **Mode-R** (rule) | Unset `QTEASY_AI_MODEL` | `provider_enabled=False` |
| **Mode-D** (DeepSeek) | `QTEASY_AI_MODEL`, `QTEASY_AI_API_KEY`, `QTEASY_AI_BASE_URL=https://api.deepseek.com/v1` | `mode=cloud_llm`, `api_key_present=True` |
| **Mode-L** (local Llama) | Local gateway e.g. `QTEASY_AI_BASE_URL=http://127.0.0.1:11434/v1` | `mode=local_llm` |

Switch modes: **restart kernel / new shell**, unset old env, set new env, then:

```bash
qteasy-ai provider-check
```

or in Notebook:

```python
from qteasy_ai.app import QteasyAssistant
QteasyAssistant().debug_config()
```

## 3. Quick corpus sweep

```bash
cd ~/Projects/qteasy-ai
/opt/anaconda3/envs/py39/bin/python tests/run_ai_manual_corpus.py
```

Record results in `tests/ai_corpus/manual_record_template.md`.

## 4. Must-run queries (implemented capabilities)

Run each with `qteasy-ai plan "<query>" --pretty` (Mode-R is enough for routing):

1. `list built-in strategies` → `qt.ai.strategy_meta.list`
2. `show me macd strategy parameters` → `qt.ai.strategy_meta.get`
3. `show summary of 000300.SH from 20240101 to 20241231` → `qt.ai.data.summary_kline`  
   （B0：含 `kline` 的 `kline summary ...` 亦路由到 summary，不再误走 export）
4. `export kline of 000300.SH to png` → `qt.ai.visual.export_kline` (confirm side effect / artifact path on `run`)
5. Ask: `qteasy-ai ask "explain PT vs PS"` → `mode=ask`, sources include `pt_ps_vs`, **no** `execution` / no plan steps. To preview a ToolPlan: `qteasy-ai preview "list built-in strategies"`
6. **B0 env**: `帮我看 Tushare 是否配好、本地缺哪些表` → `check_tushare` + `overview_tables`；payload 含 `plan_md`
7. **B0 research**: `factor IC summary for selection pool` → `qt.ai.research.factor_ic_summary`（执行需注入 panel_builder / 有研究面板）
8. **B refill**: `download daily data from 20180101 to 20231231` → `qt.ai.data.refill_basic_equity_and_index`（`plan` 零执行；无日期问法应 `clarify_required` / `date_range`）
9. **B P0**: `用 macd 在沪深300上跑 2018-2023 回测，给我看年化与最大回撤` → `backtest.run_builtin` 然后 `insight.summarize_backtest`（`depends_on`）
10. **B screen**: `请搜索过去半年内所有跌幅>20%，且行业属于制造业的股票。` → `qt.ai.research.screen_stocks`（不得落到 `summary_kline`；制造业若 0 精确命中则 `CLARIFY_REQUIRED` 并附 `industry_samples`）
11. **B optimize**: `optimize DMA parameters` → `qt.ai.optimize.run_builtin`（默认 `montecarlo` / `opti_sample_count=32`）

## 5. Boundaries (must hold)

- High side-effect skills: plan shows `side_effects`; **CLI `qteasy-ai run` = one human confirmation** and executes. Notebook `%%qtai --mode run` still requires `--confirm <plan_id>`.
- `profile.agent.allow_*` defaults are all `false` and are **not** read by CLI/`assistant.run()` in this stage (reserved for unattended agents later).
- Ask target state: `assistant.ask(...)` → `mode=ask`, KnowledgeBase answer, **no** skill / PlanExecutor / `runs/` persist. Former empty-step plan preview is `preview()` / `plan --preview`.
- Live trade uses `qt.ai.pipeline.live_trade_plan_only` (never execute orders). Skip-confirmation remains `not_supported_yet`.
- StrategyBuilder: Plan DAG for dual-MA templates; Ask does not write strategy files.
- Unsupported queries → `qt.ai.system.fallback` with `fallback_action` / `next_step` (not silent wrong skill; never default to `summary_kline`).
- No merge of `qt_ai_dev` into qteasy `master`.

## 6. Sign-off

**Jackie 验收：2026-08-08（PYTHONPATH 联调，无 pip install）**

- [x] Mode-R：`provider-check` → `mode=rule`；语料 15 条 + `test_ai_*` **34 OK**
- [x] Mode-D / Mode-L provider 契约：`test_ai_cli_notebook_entry` 单元测试覆盖
- [ ] Mode-D / Mode-L **live LLM** 联调（可选）
- [ ] Comparison notes in `manual_record_template.md`（可选）
