# Q-AI.7 Open loop live-fire (G.7)

**Status: Hang (2026-09-11).** Coding + CLI gold path landed; **do not close G.7**. Resume after **G.8** close-out. Do not close G.6, do not tag 1.0, do not bump semver.

Baseline: qteasy-ai workbench extra · qteasy **>=2.6** · Python **py39**

| Item | Notes |
|------|--------|
| Goal | Open-loop design (factor explore on Web) + user KB consume/write + CLI retreat |
| Non-goals | Resume G.6 PDCA, Workspace Files cleanup, UI rubric edits, TUI as 1.0 gate, scene 3, version bump |
| Directed tests | `python -m unittest tests.test_ai_open_workflow tests.test_ai_open_trial tests.test_ai_open_builder tests.test_ai_user_kb_consume tests.test_ai_workbench_open tests.test_ai_session tests.test_ai_intent_gold tests.test_ai_workbench_web -v` |

Entry: `qteasy-ai serve` (Web gold path) or `qteasy-ai plan --session-id g7 …`.

## Safety

Default **plan**. Nested IC trial uses the **same** Plan Confirm card as a standalone `research.factor_ic`. Do not `run` unbounded refill. Ask still must not search `user_kb/`.

System Job **`open`** (legal-edge DAG) is **not** the design loop. Catalog `workflow: open` / `flags.open_loop` is.

## Web gold path (factor explore)

Use Plan mode. Trigger words must **not** be a lone「因子 IC」.

| # | Action | Expect |
|---|--------|--------|
| O1 | `explore a useful momentum factor for hs300` (or「帮我找一个沪深300上有用的动量因子」) | Design card (hypothesis / FactorSpec), **not** an Ask bubble, **not** an IC/codegen confirm card. Workspace `#g7-slot` shows draft |
| O2 | Follow up `hypothesis: short-term reversal on hs300` | Spec updates; still no `factor_ic_summary` |
| O3 | `try IC on this factor` | One closed IC Plan card (Confirm / Change params / Cancel). Queue shows one **active** trial |
| O4 | Optional: Confirm the trial | Same confirm gate as standalone IC. Design draft remains |
| O5 | `lock this spec` then Confirm write | Writes `user_kb/raw/factors/{slug}.md` only after confirm; `#g7-slot` lists KB hits |
| O6 | **Abandon trial** / **Abandon open job** | Buttons in `#g7-slot` and design card; trial drop keeps draft; open drop keeps `session_id` |
| O7 | Ask `什么是 qteasy` | `what_is_qteasy`; **no** user-note sources; no confirmable plan card |
| O8 | Closed regression: Beginner list-strategies / dual-MA builder | Same Confirm card DOM as G.6 Hang |

## CLI extras (builder open flag is CLI-only)

```text
qteasy-ai plan "explore a useful momentum factor for hs300" --session-id g7 --raw
qteasy-ai plan "try IC on this factor" --session-id g7 --raw
qteasy-ai plan --abandon-trial --session-id g7
qteasy-ai plan "lock this spec" --session-id g7
qteasy-ai plan --confirm-kb-write --session-id g7
qteasy-ai plan --abandon-open --session-id g7

# smoke only — do not demo on Web this slice
qteasy-ai plan "还没想好规则，帮我设计一个策略" --session-id g7b --raw
# still closed five-step recipe
qteasy-ai plan "帮我写一个基于 20/60 日均线金叉死叉的择时策略，并用 2015–2020 年沪深300做回测"
```

NL equivalents: `abandon trial` /「放弃这次试错」; `abandon open` /「放弃这个探索」.

KB write order: **lock → `--confirm-kb-write` → then `--abandon-open`**. Abandon-open first clears the design; later lock has nothing to write.

## Close bar

Jackie signs O1–O8 **after G.8**. This slice stays Hang. **Does not** close G.6. **Does not** ship 1.0.

## Cross links

- Previous workbench hang: [Q-AI.7](LIVE_FIRE_DRILL_QAI7.md) (G.0–G.4 shell; G.6 still open)
- Domain: `qteasy-ai-job-workflow` / `qteasy-ai-session` / `qteasy-ai-workbench` / `qteasy-ai-knowledge-layers`
