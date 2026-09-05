# coding=utf-8
# ======================================
# File: test_ai_intent_h_prime.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-05
# Desc:
# Unittest for IntentEngine 方案 H′ 鲁棒语料
# ======================================

import json
import unittest
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from qteasy_ai.intent_engine import IntentEngine
from qteasy_ai.intents import load_default_catalog
from qteasy_ai.provider import FakeLLMProvider

_CORPUS = Path(__file__).resolve().parent / "ai_corpus" / "e8_h_prime_robustness.json"


def _load_cases() -> List[Dict[str, Any]]:
    """读取 H′ 鲁棒语料。"""

    with _CORPUS.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return list(payload.get("cases") or [])


def _fake_reply_text(reply: Any) -> str:
    """把语料 fake_reply 编成 Provider 文本。"""

    if isinstance(reply, (dict, list)):
        return json.dumps(reply, ensure_ascii=False)
    return str(reply)


class TestAiIntentHPrime(unittest.TestCase):
    """表驱动：宪法 / Mode-R / Mode-D 协议与改写。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_default_catalog()
        cls.cases = _load_cases()
        cls.family_counts: Counter = Counter()

    def test_h_prime_robustness_corpus(self) -> None:
        """每条语料的 job / source / rationale 符合表内期望。"""

        print("\n[TestAiIntentHPrime] cases:", len(self.cases))
        self.assertGreaterEqual(len(self.cases), 45)
        self.assertLessEqual(len(self.cases), 80)
        for case in self.cases:
            case_id = str(case.get("id") or "")
            family = str(case.get("family") or "")
            query = str(case.get("query") or "")
            mode = str(case.get("mode") or "")
            expected_job = str(case.get("expected_job") or "")
            expected_source = str(case.get("expected_source") or "")
            needle = str(case.get("expected_rationale_contains") or "")
            if mode == "D":
                self.assertIn("fake_reply", case, msg=f"{case_id} Mode-D missing fake_reply")
                self.assertTrue(expected_source, msg=f"{case_id} Mode-D missing expected_source")
                fake = FakeLLMProvider(replies=[_fake_reply_text(case.get("fake_reply"))])
                engine = IntentEngine(catalog=self.catalog, provider=fake)
            else:
                engine = IntentEngine(catalog=self.catalog, provider=None)
            decision = engine.classify(query)
            print(
                " id:",
                case_id,
                "family:",
                family,
                "mode:",
                mode,
                "query:",
                query[:48],
                "expected:",
                expected_job,
                expected_source,
                "actual:",
                decision.job,
                decision.source,
                "rationale:",
                decision.rationale,
            )
            self.assertEqual(decision.job, expected_job, msg=case_id)
            if expected_source:
                self.assertEqual(decision.source, expected_source, msg=case_id)
            if needle:
                self.assertIn(needle, decision.rationale, msg=case_id)
            self.family_counts[family] += 1
        print("\n[TestAiIntentHPrime] family counts:", dict(self.family_counts))
        for family in (
            "const_unsafe",
            "const_unsupported",
            "const_multi_risk",
            "const_live",
            "r_gold",
            "r_zero",
            "r_multi",
            "d_protocol",
            "d_paraphrase",
            "d_multi_intent",
        ):
            print(" family:", family, "n:", self.family_counts[family])
            self.assertGreater(self.family_counts[family], 0, msg=family)


if __name__ == "__main__":
    unittest.main()
