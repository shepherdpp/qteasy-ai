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

    def test_llm_screen_query_blob_fills_required_slots_from_rules(self) -> None:
        """LLM 把筛股整句塞进 query 时，用规则路径补齐 industry/threshold。"""

        print("\n[TestAiPlannerHybrid] LLM screen query-blob fills slots from rules")
        query = "请搜索过去半年内所有跌幅>20%，且行业属于公共交通的股票。"
        fake = FakeLLMProvider(
            replies=[
                _llm_plan(
                    [
                        {
                            "skill_name": "qt.ai.research.screen_stocks",
                            "inputs": {
                                "query": "过去半年内跌幅>20%且行业属于公共交通的股票",
                            },
                        }
                    ]
                )
            ]
        )
        hybrid = Planner(self.registry, provider=fake, env_facts={}).build_plan(query, mode="plan")
        rule = Planner(self.registry, env_facts={}).build_plan(query, mode="plan")
        print(" hybrid source:", hybrid.assumptions.get("candidate_source"))
        print(" hybrid skill/inputs:", hybrid.steps[0].skill_name, hybrid.steps[0].inputs)
        print(" rule skill/inputs:", rule.steps[0].skill_name, rule.steps[0].inputs)
        self.assertEqual(hybrid.steps[0].skill_name, "qt.ai.research.screen_stocks")
        self.assertEqual(hybrid.steps[0].inputs.get("industry"), "公共交通")
        self.assertEqual(float(hybrid.steps[0].inputs.get("threshold")), 0.2)
        self.assertEqual(rule.steps[0].skill_name, "qt.ai.research.screen_stocks")
        self.assertEqual(rule.steps[0].inputs.get("industry"), "公共交通")
        self.assertEqual(float(rule.steps[0].inputs.get("threshold")), 0.2)
        self.assertNotEqual(hybrid.steps[0].inputs, {})

    def test_llm_empty_fallback_fills_required_slots_from_rules(self) -> None:
        """LLM 给出空 inputs 的 fallback 时，用规则路径填齐必填槽。"""

        print("\n[TestAiPlannerHybrid] LLM empty fallback fills slots from rules")
        query = "你好吗？"
        fake = FakeLLMProvider(
            replies=[_llm_plan([{"skill_name": "qt.ai.system.fallback", "inputs": {}}])]
        )
        hybrid = Planner(self.registry, provider=fake, env_facts={}).build_plan(query, mode="plan")
        rule = Planner(self.registry, env_facts={}).build_plan(query, mode="plan")
        print(" hybrid source/inputs:", hybrid.assumptions.get("candidate_source"), hybrid.steps[0].inputs)
        print(" rule action:", rule.steps[0].inputs.get("fallback_action"), rule.steps[0].inputs.get("reason"))
        self.assertEqual(hybrid.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(rule.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(hybrid.steps[0].inputs.get("query"), query)
        self.assertTrue(hybrid.steps[0].inputs.get("fallback_action"))
        self.assertTrue(hybrid.steps[0].inputs.get("reason"))
        self.assertEqual(
            hybrid.steps[0].inputs.get("fallback_action"),
            rule.steps[0].inputs.get("fallback_action"),
        )
        self.assertEqual(hybrid.steps[0].inputs.get("reason"), rule.steps[0].inputs.get("reason"))
        self.assertNotEqual(hybrid.steps[0].inputs, {})

    def test_llm_screen_complete_slots_keeps_candidate_source_llm(self) -> None:
        """LLM 已填齐筛股必填槽时保留 candidate_source=llm，不被规则覆盖。"""

        print("\n[TestAiPlannerHybrid] LLM screen complete slots stay llm")
        query = "请搜索过去半年内所有跌幅>20%，且行业属于公共交通的股票。"
        fake = FakeLLMProvider(
            replies=[
                _llm_plan(
                    [
                        {
                            "skill_name": "qt.ai.research.screen_stocks",
                            "inputs": {
                                "industry": "银行",
                                "threshold": 0.15,
                            },
                        }
                    ]
                )
            ]
        )
        hybrid = Planner(self.registry, provider=fake, env_facts={}).build_plan(query, mode="plan")
        print(" source:", hybrid.assumptions.get("candidate_source"))
        print(" inputs:", hybrid.steps[0].inputs)
        self.assertEqual(hybrid.assumptions.get("candidate_source"), "llm")
        self.assertEqual(hybrid.steps[0].skill_name, "qt.ai.research.screen_stocks")
        self.assertEqual(hybrid.steps[0].inputs.get("industry"), "银行")
        self.assertEqual(float(hybrid.steps[0].inputs.get("threshold")), 0.15)

    def test_llm_catalog_includes_skill_name_and_summary(self) -> None:
        """Hybrid 候选 prompt 对每个已注册 skill 含一行 name: summary。"""

        print("\n[TestAiPlannerHybrid] catalog name + summary")
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
                        }
                    ]
                )
            ]
        )
        planner = Planner(self.registry, provider=fake, env_facts={})
        plan = planner.build_plan("run macd backtest 2018-2023 on 000300.SH", mode="plan")
        self.assertTrue(fake.prompts)
        prompt = fake.prompts[0]
        print(" prompt catalog excerpt:", prompt[:800])
        print(" plan skill:", plan.steps[0].skill_name)
        skills = self.registry.list_skills()
        self.assertGreaterEqual(len(skills), 1)
        for meta in skills:
            expected_line = f"- {meta.name}: {meta.summary}"
            print(" expect line:", expected_line)
            self.assertIn(expected_line, prompt)
            self.assertTrue(str(meta.summary).strip())
        self.assertIn("qt.ai.backtest.run_builtin:", prompt)
        self.assertIn("qt.ai.data.refill_basic_equity_and_index:", prompt)
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.backtest.run_builtin")

    def test_llm_screen_missing_slots_clarifies_when_rules_cannot_fill(self) -> None:
        """LLM 点了筛股但规则走 fallback、缺槽无法填时改为 clarify_required。"""

        print("\n[TestAiPlannerHybrid] LLM screen missing slots clarify")
        query = "你好吗？"
        fake = FakeLLMProvider(
            replies=[
                _llm_plan(
                    [
                        {
                            "skill_name": "qt.ai.research.screen_stocks",
                            "inputs": {},
                        }
                    ]
                )
            ]
        )
        hybrid = Planner(self.registry, provider=fake, env_facts={}).build_plan(query, mode="plan")
        rule = Planner(self.registry, env_facts={}).build_plan(query, mode="plan")
        print(" hybrid skill/inputs:", hybrid.steps[0].skill_name, hybrid.steps[0].inputs)
        print(" rule skill:", rule.steps[0].skill_name, rule.steps[0].inputs.get("fallback_action"))
        self.assertEqual(hybrid.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(hybrid.steps[0].inputs.get("fallback_action"), "clarify_required")
        missing = str(hybrid.steps[0].inputs.get("missing_info") or "")
        print(" missing_info:", missing)
        self.assertIn("industry", missing)
        self.assertIn("threshold", missing)
        self.assertEqual(rule.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertNotEqual(rule.steps[0].inputs.get("fallback_action"), "clarify_required")


if __name__ == "__main__":
    unittest.main()
