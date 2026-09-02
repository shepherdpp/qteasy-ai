# coding=utf-8
# ======================================
# File: test_ai_planner_e.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-02
# Desc:
# Unittest for Phase E 装配：trace / open / schema
# ======================================

import json
import unittest

from qteasy_ai.app import build_default_registry
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider


class TestAiPlannerE(unittest.TestCase):
    """E.0 装配层：intent_job、open 合法边、schema。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_known_job_trace_fields(self) -> None:
        """已知 Job 的 planner_trace 含 intent_job / source / rationale。"""

        print("\n[TestAiPlannerE] trace fields")
        plan = Planner(self.registry, env_facts={}).build_plan("list built-in strategies", mode="plan")
        print(" trace:", plan.planner_trace)
        print(" skills:", [s.skill_name for s in plan.steps])
        self.assertEqual(plan.planner_trace.get("intent_job"), "strategy.meta")
        self.assertEqual(plan.planner_trace.get("source"), "rule")
        self.assertTrue(str(plan.planner_trace.get("rationale") or ""))
        self.assertNotIn("recipe_slots_from", plan.planner_trace)
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.strategy_meta.list")

    def test_open_legal_summary_dag(self) -> None:
        """open 合法低副作用 DAG 放行，不压成官方菜谱。"""

        print("\n[TestAiPlannerE] open legal dag")
        fake = FakeLLMProvider(
            replies=[
                json.dumps({"job": "open"}),
                json.dumps(
                    {
                        "steps": [
                            {"skill_name": "qt.ai.strategy_meta.list", "inputs": {}},
                            {"skill_name": "qt.ai.data.summary_kline", "inputs": {"shares": "000300.SH"}},
                        ]
                    }
                ),
            ]
        )
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "xyzzy unmatched formula 12345", mode="plan"
        )
        names = [s.skill_name for s in plan.steps]
        print(" skills:", names, "intent:", plan.planner_trace.get("intent_job"))
        print(" prompts:", len(fake.prompts))
        self.assertEqual(plan.planner_trace.get("intent_job"), "open")
        self.assertEqual(names, ["qt.ai.strategy_meta.list", "qt.ai.data.summary_kline"])
        self.assertGreaterEqual(len(fake.prompts), 2)

    def test_open_drops_unknown_input_keys(self) -> None:
        """schema：丢掉未知键。"""

        print("\n[TestAiPlannerE] drop unknown keys")
        fake = FakeLLMProvider(
            replies=[
                json.dumps({"job": "open"}),
                json.dumps(
                    {
                        "steps": [
                            {
                                "skill_name": "qt.ai.strategy_meta.get",
                                "inputs": {"strategy_id": "macd", "invented_key": 1},
                            }
                        ]
                    }
                ),
            ]
        )
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "xyzzy unmatched formula 12345", mode="plan"
        )
        print(" inputs:", plan.steps[0].inputs)
        print(" corrections:", plan.planner_trace.get("validator_trace", {}).get("corrections"))
        self.assertEqual(plan.steps[0].inputs.get("strategy_id"), "macd")
        self.assertNotIn("invented_key", plan.steps[0].inputs)

    def test_data_read_job_routes(self) -> None:
        """data.read Job 出三入口 skill。"""

        print("\n[TestAiPlannerE] data.read")
        plan = Planner(self.registry, env_facts={}).build_plan(
            "get_static_data industry for 000001.SZ", mode="plan"
        )
        print(" skill:", plan.steps[0].skill_name, plan.steps[0].inputs)
        print(" intent:", plan.planner_trace.get("intent_job"))
        self.assertEqual(plan.planner_trace.get("intent_job"), "data.read")
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.data.read")
        self.assertEqual(plan.steps[0].inputs.get("channel"), "static")

    def test_inverted_dates_clarify(self) -> None:
        """倒置日期区间 → clarify，不得落到 summary 执行失败。"""

        print("\n[TestAiPlannerE] inverted dates")
        plan = Planner(self.registry, env_facts={}).build_plan(
            "show kline summary 000300.SH from 20241231 to 20240101", mode="plan"
        )
        print(" skill:", plan.steps[0].skill_name, plan.steps[0].inputs)
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(plan.steps[0].inputs.get("fallback_action"), "clarify_required")
        self.assertEqual(plan.steps[0].inputs.get("reason"), "invalid_date_range")

    def test_invalid_freq_clarify(self) -> None:
        """非法 freq → clarify。"""

        print("\n[TestAiPlannerE] invalid freq")
        plan = Planner(self.registry, env_facts={}).build_plan(
            "summary kline freq=not_a_freq 000300.SH", mode="plan"
        )
        print(" skill:", plan.steps[0].skill_name, plan.steps[0].inputs)
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(plan.steps[0].inputs.get("reason"), "invalid_frequency_expression")


if __name__ == "__main__":
    unittest.main()
