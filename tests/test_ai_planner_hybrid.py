# coding=utf-8
# ======================================
# File: test_ai_planner_hybrid.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-28
# Desc:
# Unittest for Hybrid Planner 方案 H′
# （Mode-D LLM 只出 Job ID）
# ======================================

import json
import unittest

from qteasy_ai.app import build_default_registry
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider


def _llm_job(job: str) -> str:
    """构造 FakeLLM 分类 JSON。"""

    return json.dumps({"job": job}, ensure_ascii=False)


class TestAiPlannerHybrid(unittest.TestCase):
    """测试 Job 分类 + 规则出图。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_llm_zero_hit_summary_job_uses_registry_side_effects(self) -> None:
        """0 命中 + LLM Job=data.summary：出图且 side_effects 来自 registry。"""

        print("\n[TestAiPlannerHybrid] llm summary job")
        fake = FakeLLMProvider(replies=[_llm_job("data.summary")])
        planner = Planner(self.registry, provider=fake, env_facts={})
        plan = planner.build_plan("xyzzy unmatched formula 12345", mode="plan")
        step = plan.steps[0]
        meta = self.registry.get_metadata("qt.ai.data.summary_kline")
        print(" intent:", plan.planner_trace.get("intent_job"), plan.planner_trace.get("source"))
        print(" skill:", step.skill_name)
        print(" side_effects:", step.side_effects)
        self.assertEqual(plan.planner_trace.get("intent_job"), "data.summary")
        self.assertEqual(plan.planner_trace.get("source"), "llm")
        self.assertEqual(step.skill_name, "qt.ai.data.summary_kline")
        self.assertEqual(step.side_effects, meta.side_effects)
        self.assertTrue(fake.prompts)
        self.assertIn("data.summary:", fake.prompts[0])
        self.assertNotIn("qt.ai.backtest.run_builtin:", fake.prompts[0])

    def test_llm_unknown_job_clarifies_not_skill_menu(self) -> None:
        """未知 Job id → clarify，不得落到 skill 菜单。"""

        print("\n[TestAiPlannerHybrid] unknown job clarify")
        fake = FakeLLMProvider(replies=[_llm_job("qt.ai.invented.skill")])
        planner = Planner(self.registry, provider=fake, env_facts={})
        plan = planner.build_plan("xyzzy unmatched formula 12345", mode="plan")
        print(" skills:", [s.skill_name for s in plan.steps])
        print(" intent:", plan.planner_trace.get("intent_job"), plan.steps[0].inputs)
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(plan.steps[0].inputs.get("fallback_action"), "clarify_required")
        self.assertNotEqual(plan.planner_trace.get("intent_job"), "data.summary")

    def test_gold_refill_without_dates_still_clarify(self) -> None:
        """下载缺日期仍 clarify date_range。"""

        print("\n[TestAiPlannerHybrid] refill missing dates")
        fake = FakeLLMProvider(replies=[_llm_job("data.refill")])
        planner = Planner(self.registry, provider=fake, env_facts={})
        plan = planner.build_plan("download A-share daily data to local datasource", mode="plan")
        step = plan.steps[0]
        print(" skill:", step.skill_name, "inputs:", step.inputs)
        print(" intent:", plan.planner_trace.get("intent_job"), plan.planner_trace.get("source"))
        print(" prompts:", len(fake.prompts))
        self.assertEqual(plan.planner_trace.get("intent_job"), "data.refill")
        self.assertEqual(plan.planner_trace.get("source"), "llm")
        self.assertEqual(step.skill_name, "qt.ai.system.fallback")
        self.assertEqual(step.inputs.get("fallback_action"), "clarify_required")
        self.assertEqual(step.inputs.get("missing_info"), "date_range")
        self.assertTrue(fake.prompts)

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
        print(" intent:", rule_plan.planner_trace.get("intent_job"), rule_plan.planner_trace.get("source"))
        self.assertEqual(names_none, names_rule)
        self.assertEqual(names_none, ["qt.ai.backtest.run_builtin", "qt.ai.insight.summarize_backtest"])
        self.assertEqual(rule_plan.planner_trace.get("intent_job"), "backtest.builtin")
        self.assertEqual(rule_plan.planner_trace.get("source"), "rule")
        self.assertEqual(rule_plan.steps[0].inputs.get("strategy_id").lower(), "macd")
        self.assertEqual(hybrid_none.steps[0].inputs.get("asset_pool"), "000300.SH")

    def test_screen_paraphrase_mode_d_uses_llm_job(self) -> None:
        """筛股改写句：Mode-D 信 LLM Job，再走同一菜谱。"""

        print("\n[TestAiPlannerHybrid] screen Mode-D llm job")
        query = "请搜索过去半年内所有跌幅>20%，且行业属于公共交通的股票。"
        fake = FakeLLMProvider(replies=[_llm_job("research.screen")])
        hybrid = Planner(self.registry, provider=fake, env_facts={}).build_plan(query, mode="plan")
        names = [s.skill_name for s in hybrid.steps]
        print(" skills:", names)
        print(" intent:", hybrid.planner_trace.get("intent_job"), hybrid.planner_trace.get("source"))
        print(" universe inputs:", hybrid.steps[0].inputs)
        print(" prompts:", len(fake.prompts))
        self.assertEqual(hybrid.planner_trace.get("intent_job"), "research.screen")
        self.assertEqual(hybrid.planner_trace.get("source"), "llm")
        self.assertEqual(names[0], "qt.ai.research.universe_filter")
        self.assertEqual(hybrid.steps[0].inputs.get("industry"), "公共交通")
        self.assertIn("qt.ai.research.price_predicate", names)
        self.assertTrue(fake.prompts)
        self.assertNotIn("recipe_slots_from", hybrid.planner_trace)

    def test_zero_hit_hello_clarifies(self) -> None:
        """无匹配寒暄 → clarify，不得 summary。"""

        print("\n[TestAiPlannerHybrid] hello clarify")
        plan = Planner(self.registry, env_facts={}).build_plan("你好吗？", mode="plan")
        print(" skill:", plan.steps[0].skill_name, plan.steps[0].inputs.get("fallback_action"))
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(plan.steps[0].inputs.get("fallback_action"), "clarify_required")
        self.assertNotEqual(plan.steps[0].skill_name, "qt.ai.data.summary_kline")

    def test_classify_prompt_is_job_catalog(self) -> None:
        """分类 prompt 含 Job 一行定义，不含扁平 skill 菜单。"""

        print("\n[TestAiPlannerHybrid] job catalog prompt")
        fake = FakeLLMProvider(replies=[_llm_job("data.summary")])
        planner = Planner(self.registry, provider=fake, env_facts={})
        plan = planner.build_plan("xyzzy unmatched formula 12345", mode="plan")
        prompt = fake.prompts[0]
        print(" prompt excerpt:", prompt[:400])
        print(" plan skill:", plan.steps[0].skill_name)
        self.assertIn("- data.summary:", prompt)
        self.assertIn("- backtest.builtin:", prompt)
        self.assertNotIn("- qt.ai.backtest.run_builtin:", prompt)
        self.assertNotIn("- qt.ai.data.refill_basic_equity_and_index:", prompt)


if __name__ == "__main__":
    unittest.main()
