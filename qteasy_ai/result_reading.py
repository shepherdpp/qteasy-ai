# coding=utf-8
# ======================================
# File: result_reading.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-19
# Desc:
# 运行结束后的一段解读。只引用记录；指不回就整段换成模板。
# ======================================

"""结果卡事实行之外的解读。

有模型时先作文。代码、数字、排名、跑赢、总账或买卖指不回记录，整段换成模板。
没有模型时直接填同一份模板。不写槽，不改已经执行的步骤。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from .human_card import _NUMBER_RE, _execution_error_message, _shown_result_facts
from .identity import prefix_system_prompt
from .slot_graph import committed_fact_lines

_CODE_RE = re.compile(r"\d{6}(?:\.(?:SH|SZ|BJ))?")
_RANK_RE = re.compile(r"排名|第\d+|#\d+|\brank\b|\btop\s+\d+", re.IGNORECASE)
_BEAT_RE = re.compile(r"跑赢|跑输|outperform|underperform|\bbeats?\b", re.IGNORECASE)
_TRADE_RE = re.compile(r"买入|卖出|建议买|建议卖|\bbuy\b|\bsell\b", re.IGNORECASE)
_READING_SYSTEM = (
    "Write one paragraph about this run.\n"
    "Use only codes and numbers that already appear in the fields.\n"
    "Do not add a ledger, a rank, an outperform or underperform judgment, "
    "a buy or a sell, or an excess number that is not in the fields.\n"
    "The questions are listed so you can speak to them."
)
_EXECUTED = frozenset({"success", "partial_failed", "failed"})


def reading_corpus(plan: Mapping[str, Any], execution: Mapping[str, Any]) -> str:
    """拼出解读可以引用的记录。

    只有事实行、成功步已经展示的标量，以及错误原文。
    用户原句和提问不在这里。

    Parameters
    ----------
    plan : mapping
        已执行的计划。
    execution : mapping
        这一次运行记录。

    Returns
    -------
    str
        用换行接起来的语料。
    """

    lines = [str(item).strip() for item in committed_fact_lines(_plan_steps(plan)) if str(item).strip()]
    for key, value in _shown_scalars(execution):
        lines.append(f"{key} = {value}")
    error = _execution_error_message(dict(execution or {}))
    if error:
        lines.append(error)
    return "\n".join(lines)


def reading_template(plan: Mapping[str, Any], execution: Mapping[str, Any]) -> str:
    """无模型和降级共用的一段英文。

    Parameters
    ----------
    plan : mapping
        提供用户原句、提问和已提交输入。
    execution : mapping
        成功时写出事实和标量；否则只写错误。

    Returns
    -------
    str
        一段解读。
    """

    query = str((plan or {}).get("user_query") or "")
    parts = [f"You asked: {query}."]
    for item in _questions(plan):
        parts.append(f"Question: {item}.")
    if str((execution or {}).get("status") or "") == "success":
        for line in committed_fact_lines(_plan_steps(plan)):
            text = str(line).strip()
            if text:
                parts.append(text if text.endswith(".") else text + ".")
        for key, value in _shown_scalars(execution):
            parts.append(f"Shown: {key} = {value}.")
        parts.append("This record has no other total.")
    else:
        message = _execution_error_message(dict(execution or {}))
        if message:
            parts.append(f"The run did not finish. Error: {message}.")
        else:
            parts.append("The run did not finish.")
    return " ".join(parts)


def write_result_reading(
    plan: Mapping[str, Any],
    execution: Mapping[str, Any],
    *,
    provider: Any = None,
    identity_dir: Any = None,
) -> str:
    """生成一段解读。指不回记录时整段换成模板。

    Parameters
    ----------
    plan : mapping
        用户原句和已提交输入。只读。
    execution : mapping
        运行记录。只读。
    provider : optional
        有 ``chat`` 时先作文。没有则直接填模板。
    identity_dir : optional
        系统提示前的身份目录。

    Returns
    -------
    str
        留给结果卡的一段话。

    Examples
    --------
    >>> write_result_reading(
    ...     {"user_query": "one index", "steps": []},
    ...     {"status": "failed", "steps": []},
    ... )
    'You asked: one index. The run did not finish.'
    """

    template = reading_template(plan, execution)
    if provider is None or not hasattr(provider, "chat"):
        return template
    corpus = reading_corpus(plan, execution)
    try:
        raw = provider.chat(
            _reading_prompt(plan, corpus),
            system_prompt=prefix_system_prompt(_READING_SYSTEM, identity_dir),
        )
    except Exception:
        return template
    body = str(raw or "").strip()
    if not body:
        return template
    failed = str((execution or {}).get("status") or "") != "success"
    if _ungrounded(body, corpus, failed=failed):
        return template
    return body


def attach_result_reading(
    cards: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any],
    execution: Mapping[str, Any],
    *,
    provider: Any = None,
    identity_dir: Any = None,
) -> List[Dict[str, Any]]:
    """把解读贴到已经执行的结果卡下面。

    Parameters
    ----------
    cards : sequence of mapping
        投影并润色之后的人读卡。
    plan : mapping
        已执行计划。
    execution : mapping
        运行记录。
    provider : optional
        解读用的模型。不经过润色那一层过滤。
    identity_dir : optional
        身份目录。

    Returns
    -------
    list of dict
        结果卡正文多一段解读。没有结果卡时原样返回。
    """

    rows = [item for item in (cards or [])]
    status = str((execution or {}).get("status") or "")
    steps = [item for item in ((execution or {}).get("steps") or []) if isinstance(item, dict)]
    if status not in _EXECUTED or not steps:
        return rows
    if not any(isinstance(item, Mapping) and item.get("kind") == "result" for item in rows):
        return rows
    reading = write_result_reading(
        plan or {},
        execution or {},
        provider=provider,
        identity_dir=identity_dir,
    )
    out: List[Dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, Mapping) or item.get("kind") != "result":
            out.append(dict(item) if isinstance(item, Mapping) else item)
            continue
        cloned = dict(item)
        payload = item.get("payload")
        if isinstance(payload, dict):
            cloned["payload"] = dict(payload)
        body = str(item.get("text") or "").rstrip()
        cloned["text"] = f"{body}\n\n{reading}" if body else reading
        out.append(cloned)
    return out


def _plan_steps(plan: Mapping[str, Any]) -> List[Any]:
    """计划上的步骤。缺了就是空列表。"""

    raw = plan.get("steps") if isinstance(plan, Mapping) else None
    if not isinstance(raw, list):
        return []
    return list(raw)


def _questions(plan: Mapping[str, Any]) -> List[str]:
    """``parse_record.questions`` 里的非空原文。"""

    assumptions = plan.get("assumptions") if isinstance(plan, Mapping) else None
    record = assumptions.get("parse_record") if isinstance(assumptions, dict) else None
    raw = record.get("questions") if isinstance(record, dict) else None
    if not isinstance(raw, list):
        return []
    found: List[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text:
            found.append(text)
    return found


def _shown_scalars(execution: Mapping[str, Any]) -> List[Tuple[str, str]]:
    """成功步上已经展示的标量。失败步不贡献。"""

    found: List[Tuple[str, str]] = []
    for step in (execution or {}).get("steps") or []:
        if not isinstance(step, dict):
            continue
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        if result.get("ok") is False:
            continue
        scalars, _counts, _rows = _shown_result_facts(result, False)
        found.extend((str(key), str(value)) for key, value in scalars)
    return found


def _reading_prompt(plan: Mapping[str, Any], corpus: str) -> str:
    """交给模型的用户提示。只有原句、提问和语料。"""

    lines = [f"User asked: {str((plan or {}).get('user_query') or '')}", "Questions:"]
    lines.extend(_questions(plan))
    lines.extend(["Fields:", corpus])
    return "\n".join(lines)


def _ungrounded(text: str, corpus: str, *, failed: bool) -> bool:
    """这段话里有指不回语料的代码、数字、排名、跑赢、总账或买卖。"""

    for pattern in (_CODE_RE, _NUMBER_RE, _RANK_RE, _BEAT_RE, _TRADE_RE):
        for match in pattern.findall(text):
            if match not in corpus:
                return True
    if "总账" in text and "总账" not in corpus:
        return True
    if failed and "succeeded" in text and "succeeded" not in corpus:
        return True
    return False
