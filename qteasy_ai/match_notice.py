# coding=utf-8
# ======================================
# File: match_notice.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-19
# Desc:
# 匹配说明只投影计划记录里的任务种类、来源和理由。
# ======================================

"""已记下的匹配结果，整理成用户能读的一句说明。"""

from __future__ import annotations

from typing import Any, Mapping


def render_match_notice(trace: Mapping[str, Any], *, chinese: bool) -> str:
    """用记录里的任务种类、来源和理由写成一句说明。

    不查任务目录，也不分类。来源或理由空着就省掉那一截。

    Parameters
    ----------
    trace : mapping
        计划上的 ``planner_trace``。只用 ``intent_job``、``source``、``rationale``。
    chinese : bool
        为 True 时用中文标签。任务 id 仍按记录原文抄出。

    Returns
    -------
    str
        有任务种类时是一句说明，否则是空串。

    Examples
    --------
    >>> render_match_notice(
    ...     {"intent_job": "research.hold_compare", "source": "rule", "rationale": "portfolio_compare"},
    ...     chinese=True,
    ... )
    '任务 research.hold_compare。来源 rule。理由 portfolio_compare。'
    """

    if not isinstance(trace, Mapping):
        return ""
    job = str(trace.get("intent_job") or "").strip()
    if not job:
        return ""
    source = str(trace.get("source") or "").strip()
    reason = str(trace.get("rationale") or "").strip()
    if chinese:
        parts = [f"任务 {job}"]
        if source:
            parts.append(f"来源 {source}")
        if reason:
            parts.append(f"理由 {reason}")
        return "。".join(parts) + "。"
    parts = [f"Task {job}"]
    if source:
        parts.append(f"Source {source}")
    if reason:
        parts.append(f"Reason {reason}")
    return ". ".join(parts) + "."
