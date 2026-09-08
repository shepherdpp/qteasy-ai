# coding=utf-8
# ======================================
# File: test_ai_workbench_dto.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-07
# Desc:
# Unittest for Workbench DTO / mapper (G.1)
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.session import ConversationState
from qteasy_ai.workbench.mapper import classify_artifacts, map_assistant_payload


class TestAiWorkbenchDto(unittest.TestCase):
    """G.1：Ask / Plan / 澄清 / sidebar / artifact 分类。"""

    def _assistant(self, temp_dir: str) -> QteasyAssistant:
        """临时 MemoryStore 上的助手。"""

        store = MemoryStore(base_dir=temp_dir)
        return QteasyAssistant(memory_store=store, registry=build_default_registry())

    def test_ask_what_is_qteasy_has_sources_no_executable_plan(self) -> None:
        """Ask「什么是 qteasy」→ mode=ask、sources 非空、plan_card 不可确认执行。"""

        print("\n[TestAiWorkbenchDto] ask what is qteasy")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = self._assistant(temp_dir)
            payload = assistant.ask("什么是 qteasy", response_style="raw")
            state = map_assistant_payload(payload, query="什么是 qteasy")
            dumped = state.to_dict()
            print(" mode:", dumped["mode"])
            print(" sources:", dumped["sources"])
            print(" plan_card:", dumped["plan_card"])
            print(" messages kinds:", [item["kind"] for item in dumped["messages"]])
            self.assertEqual(dumped["mode"], "ask")
            self.assertIn("what_is_qteasy", dumped["sources"])
            self.assertTrue(dumped["sources"])
            card = dumped["plan_card"]
            self.assertTrue(card is None or card.get("confirmable") is False or not card.get("steps"))
            kinds = [item["kind"] for item in dumped["messages"]]
            self.assertIn("ask_text", kinds)
            self.assertNotIn("plan_card", kinds)

    def test_plan_list_strategies_dry_run_card(self) -> None:
        """Plan 列出内置策略 → steps 非空、side_effects、dry_run。"""

        print("\n[TestAiWorkbenchDto] plan list strategies")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = self._assistant(temp_dir)
            payload = assistant.plan("list built-in strategies", response_style="raw")
            state = map_assistant_payload(payload, query="list built-in strategies")
            dumped = state.to_dict()
            print(" mode:", dumped["mode"])
            print(" execution:", dumped["execution"])
            print(" plan_card steps:", dumped["plan_card"]["steps"] if dumped["plan_card"] else None)
            self.assertEqual(dumped["mode"], "plan")
            self.assertEqual(dumped["execution"]["status"], "dry_run")
            self.assertIsNotNone(dumped["plan_card"])
            steps = dumped["plan_card"]["steps"]
            self.assertGreaterEqual(len(steps), 1)
            self.assertIn("side_effects", steps[0])
            self.assertIn("network", steps[0]["side_effects"])
            self.assertTrue(dumped["plan_card"]["plan_id"])

    def test_refill_missing_dates_clarification(self) -> None:
        """缺槽 refill → clarification 消息、sidebar missing、无 execute success。"""

        print("\n[TestAiWorkbenchDto] refill missing dates")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = self._assistant(temp_dir)
            payload = assistant.plan("帮我下载日线", response_style="raw", session_id="s-refill")
            session = assistant.session_store.load("s-refill")
            state = map_assistant_payload(payload, session=session, query="帮我下载日线")
            dumped = state.to_dict()
            kinds = [item["kind"] for item in dumped["messages"]]
            print(" kinds:", kinds)
            print(" missing:", dumped["sidebar"]["missing"])
            print(" execution:", dumped["execution"]["status"])
            print(" clarification msg:", [m for m in dumped["messages"] if m["kind"] == "clarification"])
            self.assertIn("clarification", kinds)
            self.assertTrue(dumped["sidebar"]["missing"] or dumped["messages"])
            self.assertNotEqual(dumped["execution"]["status"], "success")
            self.assertEqual(dumped["execution"]["status"], "dry_run")

    def test_sidebar_projects_slot_source_and_confirmed(self) -> None:
        """sidebar 投影 slots 的 source / confirmed；未知键不影响投影。"""

        print("\n[TestAiWorkbenchDto] sidebar slots")
        session = ConversationState.empty("s-slots")
        session.active_intent = {"job": "data.refill", "flags": {}}
        session.set_slot("start", "20240101", source="user", confirmed=True)
        session.set_slot("shares", "000300.SH", source="default", confirmed=False)
        session.missing = ["end"]
        session.current_plan_id = "plan_demo"
        payload = {
            "mode": "plan",
            "plan": {"plan_id": "plan_demo", "steps": [], "mode": "plan"},
            "execution": {"status": "dry_run", "steps": []},
            "run_id": "run_demo",
        }
        state = map_assistant_payload(payload, session=session, query="download")
        dumped = state.to_dict()
        slots = {item["name"]: item for item in dumped["sidebar"]["slots"]}
        print(" sidebar:", dumped["sidebar"])
        self.assertEqual(dumped["sidebar"]["active_intent"]["job"], "data.refill")
        self.assertEqual(slots["start"]["source"], "user")
        self.assertTrue(slots["start"]["confirmed"])
        self.assertEqual(slots["shares"]["source"], "default")
        self.assertFalse(slots["shares"]["confirmed"])
        self.assertEqual(dumped["sidebar"]["missing"], ["end"])
        self.assertNotIn("confidence", slots["start"])

    def test_classify_artifacts_four_types(self) -> None:
        """合成 step result → data_table / chart / strategy_code / backtest_report。"""

        print("\n[TestAiWorkbenchDto] classify artifacts")
        run_id = "run_art"
        table_step = {
            "step_id": "s1",
            "skill_name": "qt.ai.data.read",
            "result": {
                "ok": True,
                "skill_name": "qt.ai.data.read",
                "data_summary": {"channel": "history", "names": "close", "n_rows": 2},
                "payload": {"preview_rows": [{"close": 1.0}, {"close": 2.0}]},
                "artifacts": [],
            },
        }
        chart_step = {
            "step_id": "s2",
            "skill_name": "qt.ai.visual.export_kline",
            "result": {
                "ok": True,
                "artifacts": [{"type": "image", "path": "/tmp/kline.png"}],
            },
        }
        code_step = {
            "step_id": "s3",
            "skill_name": "qt.ai.strategy.codegen_hybrid",
            "result": {
                "ok": True,
                "artifacts": [{"kind": "strategy_source", "path": "/tmp/GeneratedSmaCross.py"}],
            },
        }
        bt_step = {
            "step_id": "s4",
            "skill_name": "qt.ai.backtest.run_builtin",
            "result": {
                "ok": True,
                "metrics": {"annual_rtn": 0.1, "mdd": -0.2},
                "artifacts": [{"kind": "trade_log", "path": "/tmp/trade_log.csv"}],
            },
        }
        items = classify_artifacts(run_id, [table_step, chart_step, code_step, bt_step])
        types = [item["type"] for item in items]
        print(" types:", types)
        print(" items:", items)
        self.assertEqual(types, ["data_table", "chart", "strategy_code", "backtest_report"])
        for item in items:
            self.assertEqual(item["run_id"], run_id)
        self.assertEqual(items[0]["preview"]["data_summary"]["channel"], "history")
        self.assertEqual(len(items[0]["preview"]["preview_rows"]), 2)

    def test_data_read_invalid_channel_english_error(self) -> None:
        """非法 channel 的 data.read 结果 → error.message 英文非空。"""

        print("\n[TestAiWorkbenchDto] invalid channel error")
        payload = {
            "mode": "plan",
            "plan": {
                "plan_id": "plan_err",
                "mode": "plan",
                "steps": [{"step_id": "s1", "skill_name": "qt.ai.data.read", "side_effects": {}}],
            },
            "execution": {
                "status": "partial_failed",
                "steps": [
                    {
                        "step_id": "s1",
                        "skill_name": "qt.ai.data.read",
                        "result": {
                            "ok": False,
                            "error": {
                                "code": "INVALID_CHANNEL",
                                "message": "channel must be one of: history, reference, static.",
                            },
                        },
                    }
                ],
            },
            "run_id": "run_err",
        }
        state = map_assistant_payload(payload, query="read data")
        dumped = state.to_dict()
        print(" error:", dumped["error"])
        print(" messages:", dumped["messages"])
        self.assertIsNotNone(dumped["error"])
        message = str(dumped["error"].get("message") or "")
        self.assertTrue(message)
        self.assertRegex(message, r"[A-Za-z]")
        self.assertIn("channel", message.lower())

    def test_high_side_effect_needs_confirm(self) -> None:
        """refill 步 needs_confirm=true。"""

        print("\n[TestAiWorkbenchDto] needs_confirm")
        payload = {
            "mode": "plan",
            "plan": {
                "plan_id": "plan_refill",
                "mode": "plan",
                "steps": [
                    {
                        "step_id": "s1",
                        "skill_name": "qt.ai.data.refill_basic_equity_and_index",
                        "side_effects": {
                            "network": True,
                            "filesystem_write": True,
                            "local_state_change": True,
                            "heavy_compute": False,
                            "description": "refill",
                        },
                    }
                ],
            },
            "execution": {"status": "dry_run", "steps": []},
            "run_id": "run_refill",
        }
        dumped = map_assistant_payload(payload, query="download").to_dict()
        print(" steps:", dumped["plan_card"]["steps"])
        self.assertTrue(dumped["plan_card"]["steps"][0]["needs_confirm"])
        self.assertTrue(dumped["plan_card"]["needs_confirm"])


if __name__ == "__main__":
    unittest.main()
