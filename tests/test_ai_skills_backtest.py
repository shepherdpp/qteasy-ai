# coding=utf-8
# ======================================
# File: test_ai_skills_backtest.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-27
# Desc:
# Unittest for qteasy-ai stage B backtest skill
# ======================================

import unittest

from qteasy_ai.skills.backtest_run import build_backtest_run_skill


class TestAiBacktestSkill(unittest.TestCase):
    """测试内置策略回测 L1（DI run_func）。"""

    def test_backtest_metrics_gold_values(self) -> None:
        """注入金标准 final_value/annual_rtn/mdd，禁止只比两路相等。"""

        print("\n[TestAiBacktestSkill] gold metrics")
        captured = {}

        def fake_run(op, **kwargs):
            captured["op"] = op
            captured.update(kwargs)
            return {
                "final_value": 112000.0,
                "annual_rtn": 0.12,
                "mdd": 0.25,
                "peak_date": "2020-01-15",
                "valley_date": "2020-03-23",
                "recover_date": "2020-11-01",
                "complete_values": "MUST_NOT_APPEAR",
                "trade_log_file": "/tmp/trade_log_demo.csv",
            }

        def fake_operator(sid, run_freq="d"):
            captured["run_freq"] = run_freq
            return {"id": sid}

        meta, handler = build_backtest_run_skill(
            run_func=fake_run,
            operator_factory=fake_operator,
            list_func=lambda: ["macd", "dma"],
        )
        result = handler(
            strategy_id="macd",
            asset_pool="000300.SH",
            invest_start="20180101",
            invest_end="20231231",
            freq="d",
        )
        print(" metrics:", result["metrics"])
        print(" artifacts:", result["artifacts"])
        print(" run kwargs keys:", sorted(k for k in captured if k != "op"))
        print(" operator run_freq:", captured.get("run_freq"))
        self.assertTrue(result["ok"])
        self.assertTrue(meta.side_effects.filesystem_write)
        self.assertEqual(result["metrics"]["final_value"], 112000.0)
        self.assertEqual(result["metrics"]["annual_rtn"], 0.12)
        self.assertEqual(result["metrics"]["mdd"], 0.25)
        self.assertEqual(result["metrics"]["peak_date"], "2020-01-15")
        self.assertEqual(result["metrics"]["valley_date"], "2020-03-23")
        self.assertEqual(result["metrics"]["recover_date"], "2020-11-01")
        self.assertNotIn("complete_values", result["metrics"])
        self.assertEqual(result["artifacts"][0]["kind"], "trade_log")
        self.assertEqual(captured.get("visual"), False)
        self.assertEqual(captured.get("report"), False)
        self.assertEqual(captured.get("trade_log"), True)
        self.assertEqual(captured.get("mode"), 1)
        self.assertNotIn("freq", captured)
        self.assertEqual(captured.get("run_freq"), "d")

    def test_unknown_strategy_does_not_call_run(self) -> None:
        """未知策略 ID 英文错误，不调用 run_func。"""

        print("\n[TestAiBacktestSkill] unknown strategy")
        called = {"n": 0}
        _, handler = build_backtest_run_skill(
            run_func=lambda *a, **k: called.__setitem__("n", called["n"] + 1),
            operator_factory=lambda sid: None,
            list_func=lambda: ["macd"],
        )
        result = handler(strategy_id="not_a_real_strategy")
        print(" result:", result)
        print(" run called:", called["n"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "UNKNOWN_STRATEGY_ID")
        self.assertIn("not_a_real_strategy", result["error"]["message"])
        self.assertEqual(called["n"], 0)

    def test_run_kwargs_exclude_freq_config_key(self) -> None:
        """qt.run 不得接收 freq：该键不是 QT_CONFIG 内置参数。"""

        print("\n[TestAiBacktestSkill] freq is Operator.run_freq, not qt.run config")
        captured = {}

        def fake_run(op, **kwargs):
            captured["kwargs"] = dict(kwargs)
            return {"final_value": 1.0, "annual_rtn": 0.01, "mdd": 0.02}

        def fake_operator(sid, run_freq="d"):
            captured["sid"] = sid
            captured["run_freq"] = run_freq
            return {"id": sid}

        _, handler = build_backtest_run_skill(
            run_func=fake_run,
            operator_factory=fake_operator,
            list_func=lambda: ["macd"],
        )
        result = handler(strategy_id="macd", freq="w")
        print(" ok:", result["ok"])
        print(" run kwargs:", captured.get("kwargs"))
        print(" operator run_freq:", captured.get("run_freq"))
        self.assertTrue(result["ok"])
        self.assertNotIn("freq", captured["kwargs"])
        self.assertEqual(captured["run_freq"], "w")
        self.assertEqual(result["metrics"]["final_value"], 1.0)
        self.assertEqual(result["metrics"]["annual_rtn"], 0.01)
        self.assertEqual(result["metrics"]["mdd"], 0.02)


    def test_strategy_path_skips_builtin_list(self) -> None:
        """有 strategy_path 时加载自定义类，不查 built_in_list。"""

        print("\n[TestAiBacktestSkill] strategy_path custom")
        captured = {}
        listed = {"n": 0}

        def fake_run(op, **kwargs):
            captured["op"] = op
            captured["kwargs"] = dict(kwargs)
            return {"final_value": 99.0, "annual_rtn": 0.05, "mdd": 0.1}

        def fake_operator(stg, run_freq="d", **kwargs):
            captured["stg"] = stg
            captured["run_freq"] = run_freq
            captured["factory_kwargs"] = dict(kwargs)
            return {"custom": True, "stg": stg}

        def fake_load(path):
            captured["loaded_path"] = path
            return "CUSTOM_CLASS"

        def list_func():
            listed["n"] += 1
            return ["macd"]

        _, handler = build_backtest_run_skill(
            run_func=fake_run,
            operator_factory=fake_operator,
            list_func=list_func,
            load_func=fake_load,
        )
        result = handler(
            strategy_id="GeneratedSmaCross",
            strategy_path="/tmp/GeneratedSmaCross.py",
            freq="d",
            asset_pool="000300.SH",
            invest_start="20150101",
            invest_end="20201231",
        )
        print(" ok:", result["ok"])
        print(" metrics:", result["metrics"])
        print(" listed:", listed["n"])
        print(" loaded:", captured.get("loaded_path"))
        print(" stg:", captured.get("stg"))
        print(" run kwargs:", captured.get("kwargs"))
        self.assertTrue(result["ok"])
        self.assertEqual(listed["n"], 0)
        self.assertEqual(captured.get("loaded_path"), "/tmp/GeneratedSmaCross.py")
        self.assertEqual(captured.get("stg"), "CUSTOM_CLASS")
        self.assertEqual(captured.get("run_freq"), "d")
        self.assertNotIn("freq", captured.get("kwargs") or {})
        self.assertEqual(result["metrics"]["final_value"], 99.0)
        self.assertEqual(result["metrics"]["annual_rtn"], 0.05)
        self.assertEqual(result["metrics"]["mdd"], 0.1)


if __name__ == "__main__":
    unittest.main()
