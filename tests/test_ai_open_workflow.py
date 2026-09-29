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
from qteasy_ai.planner import Planner, ToolPlan
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.session import ConversationState


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

    def test_named_ic_gold_asks_for_missing_slots(self) -> None:
        """裸句缺代码、日期和列名时出澄清，不出可执行 IC 步。"""

        print("\n[TestAiOpenWorkflow] bare factor IC clarifies")
        plan = Planner(self.registry, env_facts={}).build_plan(
            "factor IC summary for selection pool", mode="plan"
        )
        names = [step.skill_name for step in plan.steps]
        inputs = plan.steps[0].inputs if plan.steps else {}
        print(" intent:", plan.planner_trace.get("intent_job"), "skills:", names)
        print(" missing_info:", inputs.get("missing_info"))
        print(" clarification:", (plan.assumptions or {}).get("clarification"))
        self.assertEqual(plan.planner_trace.get("intent_job"), "research.factor_ic")
        self.assertEqual(names, ["qt.ai.system.fallback"])
        self.assertEqual(inputs.get("fallback_action"), "clarify_required")
        missing = str(inputs.get("missing_info") or "")
        self.assertIn("shares", missing)
        self.assertIn("htype", missing)
        self.assertNotIn("qt.ai.research.factor_ic_summary", names)
        self.assertTrue((plan.assumptions or {}).get("clarification"))
        self.assertFalse((plan.assumptions or {}).get("design_loop"))

    def test_factor_ic_unknown_column_clarifies(self) -> None:
        """pct_chg 不是 history 列时澄清，不出 IC 步。"""

        print("\n[TestAiOpenWorkflow] unknown pct_chg clarifies")
        query = (
            "factor IC of close vs pct_chg for 000001.SZ,000002.SZ "
            "from 20240101 to 20240331"
        )
        plan = Planner(self.registry, env_facts={}).build_plan(query, mode="plan")
        names = [step.skill_name for step in plan.steps]
        inputs = plan.steps[0].inputs if plan.steps else {}
        print(" skills:", names)
        print(" missing_info:", inputs.get("missing_info"))
        self.assertEqual(names, ["qt.ai.system.fallback"])
        self.assertEqual(inputs.get("fallback_action"), "clarify_required")
        self.assertIn("pct_chg", str(inputs.get("missing_info") or ""))
        self.assertNotIn("qt.ai.research.factor_ic_summary", names)

    def test_factor_ic_known_columns_keep_all_symbols(self) -> None:
        """close vs volume 保留两只代码和两侧列名。"""

        print("\n[TestAiOpenWorkflow] close vs volume keeps symbols")
        query = (
            "factor IC of close vs volume for 000001.SZ,000002.SZ "
            "from 20240101 to 20240331"
        )
        plan = Planner(self.registry, env_facts={}).build_plan(query, mode="plan")
        names = [step.skill_name for step in plan.steps]
        inputs = plan.steps[0].inputs if plan.steps else {}
        print(" intent:", plan.planner_trace.get("intent_job"))
        print(" skills:", names)
        print(" inputs:", inputs)
        self.assertEqual(plan.planner_trace.get("intent_job"), "research.factor_ic")
        self.assertEqual(names, ["qt.ai.research.factor_ic_summary"])
        self.assertEqual(inputs.get("shares"), "000001.SZ,000002.SZ")
        self.assertEqual(inputs.get("start"), "20240101")
        self.assertEqual(inputs.get("end"), "20240331")
        self.assertEqual(inputs.get("factor_htype"), "close")
        self.assertEqual(inputs.get("return_htype"), "volume")

    def _factor_ic_replan(self, slots: dict) -> ToolPlan:
        """用已确认槽、跳过分类，重出因子 IC 计划。"""

        session = ConversationState.empty("factor-ic-reclarify")
        session.start_task(query="factor IC summary for selection pool", job="research.factor_ic")
        for name, value in slots.items():
            session.set_slot(name, value, source="user", confirmed=True)
        return Planner(self.registry, env_facts={}).build_plan(
            "factor IC summary for selection pool",
            mode="plan",
            session=session,
            skip_classify=True,
        )

    def test_factor_ic_confirmed_bad_column_names_the_slot(self) -> None:
        """已确认的 pct_chg 重出计划时仍澄清，文案点名该列。"""

        print("\n[TestAiOpenWorkflow] confirmed pct_chg replan clarifies")
        plan = self._factor_ic_replan(
            {
                "shares": "000001.SZ,000002.SZ",
                "start": "20240101",
                "end": "20240331",
                "factor_htype": "pct_chg",
                "return_htype": "volume",
            }
        )
        names = [step.skill_name for step in plan.steps]
        inputs = plan.steps[0].inputs if plan.steps else {}
        clar = (plan.assumptions or {}).get("clarification") or {}
        prompt = str(clar.get("confirm_prompt") or "")
        pending = [str(item.get("name") or "") for item in (clar.get("pending") or []) if isinstance(item, dict)]
        print(" skills:", names)
        print(" missing_info:", inputs.get("missing_info"))
        print(" pending:", pending)
        print(" confirm_prompt:", prompt)
        self.assertEqual(names, ["qt.ai.system.fallback"])
        self.assertIn("pct_chg", str(inputs.get("missing_info") or ""))
        self.assertIn("factor_htype", pending)
        self.assertNotIn("pct_chg", pending)
        self.assertIn("pct_chg", prompt)
        self.assertIn("close", prompt)
        self.assertIn("volume", prompt)
        self.assertNotIn("qt.ai.research.factor_ic_summary", names)

    def test_factor_ic_confirmed_legal_slots_emit_ic_step(self) -> None:
        """已确认的 close / volume 与两只代码、日期齐全时出 IC 步。"""

        print("\n[TestAiOpenWorkflow] confirmed close vs volume emits IC")
        plan = self._factor_ic_replan(
            {
                "shares": "000001.SZ,000002.SZ",
                "start": "20240101",
                "end": "20240331",
                "factor_htype": "close",
                "return_htype": "volume",
            }
        )
        names = [step.skill_name for step in plan.steps]
        inputs = plan.steps[0].inputs if plan.steps else {}
        print(" skills:", names)
        print(" inputs:", inputs)
        print(" clarification:", (plan.assumptions or {}).get("clarification"))
        self.assertEqual(names, ["qt.ai.research.factor_ic_summary"])
        self.assertEqual(inputs.get("shares"), "000001.SZ,000002.SZ")
        self.assertEqual(inputs.get("factor_htype"), "close")
        self.assertEqual(inputs.get("return_htype"), "volume")
        self.assertFalse((plan.assumptions or {}).get("clarification"))

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
