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


def _red_pixel_count(path: str) -> int:
    """统计 PNG 里接近纯红的像素，用来区分上涨蜡烛实体和蓝色折线。"""

    import matplotlib.image as mpimg

    image = mpimg.imread(path)
    arr = np.asarray(image[..., :3], dtype=float)
    if arr.size and float(np.nanmax(arr)) > 1.0:
        arr = arr / 255.0
    red = (arr[..., 0] > 0.75) & (arr[..., 1] < 0.25) & (arr[..., 2] < 0.25)
    count = int(np.count_nonzero(red))
    print(" png:", path, "shape:", image.shape, "red_pixels:", count)
    return count


def _right_axes_margin_frac(path: str) -> float:
    """白轴右缘到图像右缘的比例。默认 subplot 空白约为 0.10。"""

    import matplotlib.image as mpimg

    image = mpimg.imread(path)
    arr = np.asarray(image[..., :3], dtype=float)
    if arr.size and float(np.nanmax(arr)) > 1.0:
        arr = arr / 255.0
    white = (arr[..., 0] > 0.97) & (arr[..., 1] > 0.97) & (arr[..., 2] > 0.97)
    columns = np.where(white.any(axis=0))[0]
    width = int(arr.shape[1])
    frac = 1.0 if len(columns) == 0 else (width - 1 - int(columns.max())) / float(width)
    print(" right margin frac:", frac, "width:", width)
    return frac


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
            candle_red = _red_pixel_count(output_file) if os.path.isfile(output_file) else 0
            right_margin = _right_axes_margin_frac(output_file) if os.path.isfile(output_file) else 1.0
            print(" export skill:", export_meta.name, export_result["artifacts"])
            print(" matplotlib backend:", backend)
            print(" png exists:", os.path.isfile(output_file))
            print(" candle red pixels:", candle_red)
            print(" right axes margin:", right_margin)

            self.assertTrue(export_result["ok"])
            self.assertTrue(export_result["artifacts"][0]["path"].endswith(".png"))
            self.assertTrue(os.path.isfile(output_file))
            self.assertIn("agg", backend.lower())
            self.assertGreater(candle_red, 30)
            self.assertLess(right_margin, 0.06)

            line_file = f"{temp_dir}/close_line.png"
            line_result = export_handler(shares="000300.SH", output_path=line_file, plot_type="line")
            line_red = _red_pixel_count(line_file)
            print(" line export ok:", line_result["ok"], "red pixels:", line_red)
            self.assertTrue(line_result["ok"])
            self.assertLess(line_red, 5)

            close_alias = export_handler(
                shares="000300.SH",
                output_path=f"{temp_dir}/close_alias.png",
                plot_type="close",
            )
            print(" close alias ok:", close_alias["ok"], "plot_type:", close_alias["inputs_echo"]["plot_type"])
            self.assertTrue(close_alias["ok"])

            from qteasy.history import stack_dataframes

            panel = stack_dataframes({"000300.SH": frame.copy()}, dataframe_as="shares")
            _, panel_handler = build_visual_export_skill(get_kline_func=lambda **_: panel)
            panel_file = f"{temp_dir}/panel_kline.png"
            panel_result = panel_handler(shares="000300.SH", output_path=panel_file)
            panel_red = _red_pixel_count(panel_file)
            print(" panel export ok:", panel_result["ok"], "red pixels:", panel_red)
            self.assertTrue(panel_result["ok"])
            self.assertGreater(panel_red, 30)

            thin = frame.drop(columns=["open"])
            _, thin_handler = build_visual_export_skill(get_kline_func=lambda **_: thin.copy())
            thin_result = thin_handler(shares="000300.SH", output_path=f"{temp_dir}/no_open.png")
            print(" missing open:", thin_result["error"])
            self.assertFalse(thin_result["ok"])
            self.assertEqual(thin_result["error"]["code"], "KLINE_EXPORT_FAILED")
            self.assertIn("OHLC", thin_result["error"]["message"])
            self.assertTrue(thin_result["error"]["message"].isascii())

            bad_type = export_handler(shares="000300.SH", output_path=f"{temp_dir}/bad.png", plot_type="renko")
            print(" bad plot_type:", bad_type["error"])
            self.assertFalse(bad_type["ok"])
            self.assertEqual(bad_type["error"]["code"], "KLINE_EXPORT_FAILED")
            self.assertIn("Unsupported plot_type", bad_type["error"]["message"])

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
