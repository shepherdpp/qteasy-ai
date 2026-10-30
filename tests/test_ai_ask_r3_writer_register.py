# coding=utf-8
# ======================================
# File: test_ai_ask_r3_writer_register.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-26
# Desc:
# R3：Ask 作家规矩 + 语域布尔双轨（heuristic 词表 / LLM 定主题 JSON）
# ======================================

import json
import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant
from qteasy_ai.ask_engine import (
    AskEngine,
    _ASK_SYSTEM_PROMPT,
    _PLAIN_LANGUAGE_WRITER_CLAUSE,
    _TOPIC_SYSTEM_PROMPT,
    query_requests_plain_language,
)
from qteasy_ai.knowledge_base import KnowledgeBase
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.provider import FakeLLMProvider


class TestAiAskR3WriterRegister(unittest.TestCase):
    """R3 作家规矩与 ask_plain_language 双轨判定。"""

    def test_writer_system_has_four_standing_rules(self) -> None:
        """作家 system 恒含通识 / 卡内定义 / 自我定位 / 切 Plan 四类锚点。"""

        print("\n[TestAiAskR3WriterRegister] 作家四条规矩常量")
        print(" writer system:", _ASK_SYSTEM_PROMPT)
        lowered = _ASK_SYSTEM_PROMPT.lower()
        self.assertIn("general principle", lowered)
        self.assertIn("not a handbook", lowered)
        self.assertIn("user-level definition", lowered)
        self.assertIn("provided snippets", lowered)
        self.assertIn("do not imply the concept was already answered", lowered)
        self.assertIn("switch to plan only for actionable", lowered)
        self.assertIn("assistant.preview", lowered)
        self.assertIn("do not know where the web buttons", lowered)
        self.assertIn("先人话", _PLAIN_LANGUAGE_WRITER_CLAUSE)
        self.assertIn("标识符后置", _PLAIN_LANGUAGE_WRITER_CLAUSE)
        self.assertNotIn("先人话", _ASK_SYSTEM_PROMPT)

    def test_topic_system_mentions_plain_language_field(self) -> None:
        """定主题 system 说明 plain_language 字段，词表仅参考。"""

        print("\n[TestAiAskR3WriterRegister] 定主题 system 语域字段")
        print(" topic system:", _TOPIC_SYSTEM_PROMPT)
        lowered = _TOPIC_SYSTEM_PROMPT.lower()
        self.assertIn("plain_language", lowered)
        self.assertIn("reference", lowered)
        self.assertIn("not the only", lowered)

    def test_heuristic_wordlist_latches_without_provider(self) -> None:
        """无 Provider + 词表信号句 → session.ask_plain_language 为 True。"""

        print("\n[TestAiAskR3WriterRegister] heuristic 词表粘住")
        self.assertTrue(query_requests_plain_language("说人话讲讲回测是什么"))
        self.assertFalse(query_requests_plain_language("如何用qteasy回测"))
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(memory_store=MemoryStore(base_dir=temp_dir))
            self.assertIsNone(assistant.ask_engine.provider)
            payload = assistant.ask(
                "说人话讲讲回测是什么",
                response_style="raw",
                session_id="r3-heur",
            )
            state = assistant.session_store.load("r3-heur")
            print(" ok:", payload.get("ok"))
            print(" raw.ask_plain_language:", (payload.get("raw") or {}).get("ask_plain_language"))
            print(" session.ask_plain_language:", state.ask_plain_language)
            self.assertTrue((payload.get("raw") or {}).get("ask_plain_language"))
            self.assertTrue(state.ask_plain_language)

    def test_provider_json_latches_without_wordlist(self) -> None:
        """有 Provider：定主题 JSON plain_language true（问句无词表）→ 粘住且作家含语域条款。"""

        print("\n[TestAiAskR3WriterRegister] LLM JSON 置位本轮作家")
        query = "请把回测讲得通俗一些"
        self.assertFalse(query_requests_plain_language(query))
        fake = FakeLLMProvider(
            replies=[
                json.dumps(
                    {"topics": ["backtest"], "plain_language": True},
                    ensure_ascii=False,
                ),
                json.dumps({"ids": ["backtest_intro"]}, ensure_ascii=False),
                "通俗回测说明。",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                provider=fake,
            )
            payload = assistant.ask(query, response_style="raw", session_id="r3-llm")
            state = assistant.session_store.load("r3-llm")
            writer_system = fake.system_prompts[2]
            print(" sources:", payload.get("sources"))
            print(" session flag:", state.ask_plain_language)
            print(" writer system has clause:", _PLAIN_LANGUAGE_WRITER_CLAUSE in writer_system)
            self.assertTrue(payload.get("ok"))
            self.assertEqual(payload.get("sources"), ["backtest_intro"])
            self.assertTrue(state.ask_plain_language)
            self.assertTrue((payload.get("raw") or {}).get("ask_plain_language"))
            self.assertIn(_PLAIN_LANGUAGE_WRITER_CLAUSE, writer_system)
            self.assertIn("先人话", writer_system)
            self.assertIn("标识符后置", writer_system)
            for needle in (
                "general principle",
                "user-level definition",
                "do not imply the concept was already answered",
                "Switch to Plan only for actionable",
            ):
                self.assertIn(needle.lower(), writer_system.lower())

    def test_latched_flag_keeps_writer_clause_next_turn(self) -> None:
        """下一轮无再声明：定主题省略或 false，布尔仍 True，作家仍含语域条款。"""

        print("\n[TestAiAskR3WriterRegister] 跨轮粘住语域条款")
        fake = FakeLLMProvider(
            replies=[
                json.dumps(
                    {"topics": ["backtest"], "plain_language": True},
                    ensure_ascii=False,
                ),
                json.dumps({"ids": ["backtest_intro"]}, ensure_ascii=False),
                "第一轮。",
                json.dumps(
                    {"topics": ["backtest"], "plain_language": False},
                    ensure_ascii=False,
                ),
                json.dumps({"ids": ["backtest_intro"]}, ensure_ascii=False),
                "第二轮。",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                provider=fake,
            )
            first = assistant.ask(
                "请把回测讲得通俗一些",
                response_style="raw",
                session_id="r3-latch",
            )
            state_after_first = assistant.session_store.load("r3-latch")
            print(" after first flag:", state_after_first.ask_plain_language)
            self.assertTrue(state_after_first.ask_plain_language)
            self.assertTrue((first.get("raw") or {}).get("ask_plain_language"))
            second = assistant.ask(
                "如何用qteasy回测",
                response_style="raw",
                session_id="r3-latch",
            )
            state = assistant.session_store.load("r3-latch")
            writer_system = fake.system_prompts[5]
            print(" second raw.ask_plain_language:", (second.get("raw") or {}).get("ask_plain_language"))
            print(" session flag:", state.ask_plain_language)
            print(" second writer has clause:", _PLAIN_LANGUAGE_WRITER_CLAUSE in writer_system)
            self.assertTrue(state.ask_plain_language)
            self.assertFalse((second.get("raw") or {}).get("ask_plain_language"))
            self.assertIn(_PLAIN_LANGUAGE_WRITER_CLAUSE, writer_system)

    def test_provider_wordlist_hit_does_not_override_llm_false(self) -> None:
        """有 Provider：词表命中但 JSON plain_language false 且先前未粘 → 不强制置 True。"""

        print("\n[TestAiAskR3WriterRegister] LLM false 不以词表齐平")
        query = "说人话讲讲回测"
        self.assertTrue(query_requests_plain_language(query))
        fake = FakeLLMProvider(
            replies=[
                json.dumps(
                    {"topics": ["backtest"], "plain_language": False},
                    ensure_ascii=False,
                ),
                json.dumps({"ids": ["backtest_intro"]}, ensure_ascii=False),
                "术语版。",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                provider=fake,
            )
            payload = assistant.ask(query, response_style="raw", session_id="r3-no-or")
            state = assistant.session_store.load("r3-no-or")
            writer_system = fake.system_prompts[2]
            print(" session flag:", state.ask_plain_language)
            print(" raw turn:", (payload.get("raw") or {}).get("ask_plain_language"))
            print(" writer has clause:", _PLAIN_LANGUAGE_WRITER_CLAUSE in writer_system)
            self.assertFalse(state.ask_plain_language)
            self.assertFalse((payload.get("raw") or {}).get("ask_plain_language"))
            self.assertNotIn(_PLAIN_LANGUAGE_WRITER_CLAUSE, writer_system)

    def test_default_session_writer_omits_plain_clause(self) -> None:
        """无信号且默认 session → 作家 system 不含语域条款。"""

        print("\n[TestAiAskR3WriterRegister] 默认不含语域条款")
        fake = FakeLLMProvider(
            replies=[
                json.dumps({"topics": ["backtest"]}, ensure_ascii=False),
                json.dumps({"ids": ["backtest_intro"]}, ensure_ascii=False),
                "普通说明。",
            ]
        )
        engine = AskEngine(knowledge_base=KnowledgeBase(), provider=fake)
        payload = engine.ask("如何用qteasy回测").to_dict()
        writer_system = fake.system_prompts[2]
        print(" raw.ask_plain_language:", (payload.get("raw") or {}).get("ask_plain_language"))
        print(" writer system snippet:", writer_system[-120:])
        self.assertTrue(payload.get("ok"))
        self.assertFalse((payload.get("raw") or {}).get("ask_plain_language"))
        self.assertNotIn(_PLAIN_LANGUAGE_WRITER_CLAUSE, writer_system)
        self.assertIn("general principle", writer_system.lower())


if __name__ == "__main__":
    unittest.main()
