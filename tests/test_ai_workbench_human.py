# coding=utf-8
# ======================================
# File: test_ai_workbench_human.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-08
# Desc:
# Unittest for CLI/Notebook --human renderer
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.workbench.human import format_human_error, format_human_from_payload


class TestAiWorkbenchHuman(unittest.TestCase):
    """human 文本对齐对话区：回答 / 澄清 / 错误 / 确认卡。"""

    def test_ask_shows_answer_not_plan_json(self) -> None:
        """Ask 金句：stdout 含答案，不含可执行 plan JSON。"""

        print("\n[TestAiWorkbenchHuman] ask what is qteasy")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            payload = assistant.ask("什么是 qteasy", response_style="raw")
            text = format_human_from_payload(payload, query="什么是 qteasy")
            print(" human:", text)
            print(" sources:", payload.get("sources"))
            self.assertIn("[MODE: ASK]", text)
            self.assertIn("qteasy", text.lower())
            self.assertIn("what_is_qteasy", text)
            self.assertNotIn('"plan_id"', text)
            self.assertNotIn("Confirm: qteasy-ai run --plan-id", text)

    def test_refill_missing_is_clarification(self) -> None:
        """缺槽 refill：澄清 + missing，无 execute success。"""

        print("\n[TestAiWorkbenchHuman] refill missing dates")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            payload = assistant.plan("帮我下载日线", response_style="raw", session_id="h-refill")
            session = assistant.session_store.load("h-refill")
            text = format_human_from_payload(payload, query="帮我下载日线", session=session)
            print(" human:", text)
            print(" exec:", (payload.get("execution") or {}).get("status"))
            self.assertIn("[MODE: PLAN]", text)
            self.assertTrue(
                "missing" in text.lower()
                or "provide" in text.lower()
                or "Reply" in text
                or "Clarification" in text
                or "start" in text.lower()
            )
            self.assertNotIn("Status: success", text)
            self.assertNotIn("Confirm: qteasy-ai run --plan-id", text)

    def test_plan_lists_skill_and_confirm_hint(self) -> None:
        """只读 Plan：人读解读卡 + 以 run_id 命名的落盘路径。"""

        print("\n[TestAiWorkbenchHuman] plan list strategies")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=store,
            )
            payload = assistant.plan("list built-in strategies", response_style="raw")
            text = format_human_from_payload(
                payload,
                query="list built-in strategies",
                registry=assistant.registry,
            )
            plan_id = str((payload.get("plan") or {}).get("plan_id") or "")
            run_id = str(payload.get("run_id") or "")
            json_path = store.runs_dir / f"{run_id}.json"
            md_path = store.runs_dir / f"{run_id}.plan.md"
            print(" human:", text)
            print(" plan_id:", plan_id, "run_id:", run_id)
            print(" json exists:", json_path.is_file(), "md exists:", md_path.is_file())
            print(" named as plan_id?:", (store.runs_dir / f"{plan_id}.json").exists())
            self.assertTrue(run_id.startswith("run_"))
            self.assertTrue(plan_id.startswith("plan_"))
            self.assertNotEqual(run_id, plan_id)
            self.assertTrue(json_path.is_file())
            self.assertTrue(md_path.is_file())
            self.assertFalse((store.runs_dir / f"{plan_id}.json").exists())
            self.assertFalse((store.runs_dir / f"{plan_id}.plan.md").exists())
            self.assertIn("[MODE: PLAN]  dry_run — not executed", text)
            self.assertIn("Job:", text)
            self.assertIn("Steps: 1", text)
            self.assertIn("Skill: qt.ai.strategy_meta.list", text)
            self.assertIn("Calls: qteasy.built_in_list", text)
            self.assertIn("Expects:", text)
            self.assertIn("strategies", text)
            self.assertIn("Confirm: qteasy-ai run --plan-id", text)
            self.assertIn(plan_id, text)
            self.assertIn(run_id, text)
            self.assertIn(str(json_path), text)
            self.assertIn(str(md_path), text)
            self.assertNotIn("# ToolPlan", text)
            self.assertNotIn("**inputs**", text)
            self.assertNotIn("gold_lock", text)
            self.assertNotIn("hybrid_intent", text)
            self.assertNotIn("Review plan before execute.", text)
            disk_md = md_path.read_text(encoding="utf-8")
            print(" disk_md head:", disk_md.splitlines()[:6])
            self.assertIn(plan_id, disk_md)
            self.assertIn("# ToolPlan", disk_md)

    def test_plan_brief_picks_history_entrypoint(self) -> None:
        """qt.ai.data.read：human 只显示 channel 对应的一个入口。"""

        print("\n[TestAiWorkbenchHuman] data.read history entrypoint")
        registry = build_default_registry()
        payload = {
            "run_id": "run_demo",
            "run_file": "/tmp/run_demo.json",
            "plan_md_file": "/tmp/run_demo.plan.md",
            "plan_md": "# ToolPlan `plan_demo`\ngold_lock:A1\n**inputs**",
            "plan": {
                "plan_id": "plan_demo",
                "mode": "plan",
                "user_query": "read close of 000300.SH",
                "planner_trace": {"intent_job": "data.read"},
                "steps": [
                    {
                        "step_id": "s1",
                        "skill_name": "qt.ai.data.read",
                        "inputs": {
                            "channel": "history",
                            "names": "close",
                            "shares": "000300.SH",
                        },
                        "side_effects": {"description": "readonly three-entry fetch"},
                    }
                ],
            },
            "execution": {"status": "dry_run", "steps": []},
        }
        text = format_human_from_payload(
            payload,
            query="read close of 000300.SH",
            registry=registry,
        )
        print(" human:", text)
        self.assertIn("Job: data.read", text)
        self.assertIn("Steps: 1", text)
        calls_lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("Calls:")]
        print(" calls:", calls_lines)
        self.assertEqual(calls_lines, ["Calls: qteasy.get_history_data"])
        self.assertIn("names=close", text)
        self.assertIn("shares=000300.SH", text)
        self.assertIn("Expects:", text)
        self.assertNotIn("# ToolPlan", text)
        self.assertNotIn("gold_lock", text)

    def test_error_payload_is_english(self) -> None:
        """错误路径：英文 message。"""

        print("\n[TestAiWorkbenchHuman] english error")
        payload = {
            "ok": False,
            "error": {
                "code": "PLAN_ID_NOT_FOUND",
                "message": "Reviewed plan not found in runs/: plan_id='plan_x'.",
            },
        }
        text = format_human_error(payload)
        print(" text:", text)
        self.assertIn("Reviewed plan not found", text)
        self.assertTrue(text.endswith("\n"))

    def test_execute_success_shows_step_result(self) -> None:
        """执行成功：解读卡含结果，不再要求确认。"""

        print("\n[TestAiWorkbenchHuman] execute result brief")
        registry = build_default_registry()
        payload = {
            "run_id": "run_demo",
            "run_file": "/tmp/run_demo.json",
            "plan": {
                "plan_id": "plan_demo",
                "mode": "plan",
                "user_query": "list built-in strategies",
                "planner_trace": {"intent_job": "strategy.meta"},
                "steps": [
                    {
                        "step_id": "step_1",
                        "skill_name": "qt.ai.strategy_meta.list",
                        "inputs": {},
                    }
                ],
            },
            "execution": {
                "status": "success",
                "steps": [
                    {
                        "step_id": "step_1",
                        "skill_name": "qt.ai.strategy_meta.list",
                        "status": "done",
                        "ok": True,
                        "result": {
                            "ok": True,
                            "skill_name": "qt.ai.strategy_meta.list",
                            "payload": {"strategies": ["macd", "trix"]},
                            "metrics": {"count": 2},
                        },
                    }
                ],
            },
        }
        text = format_human_from_payload(payload, query="list built-in strategies", registry=registry)
        print(" human:", text)
        self.assertIn("[MODE: RUN]  executed", text)
        self.assertIn("Status: success", text)
        self.assertIn("Job: strategy.meta", text)
        self.assertIn("macd", text)
        self.assertIn("trix", text)
        self.assertIn("2 built-in ids", text)
        self.assertNotIn("Confirm: qteasy-ai run --plan-id", text)
        self.assertNotIn("Review plan before execute.", text)

    def test_run_get_shows_strategy_doc(self) -> None:
        """strategy_meta.get：human 打印 docstring，不只 skill 名。"""

        print("\n[TestAiWorkbenchHuman] run get trix doc")
        registry = build_default_registry()
        doc = "TRIX oscillator.\nParameters:\n- n: period (default 14)"
        payload = {
            "run_id": "run_demo",
            "run_file": "/tmp/run_demo.json",
            "plan": {
                "plan_id": "plan_demo",
                "mode": "plan",
                "user_query": "请列出trix策略的所有参数",
                "planner_trace": {"intent_job": "strategy.meta"},
                "steps": [
                    {
                        "step_id": "s1",
                        "skill_name": "qt.ai.strategy_meta.get",
                        "inputs": {"strategy_id": "trix"},
                    }
                ],
            },
            "execution": {
                "status": "success",
                "steps": [
                    {
                        "step_id": "s1",
                        "skill_name": "qt.ai.strategy_meta.get",
                        "result": {
                            "ok": True,
                            "payload": {
                                "strategy_id": "trix",
                                "strategy_type": "TRIX",
                                "doc": doc,
                            },
                            "metrics": {"doc_length": len(doc)},
                        },
                    }
                ],
            },
        }
        text = format_human_from_payload(
            payload,
            query="请列出trix策略的所有参数",
            registry=registry,
        )
        print(" human:", text)
        print(" gold doc:", doc)
        self.assertIn("[MODE: RUN]  executed", text)
        self.assertIn("Skill: qt.ai.strategy_meta.get", text)
        self.assertIn("strategy_id=trix", text)
        self.assertIn("Calls: qteasy.built_in_doc, qteasy.get_built_in_strategy", text)
        self.assertIn("n: period (default 14)", text)
        self.assertIn("TRIX oscillator.", text)
        self.assertNotIn("Confirm: qteasy-ai run --plan-id", text)

    def test_run_failed_step_shows_error(self) -> None:
        """失败步：英文 error.message。"""

        print("\n[TestAiWorkbenchHuman] run failed error")
        payload = {
            "run_id": "run_demo",
            "plan": {
                "plan_id": "plan_demo",
                "mode": "plan",
                "user_query": "get unknown strategy",
                "planner_trace": {"intent_job": "strategy.meta"},
                "steps": [
                    {
                        "step_id": "s1",
                        "skill_name": "qt.ai.strategy_meta.get",
                        "inputs": {"strategy_id": "not_a_strategy"},
                    }
                ],
            },
            "execution": {
                "status": "partial_failed",
                "steps": [
                    {
                        "step_id": "s1",
                        "skill_name": "qt.ai.strategy_meta.get",
                        "result": {
                            "ok": False,
                            "error": {
                                "code": "STRATEGY_GET_FAILED",
                                "message": "Failed to get strategy details: unknown id.",
                            },
                        },
                    }
                ],
            },
        }
        text = format_human_from_payload(payload, query="get unknown strategy")
        print(" human:", text)
        self.assertIn("[MODE: RUN]  executed", text)
        self.assertIn("Status: partial_failed", text)
        self.assertIn("Result: FAILED", text)
        self.assertIn("Failed to get strategy details: unknown id.", text)

    def test_run_data_read_shows_summary_not_rows(self) -> None:
        """data.read：只打 summary/metrics，不倾倒行数据。"""

        print("\n[TestAiWorkbenchHuman] run data.read summary")
        payload = {
            "run_id": "run_demo",
            "plan": {
                "plan_id": "plan_demo",
                "mode": "plan",
                "user_query": "read close of 000300.SH",
                "planner_trace": {"intent_job": "data.read"},
                "steps": [
                    {
                        "step_id": "s1",
                        "skill_name": "qt.ai.data.read",
                        "inputs": {"channel": "history", "names": "close", "shares": "000300.SH"},
                    }
                ],
            },
            "execution": {
                "status": "success",
                "steps": [
                    {
                        "step_id": "s1",
                        "skill_name": "qt.ai.data.read",
                        "result": {
                            "ok": True,
                            "payload": {
                                "preview": [{"close": i} for i in range(200)],
                            },
                            "metrics": {"n_rows": 200, "close_min": 1.0, "close_max": 2.5},
                            "data_summary": {"channel": "history", "n_rows": 200},
                        },
                    }
                ],
            },
        }
        text = format_human_from_payload(
            payload,
            query="read close of 000300.SH",
            registry=build_default_registry(),
        )
        print(" human:", text)
        self.assertIn("summary: channel=history, n_rows=200", text)
        self.assertIn("close_min=1", text)
        self.assertIn("Calls: qteasy.get_history_data", text)
        self.assertNotIn("close=199", text)
        self.assertNotIn("[{'close': 0}", text)

    def test_run_live_get_trix_includes_built_in_doc(self) -> None:
        """实跑 get trix：human 含 built_in_doc 金句。"""

        print("\n[TestAiWorkbenchHuman] live run trix parameters")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            query = "show me trix strategy parameters"
            payload = assistant.run(query, response_style="raw")
            text = format_human_from_payload(payload, query=query, registry=assistant.registry)
            steps = (payload.get("execution") or {}).get("steps") or []
            result = (steps[0].get("result") if steps else {}) or {}
            doc = str((result.get("payload") or {}).get("doc") or "")
            print(" human:", text)
            print(" exec status:", (payload.get("execution") or {}).get("status"))
            print(" skill:", result.get("skill_name"))
            print(" doc head:", doc[:180])
            self.assertIn("[MODE: RUN]  executed", text)
            self.assertIn("qt.ai.strategy_meta.get", text)
            self.assertIn("trix", text.lower())
            gold = next((line.strip() for line in doc.splitlines() if line.strip()), "")
            print(" gold line:", gold)
            self.assertTrue(gold)
            self.assertIn(gold[:40], text)
            self.assertNotIn("Confirm: qteasy-ai run --plan-id", text)


if __name__ == "__main__":
    unittest.main()
