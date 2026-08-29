# Q-AI.4（阶段 D）实弹演练手册（Jackie 手动执行）

**状态：TDD 已落地，待 Jackie 手测关单。**

基线：qteasy-ai **0.1.x + 阶段 D 未发版改动** · qteasy **>=2.6** · Python **py39**

| 项 | 说明 |
|----|------|
| **目标** | StrategyBuilder 一条龙：NL→Spec→模板 codegen→sanity→Operator→复用 `run_builtin`；实盘只出 plan |
| **非目标** | 阶段 E 官方 Skill 目录；自由 LLM `realize()`；自动实盘；超级筛股 |
| **语料 JSON** | [`tests/ai_corpus/d_manual_corpus.json`](../tests/ai_corpus/d_manual_corpus.json) |
| **回归冒烟** | `python tests/run_ai_manual_corpus.py`；本手册 NLP 见 `d_manual_corpus.json` |
| **对照** | 阶段 D TDD；顶层 **Q-AI.4**；OKF `knowledge/domain/qteasy-ai-strategybuilder.md` |
| **前手册** | [Q-AI.3](LIVE_FIRE_DRILL_QAI3.md) **已关单** |

**驱动**：**Mode-R 必测**。Mode-D 抽 1 条金句确认 Hybrid catalog 含 skill summary，且不把回测点成 refill。

**入口默认**：`qteasy-ai plan "<q>" --raw`。Ask 用 `qteasy-ai ask`。**禁止**对 live 做 `run`。codegen/回测 `run` 仅在审阅 plan 且本机有 000300 数据后由 Jackie 决定。

---

## 安全协议

- Plan：`execution_mode=dry_run`，codegen **确认前不写** `.qteasy/ai/strategies/`。
- 生成源码只允许 `.qteasy/ai/strategies/`，禁止 qteasy 包 / 仓内 `examples/`。
- 实盘 skill `qt.ai.pipeline.live_trade_plan_only`：只出清单，`execution_forbidden`。
- Ask「帮我写策略」必须提示改用 Plan，零写盘。
- **禁止**无日期全市场 refill `run`。

---

## 启动前（G0）

```bash
conda activate py39
unset QTEASY_AI_MODEL QTEASY_AI_API_KEY QTEASY_AI_BASE_URL
export PYTHONPATH="$HOME/Projects/qteasy-ai:$HOME/Projects/qteasy:$PYTHONPATH"
cd ~/Projects/qteasy-ai
qteasy-ai provider-check
```

记录：

- [ ] `.qteasy/ai/runs/` 文件数
- [ ] `.qteasy/ai/strategies/` 是否存在（缺则首次 codegen 会建）

可选：

```bash
/opt/anaconda3/envs/py39/bin/python examples/ai_shell_stage_d_strategybuilder_demo.py
```

---

## G1 金句 Plan（必测）

| ID | Query | 期望 |
|----|--------|------|
| D-A1 | 20/60 金叉 + 2015–2020 沪深300 回测 | skills：`spec_from_nl` → `codegen_hybrid` → `sanity_check` → `build_from_spec` → `run_builtin` |
| D-A2 | `生成一个双均线策略 strategybuilder` | `clarify_required`（缺 fast/slow），**不是** `not_supported_yet` |
| D-A3 | `start live trade now` | `qt.ai.pipeline.live_trade_plan_only` |

```bash
qteasy-ai plan "帮我写一个基于 20/60 日均线金叉死叉的择时策略，并用 2015–2020 年沪深300做回测" --raw
```

核对：`depends_on` 串联；`run_builtin.inputs` 含 `000300.SH`、`20150101`、`20201231`；`freq` 在 inputs 中表示 Operator 频率，不得当作 QT_CONFIG 键去执行。

## G2 Ask 边界

```bash
qteasy-ai ask "帮我写一个双均线策略" --raw
```

期望：`mode=ask`，无 `execution`，英文提示改用 Plan。

## G3 可选 confirm/run

仅当 G1 plan 已审阅，且本机有沪深300 日线。codegen 会写入 `.qteasy/ai/strategies/GeneratedSmaCross.py`。无数据则记 Gap，不要为演练全市场下载。

## G6 体验债（不阻塞编码收口）

- 首批模板仅 RuleIterator 双均线；选股/网格仍 clarify。
- Hybrid 错品类是否因 catalog summary 改善：Mode-D 手测记录。

---

*手册角色：Q-AI.4 手测 · 2026-08-29*
