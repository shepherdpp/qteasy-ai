# coding=utf-8
# ======================================
# File: session_gate.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-05
# Desc:
# 跟进句分类：填槽 / 新 Task / 执行 / 只讨论 / 跳过澄清。
# ======================================

"""会话门叠在 H′ 之上。填槽不调用 classify；Composer 换题开新 Task。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .planner import Planner
from .provider import BaseLLMProvider
from .session import ConversationState

_PLAN_ID_RE = re.compile(r"plan_[0-9a-f]+", flags=re.IGNORECASE)
_DISCUSS_ONLY = (
    "本次只讨论",
    "不出计划",
    "不运行",
    "just discuss",
    "discuss only",
    "don't plan",
    "do not plan",
    "no plan this time",
)
_EXECUTE_PLAN_HINTS = (
    "执行上面的计划",
    "运行该计划",
    "请执行计划",
    "请运行计划",
    "执行计划",
    "运行计划",
    "run this plan",
    "execute the plan",
    "run the plan",
    "execute plan",
)
_STRATEGY_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,31}$")


@dataclass
class GateDecision:
    """会话门输出。"""

    kind: str
    patches: Dict[str, Any] = field(default_factory=dict)
    source: str = "rule"
    rationale: str = ""


class SessionGate:
    """跟进句分类器。"""

    def __init__(self, provider: Optional[BaseLLMProvider] = None) -> None:
        self.provider = provider

    def classify(self, session: ConversationState, query: str) -> GateDecision:
        """对 Composer 跟进句分类。

        Parameters
        ----------
        session : ConversationState
            当前会话。
        query : str
            本轮用户输入。

        Returns
        -------
        GateDecision
            kind / patches。
        """

        text = (query or "").strip()
        hatch = _hatch_decision(session, text)
        if hatch is not None:
            return hatch
        if answers_pending_slot(session, text):
            patches = extract_patches(text)
            missing = list(session.task.missing) if session.task is not None else []
            if "strategy_id" in missing and _STRATEGY_TOKEN_RE.match(text) and "strategy_id" not in patches:
                patches["strategy_id"] = text
            return GateDecision(kind="fill_slot", patches=patches, rationale="answers_slot")
        status = session.task_status()
        if status == "running" and bool(getattr(session.task, "high_side_effect", False)):
            return GateDecision(kind="block_running", rationale="high_side_effect_running")
        return GateDecision(kind="new_intent", rationale="composer_new_task")


def answers_pending_slot(session: ConversationState, text: str) -> bool:
    """clarifying 且本句是在回答当前问槽。"""

    if session.task_status() != "clarifying":
        return False
    raw = str(text or "").strip()
    if not raw:
        return False
    task = session.task
    pending = task.pending_clarification if task is not None and isinstance(task.pending_clarification, dict) else {}
    missing = [str(item) for item in ((task.missing if task is not None else []) or [])]
    options = pending.get("options") if isinstance(pending.get("options"), list) else []
    compact = raw.lower()
    for opt in options:
        if not isinstance(opt, dict):
            continue
        oid = str(opt.get("id") or "").strip()
        label = str(opt.get("label") or "").strip()
        if oid and compact == oid.lower():
            return True
        if label and compact == label.lower():
            return True
    if _STRATEGY_TOKEN_RE.match(raw) and ("strategy_id" in missing or not missing):
        if "strategy_id" in missing:
            return True
        pending_names = []
        for item in pending.get("pending") or []:
            if isinstance(item, dict) and item.get("name"):
                pending_names.append(str(item.get("name")))
        if "strategy_id" in pending_names:
            return True
    patches = extract_patches(raw)
    if patches and missing and set(str(k) for k in patches.keys()).issubset(set(missing)):
        return True
    return False


def extract_plan_id(text: str) -> str:
    """抽出 ``plan_[0-9a-f]+``；没有则空串。"""

    match = _PLAN_ID_RE.search(str(text or ""))
    return str(match.group(0)).lower() if match else ""


def is_discuss_only(text: str) -> bool:
    """plan/run 句是否明确只要讨论、不要计划。"""

    raw = str(text or "")
    lower = raw.lower()
    return any(token in raw or token in lower for token in _DISCUSS_ONLY)


def is_execute_plan_utterance(text: str) -> bool:
    """是否口头执行当前或句中计划。"""

    raw = str(text or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if any(token in raw or token in lower for token in _EXECUTE_PLAN_HINTS):
        return True
    compact = re.sub(r"\s+", "", raw).lower()
    return bool(_PLAN_ID_RE.fullmatch(compact))


def is_skip_clarify(text: str) -> bool:
    """整句 skip / 跳过。"""

    compact = re.sub(r"[\s,，。.!！]", "", str(text or "")).lower()
    return compact in {"skip", "跳过", "跳过吧", "skipit"}


def _hatch_decision(session: ConversationState, text: str) -> Optional[GateDecision]:
    """模式缺口与 skip。"""

    if is_discuss_only(text):
        return GateDecision(kind="discuss_only", rationale="discuss_only")
    task = session.task
    if is_skip_clarify(text) and task is not None and (task.pending_clarification or task.missing):
        return GateDecision(kind="skip_clarify", rationale="skip_clarify")
    if is_execute_plan_utterance(text):
        patches: Dict[str, Any] = {}
        plan_id = extract_plan_id(text)
        if plan_id:
            patches["plan_id"] = plan_id
        return GateDecision(kind="execute_plan", patches=patches, rationale="execute_plan")
    return None


def extract_patches(text: str) -> Dict[str, Any]:
    """从跟进句抽出槽补丁（日期 / 标的 / 慢线 / strategy_id）。"""

    patches: Dict[str, Any] = {}
    raw = str(text or "").strip()
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,31}", raw):
        patches["strategy_id"] = raw
    else:
        named_sid = re.search(
            r"strategy_id\s*(?:是|为|=|:|：)\s*([A-Za-z][A-Za-z0-9_]+)",
            raw,
            flags=re.IGNORECASE,
        )
        if named_sid:
            patches["strategy_id"] = named_sid.group(1)
        else:
            named_sid = re.search(
                r"策略(?:\s*id)?\s*(?:是|为|=|:|：)\s*([A-Za-z][A-Za-z0-9_]+)",
                raw,
                flags=re.IGNORECASE,
            )
            if named_sid:
                patches["strategy_id"] = named_sid.group(1)
    market = Planner._extract_market_inputs(text)
    for key in ("start", "end", "shares", "freq"):
        if market.get(key):
            patches[key] = market[key]
    end_only = re.search(r"(?:到|至|until|to)\s*(20\d{2})\s*年?", text, flags=re.IGNORECASE)
    if end_only and "end" not in patches:
        patches["end"] = f"{int(end_only.group(1)):04d}1231"
    slow = re.search(r"慢线\s*(?:改成|改为|换成|成|=|:|：)?\s*(\d+)", text)
    if slow:
        patches["slow"] = int(slow.group(1))
    fast = re.search(r"快线\s*(?:改成|改为|换成|成|=|:|：)?\s*(\d+)", text)
    if fast:
        patches["fast"] = int(fast.group(1))
    hyp = re.search(
        r"hypothesis\s*(?:改成|改为|换成|为|=|:|：)\s*(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if hyp:
        patches["hypothesis"] = hyp.group(1).strip()
    named = re.search(r"(?:named|叫)\s+([A-Za-z0-9_]+)", text, flags=re.IGNORECASE)
    if named:
        patches["name"] = named.group(1)
    return patches


def merge_facts(
    session: ConversationState,
    patches: Dict[str, Any],
    *,
    source: str = "user",
    confirmed: bool = True,
) -> None:
    """把补丁写入结构化槽。"""

    if session.task is None:
        return
    for key, value in (patches or {}).items():
        session.set_slot(str(key), value, source=source, confirmed=confirmed)
        if key in session.task.missing:
            session.task.set_missing([item for item in session.task.missing if item != key])
