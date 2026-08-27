# coding=utf-8
# ======================================
# File: test_ai_skills_refill.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-27
# Desc:
# Unittest for qteasy-ai stage B refill skill
# ======================================

import unittest

from qteasy_ai.skills.data_refill import build_data_refill_skill


class TestAiRefillSkill(unittest.TestCase):
    """测试 refill L1（DI，禁止真联网）。"""

    def test_refill_happy_path_does_not_call_network_when_injected(self) -> None:
        """有 token 时调用注入 refill_func，默认表与依赖表金标准。"""

        print("\n[TestAiRefillSkill] happy path")
        captured = {}

        def fake_refill(**kwargs):
            captured.update(kwargs)
            return None

        meta, handler = build_data_refill_skill(
            refill_func=fake_refill,
            token_getter=lambda: {"token_present": True, "token_source": "env"},
        )
        result = handler(start="20180101", end="20231231")
        print(" ok:", result["ok"])
        print(" metrics:", result["metrics"])
        print(" captured:", captured)
        print(" side_effects:", meta.side_effects)
        self.assertTrue(result["ok"])
        self.assertTrue(meta.side_effects.network)
        self.assertTrue(meta.side_effects.filesystem_write)
        self.assertTrue(meta.side_effects.local_state_change)
        self.assertTrue(meta.side_effects.heavy_compute)
        self.assertEqual(captured["tables"], ["stock_daily", "index_daily"])
        self.assertEqual(captured["start_date"], "20180101")
        self.assertEqual(captured["end_date"], "20231231")
        self.assertTrue(captured["refill_dependent_tables"])
        self.assertEqual(result["metrics"]["start"], "20180101")
        self.assertEqual(result["metrics"]["end"], "20231231")
        self.assertIn("all symbols", result["warnings"][0].lower())

    def test_refill_missing_token_does_not_call_refill(self) -> None:
        """无 token 返回英文错误，不调用 refill_func。"""

        print("\n[TestAiRefillSkill] missing token")
        called = {"n": 0}

        def fake_refill(**kwargs):
            called["n"] += 1

        _, handler = build_data_refill_skill(
            refill_func=fake_refill,
            token_getter=lambda: {"token_present": False, "token_source": "missing"},
        )
        result = handler(start="20180101", end="20231231")
        print(" result:", result)
        print(" refill called:", called["n"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "TUSHARE_TOKEN_MISSING")
        self.assertIn("TUSHARE_TOKEN", result["error"]["message"])
        self.assertIn("QT_CONFIG", result["error"]["message"])
        self.assertEqual(called["n"], 0)

    def test_refill_missing_dates_english_error(self) -> None:
        """缺起止日期不下载。"""

        print("\n[TestAiRefillSkill] missing dates")
        called = {"n": 0}
        _, handler = build_data_refill_skill(
            refill_func=lambda **kwargs: called.__setitem__("n", called["n"] + 1),
            token_getter=lambda: {"token_present": True, "token_source": "env"},
        )
        result = handler(start="", end="")
        print(" result:", result)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "REFILL_DATE_RANGE_REQUIRED")
        self.assertEqual(called["n"], 0)


if __name__ == "__main__":
    unittest.main()
