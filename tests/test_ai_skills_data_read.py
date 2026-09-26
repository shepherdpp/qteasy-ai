# coding=utf-8
# ======================================
# File: test_ai_skills_data_read.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-02
# Desc:
# Unittest for qt.ai.data.read 三入口
# ======================================

import json
import unittest

import pandas as pd

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

    def test_history_preview_rows_have_share_date_and_close(self) -> None:
        """history 的 dict[标的, DataFrame] 收成带列名的预览行，不是类型字符串。"""

        print("\n[TestAiDataReadSkill] history preview rows")
        index = pd.date_range("2024-01-02", periods=2, freq="D")
        index.name = "date"
        frames = {
            "000300.SH": pd.DataFrame({"close": [10.5, float("nan")]}, index=index),
            "000001.SZ": pd.DataFrame({"close": [8.0, 8.5]}, index=index),
        }

        _, handler = build_data_read_skill(
            history_func=lambda **kwargs: frames,
            reference_func=lambda **kwargs: {},
            static_func=lambda **kwargs: {},
        )
        result = handler(channel="history", names="close", shares="000300.SH,000001.SZ")
        rows = result["payload"]["preview_rows"]
        print(" preview_rows:", rows)
        print(" payload json:", json.dumps(result["payload"]))
        self.assertTrue(result["ok"])
        self.assertNotIn("<class", json.dumps(result["payload"]))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["share"], "000300.SH")
        self.assertEqual(rows[0]["close"], 10.5)
        self.assertIn("2024-01-02", str(rows[0]["date"]))
        self.assertIsNone(rows[1]["close"])
        self.assertEqual(rows[2]["share"], "000001.SZ")
        self.assertEqual(rows[2]["close"], 8.0)
        self.assertTrue(all(isinstance(row, dict) for row in rows))

    def test_reference_preview_rows_use_series_names(self) -> None:
        """reference 的 dict[name, Series] 按时间对齐成宽表，一时刻一行。"""

        print("\n[TestAiDataReadSkill] reference preview rows")
        index = pd.date_range("2024-01-01", periods=3, freq="D")
        index.name = "date"
        series = {
            "cn_gdp": pd.Series([1.1, 1.2, 1.3], index=index),
            "cn_cpi": pd.Series([100.0, 101.0, 102.0], index=index),
        }

        _, handler = build_data_read_skill(
            history_func=lambda **kwargs: {},
            reference_func=lambda **kwargs: series,
            static_func=lambda **kwargs: {},
        )
        result = handler(channel="reference", names="cn_gdp,cn_cpi", start="20240101", end="20240131")
        rows = result["payload"]["preview_rows"]
        print(" preview_rows:", rows)
        self.assertTrue(result["ok"])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["cn_gdp"], 1.1)
        self.assertEqual(rows[0]["cn_cpi"], 100.0)
        self.assertEqual(rows[2]["cn_gdp"], 1.3)
        self.assertIn("2024-01-01", str(rows[0]["date"]))
        self.assertFalse(any(isinstance(row, list) for row in rows))

    def test_static_preview_rows_keep_code_and_attribute(self) -> None:
        """static 的 Series / DataFrame 保留代码列与属性列。"""

        print("\n[TestAiDataReadSkill] static preview rows")
        industry = pd.Series(["银行"], index=pd.Index(["000001.SZ"], name="qt_code"), name="industry")
        basics = pd.DataFrame(
            {"industry": ["银行"], "list_date": ["19910403"]},
            index=pd.Index(["000001.SZ"], name="qt_code"),
        )

        def fake_static(**kwargs):
            names = str(kwargs.get("names") or "")
            if "list_date" in names:
                return basics
            return industry

        _, handler = build_data_read_skill(
            history_func=lambda **kwargs: {},
            reference_func=lambda **kwargs: {},
            static_func=fake_static,
        )
        series_result = handler(channel="static", names="industry", shares="000001.SZ")
        frame_result = handler(channel="static", names="industry,list_date", shares="000001.SZ")
        series_rows = series_result["payload"]["preview_rows"]
        frame_rows = frame_result["payload"]["preview_rows"]
        print(" series rows:", series_rows)
        print(" frame rows:", frame_rows)
        self.assertEqual(series_rows, [{"qt_code": "000001.SZ", "industry": "银行"}])
        self.assertEqual(
            frame_rows,
            [{"qt_code": "000001.SZ", "industry": "银行", "list_date": "19910403"}],
        )

    def test_preview_rows_cap_at_fifty(self) -> None:
        """超过 50 行只保留前 50 行，第一行与第 50 行数值可核对。"""

        print("\n[TestAiDataReadSkill] preview row cap")
        index = pd.date_range("2024-01-01", periods=60, freq="D")
        index.name = "date"
        frame = pd.DataFrame({"close": [float(i) for i in range(60)]}, index=index)

        _, handler = build_data_read_skill(
            history_func=lambda **kwargs: {"000300.SH": frame},
            reference_func=lambda **kwargs: {},
            static_func=lambda **kwargs: {},
        )
        result = handler(channel="history", names="close", shares="000300.SH")
        rows = result["payload"]["preview_rows"]
        closes = [row["close"] for row in rows]
        print(" n_rows:", len(rows), "first:", rows[0], "last:", rows[-1])
        self.assertEqual(len(rows), 50)
        self.assertEqual(rows[0]["close"], 0.0)
        self.assertEqual(rows[0]["share"], "000300.SH")
        self.assertEqual(rows[49]["close"], 49.0)
        self.assertNotIn(59.0, closes)


if __name__ == "__main__":
    unittest.main()
