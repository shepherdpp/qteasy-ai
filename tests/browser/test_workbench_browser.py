# coding=utf-8
# ======================================
# File: test_workbench_browser.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-03
# Desc:
# 用 Playwright 点工作台：栏宽、主题、Plan/Ask、改字、Stop 与 Background。
# 不进入 A1 的 test_ai_*.py。运行：
#   python -m unittest discover -s tests/browser -p 'test_*.py' -v
# ======================================

"""工作台浏览器点击测试。"""

from __future__ import annotations

import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

from harness import HOLD_QUERY, WorkbenchBrowserCase

_PLAN_TIMEOUT_MS = 60000
_NEAR = 2.0
_DRAG = 8.0


class TestWorkbenchBrowser(WorkbenchBrowserCase):
    """壳、对话和运行控制。"""

    def _wait_macd_plan(self) -> None:
        """等改写后的 plan 卡出现，而不是气泡先被本地改掉的那一帧。"""

        self.page.wait_for_function(
            """() => {
              const confirm = document.querySelector('#btn-confirm');
              if (!confirm) return false;
              const elapsed = document.querySelector('#busy-elapsed');
              if (elapsed && elapsed.textContent.includes('Planning')) return false;
              const nodes = [...document.querySelectorAll('.bubble-text')].map((n) => n.textContent || '');
              return nodes.some((t) => t.includes('macd')) && !nodes.some((t) => t.includes('list built-in'));
            }""",
            timeout=_PLAN_TIMEOUT_MS,
        )

    def test_badges_default_plan(self) -> None:
        """打开页面：默认 Plan，菜单里有 Ask / Plan / Agent。"""

        print("\n[TestWorkbenchBrowser] badges default Plan")
        badge = self.page.locator("#composer-mode").inner_text()
        print(" badge:", badge)
        self.assertTrue(badge.strip().startswith("Plan"))
        self.page.click("#composer-mode")
        menu = self.page.locator("#mode-menu")
        labels = [text.strip() for text in menu.locator("button").all_inner_texts()]
        print(" menu:", labels)
        self.assertEqual(labels, ["Ask", "Plan", "Agent"])

    def test_fold_sessions_widens_chat_only(self) -> None:
        """折叠 Sessions 只加宽对话栏。"""

        print("\n[TestWorkbenchBrowser] fold sessions")
        chat = self.width_of("#chat-col")
        artifact = self.width_of("#artifact-col")
        workspace = self.width_of("#sidebar-col")
        print(" before:", chat, artifact, workspace)
        self.page.click("#btn-toggle-rail")
        chat_folded = self.width_of("#chat-col")
        artifact_folded = self.width_of("#artifact-col")
        workspace_folded = self.width_of("#sidebar-col")
        print(" folded:", chat_folded, artifact_folded, workspace_folded)
        self.assertGreater(chat_folded, chat + 50)
        self.assertAlmostEqual(artifact_folded, artifact, delta=_NEAR)
        self.assertAlmostEqual(workspace_folded, workspace, delta=_NEAR)
        self.page.click("#btn-toggle-rail")
        print(" restored chat:", self.width_of("#chat-col"))
        self.assertAlmostEqual(self.width_of("#chat-col"), chat, delta=_NEAR)
        self.assertAlmostEqual(self.width_of("#artifact-col"), artifact, delta=_NEAR)

    def test_fold_workspace_widens_artifacts_flush_right(self) -> None:
        """折叠 Workspace 只加宽 Artifacts，且右缘仍贴着布局。"""

        print("\n[TestWorkbenchBrowser] fold workspace")
        chat = self.width_of("#chat-col")
        artifact = self.width_of("#artifact-col")
        print(" before:", chat, artifact)
        self.page.click("#btn-collapse-workspace")
        chat_folded = self.width_of("#chat-col")
        artifact_folded = self.width_of("#artifact-col")
        sidebar_right = self.right_of("#sidebar-col")
        layout_right = self.right_of("#layout")
        print(" folded:", chat_folded, artifact_folded, "right", sidebar_right, layout_right)
        self.assertAlmostEqual(chat_folded, chat, delta=_NEAR)
        self.assertGreater(artifact_folded, artifact + 50)
        self.assertAlmostEqual(sidebar_right, layout_right, delta=_NEAR)
        self.page.click("#btn-collapse-workspace")
        print(" restored artifact:", self.width_of("#artifact-col"))
        self.assertAlmostEqual(self.width_of("#chat-col"), chat, delta=_NEAR)
        self.assertAlmostEqual(self.width_of("#artifact-col"), artifact, delta=_NEAR)

    def test_drag_splitter_persists(self) -> None:
        """拖动分割线后刷新仍在；Settings 里可切换 Dark / Light。"""

        print("\n[TestWorkbenchBrowser] drag splitter")
        chat = self.width_of("#chat-col")
        artifact = self.width_of("#artifact-col")
        handle = self.page.locator("#col-splitter").bounding_box()
        self.assertIsNotNone(handle)
        assert handle is not None
        start_x = float(handle["x"]) + float(handle["width"]) / 2
        start_y = float(handle["y"]) + float(handle["height"]) / 2
        self.page.mouse.move(start_x, start_y)
        self.page.mouse.down()
        self.page.mouse.move(start_x + 120, start_y, steps=8)
        self.page.mouse.up()
        chat_dragged = self.width_of("#chat-col")
        artifact_dragged = self.width_of("#artifact-col")
        print(" dragged:", chat_dragged, artifact_dragged, "was", chat, artifact)
        self.assertGreater(chat_dragged, chat + 50)
        self.assertLess(artifact_dragged, artifact - 50)
        self.assertAlmostEqual(chat_dragged + artifact_dragged, chat + artifact, delta=_DRAG)
        self.page.reload(wait_until="domcontentloaded")
        self.page.wait_for_selector("#composer-mode")
        self.page.evaluate("() => window.dispatchEvent(new Event('resize'))")
        print(" reloaded:", self.width_of("#chat-col"), self.width_of("#artifact-col"))
        self.assertAlmostEqual(self.width_of("#chat-col"), chat_dragged, delta=_DRAG)
        self.assertAlmostEqual(self.width_of("#artifact-col"), artifact_dragged, delta=_DRAG)

        print("[TestWorkbenchBrowser] theme dark / light")
        self.page.click("#btn-settings")
        self.page.wait_for_selector("#btn-theme-light")
        self.page.click("#btn-theme-light")
        light = self.page.evaluate("() => document.documentElement.dataset.theme")
        stored_light = self.page.evaluate("() => localStorage.getItem('qteasy-ai.theme')")
        print(" light:", light, stored_light)
        self.assertEqual(light, "light")
        self.assertEqual(stored_light, "light")
        self.page.click("#btn-theme-dark")
        dark = self.page.evaluate("() => document.documentElement.dataset.theme")
        stored_dark = self.page.evaluate("() => localStorage.getItem('qteasy-ai.theme')")
        print(" dark:", dark, stored_dark)
        self.assertEqual(dark, "dark")
        self.assertEqual(stored_dark, "dark")

    def test_plan_list_strategies_then_confirm(self) -> None:
        """Plan 发送 list，Confirm 之后出现 run。"""

        print("\n[TestWorkbenchBrowser] plan list strategies then confirm")
        self.send("list built-in strategies")
        self.page.wait_for_selector("#btn-confirm", timeout=_PLAN_TIMEOUT_MS)
        roles = self.page.locator("#chat-log .msg-role").all_inner_texts()
        print(" before confirm roles:", roles)
        self.assertNotIn("Result", roles)
        self.assertEqual(self.harness.session_status(self.session_id()), 200)
        self.page.click("#btn-confirm")
        self.page.wait_for_function(
            "() => /run_[0-9a-f]{6,}/.test(document.body.innerText)",
            timeout=_PLAN_TIMEOUT_MS,
        )
        body = self.page.locator("body").inner_text()
        print(" after confirm has run:", "run_" in body)
        self.assertIn("run_", body)

    def test_unbounded_refill_skip_ends_failed(self) -> None:
        """无界下载出现澄清；Skip 后失败结束，不执行。"""

        print("\n[TestWorkbenchBrowser] unbounded refill skip")
        self.send("download A-share daily data to local datasource")
        self.page.wait_for_selector("[data-testid='clarification-form']", timeout=_PLAN_TIMEOUT_MS)
        self.assertTrue(self.page.locator("#btn-clarify-skip").is_visible())
        self.page.click("#btn-clarify-skip")
        self.page.wait_for_selector("text=Clarification skipped. This request ended.", timeout=_PLAN_TIMEOUT_MS)
        body = self.page.locator("#chat-log").inner_text()
        print(" after skip:", body[:400])
        self.assertIn("Clarification skipped. This request ended.", body)
        self.assertEqual(self.page.locator("#btn-confirm").count(), 0)
        self.assertNotIn("refill", body.lower())

    def test_ask_shows_source_without_confirm(self) -> None:
        """Ask 命中 KB，没有 Confirm。"""

        print("\n[TestWorkbenchBrowser] ask what is qteasy")
        self.page.click("#composer-mode")
        self.page.locator('#mode-menu button[data-mode="ask"]').click()
        badge = self.page.locator("#composer-mode").inner_text()
        print(" badge:", badge)
        self.assertTrue(badge.strip().startswith("Ask"))
        self.send("what is qteasy")
        self.page.wait_for_selector("text=what_is_qteasy", timeout=_PLAN_TIMEOUT_MS)
        body = self.page.locator("#chat-log").inner_text()
        print(" ask body:", body[:400])
        self.assertIn("Sources:", body)
        self.assertIn("what_is_qteasy", body)
        self.assertEqual(self.page.locator("#btn-confirm").count(), 0)

    def test_edit_unexecuted_message_sends(self) -> None:
        """未执行的最近一句改字后直接 Send，不弹确认。"""

        print("\n[TestWorkbenchBrowser] edit unexecuted message")
        self.dialog_mode = "dismiss"
        self.send("list built-in strategies")
        self.page.wait_for_selector("#btn-confirm", timeout=_PLAN_TIMEOUT_MS)
        self.page.locator(".msg.user .bubble").hover()
        self.page.locator(".bubble-edit").click()
        label = self.page.locator("#btn-rewind-submit").inner_text()
        print(" submit label:", label)
        self.assertEqual(label.strip(), "Send")
        self.dialogs.clear()
        self.page.fill("#rewind-text", "show me macd strategy parameters")
        self.page.click("#btn-rewind-submit")
        self._wait_macd_plan()
        print(" dialogs:", self.dialogs)
        print(" bubbles:", self.page.locator(".bubble-text").all_inner_texts())
        self.assertEqual(self.dialogs, [])
        self.assertTrue(self.page.locator("#btn-confirm").is_visible())

    def test_edit_cancel_keeps_original_text(self) -> None:
        """改字后点 Cancel，气泡仍是原句。"""

        print("\n[TestWorkbenchBrowser] edit cancel")
        self.send("list built-in strategies")
        self.page.wait_for_selector("#btn-confirm", timeout=_PLAN_TIMEOUT_MS)
        self.page.locator(".msg.user .bubble").hover()
        self.page.locator(".bubble-edit").click()
        self.page.fill("#rewind-text", "show me macd strategy parameters")
        self.page.click("#btn-rewind-cancel")
        bubbles = self.page.locator(".bubble-text").all_inner_texts()
        print(" bubbles:", bubbles)
        self.assertEqual(self.page.locator("#rewind-text").count(), 0)
        self.assertTrue(any("list built-in strategies" in text for text in bubbles))
        self.assertFalse(any("macd" in text for text in bubbles))
        self.assertTrue(self.page.locator("#btn-confirm").is_visible())

    def test_edit_executed_message_discard_resend(self) -> None:
        """最近一条已执行的句子用 Discard and resend，不弹确认。"""

        print("\n[TestWorkbenchBrowser] edit executed message")
        self.dialog_mode = "dismiss"
        self.send("list built-in strategies")
        self.page.wait_for_selector("#btn-confirm", timeout=_PLAN_TIMEOUT_MS)
        self.page.click("#btn-confirm")
        self.page.wait_for_selector("#chat-log .msg-role >> text=Result", timeout=_PLAN_TIMEOUT_MS)
        self.page.locator(".msg.user .bubble").hover()
        self.page.locator(".bubble-edit").click()
        label = self.page.locator("#btn-rewind-submit").inner_text()
        print(" submit label:", label)
        self.assertEqual(label.strip(), "Discard and resend")
        self.dialogs.clear()
        self.page.fill("#rewind-text", "show me macd strategy parameters")
        self.page.click("#btn-rewind-submit")
        self._wait_macd_plan()
        chat = self.page.locator("#chat-log").inner_text()
        print(" dialogs:", self.dialogs)
        print(" chat head:", chat[:300])
        self.assertEqual(self.dialogs, [])
        self.assertIn("Plan ready", chat)
        self.assertNotIn("list built-in strategies", chat)

    def test_cancel_plan_does_not_run(self) -> None:
        """Cancel 关掉计划卡，不产生执行结果。"""

        print("\n[TestWorkbenchBrowser] cancel plan")
        self.send("list built-in strategies")
        self.page.wait_for_selector("#btn-confirm", timeout=_PLAN_TIMEOUT_MS)
        self.page.click("#btn-cancel")
        self.page.wait_for_selector("text=Plan card dismissed")
        body = self.page.locator("#chat-log").inner_text()
        print(" after cancel:", body[:300])
        self.assertIn("Plan card dismissed", body)
        self.assertEqual(self.page.locator("#btn-confirm").count(), 0)
        self.assertEqual(self.page.locator("#chat-log .msg-role", has_text="Result").count(), 0)

    def test_rename_then_delete_session(self) -> None:
        """改名后删除。session 文件消失，runs/ 还在。"""

        print("\n[TestWorkbenchBrowser] rename then delete")
        self.send("list built-in strategies")
        self.page.wait_for_selector("#btn-confirm", timeout=_PLAN_TIMEOUT_MS)
        session_id = self.session_id()
        self.assertTrue(self.harness.session_file_exists(session_id))
        runs_before = self.harness.run_names()
        print(" session:", session_id, "runs:", runs_before)
        self.assertTrue(runs_before)
        row = self.page.locator(f'[data-session-id="{session_id}"]')
        row.hover()
        row.locator("[data-session-rename]").click()
        self.page.fill(".session-rename", "Browser drill")
        self.page.press(".session-rename", "Enter")
        self.page.wait_for_function(
            "() => document.querySelector('#session-title').textContent.includes('Browser drill')",
            timeout=10000,
        )
        title = self.page.locator("#session-title").inner_text()
        print(" title:", title)
        self.assertIn("Browser drill", title)
        row.hover()
        row.locator("[data-session-delete]").click()
        self.page.wait_for_function(
            "() => !document.body.innerText.includes('Browser drill')",
            timeout=10000,
        )
        status = self.harness.session_status(session_id)
        file_exists = self.harness.session_file_exists(session_id)
        runs_after = self.harness.run_names()
        print(" GET:", status, "file:", file_exists, "runs after:", runs_after)
        self.assertFalse(file_exists)
        self.assertEqual(runs_after, runs_before)

    def test_background_unlocks_composer(self) -> None:
        """Background 解开输入框，进度条还在。"""

        print("\n[TestWorkbenchBrowser] background")
        self.send(HOLD_QUERY)
        self.page.wait_for_selector("#btn-confirm", timeout=_PLAN_TIMEOUT_MS)
        self.page.click("#btn-confirm")
        self.page.wait_for_selector("#btn-background-run", timeout=20000)
        working = self.page.locator("#busy-elapsed").inner_text()
        print(" working:", working)
        self.assertIn("Working", working)
        self.page.click("#btn-background-run")
        self.page.wait_for_function(
            "() => (document.querySelector('#busy-elapsed') || {}).textContent.includes('Background')",
            timeout=10000,
        )
        clock = self.page.locator("#busy-elapsed").inner_text()
        bars = self.page.locator("#busy-msg .progress-indet, #busy-msg .progress-det").count()
        print(" background:", clock, "bars:", bars, "input enabled:", self.page.locator("#query-input").is_enabled())
        self.assertIn("Background", clock)
        self.assertGreater(bars, 0)
        self.assertTrue(self.page.locator("#query-input").is_enabled())
        self.assertTrue(self.page.locator("#btn-send").is_enabled())

    def test_stop_confirms_and_clears_run(self) -> None:
        """Stop 经过确认框，hold 因取消结束。"""

        print("\n[TestWorkbenchBrowser] stop")
        self.send(HOLD_QUERY)
        self.page.wait_for_selector("#btn-confirm", timeout=_PLAN_TIMEOUT_MS)
        self.page.click("#btn-confirm")
        self.page.wait_for_selector("#btn-stop-watch", timeout=20000)
        working = self.page.locator("#busy-elapsed").inner_text()
        print(" working:", working)
        self.assertIn("Working", working)
        self.dialogs.clear()
        self.page.click("#btn-stop-watch")
        self.page.locator("#busy-msg").wait_for(state="hidden", timeout=15000)
        print(" dialogs:", self.dialogs)
        print(" input enabled:", self.page.locator("#query-input").is_enabled())
        self.assertTrue(any(message.startswith("Stop this run?") for message in self.dialogs))
        self.assertTrue(self.page.locator("#query-input").is_enabled())
        self.assertTrue(self.harness.hold.finished.wait(timeout=5))
        print(" hold reason:", self.harness.hold.reason)
        self.assertEqual(self.harness.hold.reason, "cancelled")
