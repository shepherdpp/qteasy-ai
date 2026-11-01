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

from qteasy.history import stack_dataframes
from qteasy_ai.skills import (
    build_data_kline_skill,
    build_hp_plot_skill,
    build_strategy_meta_get_skill,
    build_strategy_meta_list_skill,
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

    def test_kline_plot_candle_png(self) -> None:
        """hp.plot 画出上涨蜡烛并裁掉默认灰边。"""

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
        panel = stack_dataframes({"000300.SH": frame.copy()}, dataframe_as="shares")
        plot_meta, plot_handler = build_hp_plot_skill()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = f"{temp_dir}/kline.png"
            plot_result = plot_handler(
                output_path=output_file,
                upstream_payload={"panel": panel},
            )
            import matplotlib

            backend = str(matplotlib.get_backend() or "")
            candle_red = _red_pixel_count(output_file) if os.path.isfile(output_file) else 0
            right_margin = _right_axes_margin_frac(output_file) if os.path.isfile(output_file) else 1.0
            print("\n[TestAiReadonlySkills] plot skill:", plot_meta.name, plot_result["artifacts"])
            print(" matplotlib backend:", backend)
            print(" png exists:", os.path.isfile(output_file))
            print(" candle red pixels:", candle_red)
            print(" right axes margin:", right_margin)
            print(" page_count:", plot_result["metrics"].get("page_count"))

            self.assertTrue(plot_result["ok"])
            self.assertEqual(plot_result["metrics"]["page_count"], 1)
            self.assertTrue(plot_result["artifacts"][0]["path"].endswith(".png"))
            self.assertTrue(os.path.isfile(output_file))
            self.assertIn("agg", backend.lower())
            self.assertGreater(candle_red, 30)
            self.assertLess(right_margin, 0.06)

    def test_data_kline_empty_data_english_error(self) -> None:
        """空 K 线失败且 error.message 为英文。"""

        print("\n[TestAiReadonlySkills] empty kline error")
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "vol"])
        _, handler = build_data_kline_skill(get_kline_func=lambda **_: empty.copy())
        result = handler(shares="000300.SH")
        print(" result:", result["error"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "KLINE_FETCH_FAILED")
        self.assertTrue(result["error"]["message"].isascii())
        self.assertNotIn("Traceback", result["error"]["message"])


if __name__ == "__main__":
    unittest.main()
