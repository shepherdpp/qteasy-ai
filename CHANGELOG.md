# Changelog

All notable user-visible changes to **qteasy-ai** are documented here.  
SemVer applies independently from [qteasy](https://github.com/shepherdpp/qteasy).

## 0.2.1 (2026-10-07)

### Added

- `qteasy_ai.version_info` exposes major / minor / patch fields, matching `qteasy.version_info`.

### Changed

- Ask stays on one topic. Questions about errors or live-trade limits no longer mix in an intro explanation.
- A bare mention of "strategy" no longer brings up the built-in strategy list. Naming a strategy (such as macd defaults) or asking to list built-in strategies still returns live metadata. A bare "what is a strategy" with no matching topic stops and suggests Plan.

## 0.2.0 (2026-10-05)

### Added

- `qteasy-ai ask` only answers. It no longer returns an empty dry-run plan. `plan` shows the steps first; after you confirm, it can read data, backtest, or optimize. This works without a configured model.
- Desktop workbench via `qteasy-ai serve`: conversation, artifacts, and the current task. Open the plan in the artifact pane. Stop a run, or leave it in the background.
- Official jobs: environment check, bounded data refill, read and summarize, built-in backtest and optimization, a short read of the last backtest, and a dual-moving-average strategy draft. Live trade stays plan-only.
- Continue in the same session: add a date or symbol, or revise the previous plan. Clarification offers a choice; skip ends that turn.

### Changed

- Save several providers in Settings and switch among them. Lists never show raw API keys. Without a model, Ask uses the built-in notes and Plan follows the built-in rules. The default model wait is 120 seconds (`QTEASY_AI_TIMEOUT`).
- Reopening a session after a process stop lets you confirm the same plan again. It does not resume the interrupted step.
- Exporting a k-line chart from the workbench no longer takes the server down with the plot window.

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
