# qteasy-ai Workbench (Web + TUI)

The workbench is an extra shell over the same `QteasyAssistant` used by CLI and Notebook. It does **not** reimplement the planner.

Install:

```bash
pip install "qteasy-ai[workbench]"
```

## Web (desktop three columns)

```bash
qteasy-ai serve --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`. Columns: **Session** (conversation, clarification, Plan confirm card, step checklist, composer) · **Artifacts** (tables, charts, code, reports) · **Workspace** (Now: job/slots/env; Files: `runs/` · `strategies/` · `user_kb/` tree). Workspace is collapsible. Enter inserts a newline; Ctrl/⌘+Enter sends.

- Ask / Plan / Agent are explicit. Completing slots does **not** auto-execute.
- Plan success completes the utterance (keeps `plan_id`). Confirm is an optional shortcut for `run_plan` and does **not** block the composer. Cancel dismisses the card; it does not abandon a closed job.
- Confirm runs `POST /v1/run-plan` with the reviewed `plan_id` (same as `qteasy-ai run --plan-id`). Editing `plan.md` does **not** change execution.
- Runs are stored in the same `.qteasy/ai/runs/` directory as the CLI.
- `GET /v1/sessions` lists saved sessions; `GET /v1/workspace` lists local files. Neither searches user KB.

CLI and Notebook default to **`--human`**: they print the same kernel human cards the chat pane uses (Ask, `plan_ready`, clarify, result, error, `mode_notice`). Do not treat that text or `plan.md` as executable. Plan dry-run also writes a **`plan` Artifact** (`runs/{run_id}.plan.md`) for review; JSON in `runs/{run_id}.json` is the only execute source (**json_wins**). **`run` / Agent does not create or show `plan.md`**. **`plan_id` is not the filename**. Use `--raw` or `--pretty` when you need the payload. `qteasy-ai` with no subcommand prints a usage card (`ask` / `plan` / `run --plan-id`) and does not execute.

## Minimal TUI

```bash
qteasy-ai tui --session-id demo
```

The TUI covers Ask, Plan confirmation, and `steps[]`. It does **not** show Artifact tabs; confirm still uses the DTO `plan_card`. Web reviews `plan.md` as a `plan` Artifact instead of dumping it into chat.

Human-card review (G.8/G.9): [LIVE_FIRE_DRILL_QAI7_HUMAN.md](LIVE_FIRE_DRILL_QAI7_HUMAN.md).

## Safety

Live trade is never auto-executed. High side-effect steps need an explicit confirm (or `agent_auto` plus `profile.agent.allow_*`).
