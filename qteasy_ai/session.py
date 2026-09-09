# coding=utf-8
# ======================================
# File: session.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-05
# Desc:
# 多轮 ConversationState 与 sessions/ 落盘。
# ======================================

"""闭合 Job 的多轮会话状态。

加载忽略未知键（1.x 可加可选字段）。不预填开放环字段。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .memory_store import MemoryStore, _json_safe

SLOT_SOURCES = frozenset({"user", "profile", "env_facts", "default", "extracted"})
VISIBLE_MESSAGE_KINDS = frozenset({"user_text", "ask_text", "error", "clarification"})
_SKIP_MESSAGE_KINDS = frozenset({"", "plan_card", "step_status"})
_STATE_KEYS = frozenset(
    {
        "session_id",
        "active_intent",
        "slots",
        "missing",
        "pending_clarification",
        "current_plan_id",
        "clarify_round",
        "turns",
        "messages",
        "attachments",
        "agent_auto",
        "awaiting_abandon",
        "original_query",
        "task_complete",
    }
)


def normalize_message(raw: Any) -> Optional[Dict[str, Any]]:
    """把一条可见对话规范成 ``kind`` / ``text`` / ``payload``。

    Parameters
    ----------
    raw : Any
        原始消息。

    Returns
    -------
    dict or None
        非法或应跳过的 kind 返回 None。
    """

    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip()
    if kind in _SKIP_MESSAGE_KINDS or not kind:
        return None
    text = str(raw.get("text") or "")
    payload = dict(raw.get("payload") or {}) if isinstance(raw.get("payload"), dict) else {}
    return {"kind": kind, "text": text, "payload": payload}


def _coerce_messages(raw: Any) -> List[Dict[str, Any]]:
    """从 JSON 恢复 messages 列表。"""

    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        row = normalize_message(item)
        if row is not None:
            out.append(row)
    return out


@dataclass
class Slot:
    """单个槽位：值、来源、是否已确认。不含 confidence。"""

    value: Any = None
    source: str = "user"
    confirmed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""

        source = self.source if self.source in SLOT_SOURCES else "user"
        return {"value": self.value, "source": source, "confirmed": bool(self.confirmed)}

    @classmethod
    def from_dict(cls, raw: Any) -> "Slot":
        """从字典恢复；丢弃 confidence 等未知键。"""

        data = raw if isinstance(raw, dict) else {"value": raw}
        source = str(data.get("source") or "user")
        if source not in SLOT_SOURCES:
            source = "user"
        return cls(
            value=data.get("value"),
            source=source,
            confirmed=bool(data.get("confirmed", False)),
        )


@dataclass
class ConversationState:
    """一次会话的最小结构化状态。"""

    session_id: str
    active_intent: Optional[Dict[str, Any]] = None
    slots: Dict[str, Slot] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    pending_clarification: Optional[Dict[str, Any]] = None
    current_plan_id: str = ""
    clarify_round: int = 0
    turns: List[Dict[str, Any]] = field(default_factory=list)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    agent_auto: bool = False
    awaiting_abandon: bool = False
    original_query: str = ""
    task_complete: bool = False

    @classmethod
    def empty(cls, session_id: str) -> "ConversationState":
        """新建空会话。"""

        return cls(session_id=str(session_id or "").strip() or "default")

    def to_dict(self) -> Dict[str, Any]:
        """只写出 F 已知字段，不写 active_design / 试错队列。"""

        return {
            "session_id": self.session_id,
            "active_intent": dict(self.active_intent) if self.active_intent else None,
            "slots": {key: slot.to_dict() for key, slot in self.slots.items()},
            "missing": list(self.missing),
            "pending_clarification": dict(self.pending_clarification)
            if isinstance(self.pending_clarification, dict)
            else None,
            "current_plan_id": self.current_plan_id,
            "clarify_round": int(self.clarify_round),
            "turns": list(self.turns),
            "messages": list(self.messages),
            "attachments": list(self.attachments),
            "agent_auto": bool(self.agent_auto),
            "awaiting_abandon": bool(self.awaiting_abandon),
            "original_query": self.original_query,
            "task_complete": bool(self.task_complete),
        }

    @classmethod
    def from_dict(cls, raw: Any, *, session_id: str = "") -> "ConversationState":
        """从 JSON 恢复；忽略未知键。"""

        data = raw if isinstance(raw, dict) else {}
        sid = str(data.get("session_id") or session_id or "").strip() or "default"
        slots_raw = data.get("slots") if isinstance(data.get("slots"), dict) else {}
        slots = {str(key): Slot.from_dict(value) for key, value in slots_raw.items()}
        attachments: List[Dict[str, Any]] = []
        for item in data.get("attachments") or []:
            if not isinstance(item, dict):
                continue
            path = str(item.get("source_path") or "").strip()
            if not path:
                continue
            att: Dict[str, Any] = {"source_path": path}
            if item.get("summary"):
                att["summary"] = str(item.get("summary"))
            attachments.append(att)
        intent = data.get("active_intent")
        if not isinstance(intent, dict):
            intent = None
        pending = data.get("pending_clarification")
        if not isinstance(pending, dict):
            pending = None
        return cls(
            session_id=sid,
            active_intent=intent,
            slots=slots,
            missing=[str(item) for item in (data.get("missing") or [])],
            pending_clarification=pending,
            current_plan_id=str(data.get("current_plan_id") or ""),
            clarify_round=int(data.get("clarify_round") or 0),
            turns=list(data.get("turns") or []) if isinstance(data.get("turns"), list) else [],
            messages=_coerce_messages(data.get("messages")),
            attachments=attachments,
            agent_auto=bool(data.get("agent_auto", False)),
            awaiting_abandon=bool(data.get("awaiting_abandon", False)),
            original_query=str(data.get("original_query") or ""),
            task_complete=bool(data.get("task_complete", False)),
        )

    def task_incomplete(self) -> bool:
        """当前闭合任务尚未完成（有缺失、澄清中或计划未确认）。"""

        if self.task_complete:
            return False
        if not self.active_intent:
            return False
        if self.missing or self.pending_clarification:
            return True
        return bool(self.current_plan_id) and not self.task_complete

    def set_slot(self, name: str, value: Any, *, source: str, confirmed: bool) -> None:
        """写入或覆盖一个槽。"""

        self.slots[str(name)] = Slot(value=value, source=source, confirmed=confirmed)

    def append_messages(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """追加可见对话；尾部同 kind+text 跳过。最多 120 条。

        Parameters
        ----------
        rows : list of dict
            本轮消息。

        Returns
        -------
        list of dict
            追加后的 ``messages``。
        """

        seen = {(row.get("kind"), row.get("text")) for row in self.messages[-8:]}
        for raw in rows or []:
            item = normalize_message(raw)
            if item is None:
                continue
            if not str(item.get("text") or "") and item.get("kind") != "error":
                continue
            key = (item.get("kind"), item.get("text"))
            if key in seen:
                continue
            seen.add(key)
            self.messages.append(item)
        self.messages = self.messages[-120:]
        return list(self.messages)

    def rewind_from_user_index(self, message_index: int, *, discard: bool = False) -> Dict[str, Any]:
        """裁掉指定用户句之后的对话与 turns；不替换该句文本。

        Parameters
        ----------
        message_index : int
            ``messages`` 中目标 ``user_text`` 的下标。
        discard : bool, optional
            后缀含已执行 run 时须为 True，否则只报告需要确认。

        Returns
        -------
        dict
            ``ok`` / ``needs_confirm`` / ``executed_run_ids``。
        """

        idx = int(message_index)
        if idx < 0 or idx >= len(self.messages):
            return {"ok": False, "needs_confirm": False, "executed_run_ids": [], "error": "MESSAGE_INDEX_INVALID"}
        if str(self.messages[idx].get("kind") or "") != "user_text":
            return {"ok": False, "needs_confirm": False, "executed_run_ids": [], "error": "NOT_USER_MESSAGE"}
        suffix = self.messages[idx + 1 :]
        executed = []
        for row in suffix:
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            rid = str(payload.get("run_id") or "").strip()
            if rid and payload.get("executed"):
                executed.append(rid)
        if executed and not discard:
            return {"ok": False, "needs_confirm": True, "executed_run_ids": executed}
        user_before = sum(1 for row in self.messages[:idx] if row.get("kind") == "user_text")
        self.messages = list(self.messages[:idx])
        self.turns = list(self.turns[:user_before])
        self.current_plan_id = ""
        self.pending_clarification = None
        self.missing = []
        self.task_complete = False
        return {"ok": True, "needs_confirm": False, "executed_run_ids": executed}


class SessionStore:
    """读写 ``sessions/{session_id}.json``。"""

    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory_store = memory_store
        self.sessions_dir = memory_store.sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, session_id: str) -> Path:
        """会话文件路径。"""

        safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(session_id or "default"))
        return self.sessions_dir / f"{safe}.json"

    def load(self, session_id: str) -> ConversationState:
        """读取会话；缺文件或损坏则空状态。"""

        path = self.path_for(session_id)
        if not path.exists():
            return ConversationState.empty(session_id)
        try:
            with path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            backup = path.with_suffix(path.suffix + ".corrupt.json")
            try:
                if path.exists():
                    path.replace(backup)
            except OSError:
                pass
            print(
                f"[SessionStore] Warning: failed to read {path} ({exc}); "
                f"using empty session and moved corrupt file to {backup}."
            )
            return ConversationState.empty(session_id)
        return ConversationState.from_dict(raw, session_id=session_id)

    def save(self, state: ConversationState) -> str:
        """落盘会话并返回路径。"""

        path = self.path_for(state.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(_json_safe(state.to_dict()), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        tmp_path.replace(path)
        return str(path)

    def list_summaries(self) -> List[Dict[str, Any]]:
        """列举已落盘会话的摘要（不含完整 turns）。

        Parameters
        ----------
        无

        Returns
        -------
        list of dict
            每项含 ``session_id`` / ``title`` / ``job`` / ``mtime``。
        """

        rows: List[Dict[str, Any]] = []
        paths = [
            path
            for path in self.sessions_dir.glob("*.json")
            if ".corrupt" not in path.name and not path.name.endswith(".transcript.json")
        ]
        paths.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        for path in paths:
            sid = path.stem
            state = self.load(sid)
            title = str(state.original_query or "").strip()
            if not title and state.turns:
                last = state.turns[-1] if isinstance(state.turns[-1], dict) else {}
                title = str(last.get("query") or "").strip()
            if not title:
                title = sid
            job = ""
            if isinstance(state.active_intent, dict):
                job = str(state.active_intent.get("job") or "")
            rows.append(
                {
                    "session_id": sid,
                    "title": title[:80],
                    "job": job,
                    "mtime": path.stat().st_mtime,
                }
            )
        return rows
