# coding=utf-8
# ======================================
# File: dto.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-07
# Desc:
# WorkbenchState 及子结构（Web / TUI 共用）。
# ======================================

"""工作台 DTO：Python dataclass → JSON，两端只渲染本结构。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

MESSAGE_KINDS = frozenset(
    {"user_text", "ask_text", "clarification", "plan_card", "step_status", "error"}
)
ARTIFACT_TYPES = frozenset({"data_table", "chart", "strategy_code", "backtest_report"})


@dataclass
class WorkbenchMessage:
    """对话流中的一条消息。"""

    kind: str
    text: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """序列化。"""

        return {"kind": self.kind, "text": self.text, "payload": dict(self.payload)}


@dataclass
class WorkbenchPlanStep:
    """确认卡上的一步。"""

    step_id: str
    skill_name: str
    side_effects: Dict[str, Any] = field(default_factory=dict)
    needs_confirm: bool = False
    status: str = "pending"
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """序列化。"""

        return asdict(self)


@dataclass
class WorkbenchPlanCard:
    """Plan 确认卡。Ask 路径 confirmable 必须为 False。"""

    plan_id: str
    steps: List[WorkbenchPlanStep] = field(default_factory=list)
    plan_md: str = ""
    confirmable: bool = True
    needs_confirm: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """序列化。"""

        return {
            "plan_id": self.plan_id,
            "steps": [step.to_dict() for step in self.steps],
            "plan_md": self.plan_md,
            "confirmable": self.confirmable,
            "needs_confirm": self.needs_confirm,
        }


@dataclass
class WorkbenchSidebarSlot:
    """侧栏单个槽。不含 confidence。"""

    name: str
    value: Any = None
    source: str = "user"
    confirmed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """序列化。"""

        return {
            "name": self.name,
            "value": self.value,
            "source": self.source,
            "confirmed": bool(self.confirmed),
        }


@dataclass
class WorkbenchSidebar:
    """状态侧栏：F ConversationState 投影。"""

    active_intent: Optional[Dict[str, Any]] = None
    slots: List[WorkbenchSidebarSlot] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    env_summary: Dict[str, Any] = field(default_factory=dict)
    current_plan_id: str = ""
    clarify_round: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """序列化。"""

        return {
            "active_intent": dict(self.active_intent) if self.active_intent else None,
            "slots": [slot.to_dict() for slot in self.slots],
            "missing": list(self.missing),
            "env_summary": dict(self.env_summary),
            "current_plan_id": self.current_plan_id,
            "clarify_round": int(self.clarify_round),
        }


@dataclass
class WorkbenchArtifact:
    """Artifact Tab 一项，必须带 run_id。"""

    type: str
    run_id: str
    title: str
    export_path: str = ""
    preview: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """序列化。"""

        return asdict(self)


@dataclass
class WorkbenchState:
    """工作台整页状态。"""

    mode: str
    session_id: str = ""
    messages: List[WorkbenchMessage] = field(default_factory=list)
    plan_card: Optional[WorkbenchPlanCard] = None
    sidebar: WorkbenchSidebar = field(default_factory=WorkbenchSidebar)
    artifacts: List[WorkbenchArtifact] = field(default_factory=list)
    execution: Dict[str, Any] = field(default_factory=dict)
    error: Optional[Dict[str, Any]] = None
    run_id: str = ""
    sources: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为前端/TUI JSON。"""

        return {
            "mode": self.mode,
            "session_id": self.session_id,
            "messages": [item.to_dict() for item in self.messages],
            "plan_card": None if self.plan_card is None else self.plan_card.to_dict(),
            "sidebar": self.sidebar.to_dict(),
            "artifacts": [item.to_dict() for item in self.artifacts],
            "execution": dict(self.execution),
            "error": dict(self.error) if isinstance(self.error, dict) else self.error,
            "run_id": self.run_id,
            "sources": list(self.sources),
        }
