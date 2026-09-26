# coding=utf-8
# ======================================
# File: test_ai_skills_readonly.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-15
# Desc:
# Unittest for qteasy ai readonly skills
# ======================================

import os
import tempfile
import unittest

import numpy as np
import pandas as pd

from qteasy_ai.skills import (
    build_data_summary_skill,
    build_strategy_meta_get_skill,
    build_strategy_meta_list_skill,
    build_visual_export_skill,
)


class TestAiReadonlySkills(unittest.TestCase):
    """测试阶段A只读技能输出契约。"""

    def test_strategy_meta_skills(self) -> None:
        """验证策略列表和详情技能。"""

        class DummyStrategy:
            pass

        list_meta, list_handler = build_strategy_meta_list_skill(list_func=lambda: ["macd", "dma"])
        get_meta, get_handler = build_strategy_meta_get_skill(
            doc_func=lambda sid: f"{sid} docs",
            get_func=lambda sid: DummyStrategy(),
        )
        list_result = list_handler()
        get_result = get_handler(strategy_id="macd")

        print("\n[TestAiReadonlySkills] list skill:", list_meta.name, list_result)
        print(" get skill:", get_meta.name, get_result)

        self.assertTrue(list_result["ok"])
        self.assertEqual(list_result["metrics"]["count"], 2)
        self.assertTrue(get_result["ok"])
        self.assertEqual(get_result["payload"]["strategy_id"], "macd")

    def test_data_summary_and_export_skills(self) -> None:
        """验证数据摘要与图像导出技能。"""

        date_index = pd.date_range("2024-01-01", periods=8, freq="D")
        date_index.name = "date"
        frame = pd.DataFrame(
            {
                "open": [1, 2, 3, 4, 5, 6, 7, 8],
                "high": [2, 3, 4, 5, 6, 7, 8, 9],
                "low": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5],
                "close": [1.2, 2.2, 3.1, 3.8, 5.0, 5.2, 5.4, 6.0],
                "vol": [10, 11, 12, 13, 14, 15, 16, 17],
            },
            index=date_index,
        )

        summary_meta, summary_handler = build_data_summary_skill(get_kline_func=lambda **_: frame.copy())
        summary_result = summary_handler(shares="000300.SH", freq="d")

        close = frame["close"].astype(float)
        simple_rets = close.pct_change().dropna()
        exp_vol_daily = float(simple_rets.std(ddof=1))
        exp_vol_annual = exp_vol_daily * float(np.sqrt(252.0))
        rows = summary_result["payload"]["preview_rows"]
        print("\n[TestAiReadonlySkills] summary skill:", summary_meta.name)
        print(" metrics:", summary_result["metrics"])
        print(" preview_rows:", rows)
        print(" expected vol_daily/annual:", exp_vol_daily, exp_vol_annual)

        self.assertTrue(summary_result["ok"])
        self.assertEqual(summary_result["metrics"]["n_rows"], 8)
        self.assertEqual(summary_result["metrics"]["n_trading_days"], 8)
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0]["close"], 1.2)
        self.assertEqual(rows[7]["close"], 6.0)
        self.assertIn("2024-01-01", str(rows[0]["date"]))
        self.assertIn("2024-01-08", str(rows[7]["date"]))
        self.assertTrue(all(isinstance(row, dict) and "close" in row for row in rows))
        self.assertFalse(any(isinstance(row, list) for row in rows))
        self.assertAlmostEqual(summary_result["metrics"]["volatility_daily"], exp_vol_daily, places=10)
        self.assertAlmostEqual(
            summary_result["metrics"]["volatility_annualized"], exp_vol_annual, places=10
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = f"{temp_dir}/kline.png"
            export_meta, export_handler = build_visual_export_skill(get_kline_func=lambda **_: frame.copy())
            export_result = export_handler(shares="000300.SH", output_path=output_file)
            import matplotlib

            backend = str(matplotlib.get_backend() or "")
            print(" export skill:", export_meta.name, export_result["artifacts"])
            print(" matplotlib backend:", backend)
            print(" png exists:", os.path.isfile(output_file))

            self.assertTrue(export_result["ok"])
            self.assertTrue(export_result["artifacts"][0]["path"].endswith(".png"))
            self.assertTrue(os.path.isfile(output_file))
            self.assertIn("agg", backend.lower())

    def test_data_summary_empty_data_english_error(self) -> None:
        """空数据失败且 error.message 为英文。"""

        print("\n[TestAiReadonlySkills] empty data error")
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "vol"])
        _, handler = build_data_summary_skill(get_kline_func=lambda **_: empty.copy())
        result = handler(shares="000300.SH")
        print(" result:", result)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "KLINE_SUMMARY_FAILED")
        self.assertIn("Failed to summarize", result["error"]["message"])


if __name__ == "__main__":
    unittest.main()
