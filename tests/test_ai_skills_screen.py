# coding=utf-8
# ======================================
# File: test_ai_skills_screen.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-27
# Desc:
# Unittest for qteasy-ai stage B screen skill
# ======================================

import unittest

import pandas as pd

from qteasy_ai.skills.research_screen import build_research_screen_skill


class TestAiScreenSkill(unittest.TestCase):
    """测试只读筛股 L2（DI filter + history）。"""

    def test_drawdown_threshold_gold_hits(self) -> None:
        """跌幅>20%：-0.25 命中，-0.10 不命中。"""

        print("\n[TestAiScreenSkill] gold hits")
        pool = pd.DataFrame(
            {"name": ["Alpha", "Beta"], "industry": ["银行", "银行"]},
            index=["000001.SZ", "000002.SZ"],
        )
        idx = pd.date_range("2024-01-01", periods=5, freq="D")
        history = {
            "000001.SZ": pd.DataFrame({"close": [100.0, 90.0, 80.0, 76.0, 75.0]}, index=idx),
            "000002.SZ": pd.DataFrame({"close": [100.0, 95.0, 92.0, 91.0, 90.0]}, index=idx),
        }

        def fake_filter(**kwargs):
            print(" filter kwargs:", kwargs)
            return pool

        def fake_history(**kwargs):
            print(" history kwargs:", {k: kwargs.get(k) for k in ("start", "end", "rows", "shares")})
            return history

        meta, handler = build_research_screen_skill(
            filter_stocks_func=fake_filter,
            history_func=fake_history,
            list_industries_func=lambda: ["银行", "电气设备"],
            latest_end_func=lambda: "20241231",
        )
        result = handler(industry="银行", threshold=0.20, metric="drawdown", lookback_days=126)
        hits = result["payload"]["hits"]
        print(" metrics:", result["metrics"])
        print(" hits:", hits)
        print(" returns gold: 000001.SZ", 75.0 / 100.0 - 1.0, "000002.SZ", 90.0 / 100.0 - 1.0)
        print(" prices gold: start", 100.0, "end", 75.0, "dates", "20240101", "20240105")
        self.assertTrue(result["ok"])
        self.assertFalse(meta.side_effects.network)
        self.assertFalse(meta.side_effects.filesystem_write)
        self.assertEqual(result["metrics"]["hit_count"], 1)
        self.assertEqual(hits[0]["symbol"], "000001.SZ")
        self.assertEqual(hits[0]["name"], "Alpha")
        self.assertAlmostEqual(hits[0]["return"], -0.25, places=10)
        self.assertAlmostEqual(hits[0]["start_price"], 100.0, places=10)
        self.assertAlmostEqual(hits[0]["end_price"], 75.0, places=10)
        self.assertEqual(hits[0]["start_date"], "20240101")
        self.assertEqual(hits[0]["end_date"], "20240105")
        self.assertEqual([item["symbol"] for item in hits], ["000001.SZ"])

    def test_unknown_industry_clarify_with_samples(self) -> None:
        """制造业 0 精确命中 → CLARIFY_REQUIRED 并附行业样例。"""

        print("\n[TestAiScreenSkill] industry miss")
        called_filter = {"n": 0}

        def fake_filter(**kwargs):
            called_filter["n"] += 1
            return pd.DataFrame()

        _, handler = build_research_screen_skill(
            filter_stocks_func=fake_filter,
            history_func=lambda **kwargs: {},
            list_industries_func=lambda: ["银行", "电气设备"],
        )
        result = handler(industry="制造业", threshold=0.20, metric="drawdown")
        print(" result error:", result["error"])
        print(" filter called:", called_filter["n"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CLARIFY_REQUIRED")
        self.assertIn("industry_samples", result["error"]["details"])
        self.assertEqual(result["error"]["details"]["industry_samples"][:2], ["银行", "电气设备"])
        self.assertEqual(called_filter["n"], 0)
        # G6：现样例 = 注入目录切片，非按「制造业」近似推荐；模糊匹配后面再做。

    def test_missing_dates_resolved_before_history(self) -> None:
        """未给 start/end 时必须补齐窗口，禁止把两端空值传给 get_history_data。"""

        print("\n[TestAiScreenSkill] resolve start/end from lookback")
        captured = {}
        pool = pd.DataFrame(
            {"name": ["Alpha"], "industry": ["仓储物流"]},
            index=["000001.SZ"],
        )
        idx = pd.date_range("2024-06-01", periods=5, freq="D")
        history = {"000001.SZ": pd.DataFrame({"close": [100.0, 90.0, 80.0, 70.0, 60.0]}, index=idx)}

        def fake_history(**kwargs):
            captured.update(kwargs)
            return history

        _, handler = build_research_screen_skill(
            filter_stocks_func=lambda **kwargs: pool,
            history_func=fake_history,
            list_industries_func=lambda: ["仓储物流"],
            latest_end_func=lambda: "20240827",
        )
        result = handler(industry="仓储物流", threshold=0.20, metric="drawdown", lookback_days=126)
        expected_start = (pd.Timestamp("20240827") - pd.Timedelta(days=126 * 7 // 5 + 14)).strftime("%Y%m%d")
        print(" ok:", result["ok"])
        print(" history start/end:", captured.get("start"), captured.get("end"))
        print(" expected start:", expected_start)
        print(" echo start/end:", result["inputs_echo"]["start"], result["inputs_echo"]["end"])
        hit = result["payload"]["hits"][0]
        print(" hit_count:", result["metrics"]["hit_count"], "return:", hit["return"])
        print(" hit prices:", hit.get("start_price"), hit.get("end_price"), hit.get("start_date"), hit.get("end_date"))
        self.assertTrue(result["ok"])
        self.assertEqual(captured.get("end"), "20240827")
        self.assertEqual(captured.get("start"), expected_start)
        self.assertIsNone(captured.get("rows"))
        self.assertEqual(result["inputs_echo"]["start"], expected_start)
        self.assertEqual(result["inputs_echo"]["end"], "20240827")
        self.assertEqual(result["metrics"]["hit_count"], 1)
        self.assertAlmostEqual(hit["return"], 60.0 / 100.0 - 1.0, places=10)
        self.assertAlmostEqual(hit["start_price"], 100.0, places=10)
        self.assertAlmostEqual(hit["end_price"], 60.0, places=10)
        self.assertEqual(hit["start_date"], "20240601")
        self.assertEqual(hit["end_date"], "20240605")

    def test_universe_and_project_no_threshold(self) -> None:
        """无阈值：universe 枚举后投影，不要求 threshold。"""

        print("\n[TestAiScreenSkill] universe project")
        from qteasy_ai.skills.research_screen import (
            build_project_universe_skill,
            build_universe_filter_skill,
        )

        pool = pd.DataFrame(
            {"name": ["Alpha", "Beta"], "industry": ["银行", "银行"]},
            index=["000001.SZ", "000002.SZ"],
        )
        _, universe = build_universe_filter_skill(
            filter_stocks_func=lambda **kwargs: pool,
            list_industries_func=lambda: ["银行"],
        )
        uni = universe(industry="银行")
        print(" universe payload:", uni["payload"])
        self.assertTrue(uni["ok"])
        self.assertEqual(uni["metrics"]["universe_size"], 2)
        _, project = build_project_universe_skill()
        projected = project(upstream_payload=uni["payload"])
        print(" projected:", projected["payload"]["hits"], projected["metrics"])
        self.assertTrue(projected["ok"])
        self.assertTrue(projected["metrics"]["enumerated"])
        self.assertEqual(projected["metrics"]["hit_count"], 2)
        self.assertEqual(projected["payload"]["hits"][0]["symbol"], "000001.SZ")


if __name__ == "__main__":
    unittest.main()
