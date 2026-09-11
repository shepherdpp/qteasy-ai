# coding=utf-8
# ======================================
# File: human.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-08
# Desc:
# 将内核人读卡渲染为对话区纯文本。
# ======================================

"""CLI / Notebook ``--human`` 渲染。只消费内核卡，不现场发明解读。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..human_card import format_human_cards, project_human_cards
from ..session import ConversationState
from .dto import WorkbenchState


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
            or inner.get("human_cards") is not None
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
    """把工作台状态中的内核卡打成英文文本。

    Parameters
    ----------
    state : WorkbenchState
        已投影状态（``messages`` 为人读卡）。
    confirm_hint : str, optional
        忽略；确认提示已写入 ``plan_ready``。
    run_file : str, optional
        忽略。
    plan_md_file : str, optional
        忽略。
    plan : dict, optional
        忽略。
    registry : Any, optional
        忽略。
    query : str, optional
        忽略。
    execution : dict, optional
        覆盖 MODE 行所用 execution。

    Returns
    -------
    str
        纯文本，末尾换行。
    """

    del confirm_hint, run_file, plan_md_file, plan, registry, query
    cards = [{"kind": item.kind, "text": item.text, "payload": dict(item.payload or {})} for item in state.messages]
    raw = {
        "mode": state.mode,
        "execution": execution if isinstance(execution, dict) else dict(state.execution or {}),
        "run_id": state.run_id,
        "sources": list(state.sources or []),
        "requested_mode": "",
        "human_cards": cards,
    }
    return format_human_cards(cards, payload=raw)


def format_human_from_payload(
    payload: Any,
    *,
    query: str = "",
    session: Optional[ConversationState] = None,
    env_facts: Optional[Dict[str, Any]] = None,
    confirm_hint: str = "",
    registry: Any = None,
) -> str:
    """raw / pretty 包装 → human 文本（只打内核卡）。

    Parameters
    ----------
    payload : Any
        Assistant 返回值。
    query : str, optional
        本轮问句。
    session : ConversationState, optional
        忽略；卡已在 payload 或由投影器生成。
    env_facts : dict, optional
        忽略。
    confirm_hint : str, optional
        忽略。
    registry : SkillRegistry, optional
        投影 Plan/run 卡时查 metadata。

    Returns
    -------
    str
        ``format_human_cards`` 文本。
    """

    del session, env_facts, confirm_hint
    raw = unwrap_raw_payload(payload)
    cards = raw.get("human_cards")
    if not isinstance(cards, list) or not cards:
        cards = project_human_cards(
            raw,
            requested_mode=str(raw.get("requested_mode") or ""),
            query=query,
            registry=registry,
        )
    return format_human_cards(cards, payload=raw)
