# coding=utf-8
# ======================================
# File: mapper.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-07
# Desc:
# 将 Assistant raw payload 投影为 WorkbenchState。
# ======================================

"""装配层输出 → 工作台 DTO。不调用 Planner。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..human_card import normalize_card_kind, project_human_cards
from ..plan_markdown import skill_step_title
from ..session import ConversationState
from .dto import (
    WorkbenchArtifact,
    WorkbenchMessage,
    WorkbenchPlanCard,
    WorkbenchPlanStep,
    WorkbenchSidebar,
    WorkbenchSidebarSlot,
    WorkbenchState,
)

_PREVIEW_ROW_CAP = 50

_DEFAULT_NEXT_ACTION = (
    "Fix the issue above, then retry this step. You do not need to start over."
)

_HIGH_SIDE_EFFECT_SKILLS = frozenset(
    {
        "qt.ai.data.refill_basic_equity_and_index",
        "qt.ai.backtest.run_builtin",
        "qt.ai.optimize.run_builtin",
        "qt.ai.strategy.codegen_hybrid",
        "qt.ai.pipeline.live_trade_plan_only",
        "qt.ai.visual.export_kline",
    }
)


def step_needs_confirm(skill_name: str, side_effects: Optional[Dict[str, Any]] = None) -> bool:
    """高副作用 skill 或任一侧效应开关为真时须确认。

    Parameters
    ----------
    skill_name : str
        注册名。
    side_effects : dict, optional
        ToolPlan 步的 side_effects。

    Returns
    -------
    bool
        是否须用户确认后才能 execute。
    """

    name = str(skill_name or "")
    if name in _HIGH_SIDE_EFFECT_SKILLS:
        return True
    effects = side_effects if isinstance(side_effects, dict) else {}
    return bool(
        effects.get("network")
        or effects.get("filesystem_write")
        or effects.get("local_state_change")
        or effects.get("heavy_compute")
    )


def _slice_preview_rows(payload: Any) -> List[Any]:
    """从 payload 切预览行，禁止整表进入 DTO。"""

    if not isinstance(payload, dict):
        return []
    rows = payload.get("preview_rows")
    if isinstance(rows, list):
        return rows[:_PREVIEW_ROW_CAP]
    preview = payload.get("preview")
    if preview in (None, ""):
        return []
    return [preview]


def _read_text_file(path: str, *, cap: int = 200000) -> str:
    """读取策略源码等文本；失败或过大返回空串。"""

    target = Path(str(path or "").strip())
    if not str(target) or not target.is_file():
        return ""
    try:
        if target.stat().st_size > cap:
            return ""
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _image_artifact(arts: List[Any]) -> Optional[Dict[str, Any]]:
    """从 skill artifacts 里挑出图文件。"""

    for item in arts or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        typ = str(item.get("type") or "").strip().lower()
        path = str(item.get("path") or "")
        if typ == "image" or kind in {"image", "chart", "png"}:
            return item
        if path.lower().endswith((".png", ".svg", ".html")):
            return item
    return None


def classify_artifacts(run_id: str, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从 execution.steps 分类 Artifact。

    Parameters
    ----------
    run_id : str
        本次 run。
    steps : list of dict
        Executor 步骤记录。

    Returns
    -------
    list of dict
        ``WorkbenchArtifact.to_dict()`` 列表。
    """

    rid = str(run_id or "").strip()
    items: List[WorkbenchArtifact] = []
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        skill = str(step.get("skill_name") or result.get("skill_name") or "")
        arts = result.get("artifacts") if isinstance(result.get("artifacts"), list) else []
        if skill == "qt.ai.strategy_meta.list":
            payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
            strategies = payload.get("strategies") if isinstance(payload.get("strategies"), list) else []
            summary = result.get("data_summary") if isinstance(result.get("data_summary"), dict) else {}
            if not summary:
                summary = {"count": len(strategies), "first_items": strategies[:10]}
            preview_rows = [{"strategy": str(item)} for item in strategies[:500]]
            items.append(
                WorkbenchArtifact(
                    type="data_table",
                    run_id=rid,
                    title=skill or "built-in strategies",
                    export_path="",
                    preview={
                        "data_summary": summary,
                        "preview_rows": preview_rows,
                    },
                )
            )
            continue
        if skill == "qt.ai.strategy_meta.get":
            payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
            sid = str(payload.get("strategy_id") or "").strip()
            stype = str(payload.get("strategy_type") or "").strip()
            doc = str(payload.get("doc") or "").strip()
            summary = result.get("data_summary") if isinstance(result.get("data_summary"), dict) else {}
            summary = {
                **summary,
                "strategy_id": sid,
                "strategy_type": stype,
                "doc_length": len(doc),
            }
            metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
            if metrics.get("doc_length") is not None:
                summary["doc_length"] = metrics.get("doc_length")
            lines = doc.splitlines()[:200] if doc else []
            preview_rows = [{"line": line} for line in lines if str(line).strip()]
            if not preview_rows:
                preview_rows = [{"line": "(empty documentation)"}]
            items.append(
                WorkbenchArtifact(
                    type="data_table",
                    run_id=rid,
                    title=skill or "strategy details",
                    export_path="",
                    preview={
                        "data_summary": summary,
                        "preview_rows": preview_rows,
                    },
                )
            )
            continue
        if skill in {"qt.ai.data.read", "qt.ai.data.summary_kline"} or (
            isinstance(result.get("data_summary"), dict)
            and skill.startswith("qt.ai.data.")
            and "export" not in skill
            and "refill" not in skill
            and skill
        ):
            summary = result.get("data_summary") if isinstance(result.get("data_summary"), dict) else {}
            preview_rows = _slice_preview_rows(result.get("payload"))
            items.append(
                WorkbenchArtifact(
                    type="data_table",
                    run_id=rid,
                    title=skill or "data_table",
                    export_path="",
                    preview={
                        "data_summary": summary,
                        "preview_rows": preview_rows,
                    },
                )
            )
            continue
        source_art = next(
            (
                item
                for item in arts
                if isinstance(item, dict)
                and str(item.get("kind") or "") == "strategy_source"
            ),
            None,
        )
        if source_art is not None or skill == "qt.ai.strategy.codegen_hybrid":
            path = str((source_art or {}).get("path") or "")
            warnings = [] if path else ["Strategy source path is missing."]
            source = _read_text_file(path)
            if path and not source:
                warnings.append("Strategy source could not be loaded.")
            items.append(
                WorkbenchArtifact(
                    type="strategy_code",
                    run_id=rid,
                    title=skill or "strategy_code",
                    export_path=path,
                    preview={"path": path, "source": source},
                    warnings=warnings,
                )
            )
            continue
        trade_art = next(
            (
                item
                for item in arts
                if isinstance(item, dict)
                and str(item.get("kind") or "") in {"trade_log", "complete_values_file"}
            ),
            None,
        )
        metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        if skill == "qt.ai.backtest.run_builtin" or trade_art is not None:
            path = str((trade_art or {}).get("path") or "")
            items.append(
                WorkbenchArtifact(
                    type="backtest_report",
                    run_id=rid,
                    title=skill or "backtest_report",
                    export_path=path,
                    preview={"metrics": metrics, "path": path},
                )
            )
            image_art = _image_artifact(arts)
            if image_art is not None:
                img_path = str(image_art.get("path") or "")
                warnings = [] if img_path else ["Chart file path is missing."]
                items.append(
                    WorkbenchArtifact(
                        type="chart",
                        run_id=rid,
                        title="qt.ai.backtest.visual",
                        export_path=img_path,
                        preview={"path": img_path},
                        warnings=warnings,
                    )
                )
            continue
        image_art = _image_artifact(arts)
        if image_art is not None or skill == "qt.ai.visual.export_kline":
            path = str((image_art or {}).get("path") or "")
            warnings = [] if path else ["Chart file path is missing."]
            items.append(
                WorkbenchArtifact(
                    type="chart",
                    run_id=rid,
                    title=skill or "chart",
                    export_path=path,
                    preview={"path": path},
                    warnings=warnings,
                )
            )
    return [item.to_dict() for item in items]


def _is_ask_payload(payload: Dict[str, Any]) -> bool:
    """判断 Ask 目标态载荷（无 ToolPlan execute 语义）。"""

    if str(payload.get("mode") or "") == "ask":
        return True
    if "answer" in payload and "plan" not in payload:
        return True
    return False


def _step_summary(skill: str, raw: Dict[str, Any]) -> str:
    """人话步骤标题：payload.summary 优先，否则内置对照表。

    Parameters
    ----------
    skill : str
        注册 skill 名。
    raw : dict
        ToolPlan 步原始 dict。

    Returns
    -------
    str
        确认卡标题；未知 skill 为空串。
    """

    return skill_step_title(skill, raw)


def _plan_steps(plan: Dict[str, Any]) -> List[WorkbenchPlanStep]:
    """ToolPlan.steps → 确认卡步骤。"""

    rows: List[WorkbenchPlanStep] = []
    for raw in plan.get("steps") or []:
        if not isinstance(raw, dict):
            continue
        effects = raw.get("side_effects") if isinstance(raw.get("side_effects"), dict) else {}
        skill = str(raw.get("skill_name") or "")
        rows.append(
            WorkbenchPlanStep(
                step_id=str(raw.get("step_id") or ""),
                skill_name=skill,
                side_effects={
                    "network": bool(effects.get("network")),
                    "filesystem_write": bool(effects.get("filesystem_write")),
                    "local_state_change": bool(effects.get("local_state_change")),
                    "heavy_compute": bool(effects.get("heavy_compute")),
                    "description": str(effects.get("description") or ""),
                },
                needs_confirm=step_needs_confirm(skill, effects),
                status="pending",
                summary=_step_summary(skill, raw),
                inputs=dict(raw.get("inputs") or {}) if isinstance(raw.get("inputs"), dict) else {},
            )
        )
    return rows


def _execution_view(payload: Dict[str, Any]) -> Dict[str, Any]:
    """投影 execution 状态与 steps 打勾列表。"""

    execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
    steps_out: List[Dict[str, Any]] = []
    for raw in execution.get("steps") or []:
        if not isinstance(raw, dict):
            continue
        result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
        ok = result.get("ok")
        if result.get("skipped"):
            status = "skipped"
        elif ok is True:
            status = "done"
        elif ok is False:
            status = "error"
        else:
            status = "pending"
        steps_out.append(
            {
                "step_id": str(raw.get("step_id") or ""),
                "skill_name": str(raw.get("skill_name") or ""),
                "status": status,
                "ok": ok,
            }
        )
    return {
        "status": str(execution.get("status") or ""),
        "steps": steps_out,
        "summary": dict(execution.get("summary") or {})
        if isinstance(execution.get("summary"), dict)
        else {},
    }


def _enrich_error(err: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """为错误补英文 next_action，便于 Retry。

    Parameters
    ----------
    err : dict or None
        装配层 error。

    Returns
    -------
    dict or None
        含 ``next_action`` 的拷贝。
    """

    if not isinstance(err, dict) or not err:
        return err
    out = dict(err)
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


def _first_step_error(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """取第一个英文 error。"""

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


def _sidebar_from_session(
    session: Optional[ConversationState],
    payload: Dict[str, Any],
    env_facts: Optional[Dict[str, Any]] = None,
) -> WorkbenchSidebar:
    """投影侧栏。"""

    session_blob = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    if session is None:
        return WorkbenchSidebar(
            active_intent=None,
            slots=[],
            missing=[str(item) for item in (session_blob.get("missing") or [])],
            env_summary=dict(env_facts or {}),
            current_plan_id=str(session_blob.get("current_plan_id") or ""),
            clarify_round=int(session_blob.get("clarify_round") or 0),
            design=dict(session_blob["active_design"])
            if isinstance(session_blob.get("active_design"), dict)
            else None,
            trial_queue=list(session_blob.get("trial_queue") or []),
        )
    slots = [
        WorkbenchSidebarSlot(
            name=name,
            value=slot.value,
            source=slot.source,
            confirmed=slot.confirmed,
        )
        for name, slot in (session.slots or {}).items()
    ]
    return WorkbenchSidebar(
        active_intent=dict(session.active_intent) if session.active_intent else None,
        slots=slots,
        missing=list(session.missing),
        env_summary=dict(env_facts or {}),
        current_plan_id=str(session.current_plan_id or ""),
        clarify_round=int(session.clarify_round),
        design=dict(session.active_design) if session.active_design else None,
        trial_queue=list(session.trial_queue or []),
    )


def _cards_to_messages(cards: Any) -> List[WorkbenchMessage]:
    """人读卡 list → WorkbenchMessage。"""

    rows: List[WorkbenchMessage] = []
    for item in cards or []:
        if not isinstance(item, dict):
            continue
        kind = normalize_card_kind(item.get("kind"))
        if not kind:
            continue
        payload = dict(item.get("payload") or {}) if isinstance(item.get("payload"), dict) else {}
        rows.append(WorkbenchMessage(kind=kind, text=str(item.get("text") or ""), payload=payload))
    return rows


def _messages_from_payload(raw: Dict[str, Any], query: str) -> List[WorkbenchMessage]:
    """优先消费内核卡，缺失时现场投影同一套规则。"""

    cards = raw.get("human_cards")
    if not isinstance(cards, list) or not cards:
        cards = project_human_cards(
            raw,
            requested_mode=str(raw.get("requested_mode") or ""),
            query=query,
        )
    return _cards_to_messages(cards)


def _plan_review_artifact(raw: Dict[str, Any], run_id: str, session_id: str) -> Optional[WorkbenchArtifact]:
    """Plan dry-run 的 plan.md 审阅 Artifact。"""

    execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else {}
    if str(execution.get("status") or "") != "dry_run":
        return None
    md = str(raw.get("plan_md") or "")
    path = str(raw.get("plan_md_file") or "")
    if not md and not path:
        return None
    cap = 200000
    preview_md = md[:cap] if md else ""
    return WorkbenchArtifact(
        type="plan",
        run_id=str(run_id or ""),
        title="plan.md",
        export_path=path,
        preview={"markdown": preview_md, "path": path},
        session_id=session_id,
    )


def map_assistant_payload(
    payload: Dict[str, Any],
    *,
    session: Optional[ConversationState] = None,
    query: str = "",
    env_facts: Optional[Dict[str, Any]] = None,
) -> WorkbenchState:
    """把 ``ask`` / ``plan`` / ``run`` raw dict 投影为工作台状态。

    Parameters
    ----------
    payload : dict
        ``response_style='raw'`` 的 Assistant 输出。
    session : ConversationState, optional
        F 会话；侧栏真源。
    query : str, optional
        本轮用户输入，写入 ``user_text``。
    env_facts : dict, optional
        侧栏数据状态摘要。

    Returns
    -------
    WorkbenchState
        可 JSON 化的工作台状态。
    """

    raw = dict(payload or {})
    sid = ""
    if session is not None:
        sid = session.session_id
    elif isinstance(raw.get("session"), dict):
        sid = str(raw["session"].get("session_id") or "")

    messages = _messages_from_payload(raw, query)

    if _is_ask_payload(raw):
        sources = [str(item) for item in (raw.get("sources") or [])]
        err = _enrich_error(raw.get("error") if isinstance(raw.get("error"), dict) else None)
        return WorkbenchState(
            mode="ask",
            session_id=sid,
            messages=messages,
            plan_card=None,
            sidebar=_sidebar_from_session(session, raw, env_facts),
            artifacts=[],
            execution={"status": "", "steps": []},
            error=dict(err) if err else None,
            run_id="",
            sources=sources,
        )

    plan = raw.get("plan") if isinstance(raw.get("plan"), dict) else {}
    plan_md = str(raw.get("plan_md") or "")
    assumptions = plan.get("assumptions") if isinstance(plan.get("assumptions"), dict) else {}
    card_steps = _plan_steps(plan)
    needs = any(step.needs_confirm for step in card_steps)
    clarification = raw.get("clarification")
    if not isinstance(clarification, dict):
        clarification = (plan.get("assumptions") or {}).get("clarification")
    if isinstance(clarification, dict) and clarification:
        pending = clarification.get("pending") or []
        missing_from_pending = [
            str(item.get("name") or "")
            for item in pending
            if isinstance(item, dict) and item.get("name")
        ]
    else:
        missing_from_pending = []

    execution = _execution_view(raw)
    # Confirm 是可选快捷，不作为 incomplete 门；澄清 fallback 仍不可点 Confirm。
    confirmable = str(execution.get("status") or "") == "dry_run" and bool(card_steps)
    if isinstance(clarification, dict) and clarification:
        skills = [step.skill_name for step in card_steps]
        if skills and all(name == "qt.ai.system.fallback" for name in skills):
            confirmable = False

    plan_card = None
    skip_status_card = (
        (bool(assumptions.get("design_loop")) and not card_steps)
        or bool(assumptions.get("open_job_cleared"))
        or bool(assumptions.get("open_idle"))
    )
    if (card_steps or plan.get("plan_id")) and not skip_status_card:
        plan_card = WorkbenchPlanCard(
            plan_id=str(plan.get("plan_id") or ""),
            steps=card_steps,
            plan_md="",
            confirmable=confirmable,
            needs_confirm=needs,
        )

    err = _first_step_error(raw)
    blocked = (plan.get("assumptions") or {}).get("allow_gate_blocked")
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

    run_id = str(raw.get("run_id") or (raw.get("execution") or {}).get("run_id") or "")
    exec_steps = []
    if isinstance(raw.get("execution"), dict):
        exec_steps = list(raw["execution"].get("steps") or [])
    artifacts = classify_artifacts(run_id, exec_steps) if exec_steps else []
    tagged = []
    for item in artifacts:
        art = _artifact_from_dict(item)
        art.session_id = sid
        tagged.append(art)
    plan_art = _plan_review_artifact(raw, run_id, sid)
    if plan_art is not None:
        tagged.insert(0, plan_art)

    sidebar = _sidebar_from_session(session, raw, env_facts)
    if missing_from_pending and not sidebar.missing:
        sidebar.missing = missing_from_pending
    trace = plan.get("planner_trace") if isinstance(plan.get("planner_trace"), dict) else {}
    job = str(trace.get("intent_job") or "")
    if job and sidebar.active_intent is None:
        sidebar.active_intent = {"job": job, "flags": {}}

    mode = str(plan.get("mode") or raw.get("mode") or "plan")
    if mode not in {"ask", "plan", "run", "agent"}:
        mode = "plan"

    return WorkbenchState(
        mode=mode,
        session_id=sid,
        messages=messages,
        plan_card=plan_card,
        sidebar=sidebar,
        artifacts=tagged,
        execution=execution,
        error=err,
        run_id=run_id,
        sources=[],
    )


def _artifact_from_dict(item: Dict[str, Any]) -> WorkbenchArtifact:
    """dict → WorkbenchArtifact。"""

    return WorkbenchArtifact(
        type=str(item.get("type") or ""),
        run_id=str(item.get("run_id") or ""),
        title=str(item.get("title") or ""),
        export_path=str(item.get("export_path") or ""),
        preview=dict(item.get("preview") or {}),
        warnings=list(item.get("warnings") or []),
        session_id=str(item.get("session_id") or ""),
    )
