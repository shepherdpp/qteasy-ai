# coding=utf-8
# ======================================
# File: test_ai_planner_d.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-29
# Desc:
# Unittest for stage D StrategyBuilder DAG
# ======================================

import json
import tempfile
import unittest

from qteasy_ai.app import build_default_registry
from qteasy_ai.contracts import SkillMetadata, SkillSideEffects, ToolPlan, ToolStep
from qteasy_ai.executor import PlanExecutor
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.registry import SkillRegistry


def _llm_plan(steps: list) -> str:
    """构造 FakeLLM 返回的计划 JSON。"""

    return json.dumps({"steps": steps}, ensure_ascii=False)


_BUILDER_SKILLS = [
    "qt.ai.strategy.spec_from_nl",
    "qt.ai.strategy.codegen_hybrid",
    "qt.ai.strategy.sanity_check",
    "qt.ai.operator.build_from_spec",
    "qt.ai.backtest.run_builtin",
]


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
        print(" planner_trace keys:", sorted(plan.planner_trace.keys()))
        self.assertNotIn("llm_skill_sequence", plan.planner_trace)
        self.assertNotIn("llm_skill_sequence", plan.assumptions)

    def test_llm_matching_recipe_overwrites_slots_and_depends(self) -> None:
        """LLM 五步品类对但槽/依赖错时，规则覆写；candidate_source 仍为 llm。"""

        print("\n[TestAiPlannerD] LLM matching recipe overwrites slots")
        fake = FakeLLMProvider(
            replies=[
                _llm_plan(
                    [
                        {
                            "skill_name": "qt.ai.strategy.spec_from_nl",
                            "inputs": {
                                "natural_language": "基于20/60日均线金叉死叉的择时策略",
                                "strategy_name": "dual_ma_20_60",
                                "query": GOLDEN_D1,
                            },
                        },
                        {
                            "skill_name": "qt.ai.strategy.codegen_hybrid",
                            "inputs": {
                                "strategy_name": "dual_ma_20_60",
                                "fast_period": 20,
                                "slow_period": 60,
                            },
                        },
                        {
                            "skill_name": "qt.ai.strategy.sanity_check",
                            "inputs": {"strategy_name": "dual_ma_20_60"},
                        },
                        {
                            "skill_name": "qt.ai.operator.build_from_spec",
                            "inputs": {
                                "operator_name": "dual_ma_20_60",
                                "strategy_name": "dual_ma_20_60",
                            },
                        },
                        {
                            "skill_name": "qt.ai.backtest.run_builtin",
                            "inputs": {
                                "strategy_name": "dual_ma_20_60",
                                "asset_pool": ["000300.SH"],
                                "start_date": "2015-01-01",
                                "end_date": "2020-12-31",
                                "mode": 1,
                                "strategy_id": "GeneratedSmaCross",
                            },
                        },
                    ]
                )
            ]
        )
        hybrid = Planner(self.registry, provider=fake, env_facts={}).build_plan(GOLDEN_D1, mode="plan")
        rule = self.planner.build_plan(GOLDEN_D1, mode="plan")
        names = [step.skill_name for step in hybrid.steps]
        print(" source:", hybrid.assumptions.get("candidate_source"))
        print(" recipe_slots_from:", hybrid.assumptions.get("recipe_slots_from"))
        print(" skills:", names)
        print(" depends:", [step.depends_on for step in hybrid.steps])
        print(" spec inputs:", hybrid.steps[0].inputs)
        print(" backtest inputs:", hybrid.steps[-1].inputs)
        self.assertEqual(hybrid.assumptions.get("candidate_source"), "llm")
        self.assertEqual(hybrid.assumptions.get("recipe_slots_from"), "rule")
        self.assertEqual(names, _BUILDER_SKILLS)
        self.assertEqual([step.depends_on for step in hybrid.steps], [step.depends_on for step in rule.steps])
        self.assertEqual(hybrid.steps[0].inputs, rule.steps[0].inputs)
        self.assertEqual(hybrid.steps[0].inputs, {"query": GOLDEN_D1})
        self.assertNotIn("fast_period", hybrid.steps[1].inputs)
        self.assertNotIn("start_date", hybrid.steps[-1].inputs)
        self.assertEqual(hybrid.steps[-1].inputs.get("asset_pool"), "000300.SH")
        self.assertEqual(hybrid.steps[-1].inputs.get("invest_start"), "20150101")
        self.assertEqual(hybrid.steps[-1].inputs.get("invest_end"), "20201231")
        self.assertEqual(hybrid.steps[-1].inputs, rule.steps[-1].inputs)

    def test_llm_wrapped_seven_steps_overwrites_to_rule_recipe(self) -> None:
        """LLM 在五步前后加 overview/insight 时，整表换成规则五步。"""

        print("\n[TestAiPlannerD] LLM 7-step wrapper overwrites to rule 5")
        fake = FakeLLMProvider(
            replies=[
                _llm_plan(
                    [
                        {
                            "skill_name": "qt.ai.env.overview_tables",
                            "inputs": {"tables": ["index_daily"]},
                        },
                        {
                            "skill_name": "qt.ai.strategy.spec_from_nl",
                            "inputs": {
                                "description": "20/60 金叉死叉",
                                "query": GOLDEN_D1,
                            },
                        },
                        {
                            "skill_name": "qt.ai.strategy.codegen_hybrid",
                            "inputs": {"strategy_name": "ma_cross_20_60", "fast_ma": 20, "slow_ma": 60},
                        },
                        {
                            "skill_name": "qt.ai.strategy.sanity_check",
                            "inputs": {"strategy_file": "ma_cross_20_60"},
                        },
                        {
                            "skill_name": "qt.ai.operator.build_from_spec",
                            "inputs": {"strategy_name": "ma_cross_20_60", "run_freq": "d"},
                        },
                        {
                            "skill_name": "qt.ai.backtest.run_builtin",
                            "inputs": {
                                "strategy": "ma_cross_20_60",
                                "asset_pool": ["000300.SH"],
                                "start_date": "2015-01-01",
                                "end_date": "2020-12-31",
                                "strategy_id": "GeneratedSmaCross",
                            },
                        },
                        {
                            "skill_name": "qt.ai.insight.summarize_backtest",
                            "inputs": {"strategy": "ma_cross_20_60", "start_date": "2015-01-01"},
                        },
                    ]
                )
            ]
        )
        hybrid = Planner(self.registry, provider=fake, env_facts={}).build_plan(GOLDEN_D1, mode="plan")
        rule = self.planner.build_plan(GOLDEN_D1, mode="plan")
        names = [step.skill_name for step in hybrid.steps]
        print(" source:", hybrid.assumptions.get("candidate_source"))
        print(" recipe_slots_from:", hybrid.assumptions.get("recipe_slots_from"))
        print(" skills:", names)
        print(" depends:", [step.depends_on for step in hybrid.steps])
        print(" backtest inputs:", hybrid.steps[-1].inputs if names else None)
        self.assertEqual(hybrid.assumptions.get("candidate_source"), "llm")
        self.assertEqual(hybrid.assumptions.get("recipe_slots_from"), "rule")
        self.assertEqual(names, _BUILDER_SKILLS)
        self.assertEqual(len(hybrid.steps), 5)
        self.assertEqual([step.depends_on for step in hybrid.steps], [step.depends_on for step in rule.steps])
        self.assertEqual(hybrid.steps[0].inputs, {"query": GOLDEN_D1})
        self.assertEqual(hybrid.steps[-1].inputs.get("asset_pool"), "000300.SH")
        self.assertEqual(hybrid.steps[-1].inputs.get("invest_start"), "20150101")
        self.assertEqual(hybrid.steps[-1].inputs, rule.steps[-1].inputs)
        expected_l = [
            "qt.ai.env.overview_tables",
            "qt.ai.strategy.spec_from_nl",
            "qt.ai.strategy.codegen_hybrid",
            "qt.ai.strategy.sanity_check",
            "qt.ai.operator.build_from_spec",
            "qt.ai.backtest.run_builtin",
            "qt.ai.insight.summarize_backtest",
        ]
        print(" llm_skill_sequence:", hybrid.planner_trace.get("llm_skill_sequence"))
        self.assertEqual(hybrid.planner_trace.get("llm_skill_sequence"), expected_l)
        self.assertEqual(hybrid.assumptions.get("llm_skill_sequence"), expected_l)

    def test_llm_prefix_sequence_completes_to_rule_recipe(self) -> None:
        """LLM 只吐规则菜谱前缀时，补成完整规则图。"""

        print("\n[TestAiPlannerD] LLM prefix completes to full rule recipe")
        fake = FakeLLMProvider(
            replies=[
                _llm_plan(
                    [
                        {
                            "skill_name": "qt.ai.strategy.spec_from_nl",
                            "inputs": {"natural_language": "dual ma", "strategy_name": "dual_ma_20_60"},
                        },
                        {
                            "skill_name": "qt.ai.strategy.codegen_hybrid",
                            "inputs": {"fast_period": 20, "slow_period": 60},
                        },
                        {
                            "skill_name": "qt.ai.strategy.sanity_check",
                            "inputs": {"strategy_name": "dual_ma_20_60"},
                        },
                        {
                            "skill_name": "qt.ai.operator.build_from_spec",
                            "inputs": {"operator_name": "dual_ma_20_60"},
                        },
                    ]
                )
            ]
        )
        hybrid = Planner(self.registry, provider=fake, env_facts={}).build_plan(GOLDEN_D1, mode="plan")
        names = [step.skill_name for step in hybrid.steps]
        print(" source:", hybrid.assumptions.get("candidate_source"))
        print(" recipe_slots_from:", hybrid.assumptions.get("recipe_slots_from"))
        print(" skills:", names)
        self.assertEqual(hybrid.assumptions.get("candidate_source"), "llm")
        self.assertEqual(hybrid.assumptions.get("recipe_slots_from"), "rule")
        self.assertEqual(names, _BUILDER_SKILLS)
        self.assertEqual(hybrid.steps[-1].inputs.get("invest_end"), "20201231")

    def test_llm_interrupted_sequence_does_not_overwrite(self) -> None:
        """LLM 在菜谱中间插入其它 skill 时不覆写。"""

        print("\n[TestAiPlannerD] LLM interrupted sequence keeps candidate slots")
        fake = FakeLLMProvider(
            replies=[
                _llm_plan(
                    [
                        {
                            "skill_name": "qt.ai.strategy.spec_from_nl",
                            "inputs": {"natural_language": "dual ma", "strategy_name": "dual_ma_20_60"},
                        },
                        {
                            "skill_name": "qt.ai.data.refill_basic_equity_and_index",
                            "inputs": {"tables": ["index_daily"], "start": "20150101", "end": "20201231"},
                        },
                        {
                            "skill_name": "qt.ai.strategy.codegen_hybrid",
                            "inputs": {"fast_period": 20, "slow_period": 60},
                        },
                        {
                            "skill_name": "qt.ai.strategy.sanity_check",
                            "inputs": {"strategy_name": "dual_ma_20_60"},
                        },
                        {
                            "skill_name": "qt.ai.operator.build_from_spec",
                            "inputs": {"operator_name": "dual_ma_20_60"},
                        },
                        {
                            "skill_name": "qt.ai.backtest.run_builtin",
                            "inputs": {"start_date": "2015-01-01", "strategy_id": "GeneratedSmaCross"},
                        },
                    ]
                )
            ]
        )
        hybrid = Planner(self.registry, provider=fake, env_facts={}).build_plan(GOLDEN_D1, mode="plan")
        names = [step.skill_name for step in hybrid.steps]
        print(" source:", hybrid.assumptions.get("candidate_source"))
        print(" recipe_slots_from:", hybrid.assumptions.get("recipe_slots_from"))
        print(" skills:", names)
        print(" depends:", [step.depends_on for step in hybrid.steps])
        print(" codegen inputs:", hybrid.steps[2].inputs if len(hybrid.steps) > 2 else None)
        self.assertEqual(hybrid.assumptions.get("candidate_source"), "llm")
        self.assertNotEqual(hybrid.assumptions.get("recipe_slots_from"), "rule")
        self.assertEqual(len(names), 6)
        self.assertEqual(names[1], "qt.ai.data.refill_basic_equity_and_index")
        self.assertIn("qt.ai.strategy.codegen_hybrid", names)
        codegen = next(step for step in hybrid.steps if step.skill_name == "qt.ai.strategy.codegen_hybrid")
        self.assertEqual(codegen.depends_on, [])
        self.assertEqual(codegen.inputs.get("fast_period"), 20)

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

    def test_llm_incomplete_builder_overwrites_codegen_to_clarify(self) -> None:
        """Mode-D 单步 codegen 漏网时，SB fallback 菜谱仍覆写为澄清。"""

        print("\n[TestAiPlannerD] LLM incomplete builder overwrites codegen to clarify")
        query = "生成一个双均线策略 strategybuilder"
        fake = FakeLLMProvider(
            replies=[
                _llm_plan(
                    [
                        {
                            "skill_name": "qt.ai.strategy.codegen_hybrid",
                            "inputs": {"strategy_name": "dual_ma_strategy"},
                        }
                    ]
                )
            ]
        )
        hybrid = Planner(self.registry, provider=fake, env_facts={}).build_plan(query, mode="plan")
        print(" source:", hybrid.assumptions.get("candidate_source"))
        print(" recipe_slots_from:", hybrid.assumptions.get("recipe_slots_from"))
        print(" skill:", hybrid.steps[0].skill_name)
        print(" inputs:", hybrid.steps[0].inputs)
        self.assertEqual(hybrid.assumptions.get("candidate_source"), "llm")
        self.assertEqual(hybrid.assumptions.get("recipe_slots_from"), "rule")
        self.assertEqual(hybrid.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(hybrid.steps[0].inputs.get("fallback_action"), "clarify_required")
        missing = str(hybrid.steps[0].inputs.get("missing_info") or "")
        print(" missing_info:", missing)
        print(" llm_skill_sequence:", hybrid.planner_trace.get("llm_skill_sequence"))
        self.assertTrue("fast" in missing or "slow" in missing)
        self.assertEqual(
            hybrid.planner_trace.get("llm_skill_sequence"),
            ["qt.ai.strategy.codegen_hybrid"],
        )

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
