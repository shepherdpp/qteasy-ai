# qteasy-ai Stage A — Manual test guide (Gold Standard)

Jackie-only smoke checklist for **0.1.x**. Automated regression: `python -m unittest discover -s tests -p 'test_ai_*' -v`.

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
5. Ask: `assistant.ask("explain PT vs PS")` → `dry_run`, **zero** plan steps
6. **B0 env**: `帮我看 Tushare 是否配好、本地缺哪些表` → `check_tushare` + `overview_tables`；payload 含 `plan_md`
7. **B0 research**: `factor IC summary for selection pool` → `qt.ai.research.factor_ic_summary`（执行需注入 panel_builder / 有研究面板）

## 5. Boundaries (must hold)

- High side-effect skills: plan shows `side_effects`; run only after explicit confirm in Notebook (`%%qtai --confirm <plan_id>`).
- Unsupported queries → `qt.ai.system.fallback` with `fallback_action` / `next_step` (not silent wrong skill).
- No merge of `qt_ai_dev` into qteasy `master`.

## 6. Sign-off

**Jackie 验收：2026-08-08（PYTHONPATH 联调，无 pip install）**

- [x] Mode-R：`provider-check` → `mode=rule`；语料 15 条 + `test_ai_*` **34 OK**
- [x] Mode-D / Mode-L provider 契约：`test_ai_cli_notebook_entry` 单元测试覆盖
- [ ] Mode-D / Mode-L **live LLM** 联调（可选）
- [ ] Comparison notes in `manual_record_template.md`（可选）
