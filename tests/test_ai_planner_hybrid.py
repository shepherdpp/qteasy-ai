# coding=utf-8
# ======================================
# File: test_ai_planner_hybrid.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-28
# Desc:
# Unittest for Hybrid Planner LLM candidate
# ======================================

import json
import unittest

from qteasy_ai.app import build_default_registry
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider


def _llm_plan(steps: list) -> str:
    """构造 FakeLLM 返回的计划 JSON。"""

    return json.dumps({"steps": steps}, ensure_ascii=False)


class TestAiPlannerHybrid(unittest.TestCase):
    """测试 LLM 候选 + 规则门禁。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_llm_valid_backtest_uses_registry_side_effects(self) -> None:
        """合法 LLM 候选被采纳，side_effects 来自 registry 而非 LLM 自报。"""

        print("\n[TestAiPlannerHybrid] valid LLM backtest")
        fake = FakeLLMProvider(
            replies=[
                _llm_plan(
                    [
                        {
                            "skill_name": "qt.ai.backtest.run_builtin",
                            "inputs": {
                                "strategy_id": "macd",
                                "asset_pool": "000300.SH",
                                "invest_start": "20180101",
                                "invest_end": "20231231",
                            },
                            "side_effects": {"network": True, "description": "llm_lied"},
                        }
                    ]
                )
            ]
        )
        planner = Planner(self.registry, provider=fake, env_facts={})
        plan = planner.build_plan("whatever the user said", mode="plan")
        step = plan.steps[0]
        meta = self.registry.get_metadata("qt.ai.backtest.run_builtin")
        print(" source:", plan.assumptions.get("candidate_source"), plan.planner_trace.get("candidate_source"))
        print(" skill:", step.skill_name)
        print(" side_effects:", step.side_effects)
        print(" llm prompts:", len(fake.prompts))
        self.assertEqual(plan.assumptions.get("candidate_source"), "llm")
        self.assertEqual(plan.planner_trace.get("candidate_source"), "llm")
        self.assertEqual(step.skill_name, "qt.ai.backtest.run_builtin")
        self.assertEqual(step.side_effects, meta.side_effects)
        self.assertNotEqual(step.side_effects.description, "llm_lied")
        self.assertTrue(step.side_effects.filesystem_write)
        self.assertTrue(step.side_effects.heavy_compute)
        self.assertEqual(len(fake.prompts), 1)

    def test_llm_unknown_skill_downgrades_to_rules(self) -> None:
        """未知 skill 降级规则路径，trace 记录 downgrade_reason。"""

        print("\n[TestAiPlannerHybrid] unknown skill downgrade")
        fake = FakeLLMProvider(
            replies=[_llm_plan([{"skill_name": "qt.ai.invented.skill", "inputs": {}}])]
        )
        planner = Planner(self.registry, provider=fake, env_facts={})
        plan = planner.build_plan("list built-in strategies", mode="plan")
        print(" skills:", [s.skill_name for s in plan.steps])
        print(" source:", plan.assumptions.get("candidate_source"))
        print(" downgrade:", plan.planner_trace.get("downgrade_reason"))
        self.assertEqual(plan.assumptions.get("candidate_source"), "rule")
        self.assertIn("invented", str(plan.planner_trace.get("downgrade_reason", "")).lower()
                      + str(plan.assumptions.get("downgrade_reason", "")).lower())
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.strategy_meta.list")

    def test_llm_refill_without_dates_still_clarify(self) -> None:
        """LLM 给出无日期 refill 仍 clarify date_range。"""

        print("\n[TestAiPlannerHybrid] LLM refill missing dates")
        fake = FakeLLMProvider(
            replies=[
                _llm_plan(
                    [
                        {
                            "skill_name": "qt.ai.data.refill_basic_equity_and_index",
                            "inputs": {"tables": ["stock_daily"]},
                        }
                    ]
                )
            ]
        )
        planner = Planner(self.registry, provider=fake, env_facts={})
        plan = planner.build_plan("download A-share daily data to local datasource", mode="plan")
        step = plan.steps[0]
        print(" skill:", step.skill_name, "inputs:", step.inputs)
        self.assertEqual(step.skill_name, "qt.ai.system.fallback")
        self.assertEqual(step.inputs.get("fallback_action"), "clarify_required")
        self.assertEqual(step.inputs.get("missing_info"), "date_range")

    def test_no_provider_p0_skill_sequence_matches_rules(self) -> None:
        """无 Provider 时与规则路径 P0 DAG 技能序列一致。"""

        print("\n[TestAiPlannerHybrid] no provider P0")
        query = "用 macd 在沪深300上跑 2018–2023 回测，给我看年化与最大回撤"
        rule_plan = Planner(self.registry, env_facts={}).build_plan(query, mode="plan")
        hybrid_none = Planner(self.registry, provider=None, env_facts={}).build_plan(query, mode="plan")
        names_rule = [s.skill_name for s in rule_plan.steps]
        names_none = [s.skill_name for s in hybrid_none.steps]
        print(" rule:", names_rule)
        print(" none:", names_none)
        self.assertEqual(names_none, names_rule)
        self.assertEqual(names_none, ["qt.ai.backtest.run_builtin", "qt.ai.insight.summarize_backtest"])
        self.assertEqual(hybrid_none.assumptions.get("candidate_source"), "rule")
        self.assertEqual(rule_plan.steps[0].inputs.get("strategy_id").lower(), "macd")
        self.assertEqual(hybrid_none.steps[0].inputs.get("asset_pool"), "000300.SH")
        self.assertEqual(hybrid_none.steps[0].inputs.get("invest_start"), "20180101")
        self.assertEqual(hybrid_none.steps[0].inputs.get("invest_end"), "20231231")


if __name__ == "__main__":
    unittest.main()
