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
    r"(\b(sharpe|drawdown|hit_count|max_drawdown|annual(?:ized)?\s+return|hit count)\b|回撤|夏普)",
    re.IGNORECASE,
)
_SOURCE_LABEL = {
    "user": "user",
    "profile": "profile",
    "kernel": "kernel",
    "ai_default": "AI default",
}
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
_ZH_SYSTEM_PROMPT = (
    "Rewrite this qteasy-ai plan review into Simplified Chinese markdown. "
    "Keep every qt.ai skill id and every parameter value unchanged. "
    "Do not add steps, returns, drawdowns, hit counts, or a mermaid diagram. "
    "Output the rewritten prose only."
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


def plan_artifact_title(plan_id: str, steps: Optional[Sequence[Any]] = None) -> str:
    """Plan Artifact 显示名：第一步人话标题 + plan_id 短 hex。

    Parameters
    ----------
    plan_id : str
        JSON 内 ``plan_id``（``plan_`` + hex），不是文件名。
    steps : sequence, optional
        ``ToolStep`` 或含 ``skill_name`` 的 dict。

    Returns
    -------
    str
        如 ``List built-in strategies · af7f4f6a``；无 skill 时 ``Plan · <hex>``。
    """

    raw_id = str(plan_id or "").strip()
    hex_part = raw_id[5:] if raw_id.lower().startswith("plan_") else raw_id
    short = (hex_part or "plan")[:8]
    first_skill = ""
    first_raw: Optional[Dict[str, Any]] = None
    for step in steps or []:
        if isinstance(step, dict):
            first_skill = str(step.get("skill_name") or "").strip()
            first_raw = step
            break
        first_skill = str(getattr(step, "skill_name", "") or "").strip()
        summary = str(getattr(step, "summary", "") or "").strip()
        first_raw = {"summary": summary} if summary else None
        if first_skill:
            break
    label = skill_step_title(first_skill, first_raw) if first_skill else "Plan"
    if not str(label or "").strip():
        label = "Plan"
    return f"{label} · {short}"


def run_group_title(run_id: str, steps: Optional[Sequence[Any]] = None) -> str:
    """孤儿 run 显示名：第一步人话标题 + run_id 短 hex。

    Parameters
    ----------
    run_id : str
        ``run_`` + hex。不是文件名。
    steps : sequence, optional
        执行步骤或计划步骤。只认字符串 ``summary``，字典汇总不覆盖人话标题。

    Returns
    -------
    str
        如 ``Read market data (history / reference / static) · 5632abcd``；
        无步骤时 ``Run · <hex>``。
    """

    raw_id = str(run_id or "").strip()
    hex_part = raw_id[4:] if raw_id.lower().startswith("run_") else raw_id
    short = (hex_part or "run")[:8]
    first_skill = ""
    first_raw: Optional[Dict[str, Any]] = None
    for step in steps or []:
        if isinstance(step, dict):
            first_skill = str(step.get("skill_name") or "").strip()
            summary = step.get("summary")
            first_raw = {"summary": summary} if isinstance(summary, str) and summary.strip() else None
            break
        first_skill = str(getattr(step, "skill_name", "") or "").strip()
        summary = getattr(step, "summary", "")
        summary_text = summary.strip() if isinstance(summary, str) else ""
        first_raw = {"summary": summary_text} if summary_text else None
        if first_skill:
            break
    label = skill_step_title(first_skill, first_raw) if first_skill else "Run"
    if not str(label or "").strip():
        label = "Run"
    return f"{label} · {short}"


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
    *,
    extra: Optional[Set[str]] = None,
) -> List[Tuple[str, str]]:
    """白名单用户槽，外加当前 Job 声明过的槽。内部 Hybrid 键永不出现。"""

    allowed = set(SLOT_WHITELIST)
    allowed.update(str(name) for name in (extra or set()) if str(name).strip())
    collected: Dict[str, str] = {}
    for key, value in (assumptions or {}).items():
        name = str(key or "").strip()
        if name in ASSUMPTION_BLACKLIST:
            continue
        if name not in allowed:
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
            if name in ASSUMPTION_BLACKLIST or name not in allowed:
                continue
            text = str(value).strip()
            if text:
                collected[name] = text
    return [(key, collected[key]) for key in sorted(collected)]


def _job_slot_meta(job: str) -> Dict[str, Dict[str, str]]:
    """当前 Job 的槽 label 与 hint。没有声明时为空。"""

    name = str(job or "").strip()
    if not name:
        return {}
    from .intents import load_default_catalog

    rows = load_default_catalog().job_slots(name)
    meta: Dict[str, Dict[str, str]] = {}
    for item in rows:
        slot = str(item.get("name") or "").strip()
        if not slot:
            continue
        meta[slot] = {
            "label": str(item.get("label") or slot),
            "hint": str(item.get("hint") or "").strip(),
        }
    return meta


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


def _source_label(sources: Dict[str, str], key: str, default: str) -> str:
    """把来源键译成英文标签。"""

    raw = str((sources or {}).get(key) or default)
    return _SOURCE_LABEL.get(raw, raw or default)


def _optimize_lines(step: Dict[str, Any], sources: Dict[str, str]) -> List[str]:
    """优化步骤：AI 默认与日期来源。不写未跑出的最优值。"""

    inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
    method = inputs.get("opti_method", "montecarlo")
    count = inputs.get("opti_sample_count", 32)
    lines = [
        (
            "   - Optimized settings: "
            f"opti_method={method} ({_source_label(sources, 'opti_method', 'ai_default')}), "
            f"opti_sample_count={count} ({_source_label(sources, 'opti_sample_count', 'ai_default')})"
        ),
        "   - Search space: strategy parameters with opt_tag 1 or 2.",
    ]
    start = inputs.get("invest_start") or inputs.get("start")
    end = inputs.get("invest_end") or inputs.get("end")
    if start or end:
        lines.append(
            "   - Dates: "
            f"invest_start={start or 'unset'} ({_source_label(sources, 'invest_start', 'user')}), "
            f"invest_end={end or 'unset'} ({_source_label(sources, 'invest_end', 'user')})"
        )
    else:
        lines.append(
            "   - Dates: not set in the plan; the kernel window is used at run time (source: kernel)."
        )
    return lines


def _lookup_skill_meta(skill_name: str, registry: Any = None) -> Any:
    """从 registry 取技能元数据；没有注册表或未注册时返回 None。"""

    if registry is None or not str(skill_name or "").strip():
        return None
    try:
        return registry.get_metadata(skill_name)
    except (KeyError, AttributeError, TypeError):
        return None


def _side_effect_flags(side_effects: Any) -> Tuple[bool, bool, bool, str]:
    """抽出网络、写文件、本地状态与说明。"""

    if isinstance(side_effects, dict):
        network = bool(side_effects.get("network", False))
        filesystem_write = bool(side_effects.get("filesystem_write", False))
        local_change = bool(side_effects.get("local_state_change", False))
        description = str(side_effects.get("description") or "").strip()
    else:
        network = bool(getattr(side_effects, "network", False))
        filesystem_write = bool(getattr(side_effects, "filesystem_write", False))
        local_change = bool(getattr(side_effects, "local_state_change", False))
        description = str(getattr(side_effects, "description", "") or "").strip()
    return network, filesystem_write, local_change, description


def _reads_writes_line(skill: str, side_effects: Any, registry: Any = None) -> str:
    """人话读写：入口名，以及下载或写文件。"""

    meta = _lookup_skill_meta(skill, registry)
    entries: List[str] = []
    if meta is not None:
        raw_entries = getattr(meta, "qteasy_entrypoints", None) or []
        entries = [str(item).strip() for item in raw_entries if str(item).strip()]
    network, filesystem_write, local_change, description = _side_effect_flags(side_effects)
    bits: List[str] = []
    if entries:
        named = ", ".join(f"`{item}`" for item in entries)
        if network or filesystem_write or local_change:
            bits.append(f"uses {named}")
        else:
            bits.append(f"reads {named}")
    if network:
        bits.append("downloads data")
    if filesystem_write:
        bits.append("writes files")
    elif local_change:
        bits.append("changes local data")
    generic = description.lower() in {"", "readonly", "readonly insight"}
    if description and not generic:
        bits.append(description)
    elif not bits:
        bits.append(description or "read-only")
    return "; ".join(bits)


def _expected_output(skill: str, registry: Any = None) -> str:
    """预期产物句。

    优先 ``expected_artifact``。字段为空时用 summary 与第一个入口名合成。
    没有 registry 时只写 ``Calls {skill}.``，不用通用空话。
    """

    meta = _lookup_skill_meta(skill, registry)
    name = str(skill or "").strip()
    if meta is None:
        if name:
            return f"Calls {name}."
        return "Calls this step."
    text = str(getattr(meta, "expected_artifact", "") or "").strip()
    if text:
        return text
    summary = str(getattr(meta, "summary", "") or "").strip()
    raw_entries = getattr(meta, "qteasy_entrypoints", None) or []
    entries = [str(item).strip() for item in raw_entries if str(item).strip()]
    entry = entries[0] if entries else (name or "this step")
    if summary:
        return f"{summary} Calls {entry}."
    return f"Calls {entry}."


def _mode_r_body(
    *,
    plan_id: str,
    user_query: str,
    job: str,
    risk: str,
    steps: Sequence[Dict[str, Any]],
    slots: Sequence[Tuple[str, str]],
    sources: Optional[Dict[str, str]] = None,
    registry: Any = None,
    slot_meta: Optional[Dict[str, Dict[str, str]]] = None,
) -> str:
    """无 Provider 时的确定性人读正文。"""

    source_map = dict(sources or {})
    meta = dict(slot_meta or {})
    declared = set(meta)
    lines: List[str] = ["# Plan", ""]
    if plan_id:
        lines.append(f"plan_id: {plan_id}")
    if user_query:
        lines.append(f"You asked: {user_query}")
    if job:
        lines.append(f"Job: {job}")
    lines.append(f"Risk: {risk}.")
    lines.extend(["", "## What will run", ""])
    inventory: List[str] = []
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
        if skill:
            lines.append(f"   - Calls: `{skill}`")
        else:
            lines.append("   - Calls: this step")
        reads = _reads_writes_line(skill, step.get("side_effects"), registry)
        lines.append(f"   - Reads / writes: {reads}")
        expect = _expected_output(skill, registry)
        lines.append(f"   - Expected output: {expect}")
        if skill:
            inventory.append(f"- {title} (`{skill}`): {expect}")
        else:
            inventory.append(f"- {title}: {expect}")
        step_slots = _collect_slots({}, [step], extra=declared)
        if step_slots:
            shown = ", ".join(f"{key}={value}" for key, value in step_slots)
            lines.append(f"   - Inputs: {shown}")
        if skill == "qt.ai.optimize.run_builtin":
            lines.extend(_optimize_lines(step, source_map))
        lines.append("")
    lines.extend(["## Flow", "", "```mermaid", _build_mermaid(steps).rstrip(), "```", ""])
    if slots:
        lines.extend(["## Slots", ""])
        for key, value in slots:
            row = meta.get(key) or {}
            title = str(row.get("label") or _slot_title(key))
            lines.append(f"- {title}: {value}")
            hint = str(row.get("hint") or "").strip()
            if hint:
                lines.append(f"  {hint}")
        lines.append("")
    lines.extend(["## Expected result", ""])
    if inventory:
        lines.extend(inventory)
        lines.append("")
    else:
        lines.extend(["_No step artifacts._", ""])
    lines.extend(
        [
            "## Confirm",
            "",
            "Nothing runs until you confirm. "
            "Editing this description does not change the plan that will run.",
            "",
        ]
    )
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


def _mermaid_fence(mode_r: str) -> str:
    """取出 Mode-R 里由代码生成的 mermaid 块。"""

    match = re.search(r"```mermaid\n.*?```", mode_r, flags=re.DOTALL)
    if not match:
        return ""
    return match.group(0)


def _llm_language_overlay(
    *,
    provider: Any,
    mode_r: str,
    plan_id: str,
    steps: Sequence[Dict[str, Any]],
) -> str:
    """中文问句时改写散文；失败返回空串。框图仍用 Mode-R 原块。"""

    if provider is None or not hasattr(provider, "chat"):
        return ""
    allowed = _allowed_skills(steps)
    fact_pack = (
        f"plan_id: {plan_id}\n"
        f"allowed_skills: {sorted(allowed)}\n"
        f"mode_r_markdown:\n{mode_r}"
    )
    try:
        raw = provider.chat(fact_pack, system_prompt=_ZH_SYSTEM_PROMPT)
    except Exception:
        return ""
    body = str(raw or "").strip()
    if not _why_is_allowed(body, allowed_skills=allowed):
        return ""
    for skill in allowed:
        if skill not in body:
            return ""
    body = re.sub(r"```mermaid\n.*?```", "", body, flags=re.DOTALL).strip()
    fence = _mermaid_fence(mode_r)
    if fence:
        body = f"{body}\n\n{fence}"
    if not body.endswith("\n"):
        body += "\n"
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

    Mode-R 叙事与 mermaid 必须独立成立。英文问句时 ``provider`` 只叠
    ``## Why this plan``。中文问句时改写散文并保留代码生成的 mermaid；
    校验失败则留英文 Mode-R。

    Parameters
    ----------
    plan : ToolPlan or dict
        机器轨计划。
    provider : object, optional
        实现 ``chat(prompt, system_prompt=...)`` 的 LLM Provider。
    registry : object, optional
        可用 ``get_metadata(skill_name)`` 补人话标题、读写入口与 ``expected_artifact``。

    Returns
    -------
    str
        人读 Markdown 审阅轨；不是执行真源。
    """

    unpacked = _unpack_plan(plan)
    raw_steps = unpacked["steps"]
    steps = [_normalize_step(item, index) for index, item in enumerate(raw_steps, start=1)]
    assumptions = unpacked["assumptions"] if isinstance(unpacked["assumptions"], dict) else {}
    raw_sources = assumptions.get("input_sources")
    sources = dict(raw_sources) if isinstance(raw_sources, dict) else {}
    trace = unpacked["planner_trace"] if isinstance(unpacked["planner_trace"], dict) else {}
    job = str(trace.get("intent_job") or "").strip()
    slot_meta = _job_slot_meta(job)
    slots = _collect_slots(assumptions, steps, extra=set(slot_meta))
    risk = _overall_risk([_side_effects_label(item.get("side_effects")) for item in steps])
    mode_r = _mode_r_body(
        plan_id=unpacked["plan_id"],
        user_query=unpacked["user_query"],
        job=job,
        risk=risk,
        steps=steps,
        slots=slots,
        sources=sources,
        registry=registry,
        slot_meta=slot_meta,
    )
    if provider is not None and re.search(r"[\u4e00-\u9fff]", unpacked["user_query"]):
        rewritten = _llm_language_overlay(
            provider=provider,
            mode_r=mode_r,
            plan_id=unpacked["plan_id"],
            steps=steps,
        )
        if rewritten:
            return rewritten
        return mode_r
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
