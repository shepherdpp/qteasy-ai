# Q-AI.1 实弹演练手册（Jackie 手动执行）

基线：qteasy-ai **0.1.0** · qteasy **>=2.6** · Python **py39**

| 项 | 说明 |
|----|------|
| **目标** | 从用户视角理解骨架：怎么问、怎么出 plan、怎么执行、结果形态、**不能做什么** |
| **非目标** | 不验收 Q-AI.1.5+；不追求 LLM 回答质量（0.1.0 Planner 为**规则路由**） |
| **关单摘要（真源）** | qteasy 仓 [`knowledge/runlog/qteasy-ai-live-fire-drill-qai1-2026-08.md`](https://github.com/shepherdpp/qteasy/blob/main/knowledge/runlog/qteasy-ai-live-fire-drill-qai1-2026-08.md) |
| **本地明细** | 复制 [`manual_record_template.md`](../tests/ai_corpus/manual_record_template.md) 为 `manual_record_YYYY-MM-DD.md`（**gitignore，不进仓**） |
| **Round-D/L 脚本** | `python tests/run_ai_drill_provider_compare.py`（需已 export `QTEASY_AI_*`） |
| **对照** | 顶层金标准见 qteasy 仓 `.cursor/plans/qteasy_ai_top_level_design.plan.md` |

## 启动前

```bash
conda activate py39
unset QTEASY_AI_MODEL QTEASY_AI_API_KEY QTEASY_AI_BASE_URL   # Round-R
export PYTHONPATH="$HOME/Projects/qteasy-ai:$HOME/Projects/qteasy:$PYTHONPATH"
cd ~/Projects/qteasy-ai
qteasy-ai provider-check
```

Round-D：设置 `QTEASY_AI_MODEL` / `QTEASY_AI_API_KEY` / `QTEASY_AI_BASE_URL=https://api.deepseek.com/v1`  
Round-L：本机网关如 `QTEASY_AI_BASE_URL=http://127.0.0.1:11434/v1` + 对应 model  

每轮换驱动前：**新 shell 或重启 Notebook kernel**。

**重要预期**：Round-D/L 与 Round-R 的 **skill 匹配应相同**；差异主要在 `provider_enabled`。若不同，记 bug/环境串扰。

---

## 阶段 A：架构体感（~15 min）

1. 读顶层金标准 §三架构图；对照 `qteasy_ai/app.py` 的 `ask` / `plan` / `run`
2. 记下演练前 `.qteasy/ai/runs/` 文件数
3. `qteasy-ai provider-check` 与 `QteasyAssistant().debug_config()`

**先写预期**：Ask 能否回答「什么是 PT」？（阶段 C 再验证）

## 阶段 B：三入口同一句话（~25 min）

**推荐 query（命中 summary）**：`show summary of 000300.SH from 20240101 to 20241231`  

> **已知坑（0.1.0）**：若写成 `show **kline** summary ...`，规则 Planner 会因关键词 `kline` 优先路由到 `qt.ai.visual.export_kline`（写文件），而不是 `data.summary_kline`。演练时可故意跑错句对比。

| ID | 入口 | 命令 |
|----|------|------|
| B1 | CLI raw | `qteasy-ai plan "<query>" --raw` |
| B2 | CLI pretty | `qteasy-ai plan "<query>" --pretty` |
| B3 | Notebook API | `assistant.plan(query, response_style="raw")` |
| B4 | Notebook magic | `%%qtai --mode plan` + 同句 |

反馈：更喜欢哪个入口？raw vs pretty？能否看到副作用级别 / 是否调 qteasy？

## 阶段 C：三模式对照（~30 min）

### C1 策略知识

`list built-in strategies` / `show me macd strategy parameters` — 分别 `ask` / `plan` / `run`

### C2 数据摘要

同 B 的 query — 三模式；核对 `metrics` / `data_summary`

### C3 导出副作用

`export kline of 000300.SH to png` — plan 不应落盘；run 应有 artifact  
Notebook：`%%qtai --mode run` → `%%qtai --confirm <plan_id>`

## 阶段 D：正路径全覆盖（~20 min）

```bash
/opt/anaconda3/envs/py39/bin/python tests/run_ai_manual_corpus.py
```

或手动 A1/A2/B1/C1/D1（见记录文件表格）。

## 阶段 E：边界（~25 min）

见 `tests/ai_corpus/error_corpus.json`、`future_capabilities.json`；记录 `fallback_action` / `error.code`。

## 阶段 F：记忆与追溯（~20 min）

runs 落盘、`keep`/`pin`、手动写 `env_facts`（确认 Planner 是否消费）、`persist=none` vs `bounded`。

## 阶段 G：三轮驱动对比（~30 min）

精简子集在 Round-R / D / L 各跑一遍：list strategies、kline summary、explain PT、macd backtest（边界）。

## 阶段 H：金标准反思（~20 min）

填记录文件「金标准可推翻清单」与 Top 5 × 3。

---

## 验收清单

- [ ] 15 条语料有记录
- [ ] 三入口、三模式、四 skill + fallback 已 touch
- [ ] 至少打开 1 个 `runs/*.json`
- [ ] Round-R/D/L 对比表已填
- [ ] Top 5 × 3 已写
- [ ] 金标准可修订清单已写（可写「无修订」）
