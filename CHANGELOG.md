# Changelog

All notable user-visible changes to **qteasy-ai** are documented here.  
SemVer applies independently from [qteasy](https://github.com/shepherdpp/qteasy).

## 0.4.0 (2026-11-19)

### Added

- Hold several named symbols as one portfolio (equal weight or a stated ratio) and plot it after confirm. A benchmark is its own field.
- Short read-only plans can chain up to three steps (read, transform, plot) after confirm. Backtest, refill, strategy writing, and live trade do not run from there.
- Settings can show the qteasy and qteasy-ai versions and release dates, and whether a data source is connected. Account details stay hidden.

### Changed

- A check-up or export keeps only the steps the sentence uses. Switching between volatility and return stays the same check-up.
- A plan does not finish from symbols, dates, or weights you did not write. Company names are not turned into codes. An illegal date stays on the same question. Ratios become weights; equal weight stays equal weight. Several holdings are one question each. An unexecuted plan changes only the fields the next sentence touches. A side question stays out of the plan.
- Confirm and result show the saved steps. The matched job and why it matched stay on the result; classify and validation text stay in the debug view.
- Ask follows numbered notes and keeps a fading outline of the session. A question about an earlier turn continues from that turn.
- The first Ctrl+C asks before serve exits; only y within 5 seconds quits. The clarify card stays above the composer. A failed step no longer blanks the chat.

## 0.3.1 (2026-10-31)

### Changed

- Workbench clarification is a step-by-step wizard (`< X of N >`): one slot at a time, up to five options per step, submit once all drafts are ready; End this request uses an in-card confirm.
- Clarify and plan-ready share a fixed-height card with letter-row options and short footer labels.
- While clarifying in the workbench, typing in the composer starts a new topic instead of filling slots or skipping; use the card controls. CLI typed slot-fill is unchanged.
- After three invalid clarification submits, the next card is a last chance; a fourth invalid submit ends the request with fail-close copy distinct from End this request.

## 0.3.0 (2026-10-28)

### Added

- Ask covers data concepts, HistoryPanel, strategy and signals, backtest and optimize, live-trade boundaries, and how to enter Ask / Plan / Confirm in the workbench.
- Session-level file attachments in the workbench composer.
- One-click copy for assistant output, with a checkmark and status-bar notice on success.

### Changed

- A "plain language" preference sticks for the rest of the Ask session. Questions about lookahead bias or PT / PS / VS stay on those topics.
- When nothing in the official notes matches, Ask leaves one language-matched assistant reply and does not add an error card.
- Deleting a session also removes the runs it owns. The Sessions list shortens long last-user previews; you can rename a session before it is saved.

## 0.2.3 (2026-10-15)

### Added

- Ask covers an overview window: what qteasy is, how the parts connect, why it beats a hand-written backtest, plus install, datasource FAQ, help, and the capability map.

### Changed

- In the same session, Ask remembers the last focus and follows up from named topics or earlier turns, instead of whole-sentence menu ordinals. Related notes are invited for a later question rather than pasted into the current answer.
- Workbench code fences label Ask and Result blocks and highlight only Python; bash and plain text stay uncolored.
- The assistant introduces itself as Kairos when asked who it is; the product shell title remains qteasy-ai.

## 0.2.2 (2026-10-08)

### Changed

- Without a model, a curated question returns that one answer. A space between Chinese and Latin does not change it: "如何用qteasy回测" and "如何用 qteasy 回测" both explain backtesting, not "what is qteasy".
- With a model, a paraphrase stays on the same topic. "如何用qteasy进行回测" explains backtesting instead of the product introduction. If the topic is uncertain or no card fits, Ask stops and suggests Plan.

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
