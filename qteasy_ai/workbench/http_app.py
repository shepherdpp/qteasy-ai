# coding=utf-8
# ======================================
# File: http_app.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-07
# Desc:
# 薄 Starlette 适配层：只调用 QteasyAssistant。
# ======================================

"""工作台 HTTP 适配层。禁止在路由中调用 Planner.build_plan。"""

from __future__ import annotations

import json
import os
import queue
import signal
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional
from urllib.parse import unquote

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ..config import ensure_mplbackend_agg
from ..app import QteasyAssistant
from ..contracts import PlanStepRecord
from ..memory_store import MemoryStore, _json_safe
from ..session import (
    BACKGROUND_RUN_NOTICE,
    CANCEL_RUN_NOTICE,
    SessionStore,
    is_live_backgrounded,
    is_live_running,
    live_elapsed_s,
    live_task_id,
    live_snapshot,
    mark_live_background,
    note_cancelled_task,
    request_live_cancel,
)
from ..plan_markdown import plan_artifact_title, run_group_title
from .mapper import classify_artifacts, map_assistant_payload

STATIC_DIR = Path(__file__).resolve().parent / "static"

_NEXT_ACTION = {
    "QUERY_REQUIRED": "Type a question in the composer, then press Ctrl+Enter to send.",
    "PLAN_ID_REQUIRED": "Confirm a plan from this session, or send a new Plan request.",
    "PLAN_ID_NOT_FOUND": "Create a plan first, then press Confirm. The plan_id lives in runs/, not as a filename.",
    "SESSION_ID_REQUIRED": "Select a session from the left rail, or click New.",
    "SESSION_NOT_FOUND": "That session is gone. Pick another from the left rail, or click New.",
    "PATH_REQUIRED": "Pick an artifact in Workspace, or a strategy file to preview.",
    "FILE_NOT_FOUND": "Choose a file inside the memory root, or an artifact from this session.",
    "FILE_NOT_TEXT": "Only text workspace files can be previewed. Export binaries from Artifacts.",
    "FILE_TOO_LARGE": "Pick a smaller file, or open it on disk under the memory root.",
    "RUN_NOT_FOUND": "Confirm a plan to create a run, then open it from this session's artifacts.",
    "ARTIFACT_NOT_FOUND": "Export only files that belong to this run_id.",
    "RUN_FAILED": "Edit the blue message (pencil) and send it again.",
    "MESSAGE_INDEX_INVALID": "Pick a user message in this session, then press Edit.",
    "NOT_USER_MESSAGE": "Only user messages can be edited. Pick a You bubble.",
    "REWIND_DISCARD_REQUIRED": "Editing this message discards later executed runs. Confirm to continue.",
    "PROVIDER_CONFIRM_REQUIRED": "Review the new provider settings, then press Confirm.",
    "PROVIDER_BUILTIN_LOCKED": "Mode-R stays in the list. Add another provider, or switch to one.",
    "PROVIDER_FIELDS_REQUIRED": "Enter a name and a model, then press Confirm.",
    "PROVIDER_NOT_FOUND": "Pick a provider from the list, or add one in Settings.",
    "CONFIRM_REQUIRED": "Set confirm=true after reviewing the note, then retry the write.",
    "KB_WRITE_NOT_PENDING": "Lock the FactorSpec first (save this note), then confirm the write.",
    "RUN_IN_PROGRESS": "Wait for the current run to finish, or open that session and watch it.",
    "QUIT_DISABLED": "Quit is available from Settings when this page was opened with qteasy-ai serve.",
    "QUIT_CONFIRM_REQUIRED": "Confirm quit in the dialog, then try again.",
}


def request_process_stop() -> None:
    """在响应发出后对本进程发 SIGINT，让 ``uvicorn.run`` 按 Ctrl+C 退出。"""

    threading.Timer(0.25, lambda: os.kill(os.getpid(), signal.SIGINT)).start()


def _error(code: str, message: str, status: int) -> JSONResponse:
    """英文错误 JSON，含可行动 next_action。"""

    return JSONResponse(
        {
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "next_action": _NEXT_ACTION.get(
                    code, "Fix the issue above, then retry. You do not need to start over."
                ),
            },
        },
        status_code=status,
    )


def _provider_timeout(value: Any) -> Optional[int]:
    """把请求里的 timeout 收成整数；空值表示不改。"""

    if value in (None, ""):
        return None
    return int(value)


def _wants_stream(request: Request) -> bool:
    """Accept: text/event-stream 或 ?stream=1 时走 SSE。

    Parameters
    ----------
    request : Request
        当前 HTTP 请求。

    Returns
    -------
    bool
        是否以 SSE 流式返回。
    """

    flag = str(request.query_params.get("stream") or "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    accept = (request.headers.get("accept") or "").lower()
    return "text/event-stream" in accept


def _sse_error_payload(exc: BaseException) -> Dict[str, Any]:
    """SSE ``error`` 事件体。序列化或装配失败时用，避免生成器裸抛。"""

    return {
        "ok": False,
        "error": {
            "code": "RUN_FAILED",
            "message": str(exc) or "Run failed.",
            "next_action": _NEXT_ACTION["RUN_FAILED"],
        },
    }


def _sse_line(event: str, data: Any) -> str:
    """一条 SSE 记录。写出前走 ``_json_safe``，非有限浮点变成 null。

    Parameters
    ----------
    event : str
        事件名。
    data : Any
        事件载荷。非 JSON 原生类型会先规范化。

    Returns
    -------
    str
        SSE 文本块。
    """

    return f"event: {event}\ndata: {json.dumps(_json_safe(data), ensure_ascii=False)}\n\n"


class WorkbenchHttp:
    """绑定一个 Assistant 的路由集合。"""

    def __init__(self, assistant: QteasyAssistant) -> None:
        self.assistant = assistant
        self.events: Dict[str, List[Dict[str, Any]]] = {}

    def _record_step(self, run_bucket: List[Dict[str, Any]], record: PlanStepRecord) -> None:
        """on_step：写入 SSE 缓存。"""

        run_bucket.append(
            {
                "step_id": record.step_id,
                "skill_name": record.skill_name,
                "ok": (record.result or {}).get("ok"),
                "status": "done" if (record.result or {}).get("ok") else "error",
            }
        )

    def _to_dto(
        self,
        payload: Dict[str, Any],
        *,
        query: str = "",
        session_id: str = "",
        persist_transcript: bool = False,
    ) -> Dict[str, Any]:
        """raw payload → WorkbenchState JSON。transcript 只读装配层已写的卡，不再现场拼句。"""

        del persist_transcript
        session = None
        sid = str(session_id or "").strip()
        if sid:
            session = SessionStore(self.assistant.memory_store).load(sid)
        env = self.assistant.memory_store.load_env_facts()
        state = map_assistant_payload(payload, session=session, query=query, env_facts=env)
        dumped = state.to_dict()
        dumped["ok"] = dumped.get("error") is None
        extra = list(dumped.get("messages") or [])
        run_status = str((dumped.get("execution") or {}).get("status") or "")
        run_id = str(dumped.get("run_id") or "")
        if run_id:
            for item in extra:
                if not isinstance(item, dict):
                    continue
                if str(item.get("kind") or "") == "user_text":
                    continue
                payload_row = dict(item.get("payload") or {}) if isinstance(item.get("payload"), dict) else {}
                payload_row["run_id"] = run_id
                if run_status and run_status not in {"", "dry_run"}:
                    payload_row["executed"] = True
                arts = dumped.get("artifacts") or []
                if arts:
                    payload_row["artifact_refs"] = [
                        {
                            "type": str(art.get("type") or ""),
                            "run_id": str(art.get("run_id") or run_id),
                            "title": str(art.get("title") or ""),
                        }
                        for art in arts
                        if isinstance(art, dict)
                    ][:12]
                item["payload"] = payload_row
        if sid:
            conv = SessionStore(self.assistant.memory_store).load(sid)
            dumped["transcript"] = list(conv.messages)
            dumped["artifacts"] = self._artifacts_for_session(conv)
        else:
            dumped["transcript"] = []
        return self._overlay_live_running(dumped, sid)

    def _overlay_live_running(self, dumped: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        """进程内仍在执行时投影 running / elapsed / 步态。

        前台关掉 Confirm。后台只关掉属于当前 live 任务的那张计划卡；
        后发的另一张计划保持自己的 confirmable。
        """

        sid = str(session_id or "").strip()
        snap = live_snapshot(sid) if sid else None
        if snap is None:
            return dumped
        execution = dict(dumped.get("execution") or {})
        execution["status"] = "running"
        execution["elapsed_s"] = snap["elapsed_s"]
        execution["backgrounded"] = bool(snap.get("backgrounded"))
        execution["blocks_composer"] = bool(snap.get("blocks_composer", True))
        if snap.get("step_index"):
            execution["step_index"] = snap["step_index"]
            execution["step_total"] = snap["step_total"]
        if snap.get("steps"):
            execution["steps"] = snap["steps"]
        if snap.get("progress"):
            execution["progress"] = snap["progress"]
        dumped["execution"] = execution
        card = dumped.get("plan_card")
        hide_confirm = bool(execution.get("blocks_composer", True))
        live_task = str(snap.get("task_id") or "")
        if not hide_confirm and live_task:
            conv = SessionStore(self.assistant.memory_store).load(sid)
            task = conv.task
            if task is not None and str(task.id or "") == live_task:
                hide_confirm = True
        if isinstance(card, dict) and hide_confirm:
            card = dict(card)
            card["confirmable"] = False
            dumped["plan_card"] = card
        return dumped

    def _artifacts_for_session(self, conv: Any) -> List[Dict[str, Any]]:
        """按 messages 中的 run_id 收集本 Session 产物。

        某个 run 自身是 dry-run 且 ``{run_id}.plan.md`` 在盘上则列入 ``type=plan``。
        不因最新 execute 为 success/running 而扣掉已落盘的审阅文档；
        success/running 的 execute run 没有 plan.md，不会另造 plan 项。
        每项带 run 文件 ``mtime`` 与 ``run_title``（第一步人话 + 短 hex），供树排序，不改点击目标。
        """

        sid = str(getattr(conv, "session_id", "") or "")
        ordered: List[str] = []
        seen = set()
        for row in list(getattr(conv, "messages", None) or []):
            payload = row.get("payload") if isinstance(row, dict) and isinstance(row.get("payload"), dict) else {}
            rid = str(payload.get("run_id") or "").strip()
            if rid and rid not in seen:
                seen.add(rid)
                ordered.append(rid)
        items: List[Dict[str, Any]] = []
        for rid in ordered:
            run = self.assistant.memory_store.load_run(rid)
            steps = []
            if isinstance(run.get("execution"), dict):
                steps = list(run["execution"].get("steps") or [])
            plan_blob = run.get("plan") if isinstance(run.get("plan"), dict) else {}
            title_steps = steps or list(plan_blob.get("steps") or [])
            run_title = run_group_title(rid, title_steps)
            run_path = self.assistant.memory_store.runs_dir / f"{rid}.json"
            try:
                mtime = float(run_path.stat().st_mtime) if run_path.is_file() else 0.0
            except OSError:
                mtime = 0.0
            for art in classify_artifacts(rid, steps):
                art["session_id"] = sid
                art["mtime"] = mtime
                art["run_title"] = run_title
                items.append(art)
            status = str((run.get("execution") or {}).get("status") or "")
            md_path = self.assistant.memory_store.runs_dir / f"{rid}.plan.md"
            if status == "dry_run" and md_path.is_file():
                markdown = ""
                try:
                    markdown = md_path.read_text(encoding="utf-8")[:200000]
                except OSError:
                    markdown = ""
                items.append(
                    {
                        "type": "plan",
                        "run_id": rid,
                        "title": plan_artifact_title(
                            str(plan_blob.get("plan_id") or ""),
                            plan_blob.get("steps") or [],
                        ),
                        "export_path": str(md_path),
                        "preview": {"markdown": markdown, "path": str(md_path)},
                        "warnings": [],
                        "session_id": sid,
                        "mtime": mtime,
                        "run_title": run_title,
                    }
                )
        return items

    def _stream_execute(
        self,
        runner: Callable[[Any], Dict[str, Any]],
        *,
        query: str = "",
        session_id: str = "",
    ) -> Iterator[str]:
        """在线程中执行 runner，按 on_step 推 SSE；空闲 ≥2s 推 heartbeat，最后推 state。

        Parameters
        ----------
        runner : callable
            接收 on_step，返回 raw payload。
        query : str, optional
            写入 DTO 的用户句。
        session_id : str, optional
            侧栏会话。

        Returns
        -------
        iterator of str
            SSE 文本块。
        """

        bucket: List[Dict[str, Any]] = []
        q: "queue.Queue[Any]" = queue.Queue()
        box: Dict[str, Any] = {}
        started = time.monotonic()

        def on_step(record: PlanStepRecord) -> None:
            self._record_step(bucket, record)
            q.put(("step", dict(bucket[-1])))

        def on_step_start(step_id: str, skill_name: str, index: int, total: int) -> None:
            q.put(
                (
                    "step",
                    {
                        "step_id": step_id,
                        "skill_name": skill_name,
                        "status": "running",
                        "index": int(index),
                        "total": int(total),
                    },
                )
            )

        def on_progress(done: int, total: int, label: str = "") -> None:
            q.put(
                (
                    "progress",
                    {
                        "done": int(done),
                        "total": int(total),
                        "label": str(label or ""),
                    },
                )
            )

        def worker() -> None:
            try:
                try:
                    box["payload"] = runner(
                        on_step,
                        on_step_start=on_step_start,
                        on_progress=on_progress,
                    )
                except TypeError:
                    box["payload"] = runner(on_step)
            except Exception as exc:
                box["exc"] = exc
            q.put(("end", None))

        threading.Thread(target=worker, daemon=True).start()
        while True:
            try:
                kind, data = q.get(timeout=2.0)
            except queue.Empty:
                elapsed = live_elapsed_s(session_id)
                if elapsed is None:
                    elapsed = int(time.monotonic() - started)
                yield _sse_line("heartbeat", {"elapsed_s": elapsed})
                continue
            if kind == "step":
                yield _sse_line("step_status", data)
            elif kind == "progress":
                yield _sse_line("progress", data)
            else:
                break
        exc = box.get("exc")
        if isinstance(exc, ValueError):
            yield _sse_line(
                "error",
                {
                    "ok": False,
                    "error": {
                        "code": "PLAN_ID_NOT_FOUND",
                        "message": str(exc),
                        "next_action": _NEXT_ACTION["PLAN_ID_NOT_FOUND"],
                    },
                },
            )
            return
        if exc is not None:
            yield _sse_line(
                "error",
                {
                    "ok": False,
                    "error": {
                        "code": "RUN_FAILED",
                        "message": str(exc) or "Run failed.",
                        "next_action": _NEXT_ACTION["RUN_FAILED"],
                    },
                },
            )
            return
        try:
            dto = self._to_dto(
                box.get("payload") or {},
                query=query,
                session_id=session_id,
                persist_transcript=True,
            )
            run_id = str(dto.get("run_id") or "")
            if run_id:
                self.events[run_id] = list(bucket)
            line = _sse_line("state", dto)
        except Exception as exc:
            yield _sse_line("error", _sse_error_payload(exc))
            return
        yield line

    def _sse_response(self, iterator: Iterator[str]) -> StreamingResponse:
        """SSE 响应头。

        Parameters
        ----------
        iterator : iterator of str
            ``_stream_execute`` 产出。

        Returns
        -------
        StreamingResponse
            ``text/event-stream``。
        """

        return StreamingResponse(
            iterator,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def _read_json(self, request: Request) -> Dict[str, Any]:
        """解析 JSON 体。"""

        try:
            body = await request.json()
        except Exception:
            return {}
        return body if isinstance(body, dict) else {}

    async def ask(self, request: Request) -> JSONResponse:
        """POST /v1/ask。"""

        body = await self._read_json(request)
        query = str(body.get("query") or "").strip()
        if not query:
            return _error("QUERY_REQUIRED", "Provide a query.", 400)
        session_id = str(body.get("session_id") or "").strip()
        depth = str(body.get("depth") or "standard")
        payload = self.assistant.ask(
            query,
            response_style="raw",
            explanation_depth=depth,
            session_id=session_id or None,
        )
        return JSONResponse(
            self._to_dto(payload, query=query, session_id=session_id, persist_transcript=True)
        )

    async def plan(self, request: Request) -> JSONResponse:
        """POST /v1/plan。"""

        body = await self._read_json(request)
        query = str(body.get("query") or "").strip()
        raw_patches = body.get("patches") if isinstance(body.get("patches"), dict) else {}
        patches = {
            str(key).strip(): value
            for key, value in raw_patches.items()
            if str(key).strip() and value not in (None, "")
        }
        skip = bool(body.get("skip"))
        session_id = str(body.get("session_id") or "").strip()
        if skip:
            if not session_id:
                return _error("SESSION_ID_REQUIRED", "Provide a session_id with skip.", 400)
            payload = self.assistant.plan(
                query,
                response_style="raw",
                session_id=session_id,
                skip=True,
            )
            return JSONResponse(
                self._to_dto(payload, query=query, session_id=session_id, persist_transcript=True)
            )
        if not query and not patches:
            return _error("QUERY_REQUIRED", "Provide a query.", 400)
        if patches and not session_id:
            return _error("SESSION_ID_REQUIRED", "Provide a session_id with patches.", 400)
        payload = self.assistant.plan(
            query,
            response_style="raw",
            session_id=session_id or None,
            patches=patches or None,
        )
        return JSONResponse(
            self._to_dto(payload, query=query, session_id=session_id, persist_transcript=True)
        )

    async def run(self, request: Request) -> Response:
        """POST /v1/run（显式 Agent 入口）。默认 JSON；可选 SSE。"""

        body = await self._read_json(request)
        query = str(body.get("query") or "").strip()
        if not query:
            return _error("QUERY_REQUIRED", "Provide a query.", 400)
        session_id = str(body.get("session_id") or "").strip()
        agent_auto = body.get("agent_auto")

        def runner(on_step: Any, on_step_start: Any = None, on_progress: Any = None) -> Dict[str, Any]:
            return self.assistant.run(
                query,
                response_style="raw",
                session_id=session_id or None,
                agent_auto=bool(agent_auto) if agent_auto is not None else None,
                on_step=on_step,
                on_step_start=on_step_start,
                on_progress=on_progress,
            )

        if _wants_stream(request):
            return self._sse_response(
                self._stream_execute(runner, query=query, session_id=session_id)
            )
        bucket: List[Dict[str, Any]] = []

        def on_step(record: PlanStepRecord) -> None:
            self._record_step(bucket, record)

        payload = runner(on_step)
        dto = self._to_dto(payload, query=query, session_id=session_id, persist_transcript=True)
        run_id = str(dto.get("run_id") or "")
        if run_id:
            self.events[run_id] = list(bucket)
        return JSONResponse(dto)

    async def run_plan(self, request: Request) -> Response:
        """POST /v1/run-plan：按已审阅 plan_id 执行，禁止重新 Hybrid。默认 JSON。"""

        body = await self._read_json(request)
        plan_id = str(body.get("plan_id") or "").strip()
        if not plan_id:
            return _error(
                "PLAN_ID_REQUIRED",
                "Provide plan_id. Missing plan_id is not executed as a new query.",
                400,
            )
        session_id = str(body.get("session_id") or "").strip()
        if session_id and is_live_running(session_id) and not is_live_backgrounded(session_id):
            return _error(
                "RUN_IN_PROGRESS",
                "A run is already in progress for this session.",
                409,
            )

        def runner(on_step: Any, on_step_start: Any = None, on_progress: Any = None) -> Dict[str, Any]:
            return self.assistant.run_plan(
                plan_id,
                response_style="raw",
                session_id=session_id or None,
                on_step=on_step,
                on_step_start=on_step_start,
                on_progress=on_progress,
            )

        if _wants_stream(request):
            return self._sse_response(
                self._stream_execute(runner, query="", session_id=session_id)
            )
        bucket: List[Dict[str, Any]] = []

        def on_step(record: PlanStepRecord) -> None:
            self._record_step(bucket, record)

        try:
            payload = runner(on_step)
        except ValueError as exc:
            return _error("PLAN_ID_NOT_FOUND", str(exc), 404)
        dto = self._to_dto(payload, query="", session_id=session_id, persist_transcript=True)
        run_id = str(dto.get("run_id") or "")
        if run_id:
            self.events[run_id] = list(bucket)
        return JSONResponse(dto)

    async def kb_write(self, request: Request) -> JSONResponse:
        """POST /v1/kb/write：须 confirm=true。"""

        body = await self._read_json(request)
        session_id = str(body.get("session_id") or "").strip()
        if not session_id:
            return _error("SESSION_ID_REQUIRED", "Provide session_id.", 400)
        if not bool(body.get("confirm")):
            return _error("CONFIRM_REQUIRED", "KB write requires confirm=true.", 400)
        try:
            payload = self.assistant.confirm_kb_write(
                session_id, confirm=True, response_style="raw"
            )
        except ValueError as exc:
            return _error("KB_WRITE_NOT_PENDING", str(exc), 400)
        return JSONResponse(
            self._to_dto(payload, query="confirm kb write", session_id=session_id, persist_transcript=True)
        )

    async def get_session(self, request: Request) -> JSONResponse:
        """GET /v1/session/{session_id}：有 current_plan_id 则按 plan_id 回填 DTO。"""

        session_id = str(request.path_params.get("session_id") or "").strip()
        if not session_id:
            return _error("SESSION_ID_REQUIRED", "Provide a session_id.", 400)
        conv = SessionStore(self.assistant.memory_store).load(session_id)
        env = self.assistant.memory_store.load_env_facts()
        plan_id = str(conv.task.plan_id or "") if conv.task is not None else ""
        pending = conv.task.pending_clarification if conv.task is not None else None
        payload: Dict[str, Any] = {
            "mode": "plan",
            "plan": {"plan_id": plan_id, "steps": []},
            "execution": {"status": "", "steps": []},
        }
        if plan_id:
            found = self.assistant.memory_store.find_run_by_plan_id(plan_id)
            if found:
                payload = dict(found)
        if pending and not payload.get("clarification"):
            payload = dict(payload)
            payload["clarification"] = dict(pending)
        mapped = map_assistant_payload(payload, session=conv, env_facts=env)
        dumped = mapped.to_dict()
        dumped["ok"] = True
        if not conv.messages:
            hist = self.assistant.memory_store.load_ui_transcript(session_id)
            if hist:
                conv.append_messages(hist)
                SessionStore(self.assistant.memory_store).save(conv)
        dumped["transcript"] = list(conv.messages)
        dumped["artifacts"] = self._artifacts_for_session(conv)
        for row in reversed(conv.messages):
            kind = str(row.get("kind") or "")
            if kind == "ask":
                dumped["mode"] = "ask"
                break
            if kind in {"plan_ready", "result", "clarify", "executing", "error"}:
                break
        return JSONResponse(self._overlay_live_running(dumped, session_id))

    async def patch_session(self, request: Request) -> JSONResponse:
        """PATCH /v1/session/{session_id}：改用户标签 ``name``。"""

        session_id = str(request.path_params.get("session_id") or "").strip()
        if not session_id:
            return _error("SESSION_ID_REQUIRED", "Provide a session_id.", 400)
        store = SessionStore(self.assistant.memory_store)
        if not store.exists(session_id):
            return _error("SESSION_NOT_FOUND", "Session not found.", 404)
        body = await self._read_json(request)
        conv = store.load(session_id)
        conv.name = str(body.get("name") or "")
        store.save(conv)
        row = store.summarize_one(conv)
        row["ok"] = True
        return JSONResponse(row)

    async def delete_session(self, request: Request) -> JSONResponse:
        """DELETE /v1/session/{session_id}：只删 session 文件。"""

        session_id = str(request.path_params.get("session_id") or "").strip()
        if not session_id:
            return _error("SESSION_ID_REQUIRED", "Provide a session_id.", 400)
        store = SessionStore(self.assistant.memory_store)
        if not store.delete(session_id):
            return _error("SESSION_NOT_FOUND", "Session not found.", 404)
        return JSONResponse({"ok": True, "session_id": session_id})

    async def cancel_run(self, request: Request) -> JSONResponse:
        """POST /v1/session/{session_id}/cancel-run：确认后的 Stop。"""

        session_id = str(request.path_params.get("session_id") or "").strip()
        if not session_id:
            return _error("SESSION_ID_REQUIRED", "Provide a session_id.", 400)
        store = SessionStore(self.assistant.memory_store)
        if not store.exists(session_id):
            return _error("SESSION_NOT_FOUND", "Session not found.", 404)
        conv = store.load(session_id)
        task_id = live_task_id(session_id)
        stopped = bool(task_id)
        if conv.task is not None and conv.task.status == "running" and (not task_id or conv.task.id == task_id):
            note_cancelled_task(conv.task.id)
            conv.cancel_task()
            stopped = True
        request_live_cancel(session_id)
        if stopped:
            conv.append_messages(
                [
                    {
                        "kind": "mode_notice",
                        "text": CANCEL_RUN_NOTICE,
                        "payload": {"reason": "run_cancelled", "task_id": task_id},
                    }
                ]
            )
            store.save(conv)
        return await self.get_session(request)

    async def background_run(self, request: Request) -> JSONResponse:
        """POST /v1/session/{session_id}/background-run：进度留下，Composer 解锁。"""

        session_id = str(request.path_params.get("session_id") or "").strip()
        if not session_id:
            return _error("SESSION_ID_REQUIRED", "Provide a session_id.", 400)
        store = SessionStore(self.assistant.memory_store)
        if not store.exists(session_id):
            return _error("SESSION_NOT_FOUND", "Session not found.", 404)
        if not mark_live_background(session_id):
            return _error(
                "RUN_NOT_IN_PROGRESS",
                "No run is in progress for this session.",
                409,
            )
        conv = store.load(session_id)
        conv.append_messages(
            [
                {
                    "kind": "mode_notice",
                    "text": BACKGROUND_RUN_NOTICE,
                    "payload": {"reason": "background_run"},
                }
            ]
        )
        store.save(conv)
        return await self.get_session(request)

    async def list_sessions(self, request: Request) -> JSONResponse:
        """GET /v1/sessions：只读列举已落盘会话。"""

        del request
        store = SessionStore(self.assistant.memory_store)
        rows = store.list_summaries()
        for row in rows:
            if isinstance(row, dict):
                row["running"] = is_live_running(str(row.get("session_id") or ""))
        return JSONResponse({"ok": True, "sessions": rows})

    async def rewind_session(self, request: Request) -> JSONResponse:
        """POST /v1/session/{session_id}/rewind：裁掉某条用户句之后的历史并重发。"""

        session_id = str(request.path_params.get("session_id") or "").strip()
        if not session_id:
            return _error("SESSION_ID_REQUIRED", "Provide a session_id.", 400)
        body = await self._read_json(request)
        try:
            message_index = int(body.get("message_index"))
        except (TypeError, ValueError):
            return _error("MESSAGE_INDEX_INVALID", "Provide message_index of a user message.", 400)
        query = str(body.get("query") or "").strip()
        if not query:
            return _error("QUERY_REQUIRED", "Provide the rewritten query.", 400)
        discard = bool(body.get("confirm_discard") or body.get("discard"))
        mode = str(body.get("mode") or "plan").strip().lower()
        if mode not in {"ask", "plan", "agent", "run"}:
            mode = "plan"
        store = SessionStore(self.assistant.memory_store)
        conv = store.load(session_id)
        result = conv.rewind_from_user_index(message_index, discard=discard)
        if result.get("needs_confirm"):
            return JSONResponse(
                {
                    "ok": False,
                    "error": {
                        "code": "REWIND_DISCARD_REQUIRED",
                        "message": "Editing this message discards later executed runs.",
                        "next_action": _NEXT_ACTION["REWIND_DISCARD_REQUIRED"],
                    },
                    "needs_confirm": True,
                    "executed_run_ids": result.get("executed_run_ids") or [],
                },
                status_code=409,
            )
        if not result.get("ok"):
            code = str(result.get("error") or "MESSAGE_INDEX_INVALID")
            return _error(code, "Cannot rewind to that message.", 400)
        store.save(conv)
        if mode == "ask":
            payload = self.assistant.ask(
                query, response_style="raw", session_id=session_id
            )
        elif mode in {"agent", "run"}:
            payload = self.assistant.run(query, response_style="raw", session_id=session_id)
        else:
            payload = self.assistant.plan(query, response_style="raw", session_id=session_id)
        return JSONResponse(
            self._to_dto(payload, query=query, session_id=session_id, persist_transcript=True)
        )

    async def shutdown_server(self, request: Request) -> JSONResponse:
        """POST /v1/server/shutdown：确认后停止 ``qteasy-ai serve``。"""

        if not getattr(request.app.state, "allow_quit", False):
            return _error("QUIT_DISABLED", "Quit is only available on qteasy-ai serve.", 403)
        body = await self._read_json(request)
        if body.get("confirm") is not True:
            return _error("QUIT_CONFIRM_REQUIRED", "Confirm quit before stopping the server.", 400)
        request_process_stop()
        return JSONResponse({"ok": True, "message": "Workbench server is stopping."})

    async def get_provider(self, request: Request) -> JSONResponse:
        """GET /v1/provider：当前项诊断与池列表，不含 raw api_key。"""

        del request
        return JSONResponse(self._provider_dto())

    async def post_provider(self, request: Request) -> JSONResponse:
        """POST /v1/provider：确认后增删改，或直接切换当前项。"""

        body = await self._read_json(request)
        action = str(body.get("action") or "").strip()
        confirmed = bool(body.get("confirmed") or body.get("confirm"))
        if action in {"add", "update", "remove"} and not confirmed:
            return _error(
                "PROVIDER_CONFIRM_REQUIRED",
                "Changing provider requires confirm.",
                400,
            )
        store = self.assistant.memory_store
        if action == "add":
            result = store.add_provider(
                name=str(body.get("name") or ""),
                model=str(body.get("model") or ""),
                base_url=str(body.get("base_url") or ""),
                api_key=str(body.get("api_key") or ""),
                timeout=_provider_timeout(body.get("timeout")),
            )
        elif action == "update":
            result = store.update_provider(
                str(body.get("id") or ""),
                name=body.get("name") if "name" in body else None,
                model=body.get("model") if "model" in body else None,
                base_url=body.get("base_url") if "base_url" in body else None,
                api_key=body.get("api_key") if "api_key" in body else None,
                timeout=_provider_timeout(body.get("timeout")) if "timeout" in body else None,
            )
        elif action == "remove":
            result = store.remove_provider(str(body.get("id") or ""))
        elif action == "use":
            result = store.use_provider(str(body.get("id") or ""))
        else:
            return _error(
                "PROVIDER_FIELDS_REQUIRED",
                "Name and model are required.",
                400,
            )
        if not result.get("ok"):
            code = str(result.get("error") or "PROVIDER_NOT_FOUND")
            status = 404 if code == "PROVIDER_NOT_FOUND" else 400
            return _error(code, str(result.get("message") or "Provider update failed."), status)
        self.assistant.apply_provider(store.build_active_provider())
        dto = self._provider_dto()
        if action == "add" and result.get("id"):
            dto["id"] = result["id"]
        return JSONResponse(dto)

    def _provider_dto(self) -> Dict[str, Any]:
        """当前项诊断。请求本身成功时 ok 为真，configured 表示是否有模型。"""

        body = self.assistant.memory_store.active_diagnostics()
        body["configured"] = bool(body.get("configured"))
        body["ok"] = True
        body.pop("api_key", None)
        return body

    async def get_workspace(self, request: Request) -> JSONResponse:
        """GET /v1/workspace：本 Session 产物索引。"""

        session_id = str(request.query_params.get("session_id") or "").strip()
        if not session_id:
            return JSONResponse({"ok": True, "session_id": "", "artifacts": []})
        conv = SessionStore(self.assistant.memory_store).load(session_id)
        artifacts = self._artifacts_for_session(conv)
        return JSONResponse(
            {
                "ok": True,
                "session_id": session_id,
                "artifacts": artifacts,
            }
        )

    async def get_workspace_file(self, request: Request) -> JSONResponse:
        """GET /v1/workspace/file?path=：读取 base_dir 内文本文件。"""

        rel = unquote(str(request.query_params.get("path") or "")).strip()
        if not rel:
            return _error("PATH_REQUIRED", "Provide path query parameter.", 400)
        target = self.assistant.memory_store.resolve_under_base(rel)
        if target is None or not target.is_file():
            return _error("FILE_NOT_FOUND", "Workspace file is not under the memory root.", 404)
        suffix = target.suffix.lower()
        if suffix not in {".py", ".json", ".md", ".txt", ".csv", ".yml", ".yaml", ".log"}:
            return _error("FILE_NOT_TEXT", "Only text workspace files can be previewed.", 415)
        try:
            if target.stat().st_size > 512 * 1024:
                return _error("FILE_TOO_LARGE", "Workspace file exceeds 512 KB preview limit.", 413)
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return _error("FILE_NOT_FOUND", "Workspace file cannot be read as text.", 404)
        return JSONResponse({"ok": True, "path": rel, "name": target.name, "content": content})

    async def get_run(self, request: Request) -> JSONResponse:
        """GET /v1/runs/{run_id}。"""

        run_id = str(request.path_params.get("run_id") or "").strip()
        payload = self.assistant.memory_store.load_run(run_id)
        if not payload:
            return _error("RUN_NOT_FOUND", f"Run not found: {run_id}.", 404)
        return JSONResponse(self._to_dto(payload, query=""))

    async def get_events(self, request: Request) -> Response:
        """GET /v1/runs/{run_id}/events：SSE，无缓存则从 run 步骤降级。"""

        run_id = str(request.path_params.get("run_id") or "").strip()
        events = list(self.events.get(run_id) or [])
        if not events:
            payload = self.assistant.memory_store.load_run(run_id)
            execution = payload.get("execution") if isinstance(payload, dict) else {}
            for raw in (execution or {}).get("steps") or []:
                if not isinstance(raw, dict):
                    continue
                result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
                events.append(
                    {
                        "step_id": str(raw.get("step_id") or ""),
                        "skill_name": str(raw.get("skill_name") or ""),
                        "ok": result.get("ok"),
                        "status": "done" if result.get("ok") else "error",
                    }
                )
        chunks = []
        for item in events:
            chunks.append(f"event: step_status\ndata: {json.dumps(item, ensure_ascii=False)}\n\n")
        if not chunks:
            chunks.append("event: step_status\ndata: {\"status\": \"none\"}\n\n")
        return Response("".join(chunks), media_type="text/event-stream")

    async def export_artifact(self, request: Request) -> Response:
        """GET /v1/artifacts/{run_id}?path= 导出文件。"""

        run_id = str(request.path_params.get("run_id") or "").strip()
        rel = unquote(str(request.query_params.get("path") or "")).strip()
        if not rel:
            return _error("PATH_REQUIRED", "Provide path query parameter.", 400)
        target = Path(rel).expanduser()
        payload = self.assistant.memory_store.load_run(run_id)
        allowed = _collect_artifact_paths(payload)
        if str(target) not in allowed and str(target.resolve()) not in {str(Path(p).resolve()) for p in allowed if Path(p).exists()}:
            # 仍允许 run 记录里出现过的 path
            allowed_resolved = set()
            for item in allowed:
                try:
                    allowed_resolved.add(str(Path(item).expanduser().resolve()))
                except OSError:
                    continue
            try:
                resolved = str(target.resolve())
            except OSError:
                resolved = str(target)
            if resolved not in allowed_resolved and str(target) not in allowed:
                return _error("ARTIFACT_NOT_FOUND", "Artifact path is not part of this run.", 404)
        if not target.exists() or not target.is_file():
            return _error("ARTIFACT_NOT_FOUND", "Artifact file does not exist.", 404)
        return FileResponse(str(target), filename=target.name)

    async def index(self, request: Request) -> Response:
        """GET / SPA。"""

        index = STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse(
            {"ok": True, "message": "Workbench static UI is not built yet."},
            status_code=200,
        )


def _collect_artifact_paths(payload: Dict[str, Any]) -> List[str]:
    """从 run JSON 收集 artifacts.path。"""

    paths: List[str] = []
    execution = payload.get("execution") if isinstance(payload, dict) else {}
    for step in (execution or {}).get("steps") or []:
        result = (step or {}).get("result") if isinstance(step, dict) else {}
        for art in (result or {}).get("artifacts") or []:
            if isinstance(art, dict) and art.get("path"):
                paths.append(str(art["path"]))
    return paths


def create_app(
    *,
    assistant: Optional[QteasyAssistant] = None,
    memory_store: Optional[MemoryStore] = None,
) -> Starlette:
    """创建 Starlette 应用（注入 Assistant，不新建 Planner）。

    Parameters
    ----------
    assistant : QteasyAssistant, optional
        已装配助手；缺省用 ``memory_store`` 新建。
    memory_store : MemoryStore, optional
        与 CLI 共用的落盘根。

    Returns
    -------
    Starlette
        工作台 HTTP 应用。
    """

    ensure_mplbackend_agg()
    helper = assistant or QteasyAssistant(memory_store=memory_store or MemoryStore())
    helper.apply_provider(helper.memory_store.build_active_provider())
    api = WorkbenchHttp(helper)
    routes = [
        Route("/", api.index, methods=["GET"]),
        Route("/v1/ask", api.ask, methods=["POST"]),
        Route("/v1/plan", api.plan, methods=["POST"]),
        Route("/v1/run", api.run, methods=["POST"]),
        Route("/v1/run-plan", api.run_plan, methods=["POST"]),
        Route("/v1/kb/write", api.kb_write, methods=["POST"]),
        Route("/v1/sessions", api.list_sessions, methods=["GET"]),
        Route("/v1/session/{session_id}/rewind", api.rewind_session, methods=["POST"]),
        Route("/v1/session/{session_id}/cancel-run", api.cancel_run, methods=["POST"]),
        Route("/v1/session/{session_id}/background-run", api.background_run, methods=["POST"]),
        Route("/v1/session/{session_id}", api.get_session, methods=["GET"]),
        Route("/v1/session/{session_id}", api.patch_session, methods=["PATCH"]),
        Route("/v1/session/{session_id}", api.delete_session, methods=["DELETE"]),
        Route("/v1/server/shutdown", api.shutdown_server, methods=["POST"]),
        Route("/v1/provider", api.get_provider, methods=["GET"]),
        Route("/v1/provider", api.post_provider, methods=["POST"]),
        Route("/v1/workspace/file", api.get_workspace_file, methods=["GET"]),
        Route("/v1/workspace", api.get_workspace, methods=["GET"]),
        Route("/v1/runs/{run_id}", api.get_run, methods=["GET"]),
        Route("/v1/runs/{run_id}/events", api.get_events, methods=["GET"]),
        Route("/v1/artifacts/{run_id}", api.export_artifact, methods=["GET"]),
    ]
    if STATIC_DIR.exists():
        routes.append(Mount("/static", app=StaticFiles(directory=str(STATIC_DIR)), name="static"))
    app = Starlette(routes=routes)
    app.state.assistant = helper
    app.state.workbench = api
    return app
