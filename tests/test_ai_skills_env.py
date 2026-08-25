# coding=utf-8
# ======================================
# File: test_ai_skills_env.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-25
# Desc:
# Unittest for qteasy-ai B0 env guide skills
# ======================================

import unittest

from qteasy_ai.skills.env_guide import (
    build_check_tushare_skill,
    build_overview_tables_skill,
)


class TestAiEnvGuideSkills(unittest.TestCase):
    """测试环境引导 L1 skills（DI，无 Mock）。"""

    def test_check_tushare_token_present_and_missing(self) -> None:
        """token 有/无时 metrics.token_present 金标准。"""

        print("\n[TestAiEnvGuideSkills] check_tushare present/missing")
        present_meta, present_handler = build_check_tushare_skill(
            token_getter=lambda: {"token_present": True, "token_source": "qt_config"}
        )
        missing_meta, missing_handler = build_check_tushare_skill(
            token_getter=lambda: {"token_present": False, "token_source": "missing"}
        )
        present = present_handler()
        missing = missing_handler()
        print(" present metrics:", present["metrics"])
        print(" present error:", present.get("error"))
        print(" missing metrics:", missing["metrics"])
        print(" missing error:", missing.get("error"))

        self.assertEqual(present_meta.skill_kind, "guide")
        self.assertEqual(missing_meta.skill_kind, "guide")
        self.assertTrue(present_meta.required_capabilities)
        self.assertTrue(present_meta.qteasy_entrypoints)
        self.assertTrue(present["ok"])
        self.assertTrue(present["metrics"]["token_present"])
        self.assertEqual(present["metrics"]["token_source"], "qt_config")
        self.assertIsNone(present["error"])

        self.assertTrue(missing["ok"])
        self.assertFalse(missing["metrics"]["token_present"])
        self.assertEqual(missing["metrics"]["token_source"], "missing")
        self.assertIsNotNone(missing["error"])
        self.assertEqual(missing["error"]["code"], "TUSHARE_TOKEN_MISSING")
        self.assertIn("Tushare token", missing["error"]["message"])

    def test_overview_tables_exists_and_missing(self) -> None:
        """表存在/缺失时 exists/rows 金标准。"""

        print("\n[TestAiEnvGuideSkills] overview_tables exists/missing")

        def fake_table_info(name: str) -> dict:
            catalog = {
                "stock_daily": {"exists": True, "rows": 42, "pk_min": "20200101", "pk_max": "20201231"},
                "index_daily": {"exists": False, "rows": 0},
                "trade_calendar": {"exists": True, "rows": 100},
                "stock_basic": {"exists": True, "rows": 5},
            }
            return catalog.get(name, {"exists": False, "rows": 0})

        meta, handler = build_overview_tables_skill(table_info_func=fake_table_info)
        result = handler()
        print(" skill_kind:", meta.skill_kind)
        print(" metrics:", result["metrics"])
        print(" tables:", result["data_summary"]["tables"])
        print(" warnings:", result["warnings"])

        self.assertEqual(meta.skill_kind, "guide")
        self.assertTrue(meta.required_capabilities)
        self.assertTrue(meta.qteasy_entrypoints)
        self.assertTrue(result["ok"])
        tables = result["data_summary"]["tables"]
        self.assertEqual(tables["stock_daily"]["rows"], 42)
        self.assertTrue(tables["stock_daily"]["exists"])
        self.assertFalse(tables["index_daily"]["exists"])
        self.assertEqual(tables["index_daily"]["rows"], 0)
        self.assertEqual(result["metrics"]["missing_count"], 1)
        self.assertEqual(result["metrics"]["missing_tables"], ["index_daily"])
        self.assertIn("index_daily", result["warnings"][0])


if __name__ == "__main__":
    unittest.main()
