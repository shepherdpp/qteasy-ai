# coding=utf-8
# ======================================
# File: session.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-05
# Desc:
# 多轮 ConversationState：messages[] + 单 Task 落盘。
# ======================================

"""闭合 Job 的多轮会话状态。

权威字段：``session_id`` / ``task`` / ``messages`` / ``attachments`` / ``agent_auto``
加可选用户标签 ``name``（不是 DTO 投影）。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .human_card import HUMAN_CARD_KINDS, SKIP_MESSAGE_KINDS, normalize_card_kind
from .memory_store import MemoryStore, _json_safe

SLOT_SOURCES = frozenset({"user", "profile", "env_facts", "default", "extracted"})
VISIBLE_MESSAGE_KINDS = HUMAN_CARD_KINDS
_SKIP_MESSAGE_KINDS = SKIP_MESSAGE_KINDS
TASK_STATUSES = frozenset({"clarifying", "ready", "running", "done", "cancelled"})
STATE_KEYS = frozenset({"session_id", "task", "messages", "attachments", "agent_auto", "name"})
_NAME_MAX = 80
STALE_RUNNING_NOTICE = "Execution interrupted. Confirm again to retry, or start a new topic."


@dataclass
class _LiveSnap:
    """进程内活执行快照：计时、步态、步内进度。不落盘。"""

    started_at: float
    steps: List[Dict[str, Any]] = field(default_factory=list)
    step_index: int = 0
    step_total: int = 0
    progress: Optional[Dict[str, Any]] = None


_LIVE_RUNNING: Dict[str, _LiveSnap] = {}
_LIVE_LOCK = threading.Lock()


def _normalize_live_steps(steps: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """plan 步清单 → 快照 steps（默认 pending）。"""

    out: List[Dict[str, Any]] = []
    for raw in steps or []:
        if isinstance(raw, dict):
            step_id = str(raw.get("step_id") or "")
            skill_name = str(raw.get("skill_name") or "")
            status = str(raw.get("status") or "pending") or "pending"
            ok = raw.get("ok")
        else:
            step_id = str(getattr(raw, "step_id", "") or "")
            skill_name = str(getattr(raw, "skill_name", "") or "")
            status = "pending"
            ok = None
        out.append(
            {
                "step_id": step_id,
                "skill_name": skill_name,
                "status": status,
                "ok": ok,
            }
        )
    return out


def register_live_running(
    session_id: str,
    steps: Optional[List[Any]] = None,
) -> None:
    """登记本进程正在执行的 session；首次记下 started_at，重复登记不覆盖。"""

    sid = str(session_id or "").strip()
    if not sid:
        return
    with _LIVE_LOCK:
        existing = _LIVE_RUNNING.get(sid)
        if existing is not None:
            if steps is not None:
                existing.steps = _normalize_live_steps(steps)
                existing.step_total = len(existing.steps)
            return
        snap = _LiveSnap(started_at=time.monotonic())
        if steps is not None:
            snap.steps = _normalize_live_steps(steps)
            snap.step_total = len(snap.steps)
        _LIVE_RUNNING[sid] = snap


def clear_live_running(session_id: str) -> None:
    """清除本进程活执行登记。"""

    with _LIVE_LOCK:
        _LIVE_RUNNING.pop(str(session_id or "").strip(), None)


def is_live_running(session_id: str) -> bool:
    """该 session 是否有进程内未结束的执行。"""

    return str(session_id or "").strip() in _LIVE_RUNNING


def live_elapsed_s(session_id: str) -> Optional[int]:
    """活执行已过秒数；未登记返回 None。"""

    snap = _LIVE_RUNNING.get(str(session_id or "").strip())
    if snap is None:
        return None
    return max(0, int(time.monotonic() - snap.started_at))


def live_snapshot(session_id: str) -> Optional[Dict[str, Any]]:
    """GET / heartbeat 用的活执行投影；未登记返回 None。"""

    sid = str(session_id or "").strip()
    with _LIVE_LOCK:
        snap = _LIVE_RUNNING.get(sid)
        if snap is None:
            return None
        out: Dict[str, Any] = {
            "elapsed_s": max(0, int(time.monotonic() - snap.started_at)),
            "step_index": snap.step_index,
            "step_total": snap.step_total,
            "steps": [dict(row) for row in snap.steps],
        }
        if snap.progress:
            out["progress"] = dict(snap.progress)
        return out


def mark_live_step_start(
    session_id: str,
    *,
    step_id: str,
    skill_name: str,
    index: int,
    total: int,
) -> None:
    """步开始：当前步 running，清掉上一步 progress。"""

    sid = str(session_id or "").strip()
    with _LIVE_LOCK:
        snap = _LIVE_RUNNING.get(sid)
        if snap is None:
            return
        snap.step_index = int(index)
        snap.step_total = int(total)
        snap.progress = None
        found = False
        for row in snap.steps:
            if str(row.get("step_id") or "") == str(step_id):
                row["status"] = "running"
                if skill_name:
                    row["skill_name"] = skill_name
                found = True
                break
        if not found:
            snap.steps.append(
                {
                    "step_id": str(step_id),
                    "skill_name": str(skill_name or ""),
                    "status": "running",
                    "ok": None,
                }
            )


def mark_live_step_end(
    session_id: str,
    *,
    step_id: str,
    status: str,
    ok: Any = None,
) -> None:
    """步结束：写入 done / error / skipped，清 progress。"""

    sid = str(session_id or "").strip()
    with _LIVE_LOCK:
        snap = _LIVE_RUNNING.get(sid)
        if snap is None:
            return
        snap.progress = None
        for row in snap.steps:
            if str(row.get("step_id") or "") == str(step_id):
                row["status"] = str(status or "done")
                row["ok"] = ok
                return
        snap.steps.append(
            {
                "step_id": str(step_id),
                "skill_name": "",
                "status": str(status or "done"),
                "ok": ok,
            }
        )


def mark_live_progress(
    session_id: str,
    *,
    done: int,
    total: int,
    label: str = "",
) -> None:
    """步内 tqdm 进度写入快照。"""

    sid = str(session_id or "").strip()
    with _LIVE_LOCK:
        snap = _LIVE_RUNNING.get(sid)
        if snap is None:
            return
        snap.progress = {
            "done": int(done),
            "total": int(total),
            "label": str(label or ""),
        }


def _new_task_id() -> str:
    """生成短 task id。"""

    return "task_" + uuid.uuid4().hex[:12]


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
    kind = normalize_card_kind(raw.get("kind"))
    if kind in _SKIP_MESSAGE_KINDS or not kind:
        return None
    if kind not in HUMAN_CARD_KINDS:
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
class Task:
    """当前闭合办事（1.0 同时最多一个）。"""

    id: str = ""
    user_query: str = ""
    job: str = ""
    flags: Dict[str, Any] = field(default_factory=dict)
    status: str = ""
    slots: Dict[str, Slot] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    pending_clarification: Optional[Dict[str, Any]] = None
    clarify_round: int = 0
    plan_id: str = ""
    revision: int = 0
    run_id: str = ""
    high_side_effect: bool = False

    def apply_slots(self, slots: Dict[str, Slot]) -> None:
        """覆盖全部槽。"""

        self.slots = dict(slots or {})

    def set_missing(self, names: List[str]) -> None:
        """写入 missing 并按副作用改 status。"""

        self.missing = [str(item) for item in (names or [])]
        if self.missing:
            if self.status not in {"running", "done", "cancelled"}:
                self.status = "clarifying"
        elif self.status == "clarifying" and not self.pending_clarification:
            if self.plan_id or self.job:
                self.status = "ready"

    def set_pending(self, value: Optional[Dict[str, Any]]) -> None:
        """写入待答澄清。"""

        self.pending_clarification = dict(value) if isinstance(value, dict) else None
        if self.pending_clarification or self.missing:
            if self.status not in {"running", "done", "cancelled"}:
                self.status = "clarifying"

    def cancel(self) -> None:
        """标为 cancelled 并清澄清。"""

        if self.status not in {"done", "cancelled"}:
            self.status = "cancelled"
        self.pending_clarification = None
        self.missing = []

    def mark_ready(self) -> None:
        """未终态则标 ready。"""

        if self.status not in {"running", "done", "cancelled"}:
            self.status = "ready"

    def mark_running(self) -> None:
        """标 running。"""

        self.status = "running"

    def mark_done(self) -> None:
        """未取消则标 done。"""

        if self.status != "cancelled":
            self.status = "done"

    def to_dict(self) -> Dict[str, Any]:
        """序列化 Task。"""

        status = str(self.status or "")
        if status not in TASK_STATUSES:
            status = ""
        return {
            "id": str(self.id or ""),
            "user_query": str(self.user_query or ""),
            "job": str(self.job or ""),
            "flags": dict(self.flags or {}),
            "status": status,
            "slots": {key: slot.to_dict() for key, slot in self.slots.items()},
            "missing": list(self.missing),
            "pending_clarification": dict(self.pending_clarification)
            if isinstance(self.pending_clarification, dict)
            else None,
            "clarify_round": int(self.clarify_round or 0),
            "plan_id": str(self.plan_id or ""),
            "revision": int(self.revision or 0),
            "run_id": str(self.run_id or ""),
            "high_side_effect": bool(self.high_side_effect),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> Optional["Task"]:
        """从字典恢复；非法则 None。"""

        if not isinstance(raw, dict) or not raw:
            return None
        slots_raw = raw.get("slots") if isinstance(raw.get("slots"), dict) else {}
        slots = {str(key): Slot.from_dict(value) for key, value in slots_raw.items()}
        pending = raw.get("pending_clarification")
        if not isinstance(pending, dict):
            pending = None
        status = str(raw.get("status") or "")
        if status not in TASK_STATUSES:
            status = ""
        flags = raw.get("flags") if isinstance(raw.get("flags"), dict) else {}
        return cls(
            id=str(raw.get("id") or "") or _new_task_id(),
            user_query=str(raw.get("user_query") or ""),
            job=str(raw.get("job") or ""),
            flags=dict(flags),
            status=status,
            slots=slots,
            missing=[str(item) for item in (raw.get("missing") or [])],
            pending_clarification=pending,
            clarify_round=int(raw.get("clarify_round") or 0),
            plan_id=str(raw.get("plan_id") or ""),
            revision=int(raw.get("revision") or 0),
            run_id=str(raw.get("run_id") or ""),
            high_side_effect=bool(raw.get("high_side_effect", False)),
        )


def _migrate_task_from_flat(data: Dict[str, Any]) -> Optional[Task]:
    """把旧扁平字段收成一个 Task。"""

    intent = data.get("active_intent") if isinstance(data.get("active_intent"), dict) else None
    job = str((intent or {}).get("job") or "")
    flags = dict((intent or {}).get("flags") or {}) if intent else {}
    slots_raw = data.get("slots") if isinstance(data.get("slots"), dict) else {}
    slots = {str(key): Slot.from_dict(value) for key, value in slots_raw.items()}
    pending = data.get("pending_clarification")
    if not isinstance(pending, dict):
        pending = None
    missing = [str(item) for item in (data.get("missing") or [])]
    plan_id = str(data.get("current_plan_id") or "")
    query = str(data.get("original_query") or "")
    complete = bool(data.get("task_complete", False))
    if not job and not plan_id and not pending and not slots and not query:
        return None
    if pending or missing:
        status = "clarifying"
    elif complete:
        status = "done"
    elif plan_id:
        status = "ready"
    elif job:
        status = "ready"
    else:
        status = ""
    return Task(
        id=_new_task_id(),
        user_query=query,
        job=job,
        flags=flags,
        status=status,
        slots=slots,
        missing=missing,
        pending_clarification=pending,
        clarify_round=int(data.get("clarify_round") or 0),
        plan_id=plan_id,
    )


def _user_texts(messages: List[Dict[str, Any]]) -> List[str]:
    """抽出 ``user_text`` 正文，保持时间顺序。"""

    out: List[str] = []
    for row in messages or []:
        if str(row.get("kind") or "") != "user_text":
            continue
        text = str(row.get("text") or "").strip()
        if text:
            out.append(text)
    return out


def clip_session_name(raw: Any) -> str:
    """规范化用户标签：去空白，最长 80。空串表示回退默认。"""

    return str(raw or "").strip()[:_NAME_MAX]


@dataclass
class ConversationState:
    """一次会话：日志 + 至多一个 Task。"""

    session_id: str
    task: Optional[Task] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    agent_auto: bool = False
    name: str = ""

    @classmethod
    def empty(cls, session_id: str) -> "ConversationState":
        """新建空会话。"""

        return cls(session_id=str(session_id or "").strip() or "default")

    def to_dict(self) -> Dict[str, Any]:
        """只写权威字段 + 可选 ``name``。"""

        return {
            "session_id": self.session_id,
            "task": self.task.to_dict() if self.task is not None else None,
            "messages": list(self.messages),
            "attachments": list(self.attachments),
            "agent_auto": bool(self.agent_auto),
            "name": clip_session_name(self.name),
        }

    @classmethod
    def from_dict(cls, raw: Any, *, session_id: str = "") -> "ConversationState":
        """从 JSON 恢复；忽略未知键；扁平旧字段降级为 task。"""

        data = raw if isinstance(raw, dict) else {}
        sid = str(data.get("session_id") or session_id or "").strip() or "default"
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
        task = Task.from_dict(data.get("task"))
        if task is None:
            task = _migrate_task_from_flat(data)
        elif task.clarify_round == 0:
            top = int(data.get("clarify_round") or 0)
            if top:
                task.clarify_round = top
        return cls(
            session_id=sid,
            task=task,
            messages=_coerce_messages(data.get("messages")),
            attachments=attachments,
            agent_auto=bool(data.get("agent_auto", False)),
            name=clip_session_name(data.get("name")),
        )

    def task_status(self) -> str:
        """当前 Task 状态；无 Task 为空串。"""

        if self.task is None:
            return ""
        return str(self.task.status or "")

    def task_incomplete(self) -> bool:
        """仅 clarifying 为未完成（PlanReady 不是 incomplete）。"""

        return self.task_status() == "clarifying"

    def set_slot(self, name: str, value: Any, *, source: str, confirmed: bool) -> None:
        """写入或覆盖一个槽；无 Task 则忽略。"""

        if self.task is None:
            return
        self.task.slots[str(name)] = Slot(value=value, source=source, confirmed=confirmed)

    def start_task(self, *, query: str, job: str = "", flags: Optional[Dict[str, Any]] = None) -> Task:
        """开一个新 Task。"""

        self.task = Task(
            id=_new_task_id(),
            user_query=str(query or ""),
            job=str(job or ""),
            flags=dict(flags or {}),
            status="ready",
        )
        return self.task

    def cancel_task(self) -> None:
        """将当前 Task 标为 cancelled。"""

        if self.task is None:
            return
        self.task.cancel()

    def heal_stale_running(self, *, live: bool = False) -> bool:
        """孤儿 ``running`` 降为 ``ready`` 并追加 notice；不续跑。"""

        if live or self.task is None or self.task.status != "running":
            return False
        self.task.status = "ready"
        self.append_messages(
            [
                {
                    "kind": "mode_notice",
                    "text": STALE_RUNNING_NOTICE,
                    "payload": {"reason": "stale_running"},
                }
            ]
        )
        return True

    def append_user_text(self, query: str) -> None:
        """Composer 原文写入 messages（控件路径不要调用）。"""

        text = str(query or "").strip()
        if not text:
            return
        self.append_messages([{"kind": "user_text", "text": text, "payload": {}}])

    @staticmethod
    def _message_dedupe_key(row: Dict[str, Any]) -> tuple:
        """去重键：同文案但不同 plan_id/run_id 视为不同条。"""

        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        return (
            row.get("kind"),
            row.get("text"),
            str(payload.get("plan_id") or ""),
            str(payload.get("run_id") or ""),
        )

    def append_messages(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """追加可见对话；尾部同 kind+text+plan/run 跳过。最多 120 条。

        Parameters
        ----------
        rows : list of dict
            本轮消息。

        Returns
        -------
        list of dict
            追加后的 ``messages``。
        """

        seen = {self._message_dedupe_key(row) for row in self.messages[-8:]}
        for raw in rows or []:
            item = normalize_message(raw)
            if item is None:
                continue
            if not str(item.get("text") or "") and item.get("kind") != "error":
                continue
            if str(item.get("kind") or "") == "plan_ready":
                pid = str((item.get("payload") or {}).get("plan_id") or "")
                replaced = False
                if pid:
                    for idx in range(len(self.messages) - 1, -1, -1):
                        row = self.messages[idx]
                        if str(row.get("kind") or "") != "plan_ready":
                            continue
                        old_pid = str((row.get("payload") or {}).get("plan_id") or "")
                        if old_pid == pid:
                            self.messages[idx] = item
                            replaced = True
                            break
                if replaced:
                    continue
            if item.get("kind") != "user_text":
                key = self._message_dedupe_key(item)
                if key in seen:
                    continue
                seen.add(key)
            self.messages.append(item)
        self.messages = self.messages[-120:]
        return list(self.messages)

    def close_open_card(self, answer: str, *, status: str = "answered") -> bool:
        """就地关闭最近一张未答开卡（优先 clarify，其次 plan_ready）。

        Parameters
        ----------
        answer : str
            本轮回执原文，写入 ``payload.answer``。
        status : str, optional
            ``answered`` 或 ``skipped``。

        Returns
        -------
        bool
            是否改写了一张卡。
        """

        text = str(answer or "").strip()
        mark = str(status or "answered").strip() or "answered"
        for kind in ("clarify", "plan_ready"):
            for row in reversed(self.messages):
                if str(row.get("kind") or "") != kind:
                    continue
                payload = dict(row.get("payload") or {}) if isinstance(row.get("payload"), dict) else {}
                if str(payload.get("status") or "") in {"answered", "skipped"}:
                    continue
                if text:
                    payload["answer"] = text
                payload["status"] = mark
                row["payload"] = payload
                return True
        return False

    def rewind_from_user_index(self, message_index: int, *, discard: bool = False) -> Dict[str, Any]:
        """裁掉指定用户句之后的对话；不替换该句文本。

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
        self.messages = list(self.messages[:idx])
        self.task = None
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

    def exists(self, session_id: str) -> bool:
        """落盘文件是否存在。"""

        return self.path_for(session_id).is_file()

    def delete(self, session_id: str) -> bool:
        """删除 session JSON 与旁路 transcript；不碰 ``runs/``。"""

        path = self.path_for(session_id)
        if not path.is_file():
            return False
        try:
            path.unlink()
        except OSError:
            return False
        transcript = path.with_name(f"{path.stem}.transcript.json")
        if transcript.is_file():
            try:
                transcript.unlink()
            except OSError:
                pass
        return True

    def summarize_one(self, state: ConversationState) -> Dict[str, Any]:
        """单条列表摘要（与 ``list_summaries`` 同行形状）。"""

        texts = _user_texts(state.messages)
        last_user = texts[-1][:_NAME_MAX] if texts else ""
        custom = clip_session_name(state.name)
        if custom:
            name = custom
        elif texts:
            name = texts[0][:_NAME_MAX]
        else:
            name = str(state.session_id or "")
        job = str(state.task.job or "") if state.task is not None else ""
        path = self.path_for(state.session_id)
        mtime = path.stat().st_mtime if path.is_file() else 0.0
        return {
            "session_id": str(state.session_id or ""),
            "name": name,
            "last_user": last_user,
            "title": name,
            "job": job,
            "mtime": mtime,
        }

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
        state = ConversationState.from_dict(raw, session_id=session_id)
        if state.heal_stale_running(live=is_live_running(session_id)):
            self.save(state)
        return state

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
        """列举已落盘会话的摘要。

        Parameters
        ----------
        无

        Returns
        -------
        list of dict
            每项含 ``session_id`` / ``name`` / ``last_user`` / ``title`` / ``job`` / ``mtime``。
        """

        rows: List[Dict[str, Any]] = []
        paths = [
            path
            for path in self.sessions_dir.glob("*.json")
            if ".corrupt" not in path.name and not path.name.endswith(".transcript.json")
        ]
        paths.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        for path in paths:
            rows.append(self.summarize_one(self.load(path.stem)))
        return rows
