# coding=utf-8
# ======================================
# File: plan_markdown.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-25
# Desc:
# ToolPlan → plan.md 单向人读轨：Mode-R 叙事 + mermaid；可选 LLM Why。
# ======================================

"""将 ToolPlan 渲染为 Markdown 审阅轨（不做反解析）。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from .contracts import ToolPlan, ToolStep

SLOT_WHITELIST = frozenset(
    {
        "shares",
        "start",
        "end",
        "freq",
        "strategy_id",
        "fast",
        "slow",
        "asset_pool",
        "channel",
    }
)
ASSUMPTION_BLACKLIST = frozenset(
    {
        "gold_lock",
        "hybrid_intent",
        "hybrid_intent_h_prime",
        "hybrid_candidate",
        "hybrid_candidate_stage_b0",
        "planner",
        "planner_trace",
        "topic_skipped",
        "hatch",
        "hatch_plan_id",
    }
)
_METRIC_RE = re.compile(
    r"\b(sharpe|drawdown|hit_count|max_drawdown|annual(?:ized)?\s+return|hit count)\b",
    re.IGNORECASE,
)
_SKILL_RE = re.compile(r"qt\.ai\.[a-zA-Z0-9_.]+")
_WHY_HEADING_RE = re.compile(r"^#{1,3}\s*Why this plan\s*", re.IGNORECASE)

SKILL_TITLES = {
    "qt.ai.strategy_meta.list": "List built-in strategies",
    "qt.ai.strategy_meta.get": "Show strategy parameters",
    "qt.ai.data.refill_basic_equity_and_index": "Download daily bars (bounded window)",
    "qt.ai.data.read": "Read market data (history / reference / static)",
    "qt.ai.data.summary_kline": "Summarize k-line statistics",
    "qt.ai.visual.export_kline": "Export a k-line chart",
    "qt.ai.backtest.run_builtin": "Run a built-in backtest",
    "qt.ai.optimize.run_builtin": "Run built-in parameter optimization",
    "qt.ai.strategy.codegen_hybrid": "Generate strategy source from spec",
    "qt.ai.pipeline.live_trade_plan_only": "Live-trade checklist (never auto-executes)",
    "qt.ai.system.fallback": "Need a more specific request",
}

_WHY_SYSTEM_PROMPT = (
    "You write one short English paragraph that explains why this qteasy-ai plan "
    "matches the user request. Output only the paragraph. Do not add a heading. "
    "Use only skill names, slot values, and the plan_id from the fact pack. "
    "Do not invent extra steps, qt.ai skill names, returns, drawdowns, hit counts, "
    "or other metrics."
)


def skill_step_title(skill: str, raw: Optional[Dict[str, Any]] = None) -> str:
    """人话步骤标题：显式 summary 优先，否则内置对照表。

    Parameters
    ----------
    skill : str
        技能注册名。
    raw : dict, optional
        可含 ``summary`` 覆盖标题。

    Returns
    -------
    str
        人话标题；未知 skill 回退为注册名。
    """

    if isinstance(raw, dict):
        explicit = str(raw.get("summary") or "").strip()
        if explicit:
            return explicit
    name = str(skill or "").strip()
    return str(SKILL_TITLES.get(name) or name)


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


def _overall_risk(labels: Sequence[str]) -> str:
    """从逐步副作用标签合成一句风险。"""

    joined = " | ".join(labels)
    lowered = joined.lower()
    if any(
        token in lowered
        for token in ("network", "filesystem_write", "local_state_change", "heavy_compute")
    ):
        return joined
    if "readonly" in lowered or not joined.strip():
        return "read-only"
    return joined or "read-only"


def _normalize_step(step: Any, index: int) -> Dict[str, Any]:
    """把 ToolStep 或 dict 收成渲染用字典。"""

    if isinstance(step, ToolStep):
        return {
            "step_id": str(step.step_id or f"step_{index}"),
            "skill_name": str(step.skill_name or ""),
            "inputs": dict(step.inputs or {}),
            "depends_on": list(step.depends_on or []),
            "side_effects": step.side_effects,
        }
    row = step if isinstance(step, dict) else {}
    return {
        "step_id": str(row.get("step_id") or f"step_{index}"),
        "skill_name": str(row.get("skill_name") or ""),
        "inputs": dict(row.get("inputs") or {}),
        "depends_on": list(row.get("depends_on") or []),
        "side_effects": row.get("side_effects") or {},
    }


def _unpack_plan(plan: Union[ToolPlan, Dict[str, Any]]) -> Dict[str, Any]:
    """从 ToolPlan 或 dict 抽出渲染字段。"""

    if isinstance(plan, ToolPlan):
        return {
            "plan_id": str(plan.plan_id or ""),
            "user_query": str(plan.user_query or ""),
            "assumptions": dict(plan.assumptions or {}),
            "planner_trace": dict(plan.planner_trace or {}),
            "steps": list(plan.steps or []),
        }
    row = plan if isinstance(plan, dict) else {}
    return {
        "plan_id": str(row.get("plan_id") or ""),
        "user_query": str(row.get("user_query") or ""),
        "assumptions": dict(row.get("assumptions") or {}),
        "planner_trace": dict(row.get("planner_trace") or {}),
        "steps": list(row.get("steps") or []),
    }


def _slot_title(name: str) -> str:
    """槽位显示名。"""

    return str(name or "").replace("_", " ")


def _collect_slots(
    assumptions: Dict[str, Any],
    steps: Sequence[Dict[str, Any]],
) -> List[Tuple[str, str]]:
    """白名单用户槽；内部 Hybrid 键永不出现。"""

    collected: Dict[str, str] = {}
    for key, value in (assumptions or {}).items():
        name = str(key or "").strip()
        if name in ASSUMPTION_BLACKLIST:
            continue
        if name not in SLOT_WHITELIST:
            continue
        text = str(value).strip()
        if text:
            collected[name] = text
    for step in steps:
        inputs = step.get("inputs") or {}
        if not isinstance(inputs, dict):
            continue
        for key, value in inputs.items():
            name = str(key or "").strip()
            if name in ASSUMPTION_BLACKLIST or name not in SLOT_WHITELIST:
                continue
            text = str(value).strip()
            if text:
                collected[name] = text
    return [(key, collected[key]) for key in sorted(collected)]


def _skill_title(skill_name: str, registry: Any = None) -> str:
    """对照表优先，其次 registry.summary。"""

    table = skill_step_title(skill_name)
    if table != skill_name:
        return table
    if registry is None:
        return skill_name
    try:
        meta = registry.get_metadata(skill_name)
    except (KeyError, AttributeError, TypeError):
        return skill_name
    summary = str(getattr(meta, "summary", "") or "").strip()
    if not summary:
        return skill_name
    return summary.split(".")[0].strip() or skill_name


def _mermaid_node_id(step_id: str, index: int) -> str:
    """把 step_id 收成 mermaid 节点 id。"""

    raw = re.sub(r"[^A-Za-z0-9_]", "_", str(step_id or "").strip()) or f"step_{index}"
    if raw[0].isdigit():
        return f"n_{raw}"
    return raw


def _escape_mermaid_label(text: str) -> str:
    """去掉会破坏节点标签的字符。"""

    return str(text or "").replace('"', "'").replace("[", "(").replace("]", ")")


def _build_mermaid(steps: Sequence[Dict[str, Any]]) -> str:
    """由 depends_on 生成 flowchart；无依赖则顺序串。"""

    if not steps:
        return "flowchart TD\n  empty[No steps]\n"
    node_ids: List[str] = []
    lines = ["flowchart TD"]
    id_by_step: Dict[str, str] = {}
    for index, step in enumerate(steps, start=1):
        step_id = str(step.get("step_id") or f"step_{index}")
        node_id = _mermaid_node_id(step_id, index)
        node_ids.append(node_id)
        id_by_step[step_id] = node_id
        skill = str(step.get("skill_name") or "")
        label = _escape_mermaid_label(f"{step_id}: {skill}" if skill else step_id)
        lines.append(f'  {node_id}["{label}"]')
    edges: Set[Tuple[str, str]] = set()
    for index, step in enumerate(steps):
        depends = [str(item).strip() for item in (step.get("depends_on") or []) if str(item).strip()]
        target = node_ids[index]
        if depends:
            for dep in depends:
                source = id_by_step.get(dep)
                if source:
                    edges.add((source, target))
        elif index > 0:
            edges.add((node_ids[index - 1], target))
    for source, target in edges:
        lines.append(f"  {source} --> {target}")
    return "\n".join(lines) + "\n"


def _mode_r_body(
    *,
    plan_id: str,
    user_query: str,
    job: str,
    risk: str,
    steps: Sequence[Dict[str, Any]],
    slots: Sequence[Tuple[str, str]],
    registry: Any = None,
) -> str:
    """无 Provider 时的确定性人读正文。"""

    lines: List[str] = ["# Plan", ""]
    if plan_id:
        lines.append(f"plan_id: {plan_id}")
    if user_query:
        lines.append(f"You asked: {user_query}")
    if job:
        lines.append(f"Job: {job}")
    lines.append(f"Risk: {risk}.")
    lines.extend(["", "## What will run", ""])
    if not steps:
        lines.append("_No steps._")
        lines.append("")
    for index, step in enumerate(steps, start=1):
        skill = str(step.get("skill_name") or "")
        title = _skill_title(skill, registry=registry)
        if skill:
            lines.append(f"{index}. {title} (`{skill}`)")
        else:
            lines.append(f"{index}. {title}")
        label = _side_effects_label(step.get("side_effects"))
        lines.append(f"   - Side effects: {label}")
        step_slots = _collect_slots({}, [step])
        if step_slots:
            shown = ", ".join(f"{key}={value}" for key, value in step_slots)
            lines.append(f"   - Inputs: {shown}")
        lines.append("")
    lines.extend(["## Flow", "", "```mermaid", _build_mermaid(steps).rstrip(), "```", ""])
    if slots:
        lines.extend(["## Slots", ""])
        for key, value in slots:
            lines.append(f"- {_slot_title(key)}: {value}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _allowed_skills(steps: Sequence[Dict[str, Any]]) -> Set[str]:
    """本计划出现过的 qt.ai 注册名。"""

    names: Set[str] = set()
    for step in steps:
        skill = str(step.get("skill_name") or "").strip()
        if skill:
            names.add(skill)
    return names


def _why_is_allowed(text: str, *, allowed_skills: Set[str]) -> bool:
    """Why 段不得引入计划外 skill 或明显指标。"""

    body = str(text or "").strip()
    if not body:
        return False
    if _METRIC_RE.search(body):
        return False
    for skill in _SKILL_RE.findall(body):
        if skill not in allowed_skills:
            return False
    return True


def _normalize_why(text: str) -> str:
    """去掉模型可能自带的 Why 标题。"""

    body = str(text or "").strip()
    body = _WHY_HEADING_RE.sub("", body).strip()
    return body


def _llm_why_overlay(
    *,
    provider: Any,
    mode_r: str,
    plan_id: str,
    steps: Sequence[Dict[str, Any]],
) -> str:
    """调用 Provider 叠 Why；失败返回空串。"""

    if provider is None or not hasattr(provider, "chat"):
        return ""
    allowed = _allowed_skills(steps)
    fact_pack = (
        f"plan_id: {plan_id}\n"
        f"allowed_skills: {sorted(allowed)}\n"
        f"mode_r_markdown:\n{mode_r}"
    )
    try:
        raw = provider.chat(fact_pack, system_prompt=_WHY_SYSTEM_PROMPT)
    except Exception:
        return ""
    why = _normalize_why(str(raw or ""))
    if not _why_is_allowed(why, allowed_skills=allowed):
        return ""
    return why


def tool_plan_to_markdown(
    plan: Union[ToolPlan, Dict[str, Any]],
    *,
    provider: Any = None,
    registry: Any = None,
) -> str:
    """将 ToolPlan（对象或 dict）转为 plan.md 文本。

    Mode-R 叙事与 mermaid 必须独立成立。``provider`` 仅用于叠
    ``## Why this plan``；校验失败则丢弃叠段。

    Parameters
    ----------
    plan : ToolPlan or dict
        机器轨计划。
    provider : object, optional
        实现 ``chat(prompt, system_prompt=...)`` 的 LLM Provider。
    registry : object, optional
        可用 ``get_metadata(skill_name)`` 补人话标题。

    Returns
    -------
    str
        人读 Markdown 审阅轨；不是执行真源。
    """

    unpacked = _unpack_plan(plan)
    raw_steps = unpacked["steps"]
    steps = [_normalize_step(item, index) for index, item in enumerate(raw_steps, start=1)]
    slots = _collect_slots(unpacked["assumptions"], steps)
    trace = unpacked["planner_trace"] if isinstance(unpacked["planner_trace"], dict) else {}
    job = str(trace.get("intent_job") or "").strip()
    risk = _overall_risk([_side_effects_label(item.get("side_effects")) for item in steps])
    mode_r = _mode_r_body(
        plan_id=unpacked["plan_id"],
        user_query=unpacked["user_query"],
        job=job,
        risk=risk,
        steps=steps,
        slots=slots,
        registry=registry,
    )
    why = _llm_why_overlay(
        provider=provider,
        mode_r=mode_r,
        plan_id=unpacked["plan_id"],
        steps=steps,
    )
    if not why:
        return mode_r
    header, _, rest = mode_r.partition("\n\n## What will run")
    if not rest:
        return mode_r
    overlay = f"{header}\n\n## Why this plan\n\n{why}\n\n## What will run{rest}"
    if not overlay.endswith("\n"):
        overlay += "\n"
    return overlay
