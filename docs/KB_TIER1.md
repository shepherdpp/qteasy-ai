# Official KB Pack (F.5 / tier-1)

F.5 tier-1 is a **subset** of the official Ask pack in `qteasy_ai/kb/*.json`.
These 18 ids (7 carried + 11 new) must remain present. From 0.3 the pack may grow past the old 15–25 cap.
Do **not** put user research notes here. Ask never reads `user_kb/`.

## Carried from stage C (do not rewrite unless drifted)

| id | type | topic |
|----|------|--------|
| `pt_ps_vs` | concept | PT / PS / VS |
| `operator_run_freq` | concept | run_freq belongs on Operator |
| `ask_plan_agent` | concept | Ask vs Plan vs run |
| `side_effects_safety` | boundary | side-effects / confirm |
| `common_errors_nan` | trap | NaN prices |
| `common_errors_run_freq` | trap | run_freq mistakes |
| `common_errors_date_window` | trap | missing date window |

## New in F.5

| id | type | topic |
|----|------|--------|
| `what_is_qteasy` | concept | Product intro; hits 什么是qteasy / 什么是 qteasy / what is qteasy |
| `getting_started` | concept | First steps |
| `data_three_entries` | concept | history / reference / static |
| `backtest_intro` | concept | Built-in backtest |
| `optimize_intro` | concept | Built-in optimize |
| `refill_bounded` | concept | Dated download only |
| `strategy_builder_intro` | concept | Dual-MA StrategyBuilder |
| `env_ready` | concept | Tushare / tables |
| `notebook_cli` | concept | CLI / %%qtai / session-id |
| `live_plan_only` | boundary | Live never auto |
| `official_vs_user_kb` | concept | Official KB vs user_kb scaffold |

## Must-hit queries (Mode-R Ask, zero skill)

- `什么是qteasy`
- `什么是 qteasy`
- `what is qteasy`
- Journey `BJ-ASK-WHAT`: `qteasy 是什么`
