# coding=utf-8
# ======================================
# File: test_ai_open_workflow.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-10
# Desc:
# Unittest for G.7 Catalog workflow fork (open design loop)
# ======================================

import unittest

from qteasy_ai.app import build_default_registry
from qteasy_ai.intents import load_default_catalog
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider


class TestAiOpenWorkflow(unittest.TestCase):
    """Catalog ``workflow: open`` 分叉；系统 Job open 不变。"""

    def setUp(self) -> None:
        self.catalog = load_default_catalog()
        self.registry = build_default_registry()

    def test_job_workflow_field(self) -> None:
        """factor_explore 为 open；IC / builder 仍 closed；系统 open 缺省 closed。"""

        print("\n[TestAiOpenWorkflow] job_workflow field")
        print(" factor_explore:", self.catalog.job_workflow("research.factor_explore"))
        print(" factor_ic:", self.catalog.job_workflow("research.factor_ic"))
        print(" builder:", self.catalog.job_workflow("strategy.builder"))
        print(" system open:", self.catalog.job_workflow("open"))
        self.assertEqual(self.catalog.job_workflow("research.factor_explore"), "open")
        self.assertEqual(self.catalog.job_workflow("research.factor_ic"), "closed")
        self.assertEqual(self.catalog.job_workflow("strategy.builder"), "closed")
        self.assertEqual(self.catalog.job_workflow("open"), "closed")

    def test_gold_explore_does_not_enter_empty_design_loop(self) -> None:
        """Mode-R 金句不再把 steps 掏空成设计环。"""

        print("\n[TestAiOpenWorkflow] explore gold not empty design")
        query = "explore a useful momentum factor for hs300"
        plan = Planner(self.registry, env_facts={}).build_plan(query, mode="plan")
        names = [step.skill_name for step in plan.steps]
        print(" intent:", plan.planner_trace.get("intent_job"))
        print(" skills:", names)
        print(" design_loop:", (plan.assumptions or {}).get("design_loop"))
        self.assertEqual(plan.planner_trace.get("intent_job"), "research.factor_explore")
        self.assertFalse(bool((plan.assumptions or {}).get("design_loop")))

    def test_named_ic_gold_stays_closed(self) -> None:
        """点名 IC 金句仍闭合菜谱。"""

        print("\n[TestAiOpenWorkflow] closed IC gold")
        plan = Planner(self.registry, env_facts={}).build_plan(
            "factor IC summary for selection pool", mode="plan"
        )
        names = [step.skill_name for step in plan.steps]
        print(" intent:", plan.planner_trace.get("intent_job"), "skills:", names)
        self.assertEqual(plan.planner_trace.get("intent_job"), "research.factor_ic")
        self.assertEqual(names, ["qt.ai.research.factor_ic_summary"])
        self.assertFalse((plan.assumptions or {}).get("design_loop"))

    def test_system_open_job_still_legal_dag(self) -> None:
        """系统 Job open 仍走合法边 DAG，不是设计环。"""

        print("\n[TestAiOpenWorkflow] system open job")
        import json

        fake = FakeLLMProvider(
            replies=[
                json.dumps({"job": "open"}),
                json.dumps(
                    {
                        "steps": [
                            {"skill_name": "qt.ai.strategy_meta.list", "inputs": {}},
                        ]
                    }
                ),
            ]
        )
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "xyzzy unmatched formula 12345", mode="plan"
        )
        names = [step.skill_name for step in plan.steps]
        print(" intent:", plan.planner_trace.get("intent_job"), "skills:", names)
        print(" design_loop:", (plan.assumptions or {}).get("design_loop"))
        self.assertEqual(plan.planner_trace.get("intent_job"), "open")
        self.assertEqual(names, ["qt.ai.strategy_meta.list"])
        self.assertFalse((plan.assumptions or {}).get("design_loop"))

    def test_followup_does_not_persist_design(self) -> None:
        """Composer 跟进是新 Task，不写 active_design。"""

        print("\n[TestAiOpenWorkflow] follow-up no design persist")
        import tempfile

        from qteasy_ai.app import QteasyAssistant
        from qteasy_ai.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                registry=self.registry,
            )
            sid = "g7-hyp"
            asst.plan(
                "explore a useful momentum factor for hs300",
                response_style="raw",
                session_id=sid,
            )
            second = asst.plan(
                "hypothesis: short-term reversal on hs300",
                response_style="raw",
                session_id=sid,
            )
            state = asst.session_store.load(sid)
            users = [row.get("text") for row in state.messages if row.get("kind") == "user_text"]
            print(" users:", users)
            print(" job:", state.task.job if state.task else None)
            print(" dumped:", sorted(state.to_dict().keys()))
            print(" second skills:", [item.get("skill_name") for item in ((second.get("plan") or {}).get("steps") or [])])
            self.assertIn("hypothesis: short-term reversal on hs300", users)
            self.assertFalse(hasattr(state, "active_design"))
            self.assertNotIn("active_design", state.to_dict())


if __name__ == "__main__":
    unittest.main()
