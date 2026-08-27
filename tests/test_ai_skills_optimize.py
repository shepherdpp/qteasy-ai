# coding=utf-8
# ======================================
# File: test_ai_skills_optimize.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-27
# Desc:
# Unittest for qteasy-ai stage B optimize skill
# ======================================

import unittest

from qteasy_ai.skills.optimize_run import build_optimize_run_skill


class TestAiOptimizeSkill(unittest.TestCase):
    """测试内置策略优化 L1。"""

    def test_optimize_default_montecarlo_sample_32(self) -> None:
        """默认 montecarlo sample=32，切片 best_pars/fv 金标准。"""

        print("\n[TestAiOptimizeSkill] defaults and gold fv")
        captured = {}

        def fake_run(op, **kwargs):
            captured.update(kwargs)
            return {"best_pars": [12, 26, 9], "fv": 108000.0, "opti_method": "montecarlo", "opti_sample_count": 32}

        _, handler = build_optimize_run_skill(
            run_func=fake_run,
            operator_factory=lambda sid: type("Op", (), {"strategies": []})(),
            list_func=lambda: ["dma", "macd"],
        )
        result = handler(strategy_id="dma", asset_pool="000300.SH")
        print(" metrics:", result["metrics"])
        print(" captured:", {k: captured[k] for k in ("mode", "opti_method", "opti_sample_count", "visual")})
        self.assertTrue(result["ok"])
        self.assertEqual(captured["mode"], 2)
        self.assertEqual(captured["opti_method"], "montecarlo")
        self.assertEqual(captured["opti_sample_count"], 32)
        self.assertEqual(captured["visual"], False)
        self.assertEqual(result["metrics"]["best_pars"], [12, 26, 9])
        self.assertEqual(result["metrics"]["fv"], 108000.0)
        self.assertEqual(result["metrics"]["opti_method"], "montecarlo")
        self.assertEqual(result["metrics"]["opti_sample_count"], 32)

    def test_optimize_no_adjustable_pars(self) -> None:
        """内核 assert 无可调参 → OPTIMIZE_NO_ADJUSTABLE_PARS。"""

        print("\n[TestAiOptimizeSkill] no adjustable pars")

        def fake_run(op, **kwargs):
            raise AssertionError(
                "ConfigError, none of the strategy parameters is adjustable, set opt_tag to be 1 or 2"
            )

        _, handler = build_optimize_run_skill(
            run_func=fake_run,
            operator_factory=lambda sid: type("Op", (), {"strategies": []})(),
            list_func=lambda: ["dma"],
        )
        result = handler(strategy_id="dma")
        print(" result:", result)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "OPTIMIZE_NO_ADJUSTABLE_PARS")
        self.assertIn("opt_tag", result["error"]["message"])


if __name__ == "__main__":
    unittest.main()
