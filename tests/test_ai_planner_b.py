# coding=utf-8
# ======================================
# File: test_ai_planner_b.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-27
# Desc:
# Unittest for qteasy-ai stage B planner routing
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner


class TestAiPlannerB(unittest.TestCase):
    """测试阶段 B Planner 路由与抽参。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()
        self.planner = Planner(self.registry, env_facts={})

    def test_download_without_dates_clarify(self) -> None:
        """下载缺日期 → clarify_required date_range，禁止无界下载。"""

        print("\n[TestAiPlannerB] download missing dates")
        plan = self.planner.build_plan("download A-share daily data to local datasource", mode="plan")
        step = plan.steps[0]
        print(" skill:", step.skill_name, "action:", step.inputs.get("fallback_action"))
        self.assertEqual(step.skill_name, "qt.ai.system.fallback")
        self.assertEqual(step.inputs.get("fallback_action"), "clarify_required")
        self.assertEqual(step.inputs.get("missing_info"), "date_range")

    def test_download_with_dates_routes_to_refill(self) -> None:
        """带日期的 download → refill skill，无 symbols 时 assumptions 标明 all symbols。"""

        print("\n[TestAiPlannerB] download with dates")
        plan = self.planner.build_plan("download daily data from 20180101 to 20231231", mode="plan")
        names = [step.skill_name for step in plan.steps]
        print(" skills:", names)
        print(" inputs:", plan.steps[-1].inputs)
        print(" assumptions:", plan.assumptions)
        self.assertEqual(names[-1], "qt.ai.data.refill_basic_equity_and_index")
        self.assertEqual(plan.steps[-1].inputs.get("start"), "20180101")
        self.assertEqual(plan.steps[-1].inputs.get("end"), "20231231")
        self.assertEqual(plan.steps[-1].estimated_cost, "high")
        self.assertTrue(plan.steps[-1].side_effects.local_state_change)
        self.assertIn("all symbols", plan.assumptions.get("refill_universe", ""))

    def test_download_prepends_tushare_when_token_missing(self) -> None:
        """env_facts.tushare.token_present is False 时前置 check_tushare。"""

        print("\n[TestAiPlannerB] refill token gate")
        planner = Planner(self.registry, env_facts={"tushare": {"token_present": False}})
        plan = planner.build_plan("refill stock_daily from 20200101 to 20201231", mode="plan")
        names = [step.skill_name for step in plan.steps]
        print(" skills:", names)
        self.assertEqual(names[0], "qt.ai.env.check_tushare")
        self.assertEqual(names[-1], "qt.ai.data.refill_basic_equity_and_index")

    def test_p0_macd_csi300_year_range_backtest_insight_dag(self) -> None:
        """P0：macd + 沪深300 + 2018–2023 + 年化/回撤 → backtest 然后 insight。"""

        print("\n[TestAiPlannerB] P0 DAG")
        query = "用 macd 在沪深300上跑 2018–2023 回测，给我看年化与最大回撤"
        plan = self.planner.build_plan(query, mode="plan")
        names = [step.skill_name for step in plan.steps]
        backtest = plan.steps[0]
        print(" skills:", names)
        print(" backtest inputs:", backtest.inputs)
        print(" insight depends_on:", plan.steps[1].depends_on if len(plan.steps) > 1 else None)
        self.assertEqual(names, ["qt.ai.backtest.run_builtin", "qt.ai.insight.summarize_backtest"])
        self.assertEqual(backtest.inputs.get("strategy_id").lower(), "macd")
        self.assertEqual(backtest.inputs.get("asset_pool"), "000300.SH")
        self.assertEqual(backtest.inputs.get("invest_start"), "20180101")
        self.assertEqual(backtest.inputs.get("invest_end"), "20231231")
        self.assertEqual(plan.steps[1].depends_on, ["step_1"])
        self.assertEqual(plan.steps[1].run_if, "all_dependencies_ok")

    def test_backtest_missing_strategy_clarify(self) -> None:
        """回测缺策略 ID → clarify。"""

        print("\n[TestAiPlannerB] backtest missing strategy")
        plan = self.planner.build_plan("帮我跑一个回测 from 20180101 to 20231231", mode="plan")
        print(" inputs:", plan.steps[0].inputs)
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(plan.steps[0].inputs.get("missing_info"), "strategy_id")

    def test_screen_gold_sentence_not_summary(self) -> None:
        """筛股金句路由到 screen_stocks，不得落到 summary_kline。"""

        print("\n[TestAiPlannerB] screen gold")
        query = "请搜索过去半年内所有跌幅>20%，且行业属于制造业的股票。"
        plan = self.planner.build_plan(query, mode="plan")
        step = plan.steps[0]
        print(" skill:", step.skill_name)
        print(" inputs:", step.inputs)
        self.assertEqual(step.skill_name, "qt.ai.research.screen_stocks")
        self.assertEqual(step.inputs.get("industry"), "制造业")
        self.assertEqual(step.inputs.get("metric"), "drawdown")
        self.assertEqual(step.inputs.get("lookback_days"), 126)
        self.assertAlmostEqual(float(step.inputs.get("threshold")), 0.20, places=10)

    def test_screen_missing_threshold_clarify(self) -> None:
        """筛股缺阈值 → clarify return_threshold。"""

        print("\n[TestAiPlannerB] screen missing threshold")
        plan = self.planner.build_plan("请搜索过去半年行业属于银行的股票", mode="plan")
        print(" inputs:", plan.steps[0].inputs)
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertIn("return_threshold", plan.steps[0].inputs.get("missing_info", ""))

    def test_optimize_dma_routes(self) -> None:
        """optimize DMA → optimize skill，默认 sample=32。"""

        print("\n[TestAiPlannerB] optimize DMA")
        plan = self.planner.build_plan("optimize DMA parameters", mode="plan")
        step = plan.steps[0]
        print(" skill:", step.skill_name, "inputs:", step.inputs)
        self.assertEqual(step.skill_name, "qt.ai.optimize.run_builtin")
        self.assertEqual(str(step.inputs.get("strategy_id")).lower(), "dma")
        self.assertEqual(step.inputs.get("opti_sample_count"), 32)
        self.assertEqual(step.inputs.get("opti_method"), "montecarlo")

    def test_live_and_codegen_still_fallback(self) -> None:
        """实盘走 live_trade_plan_only；StrategyBuilder 不再 not_supported_yet。"""

        print("\n[TestAiPlannerB] live/codegen")
        live = self.planner.build_plan("start live trade now", mode="plan")
        codegen = self.planner.build_plan("生成一个双均线策略 strategybuilder", mode="plan")
        print(" live:", live.steps[0].skill_name, live.execution_mode)
        print(" codegen:", codegen.steps[0].skill_name, codegen.steps[0].inputs.get("fallback_action"))
        self.assertEqual(live.steps[0].skill_name, "qt.ai.pipeline.live_trade_plan_only")
        self.assertEqual(live.execution_mode, "dry_run")
        self.assertNotEqual(codegen.steps[0].inputs.get("fallback_action"), "not_supported_yet")
        self.assertEqual(codegen.steps[0].inputs.get("fallback_action"), "clarify_required")

    def test_unmatched_does_not_default_to_summary(self) -> None:
        """无法匹配时不得默认 summary_kline。"""

        print("\n[TestAiPlannerB] unmatched")
        plan = self.planner.build_plan("随便算一个我发明的夏普公式", mode="plan")
        print(" skill:", plan.steps[0].skill_name, plan.steps[0].inputs.get("fallback_action"))
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertNotEqual(plan.steps[0].skill_name, "qt.ai.data.summary_kline")

    def test_plan_dry_run_does_not_execute_refill_handler(self) -> None:
        """plan() 对高副作用 refill 只出计划，execution 为零步。"""

        print("\n[TestAiPlannerB] plan dry_run refill")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            payload = assistant.plan(
                "download daily data from 20180101 to 20231231",
                response_style="raw",
            )
            print(" status:", payload["execution"]["status"])
            print(" exec steps:", payload["execution"]["steps"])
            print(" plan skills:", [s["skill_name"] for s in payload["plan"]["steps"]])
            self.assertEqual(payload["execution"]["status"], "dry_run")
            self.assertEqual(payload["execution"]["steps"], [])
            self.assertEqual(payload["plan"]["execution_mode"], "dry_run")
            self.assertEqual(payload["plan"]["steps"][0]["skill_name"], "qt.ai.data.refill_basic_equity_and_index")
            self.assertIn("local_state_change", str(payload.get("plan_md", "")))


if __name__ == "__main__":
    unittest.main()
