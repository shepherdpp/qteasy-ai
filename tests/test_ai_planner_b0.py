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
from qteasy_ai.skills.env_guide import build_check_tushare_skill, build_overview_tables_skill


class TestAiPlannerB0(unittest.TestCase):
    """测试 B0 规则多步路由与 env_facts 门禁。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_env_query_two_step_plan(self) -> None:
        """环境检查问法产出 check_tushare + overview_tables。"""

        print("\n[TestAiPlannerB0] env query two-step")
        planner = Planner(self.registry, env_facts={})
        plan = planner.build_plan("帮我看 Tushare 是否配好、本地缺哪些表", mode="plan")
        skill_names = [step.skill_name for step in plan.steps]
        print(" skills:", skill_names)
        self.assertEqual(set(skill_names), {"qt.ai.env.check_tushare", "qt.ai.env.overview_tables"})
        self.assertEqual(len(plan.steps), 2)
        for step in plan.steps:
            self.assertEqual(step.depends_on, [])

    def test_kline_summary_routes_to_summary_not_export(self) -> None:
        """kline summary 优先路由到 summary_kline（修误路由）。"""

        print("\n[TestAiPlannerB0] kline summary routing")
        planner = Planner(self.registry, env_facts={})
        plan = planner.build_plan("kline summary of 000300.SH", mode="plan")
        skill_names = [step.skill_name for step in plan.steps]
        print(" skills:", skill_names)
        self.assertEqual(skill_names, ["qt.ai.data.summary_kline"])
        self.assertEqual(plan.steps[0].inputs.get("shares"), "000300.SH")

    def test_empty_env_facts_summary_single_step(self) -> None:
        """空 env_facts 时 summary 问法仍单步（不破坏语料）。"""

        print("\n[TestAiPlannerB0] empty env_facts single summary")
        planner = Planner(self.registry, env_facts={})
        plan = planner.build_plan("show summary of 000300.SH from 20240101 to 20241231", mode="plan")
        skill_names = [step.skill_name for step in plan.steps]
        print(" skills:", skill_names)
        self.assertEqual(skill_names, ["qt.ai.data.summary_kline"])

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
        self.assertEqual(plan.steps[-1].skill_name, "qt.ai.data.summary_kline")

    def test_run_merges_env_facts_after_guide_execute(self) -> None:
        """execute 成功后 Assistant 将 guide 探针 merge 进 env_facts。"""

        print("\n[TestAiPlannerB0] merge env_facts after execute")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            registry = build_default_registry()
            # 覆盖默认 env skills 为 DI 探针，避免真实 QT_CONFIG/DataSource
            for name in ["qt.ai.env.check_tushare", "qt.ai.env.overview_tables"]:
                registry._meta.pop(name, None)
                registry._impl.pop(name, None)
            meta_t, handler_t = build_check_tushare_skill(
                token_getter=lambda: {"token_present": True, "token_source": "qt_config"}
            )
            meta_o, handler_o = build_overview_tables_skill(
                table_info_func=lambda name: {
                    "stock_daily": {"exists": True, "rows": 42},
                    "index_daily": {"exists": True, "rows": 10},
                    "trade_calendar": {"exists": True, "rows": 100},
                    "stock_basic": {"exists": True, "rows": 5},
                }.get(name, {"exists": False, "rows": 0})
            )
            registry.register(meta_t, handler_t)
            registry.register(meta_o, handler_o)

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
