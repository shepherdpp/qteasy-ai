# coding=utf-8
# ======================================
# File: test_ai_cli_notebook_entry.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-15
# Desc:
# Unittest for qteasy ai notebook and cli entry
# ======================================

import json
import os
import subprocess
import sys
import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore


class TestAiCliNotebookEntry(unittest.TestCase):
    """测试 Notebook/CLI 两入口可用。"""

    def test_notebook_assistant_plan_and_run(self) -> None:
        """验证 notebook 风格入口结构化输出。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            assistant = QteasyAssistant(registry=build_default_registry(), memory_store=store)
            plan_payload = assistant.plan("list built-in strategies", response_style="raw")
            run_payload = assistant.run("list built-in strategies", response_style="raw")

            print("\n[TestAiCliNotebookEntry] plan status:", plan_payload["execution"]["status"])
            print(" run status:", run_payload["execution"]["status"])
            print(" run steps:", len(run_payload["execution"]["steps"]))

            self.assertEqual(plan_payload["execution"]["status"], "dry_run")
            self.assertIn(run_payload["execution"]["status"], ["success", "partial_failed"])
            self.assertGreaterEqual(len(run_payload["execution"]["steps"]), 1)

    def test_cli_plan_command(self) -> None:
        """验证 CLI plan 子命令可执行。"""

        cmd = [sys.executable, "-m", "qteasy_ai.cli", "plan", "list built-in strategies"]
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
        payload = json.loads(completed.stdout)

        print("\n[TestAiCliNotebookEntry] cli stdout:", completed.stdout[:240])
        print(" cli status:", payload["execution"]["status"])

        self.assertEqual(payload["execution"]["status"], "dry_run")
        self.assertIn("plan_id", payload["plan"])

    def test_cli_plan_command_pretty(self) -> None:
        """验证 CLI pretty 模式可输出用户友好结构。"""

        cmd = [sys.executable, "-m", "qteasy_ai.cli", "plan", "list built-in strategies", "--pretty"]
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
        payload = json.loads(completed.stdout)

        print("\n[TestAiCliNotebookEntry] cli pretty stdout:", completed.stdout[:240])
        self.assertIn("narrative", payload)
        self.assertIn("python_code", payload)
        self.assertIn("result_preview", payload)
        self.assertIn("raw", payload)

    def test_cli_provider_check_diagnostics(self) -> None:
        """验证 provider-check 返回配置诊断信息。"""

        env = dict(os.environ)
        env["QTEASY_AI_MODEL"] = "deepseek-chat"
        env["QTEASY_AI_API_KEY"] = "test_key"
        env["QTEASY_AI_BASE_URL"] = "https://api.deepseek.com/v1"
        env["QTEASY_AI_TIMEOUT"] = "42"

        cmd = [sys.executable, "-m", "qteasy_ai.cli", "provider-check"]
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
        payload = json.loads(completed.stdout)

        print("\n[TestAiCliNotebookEntry] provider-check:", payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["provider"], "openai_compatible")
        self.assertEqual(payload["mode"], "cloud_llm")
        self.assertEqual(payload["model"], "deepseek-chat")
        self.assertEqual(payload["base_url"], "https://api.deepseek.com/v1")
        self.assertEqual(payload["timeout"], 42)
        self.assertTrue(payload["api_key_present"])
        self.assertIn("config_sources", payload)

    def test_cli_provider_check_rule_mode(self) -> None:
        """验证 provider-check 在无模型配置时为规则模式。"""

        env = dict(os.environ)
        env.pop("QTEASY_AI_MODEL", None)
        env.pop("QTEASY_AI_API_KEY", None)
        env.pop("QTEASY_AI_BASE_URL", None)
        env.pop("QTEASY_AI_TIMEOUT", None)

        cmd = [sys.executable, "-m", "qteasy_ai.cli", "provider-check"]
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
        payload = json.loads(completed.stdout)

        print("\n[TestAiCliNotebookEntry] provider-check rule mode:", payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["mode"], "rule")

    def test_cli_provider_check_local_mode(self) -> None:
        """验证 provider-check 在本地地址时识别 local_llm。"""

        env = dict(os.environ)
        env["QTEASY_AI_MODEL"] = "llama3.1:8b"
        env["QTEASY_AI_API_KEY"] = "ollama"
        env["QTEASY_AI_BASE_URL"] = "http://127.0.0.1:11434/v1"
        env["QTEASY_AI_TIMEOUT"] = "30"

        cmd = [sys.executable, "-m", "qteasy_ai.cli", "provider-check"]
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
        payload = json.loads(completed.stdout)

        print("\n[TestAiCliNotebookEntry] provider-check local mode:", payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], "local_llm")

    def test_cli_ask_command_target_state(self) -> None:
        """验证 CLI ask 返回 Ask 目标态，不含 execution。"""

        cmd = [sys.executable, "-m", "qteasy_ai.cli", "ask", "explain PT vs PS"]
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
        payload = json.loads(completed.stdout)
        print("\n[TestAiCliNotebookEntry] cli ask:", payload.get("mode"), payload.get("sources"))
        print(" answer:", str(payload.get("answer", ""))[:240])
        self.assertEqual(payload["mode"], "ask")
        self.assertNotIn("execution", payload)
        self.assertIn("PT", payload.get("answer", ""))
        self.assertIn("PS", payload.get("answer", ""))

    def test_cli_preview_and_plan_preview_alias(self) -> None:
        """验证 preview 与 plan --preview 走出 strategy_meta.list。"""

        for cmd in (
            [sys.executable, "-m", "qteasy_ai.cli", "preview", "list built-in strategies"],
            [sys.executable, "-m", "qteasy_ai.cli", "plan", "list built-in strategies", "--preview"],
        ):
            completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
            payload = json.loads(completed.stdout)
            print("\n[TestAiCliNotebookEntry] preview cmd:", cmd[-2:], "status:", payload["execution"]["status"])
            print(" skills:", [s["skill_name"] for s in payload["plan"]["steps"]])
            self.assertEqual(payload["execution"]["status"], "dry_run")
            self.assertEqual(payload["plan"]["steps"][0]["skill_name"], "qt.ai.strategy_meta.list")

    def test_run_plan_id_skips_hybrid(self) -> None:
        """run_plan 从 runs 加载已审阅 plan，不再调用 build_plan。"""

        print("\n[TestAiCliNotebookEntry] run_plan --plan-id")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            assistant = QteasyAssistant(registry=build_default_registry(), memory_store=store)
            planned = assistant.plan("list built-in strategies", response_style="raw")
            plan_id = planned["plan"]["plan_id"]
            print(" saved plan_id:", plan_id)
            calls = {"n": 0}
            original = assistant.planner.build_plan

            def wrapped(query, *, mode="plan"):
                calls["n"] += 1
                return original(query, mode=mode)

            assistant.planner.build_plan = wrapped  # type: ignore[method-assign]
            ran = assistant.run_plan(plan_id, response_style="raw")
            print(" hybrid calls:", calls["n"], "exec status:", ran["execution"]["status"])
            self.assertEqual(calls["n"], 0)
            self.assertIn(ran["execution"]["status"], ["success", "partial_failed"])
            self.assertGreaterEqual(len(ran["execution"]["steps"]), 1)

    def test_cli_run_plan_id_missing_english_error(self) -> None:
        """缺 plan 记录 → 英文错误，不改走 query run。"""

        cmd = [sys.executable, "-m", "qteasy_ai.cli", "run", "--plan-id", "plan_does_not_exist"]
        completed = subprocess.run(cmd, capture_output=True, text=True)
        payload = json.loads(completed.stdout)
        print("\n[TestAiCliNotebookEntry] missing plan_id:", payload)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(payload["error"]["code"], "PLAN_ID_NOT_FOUND")
        self.assertIn("plan_id", payload["error"]["message"].lower())

    def test_cli_same_session_id_fills_slots(self) -> None:
        """同一 --session-id 第二次跟进能改槽；不同 id 不继承。"""

        print("\n[TestAiCliNotebookEntry] cli session-id follow-up")
        with tempfile.TemporaryDirectory() as temp_dir:
            env = dict(os.environ)
            env["QTEASY_AI_HOME"] = temp_dir
            env.pop("QTEASY_AI_MODEL", None)
            cmd1 = [
                sys.executable,
                "-m",
                "qteasy_ai.cli",
                "plan",
                "帮我下载日线",
                "--session-id",
                "cli-s1",
            ]
            first = subprocess.run(cmd1, check=True, capture_output=True, text=True, env=env)
            p1 = json.loads(first.stdout)
            print(" first action:", p1["plan"]["steps"][0]["inputs"].get("fallback_action"))
            cmd2 = [
                sys.executable,
                "-m",
                "qteasy_ai.cli",
                "plan",
                "20240101 到 20241231",
                "--session-id",
                "cli-s1",
            ]
            second = subprocess.run(cmd2, check=True, capture_output=True, text=True, env=env)
            p2 = json.loads(second.stdout)
            names = [s["skill_name"] for s in p2["plan"]["steps"]]
            print(" second skills:", names, "source:", p2["plan"]["planner_trace"].get("source"))
            self.assertIn("qt.ai.data.refill_basic_equity_and_index", names)
            self.assertEqual(p2["plan"]["planner_trace"].get("source"), "session")

            other = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "qteasy_ai.cli",
                    "plan",
                    "20240101 到 20241231",
                    "--session-id",
                    "cli-other",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            p3 = json.loads(other.stdout)
            print(" other job:", p3["plan"]["planner_trace"].get("intent_job"), p3["plan"]["steps"][0]["skill_name"])
            self.assertNotEqual(p3["plan"]["planner_trace"].get("source"), "session")

    def test_cli_ask_session_id_zero_skill(self) -> None:
        """Ask --session-id 可带短槽摘要，仍无 execution.steps。"""

        print("\n[TestAiCliNotebookEntry] cli ask session-id")
        with tempfile.TemporaryDirectory() as temp_dir:
            env = dict(os.environ)
            env["QTEASY_AI_HOME"] = temp_dir
            env.pop("QTEASY_AI_MODEL", None)
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "qteasy_ai.cli",
                    "plan",
                    "download daily data from 20180101 to 20231231",
                    "--session-id",
                    "cli-ask",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "qteasy_ai.cli",
                    "ask",
                    "explain PT vs PS",
                    "--session-id",
                    "cli-ask",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            payload = json.loads(completed.stdout)
            print(" ask keys:", sorted(payload.keys()))
            print(" sources:", payload.get("sources"))
            self.assertEqual(payload["mode"], "ask")
            self.assertNotIn("execution", payload)
            self.assertNotIn("steps", payload)
            self.assertIn("pt_ps_vs", payload.get("sources") or [])

    def test_cli_parser_has_serve_and_tui(self) -> None:
        """CLI 仍保留 ask/plan/run，并增加 serve/tui。"""

        print("\n[TestAiCliNotebookEntry] workbench subcommands")
        from qteasy_ai.cli import build_parser

        parser = build_parser()
        serve = parser.parse_args(["serve", "--port", "9000"])
        tui = parser.parse_args(["tui", "--session-id", "demo"])
        print(" serve:", serve.command, serve.port)
        print(" tui:", tui.command, tui.session_id)
        self.assertEqual(serve.command, "serve")
        self.assertEqual(int(serve.port), 9000)
        self.assertEqual(tui.command, "tui")
        self.assertEqual(tui.session_id, "demo")


if __name__ == "__main__":
    unittest.main()
