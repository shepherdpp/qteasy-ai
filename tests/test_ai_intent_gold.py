# coding=utf-8
# ======================================
# File: test_ai_intent_gold.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-02
# Desc:
# Catalog gold.json 表驱动分类测试
# ======================================

import json
import unittest

from qteasy_ai.intent_engine import IntentEngine, normalize_query_text
from qteasy_ai.intents import load_default_catalog
from qteasy_ai.provider import FakeLLMProvider


class TestAiIntentGold(unittest.TestCase):
    """gold 表：Mode-R query → job / flags；lock 仅无 Provider。"""

    def test_gold_table_matches_catalog(self) -> None:
        """每条 gold 分类结果等于表内 job/flags。"""

        catalog = load_default_catalog()
        engine = IntentEngine(catalog=catalog, provider=None)
        cases = catalog.gold_cases()
        print("\n[TestAiIntentGold] cases:", len(cases))
        self.assertGreaterEqual(len(cases), 10)
        for case in cases:
            query = str(case["query"])
            expected_job = str(case["job"])
            expected_flags = dict(case.get("flags") or {})
            decision = engine.classify(query)
            print(
                " id:",
                case.get("id"),
                "query:",
                query[:60],
                "job:",
                decision.job,
                "expected:",
                expected_job,
                "source:",
                decision.source,
                "flags:",
                decision.flags,
            )
            self.assertEqual(decision.job, expected_job)
            for key, value in expected_flags.items():
                self.assertEqual(decision.flags.get(key), value)
            if case.get("lock"):
                self.assertEqual(decision.source, "rule")

    def test_locked_gold_mode_r_locks_mode_d_calls_llm(self) -> None:
        """lock 金句：无 Provider 仍锁；有 FakeLLM 会调用 LLM。"""

        catalog = load_default_catalog()
        locked = [item for item in catalog.gold_cases() if item.get("lock")]
        engine_r = IntentEngine(catalog=catalog, provider=None)
        print("\n[TestAiIntentGold] locked:", len(locked))
        self.assertGreaterEqual(len(locked), 8)
        for case in locked:
            query = str(case["query"])
            decision_r = engine_r.classify(query)
            print(
                " mode-r id:",
                case.get("id"),
                "job:",
                decision_r.job,
                "source:",
                decision_r.source,
                "rationale:",
                decision_r.rationale,
            )
            self.assertEqual(decision_r.job, case["job"])
            self.assertEqual(decision_r.source, "rule")
            self.assertFalse(decision_r.llm_called)

            fake = FakeLLMProvider(replies=[json.dumps({"job": "open"})])
            engine_d = IntentEngine(catalog=catalog, provider=fake)
            decision_d = engine_d.classify(query)
            print(
                " mode-d id:",
                case.get("id"),
                "job:",
                decision_d.job,
                "source:",
                decision_d.source,
                "llm_called:",
                decision_d.llm_called,
                "prompts:",
                len(fake.prompts),
            )
            constitution_hold = decision_r.job in {"unsafe", "not_supported", "live.plan_only"} or (
                decision_r.rationale == "multi_high_risk_intent"
            )
            if constitution_hold:
                self.assertEqual(decision_d.job, decision_r.job)
                self.assertEqual(decision_d.source, "rule")
                self.assertFalse(decision_d.llm_called)
                self.assertEqual(fake.prompts, [])
            else:
                self.assertEqual(decision_d.job, "open")
                self.assertEqual(decision_d.source, "llm")
                self.assertTrue(decision_d.llm_called)
                self.assertTrue(fake.prompts)

    def test_normalize_maps_en_dash(self) -> None:
        """en-dash 与 hyphen 金句归一。"""

        print("\n[TestAiIntentGold] normalize dash")
        left = normalize_query_text("2018–2023")
        right = normalize_query_text("2018-2023")
        print(" left:", left, "right:", right)
        self.assertEqual(left, right)


if __name__ == "__main__":
    unittest.main()
