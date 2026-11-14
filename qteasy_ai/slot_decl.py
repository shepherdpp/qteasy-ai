# coding=utf-8
# ======================================
# File: slot_decl.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-30
# Desc:
# 澄清卡出卡文案。收不收值不在这里判断。
# ======================================

"""澄清卡正文与出卡规范化。槽值校验在 slot_graph。"""

from __future__ import annotations

from typing import Any, Dict, List


def clarification_prompt(pending: List[Dict[str, Any]]) -> str:
    """卡片正文只点名被拒的格子。填法留在各格的 hint / error。

    Parameters
    ----------
    pending : list of dict
        仍要问的槽，含 ``name`` / ``label`` / ``error``。

    Returns
    -------
    str
        英文局面说明。
    """

    rejected = [item for item in pending if str(item.get("error") or "").strip()]
    missing = [item for item in pending if not str(item.get("error") or "").strip()]
    parts: List[str] = []
    if missing:
        parts.append("Some fields are still missing.")
    if rejected:
        labels = ", ".join(str(item.get("label") or item.get("name") or "") for item in rejected)
        parts.append(f"Rejected: {labels}.")
    return " ".join(parts).strip() or "Some fields are still missing."


_MAX_CLARIFY_OPTIONS = 5
_OPEN_OPTIONS_HINT = "Use the open input for other values."


def finalize_clarification_for_emit(blob: Dict[str, Any]) -> Dict[str, Any]:
    """出卡规范化：全量 pending、step 字段、每步 options≤5、去掉顶层 options。

    不把 pending 收成一项。正文不写 ``X of N``。截断 options 时在该步
    ``hint`` 追加开放输入提示。供规划器组装 ``assumptions.clarification``。

    Parameters
    ----------
    blob : dict
        含 ``pending`` 的澄清载荷。

    Returns
    -------
    dict
        规范化后的澄清载荷（新 dict）。
    """

    out = dict(blob or {})
    raw_pending = out.get("pending") if isinstance(out.get("pending"), list) else []
    pending: List[Dict[str, Any]] = []
    for item in raw_pending:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        options = row.get("options") if isinstance(row.get("options"), list) else None
        if options is not None:
            cleaned: List[Dict[str, Any]] = []
            for opt in options:
                if isinstance(opt, dict) and (opt.get("id") is not None or opt.get("label") is not None):
                    cleaned.append(dict(opt))
            truncated = len(cleaned) > _MAX_CLARIFY_OPTIONS
            cleaned = cleaned[:_MAX_CLARIFY_OPTIONS]
            if cleaned:
                row["options"] = cleaned
            else:
                row.pop("options", None)
            if truncated:
                hint = str(row.get("hint") or "").strip()
                if _OPEN_OPTIONS_HINT not in hint:
                    row["hint"] = f"{hint} {_OPEN_OPTIONS_HINT}".strip() if hint else _OPEN_OPTIONS_HINT
        pending.append(row)
    out["pending"] = pending
    out.pop("options", None)
    out["step_total"] = len(pending)
    out["step_index"] = 1 if pending else 0
    return out
