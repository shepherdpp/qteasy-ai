# coding=utf-8
# ======================================
# File: plan_markdown.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-25
# Desc:
# ToolPlan → plan.md 单向人读轨生成。
# ======================================

"""将 ToolPlan 渲染为 Markdown 人读轨（不做反解析）。"""

from __future__ import annotations

from typing import Any, Dict, List, Union

from .contracts import ToolPlan, ToolStep


def _side_effects_label(side_effects: Any) -> str:
    """将副作用结构压缩为一行标签。"""

    if isinstance(side_effects, dict):
        network = side_effects.get("network", False)
        fs = side_effects.get("filesystem_write", False)
        local = side_effects.get("local_state_change", False)
        heavy = side_effects.get("heavy_compute", False)
        desc = side_effects.get("description", "") or ""
    else:
        network = getattr(side_effects, "network", False)
        fs = getattr(side_effects, "filesystem_write", False)
        local = getattr(side_effects, "local_state_change", False)
        heavy = getattr(side_effects, "heavy_compute", False)
        desc = getattr(side_effects, "description", "") or ""
    flags: List[str] = []
    if network:
        flags.append("network")
    if fs:
        flags.append("filesystem_write")
    if local:
        flags.append("local_state_change")
    if heavy:
        flags.append("heavy_compute")
    if not flags:
        flags.append(desc or "readonly")
    return ", ".join(flags)


def tool_plan_to_markdown(plan: Union[ToolPlan, Dict[str, Any]]) -> str:
    """将 ToolPlan（对象或 dict）转为 plan.md 文本。

    Parameters
    ----------
    plan : ToolPlan or dict
        机器轨计划。

    Returns
    -------
    str
        人读 Markdown；字段含 mode、assumptions、逐步 skill/inputs/side_effects/depends_on。
    """

    if isinstance(plan, ToolPlan):
        plan_id = plan.plan_id
        user_query = plan.user_query
        mode = plan.mode
        execution_mode = plan.execution_mode
        assumptions = plan.assumptions or {}
        steps: List[Any] = list(plan.steps)
    else:
        plan_id = str(plan.get("plan_id", ""))
        user_query = str(plan.get("user_query", ""))
        mode = str(plan.get("mode", "plan"))
        execution_mode = str(plan.get("execution_mode", "dry_run"))
        assumptions = plan.get("assumptions") or {}
        steps = list(plan.get("steps") or [])

    lines: List[str] = [
        f"# ToolPlan `{plan_id}`",
        "",
        f"- **mode**: `{mode}`",
        f"- **execution_mode**: `{execution_mode}`",
        f"- **user_query**: {user_query}",
        "",
        "## Assumptions",
        "",
    ]
    if assumptions:
        for key, value in assumptions.items():
            lines.append(f"- `{key}`: `{value}`")
    else:
        lines.append("- _(none)_")
    lines.extend(["", "## Steps", ""])
    if not steps:
        lines.append("_No steps._")
    for idx, step in enumerate(steps, start=1):
        if isinstance(step, ToolStep):
            step_id = step.step_id
            skill_name = step.skill_name
            inputs = step.inputs
            depends_on = step.depends_on
            side_effects = step.side_effects
        else:
            step_id = step.get("step_id", f"step_{idx}")
            skill_name = step.get("skill_name", "")
            inputs = step.get("inputs") or {}
            depends_on = step.get("depends_on") or []
            side_effects = step.get("side_effects") or {}
        lines.append(f"### {idx}. `{step_id}` — `{skill_name}`")
        lines.append("")
        lines.append(f"- **side_effects**: {_side_effects_label(side_effects)}")
        lines.append(f"- **depends_on**: `{depends_on}`")
        lines.append(f"- **inputs**: `{inputs}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
