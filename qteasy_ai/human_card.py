# coding=utf-8
# ======================================
# File: human_card.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-11
# Desc:
# 人读卡内核投影：ToolPlan / SkillResult → session messages[]。
# ======================================

"""装配层人读卡投影。Web / CLI / TUI 只渲染，禁止反解析。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .side_effects import step_needs_confirm as _step_needs_confirm

HUMAN_CARD_KINDS = frozenset(
    {
        "user_text",
        "ask",
        "plan_ready",
        "clarify",
        "executing",
        "result",
        "error",
        "mode_notice",
        "design_card",
        "kb_write",
    }
)
KIND_ALIASES = {
    "ask_text": "ask",
    "clarification": "clarify",
}
SKIP_MESSAGE_KINDS = frozenset({"", "plan_card", "step_status"})

_DATA_READ_BY_CHANNEL = {
    "history": "qteasy.get_history_data",
    "reference": "qteasy.get_reference_data",
    "static": "qteasy.get_static_data",
}
_SKIP_INPUT_KEYS = frozenset({"upstream_payload", "upstream_metrics", "upstream_data_summary"})
_LIST_NAME_CAP = 80
_DOC_LINE_CAP = 80
_DOC_CHAR_CAP = 4000
_GENERIC_LIST_CAP = 40
from .side_effects import HIGH_SIDE_EFFECT_SKILLS, step_needs_confirm as _step_needs_confirm
_DEFAULT_NEXT_ACTION = (
    "Fix the issue above, then retry this step. You do not need to start over."
)
_INDUSTRY_SAMPLE_NEXT_ACTION = (
    "Revise the query using one exact Tushare industry short name from the samples. "
    "Do not retry the same industry name."
)
USAGE_NOTICE_TEXT = (
    "qteasy-ai needs a subcommand. It does not run tasks by default.\n"
    "Examples:\n"
    "  qteasy-ai ask \"What is qteasy?\"\n"
    "  qteasy-ai plan \"List built-in strategies\"\n"
    "  qteasy-ai run --plan-id PLAN_ID\n"
    "Ask answers questions. Plan reviews steps without executing. "
    "Run executes a reviewed plan_id (or a one-shot confirmed query)."
)


def normalize_card_kind(kind: Any) -> str:
    """把消息 kind 规范成 G.8 名；未知原样返回。

    Parameters
    ----------
    kind : Any
        原始 kind。

    Returns
    -------
    str
        规范化 kind。
    """

    raw = str(kind or "").strip()
    return str(KIND_ALIASES.get(raw, raw))


def make_card(kind: str, text: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """构造一条人读卡。

    Parameters
    ----------
    kind : str
        G.8 kind。
    text : str
        英文正文。
    payload : dict, optional
        结构化载荷。

    Returns
    -------
    dict
        ``kind`` / ``text`` / ``payload``。
    """

    return {
        "kind": normalize_card_kind(kind),
        "text": str(text or ""),
        "payload": dict(payload or {}),
    }


def usage_notice_card() -> Dict[str, Any]:
    """无子命令时的友好用法卡。

    Returns
    -------
    dict
        ``kind=mode_notice``。
    """

    return make_card(
        "mode_notice",
        USAGE_NOTICE_TEXT,
        {"requested_mode": "", "effective_kind": "usage"},
    )


def infer_effective_kind(payload: Dict[str, Any]) -> str:
    """从装配层 payload 推断有效 kind（不是第五模式）。

    Parameters
    ----------
    payload : dict
        raw Assistant 输出。

    Returns
    -------
    str
        ``ask`` / ``clarify`` / ``plan`` / ``run`` / ``error``。
    """

    raw = payload if isinstance(payload, dict) else {}
    if _is_ask_payload(raw):
        return "ask"
    if _clarification_blob(raw):
        return "clarify"
    execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else {}
    status = str(execution.get("status") or "")
    if status in {"success", "partial_failed", "failed"}:
        return "run"
    if isinstance(raw.get("error"), dict) and raw.get("error"):
        return "error"
    return "plan"


def revision_notice_text(
    revision: int,
    patches: Dict[str, Any],
    changes: Optional[Sequence[Dict[str, Any]]] = None,
) -> str:
    """改槽 Notice：接受、系统填入、拒绝分条写出。

    Parameters
    ----------
    revision : int
        修订序号。
    patches : dict
        本次写入的槽值。无 ``changes`` 时按用户接受逐条列出。
    changes : sequence of dict, optional
        每项含 ``label`` / ``value`` / ``origin``（``accepted``、``filled`` 或 ``rejected``）。
        ``filled`` 且有 ``from_label`` 时说明来源槽。

    Returns
    -------
    str
        英文正文。没有任何接受或填入时为空串，不发 Notice。
    """

    rows = [item for item in (changes or []) if isinstance(item, dict)]
    if not rows:
        rows = [
            {"label": str(key), "value": value, "origin": "accepted"}
            for key, value in (patches or {}).items()
        ]
    lines: List[str] = []
    progressed = False
    for item in rows:
        label = str(item.get("label") or item.get("name") or "").strip()
        value = item.get("value")
        origin = str(item.get("origin") or "accepted")
        if origin == "filled":
            progressed = True
            source = str(item.get("from_label") or item.get("from") or "").strip()
            if source:
                lines.append(f"Filled {label} = {value} from {source}.")
            else:
                lines.append(f"Filled {label} = {value}.")
        elif origin == "rejected":
            lines.append(f"Rejected {label} = {value}.")
        else:
            progressed = True
            lines.append(f"Accepted {label} = {value}.")
    if not progressed:
        return ""
    return "\n".join([f"Plan revised (revision {int(revision)})."] + lines)


def project_human_cards(
    payload: Dict[str, Any],
    *,
    requested_mode: str = "",
    query: str = "",
    registry: Any = None,
    include_user_text: bool = True,
) -> List[Dict[str, Any]]:
    """把 ToolPlan / SkillResult / 澄清态投影为人读卡。不调 LLM，不新造数字。

    Parameters
    ----------
    payload : dict
        装配层 raw dict。
    requested_mode : str, optional
        用户入口：``ask`` / ``plan`` / ``run`` / ``preview``。
    query : str, optional
        本轮用户句。
    registry : SkillRegistry, optional
        查 summary / entrypoints / outputs_schema。
    include_user_text : bool, default True
        是否写入 ``user_text``。

    Returns
    -------
    list of dict
        人读卡列表。
    """

    raw = dict(payload or {})
    requested = str(requested_mode or raw.get("requested_mode") or raw.get("mode") or "").strip().lower()
    if requested == "preview":
        requested = "plan"
    if requested == "agent":
        requested = "run"
    effective = str(raw.get("effective_kind") or infer_effective_kind(raw)).strip() or infer_effective_kind(raw)
    cards: List[Dict[str, Any]] = []
    asked = str(query or raw.get("user_query") or "").strip()
    plan = raw.get("plan") if isinstance(raw.get("plan"), dict) else {}
    if not asked:
        asked = str(plan.get("user_query") or "").strip()
    assumptions_early = plan.get("assumptions") if isinstance(plan.get("assumptions"), dict) else {}

    if include_user_text and asked:
        cards.append(make_card("user_text", asked, {}))

    if raw.get("block_running") or assumptions_early.get("block_running"):
        cards.append(
            make_card(
                "mode_notice",
                "A high side-effect plan is still running. Wait for it to finish, press Background, or press Stop.",
                {"requested_mode": requested, "effective_kind": "block_running"},
            )
        )
        return cards

    revision = raw.get("slot_revision")
    if isinstance(revision, dict) and revision:
        rev_n = int(raw.get("revision") or 0)
        changes = raw.get("slot_changes") if isinstance(raw.get("slot_changes"), list) else []
        notice = revision_notice_text(rev_n, revision, changes)
        if notice:
            cards.append(
                make_card(
                    "mode_notice",
                    notice,
                    {"patches": dict(revision), "revision": rev_n},
                )
            )

    if raw.get("topic_skipped"):
        cards.append(
            make_card(
                "mode_notice",
                "Previous topic skipped.",
                {"requested_mode": requested, "effective_kind": "skip"},
            )
        )
    hatch = str(raw.get("hatch") or "").strip()
    hatch_pid = str(raw.get("hatch_plan_id") or "").strip()
    if hatch == "plan_mode_execute" and hatch_pid:
        cards.append(
            make_card(
                "mode_notice",
                f"You asked to run {hatch_pid} from Plan mode.",
                {"requested_mode": requested, "effective_kind": "run", "plan_id": hatch_pid},
            )
        )
    elif hatch == "run_plan_id" and hatch_pid:
        cards.append(
            make_card(
                "mode_notice",
                f"You asked to run {hatch_pid}.",
                {"requested_mode": requested, "effective_kind": "run", "plan_id": hatch_pid},
            )
        )

    if requested in {"plan", "run"} and effective == "ask":
        cards.append(
            make_card(
                "mode_notice",
                (
                    f"You requested {requested.upper()}, but this is an Ask answer "
                    f"(no executable steps)."
                ),
                {"requested_mode": requested, "effective_kind": "ask"},
            )
        )

    if _is_ask_payload(raw):
        sources = [str(item) for item in (raw.get("sources") or []) if str(item)]
        answer = str(raw.get("answer") or raw.get("narrative") or "").strip() or "No answer."
        cards.append(make_card("ask", answer, {"sources": sources}))
        err = _enrich_error(raw.get("error") if isinstance(raw.get("error"), dict) else None)
        if err:
            cards.append(make_card("error", _error_card_text(err), dict(err)))
        return cards

    clar = _clarification_blob(raw)
    assumptions = plan.get("assumptions") if isinstance(plan.get("assumptions"), dict) else {}
    if clar:
        text = str(clar.get("confirm_prompt") or clar.get("restatement") or "Clarification required.").strip()
        pending = list(clar.get("pending") or []) if isinstance(clar.get("pending"), list) else []
        options = list(clar.get("options") or []) if isinstance(clar.get("options"), list) else []
        blob = dict(clar)
        blob["pending"] = pending
        blob["options"] = options
        plan_id = str(plan.get("plan_id") or raw.get("plan_id") or "")
        if plan_id:
            blob["plan_id"] = plan_id
        cards.append(make_card("clarify", text, blob))
        return cards

    execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else {}
    exec_steps = [item for item in (execution.get("steps") or []) if isinstance(item, dict)]
    status = str(execution.get("status") or "")
    executed = status in {"success", "partial_failed", "failed"} and bool(exec_steps)
    plan_id = str(plan.get("plan_id") or "")
    run_id = str(raw.get("run_id") or execution.get("run_id") or "")

    err = _first_error(raw)
    blocked = assumptions.get("allow_gate_blocked")
    if isinstance(blocked, list) and blocked and err is None:
        err = _enrich_error(
            {
                "code": "ALLOW_GATE_BLOCKED",
                "message": (
                    "Agent auto cannot execute high side-effect steps without allow_* flags: "
                    + ", ".join(str(item) for item in blocked)
                    + "."
                ),
            }
        )

    if executed:
        cards.append(
            make_card(
                "executing",
                "Running steps.",
                {"plan_id": plan_id, "run_id": run_id, "steps": _step_ticks(exec_steps)},
            )
        )
        brief = _slim_result_lines(plan=plan, execution=execution, registry=registry)
        result_text = "\n".join(brief)
        if not str(result_text or "").strip():
            result_text = "No rows or metrics in the result."
        result_payload: Dict[str, Any] = {
            "plan_id": plan_id,
            "run_id": run_id,
            "executed": True,
            "status": status,
        }
        cards.append(make_card("result", result_text, result_payload))
        if err and status != "success":
            cards.append(make_card("error", _error_card_text(err), dict(err)))
        return cards

    card_steps = _plan_step_rows(plan)
    if card_steps or plan_id:
        confirmable = status == "dry_run" and bool(card_steps)
        skills = [row["skill_name"] for row in card_steps]
        if skills and all(name == "qt.ai.system.fallback" for name in skills):
            confirmable = False
        brief = _slim_plan_ready_lines(
            plan=plan,
            card_steps=card_steps,
            plan_id=plan_id,
            run_id=run_id,
            plan_md_file=str(raw.get("plan_md_file") or ""),
            confirmable=confirmable,
        )
        text = "\n".join(brief)
        cards.append(
            make_card(
                "plan_ready",
                text,
                {
                    "plan_id": plan_id,
                    "run_id": run_id,
                    "confirmable": confirmable,
                },
            )
        )

    if err:
        cards.append(make_card("error", _error_card_text(err), dict(err)))
    if not any(item.get("kind") != "user_text" for item in cards):
        cards.append(make_card("ask", "No output.", {}))
    return cards


_POLISH_KINDS = frozenset({"clarify", "plan_ready", "error", "result"})
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_SKILL_RE = re.compile(r"qt\.ai\.[a-zA-Z0-9_.]+")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_PLAN_ID_VALUE_RE = re.compile(r"\bplan_[A-Za-z0-9]+\b")
_ERROR_CODE_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
_METRIC_RE = re.compile(
    r"(\b(sharpe|drawdown|hit_count|max_drawdown|annual(?:ized)?\s+return|hit count)\b|回撤|夏普)",
    re.IGNORECASE,
)
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n([\s\S]*?)\n```$")
_CARD_SYSTEM_PROMPT = (
    "Rewrite this qteasy-ai card into Simplified Chinese. "
    "Change only tone and language. "
    "Keep every qt.ai skill id, plan_id, error code, parameter, and number exactly as written. "
    "Do not add steps, returns, drawdowns, hit counts, or any number that is not already in the card. "
    "Output the rewritten card text only."
)
_RESULT_SYSTEM_PROMPT = (
    "Rewrite this qteasy-ai result card into Simplified Chinese. "
    "Keep the sentences. Translate the wording, not the facts. "
    "Keep every number and every error message exactly as written. "
    "Do not add steps, returns, drawdowns, hit counts, or any number that is not already in the card. "
    "Output the rewritten text only."
)


def polish_human_cards(
    cards: Sequence[Dict[str, Any]],
    *,
    provider: Any = None,
    query: str = "",
) -> List[Dict[str, Any]]:
    """在确定性英文卡之上按语气改写。未配置模型或问句不含中文时原样返回。

    只改 ``clarify`` / ``plan_ready`` / ``error`` / ``result`` 的 ``text``。
    校验失败、模型报错或空回复时保留该卡英文。``payload`` 不改。

    Parameters
    ----------
    cards : sequence of dict
        ``project_human_cards`` 的结果。
    provider : object, optional
        实现 ``chat(prompt, system_prompt=...)`` 的 LLM Provider。
    query : str, optional
        本轮用户句。含中文且 Provider 可用时才润色。

    Returns
    -------
    list of dict
        人读卡。未润色的项与输入为同一对象。
    """

    rows = [item for item in (cards or [])]
    if provider is None or not hasattr(provider, "chat"):
        return rows
    if not _CJK_RE.search(str(query or "")):
        return rows
    out: List[Dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        kind = normalize_card_kind(item.get("kind"))
        text = str(item.get("text") or "")
        if kind not in _POLISH_KINDS or not text.strip():
            out.append(item)
            continue
        rewritten = _rewrite_card_text(provider, text, kind=kind)
        if rewritten and _card_rewrite_ok(text, rewritten, kind=kind):
            cloned = dict(item)
            payload = item.get("payload")
            cloned["payload"] = dict(payload) if isinstance(payload, dict) else {}
            cloned["text"] = rewritten
            out.append(cloned)
            continue
        out.append(item)
    return out


def _rewrite_card_text(provider: Any, text: str, *, kind: str) -> str:
    """调用 Provider 改写一张卡。失败返回空串。"""

    prompt = _RESULT_SYSTEM_PROMPT if kind == "result" else _CARD_SYSTEM_PROMPT
    try:
        raw = provider.chat(text, system_prompt=prompt)
    except Exception:
        return ""
    body = str(raw or "").strip()
    fenced = _FENCE_RE.match(body)
    if fenced:
        body = str(fenced.group(1) or "").strip()
    return body


def _card_rewrite_ok(source: str, rewritten: str, *, kind: str) -> bool:
    """改写必须留下标识、数字和错误原文。"""

    body = str(rewritten or "").strip()
    if not body:
        return False
    src_skills = set(_SKILL_RE.findall(source))
    if set(_SKILL_RE.findall(body)) != src_skills:
        return False
    src_plans = set(_PLAN_ID_VALUE_RE.findall(source))
    dst_plans = set(_PLAN_ID_VALUE_RE.findall(body))
    if not src_plans <= dst_plans or not dst_plans <= src_plans:
        return False
    if set(_ERROR_CODE_RE.findall(body)) != set(_ERROR_CODE_RE.findall(source)):
        return False
    if set(_NUMBER_RE.findall(body)) != set(_NUMBER_RE.findall(source)):
        return False
    if not _METRIC_RE.search(source) and _METRIC_RE.search(body):
        return False
    if kind == "result":
        for line in str(source or "").splitlines():
            if not line.startswith("Error:"):
                continue
            message = line[len("Error:") :].strip()
            if message and message not in body:
                return False
    return True


def format_human_cards(
    cards: Sequence[Dict[str, Any]],
    *,
    payload: Optional[Dict[str, Any]] = None,
) -> str:
    """把已投影的人读卡打成 CLI stdout 文本。

    Parameters
    ----------
    cards : sequence of dict
        ``project_human_cards`` 结果。
    payload : dict, optional
        用于 MODE 行。

    Returns
    -------
    str
        末尾换行的英文纯文本。
    """

    raw = payload if isinstance(payload, dict) else {}
    lines: List[str] = [_mode_line(raw, cards)]
    for item in cards or []:
        if not isinstance(item, dict):
            continue
        kind = normalize_card_kind(item.get("kind"))
        text = str(item.get("text") or "").rstrip()
        if text:
            lines.append(text)
        if kind == "clarify":
            blob = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            answer = str(blob.get("answer") or "").strip()
            if answer:
                lines.append(f"Answered: {answer}")
        if kind == "ask":
            sources = []
            blob = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            sources = [str(src) for src in (blob.get("sources") or raw.get("sources") or []) if str(src)]
            if sources:
                lines.append("Sources: " + ", ".join(sources))
    cleaned = [str(line).rstrip() for line in lines if str(line).strip()]
    return "\n".join(cleaned) + "\n"


def _mode_line(payload: Dict[str, Any], cards: Sequence[Dict[str, Any]]) -> str:
    """``[MODE: …]`` 行。"""

    kinds = {normalize_card_kind(item.get("kind")) for item in cards if isinstance(item, dict)}
    if "mode_notice" in kinds and infer_effective_kind(payload) == "ask":
        requested = str(payload.get("requested_mode") or "").strip().upper()
        if requested in {"PLAN", "RUN", "AGENT"}:
            return f"[MODE: ASK]"
    execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
    status = str(execution.get("status") or "")
    exec_steps = [item for item in (execution.get("steps") or []) if isinstance(item, dict)]
    if status in {"success", "partial_failed", "failed"} and exec_steps:
        return "[MODE: RUN]  executed"
    if _is_ask_payload(payload) or "ask" in kinds and "plan_ready" not in kinds:
        if payload.get("mode") == "ask" or infer_effective_kind(payload) == "ask":
            return "[MODE: ASK]"
    notice = next(
        (
            item
            for item in cards
            if isinstance(item, dict) and normalize_card_kind(item.get("kind")) == "mode_notice"
        ),
        None,
    )
    if notice is not None:
        blob = notice.get("payload") if isinstance(notice.get("payload"), dict) else {}
        if str(blob.get("effective_kind") or "") == "usage":
            return "[MODE: NOTICE]"
    if status == "dry_run" or "plan_ready" in kinds:
        return "[MODE: PLAN]  dry_run — not executed"
    mode = str(payload.get("mode") or "").strip().upper()
    if mode:
        return f"[MODE: {mode}]"
    return "[MODE: PLAN]"


def _is_ask_payload(payload: Dict[str, Any]) -> bool:
    """Ask 目标态载荷。"""

    if str(payload.get("mode") or "") == "ask":
        return True
    if "answer" in payload and "plan" not in payload:
        return True
    return False


def _clarification_blob(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """取出澄清 dict。"""

    clar = payload.get("clarification")
    if isinstance(clar, dict) and clar:
        return clar
    plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
    nested = (plan.get("assumptions") or {}).get("clarification") if isinstance(plan.get("assumptions"), dict) else None
    if isinstance(nested, dict) and nested:
        return nested
    return None


def _industry_samples(err: Dict[str, Any]) -> List[str]:
    """从 error.details 取出非空的 Tushare 行业短名。"""

    details = err.get("details") if isinstance(err.get("details"), dict) else {}
    raw = details.get("industry_samples")
    if not isinstance(raw, list):
        return []
    names: List[str] = []
    for item in raw:
        name = str(item).strip()
        if name:
            names.append(name)
    return names


def _error_card_text(err: Dict[str, Any]) -> str:
    """error 卡正文。有行业样例时把短名追加到技能说明后面。"""

    message = str(err.get("message") or "An error occurred.").rstrip()
    samples = _industry_samples(err)
    if not samples:
        return message
    return "\n".join([message, "Sample Tushare industry short names:", *samples])


def _enrich_error(err: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """补英文 next_action。"""

    if not isinstance(err, dict) or not err:
        return err
    out = dict(err)
    if _industry_samples(out) and not str(out.get("next_action") or "").strip():
        out["next_action"] = _INDUSTRY_SAMPLE_NEXT_ACTION
        return out
    if str(out.get("next_action") or "").strip():
        return out
    message = str(out.get("message") or "").lower()
    code = str(out.get("code") or "")
    if code == "ALLOW_GATE_BLOCKED" or "allow_" in message:
        out["next_action"] = (
            "Confirm the plan manually, or enable the matching allow_* flag in profile, then retry."
        )
    elif "token" in message:
        out["next_action"] = "Set the Tushare token in env_facts or profile, then retry this step."
    elif "not found" in message or code.endswith("NOT_FOUND"):
        out["next_action"] = "Create or select a plan in this session, then Confirm."
    else:
        out["next_action"] = _DEFAULT_NEXT_ACTION
    return out


def _first_error(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """第一个英文 error。"""

    if isinstance(payload.get("error"), dict) and payload.get("error"):
        return _enrich_error(dict(payload["error"]))
    execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
    for raw in execution.get("steps") or []:
        if not isinstance(raw, dict):
            continue
        result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
        err = result.get("error")
        if isinstance(err, dict) and err.get("message"):
            return _enrich_error(dict(err))
    return None


def _step_ticks(steps: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """执行打勾摘要。"""

    rows: List[Dict[str, Any]] = []
    for raw in steps or []:
        result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
        ok = result.get("ok")
        if result.get("skipped"):
            status = "skipped"
        elif ok is True:
            status = "done"
        elif ok is False:
            status = "error"
        else:
            status = str(raw.get("status") or "pending")
        rows.append(
            {
                "step_id": str(raw.get("step_id") or ""),
                "skill_name": str(raw.get("skill_name") or ""),
                "status": status,
                "ok": ok,
            }
        )
    return rows


def _plan_step_rows(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """ToolPlan.steps 压成投影用行。"""

    rows: List[Dict[str, Any]] = []
    for raw in plan.get("steps") or []:
        if not isinstance(raw, dict):
            continue
        effects = raw.get("side_effects") if isinstance(raw.get("side_effects"), dict) else {}
        skill = str(raw.get("skill_name") or "")
        rows.append(
            {
                "step_id": str(raw.get("step_id") or ""),
                "skill_name": skill,
                "side_effects": effects,
                "needs_confirm": _step_needs_confirm(skill, effects),
                "inputs": dict(raw.get("inputs") or {}) if isinstance(raw.get("inputs"), dict) else {},
            }
        )
    return rows


def _job_name(plan: Dict[str, Any]) -> str:
    """``planner_trace.intent_job``。"""

    trace = plan.get("planner_trace") if isinstance(plan.get("planner_trace"), dict) else {}
    job = str(trace.get("intent_job") or "").strip()
    return job or "(unknown)"


def _lookup_meta(registry: Any, name: str) -> Any:
    """从 registry 取 SkillMetadata。"""

    if registry is None or not str(name or "").strip():
        return None
    getter = getattr(registry, "get_metadata", None)
    if not callable(getter):
        return None
    try:
        return getter(name)
    except KeyError:
        return None


def _format_calls(skill_name: str, meta: Any, inputs: Dict[str, Any]) -> str:
    """一个 qteasy 入口。"""

    if skill_name == "qt.ai.data.read":
        channel = str((inputs or {}).get("channel") or "history").strip().lower()
        mapped = _DATA_READ_BY_CHANNEL.get(channel)
        if mapped:
            return mapped
    entries = list(getattr(meta, "qteasy_entrypoints", None) or [])
    names = [str(item).strip() for item in entries if str(item).strip()]
    return ", ".join(names) if names else "(none)"


def _format_params(inputs: Dict[str, Any]) -> str:
    """非空 inputs。"""

    if not isinstance(inputs, dict) or not inputs:
        return "(none)"
    parts: List[str] = []
    for key, value in inputs.items():
        if key in _SKIP_INPUT_KEYS:
            continue
        if value is None or value == "" or value == [] or value == {}:
            continue
        parts.append(f"{key}={value}")
    return ", ".join(parts) if parts else "(none)"


def _format_expects(schema: Any) -> str:
    """outputs_schema 一句。"""

    if not isinstance(schema, dict) or not schema:
        return "(unspecified)"
    parts: List[str] = []
    for key, hint in schema.items():
        hint_s = str(hint or "").strip()
        if "list" in hint_s.lower():
            parts.append(f"{key}[] ({hint_s})")
        elif hint_s:
            parts.append(f"{key}: {hint_s}")
        else:
            parts.append(str(key))
    return ", ".join(parts) if parts else "(unspecified)"


def _risk_label(effects: Dict[str, Any], *, needs_confirm: bool = False) -> str:
    """副作用 → 标签。"""

    flags: List[str] = []
    if effects.get("network"):
        flags.append("network")
    if effects.get("filesystem_write"):
        flags.append("writes files")
    if effects.get("local_state_change"):
        flags.append("local state change")
    if effects.get("heavy_compute"):
        flags.append("heavy compute")
    if flags:
        label = ", ".join(flags)
    else:
        desc = str(effects.get("description") or "").strip()
        label = desc if desc else "readonly"
    if needs_confirm:
        return f"{label} (needs confirm)"
    return label


def _overall_risk(effect_rows: Sequence[Dict[str, Any]]) -> str:
    """多步风险并集。"""

    high: List[str] = []
    seen = set()
    for effects in effect_rows:
        row = effects if isinstance(effects, dict) else {}
        for flag, label in (
            ("network", "network"),
            ("filesystem_write", "writes files"),
            ("local_state_change", "local state change"),
            ("heavy_compute", "heavy compute"),
        ):
            if row.get(flag) and label not in seen:
                seen.add(label)
                high.append(label)
    if high:
        return ", ".join(high)
    for effects in effect_rows:
        row = effects if isinstance(effects, dict) else {}
        desc = str(row.get("description") or "").strip()
        if desc:
            return desc
    return "readonly"


def _storage_lines(
    *,
    plan_id: str,
    run_id: str,
    run_file: str,
    plan_md_file: str,
    show_markdown: bool = True,
) -> List[str]:
    """plan_id 与磁盘 run_id 不是同一个值。"""

    lines = ["Storage:"]
    rid = str(run_id or "").strip()
    pid = str(plan_id or "").strip()
    if pid:
        lines.append(f"- plan_id: {pid} (field inside JSON; pass to run --plan-id)")
    if rid:
        lines.append(f"- run_id: {rid} (filename stem; not the plan_id)")
    json_path = str(run_file or "").strip()
    md_path = str(plan_md_file or "").strip()
    if json_path:
        lines.append(f"- JSON: {json_path}")
    elif rid:
        lines.append(f"- JSON: <QTEASY_AI_HOME>/runs/{rid}.json  (default .qteasy/ai/)")
    if show_markdown:
        if md_path:
            lines.append(f"- Markdown: {md_path}")
        elif rid:
            lines.append(f"- Markdown: <QTEASY_AI_HOME>/runs/{rid}.plan.md")
    return lines


def _slim_plan_ready_lines(
    *,
    plan: Dict[str, Any],
    card_steps: Sequence[Dict[str, Any]],
    plan_id: str,
    run_id: str,
    plan_md_file: str,
    confirmable: bool,
) -> List[str]:
    """plan_ready 短通知：已创建、plan_id、风险一句、Artifact、两条缺口。"""

    effects_rows = [dict(step.get("side_effects") or {}) for step in card_steps]
    risk = _overall_risk(effects_rows)
    lines = ["Plan ready."]
    pid = str(plan_id or "").strip()
    if pid:
        lines.append(f"plan_id: {pid}")
    if confirmable and risk not in {"readonly"} and "readonly" not in risk.lower():
        lines.append(f"Risk: {risk} (needs confirm to execute).")
    else:
        label = "read-only" if risk in {"readonly"} or "readonly" in risk.lower() else risk
        lines.append(f"Risk: {label}.")
    md_path = str(plan_md_file or "").strip()
    rid = str(run_id or "").strip()
    if md_path:
        lines.append(f"Artifact: {md_path}")
    elif rid:
        lines.append(f"Artifact: <QTEASY_AI_HOME>/runs/{rid}.plan.md")
    lines.append(
        "To execute, say so in Plan mode (run this plan / 执行上面的计划) or use Confirm."
    )
    lines.append("To discuss only, say just discuss / 本次只讨论 (Ask; no plan).")
    del plan
    return lines


def _slim_result_lines(
    *,
    plan: Dict[str, Any],
    execution: Dict[str, Any],
    registry: Any = None,
) -> List[str]:
    """result 人读句：按 expected_artifact 说明产物，并保留已有标量。"""

    status = str(execution.get("status") or "").strip() or "unknown"
    sentences = [
        sentence
        for sentence in (
            _result_step_sentence(item, registry)
            for item in (execution.get("steps") or [])
            if isinstance(item, dict)
        )
        if sentence
    ]
    lines: List[str] = []
    if status == "success":
        if sentences:
            for sentence in sentences:
                lines.append(f"**Run succeeded.** {sentence}")
                lines.append("")
        else:
            lines.extend(["**Run succeeded.**", "", "No rows or metrics in the result.", ""])
    else:
        lines.extend(["**Run did not finish.**", ""])
        for sentence in sentences:
            lines.append(sentence)
            lines.append("")
        err = _execution_error_message(execution)
        if err:
            lines.extend([f"Error: {err[0]}", "", err[1], ""])
    lines.append("Next: start a new topic, or say run this plan if a plan_id is still current.")
    del plan
    return lines


def _execution_error_message(execution: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """失败步的原文和一句固定解读。没有 message 时不编错误。"""

    for raw in execution.get("steps") or []:
        if not isinstance(raw, dict):
            continue
        result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
        err = result.get("error") if isinstance(result.get("error"), dict) else None
        message = str((err or {}).get("message") or "").strip()
        if not message:
            continue
        return message, _failure_hint(err or {})
    return None


def _failure_hint(err: Dict[str, Any]) -> str:
    """按错误码或原文关键词选一句英文解读。"""

    code = str(err.get("code") or "")
    message = str(err.get("message") or "").lower()
    if code.endswith("NOT_FOUND") or "not found" in message or "unknown" in message:
        return "Check the name, then edit the blue message and send it again."
    if "token" in message:
        return "Set the Tushare token, then edit the blue message and send it again."
    if code == "ALLOW_GATE_BLOCKED" or "allow_" in message:
        return "Confirm the plan manually, or enable the matching allow flag, then edit the blue message and send it again."
    return "Edit the blue message (pencil) and send it again."


def _result_step_sentence(step: Dict[str, Any], registry: Any) -> str:
    """一步成功结果的一句话。失败步或没有事实时为空。"""

    result = step.get("result") if isinstance(step.get("result"), dict) else {}
    if result.get("ok") is False:
        return ""
    skill = str(step.get("skill_name") or result.get("skill_name") or "").strip()
    shown_scalars, shown_counts, row_count = _shown_result_facts(result, _is_data_table(registry, skill))
    description = _artifact_phrase(registry, skill)
    if not description and not shown_scalars and not shown_counts and row_count is None:
        return ""
    if not description:
        description = "A result artifact"
    sentence = description.rstrip(".")
    if row_count is not None:
        sentence = f"{sentence}, with {row_count} rows"
    extras = [f"{key} = {value}" for key, value in shown_scalars]
    extras.extend(f"{count} items" for count in shown_counts)
    if extras:
        return f"{sentence}. {', '.join(extras)}."
    return f"{sentence}."


def _is_data_table(registry: Any, skill_name: str) -> bool:
    """expected_artifact 写明 data table 时才把计数说成 rows。"""

    text = _artifact_phrase(registry, skill_name).lower()
    return "data table" in text


def _artifact_phrase(registry: Any, skill_name: str) -> str:
    """Skill 上的 expected_artifact。没有则空串，不猜类型。"""

    meta = _lookup_meta(registry, skill_name)
    return str(getattr(meta, "expected_artifact", "") or "").strip()


def _shown_result_facts(
    result: Dict[str, Any],
    is_table: bool,
) -> Tuple[List[Tuple[str, str]], List[str], Optional[str]]:
    """最多 3 个标量和 2 个计数。表的 n_rows 或列表长度改说成 rows，不重复。"""

    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    scalars: List[tuple] = []
    counts: List[str] = []
    for key, value in metrics.items():
        text = _scalar_text(value)
        if text is not None:
            scalars.append((str(key), text))
    for key, value in payload.items():
        if str(key) in _SKIP_INPUT_KEYS:
            continue
        if isinstance(value, list):
            counts.append(str(len(value)))
            continue
        text = _scalar_text(value)
        if text is not None:
            scalars.append((str(key), text))
    shown_scalars = scalars[:3]
    shown_counts = counts[:2]
    row_count = None
    if is_table:
        for key, text in shown_scalars:
            if key == "n_rows":
                row_count = text
                shown_scalars = [item for item in shown_scalars if item[0] != "n_rows"]
                break
        if row_count is None and shown_counts:
            row_count = shown_counts[0]
            shown_counts = shown_counts[1:]
    return shown_scalars, shown_counts, row_count


def _format_result_lines(skill_name: str, result: Dict[str, Any], *, skipped: bool) -> List[str]:
    """单步 SkillResult；不编造数值。"""

    if skipped:
        return ["   Result: skipped"]
    if not isinstance(result, dict) or not result:
        return ["   Result: no rows or metrics in the result."]
    err = result.get("error") if isinstance(result.get("error"), dict) else None
    if result.get("ok") is False or err:
        message = ""
        if isinstance(err, dict):
            message = str(err.get("message") or "").strip()
        return ["   Result: FAILED"] + ([f"   Error: {message}"] if message else [])

    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    summary = result.get("data_summary") if isinstance(result.get("data_summary"), dict) else {}
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), list) else []
    warnings = [str(item) for item in (result.get("warnings") or []) if str(item).strip()]

    body: List[str] = []
    if skill_name == "qt.ai.strategy_meta.get":
        sid = str(payload.get("strategy_id") or "").strip()
        stype = str(payload.get("strategy_type") or "").strip()
        header = ", ".join(part for part in (f"id={sid}" if sid else "", f"type={stype}" if stype else "") if part)
        if header:
            body.append(header)
        body.extend(_truncate_text_lines(str(payload.get("doc") or "").strip()))
    elif skill_name == "qt.ai.strategy_meta.list":
        names = [str(item) for item in (payload.get("strategies") or []) if str(item)]
        count = metrics.get("count", len(names))
        body.append(f"{count} built-in ids")
        body.extend(_format_name_list(names))
    elif skill_name in {"qt.ai.data.read", "qt.ai.data.summary_kline"}:
        body.extend(_format_kv_lines(summary, "summary"))
        body.extend(_format_kv_lines(_scalar_metrics(metrics), "metrics"))
    elif skill_name in {"qt.ai.backtest.run_builtin", "qt.ai.optimize.run_builtin"}:
        body.extend(_format_kv_lines(_scalar_metrics(metrics), "metrics"))
        body.extend(_format_kv_lines(summary, "summary"))
        body.extend(_artifact_path_lines(artifacts))
    elif skill_name == "qt.ai.system.fallback":
        for key in ("reason", "hint", "next_step", "missing_info", "fallback_action"):
            value = str(payload.get(key) or "").strip()
            if value:
                body.append(f"{key}: {value}")
    else:
        body.extend(_generic_payload_lines(payload))
        body.extend(_format_kv_lines(summary, "summary"))
        body.extend(_format_kv_lines(_scalar_metrics(metrics), "metrics"))
        body.extend(_artifact_path_lines(artifacts))

    if warnings:
        body.append("warnings: " + "; ".join(warnings[:5]))
    if not body:
        body.append("no rows or metrics in the result.")
    lines = ["   Result:"]
    lines.extend(f"   {line}" if line else "   " for line in body)
    return lines


def _truncate_text_lines(text: str) -> List[str]:
    """截断过长 docstring。"""

    if not text:
        return ["(empty doc)"]
    rows = text.splitlines()
    clipped = False
    if len(rows) > _DOC_LINE_CAP:
        rows = rows[:_DOC_LINE_CAP]
        clipped = True
    joined = "\n".join(rows)
    if len(joined) > _DOC_CHAR_CAP:
        joined = joined[:_DOC_CHAR_CAP].rstrip()
        rows = joined.splitlines()
        clipped = True
    if clipped:
        rows.append("… truncated; use --raw for the full result.")
    return rows


def _format_name_list(names: Sequence[str]) -> List[str]:
    """策略 id 列表。"""

    items = [str(name).strip() for name in names if str(name).strip()]
    extra = 0
    if len(items) > _LIST_NAME_CAP:
        extra = len(items) - _LIST_NAME_CAP
        items = items[:_LIST_NAME_CAP]
    lines = [", ".join(items)] if items else ["(none)"]
    if extra:
        lines.append(f"… {extra} more (use --raw)")
    return lines


def _scalar_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """可打印标量 metrics。"""

    out: Dict[str, Any] = {}
    for key, value in (metrics or {}).items():
        text = _scalar_text(value)
        if text is not None:
            out[str(key)] = text
    return out


def _format_kv_lines(data: Dict[str, Any], label: str) -> List[str]:
    """``label: k=v``。"""

    if not data:
        return []
    parts = [f"{key}={value}" for key, value in data.items()]
    return [f"{label}: " + ", ".join(parts)]


def _artifact_path_lines(artifacts: Sequence[Any]) -> List[str]:
    """只披露路径。"""

    paths: List[str] = []
    for item in artifacts or []:
        if isinstance(item, dict):
            path = str(item.get("path") or item.get("export_path") or "").strip()
            kind = str(item.get("kind") or "").strip()
            if path:
                paths.append(f"{kind}={path}" if kind else path)
        elif str(item).strip():
            paths.append(str(item).strip())
    if not paths:
        return []
    return ["artifacts: " + "; ".join(paths[:8])]


def _generic_payload_lines(payload: Dict[str, Any]) -> List[str]:
    """通用 payload。"""

    if not payload:
        return []
    lines: List[str] = []
    for key, value in payload.items():
        if key in _SKIP_INPUT_KEYS:
            continue
        if isinstance(value, str):
            if _looks_like_type_repr(value):
                continue
            if len(value) > 240:
                lines.extend(_truncate_text_lines(value))
            else:
                lines.append(f"{key}: {value}")
            continue
        text = _scalar_text(value)
        if text is not None:
            lines.append(f"{key}={text}")
            continue
        if isinstance(value, (list, tuple)):
            items = list(value)
            if items and all(isinstance(item, str) for item in items):
                shown = [str(item) for item in items[:_GENERIC_LIST_CAP]]
                extra = len(items) - len(shown)
                line = f"{key}: " + ", ".join(shown)
                if extra > 0:
                    line += f" … +{extra}"
                lines.append(line)
            elif items and all(_scalar_text(item) is not None for item in items[:12]):
                shown = [_scalar_text(item) for item in items[:12]]
                lines.append(f"{key}: " + ", ".join(shown))
            else:
                lines.append(f"{key}: list[{len(items)}]")
            continue
        if isinstance(value, dict):
            scalars = _scalar_metrics(value)
            if scalars and len(scalars) == len(value):
                lines.append(f"{key}: " + ", ".join(f"{k}={v}" for k, v in scalars.items()))
            else:
                lines.append(f"{key}: dict[{len(value)} keys]")
    return lines


def _looks_like_type_repr(text: str) -> bool:
    """``str(type(...))``。"""

    value = str(text or "").strip()
    return value.startswith("<class ") or value.startswith("<module ")


def _scalar_text(value: Any) -> Optional[str]:
    """标量转短字符串。"""

    if value is None or isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return value if len(value) <= 120 else None
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6g}"
    shape = getattr(value, "shape", None)
    item = getattr(value, "item", None)
    if shape == () and callable(item):
        try:
            return _scalar_text(item())
        except Exception:
            return None
    return None
