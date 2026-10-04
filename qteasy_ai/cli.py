# coding=utf-8
# ======================================
# File: cli.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-15
# Desc:
# qteasy AI 外壳命令行入口，支持
# ask/plan/run/provider 子命令。
# ======================================

"""qteasy AI 外壳 CLI 入口。"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict

from .app import QteasyAssistant
from .config import ensure_mplbackend_agg
from .memory_store import MemoryStore
from .workbench.human import format_human_error, format_human_from_payload
from .human_card import format_human_cards, usage_notice_card


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
    sub = parser.add_subparsers(dest="command", required=False)

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

    sub.add_parser("provider-check", help="Check the active provider.")
    provider_parser = sub.add_parser("provider", help="Manage the provider pool.")
    provider_sub = provider_parser.add_subparsers(dest="provider_command")
    provider_sub.add_parser("list", help="List providers without raw API keys.")
    add_parser = provider_sub.add_parser("add", help="Add a provider without switching to it.")
    add_parser.add_argument("--name", required=True, help="Display name.")
    add_parser.add_argument("--model", required=True, help="Model id.")
    add_parser.add_argument("--base-url", dest="base_url", required=True, help="API base URL.")
    add_parser.add_argument("--api-key", dest="api_key", default="", help="API key. Stored locally.")
    add_parser.add_argument("--timeout", type=int, default=None, help="Request timeout in seconds.")
    update_parser = provider_sub.add_parser("update", help="Update a provider. A blank API key is kept.")
    update_parser.add_argument("provider_id", help="Provider id.")
    update_parser.add_argument("--name", default=None, help="Display name.")
    update_parser.add_argument("--model", default=None, help="Model id.")
    update_parser.add_argument("--base-url", dest="base_url", default=None, help="API base URL.")
    update_parser.add_argument("--api-key", dest="api_key", default=None, help="API key. Blank keeps the saved key.")
    update_parser.add_argument("--timeout", type=int, default=None, help="Request timeout in seconds.")
    remove_parser = provider_sub.add_parser("remove", help="Remove a provider. Mode-R cannot be removed.")
    remove_parser.add_argument("provider_id", help="Provider id.")
    use_parser = provider_sub.add_parser("use", help="Switch the active provider.")
    use_parser.add_argument("provider_id", help="Provider id.")

    serve_parser = sub.add_parser("serve", help="Start the workbench HTTP server (Ask/Plan/run-plan).")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    serve_parser.add_argument("--port", type=int, default=8765, help="Bind port.")

    tui_parser = sub.add_parser("tui", help="Start the minimal workbench TUI.")
    tui_parser.add_argument("--session-id", dest="session_id", default="tui", help="Conversation session id.")
    return parser


def _run_provider_command(memory_store: MemoryStore, args: Any) -> int:
    """执行 provider list/add/update/remove/use。失败时非零退出。"""

    action = str(getattr(args, "provider_command", "") or "")
    if action == "list":
        _print_json(memory_store.list_providers())
        return 0
    if action == "add":
        result = memory_store.add_provider(
            name=str(getattr(args, "name", "") or ""),
            model=str(getattr(args, "model", "") or ""),
            base_url=str(getattr(args, "base_url", "") or ""),
            api_key=str(getattr(args, "api_key", "") or ""),
            timeout=getattr(args, "timeout", None),
        )
    elif action == "update":
        result = memory_store.update_provider(
            str(getattr(args, "provider_id", "") or ""),
            name=getattr(args, "name", None),
            model=getattr(args, "model", None),
            base_url=getattr(args, "base_url", None),
            api_key=getattr(args, "api_key", None),
            timeout=getattr(args, "timeout", None),
        )
    elif action == "remove":
        result = memory_store.remove_provider(str(getattr(args, "provider_id", "") or ""))
    elif action == "use":
        result = memory_store.use_provider(str(getattr(args, "provider_id", "") or ""))
    else:
        result = {
            "ok": False,
            "error": "PROVIDER_FIELDS_REQUIRED",
            "message": "Name and model are required.",
        }
    _print_json(result)
    return 0 if result.get("ok") else 1


def main() -> int:
    """CLI 主入口。"""

    ensure_mplbackend_agg()
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        print(format_human_cards([usage_notice_card()], payload={"mode": "notice"}), end="")
        return 0

    memory_store = MemoryStore()
    provider = memory_store.build_active_provider()
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
        query = str(getattr(args, "query", "") or "").strip()
        if not query:
            _print_cli_error(
                {
                    "ok": False,
                    "error": {
                        "code": "QUERY_REQUIRED",
                        "message": "Provide a query.",
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
        _print_json(memory_store.active_diagnostics())
        return 0
    if args.command == "provider":
        return _run_provider_command(memory_store, args)
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
        from .workbench.serve_log import build_serve_log_config, configure_qteasy_console_for_serve

        app = create_app(assistant=assistant)
        app.state.allow_quit = True
        configure_qteasy_console_for_serve()
        uvicorn.run(
            app,
            host=str(args.host),
            port=int(args.port),
            log_config=build_serve_log_config(),
        )
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
