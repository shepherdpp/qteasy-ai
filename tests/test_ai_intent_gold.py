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
    """gold 表：query → job / flags；lock 行 FakeLLM 不可否决。"""

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

    def test_locked_gold_not_vetoed_by_fake_llm(self) -> None:
        """lock 金句 + FakeLLM 错误 Job 仍为表内 Job。"""

        catalog = load_default_catalog()
        locked = [item for item in catalog.gold_cases() if item.get("lock")]
        print("\n[TestAiIntentGold] locked:", len(locked))
        self.assertGreaterEqual(len(locked), 8)
        for case in locked:
            fake = FakeLLMProvider(
                replies=[
                    json.dumps({"job": "open"}),
                    json.dumps({"job": "hack.shell"}),
                ]
            )
            engine = IntentEngine(catalog=catalog, provider=fake)
            decision = engine.classify(str(case["query"]))
            print(
                " lock id:",
                case.get("id"),
                "job:",
                decision.job,
                "llm_called:",
                decision.llm_called,
                "prompts:",
                len(fake.prompts),
            )
            self.assertEqual(decision.job, case["job"])
            self.assertEqual(decision.source, "rule")
            self.assertFalse(decision.llm_called)
            self.assertEqual(fake.prompts, [])

    def test_normalize_maps_en_dash(self) -> None:
        """en-dash 与 hyphen 金句归一。"""

        print("\n[TestAiIntentGold] normalize dash")
        left = normalize_query_text("2018–2023")
        right = normalize_query_text("2018-2023")
        print(" left:", left, "right:", right)
        self.assertEqual(left, right)


if __name__ == "__main__":
    unittest.main()
