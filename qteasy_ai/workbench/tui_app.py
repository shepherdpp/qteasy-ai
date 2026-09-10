# coding=utf-8
# ======================================
# File: tui_app.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-07
# Desc:
# 最小 Textual TUI：Ask / Plan 确认 / steps，无 Artifact Tabs。
# ======================================

"""最小工作台 TUI。同进程调用 QteasyAssistant，不直接调 Planner。"""

from __future__ import annotations

from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, Static

from ..app import QteasyAssistant
from ..memory_store import MemoryStore
from .dto import WorkbenchState
from .mapper import map_assistant_payload


class WorkbenchTui(App):
    """Ask / Plan 确认卡 / 步骤列表；不做 Artifact Tabs。"""

    CSS = """
    #mode-badge { dock: top; height: 1; }
    #chat { height: 1fr; border: solid #444; }
    #plan-card { height: auto; border: solid #666; }
    #steps { height: auto; }
    #sidebar { width: 32; border: solid #444; }
    """

    def __init__(
        self,
        assistant: Optional[QteasyAssistant] = None,
        *,
        session_id: str = "tui",
    ) -> None:
        super().__init__()
        self.assistant = assistant or QteasyAssistant(memory_store=MemoryStore())
        self.session_id = session_id or "tui"
        self.mode = "plan"
        self.state: Optional[WorkbenchState] = None

    def compose(self) -> ComposeResult:
        """组合最小控件。"""

        yield Header()
        yield Static("Mode: PLAN", id="mode-badge")
        with Horizontal():
            with VerticalScroll(id="chat"):
                yield Static("Chat", id="chat-log")
                yield Static("", id="plan-card")
                yield Static("", id="steps")
                yield Button("Confirm", id="confirm-plan")
                yield Button("Cancel", id="cancel-plan")
            yield Static("Sidebar", id="sidebar")
        yield Input(placeholder="Query", id="query")
        yield Footer()

    def apply_dto(self, state: WorkbenchState) -> None:
        """测试与运行时共用的 DTO 渲染。"""

        self.state = state
        mode = (state.mode or self.mode).upper()
        self.query_one("#mode-badge", Static).update(f"Mode: {mode}")
        lines = [f"{msg.kind}: {msg.text}" for msg in state.messages]
        self.query_one("#chat-log", Static).update("\n".join(lines) or "Chat")
        card = state.plan_card
        if card and card.steps:
            parts = [f"plan {card.plan_id}"]
            for step in card.steps:
                fx = step.side_effects or {}
                parts.append(f"- {step.skill_name} side-effects={fx.get('description') or fx}")
            self.query_one("#plan-card", Static).update("\n".join(parts))
        else:
            self.query_one("#plan-card", Static).update("")
        exec_steps = (state.execution or {}).get("steps") or []
        marks = []
        for item in exec_steps:
            flag = "✓" if item.get("status") == "done" or item.get("ok") else "•"
            marks.append(f"{flag} {item.get('skill_name') or item.get('step_id')}")
        self.query_one("#steps", Static).update("\n".join(marks))
        bar = state.sidebar
        job = (bar.active_intent or {}).get("job") if bar and bar.active_intent else "-"
        missing = ", ".join(bar.missing) if bar else ""
        extra = ""
        if bar and bar.design:
            extra += f"\nDesign: {(bar.design or {}).get('job') or 'open'}"
        queue = list(bar.trial_queue or []) if bar else []
        if queue:
            extra += f"\nQueue: {len(queue)}"
        self.query_one("#sidebar", Static).update(f"Job: {job}\nMissing: {missing}{extra}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """回车发送。"""

        self.submit_query(str(event.value or ""))

    def submit_query(self, query: str) -> None:
        """Ask 或 Plan，不在 TUI 里调 Planner。"""

        text = str(query or "").strip()
        if not text:
            return
        if self.mode == "ask":
            payload = self.assistant.ask(text, response_style="raw", session_id=self.session_id)
        else:
            payload = self.assistant.plan(text, response_style="raw", session_id=self.session_id)
        session = self.assistant.session_store.load(self.session_id)
        self.apply_dto(map_assistant_payload(payload, session=session, query=text))

    def action_confirm_plan(self) -> None:
        """确认走 run_plan。"""

        card = None if self.state is None else self.state.plan_card
        if card is None or not card.plan_id or not card.confirmable:
            return
        payload = self.assistant.run_plan(card.plan_id, response_style="raw")
        self.apply_dto(map_assistant_payload(payload))

    def action_cancel_plan(self) -> None:
        """取消确认，不 execute。"""

        if self.state is not None:
            self.state.plan_card = None
            if self.state.plan_card is None:
                self.query_one("#plan-card", Static).update("cancelled")
        # 不调用 run_plan

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """确认 / 取消。"""

        if event.button.id == "cancel-plan":
            self.action_cancel_plan()
            return
        if event.button.id == "confirm-plan":
            self.action_confirm_plan()


def run_tui(*, assistant: Optional[QteasyAssistant] = None, session_id: str = "tui") -> None:
    """启动 TUI。"""

    WorkbenchTui(assistant, session_id=session_id).run()
