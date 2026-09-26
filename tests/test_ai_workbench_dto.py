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

import pandas as pd

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.session import ConversationState
from qteasy_ai.skills.data_read import build_data_read_skill
from qteasy_ai.skills.data_summary import build_data_summary_skill
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
            self.assertIn("ask", kinds)
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
            print(" summary:", steps[0].get("summary"))
            self.assertIn("List", steps[0].get("summary") or "")

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
            print(" clarification msg:", [m for m in dumped["messages"] if m["kind"] in {"clarification", "clarify"}])
            self.assertIn("clarify", kinds)
            self.assertTrue(dumped["sidebar"]["missing"] or dumped["messages"])
            self.assertNotEqual(dumped["execution"]["status"], "success")
            self.assertEqual(dumped["execution"]["status"], "dry_run")

    def test_sidebar_projects_slot_source_and_confirmed(self) -> None:
        """sidebar 投影 slots 的 source / confirmed；未知键不影响投影。"""

        print("\n[TestAiWorkbenchDto] sidebar slots")
        session = ConversationState.empty("s-slots")
        session.start_task(query="download", job="data.refill")
        session.set_slot("start", "20240101", source="user", confirmed=True)
        session.set_slot("shares", "000300.SH", source="default", confirmed=False)
        session.task.set_missing(["end"])
        session.task.plan_id = "plan_demo"
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
                "artifacts": [
                    {"kind": "trade_log", "path": "/tmp/trade_log.csv"},
                    {"kind": "chart", "path": "/tmp/backtest_visual.png"},
                ],
            },
        }
        items = classify_artifacts(run_id, [table_step, chart_step, code_step, bt_step])
        types = [item["type"] for item in items]
        print(" types:", types)
        print(" items:", items)
        self.assertEqual(types, ["data_table", "chart", "strategy_code", "backtest_report", "chart"])
        self.assertEqual(items[-1]["export_path"], "/tmp/backtest_visual.png")
        self.assertEqual(items[-1]["title"], "qt.ai.backtest.visual")
        for item in items:
            self.assertEqual(item["run_id"], run_id)
        self.assertEqual(items[0]["preview"]["data_summary"]["channel"], "history")
        self.assertEqual(len(items[0]["preview"]["preview_rows"]), 2)

        list_step = {
            "step_id": "s5",
            "skill_name": "qt.ai.strategy_meta.list",
            "result": {
                "ok": True,
                "skill_name": "qt.ai.strategy_meta.list",
                "payload": {"strategies": ["macd", "trix", "dma"]},
                "data_summary": {"count": 3, "first_items": ["macd", "trix", "dma"]},
                "artifacts": [],
            },
        }
        listed = classify_artifacts("run_list", [list_step])
        print(" strategy list artifacts:", listed)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["type"], "data_table")
        self.assertEqual(listed[0]["preview"]["preview_rows"][0]["strategy"], "macd")
        self.assertEqual(len(listed[0]["preview"]["preview_rows"]), 3)

        get_step = {
            "step_id": "s6",
            "skill_name": "qt.ai.strategy_meta.get",
            "result": {
                "ok": True,
                "skill_name": "qt.ai.strategy_meta.get",
                "payload": {
                    "strategy_id": "bband",
                    "strategy_type": "BBAND",
                    "doc": "BBAND strategy.\nParameters:\n- n: period (default 20)",
                },
                "metrics": {"doc_length": 52},
                "data_summary": {"strategy_type": "BBAND"},
                "artifacts": [],
            },
        }
        got = classify_artifacts("run_bband", [get_step])
        print(" strategy get artifact:", got)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["type"], "data_table")
        self.assertEqual(got[0]["preview"]["data_summary"]["strategy_id"], "bband")
        self.assertTrue(any("BBAND" in str(row.get("line") or "") for row in got[0]["preview"]["preview_rows"]))

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
        print(" next_action:", dumped["error"].get("next_action"))
        self.assertRegex(str(dumped["error"].get("next_action") or ""), r"[A-Za-z]")

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
        print(" summary:", dumped["plan_card"]["steps"][0].get("summary"))
        self.assertIn("Download", dumped["plan_card"]["steps"][0].get("summary") or "")

    def test_plan_artifact_title_is_human_not_plan_md(self) -> None:
        """list 策略 dry-run 的 plan artifact title 为人话 + hex。"""

        print("\n[TestAiWorkbenchDto] plan artifact display title")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = self._assistant(temp_dir)
            payload = assistant.plan("list built-in strategies", response_style="raw")
            state = map_assistant_payload(payload, query="list built-in strategies")
            dumped = state.to_dict()
            plan_id = (dumped.get("plan_card") or {}).get("plan_id") or ""
            arts = [item for item in dumped.get("artifacts") or [] if item.get("type") == "plan"]
            print(" plan_id:", plan_id)
            print(" plan artifacts:", arts)
            self.assertRegex(str(plan_id), r"^plan_[0-9a-f]{12}$")
            self.assertTrue(arts)
            title = str(arts[0].get("title") or "")
            print(" title:", title)
            self.assertNotEqual(title, "plan.md")
            self.assertTrue("List" in title or "strateg" in title.lower())
            self.assertIn(str(plan_id).replace("plan_", "")[:8], title)

    def test_preview_list_splits_into_rows_and_caps_at_fifty(self) -> None:
        """payload.preview 为记录列表时按行展开，超过 50 行截断。"""

        print("\n[TestAiWorkbenchDto] preview list split")
        step = {
            "step_id": "s1",
            "skill_name": "qt.ai.data.summary_kline",
            "result": {
                "ok": True,
                "skill_name": "qt.ai.data.summary_kline",
                "data_summary": {"columns": ["close"]},
                "payload": {
                    "preview": [{"close": 1.0}, {"close": 2.0}, {"close": 3.0}],
                },
            },
        }
        items = classify_artifacts("run_prev", [step])
        rows = items[0]["preview"]["preview_rows"]
        print(" split rows:", rows)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], {"close": 1.0})
        self.assertEqual(rows[2], {"close": 3.0})
        self.assertNotIsInstance(rows[0], list)

        long_step = {
            "step_id": "s2",
            "skill_name": "qt.ai.data.read",
            "result": {
                "ok": True,
                "data_summary": {"channel": "history"},
                "payload": {"preview": [{"close": float(i)} for i in range(60)]},
            },
        }
        capped = classify_artifacts("run_cap", [long_step])[0]["preview"]["preview_rows"]
        print(" capped n:", len(capped), "first:", capped[0], "last:", capped[-1])
        self.assertEqual(len(capped), 50)
        self.assertEqual(capped[0]["close"], 0.0)
        self.assertEqual(capped[49]["close"], 49.0)

    def test_skill_payload_classifies_as_column_rows(self) -> None:
        """data.read / data.summary 的 handler 输出经 mapper 仍是列名字典行。"""

        print("\n[TestAiWorkbenchDto] skill payload to artifact rows")
        index = pd.date_range("2024-01-02", periods=2, freq="D")
        index.name = "date"
        history = {"000300.SH": pd.DataFrame({"close": [10.5, 11.0]}, index=index)}
        _, read_handler = build_data_read_skill(
            history_func=lambda **kwargs: history,
            reference_func=lambda **kwargs: {},
            static_func=lambda **kwargs: {},
        )
        read_result = read_handler(channel="history", names="close", shares="000300.SH")
        read_items = classify_artifacts(
            "run_read",
            [
                {
                    "step_id": "s1",
                    "skill_name": "qt.ai.data.read",
                    "result": read_result,
                }
            ],
        )
        read_rows = read_items[0]["preview"]["preview_rows"]
        print(" data.read rows:", read_rows)

        kline_index = pd.date_range("2024-01-01", periods=6, freq="D")
        kline_index.name = "date"
        kline = pd.DataFrame(
            {
                "open": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
                "high": [2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
                "low": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5],
                "close": [1.2, 2.2, 3.1, 3.8, 5.0, 5.2],
                "vol": [10, 11, 12, 13, 14, 15],
            },
            index=kline_index,
        )
        _, summary_handler = build_data_summary_skill(get_kline_func=lambda **kwargs: kline.copy())
        summary_result = summary_handler(shares="000300.SH", freq="d")
        summary_items = classify_artifacts(
            "run_sum",
            [
                {
                    "step_id": "s1",
                    "skill_name": "qt.ai.data.summary_kline",
                    "result": summary_result,
                }
            ],
        )
        summary_rows = summary_items[0]["preview"]["preview_rows"]
        print(" summary rows:", summary_rows)
        self.assertEqual(len(read_rows), 2)
        self.assertEqual(read_rows[0]["share"], "000300.SH")
        self.assertEqual(read_rows[0]["close"], 10.5)
        self.assertEqual(len(summary_rows), 6)
        self.assertEqual(summary_rows[0]["close"], 1.2)
        self.assertEqual(summary_rows[5]["close"], 5.2)
        self.assertIn("2024-01-01", str(summary_rows[0]["date"]))
        self.assertTrue(all(isinstance(row, dict) for row in summary_rows))


if __name__ == "__main__":
    unittest.main()
