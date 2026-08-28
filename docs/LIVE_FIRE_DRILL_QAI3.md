# Q-AI.3（阶段 C）实弹演练手册（Jackie 手动执行）

**状态：实弹关单（2026-08-28）。** Mode-R G0–G5 + Mode-D C-H1～C-H5 已记；Notebook C-E3 **Skip**；体验债见下方 G6，**不阻塞**关单。关单摘要：qteasy 仓 `knowledge/runlog/qteasy-ai-qai3-stage-c-tdd-2026-08.md`。下一编码：Hybrid 必填槽门禁（阶段 C 余量），再 **Q-AI.4**。

基线：qteasy-ai **0.1.x + 阶段 C 未发版改动** · qteasy **>=2.6** · Python **py39**

| 项 | 说明 |
|----|------|
| **目标** | 摸清 Ask 目标态、preview 迁移、`explanation_depth`、Hybrid 门禁与能力边界 |
| **非目标** | Q-AI.2 已关单（体验债见 QAI2 G6，本手册不重跑 B）；StrategyBuilder；实盘 execute；无界 refill；`run` 高副作用 |
| **语料 JSON** | [`tests/ai_corpus/c_manual_corpus.json`](../tests/ai_corpus/c_manual_corpus.json) |
| **回归冒烟** | `python tests/run_ai_manual_corpus.py`（current / future / error）；本手册 NLP 条见 `c_manual_corpus.json` |
| **本地明细** | 复制 [`manual_record_template.md`](../tests/ai_corpus/manual_record_template.md) → `manual_record_YYYY-MM-DD.md`（**gitignore**） |
| **对照** | 阶段 C TDD 行为边界；顶层金标准 **Q-AI.3 / §4.2**；qteasy 仓 OKF `knowledge/domain/qteasy-ai-ask-target-state.md` |
| **前手册** | [Q-AI.2](LIVE_FIRE_DRILL_QAI2.md) **已关单**，不重复全跑；只抽 1 条 `preview` vs 旧记忆「ask 空步」（见 G3） |

**驱动**：**Mode-R 必测**（Ask Offline + Plan 规则路径）。**Mode-D 关单前补跑**（Ask LLM 合成 + Plan Hybrid 候选；路由/门禁须与 R 一致或可解释降级）。不要求 Mode-L。

**入口默认**：Ask 用 `qteasy-ai ask "<q>" --raw`；审阅步骤用 `preview` / `plan --preview` / `plan`（均为 dry-run）。**禁止**对 Hybrid 候选出的 refill/回测做 `run`。

**时长**：Mode-R 约 40–60 min；Mode-D 另加 20–30 min。

---

## 安全协议

- **Ask**：不得出现 `execution`、非空 `plan.steps`、skill handler。演练前后 `.qteasy/ai/runs/` 计数对**纯 `ask`** **不增加**。
- **`preview` / `plan`**：`execution_mode=dry_run`（或 `status=dry_run`），**零** handler。
- **Hybrid**：只 `plan --raw`，**禁止**对 LLM 候选出的 refill / 回测做 `run`。
- 实盘句仍 `plan_only`（抽 1 条即可，不重复 Q-AI.2 全套）。
- **禁止**无日期或全市场 refill 的 `run`（与 Q-AI.2 相同）。

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

- [ ] `.qteasy/ai/runs/` 文件数（演练前）→ 记为 `runs_before`
- [ ] 是否已有 `.qteasy/ai/env_facts.json`

可选 Ask/preview 演示：

```bash
/opt/anaconda3/envs/py39/bin/python examples/ai_shell_stage_c_ask_demo.py
```

可选冒烟（既有回归，非本手册语料）：

```bash
/opt/anaconda3/envs/py39/bin/python tests/run_ai_manual_corpus.py
```

---

## 执行顺序

1. G0 → 2. G1 Ask 正路径 → 3. G2 Ask 不能做什么（**立刻**核对 `runs` 仍 = `runs_before`）→ 4. G3 preview vs plan vs ask → 5. G4 depth → 6. G5 入口 / Mode-D → 7. G6 反思

Ask 核对：`mode=ask`、`sources`、英文 `answer`、**无** `execution`、steps 空或不存在。  
preview/plan 核对：skill 名、`dry_run`、零 handler。

---

## G1 Ask 正路径（Mode-R Offline）

| ID | query | 期望 |
|----|-------|------|
| C-A1 | `explain PT vs PS` | `mode=ask`；`sources` 含 `pt_ps_vs`；英文答案含 Position Target / PT / PS |
| C-A2 | `where does run_freq belong` | `sources` 含 `operator_run_freq` |
| C-A3 | `difference between Ask Plan and Agent` | `sources` 含 `ask_plan_agent` |
| C-A4 | `what happens when trade price is NaN` | `sources` 含 `common_errors` |
| C-A5 | `what is macd strategy` | `sources` 含 `strategy_meta`（内置 API，**非** skill） |

```bash
qteasy-ai ask "explain PT vs PS" --raw
qteasy-ai ask "where does run_freq belong" --raw
qteasy-ai ask "difference between Ask Plan and Agent" --raw
qteasy-ai ask "what happens when trade price is NaN" --raw
qteasy-ai ask "what is macd strategy" --raw
```

每条记录：`ok` / `sources` / 答案是否像策展 KB（不是瞎编）。Gap：哪条命中偏弱？

---

## G2 Ask 不能做什么

| ID | query | 期望 |
|----|-------|------|
| C-F1 | `list built-in strategies` | 提示改用 Plan / preview；**无** steps；**不**调用 `strategy_meta.list` handler |
| C-F2 | `quantum foam meaning of life xyzzy-no-match` | `error.code=NOT_FOUND`；Mode-R 无 Provider → **不**调用 LLM |
| C-F3 | `download daily data from 20180101 to 20231231`（用 **ask**） | 仍提示 Plan；**不得**出 refill step |
| C-F4 | 纯 ask 后核对 runs | `ls .qteasy/ai/runs \| wc -l` **等于** `runs_before` |

```bash
qteasy-ai ask "list built-in strategies" --raw
qteasy-ai ask "quantum foam meaning of life xyzzy-no-match" --raw
qteasy-ai ask "download daily data from 20180101 to 20231231" --raw
ls -1 .qteasy/ai/runs 2>/dev/null | wc -l
```

禁止 Ask 静默变成空步 ToolPlan（那是阶段 A 旧行为）。

---

## G3 preview vs plan vs ask

对照旧记忆：**阶段 A 的 `ask` 空步** 已迁走。同一句 `list built-in strategies`：

| ID | 入口 | 期望 |
|----|------|------|
| C-P1 | `qteasy-ai preview "list built-in strategies" --raw` | `qt.ai.strategy_meta.list` + `dry_run` |
| C-P2 | `qteasy-ai plan "list built-in strategies" --raw` | 与 preview **相同** skill + dry_run（`plan --preview` 亦可） |
| C-P3 | `qteasy-ai ask "list built-in strategies" --raw` | 走 G2：建议 Plan，**不**出 list skill |

G3 的 preview/plan **可以**增加 `runs/` 计数（默认 bounded persist）；不要与 G2 的纯 ask 计数混为一谈。

---

## G4 explanation_depth

同一句 `explain PT vs PS`：

| ID | 命令 | 期望 |
|----|------|------|
| C-D1 | `ask ... --raw --depth brief` | **无** `python_code`（空字符串） |
| C-D2 | `ask ... --raw --depth standard` | 三通道：`narrative` + `python_code` + `result_preview` |
| C-D3 | `ask ... --raw --depth deep` | `narrative` 含 `Risk / assumptions` |

```bash
qteasy-ai ask "explain PT vs PS" --raw --depth brief
qteasy-ai ask "explain PT vs PS" --raw --depth standard
qteasy-ai ask "explain PT vs PS" --raw --depth deep
```

---

## G5 入口 + Mode-D Hybrid

| ID | 动作 | 期望 |
|----|------|------|
| C-E1 | 同一句 C-A1：CLI `--raw` vs `--pretty` | raw 有 `sources` / `answer`；pretty 有可读 narrative |
| C-E2 | 同一句 C-P1：CLI `--raw` vs `--pretty` | raw 有 steps；pretty 有 plan 预览 |
| C-E3 | Notebook：`assistant.ask("explain PT vs PS")` 与 `assistant.preview("list built-in strategies")` 各一条 | 与 CLI 同 mode / 同 skill |

**Mode-D**（关单前建议补跑；新 shell，设置 `QTEASY_AI_MODEL` / `QTEASY_AI_API_KEY` / `QTEASY_AI_BASE_URL`，`provider-check` → 非 `rule`）：

| ID | query | 期望 |
|----|-------|------|
| C-H1 | `plan` 同一句 Q-AI.2 P0：`用 macd 在沪深300上跑 2018-2023 回测，给我看年化与最大回撤` | `planner_trace.candidate_source` 为 `llm`，**或**降级 `rule` + 可解释 `downgrade_reason`；**禁止 `run`** |
| C-H2 | `plan "download A-share daily data to local datasource"` | 仍 `clarify_required` / `missing_info=date_range`（门禁不被 LLM 绕过） |
| C-H3 | `plan "随便算一个我发明的夏普公式"` | **不得**静默 `summary_kline` |
| C-H4 | `ask "explain PT vs PS" --raw`（对照 G1 Offline） | 仍 `mode=ask`、零 skill；答案可与 Offline 不同，记 Gap |
| C-H5 | 可选：`ask` 再抽 C-A2 / C-F1 / C-F2 | 路由与 R 一致或可解释；**不得**因 LLM 发明出 list/refill step |

```bash
# 新 shell；确认 provider-check 非 rule 后再跑
qteasy-ai provider-check
qteasy-ai ask "explain PT vs PS" --raw
qteasy-ai plan "用 macd 在沪深300上跑 2018-2023 回测，给我看年化与最大回撤" --raw
qteasy-ai plan "download A-share daily data to local datasource" --raw
qteasy-ai plan "随便算一个我发明的夏普公式" --raw
```

**禁止**对 Hybrid 候选出的 refill / 回测做 `run`。402 / timeout 降级规则路径算可解释，不是失败。

---

## G6 Gap 工作坊（2026-08-28 Mode-R + Mode-D；**实弹关单**）

Q-AI.2 实弹 **已关单**。本手册 **Mode-R G0–G5** 与 **Mode-D C-H1～C-H5** 已手测（Notebook C-E3 **Skip**）。未 `run` 高副作用。**Jackie 2026-08-28 关单。**

### 命题对照

| 命题 | Mode-R | Mode-D |
|------|--------|--------|
| Ask 解释是否够场景一？ | **基本够用。** C-A1 只中 `pt_ps_vs`；C-A3 只中 `ask_plan_agent`。C-A2 `run_freq` 主中 `operator_run_freq`（score 8）但 **bleed** `ask_plan_agent` + `common_errors`（score 2）。C-A4 中 `common_errors` 但给出 **整篇三错误**，不是 NaN 专条。C-A5 `strategy_meta` 走内核 API，**中文 docstring 包在英文外壳**。 | **路由与 R 相同**（含 C-A2 bleed）。**合成更好：** C-A1 更短仍准（顶层略弱 VS）；C-A2 用户答案只讲 Operator/`qt.run`，未把 bleed 写进 `answer`；C-A4 **只抽 NaN 条**；C-A5 **英文答案**（`raw.hits` 仍中文 docstring）。残差：C-A4 `python_code` 仍是 `get_history_data` 日期窗示例，与 NaN 问句错位。 |
| 「list 策略」劝去 Plan 是否反直觉？ | **符合目标态。** C-F1 `hits=[]`、无 list skill；G3 用 `preview`/`plan` 才出 `qt.ai.strategy_meta.list`。 | Ask G1 五条均无 list/refill step。C-F1/C-F2 本轮 Mode-D **未再抽**（可选）。 |
| Offline vs Mode-D 答案？ | 模板全文。 | **C-H4 通过。** 同 `sources`；LLM 压缩/切片，不改 mode。不要求字面相同。 |
| Hybrid 填槽是否比规则更好？ | 本轮 Mode-R 不测 Hybrid。Q-AI.2 Mode-D：**更差（接通后）** — 乱填 `query` 空槽，runtime `SKILL_PRECHECK_FAILED`。402/timeout 降级规则则与 R 一致。 | **C-H1～C-H3 通过（可解释降级）。** 三条均为 `provider_enabled=true`、`candidate_source=rule`、`downgrade_reason=llm_chat_failed: The read operation timed out`。C-H1 规则计划正确（`macd` / `000300.SH` / `20180101`–`20231231` + insight）。C-H2 `clarify_required` / `missing_info=date_range`。C-H3 `not_supported_yet`，**未**落到 `summary_kline`。本轮 **未**再摸到 `candidate_source=llm` 的 plan（Ask 合成已通；plan 候选 chat 超时）。空槽债仍以 QAI2 + 表征测试为准。 |
| `preview` 替代旧 ask 空步？ | **是。** C-P1 ≡ C-P2（`strategy_meta.list` + `dry_run` + `execution.steps=[]`）；ask 同一句不出 list。`runs/` 185→186/187 是 plan persist，勿与 G2 的 `wc -l`（含 `.plan.md`）混算。 | — |

### Top 5 问题（Mode-R + 继承 QAI2）

1. **Ask 检索噪声**：`run_freq` bleed 到 `ask_plan_agent` / `common_errors`（R 与 D 的 `sources` 相同）。Mode-D `answer` 能压住 bleed；Mode-R 会把多篇拼进通道。C-A4 专条切片靠 LLM；`python_code` 仍绑整篇 `common_errors`（日期窗示例）。
2. **Ask 中英混排**：Mode-R 顶层中英混；Mode-D 顶层已英文化，`raw.hits.narrative` 仍是内核中文。
3. **preview `--pretty` 把 dry-run 写成已执行**：`Listed built-in strategies successfully. Total count: 0.` / `First strategies: []`；`python_code` 为 `qt.built_in_list()` 占位。`raw.execution.status` 仍是 `dry_run`。与 QAI2「pretty 只抬 first_skill」同类。
4. **Hybrid 缺必填槽**（QAI2 接通后；本轮 plan chat **超时未接通**）：LLM 认对 skill 却空槽 → `SKILL_PRECHECK_FAILED`。表征测试：`tests/test_ai_planner_hybrid.py`。本轮只验证了 timeout → 规则路径。
5. **筛股样例不近似**（QAI2 G6）：制造业澄清样例是字典序前 15，与用户词无关。不在 Ask 目标态。

### Top 5 隐藏用法

1. CLI `plan` 走 `preview()`，G3 两份 JSON 结构相同是预期。
2. `--pretty` 仍是一层 JSON（三通道 + 嵌套 `raw`），不是纯文本；Ask 默认 depth=`standard`。
3. `raw.hits` 始终带完整 `python_code` / `risk_notes`；`--depth` 只裁顶层通道。
4. 纯 `ask` 不增 `runs/`；`preview`/`plan` 会 bounded persist。`ls \| wc -l` 含 `.plan.md`，与 `cleanup.remaining_count`（json）不可直接比。
5. Ask LLM 可成功，同时 `plan` Hybrid 候选 chat 超时（提示更长）。`downgrade_reason` 在 `assumptions` / `planner_trace`，CLI 顶部不单独提示。超时后规则路径与 Mode-R 同；**不要**为「再试一次 LLM」去 `run` 回测。

### Top 5 新潜在场景

1. Hybrid：LLM 选 skill + 规则填槽（或缺槽 `clarify_required`）。
2. Ask 检索：抑制低分 bleed；`common_errors` 按子题切片（NaN vs 另两错）。
3. Ask 内核 docstring：对外通道英文化或标明「kernel zh」。
4. pretty：dry-run 叙事须写「plan generated / waiting for confirmation」，禁止「Listed … successfully / count=0」。
5. Provider 失败时用户可见一行「已降级规则路径」（QAI2 已记）。

### 金标准可推翻清单 + 修复时机

| 项 | 建议 | 理由 |
|----|------|------|
| Hybrid 必填槽门禁 | **后面修**（优先于新 skill） | 不要把 `SKILL_PRECHECK_FAILED` 当用户文案；本轮关单前只复测 `plan`。 |
| Ask 检索 bleed / `common_errors` 整篇 | **后面修** | Mode-D 合成可掩盖；`python_code` 与问句仍会错位。 |
| macd 中英混排 | **后面修**（Offline 包装层） | Mode-D 顶层已英文化；不必挡关单。 |
| preview pretty 谎称已 list | **后面修** | 渲染层，非路由错误。 |
| 筛股近似行业 | **后面修**（归选股体验 / 阶段 E 前小改进） | 见 QAI2 G6。 |
| 现在就改代码？ | **不建议本轮顺手改** | 关单后 Hybrid 空槽单开 TDD。 |

关单摘要已写入 qteasy 仓 `knowledge/runlog/qteasy-ai-qai3-stage-c-tdd-2026-08.md`。

---

## 验收清单

- [x] G0 `provider-check` 为 Mode-R；已记 `runs_before`
- [x] G1 五条 Ask 均有 `sources` 与英文答案
- [x] G2：list / 无意义句 / ask-download 无 steps；纯 ask 后 `runs` 不变
- [x] G3：preview ≡ plan dry-run list skill；ask 同一句不出 list
- [x] G4：brief / standard / deep 各一条
- [x] G5：Ask 与 preview 各一条 raw vs pretty；Notebook C-E3 **Skip**
- [x] G6 Top 5×3 + 可推翻清单已写（Mode-R + Mode-D）
- [ ] `manual_record_*.md` 已填（本地，不进仓；可选）
- [x] Mode-D：C-H1～C-H5；**未** `run` 高副作用（C-H1～C-H3 为 timeout 降级规则；C-F1/C-F2 **未**再抽）
- [x] **关单**（2026-08-28 Jackie）

自动化（可选）：`PYTHONPATH=. /opt/anaconda3/envs/py39/bin/python -m unittest discover -s tests -p 'test_ai_*'`（阶段 C 后约 102 OK）。
