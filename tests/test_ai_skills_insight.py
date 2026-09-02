# coding=utf-8
# ======================================
# File: test_ai_skills_insight.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-27
# Desc:
# Unittest for qteasy-ai stage B insight skill
# ======================================

import unittest

from qteasy_ai.skills.insight_backtest import build_insight_backtest_skill


class TestAiInsightSkill(unittest.TestCase):
    """测试 L3 回测归因摘要。"""

    def test_summarize_upstream_metrics_gold(self) -> None:
        """上游回测 metrics 金标准切片到 insight。"""

        print("\n[TestAiInsightSkill] upstream gold")
        meta, handler = build_insight_backtest_skill(
            load_run_func=lambda _rid: {},
            list_run_payloads_func=lambda: [],
        )
        result = handler(
            upstream_metrics={
                "final_value": 112000.0,
                "annual_rtn": 0.12,
                "mdd": 0.25,
                "peak_date": "2020-01-15",
                "valley_date": "2020-03-23",
                "recover_date": "2020-11-01",
            }
        )
        print(" skill_kind:", meta.skill_kind)
        print(" metrics:", result["metrics"])
        print(" payload:", result["payload"])
        self.assertEqual(meta.skill_kind, "insight")
        self.assertTrue(result["ok"])
        self.assertEqual(result["metrics"]["annual_rtn"], 0.12)
        self.assertEqual(result["metrics"]["mdd"], 0.25)
        self.assertEqual(result["payload"]["drawdown"]["peak_date"], "2020-01-15")
        self.assertEqual(result["payload"]["drawdown"]["valley_date"], "2020-03-23")
        self.assertIn("strategy_meta", result["payload"]["change_hint"])

    def test_no_backtest_english_error(self) -> None:
        """无产物时英文错误并提示先跑回测。"""

        print("\n[TestAiInsightSkill] missing backtest")
        _, handler = build_insight_backtest_skill(
            load_run_func=lambda _rid: {},
            list_run_payloads_func=lambda: [],
        )
        result = handler()
        print(" result:", result)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INSIGHT_NO_BACKTEST")
        self.assertIn("backtest", result["error"]["message"].lower())

    def test_nearby_trades_skips_nat_anchor(self) -> None:
        """NaT 锚点不得拿去 str.contains，应退回 head 摘要。"""

        print("\n[TestAiInsightSkill] NaT nearby_trades")
        import tempfile
        from pathlib import Path

        import pandas as pd

        from qteasy_ai.skills.insight_backtest import _trade_summary_from_log

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trade_log.csv"
            frame = pd.DataFrame({"date": ["20200115", "20200323"], "qty": [1, 2]})
            frame.to_csv(path, index=False)
            rows = _trade_summary_from_log(str(path), peak_date="NaT", valley_date="NaT")
            print(" rows:", rows)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["qty"], 1)


if __name__ == "__main__":
    unittest.main()
