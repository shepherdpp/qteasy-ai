# coding=utf-8
# ======================================
# File: cli.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-15
# Desc:
# qteasy AI 外壳命令行入口，支持
# ask/plan/run/provider-check 子命令。
# ======================================

"""qteasy AI 外壳 CLI 入口。"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict

from .app import QteasyAssistant
from .config import DEFAULT_PROVIDER_TIMEOUT, ConfigCenter, provider_diagnostics
from .memory_store import MemoryStore
from .provider import OpenAICompatProvider
from .workbench.human import format_human_error, format_human_from_payload


def _build_provider_from_config() -> OpenAICompatProvider | None:
    """从 ConfigCenter 构建 Provider。"""

    config_center = ConfigCenter()
    provider_cfg = config_center.resolve_provider_config()
    model = str(provider_cfg.get("model", "")).strip()
    if not model:
        return None
    return OpenAICompatProvider(
        model=model,
        api_key=str(provider_cfg.get("api_key", "")),
        base_url=str(provider_cfg.get("base_url", "https://api.openai.com/v1")),
        timeout=int(provider_cfg.get("timeout", DEFAULT_PROVIDER_TIMEOUT)),
        config_center=config_center,
    )


def _provider_check_payload() -> Dict[str, Any]:
    """生成 provider-check 的可诊断信息。"""

    return provider_diagnostics()


def _print_json(payload: Dict[str, Any]) -> None:
    """打印 JSON。"""

    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _normalize_output(payload: Any) -> Dict[str, Any]:
    """将 Assistant 输出转换为可序列化字典。"""

    if hasattr(payload, "to_dict"):
        return payload.to_dict()
    if isinstance(payload, dict):
        return payload
    return {"output": str(payload)}


def _add_format_flags(parser: argparse.ArgumentParser) -> None:
    """Ask/Plan/run 共用：--human（默认）/ --pretty / --raw。"""

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--human",
        dest="output_format",
        action="store_const",
        const="human",
        help="Chat-pane text: answer, clarification, or error (default).",
    )
    group.add_argument(
        "--pretty",
        dest="output_format",
        action="store_const",
        const="pretty",
        help="Structured user-friendly JSON (narrative channels).",
    )
    group.add_argument(
        "--raw",
        dest="output_format",
        action="store_const",
        const="raw",
        help="Machine-readable payload JSON.",
    )
    parser.set_defaults(output_format="human")


def _response_style_for(output_format: str) -> str:
    """CLI 档位 → Assistant response_style。human 内部仍取 raw 再渲染。"""

    if output_format == "pretty":
        return "user_friendly"
    return "raw"


def _print_result(
    payload: Any,
    *,
    output_format: str,
    assistant: QteasyAssistant,
    query: str = "",
    session_id: str = "",
) -> None:
    """按档位打印：human 纯文本，pretty/raw 为 JSON。"""

    fmt = str(output_format or "human")
    if fmt in {"raw", "pretty"}:
        _print_json(_normalize_output(payload))
        return
    session = None
    sid = str(session_id or "").strip()
    if sid:
        session = assistant.session_store.load(sid)
    env = assistant.memory_store.load_env_facts()
    print(
        format_human_from_payload(
            payload,
            query=query,
            session=session,
            env_facts=env,
            registry=assistant.registry,
        ),
        end="",
    )


def _print_cli_error(payload: Dict[str, Any], output_format: str) -> None:
    """4xx 错误：human 只打 message，否则 JSON。"""

    if str(output_format or "human") == "human":
        print(format_human_error(payload), end="")
        return
    _print_json(payload)


def build_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""

    parser = argparse.ArgumentParser(
        prog="qteasy-ai",
        description="qteasy AI shell CLI (Ask / Plan / preview / run)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ask_parser = sub.add_parser("ask", help="Ask mode: Q&A via KnowledgeBase, no skill execution.")
    ask_parser.add_argument("query", type=str, help="Natural language query")
    _add_format_flags(ask_parser)
    ask_parser.add_argument(
        "--depth",
        choices=["brief", "standard", "deep"],
        default="standard",
        help="Explanation depth for Ask answers.",
    )
    ask_parser.add_argument("--session-id", dest="session_id", default="", help="Reuse a conversation session.")

    preview_parser = sub.add_parser("preview", help="Dry-run plan preview (no skill execution).")
    preview_parser.add_argument("query", type=str, help="Natural language query")
    _add_format_flags(preview_parser)
    preview_parser.add_argument(
        "--depth",
        choices=["brief", "standard", "deep"],
        default="standard",
        help="Explanation depth for pretty output.",
    )
    preview_parser.add_argument("--session-id", dest="session_id", default="", help="Reuse a conversation session.")

    plan_parser = sub.add_parser("plan", help="Plan mode dry run.")
    plan_parser.add_argument("query", nargs="?", default="", help="Natural language query")
    _add_format_flags(plan_parser)
    plan_parser.add_argument(
        "--preview",
        action="store_true",
        help="Alias of dry-run plan (same as preview subcommand).",
    )
    plan_parser.add_argument(
        "--depth",
        choices=["brief", "standard", "deep"],
        default="standard",
        help="Explanation depth for pretty output.",
    )
    plan_parser.add_argument("--session-id", dest="session_id", default="", help="Reuse a conversation session.")
    plan_parser.add_argument(
        "--abandon-trial",
        dest="abandon_trial",
        action="store_true",
        help="Abandon the current open-loop trial; keep the Spec draft.",
    )
    plan_parser.add_argument(
        "--abandon-open",
        dest="abandon_open",
        action="store_true",
        help="Abandon the entire open job; keep the session id.",
    )
    plan_parser.add_argument(
        "--confirm-kb-write",
        dest="confirm_kb_write",
        action="store_true",
        help="Confirm writing the pending design note into user_kb/raw.",
    )

    run_parser = sub.add_parser("run", help="Plan and execute, or execute a reviewed plan by id.")
    run_parser.add_argument("query", nargs="?", default="", help="Natural language query")
    run_parser.add_argument(
        "--plan-id",
        dest="plan_id",
        default="",
        help="Execute a reviewed ToolPlan from runs/ without re-planning.",
    )
    _add_format_flags(run_parser)
    run_parser.add_argument(
        "--depth",
        choices=["brief", "standard", "deep"],
        default="standard",
        help="Explanation depth for pretty output.",
    )
    run_parser.add_argument("--session-id", dest="session_id", default="", help="Reuse a conversation session.")
    run_parser.add_argument(
        "--agent-auto",
        dest="agent_auto",
        action="store_true",
        help="Session unattended mode; allow_* gates high-side-effect steps.",
    )

    sub.add_parser("provider-check", help="Check provider settings.")

    serve_parser = sub.add_parser("serve", help="Start the workbench HTTP server (Ask/Plan/run-plan).")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    serve_parser.add_argument("--port", type=int, default=8765, help="Bind port.")

    tui_parser = sub.add_parser("tui", help="Start the minimal workbench TUI.")
    tui_parser.add_argument("--session-id", dest="session_id", default="tui", help="Conversation session id.")
    return parser


def main() -> int:
    """CLI 主入口。"""

    parser = build_parser()
    args = parser.parse_args()

    memory_store = MemoryStore()
    provider = _build_provider_from_config()
    assistant = QteasyAssistant(provider=provider, memory_store=memory_store)
    output_format = str(getattr(args, "output_format", "human") or "human")
    response_style = _response_style_for(output_format)
    session_id = str(getattr(args, "session_id", "") or "").strip() or None
    session_arg = session_id or ""
    if args.command == "ask":
        depth = getattr(args, "depth", "standard")
        payload = assistant.ask(
            args.query,
            response_style=response_style,
            explanation_depth=depth,
            session_id=session_id,
        )
        _print_result(
            payload,
            output_format=output_format,
            assistant=assistant,
            query=str(args.query),
            session_id=session_arg,
        )
        return 0
    if args.command in {"plan", "preview"}:
        depth = getattr(args, "depth", "standard")
        if bool(getattr(args, "abandon_trial", False)):
            if not session_id:
                _print_cli_error(
                    {
                        "ok": False,
                        "error": {
                            "code": "SESSION_ID_REQUIRED",
                            "message": "Provide --session-id with --abandon-trial.",
                        },
                    },
                    output_format,
                )
                return 1
            payload = assistant.abandon_trial(session_id, response_style=response_style)
        elif bool(getattr(args, "abandon_open", False)):
            if not session_id:
                _print_cli_error(
                    {
                        "ok": False,
                        "error": {
                            "code": "SESSION_ID_REQUIRED",
                            "message": "Provide --session-id with --abandon-open.",
                        },
                    },
                    output_format,
                )
                return 1
            payload = assistant.abandon_open(session_id, response_style=response_style)
        elif bool(getattr(args, "confirm_kb_write", False)):
            if not session_id:
                _print_cli_error(
                    {
                        "ok": False,
                        "error": {
                            "code": "SESSION_ID_REQUIRED",
                            "message": "Provide --session-id with --confirm-kb-write.",
                        },
                    },
                    output_format,
                )
                return 1
            try:
                payload = assistant.confirm_kb_write(
                    session_id, confirm=True, response_style=response_style
                )
            except ValueError as exc:
                _print_cli_error(
                    {"ok": False, "error": {"code": "KB_WRITE_NOT_PENDING", "message": str(exc)}},
                    output_format,
                )
                return 1
        else:
            query = str(getattr(args, "query", "") or "").strip()
            if not query:
                _print_cli_error(
                    {
                        "ok": False,
                        "error": {
                            "code": "QUERY_REQUIRED",
                            "message": "Provide a query, or use --abandon-trial / --abandon-open / --confirm-kb-write.",
                        },
                    },
                    output_format,
                )
                return 1
            payload = assistant.preview(
                query,
                response_style=response_style,
                explanation_depth=depth,
                session_id=session_id,
            )
        _print_result(
            payload,
            output_format=output_format,
            assistant=assistant,
            query=str(args.query),
            session_id=session_arg,
        )
        return 0
    if args.command == "run":
        depth = getattr(args, "depth", "standard")
        plan_id = str(getattr(args, "plan_id", "") or "").strip()
        query = str(getattr(args, "query", "") or "").strip()
        if plan_id:
            try:
                payload = assistant.run_plan(
                    plan_id,
                    response_style=response_style,
                    explanation_depth=depth,
                )
            except ValueError as exc:
                _print_cli_error(
                    {"ok": False, "error": {"code": "PLAN_ID_NOT_FOUND", "message": str(exc)}},
                    output_format,
                )
                return 1
            _print_result(
                payload,
                output_format=output_format,
                assistant=assistant,
                query=query,
                session_id=session_arg,
            )
            return 0
        if not query:
            _print_cli_error(
                {
                    "ok": False,
                    "error": {
                        "code": "QUERY_OR_PLAN_ID_REQUIRED",
                        "message": "Provide a query or --plan-id. Missing plan_id is not executed as a new query.",
                    },
                },
                output_format,
            )
            return 1
        payload = assistant.run(
            query,
            response_style=response_style,
            explanation_depth=depth,
            session_id=session_id,
            agent_auto=bool(getattr(args, "agent_auto", False)) or None,
        )
        _print_result(
            payload,
            output_format=output_format,
            assistant=assistant,
            query=query,
            session_id=session_arg,
        )
        return 0
    if args.command == "provider-check":
        _print_json(_provider_check_payload())
        return 0
    if args.command == "serve":
        try:
            import uvicorn
        except ImportError:
            _print_json(
                {
                    "ok": False,
                    "error": {
                        "code": "WORKBENCH_EXTRA_REQUIRED",
                        "message": "Install extra: pip install qteasy-ai[workbench]",
                    },
                }
            )
            return 1
        from .workbench.http_app import create_app

        app = create_app(assistant=assistant)
        uvicorn.run(app, host=str(args.host), port=int(args.port))
        return 0
    if args.command == "tui":
        try:
            from .workbench.tui_app import run_tui
        except ImportError:
            _print_json(
                {
                    "ok": False,
                    "error": {
                        "code": "WORKBENCH_EXTRA_REQUIRED",
                        "message": "Install extra: pip install qteasy-ai[workbench]",
                    },
                }
            )
            return 1
        run_tui(assistant=assistant, session_id=str(getattr(args, "session_id", "") or "tui"))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
