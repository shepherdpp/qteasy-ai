# coding=utf-8
# ======================================
# File: live_plan.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-29
# Desc:
# qteasy AI 阶段 D：实盘只出计划，永不下单。
# ======================================

"""实盘 plan-only：输出前置条件与风控声明，不触发任何实盘执行。"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from ..contracts import (
    SkillMetadata,
    SkillResult,
    SkillSideEffects,
    new_run_id,
)

_LIVE_CHECKLIST = [
    "Complete a backtest on the intended strategy and review metrics/trade_log.",
    "Confirm datasource, asset pool, run_freq, and costs match the live account.",
    "Paper-trade or paper-run first; live orders require a separate explicit confirmation outside Agent mode.",
    "Set risk limits: position cap, MOQ, T+1/delivery, and no silent short selling unless declared.",
    "Keep rollback: stop the operator, cancel open orders, restore last known positions from logs.",
]


def build_live_trade_plan_only_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.pipeline.live_trade_plan_only``。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。Handler 不连接券商、不改持仓。
    """

    metadata = SkillMetadata(
        name="qt.ai.pipeline.live_trade_plan_only",
        version="0.1.0",
        summary="Produce a live-trade readiness plan only; never auto-executes live orders.",
        inputs_schema={
            "query": {"type": "string", "required": False},
        },
        outputs_schema={"checklist": "list", "execution_forbidden": "bool"},
        side_effects=SkillSideEffects(description="readonly live-trade plan; never sends orders"),
        required_capabilities=[],
        qteasy_entrypoints=[],
        skill_kind="api",
    )

    def handler(
        query: str = "",
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        run_id = new_run_id()
        inputs_echo = {"query": query, **kwargs}
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=run_id,
            inputs_echo=inputs_echo,
            payload={
                "execution_forbidden": True,
                "checklist": list(_LIVE_CHECKLIST),
                "config_suggestions": [
                    "Use Plan mode and confirm each live-related step manually.",
                    "Do not enable Agent auto-execute for live trading.",
                ],
                "risk_decl": {
                    "cost": "declare_only",
                    "moq": "declare_only",
                    "delivery": "declare_only",
                    "short_sell": "declare_only",
                },
                "rollback_hint": (
                    "If anything goes wrong: halt the operator, cancel open orders, "
                    "and restore positions from the latest trade log."
                ),
            },
            metrics={"execution_forbidden": 1},
            warnings=[
                "Live trading is never auto-executed by qteasy-ai. This skill returns a plan only."
            ],
        )
        return result.to_dict()

    return metadata, handler
