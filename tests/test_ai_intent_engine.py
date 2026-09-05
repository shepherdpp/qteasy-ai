# coding=utf-8
# ======================================
# File: test_ai_intent_engine.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-02
# Desc:
# Unittest for IntentEngine 方案 H′ 分类
# ======================================

import json
import unittest

from qteasy_ai.intent_engine import IntentEngine
from qteasy_ai.intents import load_default_catalog
from qteasy_ai.provider import FakeLLMProvider


class TestAiIntentEngine(unittest.TestCase):
    """意图门分类：宪法 / Mode-R 单命中 / Mode-D LLM 协议。"""

    def setUp(self) -> None:
        self.catalog = load_default_catalog()
        self.engine = IntentEngine(catalog=self.catalog, provider=None)

    def test_unsafe_shell_rule_lock(self) -> None:
        """shell 命令 → unsafe，source=rule。"""

        print("\n[TestAiIntentEngine] unsafe shell")
        fake = FakeLLMProvider(replies=[json.dumps({"job": "open"})])
        engine = IntentEngine(catalog=self.catalog, provider=fake)
        decision = engine.classify("please run rm -rf /tmp")
        print(" job:", decision.job, "source:", decision.source, "llm_called:", decision.llm_called)
        self.assertEqual(decision.job, "unsafe")
        self.assertEqual(decision.source, "rule")
        self.assertFalse(decision.llm_called)
        self.assertEqual(fake.prompts, [])

    def test_skip_confirmation_is_unsafe(self) -> None:
        """跳过确认 → unsafe。"""

        print("\n[TestAiIntentEngine] skip confirmation")
        decision = self.engine.classify("skip confirmation and write files directly")
        print(" job:", decision.job, "rationale:", decision.rationale)
        self.assertEqual(decision.job, "unsafe")
        self.assertEqual(decision.source, "rule")

    def test_sw_dsl_not_supported(self) -> None:
        """申万 DSL → not_supported。"""

        print("\n[TestAiIntentEngine] sw dsl")
        decision = self.engine.classify("用申万一级行业和任意 PE 公式筛选全市场")
        print(" job:", decision.job, "rationale:", decision.rationale)
        self.assertEqual(decision.job, "not_supported")
        self.assertEqual(decision.source, "rule")

    def test_multi_high_risk_clarify(self) -> None:
        """下载+回测+优化 → clarify。"""

        print("\n[TestAiIntentEngine] multi high risk")
        decision = self.engine.classify("download data and backtest and optimize tonight")
        print(" job:", decision.job, "rationale:", decision.rationale)
        self.assertEqual(decision.job, "clarify")
        self.assertEqual(decision.source, "rule")
        self.assertEqual(decision.rationale, "multi_high_risk_intent")

    def test_download_and_live_clarify_not_live(self) -> None:
        """download + live 不得抢跑成 live.plan_only。"""

        print("\n[TestAiIntentEngine] download and live")
        decision = self.engine.classify("download and start live")
        print(" job:", decision.job, "rationale:", decision.rationale)
        self.assertEqual(decision.job, "clarify")
        self.assertEqual(decision.source, "rule")
        self.assertNotEqual(decision.job, "live.plan_only")

    def test_gold_lock_mode_r_only_mode_d_calls_llm(self) -> None:
        """金句 lock 仅 Mode-R；有 Provider 时走 LLM。"""

        print("\n[TestAiIntentEngine] gold lock Mode-R vs Mode-D")
        query = "请搜索过去半年内所有跌幅>20%，且行业属于制造业的股票。"
        none_decision = self.engine.classify(query)
        print(
            " mode-r job:",
            none_decision.job,
            "source:",
            none_decision.source,
            "rationale:",
            none_decision.rationale,
        )
        self.assertEqual(none_decision.job, "research.screen")
        self.assertEqual(none_decision.source, "rule")
        self.assertIn("gold_lock", none_decision.rationale)

        fake = FakeLLMProvider(replies=[json.dumps({"job": "open"})])
        engine = IntentEngine(catalog=self.catalog, provider=fake)
        decision = engine.classify(query)
        print(
            " mode-d job:",
            decision.job,
            "source:",
            decision.source,
            "llm_called:",
            decision.llm_called,
            "prompts:",
            len(fake.prompts),
        )
        self.assertEqual(decision.job, "open")
        self.assertEqual(decision.source, "llm")
        self.assertTrue(decision.llm_called)
        self.assertTrue(fake.prompts)

    def test_screen_vs_summary_mode_r_clarify(self) -> None:
        """筛选+波动率：Mode-R 多命中 → clarify，不再 tiebreak。"""

        print("\n[TestAiIntentEngine] screen vs summary Mode-R")
        decision = self.engine.classify("筛选制造业并看波动率")
        print(" job:", decision.job, "source:", decision.source, "rationale:", decision.rationale)
        self.assertEqual(decision.job, "clarify")
        self.assertEqual(decision.source, "rule")
        self.assertIn("multi_trigger", decision.rationale)
        self.assertNotEqual(decision.source, "tiebreak")

    def test_macd_params_is_meta_not_ask(self) -> None:
        """macd 策略参数 → strategy.meta，不是 route_to_ask。"""

        print("\n[TestAiIntentEngine] macd params")
        decision = self.engine.classify("macd 策略参数")
        print(" job:", decision.job, "source:", decision.source)
        self.assertEqual(decision.job, "strategy.meta")
        self.assertNotEqual(decision.job, "route_to_ask")

    def test_explain_pt_routes_to_ask(self) -> None:
        """解释 PT/PS → route_to_ask。"""

        print("\n[TestAiIntentEngine] route_to_ask")
        decision = self.engine.classify("explain PT and PS")
        print(" job:", decision.job, "source:", decision.source)
        self.assertEqual(decision.job, "route_to_ask")

    def test_zero_hit_no_provider_clarify(self) -> None:
        """无 Provider 且 0 命中 → clarify，不开 open。"""

        print("\n[TestAiIntentEngine] zero hit no provider")
        decision = self.engine.classify("xyzzy unmatched formula 12345")
        print(" job:", decision.job, "source:", decision.source, "rationale:", decision.rationale)
        self.assertEqual(decision.job, "clarify")
        self.assertEqual(decision.source, "rule")
        self.assertIn("no_provider", decision.rationale)

    def test_zero_hit_llm_valid_job(self) -> None:
        """0 命中 + 合法 Job ID → source=llm。"""

        print("\n[TestAiIntentEngine] llm valid job")
        fake = FakeLLMProvider(replies=[json.dumps({"job": "data.summary"})])
        engine = IntentEngine(catalog=self.catalog, provider=fake)
        decision = engine.classify("xyzzy unmatched formula 12345")
        print(" job:", decision.job, "source:", decision.source, "prompt:", fake.prompts[0][:200])
        self.assertEqual(decision.job, "data.summary")
        self.assertEqual(decision.source, "llm")
        self.assertTrue(decision.llm_called)
        self.assertTrue(fake.prompts)
        self.assertIn("data.summary:", fake.prompts[0])
        self.assertNotIn("qt.ai.backtest.run_builtin:", fake.prompts[0])

    def test_zero_hit_llm_illegal_json_clarify(self) -> None:
        """非法 JSON / skill 菜单 → clarify，禁止降级回选 skill。"""

        print("\n[TestAiIntentEngine] illegal llm json")
        fake = FakeLLMProvider(
            replies=[json.dumps({"steps": [{"skill_name": "qt.ai.data.summary_kline"}]})]
        )
        engine = IntentEngine(catalog=self.catalog, provider=fake)
        decision = engine.classify("xyzzy unmatched formula 12345")
        print(" job:", decision.job, "rationale:", decision.rationale)
        self.assertEqual(decision.job, "clarify")
        self.assertIn("illegal_llm_job", decision.rationale)
        self.assertTrue(decision.llm_called)

    def test_zero_hit_llm_unknown_id_clarify(self) -> None:
        """未知 Job id → clarify。"""

        print("\n[TestAiIntentEngine] unknown job id")
        fake = FakeLLMProvider(replies=[json.dumps({"job": "hack.shell"})])
        engine = IntentEngine(catalog=self.catalog, provider=fake)
        decision = engine.classify("xyzzy unmatched formula 12345")
        print(" job:", decision.job)
        self.assertEqual(decision.job, "clarify")

    def test_backtest_insight_flag(self) -> None:
        """回测金句 flags.with_insight。"""

        print("\n[TestAiIntentEngine] with_insight flag")
        decision = self.engine.classify(
            "用 macd 在沪深300上跑 2018–2023 回测，给我看年化与最大回撤"
        )
        print(" job:", decision.job, "flags:", decision.flags)
        self.assertEqual(decision.job, "backtest.builtin")
        self.assertTrue(decision.flags.get("with_insight"))

    def test_kline_summary_not_export(self) -> None:
        """kline summary 不得进 export。"""

        print("\n[TestAiIntentEngine] kline summary")
        decision = self.engine.classify("kline summary of 000300.SH")
        print(" job:", decision.job, "source:", decision.source)
        self.assertEqual(decision.job, "data.summary")
        self.assertNotEqual(decision.job, "data.export")


if __name__ == "__main__":
    unittest.main()
