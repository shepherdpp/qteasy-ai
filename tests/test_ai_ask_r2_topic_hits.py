# coding=utf-8
# ======================================
# File: test_ai_ask_r2_topic_hits.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-26
# Desc:
# R2：overview/strategy scope、固定问句表、点卡一问多卡提示
# ======================================

import json
import unittest
from pathlib import Path

from qteasy_ai.ask_engine import AskEngine, _CARD_SYSTEM_PROMPT
from qteasy_ai.knowledge_base import KnowledgeBase
from qteasy_ai.provider import FakeLLMProvider

_REPO = Path(__file__).resolve().parents[1]
_KB_DIR = _REPO / "qteasy_ai" / "kb"
_REGISTRY_PATH = _KB_DIR / "_source" / "topic_registry.json"

# 固定问句表：无模型金句 + 有模型替身。期望 id 是独立金标准。
_HIT_TABLE = (
    ("什么是 PT", "pt_ps_vs", ["strategy"], "PT/PS/VS"),
    ("qteasy 如何防止未来函数", "qteasy_advantages", ["overview"], "未来函数"),
)


class TestAiAskR2TopicHits(unittest.TestCase):
    """R2 主题 scope、固定问句命中与点卡多卡条款。"""

    def test_overview_and_strategy_scope_strings(self) -> None:
        """overview 含未来函数，strategy 含 PT/PS/VS。"""

        print("\n[TestAiAskR2TopicHits] scope 字符串")
        registry = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        topics = {row["id"]: row for row in registry["topics"]}
        overview_scope = str(topics["overview"].get("scope") or "")
        strategy_scope = str(topics["strategy"].get("scope") or "")
        print(" overview.scope:", overview_scope)
        print(" strategy.scope:", strategy_scope)
        self.assertIn("未来函数", overview_scope)
        self.assertIn("PT/PS/VS", strategy_scope)

    def test_card_system_prompt_multi_matter_clause(self) -> None:
        """点卡 system 写明一问多卡，且勿整句 uncertain 吞有卡侧。"""

        print("\n[TestAiAskR2TopicHits] 点卡 system 一问多卡")
        print(" card system:", _CARD_SYSTEM_PROMPT)
        lowered = _CARD_SYSTEM_PROMPT.lower()
        self.assertIn("one question covers multiple matters", lowered)
        self.assertIn("uncertain", lowered)
        self.assertIn("still select", lowered)

    def test_offline_hit_table_sources(self) -> None:
        """无 Provider 时固定问句 sources 含期望 id，无 plan_id。"""

        print("\n[TestAiAskR2TopicHits] 无模型固定问句")
        engine = AskEngine(knowledge_base=KnowledgeBase())
        self.assertIsNone(engine.provider)
        for question, expect_id, _topics, _scope_hint in _HIT_TABLE:
            payload = engine.ask(question).to_dict()
            print(" question:", question)
            print(" sources:", payload.get("sources"))
            print(" expected contains:", expect_id)
            print(" ok:", payload.get("ok"), "mode:", payload.get("mode"))
            self.assertTrue(payload["ok"], msg=question)
            self.assertEqual(payload["mode"], "ask")
            self.assertIn(expect_id, payload.get("sources") or [])
            self.assertNotIn("plan_id", payload)
            self.assertNotIn("execution", payload)

    def test_provider_stub_hit_table_and_prompts(self) -> None:
        """替身三连：sources 含期望 id；定主题含 scope；点卡 system 含多卡条款。"""

        print("\n[TestAiAskR2TopicHits] 替身固定问句")
        kb = KnowledgeBase()
        for question, expect_id, topics, scope_hint in _HIT_TABLE:
            fake = FakeLLMProvider(
                replies=[
                    json.dumps({"topics": topics}, ensure_ascii=False),
                    json.dumps({"ids": [expect_id]}, ensure_ascii=False),
                    f"Grounded answer for {expect_id}.",
                ]
            )
            engine = AskEngine(knowledge_base=kb, provider=fake)
            payload = engine.ask(question).to_dict()
            print(" question:", question)
            print(" sources:", payload.get("sources"))
            print(" topic prompt snippet:", fake.prompts[0][:200])
            print(" card system:", fake.system_prompts[1])
            self.assertTrue(payload["ok"], msg=question)
            self.assertIn(expect_id, payload.get("sources") or [])
            self.assertIn(scope_hint, fake.prompts[0])
            self.assertNotIn("plan_id", payload)
            card_system = fake.system_prompts[1].lower()
            self.assertIn("one question covers multiple matters", card_system)
            self.assertIn("uncertain", card_system)


if __name__ == "__main__":
    unittest.main()
