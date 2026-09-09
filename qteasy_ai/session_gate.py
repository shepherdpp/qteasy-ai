# coding=utf-8
# ======================================
# File: session_gate.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-05
# Desc:
# 跟进句三分类：补槽 / 改槽 / 新意图。
# ======================================

"""会话门叠在 H′ 之上。补槽/改槽不调用 classify。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .planner import Planner
from .provider import BaseLLMProvider
from .session import ConversationState

_AFFIRM = (
    "对",
    "好的",
    "确认",
    "理解正确",
    "yes",
    "ok",
    "okay",
    "confirm",
    "correct",
)
_ABANDON_AFFIRM = ("放弃", "是的放弃", "abandon", "yes abandon", "丢弃")
_CHANGE_HINTS = ("改用", "改成", "换成", "改为", "change to", "use instead")
_JOB_VERBS = (
    ("optimize.builtin", ("优化", "optimize", "参数优化")),
    ("backtest.builtin", ("回测", "backtest")),
    ("data.refill", ("下载", "download", "refill", "灌数据")),
    ("research.screen", ("筛股", "筛选", "screen")),
    ("strategy.builder", ("生成策略", "写策略", "创建策略", "strategybuilder", "帮我写", "写一个")),
    ("data.summary", ("波动率", "摘要", "summary")),
)

_FOLLOWUP_KINDS = frozenset({"fill_slot", "change_slot", "new_intent", "confirm", "clarify"})


@dataclass
class GateDecision:
    """会话门输出。"""

    kind: str
    patches: Dict[str, Any] = field(default_factory=dict)
    needs_abandon: bool = False
    abandon_confirmed: bool = False
    source: str = "rule"
    rationale: str = ""


class SessionGate:
    """跟进句分类器。"""

    def __init__(self, provider: Optional[BaseLLMProvider] = None) -> None:
        self.provider = provider

    def classify(self, session: ConversationState, query: str) -> GateDecision:
        """对跟进句分类。

        Parameters
        ----------
        session : ConversationState
            当前会话。
        query : str
            本轮用户输入。

        Returns
        -------
        GateDecision
            kind / patches / 放弃标志。
        """

        text = (query or "").strip()
        # 放弃确认门优先于 LLM，避免 awaiting_abandon 被跟进分类绕过。
        if session.awaiting_abandon:
            return self._classify_rule(session, text)
        # 已完成任务：下一句一律新意图，禁止再 fill_slot 进旧 Job（含 Mode-D）。
        if session.task_complete and session.active_intent:
            return GateDecision(kind="new_intent", rationale="new_after_complete")
        if self.provider is not None and session.active_intent:
            return self._classify_llm(session, text)
        return self._classify_rule(session, text)

    def _classify_rule(self, session: ConversationState, text: str) -> GateDecision:
        """Mode-R 规则路径。"""

        if not session.active_intent:
            return GateDecision(kind="new_intent", rationale="first_turn")

        lower = text.lower()
        if session.awaiting_abandon:
            if self._is_abandon_affirm(text, lower):
                return GateDecision(
                    kind="new_intent",
                    abandon_confirmed=True,
                    rationale="abandon_confirmed",
                )
            return GateDecision(kind="clarify", rationale="abandon_not_confirmed")

        if self._is_affirm(text, lower) and session.pending_clarification:
            return GateDecision(kind="confirm", rationale="affirm_pending")

        hinted_job = self._hinted_job(text, lower)
        active_job = str((session.active_intent or {}).get("job") or "")
        if hinted_job and hinted_job != active_job:
            if session.task_incomplete() and not session.task_complete:
                return GateDecision(
                    kind="new_intent",
                    needs_abandon=True,
                    rationale="new_intent_incomplete",
                )
            return GateDecision(kind="new_intent", rationale="new_intent_idle")

        patches = extract_patches(text)
        if patches:
            kind = "change_slot" if self._is_change(text, lower) else "fill_slot"
            return GateDecision(kind=kind, patches=patches, rationale=kind)
        if self._is_affirm(text, lower):
            return GateDecision(kind="confirm", rationale="affirm")
        return GateDecision(kind="fill_slot", patches={}, rationale="followup_no_patch")

    def _classify_llm(self, session: ConversationState, text: str) -> GateDecision:
        """Mode-D：只接受 followup JSON。"""

        prompt = (
            "Classify a follow-up. Reply JSON only: "
            '{"followup":"fill_slot|change_slot|new_intent|confirm","patches":{}} . '
            f"Active job: {(session.active_intent or {}).get('job')}. "
            f"Slots: { {k: v.to_dict() for k, v in session.slots.items()} }. "
            f"Missing: {session.missing}. Utterance: {text}"
        )
        raw = self.provider.chat(prompt, system_prompt="Session follow-up classifier. JSON only.")
        parsed = _parse_followup_json(raw)
        if parsed is None:
            return GateDecision(kind="clarify", source="llm", rationale="invalid_followup_json")
        kind = str(parsed.get("followup") or "")
        if kind not in _FOLLOWUP_KINDS:
            return GateDecision(kind="clarify", source="llm", rationale="unknown_followup_kind")
        if "steps" in parsed:
            return GateDecision(kind="clarify", source="llm", rationale="steps_not_allowed")
        patches = parsed.get("patches") if isinstance(parsed.get("patches"), dict) else {}
        needs_abandon = False
        if kind == "new_intent" and session.task_incomplete():
            needs_abandon = True
        return GateDecision(
            kind=kind,
            patches=dict(patches),
            needs_abandon=needs_abandon,
            source="llm",
            rationale="llm_followup",
        )

    @staticmethod
    def _is_affirm(text: str, lower: str) -> bool:
        """是否整句肯定确认（避免「对，改用…」被误判）。"""

        compact = re.sub(r"[\s,，。.!！]", "", text).lower()
        needles = {re.sub(r"[\s,，。.!！]", "", token).lower() for token in _AFFIRM}
        needles.update({"对理解正确", "理解正确"})
        return compact in needles or compact in {"yes", "ok", "okay", "y", "confirm", "correct"}

    @staticmethod
    def _is_abandon_affirm(text: str, lower: str) -> bool:
        """是否确认放弃当前任务。"""

        compact = text.replace(" ", "").lower()
        return any(token in compact or token in lower for token in _ABANDON_AFFIRM)

    @staticmethod
    def _is_change(text: str, lower: str) -> bool:
        """是否改槽措辞。"""

        return any(hint in text or hint in lower for hint in _CHANGE_HINTS)

    @staticmethod
    def _hinted_job(text: str, lower: str) -> str:
        """从办事动词猜测另一 Job。"""

        for job, verbs in _JOB_VERBS:
            if any(verb in text or verb in lower for verb in verbs):
                return job
        return ""


def extract_patches(text: str) -> Dict[str, Any]:
    """从跟进句抽出槽补丁（日期 / 标的 / 慢线）。"""

    patches: Dict[str, Any] = {}
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
    return patches


def merge_facts(
    session: ConversationState,
    patches: Dict[str, Any],
    *,
    source: str = "user",
    confirmed: bool = True,
) -> None:
    """把补丁写入结构化槽。"""

    for key, value in (patches or {}).items():
        session.set_slot(str(key), value, source=source, confirmed=confirmed)
        if key in session.missing:
            session.missing = [item for item in session.missing if item != key]


def _parse_followup_json(raw: str) -> Optional[Dict[str, Any]]:
    """解析 Mode-D followup JSON。"""

    text = (raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    return data
