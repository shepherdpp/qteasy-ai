# coding=utf-8
# ======================================
# File: test_ai_user_kb_consume.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-10
# Desc:
# Unittest for G.7 user KB compile/consume/write
# ======================================

import json
import tempfile
import unittest
from pathlib import Path

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.knowledge_base import KnowledgeBase
from qteasy_ai.memory_store import MemoryStore


class TestAiUserKbConsume(unittest.TestCase):
    """compile 索引真消费；确认后写 raw；Ask 零用户库。"""

    def test_compile_index_without_design_loop(self) -> None:
        """raw 一篇因子笔记 → compile 非空；探索句不再挂设计环 kb_hits。"""

        print("\n[TestAiUserKbConsume] compile without design loop")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            note = store.user_kb_dir / "raw" / "factors" / "momentum.md"
            note.write_text("# momentum\n\nA user note about momentum on hs300.\n", encoding="utf-8")
            catalog = store.compile_user_kb()
            print(" catalog entries:", catalog.get("entries"))
            self.assertTrue(catalog.get("entries"))
            self.assertEqual(catalog["entries"][0]["path"], "raw/factors/momentum.md")
            asst = QteasyAssistant(memory_store=store, registry=build_default_registry())
            payload = asst.plan(
                "explore a useful momentum factor for hs300",
                response_style="raw",
                session_id="g7-kb",
            )
            assumptions = (payload.get("plan") or {}).get("assumptions") or {}
            hits = assumptions.get("kb_hits") or payload.get("kb_hits") or []
            print(" kb_hits:", hits)
            print(" design_loop:", assumptions.get("design_loop"))
            print(" dumped keys:", sorted(asst.session_store.load("g7-kb").to_dict().keys()))
            self.assertFalse(hits)
            self.assertFalse(assumptions.get("design_loop"))
            self.assertNotIn("active_design", asst.session_store.load("g7-kb").to_dict())

    def test_unconfirmed_write_does_not_touch_disk(self) -> None:
        """无待确认草案：confirm_kb_write 失败且不写盘；显式 write_confirmed_note 才落 raw。"""

        print("\n[TestAiUserKbConsume] confirm write")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            asst = QteasyAssistant(memory_store=store, registry=build_default_registry())
            sid = "g7-write"
            target = store.user_kb_dir / "raw" / "factors" / "momentum.md"
            print(" exists before:", target.exists())
            self.assertFalse(target.exists())
            with self.assertRaises(ValueError) as denied:
                asst.confirm_kb_write(sid, confirm=False, response_style="raw")
            print(" deny:", denied.exception)
            self.assertIn("confirmation", str(denied.exception).lower())
            print(" exists after reject:", target.exists())
            self.assertFalse(target.exists())
            with self.assertRaises(ValueError) as pending:
                asst.confirm_kb_write(sid, confirm=True, response_style="raw")
            print(" pending:", pending.exception)
            self.assertIn("No pending", str(pending.exception))
            self.assertFalse(target.exists())
            from qteasy_ai.open_workflow import write_confirmed_note

            wrote = write_confirmed_note(
                store,
                {
                    "relpath": "raw/factors/momentum.md",
                    "body": "# momentum\n\nA user note about momentum on hs300.\n",
                },
            )
            print(" wrote path:", wrote)
            print(" exists after write:", target.exists())
            print(" text head:", target.read_text(encoding="utf-8")[:80] if target.exists() else "")
            self.assertTrue(target.is_file())
            catalog = json.loads((store.user_kb_dir / "compiled" / "catalog.json").read_text(encoding="utf-8"))
            paths = [item.get("path") for item in catalog.get("entries") or []]
            print(" catalog paths:", paths)
            self.assertIn("raw/factors/momentum.md", paths)
            official = Path(__file__).resolve().parents[1] / "qteasy_ai" / "kb"
            self.assertTrue(official.is_dir())

    def test_ask_still_ignores_user_notes(self) -> None:
        """Ask 仍不检索用户笔记；官方 kb 不被写入。"""

        print("\n[TestAiUserKbConsume] ask ignores user notes")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            decoy = store.user_kb_dir / "raw" / "research" / "qteasy.md"
            decoy.write_text("# user decoy\nTHIS IS USER DECOY AND MUST NOT APPEAR IN ASK\n", encoding="utf-8")
            store.compile_user_kb()
            official_dir = Path(__file__).resolve().parents[1] / "qteasy_ai" / "kb"
            before = {path.name for path in official_dir.glob("*.json")}
            asst = QteasyAssistant(memory_store=store, registry=build_default_registry())
            payload = asst.ask("什么是 qteasy", response_style="raw")
            print(" sources:", payload.get("sources"))
            print(" answer head:", str(payload.get("answer") or "")[:120])
            joined = " ".join(str(item) for item in (payload.get("sources") or []))
            self.assertNotIn("user_kb", joined)
            self.assertNotIn("qteasy.md", joined)
            self.assertNotIn("USER DECOY", str(payload.get("answer") or ""))
            self.assertIn("what_is_qteasy", payload.get("sources") or [])
            after = {path.name for path in official_dir.glob("*.json")}
            print(" official kb unchanged:", before == after)
            self.assertEqual(before, after)
            kb_ids = [item.id for item in KnowledgeBase().retrieve("什么是 qteasy")]
            print(" official retrieve ids:", kb_ids)
            self.assertNotIn("user decoy", kb_ids)


if __name__ == "__main__":
    unittest.main()
