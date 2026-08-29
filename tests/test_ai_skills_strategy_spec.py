# coding=utf-8
# ======================================
# File: test_ai_skills_strategy_spec.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-29
# Desc:
# Unittest for qt.ai.strategy.spec_from_nl
# ======================================

import unittest

from qteasy_ai.contracts import StrategySpec
from qteasy_ai.skills.strategy_spec import build_strategy_spec_from_nl_skill


class TestAiStrategySpecSkill(unittest.TestCase):
    """测试 NL→StrategySpec 金句、澄清与矛盾路径。"""

    def setUp(self) -> None:
        self.meta, self.handler = build_strategy_spec_from_nl_skill()

    def test_golden_sma_cross_spec_fields(self) -> None:
        """20/60 日均线金叉死叉 → 稳定 Spec，不编造标的池。"""

        print("\n[TestAiStrategySpecSkill] golden 20/60 SMA cross")
        query = "20/60 日均线金叉死叉"
        result = self.handler(query=query)
        spec_raw = result.get("payload", {}).get("spec") or {}
        spec = StrategySpec.from_dict(spec_raw)
        print(" ok:", result["ok"])
        print(" spec:", spec.to_dict())
        print(" metrics:", result.get("metrics"))
        self.assertTrue(result["ok"])
        self.assertEqual(self.meta.name, "qt.ai.strategy.spec_from_nl")
        self.assertFalse(self.meta.side_effects.filesystem_write)
        self.assertEqual(spec.template_id, "rule_iterator.sma_cross")
        self.assertEqual(spec.signal_type, "PS")
        self.assertEqual(spec.run_freq, "d")
        self.assertEqual(spec.run_timing, "close")
        names = [item["name"] for item in spec.parameters]
        self.assertEqual(names, ["fast", "slow"])
        self.assertEqual(spec.parameters[0]["default"], 20)
        self.assertEqual(spec.parameters[1]["default"], 60)
        self.assertEqual(result["metrics"]["fast"], 20)
        self.assertEqual(result["metrics"]["slow"], 60)
        self.assertEqual(spec.asset_pool, "")
        self.assertNotEqual(spec.asset_pool, "000300.SH")
        self.assertIn("close", spec.htypes)
        self.assertGreaterEqual(spec.window_length, 60)
        self.assertFalse(spec.use_latest_data_cycle)
        self.assertEqual(spec.risk_decl.get("cost"), "declare_only")
        self.assertTrue(spec.assumptions)

    def test_missing_ma_periods_clarify_does_not_invent_pool(self) -> None:
        """未说快慢线 → clarify，不编造 asset_pool。"""

        print("\n[TestAiStrategySpecSkill] missing fast/slow")
        query = "帮我写一个均线金叉择时策略"
        result = self.handler(query=query)
        payload = result.get("payload") or {}
        print(" ok:", result["ok"])
        print(" payload:", payload)
        print(" error:", result.get("error"))
        self.assertFalse(result["ok"])
        self.assertTrue(payload.get("clarify_required"))
        self.assertEqual(result["error"]["code"], "CLARIFY_REQUIRED")
        missing = str(payload.get("missing_info") or result["error"]["details"].get("missing_info"))
        self.assertIn("fast", missing)
        self.assertIn("slow", missing)
        self.assertNotIn("asset_pool", payload.get("spec") or {})
        self.assertNotEqual((payload.get("spec") or {}).get("asset_pool"), "000300.SH")

    def test_pt_vs_conflict_does_not_silently_pick(self) -> None:
        """同时要 PT 全仓又要 VS 股数 → 澄清，不静默选一种。"""

        print("\n[TestAiStrategySpecSkill] PT vs VS conflict")
        query = "用 PT 目标仓位同时按 VS 股数下单的 20/60 日均线金叉策略"
        result = self.handler(query=query)
        payload = result.get("payload") or {}
        spec = payload.get("spec")
        print(" ok:", result["ok"])
        print(" payload:", payload)
        print(" error:", result.get("error"))
        self.assertFalse(result["ok"])
        self.assertTrue(payload.get("clarify_required"))
        self.assertEqual(result["error"]["code"], "CLARIFY_REQUIRED")
        self.assertIn("signal_type", str(payload.get("missing_info") or ""))
        self.assertIsNone(spec)
        self.assertNotEqual(payload.get("chosen_signal_type"), "PT")
        self.assertNotEqual(payload.get("chosen_signal_type"), "VS")


if __name__ == "__main__":
    unittest.main()
