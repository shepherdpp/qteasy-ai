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
import queue
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional
from urllib.parse import unquote

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ..app import QteasyAssistant
from ..contracts import PlanStepRecord
from ..memory_store import MemoryStore
from ..session import SessionStore
from .mapper import map_assistant_payload

STATIC_DIR = Path(__file__).resolve().parent / "static"

_NEXT_ACTION = {
    "QUERY_REQUIRED": "Type a question in the composer, then press Ctrl+Enter to send.",
    "PLAN_ID_REQUIRED": "Confirm a plan from this session, or send a new Plan request.",
    "PLAN_ID_NOT_FOUND": "Create a plan first, then press Confirm. The plan_id lives in runs/, not as a filename.",
    "SESSION_ID_REQUIRED": "Select a session from the left rail, or click New.",
    "PATH_REQUIRED": "Pick a file under Workspace → Files.",
    "FILE_NOT_FOUND": "Choose a file inside runs/, strategies/, or user_kb/.",
    "FILE_NOT_TEXT": "Only text workspace files can be previewed. Export binaries from Artifacts.",
    "FILE_TOO_LARGE": "Pick a smaller file, or open it on disk under the memory root.",
    "RUN_NOT_FOUND": "Open a run from Workspace → Files, or Confirm a plan to create one.",
    "ARTIFACT_NOT_FOUND": "Export only files that belong to this run_id.",
    "RUN_FAILED": "Read the error, then press Retry. You do not need to start over.",
}


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


def _sse_line(event: str, data: Any) -> str:
    """一条 SSE 记录。

    Parameters
    ----------
    event : str
        事件名。
    data : Any
        JSON 可序列化载荷。

    Returns
    -------
    str
        SSE 文本块。
    """

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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
        """raw payload → WorkbenchState JSON。"""

        session = None
        sid = str(session_id or "").strip()
        if sid:
            session = SessionStore(self.assistant.memory_store).load(sid)
        env = self.assistant.memory_store.load_env_facts()
        state = map_assistant_payload(payload, session=session, query=query, env_facts=env)
        dumped = state.to_dict()
        dumped["ok"] = dumped.get("error") is None
        extra = list(dumped.get("messages") or [])
        card = dumped.get("plan_card") or {}
        if card.get("confirmable") and not any(
            isinstance(item, dict) and item.get("kind") == "ask_text" for item in extra
        ):
            titles = [
                str(step.get("summary") or step.get("skill_name") or "").strip()
                for step in (card.get("steps") or [])
                if isinstance(step, dict)
            ]
            titles = [item for item in titles if item]
            extra.append(
                {
                    "kind": "ask_text",
                    "text": "Plan ready: " + ("; ".join(titles) or card.get("plan_id") or "review steps"),
                    "payload": {"plan_id": card.get("plan_id") or ""},
                }
            )
        if persist_transcript and sid:
            dumped["transcript"] = self.assistant.memory_store.append_ui_transcript(sid, extra)
        elif sid:
            dumped["transcript"] = self.assistant.memory_store.load_ui_transcript(sid)
        else:
            dumped["transcript"] = []
        return dumped

    def _stream_execute(
        self,
        runner: Callable[[Any], Dict[str, Any]],
        *,
        query: str = "",
        session_id: str = "",
    ) -> Iterator[str]:
        """在线程中执行 runner，按 on_step 推 SSE，最后推 state。

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

        def on_step(record: PlanStepRecord) -> None:
            self._record_step(bucket, record)
            q.put(("step", dict(bucket[-1])))

        def worker() -> None:
            try:
                box["payload"] = runner(on_step)
            except Exception as exc:
                box["exc"] = exc
            q.put(("end", None))

        threading.Thread(target=worker, daemon=True).start()
        while True:
            kind, data = q.get()
            if kind == "step":
                yield _sse_line("step_status", data)
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
        dto = self._to_dto(
            box.get("payload") or {},
            query=query,
            session_id=session_id,
            persist_transcript=True,
        )
        run_id = str(dto.get("run_id") or "")
        if run_id:
            self.events[run_id] = list(bucket)
        yield _sse_line("state", dto)

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
        if not query:
            return _error("QUERY_REQUIRED", "Provide a query.", 400)
        session_id = str(body.get("session_id") or "").strip()
        payload = self.assistant.plan(
            query,
            response_style="raw",
            session_id=session_id or None,
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

        def runner(on_step: Any) -> Dict[str, Any]:
            return self.assistant.run(
                query,
                response_style="raw",
                session_id=session_id or None,
                agent_auto=bool(agent_auto) if agent_auto is not None else None,
                on_step=on_step,
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

        def runner(on_step: Any) -> Dict[str, Any]:
            return self.assistant.run_plan(
                plan_id,
                response_style="raw",
                on_step=on_step,
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

    async def get_session(self, request: Request) -> JSONResponse:
        """GET /v1/session/{session_id}：有 current_plan_id 则按 plan_id 回填 DTO。"""

        session_id = str(request.path_params.get("session_id") or "").strip()
        if not session_id:
            return _error("SESSION_ID_REQUIRED", "Provide a session_id.", 400)
        conv = SessionStore(self.assistant.memory_store).load(session_id)
        env = self.assistant.memory_store.load_env_facts()
        payload: Dict[str, Any] = {
            "mode": "plan",
            "plan": {"plan_id": conv.current_plan_id, "steps": []},
            "execution": {"status": "", "steps": []},
        }
        if conv.current_plan_id:
            found = self.assistant.memory_store.find_run_by_plan_id(conv.current_plan_id)
            if found:
                payload = dict(found)
        if conv.pending_clarification and not payload.get("clarification"):
            payload = dict(payload)
            payload["clarification"] = dict(conv.pending_clarification)
        mapped = map_assistant_payload(payload, session=conv, env_facts=env)
        dumped = mapped.to_dict()
        dumped["ok"] = True
        dumped["turns"] = list(conv.turns)
        hist = self.assistant.memory_store.load_ui_transcript(session_id)
        if not hist:
            hist = []
            for turn in conv.turns or []:
                if isinstance(turn, dict) and turn.get("query"):
                    hist.append({"kind": "user_text", "text": str(turn.get("query")), "payload": {}})
            for msg in dumped.get("messages") or []:
                if isinstance(msg, dict) and msg.get("kind") not in {"plan_card", "step_status", "user_text"}:
                    hist.append(msg)
        dumped["transcript"] = hist
        if conv.turns:
            last = conv.turns[-1] if isinstance(conv.turns[-1], dict) else {}
            if str(last.get("kind") or "") == "ask":
                dumped["mode"] = "ask"
        return JSONResponse(dumped)

    async def list_sessions(self, request: Request) -> JSONResponse:
        """GET /v1/sessions：只读列举已落盘会话。"""

        del request
        store = SessionStore(self.assistant.memory_store)
        rows = store.list_summaries()
        return JSONResponse({"ok": True, "sessions": rows})

    async def get_workspace(self, request: Request) -> JSONResponse:
        """GET /v1/workspace：只读 runs / strategies / user_kb 树。"""

        del request
        trees = self.assistant.memory_store.list_workspace_tree()
        return JSONResponse(
            {
                "ok": True,
                "root": str(self.assistant.memory_store.base_dir),
                "trees": trees,
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

    helper = assistant or QteasyAssistant(memory_store=memory_store or MemoryStore())
    api = WorkbenchHttp(helper)
    routes = [
        Route("/", api.index, methods=["GET"]),
        Route("/v1/ask", api.ask, methods=["POST"]),
        Route("/v1/plan", api.plan, methods=["POST"]),
        Route("/v1/run", api.run, methods=["POST"]),
        Route("/v1/run-plan", api.run_plan, methods=["POST"]),
        Route("/v1/sessions", api.list_sessions, methods=["GET"]),
        Route("/v1/session/{session_id}", api.get_session, methods=["GET"]),
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
