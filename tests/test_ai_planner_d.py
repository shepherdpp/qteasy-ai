# coding=utf-8
# ======================================
# File: test_ai_planner_d.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-29
# Desc:
# Unittest for stage D StrategyBuilder DAG
# ======================================

import tempfile
import unittest

from qteasy_ai.app import build_default_registry
from qteasy_ai.contracts import ToolPlan, ToolStep
from qteasy_ai.executor import PlanExecutor
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner
from qteasy_ai.registry import SkillRegistry
from qteasy_ai.contracts import SkillMetadata, SkillSideEffects


GOLDEN_D1 = "帮我写一个基于 20/60 日均线金叉死叉的择时策略，并用 2015–2020 年沪深300做回测"


class TestAiPlannerD(unittest.TestCase):
    """测试阶段 D 规则路径 DAG。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()
        self.planner = Planner(self.registry, env_facts={})

    def test_golden_sentence_strategy_builder_dag(self) -> None:
        """金句 → spec/codegen/sanity/build/backtest，depends_on 串联。"""

        print("\n[TestAiPlannerD] golden DAG")
        plan = self.planner.build_plan(GOLDEN_D1, mode="plan")
        names = [step.skill_name for step in plan.steps]
        print(" skills:", names)
        print(" depends:", [step.depends_on for step in plan.steps])
        print(" backtest inputs:", plan.steps[-1].inputs if names else None)
        expected = [
            "qt.ai.strategy.spec_from_nl",
            "qt.ai.strategy.codegen_hybrid",
            "qt.ai.strategy.sanity_check",
            "qt.ai.operator.build_from_spec",
            "qt.ai.backtest.run_builtin",
        ]
        self.assertEqual(names, expected)
        self.assertEqual(plan.steps[1].depends_on, ["step_1"])
        self.assertEqual(plan.steps[2].depends_on, ["step_2"])
        self.assertEqual(plan.steps[3].depends_on, ["step_3"])
        self.assertEqual(plan.steps[4].depends_on, ["step_4"])
        bt = plan.steps[4]
        self.assertEqual(bt.inputs.get("asset_pool"), "000300.SH")
        self.assertEqual(bt.inputs.get("invest_start"), "20150101")
        self.assertEqual(bt.inputs.get("invest_end"), "20201231")
        self.assertEqual(bt.inputs.get("freq"), "d")
        self.assertEqual(plan.execution_mode, "dry_run")

    def test_incomplete_builder_clarifies_not_unsupported(self) -> None:
        """双均线缺周期 → clarify，不再 not_supported_yet。"""

        print("\n[TestAiPlannerD] incomplete builder")
        plan = self.planner.build_plan("生成一个双均线策略 strategybuilder", mode="plan")
        print(" skill:", plan.steps[0].skill_name, "inputs:", plan.steps[0].inputs)
        self.assertNotEqual(plan.steps[0].inputs.get("fallback_action"), "not_supported_yet")
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(plan.steps[0].inputs.get("fallback_action"), "clarify_required")
        missing = str(plan.steps[0].inputs.get("missing_info") or "")
        self.assertTrue("fast" in missing or "slow" in missing)

    def test_executor_dry_run_does_not_call_codegen(self) -> None:
        """confirm=False 时 codegen 高副作用不执行。"""

        print("\n[TestAiPlannerD] executor dry_run skips codegen")
        called = {"n": 0}
        registry = SkillRegistry()
        meta = SkillMetadata(
            name="qt.ai.strategy.codegen_hybrid",
            version="0.1.0",
            summary="test codegen",
            inputs_schema={},
            outputs_schema={},
            side_effects=SkillSideEffects(filesystem_write=True, description="write"),
        )

        def handler(**kwargs):
            called["n"] += 1
            return {"ok": True}

        registry.register(meta, handler)
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            executor = PlanExecutor(registry=registry, memory_store=store)
            step = ToolStep(
                step_id="step_1",
                skill_name=meta.name,
                inputs={},
                side_effects=meta.side_effects,
            )
            plan = ToolPlan(
                plan_id="plan_d_codegen",
                user_query="codegen",
                steps=[step],
                execution_mode="dry_run",
            )
            dry = executor.execute(plan, confirm=False)
            print(" dry status:", dry["execution"]["status"], "called:", called["n"])
            self.assertEqual(dry["execution"]["status"], "dry_run")
            self.assertEqual(called["n"], 0)
            plan.execution_mode = "execute"
            run = executor.execute(plan, confirm=True)
            print(" run status:", run["execution"]["status"], "called:", called["n"])
            self.assertEqual(called["n"], 1)
            self.assertTrue(run["execution"]["steps"][0]["result"]["ok"])


if __name__ == "__main__":
    unittest.main()
