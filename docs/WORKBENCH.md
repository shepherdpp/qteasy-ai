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

Open `http://127.0.0.1:8765`. Columns: Chat (Ask bubbles, clarification form, Plan confirm card, step checklist) · Artifacts (tabs) · State sidebar.

- Ask / Plan / Agent are explicit. Completing slots does **not** auto-execute.
- Confirm runs `POST /v1/run-plan` with the reviewed `plan_id` (same as `qteasy-ai run --plan-id`).
- Runs are stored in the same `.qteasy/ai/runs/` directory as the CLI.

## Minimal TUI

```bash
qteasy-ai tui --session-id demo
```

The TUI covers Ask, Plan confirmation, and `steps[]`. It does **not** show Artifact tabs.

## Safety

Live trade is never auto-executed. High side-effect steps need an explicit confirm (or `agent_auto` plus `profile.agent.allow_*`).
