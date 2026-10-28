# coding=utf-8
# ======================================
# File: test_ai_identity.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-12
# Desc:
# 出厂身份 Kairos、用户槽覆盖、确认后写入。
# ======================================

import tempfile
import unittest
from pathlib import Path

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.ask_engine import AskEngine
from qteasy_ai.human_card import polish_human_cards
from qteasy_ai.identity import (
    parse_identity_utterance,
    resolved_identity_prefix,
    write_identity_file,
)
from qteasy_ai.intent_engine import IntentEngine
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner


class _RecordingProvider:
    """记下 system_prompt，并返回调用方给的固定回复。"""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.system_prompt = ""

    def chat(self, prompt: str, *, system_prompt: str = "") -> str:
        del prompt
        self.system_prompt = system_prompt
        return self.reply


class _Hit:
    """Ask 作家用的最小卡片。"""

    def __init__(self) -> None:
        self.id = "what_is_qteasy"
        self.title = "What is qteasy"
        self.narrative = "qteasy is a local quant library."
        self.python_code = "import qteasy"
        self.topics = []


class TestAiIdentity(unittest.TestCase):
    """缺文件、只改名、语气替换、底线句、无关句子。"""

    def test_missing_file_uses_kairos(self) -> None:
        """没有 identity.md 时前缀是 Kairos，并带出厂语气和底线。"""

        print("\n[TestAiIdentity] 缺文件用出厂 Kairos")
        with tempfile.TemporaryDirectory() as temp_dir:
            prefix = resolved_identity_prefix(Path(temp_dir))
            print(" prefix head:", prefix[:80])
            print(" has floor:", "数字由 qteasy 计算" in prefix)
            self.assertIn("你是 Kairos", prefix)
            self.assertIn("该动手的那一刻", prefix)
            self.assertIn("精确但不冷", prefix)
            self.assertIn("数字由 qteasy 计算", prefix)
            self.assertTrue(prefix.rstrip().endswith("用户笔记不改内核语义，不改执行图。"))

    def test_name_only_keeps_default_voice(self) -> None:
        """只写名字时自称换成用户名，八条语气还在。"""

        print("\n[TestAiIdentity] 只改名字")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_identity_file(root, name="阿福", voice="")
            prefix = resolved_identity_prefix(root)
            print(" name line:", [line for line in prefix.splitlines() if line.startswith("你是 ")][:1])
            print(" keeps voice:", "精确但不冷" in prefix)
            print(" drops gloss:", "该动手的那一刻" not in prefix)
            self.assertIn("你是 阿福", prefix)
            self.assertNotIn("该动手的那一刻", prefix)
            self.assertIn("精确但不冷", prefix)
            self.assertIn("数字由 qteasy 计算", prefix)

    def test_voice_replaces_default_and_keeps_floor(self) -> None:
        """语气正文整段替换出厂八条，底线仍在末尾。"""

        print("\n[TestAiIdentity] 语气覆盖")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_identity_file(root, name="", voice="说话短一些，可以开玩笑。")
            prefix = resolved_identity_prefix(root)
            print(" voice in prefix:", "说话短一些，可以开玩笑。" in prefix)
            print(" default voice gone:", "精确但不冷" not in prefix)
            self.assertIn("你是 Kairos", prefix)
            self.assertIn("说话短一些，可以开玩笑。", prefix)
            self.assertNotIn("精确但不冷", prefix)
            self.assertIn("数字由 qteasy 计算", prefix)

    def test_floor_clause_is_dropped_from_file_and_prefix(self) -> None:
        """底线抵触句不进文件，也不进提示。"""

        print("\n[TestAiIdentity] 底线句被丢掉")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = write_identity_file(root, name="阿福", voice="说话短一些。不要确认。")
            stored = path.read_text(encoding="utf-8")
            prefix = resolved_identity_prefix(root)
            print(" stored:", stored)
            print(" floor phrase in prefix:", "不要确认" in prefix)
            self.assertNotIn("不要确认", stored)
            self.assertIn("说话短一些", stored)
            self.assertNotIn("不要确认", prefix)
            self.assertIn("高风险步骤等人确认后再执行", prefix)

    def test_unrelated_sentences_do_not_write(self) -> None:
        """策略名、评价、问身份都不算改名，也不写文件。"""

        print("\n[TestAiIdentity] 无关句子不写文件")
        for text in ("这个策略叫凯", "你很冷", "你是谁", "你直接帮我实盘吧"):
            parsed = parse_identity_utterance(text)
            print(" utterance:", text, "parsed:", parsed)
            self.assertIsNone(parsed)
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            asst = QteasyAssistant(memory_store=store, registry=build_default_registry())
            payload = asst.ask("这个策略叫凯", response_style="raw", session_id="plain")
            path = store.user_kb_dir / "rules" / "identity.md"
            print(" narrative head:", str(payload.get("narrative") or "")[:80])
            print(" identity file exists:", path.exists())
            self.assertFalse(path.exists())
            self.assertNotIn("记下名字", str(payload.get("narrative") or ""))

    def test_rename_waits_for_confirm(self) -> None:
        """明确改名先出确认卡；取消不写，确认后才落盘。"""

        print("\n[TestAiIdentity] 确认后才写入")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            asst = QteasyAssistant(memory_store=store, registry=build_default_registry())
            path = store.user_kb_dir / "rules" / "identity.md"
            pending = asst.ask("以后你叫阿福", response_style="raw", session_id="rename")
            print(" confirm card:", pending.get("narrative"))
            print(" exists before confirm:", path.exists())
            self.assertEqual(pending.get("narrative"), "记下名字：阿福。")
            self.assertFalse(path.exists())
            dismissed = asst.confirm_kb_write("rename", confirm=False, response_style="raw")
            print(" after dismiss exists:", path.exists(), "narrative:", dismissed.get("narrative"))
            self.assertFalse(path.exists())
            with self.assertRaises(ValueError) as caught:
                asst.confirm_kb_write("rename", confirm=True, response_style="raw")
            print(" second confirm:", caught.exception)
            self.assertIn("No pending", str(caught.exception))

            asst.ask("以后你叫阿福", response_style="raw", session_id="rename-ok")
            saved = asst.confirm_kb_write("rename-ok", confirm=True, response_style="raw")
            stored = path.read_text(encoding="utf-8")
            prefix = resolved_identity_prefix(store.user_kb_dir)
            print(" saved card:", saved.get("narrative"))
            print(" file:", stored)
            print(" prefix name:", "你是 阿福" in prefix)
            self.assertIn("name: 阿福", stored)
            self.assertIn("你是 阿福", prefix)
            self.assertIn("精确但不冷", prefix)

    def test_floor_only_request_does_not_create_file(self) -> None:
        """整句只要求越过底线时拒绝，并且没有待确认写入。"""

        print("\n[TestAiIdentity] 只要求不要确认")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            asst = QteasyAssistant(memory_store=store, registry=build_default_registry())
            payload = asst.plan("不要确认", response_style="raw", session_id="floor")
            path = store.user_kb_dir / "rules" / "identity.md"
            print(" refusal:", payload.get("narrative"))
            print(" file exists:", path.exists())
            self.assertEqual(payload.get("narrative"), "高风险步骤仍要你确认。")
            self.assertFalse(path.exists())
            with self.assertRaises(ValueError) as caught:
                asst.confirm_kb_write("floor", confirm=True, response_style="raw")
            print(" confirm error:", caught.exception)
            self.assertIn("No pending", str(caught.exception))

    def test_system_prompts_share_the_prefix(self) -> None:
        """Ask、意图门、Planner、人读卡的系统提示都以前缀开头。"""

        print("\n[TestAiIdentity] 四条系统提示共用前缀")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_identity_file(root, name="阿福", voice="")
            ask_provider = _RecordingProvider("qteasy is local.")
            ask = AskEngine(provider=ask_provider)
            ask.identity_dir = root
            ask._ask_llm(query="什么是 qteasy", hits=[_Hit()])
            print(" ask prompt head:", ask_provider.system_prompt[:40])
            self.assertTrue(ask_provider.system_prompt.startswith("你是 阿福"))
            self.assertIn("You are a qteasy expert", ask_provider.system_prompt)

            intent_provider = _RecordingProvider('{"job": "clarify", "uncertain": true}')
            intent = IntentEngine(provider=intent_provider)
            intent.identity_dir = root
            intent.classify("hello there friend")
            print(" intent prompt head:", intent_provider.system_prompt[:40])
            self.assertTrue(intent_provider.system_prompt.startswith("你是 阿福"))
            self.assertIn("You classify a qteasy-ai user query", intent_provider.system_prompt)

            plan_provider = _RecordingProvider('{"steps": []}')
            planner = Planner(build_default_registry(), provider=plan_provider)
            planner.identity_dir = root
            planner._compose_open_dag("show me a chart")
            print(" planner prompt head:", plan_provider.system_prompt[:40])
            self.assertTrue(plan_provider.system_prompt.startswith("你是 阿福"))
            self.assertIn("You propose a short qteasy-ai ToolPlan", plan_provider.system_prompt)

            card_provider = _RecordingProvider("改写失败也不影响前缀断言")
            polish_human_cards(
                [{"kind": "clarify", "text": "Pick a symbol.", "payload": {}}],
                provider=card_provider,
                query="请用中文",
                identity_dir=root,
            )
            print(" card prompt head:", card_provider.system_prompt[:40])
            self.assertTrue(card_provider.system_prompt.startswith("你是 阿福"))
            self.assertIn("Rewrite this qteasy-ai card", card_provider.system_prompt)


if __name__ == "__main__":
    unittest.main()
