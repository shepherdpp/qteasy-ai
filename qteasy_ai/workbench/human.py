# coding=utf-8
# ======================================
# File: human.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-08
# Desc:
# 将 WorkbenchState 渲染为对话区纯文本。
# ======================================

"""CLI / Notebook ``--human`` 渲染。与 Web/TUI 共用 mapper，不调 Planner。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..session import ConversationState
from .dto import WorkbenchMessage, WorkbenchPlanStep, WorkbenchState
from .mapper import map_assistant_payload


def unwrap_raw_payload(payload: Any) -> Dict[str, Any]:
    """从 Assistant 返回值取出 mapper 所需 raw dict。

    Parameters
    ----------
    payload : Any
        ``response_style='raw'`` 的 dict，或 ``AssistantOutput`` / pretty 包装。

    Returns
    -------
    dict
        装配层 raw payload。
    """

    nested = getattr(payload, "raw", None)
    if isinstance(nested, dict) and nested:
        return dict(nested)
    if isinstance(payload, dict):
        inner = payload.get("raw")
        if isinstance(inner, dict) and (
            inner.get("plan") is not None
            or inner.get("mode") == "ask"
            or inner.get("answer") is not None
            or inner.get("execution") is not None
        ):
            return dict(inner)
        return dict(payload)
    return {}


def format_human_error(payload: Dict[str, Any]) -> str:
    """渲染 CLI 4xx 一类的英文错误（未经 mapper）。

    Parameters
    ----------
    payload : dict
        含 ``error.message`` 的 JSON。

    Returns
    -------
    str
        单行或多行英文错误。
    """

    err = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(err, dict):
        message = str(err.get("message") or "").strip()
        if message:
            return message + "\n"
    return "An error occurred.\n"


def format_human(
    state: WorkbenchState,
    *,
    confirm_hint: str = "",
    run_file: str = "",
    plan_md_file: str = "",
    plan: Optional[Dict[str, Any]] = None,
    registry: Any = None,
    query: str = "",
    execution: Optional[Dict[str, Any]] = None,
) -> str:
    """把工作台状态打成用户在对话区应看到的英文文本。

    优先级：错误 → 澄清 → Ask 回答 → 已执行结果解读卡 → Plan 解读卡。
    ``plan.md`` 仍落盘，不作为 human 主文案。不含 Artifact 正文。

    Parameters
    ----------
    state : WorkbenchState
        mapper 投影结果。
    confirm_hint : str, optional
        Notebook ``%%qtai --confirm`` 提示；CLI 缺省写 ``run --plan-id``。
    run_file : str, optional
        ``runs/{run_id}.json`` 绝对路径。
    plan_md_file : str, optional
        ``runs/{run_id}.plan.md`` 绝对路径。
    plan : dict, optional
        装配层 ``plan``（含 ``user_query`` / ``steps[].inputs``）。
    registry : SkillRegistry, optional
        用于 summary / entrypoints / outputs_schema。
    query : str, optional
        本轮问句；``user_query`` 缺失时回退。
    execution : dict, optional
        装配层 ``execution``（含 ``steps[].result``）；DTO 投影不含 payload。

    Returns
    -------
    str
        纯文本，末尾换行。
    """

    lines: List[str] = []
    mode = str(state.mode or "").strip()
    if mode:
        lines.append(f"[MODE: {mode.upper()}]")

    execution_raw = execution if isinstance(execution, dict) else {}
    if not execution_raw:
        execution_raw = state.execution if isinstance(state.execution, dict) else {}
    status = str(execution_raw.get("status") or (state.execution or {}).get("status") or "")
    exec_steps = [item for item in (execution_raw.get("steps") or []) if isinstance(item, dict)]
    executed = status in {"success", "partial_failed", "failed"} and bool(exec_steps)

    err = state.error if isinstance(state.error, dict) else None
    if err and not executed:
        message = str(err.get("message") or "").strip()
        if message:
            lines.append(message)
            return _join(lines)

    clarification = _first_message(state.messages, "clarification")
    if clarification is not None:
        text = str(clarification.text or "").strip()
        if text:
            lines.append(text)
        pending = clarification.payload.get("pending") if isinstance(clarification.payload, dict) else None
        named = False
        if isinstance(pending, list):
            for item in pending:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                hint = str(item.get("hint") or "").strip()
                if name and hint:
                    lines.append(f"- {name}: {hint}")
                    named = True
                elif name:
                    lines.append(f"- {name}")
                    named = True
        missing = [str(item) for item in (state.sidebar.missing or []) if str(item)]
        if missing and not named:
            lines.append("Missing: " + ", ".join(missing))
        return _join(lines)

    ask = _first_message(state.messages, "ask_text")
    if ask is not None:
        text = str(ask.text or "").strip()
        if text:
            lines.append(text)
        sources = [str(item) for item in (state.sources or []) if str(item)]
        if sources:
            lines.append("Sources: " + ", ".join(sources))
        return _join(lines)

    if executed:
        if lines and lines[0].startswith("[MODE:"):
            lines[0] = "[MODE: RUN]  executed"
        lines.extend(
            _run_brief_lines(
                state,
                plan=plan if isinstance(plan, dict) else {},
                execution=execution_raw,
                registry=registry,
                query=query,
            )
        )
        plan_id = ""
        if isinstance(plan, dict):
            plan_id = str(plan.get("plan_id") or "")
        if not plan_id and state.plan_card is not None:
            plan_id = str(state.plan_card.plan_id or "")
        lines.extend(
            _storage_lines(
                plan_id=plan_id,
                run_id=state.run_id,
                run_file=run_file,
                plan_md_file=plan_md_file,
            )
        )
        return _join(lines)

    card = state.plan_card
    if card is not None and (card.steps or str(card.plan_md or "").strip()):
        if lines and lines[0].startswith("[MODE:"):
            lines[0] = "[MODE: PLAN]  dry_run — not executed"
        lines.extend(
            _plan_brief_lines(
                state,
                card_steps=card.steps,
                plan=plan if isinstance(plan, dict) else {},
                registry=registry,
                query=query,
            )
        )
        if card.confirmable and card.plan_id:
            hint = str(confirm_hint or "").strip()
            if hint:
                lines.append(hint)
            else:
                lines.append(f"Confirm: qteasy-ai run --plan-id {card.plan_id}")
        lines.extend(
            _storage_lines(
                plan_id=card.plan_id,
                run_id=state.run_id,
                run_file=run_file,
                plan_md_file=plan_md_file,
            )
        )
        return _join(lines)

    other = next((msg for msg in state.messages if msg.kind != "user_text"), None)
    if other is not None and str(other.text or "").strip():
        lines.append(str(other.text).strip())
        return _join(lines)
    if len(lines) == 1:
        lines.append("No output.")
    return _join(lines)


def format_human_from_payload(
    payload: Any,
    *,
    query: str = "",
    session: Optional[ConversationState] = None,
    env_facts: Optional[Dict[str, Any]] = None,
    confirm_hint: str = "",
    registry: Any = None,
) -> str:
    """raw / pretty 包装 → human 文本。

    Parameters
    ----------
    payload : Any
        Assistant 返回值。
    query : str, optional
        本轮用户句（写入 DTO ``user_text``，human 不回显）。
    session : ConversationState, optional
        侧栏 / missing 真源。
    env_facts : dict, optional
        环境摘要。
    confirm_hint : str, optional
        确认提示覆盖。
    registry : SkillRegistry, optional
        Plan / run 解读卡查 metadata。

    Returns
    -------
    str
        ``format_human`` 文本。
    """

    raw = unwrap_raw_payload(payload)
    state = map_assistant_payload(raw, session=session, query=query, env_facts=env_facts)
    plan = raw.get("plan") if isinstance(raw.get("plan"), dict) else {}
    execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else {}
    return format_human(
        state,
        confirm_hint=confirm_hint,
        run_file=str(raw.get("run_file") or ""),
        plan_md_file=str(raw.get("plan_md_file") or ""),
        plan=plan,
        registry=registry,
        query=query,
        execution=execution,
    )


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


def _run_brief_lines(
    state: WorkbenchState,
    *,
    plan: Dict[str, Any],
    execution: Dict[str, Any],
    registry: Any,
    query: str,
) -> List[str]:
    """用 Job / 参数 / result.payload 拼 run 结果解读卡。

    Parameters
    ----------
    state : WorkbenchState
        含侧栏 job。
    plan : dict
        装配层 plan（``user_query`` / ``steps[].inputs``）。
    execution : dict
        含 ``status`` 与 ``steps[].result``。
    registry : SkillRegistry, optional
        查 summary / entrypoints。
    query : str
        本轮问句回退。

    Returns
    -------
    list of str
        解读卡各行。
    """

    raw_plan_steps = [item for item in (plan.get("steps") or []) if isinstance(item, dict)]
    plan_by_id = {str(item.get("step_id") or ""): item for item in raw_plan_steps}
    exec_steps = [item for item in (execution.get("steps") or []) if isinstance(item, dict)]
    asked = str(plan.get("user_query") or query or "").strip()
    status = str(execution.get("status") or "").strip() or "unknown"
    lines = [f"Job: {_job_name(state, plan)}"]
    if asked:
        lines.append(f"You asked: {asked}")
    lines.append(f"Status: {status}")
    lines.append(f"Steps: {len(exec_steps)}")

    for idx, item in enumerate(exec_steps, start=1):
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        skill_name = str(item.get("skill_name") or result.get("skill_name") or "step")
        step_id = str(item.get("step_id") or "")
        plan_step = plan_by_id.get(step_id)
        if plan_step is None and idx - 1 < len(raw_plan_steps):
            plan_step = raw_plan_steps[idx - 1]
        inputs = {}
        if isinstance(plan_step, dict) and isinstance(plan_step.get("inputs"), dict):
            inputs = dict(plan_step["inputs"])
        echo = result.get("inputs_echo") if isinstance(result.get("inputs_echo"), dict) else {}
        if not inputs and echo:
            inputs = {key: value for key, value in echo.items() if key not in _SKIP_INPUT_KEYS}
        meta = _lookup_meta(registry, skill_name)
        title = str(getattr(meta, "summary", "") or "").strip() or skill_name
        ok = result.get("ok")
        if ok is None:
            ok = bool(item.get("ok")) or str(item.get("status") or "") == "done"
        skipped = bool(result.get("skipped")) or str(item.get("status") or "") == "skipped"
        flag = "skip" if skipped else ("ok" if ok else "x")
        lines.append(f"{idx}. [{flag}] {title}")
        lines.append(f"   Skill: {skill_name}")
        lines.append(f"   Calls: {_format_calls(skill_name, meta, inputs)}")
        lines.append(f"   Parameters: {_format_params(inputs)}")
        lines.extend(_format_result_lines(skill_name, result, skipped=skipped))
    return lines


def _format_result_lines(skill_name: str, result: Dict[str, Any], *, skipped: bool) -> List[str]:
    """把单步 SkillResult 压成 Result 段；不编造数值、不倾倒整表。

    Parameters
    ----------
    skill_name : str
        技能名。
    result : dict
        ``steps[].result``。
    skipped : bool
        是否跳过。

    Returns
    -------
    list of str
        已缩进的 Result 行。
    """

    if skipped:
        return ["   Result: skipped"]
    if not isinstance(result, dict) or not result:
        return ["   Result: (empty)"]
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
        body.append("(no printable result; use --raw)")
    lines = ["   Result:"]
    lines.extend(f"   {line}" if line else "   " for line in body)
    return lines


def _truncate_text_lines(text: str) -> List[str]:
    """截断过长 docstring，并提示 ``--raw``。"""

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
    """策略 id 列表：过多则截断。"""

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
    """只保留可打印标量 metrics。"""

    out: Dict[str, Any] = {}
    for key, value in (metrics or {}).items():
        text = _scalar_text(value)
        if text is not None:
            out[str(key)] = text
    return out


def _format_kv_lines(data: Dict[str, Any], label: str) -> List[str]:
    """把小 dict 打成 ``label: k=v, …``。"""

    if not data:
        return []
    parts = [f"{key}={value}" for key, value in data.items()]
    return [f"{label}: " + ", ".join(parts)]


def _artifact_path_lines(artifacts: Sequence[Any]) -> List[str]:
    """只披露产物路径，不打印文件正文。"""

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
    """通用 payload：标量、短列表、短文本；跳过类型 repr 与嵌套大对象。"""

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
    """判断是否为 ``str(type(...))`` 一类无信息字符串。"""

    value = str(text or "").strip()
    return value.startswith("<class ") or value.startswith("<module ")


def _scalar_text(value: Any) -> Optional[str]:
    """把标量（含 numpy 0-d）转成短字符串；否则 None。"""

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


def _plan_brief_lines(
    state: WorkbenchState,
    *,
    card_steps: Sequence[WorkbenchPlanStep],
    plan: Dict[str, Any],
    registry: Any,
    query: str,
) -> List[str]:
    """用 Job / 步数 / API / 参数拼人读审核卡；不引用 ``plan.md`` 正文。

    Parameters
    ----------
    state : WorkbenchState
        含侧栏 ``active_intent.job``。
    card_steps : sequence of WorkbenchPlanStep
        确认卡步骤。
    plan : dict
        装配层 plan（``user_query`` / ``steps[].inputs`` / ``planner_trace``）。
    registry : SkillRegistry, optional
        查 summary / entrypoints / outputs_schema。
    query : str
        本轮问句回退。

    Returns
    -------
    list of str
        审核卡各行。
    """

    raw_steps = [item for item in (plan.get("steps") or []) if isinstance(item, dict)]
    raw_by_id = {str(item.get("step_id") or ""): item for item in raw_steps}
    steps = list(card_steps or [])
    if not steps and raw_steps:
        steps = [
            WorkbenchPlanStep(
                step_id=str(item.get("step_id") or ""),
                skill_name=str(item.get("skill_name") or ""),
                side_effects=item.get("side_effects") if isinstance(item.get("side_effects"), dict) else {},
            )
            for item in raw_steps
        ]

    asked = str(plan.get("user_query") or query or "").strip()
    effects_rows = []
    for idx, step in enumerate(steps):
        raw = raw_by_id.get(step.step_id)
        if raw is None and idx < len(raw_steps):
            raw = raw_steps[idx]
        effects = step.side_effects if isinstance(step.side_effects, dict) else {}
        if not effects and isinstance(raw, dict) and isinstance(raw.get("side_effects"), dict):
            effects = raw["side_effects"]
        effects_rows.append(effects if isinstance(effects, dict) else {})

    lines = [
        f"Job: {_job_name(state, plan)}",
    ]
    if asked:
        lines.append(f"You asked: {asked}")
    lines.append(f"Steps: {len(steps)}")
    lines.append(f"Overall risk: {_overall_risk(effects_rows)}")

    for idx, step in enumerate(steps, start=1):
        raw = raw_by_id.get(step.step_id)
        if raw is None and idx - 1 < len(raw_steps):
            raw = raw_steps[idx - 1]
        if not isinstance(raw, dict):
            raw = {}
        inputs = raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {}
        effects = effects_rows[idx - 1] if idx - 1 < len(effects_rows) else {}
        meta = _lookup_meta(registry, step.skill_name)
        title = str(getattr(meta, "summary", "") or "").strip() or step.skill_name
        schema = getattr(meta, "outputs_schema", None) if meta is not None else None
        lines.append(f"{idx}. {title}")
        lines.append(f"   Skill: {step.skill_name}")
        lines.append(f"   Calls: {_format_calls(step.skill_name, meta, inputs)}")
        lines.append(f"   Parameters: {_format_params(inputs)}")
        lines.append(f"   Expects: {_format_expects(schema)}")
        lines.append(
            f"   Risk: {_risk_label(effects, needs_confirm=bool(step.needs_confirm))}"
        )
    return lines


def _job_name(state: WorkbenchState, plan: Dict[str, Any]) -> str:
    """优先侧栏 job，其次 ``planner_trace.intent_job``。"""

    intent = state.sidebar.active_intent if state.sidebar is not None else None
    if isinstance(intent, dict):
        job = str(intent.get("job") or "").strip()
        if job:
            return job
    trace = plan.get("planner_trace") if isinstance(plan.get("planner_trace"), dict) else {}
    job = str(trace.get("intent_job") or "").strip()
    return job or "(unknown)"


def _lookup_meta(registry: Any, name: str) -> Any:
    """从 registry 取 SkillMetadata；缺失时返回 None。"""

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
    """选一个用户能懂的 qteasy 入口；``data.read`` 按 channel 只显示一个。"""

    if skill_name == "qt.ai.data.read":
        channel = str((inputs or {}).get("channel") or "history").strip().lower()
        mapped = _DATA_READ_BY_CHANNEL.get(channel)
        if mapped:
            return mapped
    entries = list(getattr(meta, "qteasy_entrypoints", None) or [])
    names = [str(item).strip() for item in entries if str(item).strip()]
    return ", ".join(names) if names else "(none)"


def _format_params(inputs: Dict[str, Any]) -> str:
    """非空 inputs 打成 ``k=v``；全空则为 ``(none)``。"""

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
    """把 ``outputs_schema`` 压成一句；不编造执行数值。"""

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
    """副作用开关 → 人读风险标签。"""

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
    """多步风险取并集；全无开关则为 readonly。"""

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
) -> List[str]:
    """说明 plan_id 与磁盘文件名（run_id）不是同一个值。"""

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
    if md_path:
        lines.append(f"- Markdown: {md_path}")
    elif rid:
        lines.append(f"- Markdown: <QTEASY_AI_HOME>/runs/{rid}.plan.md")
    lines.append("There is no plan_<id>.json; grep runs/*.json for the plan_id.")
    return lines


def _first_message(messages: List[WorkbenchMessage], kind: str) -> Optional[WorkbenchMessage]:
    """按 kind 取第一条。"""

    for item in messages or []:
        if item.kind == kind:
            return item
    return None


def _join(lines: List[str]) -> str:
    """拼接非空行并保证末尾换行。"""

    cleaned = [str(line).rstrip() for line in lines if str(line).strip()]
    return "\n".join(cleaned) + "\n"
