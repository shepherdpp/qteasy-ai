# coding=utf-8
# ======================================
# File: run_view.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-19
# Desc:
# 同一次 run 的两级可见性。默认是逐步成败、
# 输入摘要和错误原文；调试段只摘已保存的原文。
# ======================================

"""从已保存的 run 投影逐步视图。不调用分类、填槽或质检。"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

_EXECUTED = frozenset({"success", "partial_failed", "failed"})


def project_run_view(run: Mapping[str, Any]) -> Dict[str, Any]:
    """只读这份 run，投影逐步字段和三段调试原文。

    Parameters
    ----------
    run : mapping
        已保存的 run。含 ``plan`` 和 ``execution``。

    Returns
    -------
    dict
        ``steps`` 以及 ``classify_protocol``。trace 里有 ``fill_debug`` 才放进视图。
    """

    plan = run.get("plan") if isinstance(run.get("plan"), Mapping) else {}
    execution = run.get("execution") if isinstance(run.get("execution"), Mapping) else {}
    by_id = _plan_inputs(plan)
    steps: List[Dict[str, Any]] = []
    for raw in execution.get("steps") or []:
        if not isinstance(raw, Mapping):
            continue
        result = raw.get("result") if isinstance(raw.get("result"), Mapping) else {}
        step_id = str(raw.get("step_id") or "")
        err = result.get("error") if isinstance(result.get("error"), Mapping) else {}
        steps.append(
            {
                "step_id": step_id,
                "skill_name": str(raw.get("skill_name") or result.get("skill_name") or ""),
                "ok": result.get("ok"),
                "skipped": bool(result.get("skipped")),
                "input_summary": _input_summary(by_id.get(step_id)),
                "error": str(err.get("message") or "").strip(),
            }
        )
    trace = plan.get("planner_trace") if isinstance(plan.get("planner_trace"), Mapping) else {}
    view: Dict[str, Any] = {
        "steps": steps,
        "classify_protocol": str(trace.get("classify_protocol") or ""),
    }
    fills = trace.get("fill_debug")
    if isinstance(fills, list):
        view["fill_debug"] = [dict(item) for item in fills if isinstance(item, Mapping)]
    return view


def render_run_view(view: Mapping[str, Any], *, debug: bool = False) -> str:
    """把投影打成文本。调试开关只决定三段原文出不出。

    Parameters
    ----------
    view : mapping
        ``project_run_view`` 的结果。产物索引若已写在每步的 ``artifacts`` 上，一并印出。
    debug : bool, default False
        为 True 时附上分类原文、填槽原文和校验拒绝。

    Returns
    -------
    str
        逐步块。没有步骤、也没有调试段时为空串。
    """

    lines: List[str] = []
    for raw in view.get("steps") or []:
        if not isinstance(raw, Mapping):
            continue
        step_id = str(raw.get("step_id") or "")
        skill = str(raw.get("skill_name") or "")
        lines.append(f"Step {step_id} {skill}: ok={raw.get('ok')}")
        lines.append(f"inputs: {raw.get('input_summary') or '(none)'}")
        error = str(raw.get("error") or "").strip()
        if error:
            lines.append(f"Error: {error}")
        lines.extend(_artifact_lines(raw.get("artifacts")))
    body = "\n".join(lines)
    if not debug:
        return body
    extra = ["Classify protocol:", str(view.get("classify_protocol") or "")]
    fills = view.get("fill_debug") if isinstance(view.get("fill_debug"), list) else []
    if fills:
        extra.append("Fill debug:")
        extra.append(json.dumps(fills, ensure_ascii=False))
    tail = "\n".join(extra)
    if body:
        return body + "\n" + tail
    return tail


def stamp_result_cards(
    cards: Sequence[Mapping[str, Any]],
    run: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
) -> List[Any]:
    """把逐步视图和产物索引贴到已执行的结果卡上。

    Parameters
    ----------
    cards : sequence of mapping
        润色和解读之后的人读卡。
    run : mapping
        这次运行的 payload。投影只读它。
    artifacts : sequence of mapping
        ``step_artifact_index`` 的结果。

    Returns
    -------
    list
        结果卡的 payload 多了 ``run_view`` 和 ``steps``。其它卡不动。
    """

    rows = [item for item in (cards or [])]
    execution = run.get("execution") if isinstance(run.get("execution"), Mapping) else {}
    status = str(execution.get("status") or "")
    exec_steps = [item for item in (execution.get("steps") or []) if isinstance(item, Mapping)]
    if status not in _EXECUTED or not exec_steps:
        return rows
    if not any(isinstance(item, Mapping) and item.get("kind") == "result" for item in rows):
        return rows
    view = project_run_view(run)
    by_step: Dict[str, List[Dict[str, str]]] = {}
    for item in artifacts or []:
        if not isinstance(item, Mapping):
            continue
        step_id = str(item.get("step_id") or "")
        by_step.setdefault(step_id, []).append(
            {
                "step_id": step_id,
                "type": str(item.get("type") or ""),
                "title": str(item.get("title") or ""),
                "run_id": str(item.get("run_id") or ""),
                "export_path": str(item.get("export_path") or ""),
            }
        )
    stamped: List[Dict[str, Any]] = []
    for raw in view["steps"]:
        row = dict(raw)
        row["artifacts"] = list(by_step.get(str(raw.get("step_id") or ""), []))
        stamped.append(row)
    out: List[Any] = []
    for item in rows:
        if not isinstance(item, Mapping) or item.get("kind") != "result":
            out.append(dict(item) if isinstance(item, Mapping) else item)
            continue
        cloned = dict(item)
        payload = item.get("payload")
        cloned["payload"] = dict(payload) if isinstance(payload, Mapping) else {}
        cloned["payload"]["run_view"] = view
        cloned["payload"]["steps"] = stamped
        out.append(cloned)
    return out


def _plan_inputs(plan: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    """``step_id`` 到计划步骤上的 inputs。"""

    found: Dict[str, Mapping[str, Any]] = {}
    for raw in plan.get("steps") or []:
        if not isinstance(raw, Mapping):
            continue
        inputs = raw.get("inputs") if isinstance(raw.get("inputs"), Mapping) else {}
        found[str(raw.get("step_id") or "")] = inputs
    return found


def _input_summary(inputs: Optional[Mapping[str, Any]]) -> str:
    """按键名排序拼成 ``key=value``。没有输入时是 ``(none)``。"""

    if not isinstance(inputs, Mapping) or not inputs:
        return "(none)"
    return ", ".join(f"{key}={inputs[key]}" for key in sorted(inputs))


def _artifact_lines(artifacts: Any) -> List[str]:
    """每条产物一行。没有索引就不写。"""

    if not isinstance(artifacts, list):
        return []
    lines: List[str] = []
    for item in artifacts:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title") or "")
        kind = str(item.get("type") or "")
        path = str(item.get("export_path") or "")
        line = f"Artifact: {kind} {title}".rstrip()
        if path:
            line = f"{line} {path}"
        if line != "Artifact:":
            lines.append(line)
    return lines
