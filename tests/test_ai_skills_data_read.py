# coding=utf-8
# ======================================
# File: test_ai_skills_data_read.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-02
# Desc:
# Unittest for qt.ai.data.read 三入口
# ======================================

import unittest

from qteasy_ai.skills.data_read import build_data_read_skill


class TestAiDataReadSkill(unittest.TestCase):
    """三入口只读取数。"""

    def test_history_channel_ok(self) -> None:
        """history 通道调用 get_history_data。"""

        print("\n[TestAiDataReadSkill] history")
        called = {}

        def fake_history(**kwargs):
            called.update(kwargs)
            return {"000300.SH": [1, 2, 3]}

        _, handler = build_data_read_skill(
            history_func=fake_history,
            reference_func=lambda **kwargs: {},
            static_func=lambda **kwargs: {},
        )
        result = handler(channel="history", names="close", shares="000300.SH", start="20240101", end="20240131")
        print(" ok:", result["ok"], "metrics:", result["metrics"], "called:", called)
        self.assertTrue(result["ok"])
        self.assertEqual(result["metrics"]["channel"], "history")
        self.assertEqual(result["metrics"]["n_items"], 1)
        self.assertEqual(called.get("shares"), "000300.SH")

    def test_static_channel_ok(self) -> None:
        """static 通道调用 get_static_data。"""

        print("\n[TestAiDataReadSkill] static")
        called = {}

        def fake_static(**kwargs):
            called.update(kwargs)
            return {"000001.SZ": {"industry": "银行"}}

        _, handler = build_data_read_skill(
            history_func=lambda **kwargs: {},
            reference_func=lambda **kwargs: {},
            static_func=fake_static,
        )
        result = handler(channel="static", names="industry", shares="000001.SZ")
        print(" ok:", result["ok"], "metrics:", result["metrics"], "called:", called)
        self.assertTrue(result["ok"])
        self.assertEqual(result["metrics"]["channel"], "static")
        self.assertEqual(called.get("shares"), "000001.SZ")

    def test_wrong_shape_english_error(self) -> None:
        """错形状英文错误指向另一入口。"""

        print("\n[TestAiDataReadSkill] wrong shape")

        def boom(**kwargs):
            raise ValueError("industry is static; use qt.get_static_data(...) instead of qt.get_history_data(...).")

        _, handler = build_data_read_skill(
            history_func=boom,
            reference_func=lambda **kwargs: {},
            static_func=lambda **kwargs: {},
        )
        result = handler(channel="history", names="industry", shares="000001.SZ")
        print(" error:", result["error"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "DATA_READ_FAILED")
        self.assertIn("get_static_data", result["error"]["message"])


if __name__ == "__main__":
    unittest.main()
