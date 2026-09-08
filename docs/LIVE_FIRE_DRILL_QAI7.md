# Q-AI.7 (Phase G) live-fire handbook

**Status: coding complete; waiting for Jackie hand-off.** Do **not** bump semver in this slice. `1.0.0` is Jackie’s G.5 tag.

Baseline: qteasy-ai workbench extra · qteasy **>=2.6** · Python **py39**

| Item | Notes |
|------|--------|
| Goal | Desktop Web three-pane + minimal TUI; Plan confirm card; artifacts/`run_id` share CLI `runs/` |
| Non-goals | Open workflow, user-KB retrieve, mobile/H, slot-complete auto Agent, version bump |
| Directed tests | `python -m unittest tests.test_ai_workbench_dto tests.test_ai_workbench_progress tests.test_ai_workbench_http tests.test_ai_workbench_web tests.test_ai_workbench_artifacts tests.test_ai_workbench_tui tests.test_ai_workbench_journey tests.test_ai_cli_notebook_entry -v` |

Entry: `pip install -e ".[workbench]"` then `qteasy-ai serve` / `qteasy-ai tui`.

## Safety

Default **plan / ask**. Do not `run` unbounded refill. Confirm on the Plan card before execute. Live never auto.

## Mode-R checklist

| # | Action | Expect |
|---|--------|--------|
| G1 | Open Web; badge shows Ask/Plan/Agent | Mode visible; default Plan |
| G2 | Ask `什么是 qteasy` | Sources include `what_is_qteasy`; no Confirm execute |
| G3 | Plan `list built-in strategies` then Confirm | Steps + side-effects; execute writes same `runs/` as CLI |
| G4 | Plan `帮我下载日线` | Clarification form; no execute |
| G5 | Plan dated refill; **do not** Confirm if you lack token/tables | Card shows network/write side-effects |
| G6 | Artifact tabs after a readonly execute | Tabs carry `run_id`; export link works for existing files |
| G7 | Strategy code tab → Run | Extra confirm; does not silent `POST /v1/run` |
| G8 | `qteasy-ai tui` | Mode badge, Plan card, steps; **no** Artifact tabs |
| G9 | TUI Confirm on list-strategies | Step checklist ticks; CLI `runs/` updated |
| G10 | First `serve` / MemoryStore | `user_kb/` scaffold still present; Ask does not search it |

**Close bar:** Jackie signs G1–G10. Optional `1.0.0` is Jackie-only (CHANGELOG / pyproject). David does not bump.

## Cross links

- [`WORKBENCH.md`](WORKBENCH.md)
- Catalog: [`OFFICIAL_SKILL_CATALOG.md`](OFFICIAL_SKILL_CATALOG.md)
- Previous: [Q-AI.6](LIVE_FIRE_DRILL_QAI6.md) **closed**
