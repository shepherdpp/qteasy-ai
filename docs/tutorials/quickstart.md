# Tutorial 09 - qteasy AI shell 快速上手

本教程展示 S1.4 阶段A的最小闭环：plan 生成、确认执行、结构化结果查看。

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

### 2.1 Ask 模式

```bash
qteasy-ai ask "list built-in strategies"
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

执行后可在返回结果中查看 `run_file`，并追溯每个 step 的输入输出。

### 2.4 Provider 配置诊断

```bash
qteasy-ai provider-check
```

输出会包含 `mode/model/base_url/timeout/api_key_present/config_sources`，用于快速确认当前是规则模式、云端模型还是本地模型。

## 3. Notebook 方式

```python
import qteasy as qt
from qteasy_ai.app import QteasyAssistant

assistant = QteasyAssistant()
plan_output = assistant.plan("list built-in strategies")  # 默认 user_friendly
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
- `--persist {bounded,audit,none}`：覆盖本次留存策略
- `--keep`：将本次 run 标记为保留

对于尚未实现的能力（例如下载/回测/优化/策略生成等），当前阶段会返回结构化回退结果，
`payload.fallback_action` 可能为：

- `plan_only`
- `not_supported_yet`
- `clarify_required`

当回退到 `system_fallback` 时，输出会明确给出：

- 回退原因（reason）
- 缺失信息（missing_info）
- 下一步建议（next_step）

## 4. 本地记忆文件

默认在项目目录创建：

- `.qteasy/ai/profile.json`
- `.qteasy/ai/env_facts.json`
- `.qteasy/ai/runs/*.json`
- `.qteasy/ai/pinned/*.json`

其中 runs 文件用于复盘每次 plan 的执行轨迹与产物路径，默认采用有界留存（bounded）并自动清理；
用户显式保留的记录会写入 `pinned/`，不参与自动清理。

## 5. 语料回归入口（可选）

- 语料文件：`tests/ai_corpus/*.json`
- 人工记录模板：`tests/ai_corpus/manual_record_template.md`
- 执行脚本：`python tests/run_ai_manual_corpus.py`（或 `python -m unittest discover -s tests -p 'test_ai_*.py' -v`）
- 人工测试清单：[MANUAL_TEST.md](../MANUAL_TEST.md)
