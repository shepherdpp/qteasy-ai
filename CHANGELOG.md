# Changelog

All notable user-visible changes to **qteasy-ai** are documented here.  
SemVer applies independently from [qteasy](https://github.com/shepherdpp/qteasy).

## Unreleased

### Changed

- Default LLM Provider timeout is **120 seconds** (was 30). Override with `QTEASY_AI_TIMEOUT` or `ai_timeout`.
- Hybrid Plan: when the LLM skill sequence and the rule recipe are contiguous subsequences of each other, the plan is replaced by the rule recipe (`assumptions.recipe_slots_from=rule`). Extra LLM wrapper steps are dropped. `candidate_source` stays `llm`. Fallback-only recipes still do not overwrite, except when the query hits StrategyBuilder keywords (incomplete dual-MA → `clarify_required`).
- Hybrid Plan: Mode-D `planner_trace.llm_skill_sequence` records the skill names **before** recipe overwrite (not persisted for rule-only plans). Full prompts are not stored.

### Breaking

- **`ask()` target state (Q-AI.3)**: `assistant.ask()` / `qteasy-ai ask` no longer returns an empty-step ToolPlan dry-run. It answers via KnowledgeBase (+ optional LLM) and does not call skills or PlanExecutor. Use `preview()` / `qteasy-ai preview` / `plan --preview` to inspect a dry-run ToolPlan.

### Added

- KnowledgeBase (`qteasy_ai/kb/*.json`) and `AskEngine` (Offline when no Provider).
- `assistant.preview()`, CLI `preview`, `plan --preview`.
- `explanation_depth`: `brief` / `standard` / `deep` (`--depth`).
- Hybrid Planner LLM candidate generation; RuleValidator and `env_facts` gates still apply. Unknown skills / invalid JSON fall back to the rule router. Candidate prompt includes each skill's one-line `summary`.
- User guide: [docs/USER_GUIDE.md](docs/USER_GUIDE.md). Demo: `examples/ai_shell_stage_c_ask_demo.py`.
- **StrategyBuilder (Q-AI.4)**: `qt.ai.strategy.spec_from_nl` / `codegen_hybrid` / `sanity_check` / `qt.ai.operator.build_from_spec`; generated source under `.qteasy/ai/strategies/`; reuses `backtest.run_builtin` (optional `strategy_path`). Live: `qt.ai.pipeline.live_trade_plan_only`. Demo: `examples/ai_shell_stage_d_strategybuilder_demo.py`. Handbook: [docs/LIVE_FIRE_DRILL_QAI4.md](docs/LIVE_FIRE_DRILL_QAI4.md) (live-fire closed 2026-08-31).

## 0.1.0 (2026-08-06)

First public release after splitting from qteasy `qt_ai_dev` (Stage A, behavior unchanged).

### Added

- **`qteasy_ai` package**: SkillRegistry, Hybrid Planner + RuleValidator, PlanExecutor, read-only skills (strategy_meta, data_summary, visual_export, system_fallback).
- **CLI** `qteasy-ai`: `ask`, `plan`, `run`, `provider-check`.
- **Notebook magic** `%load_ext qteasy_ai.notebook_magic` / `%qtai`.
- **Memory store**: profile, env_facts, bounded runs + pinned retention.
- **ConfigCenter**: env vars `QTEASY_AI_*` (optional injected `qt_config` for legacy `ai_*` keys).
- **Tests**: 34 `test_ai_*` cases; corpus JSON under `tests/ai_corpus/`.
- **Docs**: design ADRs (11–13), [quickstart](docs/tutorials/quickstart.md), [manual test guide](docs/MANUAL_TEST.md).

### Dependencies

- Requires **`qteasy>=2.6.0`** (kernel APIs only; qteasy does not ship AI code).
