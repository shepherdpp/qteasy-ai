# coding=utf-8
# ======================================
# File: test_ai_open_builder.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-10
# Desc:
# Unittest for strategy.builder open_loop smoke vs closed DMA
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner


GOLDEN_D1 = "帮我写一个基于 20/60 日均线金叉死叉的择时策略，并用 2015–2020 年沪深300做回测"
_BUILDER_SKILLS = [
    "qt.ai.strategy.spec_from_nl",
    "qt.ai.strategy.codegen_hybrid",
    "qt.ai.strategy.sanity_check",
    "qt.ai.operator.build_from_spec",
    "qt.ai.backtest.run_builtin",
]


class TestAiOpenBuilder(unittest.TestCase):
    """无模板策略进设计环；双均线金句仍五步闭合。"""

    def test_vague_builder_open_loop_no_codegen(self) -> None:
        """还没想好规则 → strategy.builder + open_loop，无 codegen_hybrid。"""

        print("\n[TestAiOpenBuilder] vague builder open_loop")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                registry=build_default_registry(),
            )
            payload = asst.plan(
                "还没想好规则，帮我设计一个策略",
                response_style="raw",
                session_id="g7-builder",
            )
            plan = payload.get("plan") or {}
            names = [item.get("skill_name") for item in (plan.get("steps") or [])]
            assumptions = plan.get("assumptions") or {}
            flags = ((payload.get("session") or {}).get("active_intent") or {}).get("flags") or {}
            state = asst.session_store.load("g7-builder")
            print(" intent:", (plan.get("planner_trace") or {}).get("intent_job"))
            print(" skills:", names)
            print(" design_loop:", assumptions.get("design_loop"))
            print(" flags:", (state.active_intent or {}).get("flags"))
            self.assertEqual((plan.get("planner_trace") or {}).get("intent_job"), "strategy.builder")
            self.assertTrue(assumptions.get("design_loop"))
            self.assertNotIn("qt.ai.strategy.codegen_hybrid", names)
            self.assertTrue((state.active_intent or {}).get("flags", {}).get("open_loop") or flags.get("open_loop"))
            print(" spec:", assumptions.get("spec_draft"))

    def test_dma_gold_stays_closed_five_steps(self) -> None:
        """20/60 日均线金叉仍走现有五步闭合菜谱。"""

        print("\n[TestAiOpenBuilder] DMA gold closed")
        plan = Planner(build_default_registry(), env_facts={}).build_plan(GOLDEN_D1, mode="plan")
        names = [step.skill_name for step in plan.steps]
        print(" intent:", plan.planner_trace.get("intent_job"))
        print(" skills:", names)
        print(" design_loop:", (plan.assumptions or {}).get("design_loop"))
        self.assertEqual(plan.planner_trace.get("intent_job"), "strategy.builder")
        self.assertEqual(names, _BUILDER_SKILLS)
        self.assertFalse((plan.assumptions or {}).get("design_loop"))


if __name__ == "__main__":
    unittest.main()
