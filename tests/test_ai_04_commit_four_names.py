# coding=utf-8
# ======================================
# File: test_ai_04_commit_four_names.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-11
# Desc:
# 四只公司名加沪深300。协议按项提交时不能确认用户没写过的代码。
# ======================================

import json
import unittest
from typing import Any, Dict, List, Optional, Tuple

from qteasy_ai.app import build_default_registry
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.session import ConversationState

_QUERY = "帮我用贵州茅台、格力电器、工商银行和招商银行做一个等权持仓组合，看过去3年的持仓收益率，并跟沪深300指数做一个对比。"


def _registry() -> Any:
    """默认技能表。"""

    return build_default_registry()


def _plan(
    query: str,
    replies: Optional[List[str]] = None,
    *,
    session: Any = None,
    skip_classify: bool = False,
) -> Tuple[Any, Optional[FakeLLMProvider]]:
    """无模型，或按队列喂假模型。"""

    provider = FakeLLMProvider(replies=list(replies or [])) if replies is not None else None
    planner = Planner(_registry(), provider=provider, env_facts={})
    plan = planner.build_plan(
        query,
        mode="plan",
        session=session,
        skip_classify=skip_classify,
    )
    return plan, provider


def _accepted(plan: Any) -> List[Dict[str, Any]]:
    """澄清时留下的步骤快照。"""

    return list((plan.assumptions or {}).get("accepted_steps") or [])


def _snap_inputs(plan: Any, skill: str) -> Dict[str, Any]:
    """快照里该技能的 inputs。没有快照就看可见步骤。"""

    for step in _accepted(plan):
        if str(step.get("skill_name") or "") == skill:
            return dict(step.get("inputs") or {})
    return _inputs(plan, skill)


_PROTOCOL = {
    "holdings": [
        {"mention": "贵州茅台", "code": "600519.SH"},
        {"mention": "格力电器", "code": "000651.SZ"},
        {"mention": "工商银行", "code": "601398.SH"},
        {"mention": "招商银行", "code": "600036.SH"},
    ],
    "benchmark": {"mention": "沪深300指数", "code": "000300.SH"},
    "weights": [0.25, 0.25, 0.25, 0.25],
    "mode": "weighted",
}


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
        """协议按项交出四只代码时，用户没写过的代码保持未确认。"""

        print("\n[TestAi04CommitFourNames] 四只公司名按项提交")
        plan, _provider = _plan(
            _QUERY,
            [
                json.dumps({"job": "research.hold_compare"}),
                json.dumps(_PROTOCOL),
            ],
        )
        portfolio = _snap_inputs(plan, "qt.ai.hp.portfolio")
        kline = _snap_inputs(plan, "qt.ai.data.kline")
        holdings = list(portfolio.get("holdings") or [])
        benchmark = portfolio.get("benchmark")
        shares = kline.get("shares")
        print(" executable:", _executable(plan))
        print(" holdings:", holdings)
        print(" benchmark:", benchmark)
        print(" shares:", shares, "weights:", portfolio.get("weights"), "mode:", portfolio.get("mode"))
        print(" asset_type:", kline.get("asset_type"), "pending:", _pending_names(plan))
        false_success = (
            _executable(plan)
            and str(shares or "") == "000300.SH"
            and list(portfolio.get("weights") or []) == [0.25, 0.25, 0.25, 0.25]
            and portfolio.get("mode") == "weighted"
        )
        self.assertFalse(false_success)
        self.assertFalse(_executable(plan))
        self.assertEqual(
            [item.get("mention") for item in holdings],
            ["贵州茅台", "格力电器", "工商银行", "招商银行"],
        )
        self.assertTrue(all(item.get("status") == "pending" for item in holdings))
        self.assertNotIn("000300.SH", [item.get("code") for item in holdings])
        self.assertIsInstance(benchmark, dict)
        self.assertEqual(benchmark.get("code"), "000300.SH")
        self.assertEqual(benchmark.get("status"), "confirmed")
        self.assertNotEqual(list(portfolio.get("weights") or []), [0.25, 0.25, 0.25, 0.25])
        self.assertEqual(portfolio.get("mode"), "equal")
        self.assertNotEqual(shares, "000300.SH")
        self.assertNotIn("asset_type", kline)

    def test_old_shares_key_does_not_confirm(self) -> None:
        """旧的 shares 字符串和四个 0.25 不能再拼成可执行计划。"""

        print("\n[TestAi04CommitFourNames] 旧 shares 键")
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
        portfolio = _snap_inputs(plan, "qt.ai.hp.portfolio")
        kline = _snap_inputs(plan, "qt.ai.data.kline")
        print(" executable:", _executable(plan))
        print(" holdings:", portfolio.get("holdings"), "shares:", kline.get("shares"))
        print(" weights:", portfolio.get("weights"), "mode:", portfolio.get("mode"))
        false_success = (
            _executable(plan)
            and str(kline.get("shares") or "") == "000300.SH"
            and list(portfolio.get("weights") or []) == [0.25, 0.25, 0.25, 0.25]
            and portfolio.get("mode") == "weighted"
        )
        self.assertFalse(false_success)
        self.assertFalse(_executable(plan))
        self.assertNotIn("600519.SH", json.dumps(portfolio.get("holdings") or [], ensure_ascii=False))

    def test_names_without_model_stay_incomplete(self) -> None:
        """没有模型时四只公司名都是未完成项，代码为空。"""

        print("\n[TestAi04CommitFourNames] 无模型四只公司名")
        state = ConversationState.empty("four-names")
        state.start_task(query=_QUERY, job="research.hold_compare")
        plan, _provider = _plan(_QUERY, session=state, skip_classify=True)
        portfolio = _snap_inputs(plan, "qt.ai.hp.portfolio")
        holdings = list(portfolio.get("holdings") or [])
        benchmark = portfolio.get("benchmark")
        print(" holdings:", holdings)
        print(" benchmark:", benchmark, "executable:", _executable(plan))
        self.assertEqual(
            [item.get("mention") for item in holdings],
            ["贵州茅台", "格力电器", "工商银行", "招商银行"],
        )
        self.assertTrue(all(item.get("status") == "incomplete" and not item.get("code") for item in holdings))
        self.assertIsInstance(benchmark, dict)
        self.assertEqual(benchmark.get("code"), "000300.SH")
        self.assertEqual(benchmark.get("status"), "confirmed")
        self.assertFalse(_executable(plan))


if __name__ == "__main__":
    unittest.main()
