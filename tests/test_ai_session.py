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
from qteasy_ai.session import (
    STATE_KEYS,
    STALE_RUNNING_NOTICE,
    ConversationState,
    SessionStore,
    Slot,
    clear_live_running,
    register_live_running,
)
from qteasy_ai.session_gate import SessionGate


class TestAiSession(unittest.TestCase):
    """测试会话状态字段、往返与损坏降级。"""

    def test_empty_session_fields(self) -> None:
        """空 session 只有五字段，task 为 None。"""

        print("\n[TestAiSession] empty session fields")
        state = ConversationState.empty("sess-1")
        payload = state.to_dict()
        print(" payload keys:", sorted(payload.keys()))
        print(" task:", payload["task"])
        self.assertEqual(set(payload.keys()), STATE_KEYS)
        self.assertEqual(payload["session_id"], "sess-1")
        self.assertIsNone(payload["task"])
        self.assertEqual(payload["messages"], [])
        self.assertEqual(payload["attachments"], [])
        self.assertFalse(payload["agent_auto"])
        self.assertFalse(hasattr(ConversationState, "active_intent"))
        self.assertFalse(hasattr(ConversationState, "live_design"))
        self.assertFalse(hasattr(ConversationState, "turns"))
        slot = Slot(value="000300.SH", source="profile", confirmed=False)
        slot_dict = slot.to_dict()
        print(" slot:", slot_dict)
        self.assertEqual(set(slot_dict.keys()), {"value", "source", "confirmed"})
        self.assertNotIn("confidence", slot_dict)

    def test_save_load_roundtrip(self) -> None:
        """save/load 往返保留 task 与 messages。"""

        print("\n[TestAiSession] save/load roundtrip")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            print(" sessions_dir:", store.sessions_dir)
            self.assertTrue(store.sessions_dir.exists())
            self.assertEqual(store.sessions_dir, store.base_dir / "sessions")
            sessions = SessionStore(store)
            state = ConversationState.empty("abc")
            state.start_task(query="refill", job="data.refill")
            state.set_slot("start", "20240101", source="user", confirmed=True)
            state.task.set_missing(["end"])
            state.task.plan_id = "plan-1"
            path = sessions.save(state)
            print(" saved path:", path)
            loaded = sessions.load("abc")
            print(" loaded:", loaded.to_dict())
            self.assertEqual(loaded.session_id, "abc")
            self.assertIsNotNone(loaded.task)
            self.assertEqual(loaded.task.job, "data.refill")
            self.assertEqual(loaded.task.slots["start"].value, "20240101")
            self.assertEqual(loaded.task.slots["start"].source, "user")
            self.assertTrue(loaded.task.slots["start"].confirmed)
            self.assertEqual(loaded.task.missing, ["end"])
            self.assertEqual(loaded.task.plan_id, "plan-1")
            self.assertEqual(loaded.messages, [])
            dumped = loaded.to_dict()
            print(" dumped keys:", sorted(dumped.keys()))
            self.assertEqual(set(dumped.keys()), STATE_KEYS)
            self.assertNotIn("turns", dumped)
            self.assertNotIn("active_intent", dumped)

            state.messages = [{"kind": "user_text", "text": "hi", "payload": {}}]
            sessions.save(state)
            again = sessions.load("abc")
            print(" messages roundtrip:", again.messages)
            self.assertEqual(again.messages[0]["text"], "hi")
            cut = again.rewind_from_user_index(0, discard=True)
            print(" rewind:", cut, again.messages)
            self.assertTrue(cut["ok"])
            self.assertEqual(again.messages, [])
            self.assertIsNone(again.task)
            again.messages = [
                {"kind": "user_text", "text": "a", "payload": {}},
                {
                    "kind": "plan_ready",
                    "text": "Plan ready: List built-in strategies",
                    "payload": {"plan_id": "plan_1", "run_id": "run_1"},
                },
            ]
            again.append_messages(
                [
                    {"kind": "user_text", "text": "b", "payload": {}},
                    {
                        "kind": "plan_ready",
                        "text": "Plan ready: List built-in strategies",
                        "payload": {"plan_id": "plan_2", "run_id": "run_2"},
                    },
                ]
            )
            print(" dedupe keep second plan:", again.messages)
            self.assertEqual(len([m for m in again.messages if m["kind"] == "plan_ready"]), 2)

    def test_load_ignores_unknown_keys(self) -> None:
        """未知键不崩；旧扁平 JSON 降级成 task。"""

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
                        "future_field": {"spec": "should-ignore"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            loaded = sessions.load("fwd")
            print(" loaded keys:", sorted(loaded.to_dict().keys()))
            print(" shares slot:", loaded.task.slots["shares"].to_dict())
            self.assertEqual(loaded.task.job, "backtest.builtin")
            self.assertEqual(loaded.task.slots["shares"].value, "000300.SH")
            self.assertNotIn("confidence", loaded.task.slots["shares"].to_dict())
            dumped = loaded.to_dict()
            print(" dumped:", dumped)
            self.assertEqual(set(dumped.keys()), STATE_KEYS)
            self.assertNotIn("future_field", dumped)
            self.assertNotIn("active_design", dumped)
            sessions.save(loaded)
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            print(" on_disk keys:", sorted(on_disk.keys()))
            self.assertEqual(set(on_disk.keys()), set(STATE_KEYS))
            self.assertNotIn("active_design", on_disk)
            self.assertNotIn("future_field", on_disk)

    def test_open_design_roundtrip(self) -> None:
        """设计环字段不再落盘；无 live_design 方法。"""

        print("\n[TestAiSession] open design roundtrip ignored")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            sessions = SessionStore(store)
            state = ConversationState.empty("open1")
            state.start_task(query="explore", job="research.factor_explore")
            sessions.save(state)
            loaded = sessions.load("open1")
            dumped = loaded.to_dict()
            print(" dumped keys:", sorted(dumped.keys()))
            self.assertEqual(set(dumped.keys()), STATE_KEYS)
            self.assertNotIn("active_design", dumped)
            self.assertNotIn("current_trial_plan_id", dumped)
            self.assertNotIn("trial_queue", dumped)
            self.assertFalse(hasattr(loaded, "live_design"))
            self.assertFalse(hasattr(ConversationState, "active_design"))

    def test_plan_ready_is_not_incomplete(self) -> None:
        """done 不是 incomplete；clarifying 才是。"""

        print("\n[TestAiSession] plan ready not incomplete")
        state = ConversationState.empty("plan-ready")
        state.start_task(query="list", job="strategy.meta")
        state.task.plan_id = "plan_abc"
        state.task.mark_done()
        print(" incomplete:", state.task_incomplete(), "plan_id:", state.task.plan_id)
        self.assertFalse(state.task_incomplete())
        state.task.status = "clarifying"
        state.task.set_pending({"confirm_prompt": "Which id?"})
        print(" clarifying incomplete:", state.task_incomplete())
        self.assertTrue(state.task_incomplete())

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
            self.assertIsNone(loaded.task)
            self.assertTrue(backup.exists())

    def test_load_heals_stale_running(self) -> None:
        """落盘 running 且无活执行时降为 ready，并写一次 notice。"""

        print("\n[TestAiSession] heal stale running on load")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            sessions = SessionStore(store)
            state = ConversationState.empty("stale-run")
            state.start_task(query="export kline", job="data.export")
            state.task.plan_id = "plan_export"
            state.task.high_side_effect = True
            state.task.mark_running()
            path = sessions.save(state)
            print(" saved status:", state.task.status, "path:", path)
            loaded = sessions.load("stale-run")
            print(" loaded status:", loaded.task_status())
            print(" last message:", loaded.messages[-1] if loaded.messages else None)
            on_disk = json.loads(sessions.path_for("stale-run").read_text(encoding="utf-8"))
            print(" on_disk status:", (on_disk.get("task") or {}).get("status"))
            self.assertEqual(loaded.task_status(), "ready")
            self.assertEqual(loaded.task.plan_id, "plan_export")
            self.assertTrue(loaded.task.high_side_effect)
            self.assertEqual(loaded.messages[-1]["kind"], "mode_notice")
            self.assertEqual(loaded.messages[-1]["text"], STALE_RUNNING_NOTICE)
            self.assertEqual(loaded.messages[-1]["payload"]["reason"], "stale_running")
            self.assertEqual((on_disk.get("task") or {}).get("status"), "ready")
            again = sessions.load("stale-run")
            notices = [row for row in again.messages if row.get("kind") == "mode_notice"]
            print(" second load notices:", len(notices), "status:", again.task_status())
            self.assertEqual(len(notices), 1)
            self.assertEqual(again.task_status(), "ready")
            decision = SessionGate(provider=None).classify(again, "请列出所有内置交易策略")
            print(" gate after heal:", decision.kind)
            self.assertEqual(decision.kind, "new_intent")

    def test_load_keeps_live_running(self) -> None:
        """进程内活执行时 load 不得把 running 降为 ready。"""

        print("\n[TestAiSession] load keeps live running")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            sessions = SessionStore(store)
            state = ConversationState.empty("live-run")
            state.start_task(query="export kline", job="data.export")
            state.task.plan_id = "plan_live"
            state.task.high_side_effect = True
            state.task.mark_running()
            sessions.save(state)
            register_live_running("live-run")
            try:
                loaded = sessions.load("live-run")
                print(" live loaded status:", loaded.task_status(), "messages:", loaded.messages)
                self.assertEqual(loaded.task_status(), "running")
                self.assertEqual(loaded.messages, [])
            finally:
                clear_live_running("live-run")

    def test_close_open_card_patches_latest_unanswered_clarify(self) -> None:
        """就地关闭最近未答 clarify，不追加消息。"""

        print("\n[TestAiSession] close_open_card latest clarify")
        state = ConversationState.empty("close-1")
        state.append_messages(
            [
                {"kind": "user_text", "text": "download daily", "payload": {}},
                {
                    "kind": "clarify",
                    "text": "Need start and end.",
                    "payload": {"pending": [{"name": "start"}]},
                },
            ]
        )
        before = len(state.messages)
        closed = state.close_open_card("start 20240101", status="answered")
        print(" closed:", closed, "n:", len(state.messages), "payload:", state.messages[-1]["payload"])
        self.assertTrue(closed)
        self.assertEqual(len(state.messages), before)
        self.assertEqual(state.messages[-1]["kind"], "clarify")
        self.assertEqual(state.messages[-1]["payload"]["status"], "answered")
        self.assertEqual(state.messages[-1]["payload"]["answer"], "start 20240101")
        again = state.close_open_card("end 20241231", status="answered")
        print(" second close on already answered:", again, state.messages[-1]["payload"])
        self.assertFalse(again)
        self.assertEqual(state.messages[-1]["payload"]["answer"], "start 20240101")


if __name__ == "__main__":
    unittest.main()
