# Changelog

All notable user-visible changes to **qteasy-ai** are documented here.  
SemVer applies independently from [qteasy](https://github.com/shepherdpp/qteasy).

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
