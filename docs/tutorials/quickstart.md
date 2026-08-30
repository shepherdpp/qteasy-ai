# Tutorial 09 - qteasy AI shell 快速上手

本教程展示 qteasy-ai 的最小闭环：Ask 问答、plan 生成、确认执行、结构化结果查看。

更完整的模式与安全说明见 [USER_GUIDE.md](../USER_GUIDE.md)。

## 1. 准备环境

先安装 qteasy 内核，再安装本包：

```bash
pip install "qteasy>=2.6.0"
pip install -e /path/to/qteasy-ai
```

本地双仓联调：

```bash
pip install -e /path/to/qteasy
pip install -e /path/to/qteasy-ai
```

可选 Provider 配置（**推荐环境变量**）：

```bash
export QTEASY_AI_MODEL="gpt-4o-mini"
export QTEASY_AI_API_KEY="your_api_key"
export QTEASY_AI_BASE_URL="https://api.openai.com/v1"
```

未设置 `QTEASY_AI_MODEL` 时为**规则模式**（Planner 不调用 LLM），属正常。  
若 qteasy 侧仍保留 `ai_*` 配置键（2.7 前可选兼容），`ConfigCenter` 会在 env 未设置时读取；**qteasy 2.6.0 master 无 `ai_*` 键**，请优先用 `QTEASY_AI_*`。

## 2. CLI 方式

### 2.1 Ask 模式（Q-AI.3 目标态）

Ask 是只读问答：KnowledgeBase + 可选 LLM，**不**生成可执行 steps，**不**调用 skill / PlanExecutor。

无 Provider 时仍可用（Offline 检索 + 英文模板）。有 Provider 时 Ask 的 `answer` 跟随问句语言。执行型请求（列出策略、下载、回测）请改用 Plan / preview。

```bash
qteasy-ai ask "explain PT vs PS"
qteasy-ai ask "explain PT vs PS" --depth deep
```

### 2.1b preview（原 ask 的 plan 预览）

`ask()` 不再返回空步 ToolPlan。若只想看 plan、不执行：

```bash
qteasy-ai preview "list built-in strategies"
qteasy-ai plan "list built-in strategies" --preview
```

### 2.2 Plan 模式

```bash
qteasy-ai plan "show kline summary of 000300.SH from 20240101"
qteasy-ai plan "show kline summary of 000300.SH from 20240101" --pretty
qteasy-ai plan "show kline summary of 000300.SH from 20240101" --raw
```

### 2.3 Run 模式

```bash
qteasy-ai run "export kline 000300.SH to png"
```

**CLI `run` = 人在回路的一次确认**：生成计划后立即执行（含 refill / 回测 / 优化等高副作用 skill）。这与 Notebook 不同：`%%qtai --mode run` 仍只出 plan，必须再执行 `%%qtai --confirm <plan_id>`。

`profile.json` 中的 `agent.allow_refill/allow_backtest/allow_optimize` 默认全为 `false`，本阶段**不**门控 CLI/`assistant.run()`（预留给以后的无人值守 Agent）。

执行后可在返回结果中查看 `run_file` / `plan_md`，并追溯每个 step 的输入输出。

### 2.4 Provider 配置诊断

```bash
qteasy-ai provider-check
```

输出会包含 `mode/model/base_url/timeout/api_key_present/config_sources`，用于快速确认当前是规则模式、云端模型还是本地模型。默认 `timeout` 为 120 秒，可用 `QTEASY_AI_TIMEOUT` 覆盖。

## 2.5 Stage B0（Q-AI.1.5）环境与数据

B0 在规则 Planner 上增加：

- 环境引导 skills：`qt.ai.env.check_tushare`、`qt.ai.env.overview_tables`（`skill_kind=guide`）
- `env_facts` 门禁：已知核心表缺失时，取数/研究计划前置 overview
- K 线摘要含 `n_trading_days` / `volatility_*`；研究只读 `qt.ai.research.factor_ic_summary`
- `plan()` / `run()` 同时返回 **ToolPlan JSON** 与人读 **`plan_md`**（单向，不做 md 反解析）

示例：

```bash
qteasy-ai plan "帮我看 Tushare 是否配好、本地缺哪些表" --raw
qteasy-ai plan "kline summary of 000300.SH" --pretty
```

Python：

```python
from qteasy_ai.app import QteasyAssistant

assistant = QteasyAssistant()
payload = assistant.plan("帮我看 Tushare 是否配好、本地缺哪些表", response_style="raw")
print(payload["plan"]["steps"])
print(payload["plan_md"][:400])
```

完整脚本见 `examples/ai_shell_stage_b0_demo.py`。阶段 B（Q-AI.2）plan-only 演示见 `examples/ai_shell_stage_b_demo.py`。阶段 C Ask/preview 见 `examples/ai_shell_stage_c_ask_demo.py`。

## 3. Notebook 方式

```python
import qteasy as qt
from qteasy_ai.app import QteasyAssistant

assistant = QteasyAssistant()
ask_output = assistant.ask("explain PT vs PS")
plan_output = assistant.plan("list built-in strategies")  # 默认 user_friendly
preview_output = assistant.preview("list built-in strategies", persist="none")
run_output = assistant.run("export kline of 000300.SH", keep=True)
raw_plan = assistant.plan("list built-in strategies", response_style="raw", persist="none")
debug_payload = assistant.debug_config()
```

其中 `debug_payload` 可用于核对当前配置来源与模式，不包含明文 API key。
`plan_output` / `run_output` 默认包含 `narrative/python_code/result_preview/raw` 四段信息。
如需完全兼容旧版结构化输出，使用 `response_style="raw"`。

### 3.1 Classic Notebook 魔法命令（无需 ipywidgets）

在 Classic Notebook 中可直接加载扩展，用“只写 prompt”的方式交互：

```python
%load_ext qteasy_ai.notebook_magic
```

先做 API 级诊断（Notebook 推荐）：

```python
%qtai --diag
```

或直接调用：

```python
from qteasy_ai.app import QteasyAssistant
assistant = QteasyAssistant()
assistant.debug_config()
```

说明：在 Notebook 中不推荐使用 `!qteasy-ai provider-check`，因为 kernel 环境的 PATH 与外部终端可能不一致。

Plan（默认）：

```python
%%qtai --mode plan
列出所有内置策略，并告诉我 macd 策略参数
```

Ask（纯只读）：

```python
%%qtai --mode ask
解释一下 PT/PS/VS 信号语义差异
```

Run（先 plan，后 confirm）：

```python
%%qtai --mode run
列出所有内置策略
```

输出会给出确认指令，再在下一个 cell 执行：

```python
%%qtai --confirm <plan_id>
Execute.
```

可选参数：

- `--raw`：返回原始结构化输出
- `--persist {bounded,audit,none}`：覆盖本次留存策略（Ask 不落盘）
- `--keep`：将本次 run 标记为保留
- `--depth {brief,standard,deep}`：解释层深度

对于尚未实现的能力（例如任意公式统计、选股/网格模板），当前阶段会返回结构化回退结果，
`payload.fallback_action` 可能为：

- `not_supported_yet`
- `clarify_required`（如下载缺起止日期、筛股缺阈值/窗口、双均线缺快慢周期）

实盘请求路由到 `qt.ai.pipeline.live_trade_plan_only`（只出计划，永不下单）。

阶段 B 已实现：本地 refill、内置策略回测/优化、只读筛股、回测内生归因。  
阶段 C 已实现：Ask 目标态（KB + 可选 LLM）、`preview` 迁移、`explanation_depth`、Hybrid LLM 候选（规则仍门禁）。  
阶段 D 已实现：StrategyBuilder 一条龙（NL→Spec→模板 codegen→sanity→Operator→复用回测）；源码写入 `.qteasy/ai/strategies/`。

完整脚本见 `examples/ai_shell_stage_c_ask_demo.py`、`examples/ai_shell_stage_d_strategybuilder_demo.py`。

当回退到 `system_fallback` 时，输出会明确给出：

- 回退原因（reason）
- 缺失信息（missing_info）
- 下一步建议（next_step）

## 4. 本地记忆文件

默认在项目目录创建：

- `.qteasy/ai/profile.json`
- `.qteasy/ai/env_facts.json`
- `.qteasy/ai/runs/*.json`
- `.qteasy/ai/strategies/*.py`（阶段 D 生成的策略源码）
- `.qteasy/ai/pinned/*.json`

其中 runs 文件用于复盘每次 plan 的执行轨迹与产物路径，默认采用有界留存（bounded）并自动清理；
用户显式保留的记录会写入 `pinned/`，不参与自动清理。

## 5. 语料回归入口（可选）

- 语料文件：`tests/ai_corpus/*.json`
- 人工记录模板：`tests/ai_corpus/manual_record_template.md`
- 执行脚本：`python tests/run_ai_manual_corpus.py`（或 `python -m unittest discover -s tests -p 'test_ai_*.py' -v`）
- 人工测试清单：[MANUAL_TEST.md](../MANUAL_TEST.md)
