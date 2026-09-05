# Q-AI.5 补页：意图门 H′（E.8）

**状态：编码已落地（2026-09-05）。本页不改写 [QAI5 关单手册](LIVE_FIRE_DRILL_QAI5.md) 的 Mode-D lock 表。**

基线：qteasy-ai 阶段 E + E.8 H′ · 契约真源在 qteasy 仓 `knowledge/domain/qteasy-ai-hybrid-planner.md`。

| 项 | 说明 |
|----|------|
| **目标** | 核对 H′：宪法先跑；Mode-R 仅 1 命中；Mode-D 只信 LLM 协议 |
| **非目标** | 重开 Job 表；改 `recipes.py`；改 QAI5 lock 表；E.4 Journey gold |
| **CI 语料** | [`tests/ai_corpus/e8_h_prime_robustness.json`](../tests/ai_corpus/e8_h_prime_robustness.json)（FakeLLM；`test_ai_intent_h_prime.py`） |
| **可选真模型** | [`tests/run_ai_e8_live_robustness.py`](../tests/run_ai_e8_live_robustness.py)：**不进** unittest discover |

## 控制流（摘要）

1. **宪法**（R/D 相同）：`unsafe` / 显式 `not_supported` / 多高风险 `clarify` / `live.plan_only` 永不 auto。
2. **Mode-R**：`gold.json` 精确锁；业务 triggers **正好 1 个**才接受；0 或多 → `clarify`。冲突表停用。
3. **Mode-D**：跳过 gold / 业务 triggers / 冲突表。唯一合法且确定的 Job → 接受；`uncertain` / 多 `jobs` / 非法 → `clarify`。

## 回归（CI）

在 **qteasy-ai** 仓、**py39**、非 sandbox：

```bash
cd ~/Projects/qteasy-ai
/opt/anaconda3/envs/py39/bin/python -m unittest discover -s tests -p "test_ai_intent_*.py" -v
/opt/anaconda3/envs/py39/bin/python -m unittest discover -s tests -p "test_ai_planner_hybrid.py" -v
```

勿用 `python -m unittest tests.test_ai_*`（会撞 py39 `site-packages/tests/`）。

## 可选真模型审核

新 shell，设置 `QTEASY_AI_MODEL` / `QTEASY_AI_API_KEY` / `QTEASY_AI_BASE_URL` 后：

```bash
cd ~/Projects/qteasy-ai
/opt/anaconda3/envs/py39/bin/python tests/run_ai_e8_live_robustness.py
```

未设置 `QTEASY_AI_MODEL` 时打印 skip 并以 0 退出。有模型时 stdout 打印 Markdown 表：`id | expected_job | actual_job | match | rationale`。只跑 `d_paraphrase` / `d_multi_intent` / 宪法抽检。**给 Jackie 人工审核**，不是 CI 门。

`planner` assumptions 标记为 `hybrid_intent_h_prime`，便于与关单时的 `hybrid_intent_h` 手测区分。
