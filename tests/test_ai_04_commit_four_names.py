# coding=utf-8
# ======================================
# File: test_ai_04_commit_four_names.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-11
# Desc:
# 四只公司名加沪深300 的原句，固定协议仍能交出可确认计划。
# 这条在第三步之前保持失败，用来卡住假成功。
# ======================================

import json
import unittest
from typing import Any, Dict, List, Optional, Tuple

from qteasy_ai.app import build_default_registry
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider

_QUERY = "帮我用贵州茅台、格力电器、工商银行和招商银行做一个等权持仓组合，看过去3年的持仓收益率，并跟沪深300指数做一个对比。"


def _registry() -> Any:
    """默认技能表。"""

    return build_default_registry()


def _plan(query: str, replies: Optional[List[str]] = None) -> Tuple[Any, Optional[FakeLLMProvider]]:
    """无模型，或按队列喂假模型。不挂会话。"""

    provider = FakeLLMProvider(replies=list(replies or [])) if replies is not None else None
    planner = Planner(_registry(), provider=provider, env_facts={})
    plan = planner.build_plan(query, mode="plan")
    return plan, provider


def _skills(plan: Any) -> List[str]:
    """可见步骤的技能名。"""

    return [step.skill_name for step in plan.steps]


def _inputs(plan: Any, skill: str) -> Dict[str, Any]:
    """可见步骤里该技能的 inputs。没有则空。"""

    for step in plan.steps:
        if step.skill_name == skill:
            return dict(step.inputs or {})
    return {}


def _pending_names(plan: Any) -> List[str]:
    """澄清卡上的槽名。"""

    card = (plan.assumptions or {}).get("clarification") or {}
    return [str(item.get("name") or "") for item in (card.get("pending") or []) if isinstance(item, dict)]


def _executable(plan: Any) -> bool:
    """可见步骤里没有澄清 fallback。"""

    return "qt.ai.system.fallback" not in _skills(plan)


class TestAi04CommitFourNames(unittest.TestCase):
    """四只公司名不能靠只剩沪深300 的可确认计划过关。"""

    def test_four_company_names_are_not_confirmed(self) -> None:
        """固定协议写下四只代码和四个 0.25 时，不能当成已经修完。"""

        print("\n[TestAi04CommitFourNames] 四只公司名假成功")
        plan, _provider = _plan(
            _QUERY,
            [
                json.dumps({"job": "research.hold_compare"}),
                json.dumps({
                    "shares": "600519.SH,000651.SZ,601398.SH,600036.SH",
                    "weights": [0.25, 0.25, 0.25, 0.25],
                    "mode": "weighted",
                    "benchmark": "000300.SH",
                }),
            ],
        )
        kline = _inputs(plan, "qt.ai.data.kline")
        portfolio = _inputs(plan, "qt.ai.hp.portfolio")
        shares = str(kline.get("shares") or "")
        weights = list(portfolio.get("weights") or [])
        mode = portfolio.get("mode")
        print(" skills:", _skills(plan))
        print(" executable:", _executable(plan))
        print(" shares:", shares)
        print(" weights:", weights, "mode:", mode, "benchmark:", portfolio.get("benchmark"))
        print(" pending:", _pending_names(plan))
        false_success = (
            _executable(plan)
            and shares == "000300.SH"
            and weights == [0.25, 0.25, 0.25, 0.25]
            and mode == "weighted"
        )
        self.assertFalse(false_success)


if __name__ == "__main__":
    unittest.main()
