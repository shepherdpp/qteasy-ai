# coding=utf-8
# ======================================
# File: test_ai_skills_research.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-25
# Desc:
# Unittest for qteasy-ai B0 research IC skill
# ======================================

import unittest
from functools import partial

import numpy as np

from qteasy.history import HistoryPanel
from qteasy.research import factor_ic, factor_ic_summary
from qteasy_ai.app import build_default_registry
from qteasy_ai.planner import Planner
from qteasy_ai.skills.research_factor_ic import (
    build_factor_ic_summary_skill,
    local_history_panel_builder,
)


def _make_panel() -> HistoryPanel:
    """与 qteasy test_research 同构：3 shares × 2 dates。"""

    values = np.array(
        [
            [[1.0, 2.0], [3.0, 1.0]],
            [[2.0, 4.0], [2.0, 2.0]],
            [[3.0, 6.0], [1.0, 3.0]],
        ],
        dtype=float,
    )
    return HistoryPanel(
        values=values,
        levels=["s1", "s2", "s3"],
        rows=["2023-01-01", "2023-01-02"],
        columns=["factor", "ret"],
    )


class TestAiResearchFactorIcSkill(unittest.TestCase):
    """测试因子 IC 摘要技能。"""

    def test_factor_ic_summary_gold_values(self) -> None:
        """metrics mean/ir/win_rate 与 factor_ic_summary 金标准一致。"""

        print("\n[TestAiResearchFactorIcSkill] gold values")
        panel = _make_panel()
        meta, handler = build_factor_ic_summary_skill(panel_builder=lambda **_: panel)
        result = handler(factor_htype="factor", return_htype="ret", method="pearson")
        ic = factor_ic(panel, "factor", "ret", method="pearson")
        summary = factor_ic_summary(ic)
        print(" result metrics:", result["metrics"])
        print(" expected summary:\n", summary)

        self.assertTrue(result["ok"])
        self.assertEqual(meta.name, "qt.ai.research.factor_ic_summary")
        self.assertAlmostEqual(result["metrics"]["mean"], float(summary.loc["mean"]), places=10)
        self.assertAlmostEqual(result["metrics"]["std"], float(summary.loc["std"]), places=10)
        self.assertAlmostEqual(result["metrics"]["ir"], float(summary.loc["ir"]), places=10)
        self.assertAlmostEqual(result["metrics"]["win_rate"], float(summary.loc["win_rate"]), places=10)
        self.assertEqual(result["metrics"]["n_periods"], 2)
        # pearson: +1 and -1 → mean 0, win_rate 0.5
        self.assertAlmostEqual(result["metrics"]["mean"], 0.0, places=10)
        self.assertAlmostEqual(result["metrics"]["win_rate"], 0.5, places=10)

    def test_factor_ic_unknown_column_english_error(self) -> None:
        """缺列时返回英文错误。"""

        print("\n[TestAiResearchFactorIcSkill] unknown column")
        panel = _make_panel()
        _, handler = build_factor_ic_summary_skill(panel_builder=lambda **_: panel)
        result = handler(factor_htype="nope", return_htype="ret")
        print(" result:", result)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "FACTOR_IC_SUMMARY_FAILED")
        self.assertIn("Failed to compute factor IC summary", result["error"]["message"])
        self.assertIn("nope", result["error"]["message"])

    def test_registered_skill_missing_pool_actionable_english(self) -> None:
        """手册原句无标的/日期时，注册技能返回可行动英文错误，不提注入。"""

        print("\n[TestAiResearchFactorIcSkill] registered skill, handbook query has no pool")
        query = "factor IC summary for selection pool"
        market = Planner._extract_market_inputs(query)
        registry = build_default_registry()
        result = registry.call("qt.ai.research.factor_ic_summary", **market)
        message = result["error"]["message"]
        print(" market inputs:", market)
        print(" error:", result["error"])

        self.assertNotIn("shares", market)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "FACTOR_IC_SUMMARY_FAILED")
        self.assertIn("at least two symbols", message)
        self.assertIn("date range", message)
        self.assertNotIn("panel_builder", message)
        self.assertNotIn("skill injection", message)

    def test_local_builder_gold_when_history_injected(self) -> None:
        """注入行情返回合成面板时，请求列与 IC 金标准一致。"""

        print("\n[TestAiResearchFactorIcSkill] local builder gold")
        panel = _make_panel()
        seen: dict = {}

        def fetch(**kwargs):
            seen.update(kwargs)
            return panel

        builder = partial(local_history_panel_builder, get_history_data=fetch)
        _, handler = build_factor_ic_summary_skill(panel_builder=builder)
        result = handler(
            factor_htype="factor",
            return_htype="ret",
            method="pearson",
            shares="s1,s2,s3",
            start="20230101",
            end="20230102",
        )
        ic = factor_ic(panel, "factor", "ret", method="pearson")
        summary = factor_ic_summary(ic)
        print(" requested:", {key: seen.get(key) for key in ("htype_names", "shares", "start", "end")})
        print(" result metrics:", result["metrics"])
        print(" expected summary:\n", summary)

        self.assertEqual(list(seen["htype_names"]), ["factor", "ret"])
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["metrics"]["mean"], float(summary.loc["mean"]), places=10)
        self.assertAlmostEqual(result["metrics"]["std"], float(summary.loc["std"]), places=10)
        self.assertAlmostEqual(result["metrics"]["ir"], float(summary.loc["ir"]), places=10)
        self.assertAlmostEqual(result["metrics"]["win_rate"], float(summary.loc["win_rate"]), places=10)
        self.assertAlmostEqual(result["metrics"]["mean"], 0.0, places=10)
        self.assertAlmostEqual(result["metrics"]["win_rate"], 0.5, places=10)

    def test_local_builder_empty_data_refill_english(self) -> None:
        """本地面板为空时提示 refill，不提注入。"""

        print("\n[TestAiResearchFactorIcSkill] empty local panel")

        def fetch(**kwargs):
            return HistoryPanel()

        builder = partial(local_history_panel_builder, get_history_data=fetch)
        _, handler = build_factor_ic_summary_skill(panel_builder=builder)
        result = handler(
            factor_htype="close",
            return_htype="pct_chg",
            shares="000001.SZ,000002.SZ",
            start="20240101",
            end="20240131",
        )
        message = result["error"]["message"]
        print(" error:", result["error"])

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "FACTOR_IC_SUMMARY_FAILED")
        self.assertIn("Refill", message)
        self.assertNotIn("panel_builder", message)
        self.assertNotIn("skill injection", message)


if __name__ == "__main__":
    unittest.main()
