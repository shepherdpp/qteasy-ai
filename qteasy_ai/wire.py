# coding=utf-8
# ======================================
# File: wire.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-07
# Desc:
# 步骤图的线格式检查：补形状开关，接不上就拒绝。
# 不插入转换步，也不再向模型要第二张图。
# ======================================

"""对齐已声明技能之间的 payload 键和 Python 类型。

两边都声明了才检查。形状开关是图常量：后继需要另一种已经声明的产出时写上，
没有后继就留着库默认。开放图接不上时出选择卡；闭合菜谱接不上是菜谱错误。
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .contracts import Wire
from .plan_markdown import skill_step_title
from .wires import PANEL

_CJK = re.compile(r"[\u4e00-\u9fff]")
_SKIP_INPUTS = {"upstream_payload", "upstream_payloads"}
_ZH_TITLES = {
    "qt.ai.data.history": "行情",
    "qt.ai.data.kline": "行情",
    "qt.ai.hp.agg": "汇总表",
    "qt.ai.hp.plot": "绘图",
    "qt.ai.hp.returns": "收益",
    "qt.ai.hp.performance": "绩效",
    "qt.ai.hp.volatility": "波动率",
    "qt.ai.hp.describe": "描述",
    "qt.ai.hp.alpha_beta": "阿尔法",
    "qt.ai.hp.corr": "相关性",
    "qt.ai.hp.indicator": "指标",
    "qt.ai.hp.candle_pattern": "形态",
}


def align_steps(planner: Any, steps: Sequence[Any]) -> Optional[str]:
    """按后继需要的产出写入形状开关。

    Parameters
    ----------
    planner : Planner
        用来读技能 metadata。
    steps : sequence
        当前步骤。依赖会先收成更早的 ``step_id``。

    Returns
    -------
    str or None
        接得上时返回 ``None``，并改写有后继的形状开关。
        依赖收不拢时也返回 ``None``，留给原有的依赖检查。
        没有任何已声明取值能同时满足全部后继时，返回英文原因，不改开关。
    """

    if _resolve_depends(steps):
        return None
    metas = {step.step_id: _metadata(planner, step.skill_name) for step in steps}
    found = _first_fit(steps, metas)
    if found is None:
        bad, _combo = _best_failure(steps, metas)
        return _explain(bad, metas)
    _apply(steps, metas, found)
    return None


def choice_card(planner: Any, steps: Sequence[Any], query: str) -> Dict[str, Any]:
    """开放图接不上时的选择卡。只放重新验证过的走法。

    Parameters
    ----------
    planner : Planner
        用来再跑一次同一套对齐。
    steps : sequence
        接不上的那张图。本函数不改这张图。
    query : str
        原句。含汉字则整张卡用中文。

    Returns
    -------
    dict
        澄清载荷。``pending[0].name`` 为 ``wire_choice``。
        能继续的走法把步骤快照放在 ``wire_snapshots``。
    """

    chinese = bool(_CJK.search(str(query or "")))
    metas = {step.step_id: _metadata(planner, step.skill_name) for step in steps}
    bad, _combo = _best_failure(steps, metas)
    kept = [step for step in steps if step not in bad]
    dropped = list(bad)
    options: List[Dict[str, str]] = []
    snapshots: Dict[str, List[Dict[str, Any]]] = {}
    drop_rows = _drop_snapshot(planner, steps, dropped)
    if drop_rows:
        options.append(
            {
                "id": "drop_consumer",
                "label": _drop_label(kept, dropped, chinese),
            }
        )
        snapshots["drop_consumer"] = drop_rows
    panel_rows = _use_panel_snapshot(planner, steps, bad)
    if panel_rows and panel_rows != drop_rows:
        options.append(
            {
                "id": "use_panel",
                "label": "改画前面的行情" if chinese else "Plot the earlier series instead",
            }
        )
        snapshots["use_panel"] = panel_rows
    options.append(
        {
            "id": "rewrite",
            "label": "我换一种说法" if chinese else "Say it a different way",
        }
    )
    body = _body(kept, dropped, chinese)
    stem = "怎么继续" if chinese else "How to continue"
    return {
        "restatement": f"You asked: {query}",
        "confirm_prompt": body,
        "pending": [
            {
                "name": "wire_choice",
                "label": stem,
                "prompt": stem,
                "hint": "",
                "error": "",
                "type": "string",
                "options": options,
            }
        ],
        "wire_snapshots": snapshots,
    }


def _resolve_depends(steps: Sequence[Any]) -> str:
    """把依赖收成更早一步的步骤号。收不拢返回 ``unresolved_depends``。"""

    for index, step in enumerate(steps):
        if step.skill_name == "qt.ai.system.fallback":
            continue
        raw = [str(item).strip() for item in (getattr(step, "depends_on", None) or [])]
        raw = [item for item in raw if item]
        if not raw:
            step.depends_on = []
            continue
        earlier = list(steps[:index])
        earlier_ids = {str(item.step_id) for item in earlier}
        resolved: List[str] = []
        for token in raw:
            if token in earlier_ids:
                resolved.append(token)
                continue
            matches = [str(item.step_id) for item in earlier if str(item.skill_name) == token]
            if len(matches) == 1:
                resolved.append(matches[0])
                continue
            return "unresolved_depends"
        step.depends_on = resolved
    return ""


def _metadata(planner: Any, skill_name: str) -> Any:
    """读技能说明。没有这只技能时返回 ``None``。"""

    try:
        return planner.registry.get_metadata(skill_name)
    except Exception:
        return None


def _declared(meta: Any) -> bool:
    """``produces`` 不是 ``None`` 才参加检查。"""

    return meta is not None and getattr(meta, "produces", None) is not None


def _has_switch(meta: Any) -> bool:
    """这只技能有没有形状开关。"""

    return bool(getattr(meta, "produces_when", None))


def _token(value: Any) -> str:
    """入参取值收成声明里的记号。"""

    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value).strip().lower()


def _coerce(token: str) -> Any:
    """记号写回输入。``true`` / ``false`` 写成布尔，其余保持字符串。"""

    if token == "true":
        return True
    if token == "false":
        return False
    return token


def _blank(value: Any) -> bool:
    """这个入参算不算没填。"""

    return value in (None, "", [])


def _outputs(meta: Any, inputs: Dict[str, Any]) -> Tuple[Wire, ...]:
    """按当前入参算出交出的线。开关没写就是库默认。"""

    wires = tuple(getattr(meta, "produces", None) or ())
    for key, mapping in (getattr(meta, "produces_when", None) or {}).items():
        if key not in inputs:
            continue
        token = _token(inputs.get(key))
        if token in mapping:
            wires = tuple(mapping[token])
    return wires


def _needs(meta: Any, inputs: Dict[str, Any]) -> Tuple[Tuple[Wire, ...], List[Tuple[Wire, ...]]]:
    """全部要满足的线，以及各组「满足一条即可」。"""

    required = tuple(getattr(meta, "consumes", None) or ())
    groups: List[Tuple[Wire, ...]] = []
    any_of = getattr(meta, "consumes_any", None)
    if any_of:
        groups.append(tuple(any_of))
    for key, mapping in (getattr(meta, "consumes_any_when", None) or {}).items():
        if key not in inputs or _blank(inputs.get(key)):
            token = ""
        else:
            token = _token(inputs.get(key))
        if token in mapping:
            groups.append(tuple(mapping[token]))
    return required, groups


def _covers(have: Sequence[Wire], need: Wire) -> bool:
    """已有的线里有没有同一键、同一类型、同一 dtype。"""

    return any(
        item.key == need.key and item.py_type == need.py_type and item.dtype == need.dtype
        for item in have
    )


def _virtual_inputs(step: Any, meta: Any, combo: Dict[str, Dict[str, str]], steps: Sequence[Any]) -> Dict[str, Any]:
    """评估某个开关取值时的入参。没有后继的步骤保持原样。"""

    inputs = dict(step.inputs or {})
    if not _has_switch(meta) or not _is_producer_used(step, steps):
        return inputs
    chosen = combo.get(step.step_id) or {}
    for key in (meta.produces_when or {}):
        if key in chosen:
            inputs[key] = _coerce(chosen[key])
        else:
            inputs.pop(key, None)
    return inputs


def _is_producer_used(step: Any, steps: Sequence[Any]) -> bool:
    """有没有别的步骤依赖这一步。"""

    sid = str(step.step_id)
    return any(sid in [str(item) for item in (other.depends_on or [])] for other in steps)


def _candidates(steps: Sequence[Any], metas: Dict[str, Any]) -> List[Dict[str, Dict[str, str]]]:
    """各步开关取值的组合。没写的键表示用库默认。组合按改动少的排在前面。"""

    pools: List[List[Dict[str, str]]] = []
    for step in steps:
        meta = metas.get(step.step_id)
        if not _declared(meta) or not _has_switch(meta) or not _is_producer_used(step, steps):
            pools.append([{}])
            continue
        built: List[Dict[str, str]] = [{}]
        for key, mapping in (meta.produces_when or {}).items():
            nxt: List[Dict[str, str]] = []
            for base in built:
                nxt.append(dict(base))
                for token in mapping:
                    row = dict(base)
                    row[str(key)] = str(token)
                    nxt.append(row)
            built = nxt
        pools.append(built)
    combos: List[Dict[str, Dict[str, str]]] = [{}]
    for step, options in zip(steps, pools):
        nxt_combos: List[Dict[str, Dict[str, str]]] = []
        for combo in combos:
            for opt in options:
                row = dict(combo)
                row[str(step.step_id)] = opt
                nxt_combos.append(row)
        combos = nxt_combos
    combos.sort(key=lambda combo: sum(len(item) for item in combo.values()))
    return combos


def _unsatisfied(
    steps: Sequence[Any],
    metas: Dict[str, Any],
    combo: Dict[str, Dict[str, str]],
) -> List[Any]:
    """在这组开关下接不上的消费步。未声明的边跳过。没有依赖的步不检查。"""

    by_id = {str(step.step_id): step for step in steps}
    bad = []
    for step in steps:
        meta = metas.get(step.step_id)
        if not _declared(meta):
            continue
        dep_ids = [str(item) for item in (step.depends_on or [])]
        if not dep_ids:
            continue
        deps = [by_id[item] for item in dep_ids if item in by_id]
        if len(deps) != len(dep_ids):
            continue
        if any(not _declared(metas.get(dep.step_id)) for dep in deps):
            continue
        have: List[Wire] = []
        for dep in deps:
            dep_meta = metas.get(dep.step_id)
            have.extend(_outputs(dep_meta, _virtual_inputs(dep, dep_meta, combo, steps)))
        required, groups = _needs(meta, dict(step.inputs or {}))
        if any(not _covers(have, wire) for wire in required):
            bad.append(step)
            continue
        if any(not any(_covers(have, wire) for wire in group) for group in groups):
            bad.append(step)
    return bad


def _first_fit(steps: Sequence[Any], metas: Dict[str, Any]) -> Optional[Dict[str, Dict[str, str]]]:
    """改动最少、并且全部接上的那组开关。没有则 ``None``。"""

    for combo in _candidates(steps, metas):
        if not _unsatisfied(steps, metas, combo):
            return combo
    return None


def _best_failure(
    steps: Sequence[Any],
    metas: Dict[str, Any],
) -> Tuple[List[Any], Dict[str, Dict[str, str]]]:
    """接不上时，留下失败步最少的那组，用来决定选择卡删谁。"""

    best_bad: List[Any] = list(steps)
    best_combo: Dict[str, Dict[str, str]] = {}
    best_cost: Optional[Tuple[int, int]] = None
    for combo in _candidates(steps, metas):
        bad = _unsatisfied(steps, metas, combo)
        cost = (len(bad), sum(len(item) for item in combo.values()))
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_bad = bad
            best_combo = combo
    return best_bad, best_combo


def _apply(steps: Sequence[Any], metas: Dict[str, Any], combo: Dict[str, Dict[str, str]]) -> None:
    """把选中的开关写进有后继的步骤。没选中的开关删掉，运行时用库默认。"""

    for step in steps:
        meta = metas.get(step.step_id)
        if not _declared(meta) or not _has_switch(meta) or not _is_producer_used(step, steps):
            continue
        chosen = combo.get(step.step_id) or {}
        inputs = dict(step.inputs or {})
        for key in meta.produces_when:
            if key in chosen:
                inputs[key] = _coerce(chosen[key])
            else:
                inputs.pop(key, None)
        step.inputs = inputs


def _explain(bad: Sequence[Any], metas: Dict[str, Any]) -> str:
    """闭合菜谱用的英文原因。开放图的选择卡不用这段。"""

    parts = []
    for step in bad:
        meta = metas.get(step.step_id)
        required, groups = _needs(meta, dict(step.inputs or {}))
        wires = list(required)
        for group in groups:
            wires.extend(group)
        shown = ", ".join(f"{wire.key}:{wire.py_type}" for wire in wires) or "nothing"
        parts.append(f"{step.step_id} {step.skill_name} needs {shown}")
    return "wire_product_mismatch: " + "; ".join(parts)


def _snapshot(steps: Sequence[Any]) -> List[Dict[str, Any]]:
    """选择卡上的步骤快照。不带上游 payload。"""

    rows = []
    for step in steps:
        inputs = {
            str(key): value
            for key, value in dict(step.inputs or {}).items()
            if str(key) not in _SKIP_INPUTS
        }
        rows.append(
            {
                "step_id": step.step_id,
                "skill_name": step.skill_name,
                "inputs": inputs,
                "depends_on": [str(item) for item in (step.depends_on or [])],
            }
        )
    return rows


def _clone(steps: Sequence[Any]) -> List[Any]:
    """复制步骤，试走法时不改原图。"""

    return [deepcopy(step) for step in steps]


def _drop_snapshot(planner: Any, steps: Sequence[Any], dropped: Sequence[Any]) -> List[Dict[str, Any]]:
    """去掉接不上的步骤后再对齐。剩下的图仍不合法或变空，就不出这一项。"""

    if not dropped:
        return []
    drop_ids = {str(step.step_id) for step in dropped}
    kept = [step for step in _clone(steps) if str(step.step_id) not in drop_ids]
    if not kept:
        return []
    for step in kept:
        step.depends_on = [str(item) for item in (step.depends_on or []) if str(item) not in drop_ids]
    if align_steps(planner, kept):
        return []
    return _snapshot(kept)


def _use_panel_snapshot(planner: Any, steps: Sequence[Any], bad: Sequence[Any]) -> List[Dict[str, Any]]:
    """要面板的那一步改依赖更早交出面板的步骤，并去掉因此空出来的中间步。"""

    consumers = []
    for step in bad:
        meta = _metadata(planner, step.skill_name)
        required, _groups = _needs(meta, dict(step.inputs or {}))
        if any(wire.key == PANEL.key and wire.py_type == PANEL.py_type for wire in required):
            consumers.append(step)
    if not consumers:
        return []
    cloned = _clone(steps)
    by_id = {str(step.step_id): step for step in cloned}
    order = [str(step.step_id) for step in cloned]
    for step in consumers:
        target = by_id.get(str(step.step_id))
        if target is None:
            return []
        index = order.index(str(target.step_id))
        source = ""
        for earlier_id in reversed(order[:index]):
            meta = _metadata(planner, by_id[earlier_id].skill_name)
            if _can_emit_panel(meta):
                source = earlier_id
                break
        if not source:
            return []
        target.depends_on = [source]
    needed = set()

    def walk(step_id: str) -> None:
        if step_id in needed or step_id not in by_id:
            return
        needed.add(step_id)
        for dep in by_id[step_id].depends_on or []:
            walk(str(dep))

    for step in consumers:
        walk(str(step.step_id))
    pruned = [step for step in cloned if str(step.step_id) in needed]
    if not pruned or align_steps(planner, pruned):
        return []
    return _snapshot(pruned)


def _can_emit_panel(meta: Any) -> bool:
    """默认或某个已声明开关能不能交出面板。"""

    if not _declared(meta):
        return False
    if _covers(tuple(meta.produces or ()), PANEL):
        return True
    for mapping in (meta.produces_when or {}).values():
        for wires in mapping.values():
            if _covers(tuple(wires), PANEL):
                return True
    return False


def _title(skill: str, chinese: bool) -> str:
    """选择卡上的人话标题。中文卡用短标题。"""

    if chinese and skill in _ZH_TITLES:
        return _ZH_TITLES[skill]
    return skill_step_title(skill)


def _join(steps: Sequence[Any], chinese: bool) -> str:
    """把若干步的标题连起来。"""

    titles = []
    seen = set()
    for step in steps:
        title = _title(str(step.skill_name), chinese)
        if title in seen:
            continue
        seen.add(title)
        titles.append(title)
    if chinese:
        return "、".join(titles)
    return " and ".join(titles)


def _drop_label(kept: Sequence[Any], dropped: Sequence[Any], chinese: bool) -> str:
    """去掉接不上的那一步时，选项上的句子。"""

    kept_text = _join(kept, chinese)
    only_plot = bool(dropped) and all(str(step.skill_name) == "qt.ai.hp.plot" for step in dropped)
    if chinese:
        if only_plot:
            return f"保留{kept_text}，不画图"
        return f"只保留{kept_text}"
    if only_plot:
        return f"Keep {kept_text}, without the plot"
    return f"Keep only {kept_text}"


def _body(kept: Sequence[Any], dropped: Sequence[Any], chinese: bool) -> str:
    """先说哪一段做得到，再说哪一段接不上。"""

    if not kept:
        return "这几步接不上。" if chinese else "These steps do not connect."
    if not dropped:
        return "这几步接不上。" if chinese else "These steps do not connect."
    if chinese:
        return f"{_join(kept, True)}可以继续。{_join(dropped, True)}接不上。"
    return f"{_join(kept, False)} can continue. {_join(dropped, False)} does not connect."
