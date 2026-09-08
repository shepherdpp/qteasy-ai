# coding=utf-8
# ======================================
# File: test_ai_notebook_magic.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-26
# Desc:
# Unittest for qteasy ai notebook magic
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.notebook_magic import (
    execute_magic_command,
    parse_magic_command,
    render_magic_display,
)


class TestAiNotebookMagic(unittest.TestCase):
    """测试 Notebook 魔法命令入口。"""

    def test_parse_magic_command(self) -> None:
        """验证魔法命令参数解析。"""

        command = parse_magic_command(
            line="--mode run --raw --persist none --keep --confirm plan_abc",
            cell="列出所有内置策略",
        )
        print("\n[TestAiNotebookMagic] parsed command:", command)
        self.assertEqual(command.mode, "run")
        self.assertEqual(command.response_style, "raw")
        self.assertEqual(command.output_format, "raw")
        self.assertEqual(command.persist, "none")
        self.assertTrue(command.keep)
        self.assertEqual(command.confirm_plan_id, "plan_abc")
        self.assertFalse(command.diag)
        self.assertEqual(command.query, "列出所有内置策略")

    def test_ask_mode_is_readonly(self) -> None:
        """验证 Ask 目标态：无 execution、无 steps，答案来自 KnowledgeBase。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            plan_cache = {}
            command = parse_magic_command("--mode ask --raw explain PT vs PS")
            outcome = execute_magic_command(command, assistant=assistant, plan_cache=plan_cache)
            payload = outcome["result"]

            print("\n[TestAiNotebookMagic] ask mode:", payload.get("mode"))
            print(" ask keys:", sorted(payload.keys()) if isinstance(payload, dict) else type(payload))
            print(" ask sources:", payload.get("sources"))
            print(" ask answer:", str(payload.get("answer", ""))[:240])
            self.assertEqual(outcome["mode"], "ask")
            self.assertEqual(payload["mode"], "ask")
            self.assertNotIn("execution", payload)
            self.assertTrue(payload.get("ok"))
            self.assertIn("PT", payload.get("answer", ""))
            self.assertIn("PS", payload.get("answer", ""))
            runs = assistant.memory_store.list_runs()
            print(" ask persisted runs:", runs)
            self.assertEqual(runs, [])

    def test_confirm_flow(self) -> None:
        """验证 run -> confirm 的两阶段流程。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            plan_cache = {}

            run_command = parse_magic_command("--mode run --raw 列出所有内置策略")
            run_outcome = execute_magic_command(run_command, assistant=assistant, plan_cache=plan_cache)
            run_payload = run_outcome["result"]
            plan_id = run_outcome["plan_id"]

            print("\n[TestAiNotebookMagic] run dry status:", run_payload["execution"]["status"])
            print(" cached plan id:", plan_id)
            print(" cache size:", len(plan_cache))
            self.assertEqual(run_payload["execution"]["status"], "dry_run")
            self.assertIn(plan_id, plan_cache)

            confirm_command = parse_magic_command(f"--raw --confirm {plan_id}")
            confirm_outcome = execute_magic_command(confirm_command, assistant=assistant, plan_cache=plan_cache)
            confirm_payload = confirm_outcome["result"]

            print("[TestAiNotebookMagic] confirm status:", confirm_payload["execution"]["status"])
            print(" confirm steps:", len(confirm_payload["execution"]["steps"]))
            print(" cache size after confirm:", len(plan_cache))
            self.assertIn(confirm_payload["execution"]["status"], ["success", "partial_failed"])
            self.assertGreaterEqual(len(confirm_payload["execution"]["steps"]), 1)
            self.assertNotIn(plan_id, plan_cache)

    def test_fallback_not_approximate_substitution(self) -> None:
        """验证不支持请求走 system fallback，而非近似替代 skill。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            plan_cache = {}
            command = parse_magic_command("--mode plan --raw 下载A股数据并回测")
            outcome = execute_magic_command(command, assistant=assistant, plan_cache=plan_cache)
            payload = outcome["result"]
            first_step = payload["plan"]["steps"][0]

            print("\n[TestAiNotebookMagic] fallback first skill:", first_step["skill_name"])
            print(" fallback action:", first_step["inputs"].get("fallback_action"))
            self.assertEqual(first_step["skill_name"], "qt.ai.system.fallback")
            self.assertIn(first_step["inputs"].get("fallback_action"), ["not_supported_yet", "clarify_required", "plan_only"])

    def test_notebook_diag_uses_api_path(self) -> None:
        """验证 `%qtai --diag` 走 assistant.debug_config API。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            plan_cache = {}
            command = parse_magic_command("--raw --diag")
            outcome = execute_magic_command(command, assistant=assistant, plan_cache=plan_cache)
            payload = outcome["result"]

            print("\n[TestAiNotebookMagic] diag outcome:", payload)
            self.assertEqual(outcome["mode"], "diag")
            self.assertIn("diagnostics", payload)
            self.assertIn("provider_enabled", payload["diagnostics"])
            self.assertIn("config_sources", payload["diagnostics"])

    def test_notebook_session_id_followup(self) -> None:
        """同一 --session-id 跟进能改槽。"""

        print("\n[TestAiNotebookMagic] session-id follow-up")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            plan_cache = {}
            first = parse_magic_command("--mode plan --raw --session-id nb-s1 帮我下载日线")
            print(" parsed session_id:", first.session_id)
            self.assertEqual(first.session_id, "nb-s1")
            execute_magic_command(first, assistant=assistant, plan_cache=plan_cache)
            second = parse_magic_command("--mode plan --raw --session-id nb-s1 20240101 到 20241231")
            outcome = execute_magic_command(second, assistant=assistant, plan_cache=plan_cache)
            payload = outcome["result"]
            names = [s["skill_name"] for s in payload["plan"]["steps"]]
            print(" skills:", names, "source:", payload["plan"]["planner_trace"].get("source"))
            self.assertIn("qt.ai.data.refill_basic_equity_and_index", names)
            self.assertEqual(payload["plan"]["planner_trace"].get("source"), "session")

    def test_notebook_ask_session_zero_skill(self) -> None:
        """Ask 带 session-id 仍无 execution。"""

        print("\n[TestAiNotebookMagic] ask session-id")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            plan_cache = {}
            command = parse_magic_command("--mode ask --raw --session-id nb-ask explain PT vs PS")
            outcome = execute_magic_command(command, assistant=assistant, plan_cache=plan_cache)
            payload = outcome["result"]
            print(" mode:", payload.get("mode"), "keys:", sorted(payload.keys()) if isinstance(payload, dict) else type(payload))
            self.assertEqual(payload["mode"], "ask")
            self.assertNotIn("execution", payload)


    def test_parse_default_is_human(self) -> None:
        """无 flag 时 display 为 human，内部仍取 raw。"""

        command = parse_magic_command("--mode ask explain PT vs PS")
        print("\n[TestAiNotebookMagic] default format:", command.output_format, command.response_style)
        self.assertEqual(command.output_format, "human")
        self.assertEqual(command.response_style, "raw")
        pretty = parse_magic_command("--mode plan --pretty list built-in strategies")
        print(" pretty format:", pretty.output_format, pretty.response_style)
        self.assertEqual(pretty.output_format, "pretty")
        self.assertEqual(pretty.response_style, "user_friendly")

    def test_human_display_ask_and_plan(self) -> None:
        """Notebook human display：Ask 有答案；Plan 有确认提示。"""

        print("\n[TestAiNotebookMagic] human display")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            plan_cache = {}
            ask_cmd = parse_magic_command("--mode ask explain PT vs PS")
            ask_out = execute_magic_command(ask_cmd, assistant=assistant, plan_cache=plan_cache)
            ask_text = render_magic_display(
                ask_out["mode"],
                ask_out["result"],
                output_format=ask_cmd.output_format,
                query=ask_cmd.query,
                assistant=assistant,
            )
            print(" ask display:", ask_text[:400])
            self.assertIn("[MODE: ASK]", ask_text)
            self.assertIn("PT", ask_text)
            self.assertNotIn("### Python Code", ask_text)

            plan_cmd = parse_magic_command("--mode plan list built-in strategies")
            plan_out = execute_magic_command(plan_cmd, assistant=assistant, plan_cache=plan_cache)
            hint = str(plan_out.get("confirm_hint") or "")
            plan_text = render_magic_display(
                plan_out["mode"],
                plan_out["result"],
                output_format=plan_cmd.output_format,
                confirm_hint=hint,
                query=plan_cmd.query,
                assistant=assistant,
            )
            print(" plan display:", plan_text[:400])
            self.assertIn("qt.ai.strategy_meta.list", plan_text)
            self.assertIn("Calls: qteasy.built_in_list", plan_text)
            self.assertIn("Job:", plan_text)
            self.assertNotIn("# ToolPlan", plan_text)
            self.assertIn("Confirm: qteasy-ai run --plan-id", plan_text)


if __name__ == "__main__":
    unittest.main()

