# coding=utf-8
# ======================================
# File: test_ai_workbench_tui.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-07
# Desc:
# Unittest for minimal Textual TUI (G.6)
# ======================================

import asyncio
import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.workbench.mapper import map_assistant_payload
from qteasy_ai.workbench.tui_app import WorkbenchTui


class TestAiWorkbenchTui(unittest.TestCase):
    """G.6：mode、Ask 无执行确认、Plan 确认卡、无 Artifact Tab。"""

    def _assistant(self, temp_dir: str) -> QteasyAssistant:
        """临时助手。"""

        return QteasyAssistant(
            memory_store=MemoryStore(base_dir=temp_dir),
            registry=build_default_registry(),
        )

    def _run(self, coro):
        """运行 async 测试体。"""

        return asyncio.run(coro)

    def test_mode_badge_on_start(self) -> None:
        """启动后可见 mode 标签。"""

        print("\n[TestAiWorkbenchTui] mode badge")

        async def _body() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                app = WorkbenchTui(self._assistant(temp_dir), session_id="tui-mode")
                async with app.run_test() as pilot:
                    badge = str(pilot.app.query_one("#mode-badge").render())
                    print(" badge:", badge)
                    self.assertIn("Mode:", badge)
                    self.assertIn("PLAN", badge.upper())

        self._run(_body())

    def test_ask_dto_has_no_confirmable_card(self) -> None:
        """Ask DTO：对话有问答，确认卡空。"""

        print("\n[TestAiWorkbenchTui] ask dto")

        async def _body() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                assistant = self._assistant(temp_dir)
                payload = assistant.ask("什么是 qteasy", response_style="raw")
                state = map_assistant_payload(payload, query="什么是 qteasy")
                app = WorkbenchTui(assistant, session_id="tui-ask")
                async with app.run_test() as pilot:
                    app.apply_dto(state)
                    await pilot.pause()
                    chat = str(pilot.app.query_one("#chat-log").render())
                    card = str(pilot.app.query_one("#plan-card").render())
                    print(" chat:", chat[:200])
                    print(" card:", card)
                    self.assertIn("ask_text", chat)
                    self.assertEqual(card.strip(), "")

        self._run(_body())

    def test_plan_confirm_runs_plan_id(self) -> None:
        """Plan 确认卡列出 skill + side-effects；确认触发 run_plan。"""

        print("\n[TestAiWorkbenchTui] plan confirm")

        async def _body() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                assistant = self._assistant(temp_dir)
                payload = assistant.plan("list built-in strategies", response_style="raw")
                state = map_assistant_payload(payload, query="list built-in strategies")
                app = WorkbenchTui(assistant, session_id="tui-plan")
                async with app.run_test() as pilot:
                    app.apply_dto(state)
                    await pilot.pause()
                    card = str(pilot.app.query_one("#plan-card").render())
                    print(" card:", card)
                    self.assertIn("qt.ai.strategy_meta.list", card)
                    self.assertIn("side-effects", card)
                    app.action_confirm_plan()
                    await pilot.pause()
                    steps = str(pilot.app.query_one("#steps").render())
                    print(" steps:", steps)
                    self.assertIn("✓", steps)
                    statuses = []
                    for run_id in assistant.memory_store.list_runs():
                        rec = assistant.memory_store.load_run(run_id)
                        statuses.append((rec.get("execution") or {}).get("status"))
                    print(" statuses:", statuses)
                    self.assertIn("success", statuses)

        self._run(_body())

    def test_no_artifact_tab_widget(self) -> None:
        """界面树无 Artifact Tab 控件。"""

        print("\n[TestAiWorkbenchTui] no artifact tabs")

        async def _body() -> None:
            from textual.css.query import NoMatches

            with tempfile.TemporaryDirectory() as temp_dir:
                app = WorkbenchTui(self._assistant(temp_dir))
                async with app.run_test() as pilot:
                    ids = [widget.id for widget in pilot.app.query("*") if widget.id]
                    print(" widget ids:", ids)
                    self.assertNotIn("artifact-tabs", ids)
                    self.assertNotIn("artifact-col", ids)
                    with self.assertRaises(NoMatches):
                        pilot.app.query_one("#artifact-tabs")

        self._run(_body())

    def test_cancel_does_not_execute(self) -> None:
        """取消确认不写 execute success。"""

        print("\n[TestAiWorkbenchTui] cancel")

        async def _body() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                assistant = self._assistant(temp_dir)
                payload = assistant.plan("list built-in strategies", response_style="raw")
                state = map_assistant_payload(payload, query="list built-in strategies")
                app = WorkbenchTui(assistant, session_id="tui-cancel")
                async with app.run_test() as pilot:
                    app.apply_dto(state)
                    await pilot.pause()
                    app.action_cancel_plan()
                    await pilot.pause()
                    statuses = [
                        (assistant.memory_store.load_run(run_id).get("execution") or {}).get("status")
                        for run_id in assistant.memory_store.list_runs()
                    ]
                    print(" statuses after cancel:", statuses)
                    self.assertTrue(statuses)
                    self.assertTrue(all(item == "dry_run" for item in statuses))

        self._run(_body())


if __name__ == "__main__":
    unittest.main()
