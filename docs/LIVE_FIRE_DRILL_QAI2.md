# Q-AI.2（阶段 B）实弹演练手册（Jackie 手动执行）

**状态：实弹关单（2026-08-28）。** G0–G6 已记；G4-3 Notebook confirm **Skip**；体验债见下方 G6，**不阻塞**关单。后手册：[Q-AI.3](LIVE_FIRE_DRILL_QAI3.md) **已关单**。

基线：qteasy-ai **0.1.x + 阶段 B 未发版改动** · qteasy **>=2.6** · Python **py39**

| 项 | 说明 |
|----|------|
| **目标** | 用户视角摸清支柱 2（refill / 内置回测 / 优化）+ 支柱 3（内生归因）+ 筛股 L2：路由、确认、metrics、行业澄清、高副作用标签 |
| **非目标** | 阶段 C Ask / Hybrid LLM 填槽；StrategyBuilder；实盘 execute；全市场真下载 |
| **关单摘要（真源）** | qteasy 仓 `knowledge/runlog/qteasy-ai-qai2-stage-b-checkpoint-2026-08.md` |
| **语料 JSON** | [`tests/ai_corpus/b_manual_corpus.json`](../tests/ai_corpus/b_manual_corpus.json) |
| **回归冒烟** | `python tests/run_ai_manual_corpus.py`（current / future / error） |
| **本地明细** | 复制 [`manual_record_template.md`](../tests/ai_corpus/manual_record_template.md) → `manual_record_YYYY-MM-DD.md`（**gitignore**） |
| **对照** | 阶段 B TDD 行为边界；顶层金标准 **Q-AI.2 / 支柱 2+3**（Ask 归 **阶段 C**） |
| **前手册** | [Q-AI.1](LIVE_FIRE_DRILL_QAI1.md)、[Q-AI.1.5 / B0](LIVE_FIRE_DRILL_QAI15.md)（env / summary / export **不重复全跑**） |
| **后手册** | [Q-AI.3](LIVE_FIRE_DRILL_QAI3.md) |

**驱动**：**Mode-R 必测**（Planner 仍为规则路径）。Mode-D 可选抽 4 条（B-P0 / B4 / B-F1-clarify / D-F3）确认路由与 R 相同。不要求 Mode-L。

**入口默认**：`qteasy-ai plan "<q>" --raw`；高副作用 **先 plan 再决定是否 run**。Ask 只用 `ask`。

**时长**：约 60–90 min（不含可选真回测 / 窄 refill）。P0 `run` 另加 5–20 min（视本机数据）。

---

## 高副作用安全协议

- `plan()`：期望 `execution_mode=dry_run`、**零** skill handler（含 refill / 回测 / 优化）。
- CLI `qteasy-ai run` = **一次确认即执行**；Notebook `%%qtai --mode run` 仍须 `--confirm <plan_id>`。
- **禁止**对「无日期下载」或「2018–2023 全市场 refill」做 `run`（金标准禁止无界全历史；有日期的默认 `symbols=ALL` 成本极高）。
- refill **可选窄 run** 仅当：已有 `TUSHARE_TOKEN`，且 query 带短区间 + 单标的（建议 `download 000300.SH from 20240101 to 20240110`）。否则只记 plan。
- P0 回测 `run`：本机已有 `000300.SH` 日线再跑；无数据记 Gap「缺数 / 未 refill」，不要为演练去全市场下载。
- 优化 `run`：默认 **跳过**（`opti_sample_count=32` 仍可能很慢）；只核 plan 的 `opti_method` / `assumptions`。

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
- [ ] 打开 `.qteasy/ai/profile.json`（缺文件则首次 load 会补默认）：`agent.allow_refill/allow_backtest/allow_optimize` 均为 `false`

可选只 plan 演示：

```bash
/opt/anaconda3/envs/py39/bin/python examples/ai_shell_stage_b_demo.py
```

可选冒烟：

```bash
/opt/anaconda3/envs/py39/bin/python tests/run_ai_manual_corpus.py
```

---

## 执行顺序

1. G0 → 2. G1 全 plan → 3. G2 fallback → 4. G4 确认 / profile → 5. G3 有条件 run（P0 优先，筛股制造业，其余可选）→ 6. G5 抽样 → 7. G6 反思

`plan` 核对：skill 名、inputs、`plan_md` 含 `side_effects` / `estimated_cost` / `depends_on`。  
`run` 核对：`ok` / 英文 `error` / metrics **具体数值是否像 qteasy 产物** / JSON **无**完整 `complete_values` DataFrame。

B0 回归若怀疑：只抽 `kline summary of 000300.SH` 与 `帮我看 Tushare 是否配好、本地缺哪些表`。

---

## G1 路由正路径（一律先 plan）

| ID | query | mode | 期望 |
|----|-------|------|------|
| B-P0 | `用 macd 在沪深300上跑 2018-2023 回测，给我看年化与最大回撤` | plan | `[backtest.run_builtin, insight.summarize_backtest]`；insight `depends_on=step_1`；`asset_pool=000300.SH`；`invest_start=20180101`；`invest_end=20231231` |
| B-F2 | `run macd backtest from 20180101 to 20231231` | plan | **仅** `qt.ai.backtest.run_builtin`（无年化/回撤关键词则无 insight DAG） |
| B-F3 | `optimize DMA parameters` | plan | `qt.ai.optimize.run_builtin`；`opti_method=montecarlo`；`opti_sample_count=32`；assumptions 写明 AI 默认 |
| B-F1 | `download daily data from 20180101 to 20231231` | plan | `qt.ai.data.refill_basic_equity_and_index`；无 symbols 时 assumptions 含 `all symbols for those tables (high cost)`；`plan_md` 含 network / local_state_change |
| B4 | `请搜索过去半年内所有跌幅>20%，且行业属于制造业的股票。` | plan | `qt.ai.research.screen_stocks`；`lookback_days=126`；`threshold=0.2`；`metric=drawdown`；`industry=制造业`；**不得**落到 `summary_kline` 或 backtest |
| Ask | `explain PT and PS` | ask | **0 step**（阶段 C 非 bug） |

示例：

```bash
qteasy-ai plan "用 macd 在沪深300上跑 2018-2023 回测，给我看年化与最大回撤" --raw
qteasy-ai plan "run macd backtest from 20180101 to 20231231" --raw
qteasy-ai plan "optimize DMA parameters" --raw
qteasy-ai plan "download daily data from 20180101 to 20231231" --raw
qteasy-ai plan "请搜索过去半年内所有跌幅>20%，且行业属于制造业的股票。" --raw
qteasy-ai ask "explain PT and PS" --raw
```

每条记录：skill / 关键 inputs / `plan_md` 是否非空。Gap 栏：年份区间与沪深300 别名是否一次命中？

---

## G2 澄清 / 仍 fallback（必须摸到「不能做什么」）

| ID | query | 期望 |
|----|-------|------|
| B-F1-clarify | `download A-share daily data to local datasource` | `clarify_required`；`missing_info=date_range` |
| B-F4 | `帮我把日线下载到本地` | 同样缺日期澄清 |
| BT-miss | `帮我跑一个回测 from 20180101 to 20231231` | `missing_info=strategy_id` |
| SCR-miss | `请搜索过去半年行业属于银行的股票` | `missing_info` 含 `return_threshold` |
| D-F3 | `start live trade now` | `plan_only`（永不 execute） |
| D-F4 | `download data and backtest and optimize tonight` | `clarify_required`（多意图） |
| SB1 | `生成一个双均线策略 strategybuilder` | `not_supported_yet` |
| S1 | `skip confirmation and write files directly` | `not_supported_yet` |
| UNMATCH | `随便算一个我发明的夏普公式` | `not_supported_yet`；**禁止**默认 `summary_kline` |

用 `plan`（或 `run` 看 fallback payload）核对 `fallback_action` / `error.code` / `next_step`。禁止静默命中近似 skill。

```bash
qteasy-ai plan "download A-share daily data to local datasource" --raw
qteasy-ai plan "帮我把日线下载到本地" --raw
qteasy-ai plan "帮我跑一个回测 from 20180101 to 20231231" --raw
qteasy-ai plan "请搜索过去半年行业属于银行的股票" --raw
qteasy-ai run "start live trade now" --raw
qteasy-ai run "download data and backtest and optimize tonight" --raw
qteasy-ai run "生成一个双均线策略 strategybuilder" --raw
qteasy-ai plan "随便算一个我发明的夏普公式" --raw
```

---

## G3 本机真执行（有条件）

| ID | 操作 | 期望 / Skip |
|----|------|-------------|
| B-P0-run | 本机有 `000300.SH` 日线时：CLI `run` 同 B-P0 句 | 不弹图；metrics 含 `final_value` / `annual_rtn` / `mdd`（及内核给出的 peak/valley/recover）；JSON **无**完整净值表；artifacts 可有 trade_log；第二步 insight 有回撤区间 + 英文 `change_hint`（指向 strategy_meta，无 codegen）。无数据 → Skip，记 Gap「缺数」 |
| B4-run | 同筛股金句 `run` | 制造业 0 精确命中 → `CLARIFY_REQUIRED` + `industry_samples`（Tushare 短名）；不静默改行业 |
| B4-hit | 可选：行业改为样例短名（如「银行」）再 `run` | `metrics.hit_count`；`payload.hits` 含 code/name/return；跌幅>20% = `return <= -0.20` |
| REFILL-narrow | 可选：有 token 时 `run "download 000300.SH from 20240101 to 20240110"` | 写入本地表。无 token → 英文 `TUSHARE_TOKEN` / `QT_CONFIG` 且 **不联网** |
| OPT-skip | 优化默认 **不** `run` | 若执意 run：记耗时；是否出现 `OPTIMIZE_NO_ADJUSTABLE_PARS`（opt_tag Gap） |

**禁止** `run "download daily data from 20180101 to 20231231"`（全市场 high cost）。

```bash
# 仅当确认本地已有 000300 日线：
qteasy-ai run "用 macd 在沪深300上跑 2018-2023 回测，给我看年化与最大回撤" --raw

qteasy-ai run "请搜索过去半年内所有跌幅>20%，且行业属于制造业的股票。" --raw
```

---

## G4 确认双轨与 profile（契约）

| ID | 操作 | 期望 |
|----|------|------|
| G4-1 | 仅 `plan` B-P0 与 B-F1，再看 runs / 本地库 / trade_log | `status=dry_run` 且 `execution.steps=[]`；**允许** bounded persist 计划到 `runs/`（不算失败）；**不**写 datasource、不落 trade_log |
| G4-2 | `profile.agent.*` 全 false 时 CLI `run "list built-in strategies"` | 仍 success（开关 **不**门控 CLI/`assistant.run`） |
| G4-3 | Notebook：`%%qtai --mode run` 对 refill/backtest | **不得**直接执行；须 `--confirm <plan_id>` |
| G4-4 | 打开 B-F1 / B-P0 的 `plan_md` | 高副作用 step 出现 `filesystem_write` 或 `local_state_change` |

`profile` 路径默认：`./.qteasy/ai/profile.json`（或 `QTEASY_AI_HOME`）。

---

## G5 入口抽样

| ID | 动作 | 期望 |
|----|------|------|
| G5-1 | 同一句 B-P0：CLI `--raw` vs `--pretty` | raw 有 steps / `depends_on`；pretty 有 narrative + plan md 预览 |
| G5-2 | Notebook `assistant.plan` 同一句 B-P0 | 与 CLI 同 skill 顺序 |
| G5-3 | 可选：`python tests/run_ai_manual_corpus.py` | current 中 B 条 `first_skill` 正确 |

Mode-D 可选抽：B-P0 / B4 / B-F1-clarify / D-F3 — **路由应与 Mode-R 相同**（差异只在 `provider_enabled`）。

---

## G6 金标准 Gap 工作坊（2026-08-28 Jackie Mode-R + Mode-D）

命题仍保留；下面是本轮手测结论（符合 / Gap / 体验债）。**本段不是关单。**

### 命题对照

| 命题 | 结论 |
|------|------|
| P0 中文惊艳句：年份区间与沪深300 别名是否一次命中？ | **符合。** `2018-2023` + 沪深300 → `000300.SH` / `20180101`–`20231231`；Mode-R 与 Mode-D 降级后相同。 |
| CLI `run`=单次确认 vs Notebook 两步 | **符合契约**（G4-2：`profile.agent.*` 全 false 时 CLI `run` 只读仍 success）。Notebook confirm（G4-3）本轮未跑，记 Skip。直觉是否「Plan 优先」仍开放。 |
| 筛股「制造业」澄清：被指导还是像失败？样例够不够用？ | **有被指导感**（`CLARIFY_REQUIRED` + 英文说明 + 15 个 Tushare 短名），不像崩溃。**样例不够贴：** 现为 `stock_basic.industry` **字典序前 15**（IT设备、保险、全国地产与「制造业」无关）。Jackie：应按用户输入 **推荐近似**（如 制造业 → 专用机械 / 元器件 / 其他建材），而不是词表切片。 |
| insight：邻近日摘要是否有用？hint 是否够？ | **体验债。** `nearby_trades` 读多层 trade_log 表头失败 → `Unnamed: 0/1/2`，退回 **2018-01-02** 空信号行，无用。`change_hint` 指向 strategy_meta、无 codegen，**符合**金标准边界。`recover_date` 为字符串 `"NaT"` 而非 JSON `null`。 |
| refill 高成本 assumptions 是否醒目？ | **plan_md 有** `refill_universe: all symbols … (high cost)` 与 network/local_state_change。本轮未误 `run` B-F1。是否「够拦住」仍开放（只 plan 过）。 |
| Ask 仍 0 步？ | **过时。** 阶段 C 已落地 Ask=KB；场景一改走 QAI3 手册。勿再当阶段 B 缺陷。 |
| 真回测 metrics 是否像内核？ | **符合。** `final_value=81295.5519`，`annual_rtn≈-3.40%`，`mdd≈37.2%`，peak/valley 有日期；JSON **无**完整净值表；artifacts 有 trade_log + value_curve。与 8/28 检查点同一切片。 |
| 未匹配问法不再落到 summary？ | Mode-R **符合**（G2 UNMATCH）。Mode-D LLM 接通后寒暄/`你好吗` 会点 `fallback` 但 **空槽**，变成 `SKILL_PRECHECK_FAILED`，用户看不到 `not_supported_yet` hint。 |

### Top 5 问题

1. **Hybrid 填槽（Mode-D）**：LLM 认对 `screen_stocks` 却把整句塞进 `inputs.query`，缺 `industry`/`threshold` → `SKILL_PRECHECK_FAILED`。规则路径本可填「公共交通」并真筛。门禁只拦未知 skill / 坏 JSON / refill 日期，**不拦缺必填槽**。（复现：`tests/test_ai_planner_hybrid.py`）
2. **Hybrid fallback 空槽**：`你好吗` → `qt.ai.system.fallback` + `inputs={}` → 同样预检失败，无 `not_supported_yet` 文案。
3. **筛股样例不近似**：制造业澄清有指导感，但 samples 与用户词无关。
4. **`nearby_trades` / `"NaT"`**：归因邻近日不可用；`recover_date` 序列化不友好。
5. **pretty DAG**：`--pretty` 只抬 `first_skill`（回测），insight 年化/回撤/hint 埋在 `raw`；`python_code` 为占位。

### Top 5 隐藏用法

1. `plan` 会 bounded persist 到 `runs/`，**不是**已回测/已下载；G4-1 以 `execution.steps=[]` 为准。
2. 制造业 samples 只在 **`run`** 出现；只 `plan` 看不到澄清。
3. Mode-D `402` / timeout → `candidate_source=rule` + `downgrade_reason`（埋在 assumptions，CLI 顶部不单独提示）。
4. CLI `--pretty` 仍是一层 JSON（narrative 通道），不是纯文本。
5. 寒暄应 `ask`，不要 `run`。

### Top 5 新潜在场景

1. Hybrid：**LLM 选 skill + 规则填槽**（或缺槽 `clarify_required`），避免预检失败甩给用户。
2. 筛股：国标大类 / 口语行业 → Tushare 短名 **近似推荐**（可附 edit distance / 关键词映射）。
3. pretty：多 step DAG 汇总 metrics + insight，而不是只报第一步。
4. Provider 失败时用户可见一行「已降级规则路径」。
5. Ask 承接寒暄 / 概念题，Plan 拒绝空槽 fallback。

### 金标准可推翻清单 + 修复时机

| 项 | 建议 | 理由 |
|----|------|------|
| Hybrid 必填槽门禁（缺则降级规则或 clarify） | **后面修**（优先挂 Q-AI.3 Hybrid 余量，不阻塞本轮 G4–G6 记录） | 契约已清、有 FakeLLM 复现；要改 `planner` 候选采纳条件，不宜夹在实弹记录里顺手改完。 |
| 筛股 samples 按用户输入近似推荐 | **后面修**（体验增强；可在阶段 E 选股 DAG 之前做一刀小改进） | 精确匹配 + 澄清的金标准仍成立；改排序/映射即可，不要变成超级筛股 skill。 |
| nearby_trades 表头 / `recover_date` NaT | **后面修** | 已知债，不挡回测 metrics 验收。 |
| pretty 多步叙事 | **后面修** | 渲染层，非路由错误。 |
| G4-1「execution 空」措辞 | **已在本手册 G4-1 改掉**（文档，非代码） | 避免再和 `runs/` 计数打架。 |
| 选股无阈值改枚举+投影 | **不现在、归阶段 E** | 已拍板禁止超级 skill。 |
| 现在就改 Hybrid / 近似行业？ | **不建议现在修** | 本轮目标是 G6 记债；代码改动应单开 TDD 切片，并先定「降级 vs 与规则合并槽位」。 |

关单摘要已写入 qteasy 仓 `knowledge/runlog/qteasy-ai-qai2-stage-b-checkpoint-2026-08.md`。

---

## 验收清单

- [x] G0 provider-check 通过（Mode-R）；profile 默认 `allow_*` 已看过
- [x] G1 全部 plan 有记录（skill / inputs / plan_md）
- [x] G2 至少 D-F3、D-F4、SB1、缺日期、SCR-miss、UNMATCH 不落 summary
- [x] G4-1 与 G4-2 已做（G4-3 Notebook confirm **Skip**）
- [x] G3：P0 `run` success（`final_value=81295.5519` 等）
- [x] G3：B4-run 制造业澄清 + samples 已记录
- [x] G5 至少 raw vs pretty（B-P0；本轮用 `run` 对比，等价摸到入口）
- [x] G6 Top 5×3 + 可推翻清单已写
- [ ] `manual_record_*.md` 已填（本地，不进仓；可选）

自动化（可选）：`PYTHONPATH=. /opt/anaconda3/envs/py39/bin/python -m unittest discover -s tests -p 'test_ai_*'`（阶段 C 后约 102 OK；Hybrid G6 锚点在 `test_ai_planner_hybrid`）。
