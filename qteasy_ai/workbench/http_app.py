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
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, FileResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ..app import QteasyAssistant
from ..contracts import PlanStepRecord
from ..memory_store import MemoryStore
from ..session import SessionStore
from .mapper import map_assistant_payload

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _error(code: str, message: str, status: int) -> JSONResponse:
    """英文错误 JSON。"""

    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status,
    )


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
        return dumped

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
        return JSONResponse(self._to_dto(payload, query=query, session_id=session_id))

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
        return JSONResponse(self._to_dto(payload, query=query, session_id=session_id))

    async def run(self, request: Request) -> JSONResponse:
        """POST /v1/run（显式 Agent 入口）。"""

        body = await self._read_json(request)
        query = str(body.get("query") or "").strip()
        if not query:
            return _error("QUERY_REQUIRED", "Provide a query.", 400)
        session_id = str(body.get("session_id") or "").strip()
        agent_auto = body.get("agent_auto")
        bucket: List[Dict[str, Any]] = []

        def on_step(record: PlanStepRecord) -> None:
            self._record_step(bucket, record)

        payload = self.assistant.run(
            query,
            response_style="raw",
            session_id=session_id or None,
            agent_auto=bool(agent_auto) if agent_auto is not None else None,
            on_step=on_step,
        )
        dto = self._to_dto(payload, query=query, session_id=session_id)
        run_id = str(dto.get("run_id") or "")
        if run_id:
            self.events[run_id] = list(bucket)
        return JSONResponse(dto)

    async def run_plan(self, request: Request) -> JSONResponse:
        """POST /v1/run-plan：按已审阅 plan_id 执行，禁止重新 Hybrid。"""

        body = await self._read_json(request)
        plan_id = str(body.get("plan_id") or "").strip()
        if not plan_id:
            return _error(
                "PLAN_ID_REQUIRED",
                "Provide plan_id. Missing plan_id is not executed as a new query.",
                400,
            )
        bucket: List[Dict[str, Any]] = []

        def on_step(record: PlanStepRecord) -> None:
            self._record_step(bucket, record)

        try:
            payload = self.assistant.run_plan(
                plan_id,
                response_style="raw",
                on_step=on_step,
            )
        except ValueError as exc:
            return _error("PLAN_ID_NOT_FOUND", str(exc), 404)
        dto = self._to_dto(payload, query="")
        run_id = str(dto.get("run_id") or "")
        if run_id:
            self.events[run_id] = list(bucket)
        return JSONResponse(dto)

    async def get_session(self, request: Request) -> JSONResponse:
        """GET /v1/session/{session_id}。"""

        session_id = str(request.path_params.get("session_id") or "").strip()
        if not session_id:
            return _error("SESSION_ID_REQUIRED", "Provide a session_id.", 400)
        state = SessionStore(self.assistant.memory_store).load(session_id)
        empty = map_assistant_payload(
            {
                "mode": "plan",
                "plan": {"plan_id": state.current_plan_id, "steps": []},
                "execution": {"status": "", "steps": []},
            },
            session=state,
            env_facts=self.assistant.memory_store.load_env_facts(),
        )
        dumped = empty.to_dict()
        dumped["ok"] = True
        dumped["turns"] = list(state.turns)
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
