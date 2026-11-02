# coding=utf-8
# ======================================
# File: test_ai_planner_b0.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-25
# Desc:
# Unittest for qteasy-ai B0 planner routing
# and env_facts gate
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner
from qteasy_ai.skills.datasource_tables import build_table_info_skill
from qteasy_ai.skills.env_guide import DEFAULT_CORE_TABLES, build_check_tushare_skill


class TestAiPlannerB0(unittest.TestCase):
    """测试 B0 规则多步路由与 env_facts 门禁。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_env_query_two_step_plan(self) -> None:
        """环境检查问法产出 check_tushare 和四张核心表的 table_info。"""

        print("\n[TestAiPlannerB0] env query table_info")
        planner = Planner(self.registry, env_facts={})
        plan = planner.build_plan("帮我看 Tushare 是否配好、本地缺哪些表", mode="plan")
        skill_names = [step.skill_name for step in plan.steps]
        tables = [step.inputs.get("table_name") for step in plan.steps[1:]]
        print(" skills:", skill_names)
        print(" tables:", tables)
        self.assertEqual(skill_names[0], "qt.ai.env.check_tushare")
        self.assertEqual(skill_names[1:], ["qt.ai.datasource.table_info"] * 4)
        self.assertEqual(tables, list(DEFAULT_CORE_TABLES))
        self.assertEqual(len(plan.steps), 5)
        for step in plan.steps:
            self.assertEqual(step.depends_on, [])

    def test_export_kline_line_only_when_close_curve_requested(self) -> None:
        """普通导出不传 plot_type；明确收盘曲线才是 line。"""

        print("\n[TestAiPlannerB0] export plot_type")
        planner = Planner(self.registry, env_facts={})
        candle = planner.build_plan("export kline of 000300.SH to png", mode="plan")
        line = planner.build_plan("export close curve of 000300.SH", mode="plan")
        legacy_candle = planner._infer_steps(
            query="export kline of 000300.SH to png",
            q_lower="export kline of 000300.SH to png",
        )
        legacy_line = planner._infer_steps(
            query="导出 000300.SH 折线",
            q_lower="导出 000300.SH 折线",
        )
        print(" candle skills:", [step.skill_name for step in candle.steps])
        print(" candle inputs:", [step.inputs for step in candle.steps])
        print(" line skills:", [step.skill_name for step in line.steps])
        print(" legacy line:", [step.skill_name for step in legacy_line], [step.inputs for step in legacy_line])

        self.assertEqual(
            [step.skill_name for step in candle.steps],
            ["qt.ai.data.kline", "qt.ai.hp.plot"],
        )
        self.assertTrue(all("plot_type" not in step.inputs for step in candle.steps))
        self.assertEqual(
            [step.skill_name for step in line.steps],
            ["qt.ai.data.kline", "qt.ai.hp.plot"],
        )
        self.assertTrue(all("plot_type" not in step.inputs for step in line.steps))
        self.assertEqual(
            [step.skill_name for step in legacy_candle],
            ["qt.ai.data.kline", "qt.ai.hp.plot"],
        )
        self.assertEqual(
            [step.skill_name for step in legacy_line],
            ["qt.ai.data.kline", "qt.ai.hp.plot"],
        )
        self.assertTrue(all("plot_type" not in step.inputs for step in legacy_line))

    def test_kline_summary_routes_to_summary_not_export(self) -> None:
        """kline summary 走取数、波动率和结构摘要，不落到导出。"""

        print("\n[TestAiPlannerB0] kline summary routing")
        planner = Planner(self.registry, env_facts={})
        plan = planner.build_plan("kline summary of 000300.SH", mode="plan")
        skill_names = [step.skill_name for step in plan.steps]
        print(" skills:", skill_names)
        self.assertEqual(
            skill_names,
            ["qt.ai.data.kline", "qt.ai.hp.volatility", "qt.ai.hp.describe"],
        )
        self.assertEqual(plan.steps[0].inputs.get("shares"), "000300.SH")

    def test_empty_env_facts_summary_has_no_table_gate(self) -> None:
        """空 env_facts 时 summary 不前置 overview。"""

        print("\n[TestAiPlannerB0] empty env_facts summary chain")
        planner = Planner(self.registry, env_facts={})
        plan = planner.build_plan("show summary of 000300.SH from 20240101 to 20241231", mode="plan")
        skill_names = [step.skill_name for step in plan.steps]
        print(" skills:", skill_names)
        self.assertEqual(
            skill_names,
            ["qt.ai.data.kline", "qt.ai.hp.volatility", "qt.ai.hp.describe"],
        )
        self.assertNotIn("qt.ai.env.overview_tables", skill_names)

    def test_missing_table_gate_prepends_overview(self) -> None:
        """已记录 index_daily.exists=False 时 summary 前置 overview_tables。"""

        print("\n[TestAiPlannerB0] missing table gate")
        env_facts = {
            "tables": {
                "index_daily": {"exists": False, "rows": 0},
                "stock_daily": {"exists": True, "rows": 10},
            }
        }
        planner = Planner(self.registry, env_facts=env_facts)
        plan = planner.build_plan("show summary of 000300.SH", mode="plan")
        skill_names = [step.skill_name for step in plan.steps]
        print(" skills:", skill_names)
        self.assertGreaterEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.env.overview_tables")
        self.assertIn("qt.ai.data.kline", skill_names)
        self.assertEqual(plan.steps[-1].skill_name, "qt.ai.hp.describe")
        kline = next(step for step in plan.steps if step.skill_name == "qt.ai.data.kline")
        self.assertEqual(plan.steps[-1].depends_on, [kline.step_id])

    def test_run_merges_env_facts_after_guide_execute(self) -> None:
        """execute 成功后 Assistant 将 guide 探针 merge 进 env_facts。"""

        print("\n[TestAiPlannerB0] merge env_facts after execute")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            registry = build_default_registry()
            # 覆盖默认 env skills 为 DI 探针，避免真实 QT_CONFIG/DataSource
            for name in ["qt.ai.env.check_tushare", "qt.ai.datasource.table_info"]:
                registry._meta.pop(name, None)
                registry._impl.pop(name, None)
            meta_t, handler_t = build_check_tushare_skill(
                token_getter=lambda: {"token_present": True, "token_source": "qt_config"}
            )
            catalog = {
                "stock_daily": {"exists": True, "rows": 42},
                "index_daily": {"exists": True, "rows": 10},
                "trade_calendar": {"exists": True, "rows": 100},
                "stock_basic": {"exists": True, "rows": 5},
            }

            def fake_info(table, verbose=False, print_info=False, human=False):
                return catalog.get(table, {"exists": False, "rows": 0})

            meta_i, handler_i = build_table_info_skill(
                table_info_func=fake_info,
                schema_func=lambda table: [],
            )
            registry.register(meta_t, handler_t)
            registry.register(meta_i, handler_i)

            assistant = QteasyAssistant(memory_store=store, registry=registry)
            payload = assistant.run("帮我看 Tushare 是否配好、本地缺哪些表", response_style="raw")
            print(" execution status:", payload["execution"]["status"])
            env_facts = store.load_env_facts()
            print(" merged env_facts:", env_facts)
            self.assertEqual(payload["execution"]["status"], "success")
            self.assertTrue(env_facts["tushare"]["token_present"])
            self.assertEqual(env_facts["tables"]["stock_daily"]["rows"], 42)
            self.assertIn("updated_at", env_facts)


if __name__ == "__main__":
    unittest.main()
