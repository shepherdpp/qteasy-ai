# coding=utf-8
# ======================================
# File: side_effects.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-22
# Desc:
# 高副作用判定（Session / 人读卡 / Workbench 共用）。
# ======================================

"""Skill 高副作用判定。禁止 Session 去 import workbench。"""

from __future__ import annotations

from typing import Any, Dict, Optional

HIGH_SIDE_EFFECT_SKILLS = frozenset(
    {
        "qt.ai.data.refill_basic_equity_and_index",
        "qt.ai.backtest.run_builtin",
        "qt.ai.optimize.run_builtin",
        "qt.ai.strategy.codegen_hybrid",
        "qt.ai.pipeline.live_trade_plan_only",
        "qt.ai.visual.export_kline",
    }
)


def step_needs_confirm(skill_name: str, side_effects: Optional[Dict[str, Any]] = None) -> bool:
    """高副作用 skill 或任一侧效应开关为真时须确认。

    Parameters
    ----------
    skill_name : str
        注册名。
    side_effects : dict, optional
        ToolPlan 步的 side_effects。

    Returns
    -------
    bool
        是否须用户确认后才能 execute。
    """

    name = str(skill_name or "")
    if name in HIGH_SIDE_EFFECT_SKILLS:
        return True
    effects = side_effects if isinstance(side_effects, dict) else {}
    return bool(
        effects.get("network")
        or effects.get("filesystem_write")
        or effects.get("local_state_change")
        or effects.get("heavy_compute")
    )


def plan_has_high_side_effect(plan: Any) -> bool:
    """计划任一步为高副作用则为真。

    Parameters
    ----------
    plan : Any
        ToolPlan 或带 ``steps`` 的对象。

    Returns
    -------
    bool
        是否含高副作用步。
    """

    steps = list(getattr(plan, "steps", None) or [])
    for step in steps:
        skill = str(getattr(step, "skill_name", "") or "")
        raw_fx = getattr(step, "side_effects", None)
        if hasattr(raw_fx, "network"):
            effects = {
                "network": bool(getattr(raw_fx, "network", False)),
                "filesystem_write": bool(getattr(raw_fx, "filesystem_write", False)),
                "local_state_change": bool(getattr(raw_fx, "local_state_change", False)),
                "heavy_compute": bool(getattr(raw_fx, "heavy_compute", False)),
            }
        elif isinstance(raw_fx, dict):
            effects = raw_fx
        else:
            effects = {}
        if step_needs_confirm(skill, effects):
            return True
    return False
