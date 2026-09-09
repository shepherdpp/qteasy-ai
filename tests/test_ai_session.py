# coding=utf-8
# ======================================
# File: test_ai_session.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-05
# Desc:
# Unittest for ConversationState / SessionStore
# ======================================

import json
import tempfile
import unittest

from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.session import ConversationState, SessionStore, Slot


class TestAiSession(unittest.TestCase):
    """测试会话状态字段、往返与损坏降级。"""

    def test_empty_session_fields(self) -> None:
        """空 session 含 F 最小字段，无 confidence / 开放环键。"""

        print("\n[TestAiSession] empty session fields")
        state = ConversationState.empty("sess-1")
        payload = state.to_dict()
        print(" payload keys:", sorted(payload.keys()))
        print(" slots:", payload["slots"])
        self.assertEqual(payload["session_id"], "sess-1")
        self.assertIsNone(payload["active_intent"])
        self.assertEqual(payload["slots"], {})
        self.assertEqual(payload["missing"], [])
        self.assertIsNone(payload["pending_clarification"])
        self.assertEqual(payload["current_plan_id"], "")
        self.assertEqual(payload["clarify_round"], 0)
        self.assertEqual(payload["turns"], [])
        self.assertEqual(payload["messages"], [])
        self.assertEqual(payload["attachments"], [])
        self.assertNotIn("confidence", payload)
        self.assertNotIn("active_design", payload)
        self.assertNotIn("current_trial_plan", payload)
        slot = Slot(value="000300.SH", source="profile", confirmed=False)
        slot_dict = slot.to_dict()
        print(" slot:", slot_dict)
        self.assertEqual(set(slot_dict.keys()), {"value", "source", "confirmed"})
        self.assertNotIn("confidence", slot_dict)

    def test_save_load_roundtrip(self) -> None:
        """save/load 往返保留 F 字段。"""

        print("\n[TestAiSession] save/load roundtrip")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            print(" sessions_dir:", store.sessions_dir)
            self.assertTrue(store.sessions_dir.exists())
            self.assertEqual(store.sessions_dir, store.base_dir / "sessions")
            sessions = SessionStore(store)
            state = ConversationState.empty("abc")
            state.active_intent = {"job": "data.refill", "flags": {}}
            state.set_slot("start", "20240101", source="user", confirmed=True)
            state.missing = ["end"]
            state.current_plan_id = "plan-1"
            state.turns = [{"query": "download daily"}]
            path = sessions.save(state)
            print(" saved path:", path)
            loaded = sessions.load("abc")
            print(" loaded:", loaded.to_dict())
            self.assertEqual(loaded.session_id, "abc")
            self.assertEqual(loaded.active_intent["job"], "data.refill")
            self.assertEqual(loaded.slots["start"].value, "20240101")
            self.assertEqual(loaded.slots["start"].source, "user")
            self.assertTrue(loaded.slots["start"].confirmed)
            self.assertEqual(loaded.missing, ["end"])
            self.assertEqual(loaded.current_plan_id, "plan-1")
            self.assertEqual(loaded.turns[0]["query"], "download daily")
            self.assertEqual(loaded.messages, [])

            state.messages = [{"kind": "user_text", "text": "hi", "payload": {}}]
            sessions.save(state)
            again = sessions.load("abc")
            print(" messages roundtrip:", again.messages)
            self.assertEqual(again.messages[0]["text"], "hi")
            cut = again.rewind_from_user_index(0, discard=True)
            print(" rewind:", cut, again.messages, again.turns)
            self.assertTrue(cut["ok"])
            self.assertEqual(again.messages, [])
            self.assertEqual(again.turns, [])

    def test_load_ignores_unknown_keys(self) -> None:
        """未知键（如 active_design）不崩；再保存不写出开放环字段。"""

        print("\n[TestAiSession] unknown keys forward-compat")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            sessions = SessionStore(store)
            path = sessions.path_for("fwd")
            path.write_text(
                json.dumps(
                    {
                        "session_id": "fwd",
                        "active_intent": {"job": "backtest.builtin", "flags": {}},
                        "slots": {
                            "shares": {
                                "value": "000300.SH",
                                "source": "user",
                                "confirmed": True,
                                "confidence": 0.9,
                            }
                        },
                        "missing": [],
                        "active_design": {"spec": "should-ignore"},
                        "current_trial_plan": "trial-x",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            loaded = sessions.load("fwd")
            print(" loaded keys:", sorted(loaded.to_dict().keys()))
            print(" shares slot:", loaded.slots["shares"].to_dict())
            self.assertEqual(loaded.active_intent["job"], "backtest.builtin")
            self.assertEqual(loaded.slots["shares"].value, "000300.SH")
            self.assertNotIn("confidence", loaded.slots["shares"].to_dict())
            dumped = loaded.to_dict()
            print(" dumped:", dumped)
            self.assertNotIn("active_design", dumped)
            self.assertNotIn("current_trial_plan", dumped)
            sessions.save(loaded)
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            print(" on_disk keys:", sorted(on_disk.keys()))
            self.assertNotIn("active_design", on_disk)
            self.assertNotIn("current_trial_plan", on_disk)

    def test_corrupt_session_falls_back(self) -> None:
        """损坏 JSON 降级为空会话。"""

        print("\n[TestAiSession] corrupt json fallback")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            sessions = SessionStore(store)
            path = sessions.path_for("bad")
            path.write_text("{not-json", encoding="utf-8")
            loaded = sessions.load("bad")
            backup = path.with_suffix(path.suffix + ".corrupt.json")
            print(" loaded:", loaded.to_dict())
            print(" backup exists:", backup.exists())
            self.assertEqual(loaded.session_id, "bad")
            self.assertIsNone(loaded.active_intent)
            self.assertTrue(backup.exists())


if __name__ == "__main__":
    unittest.main()
