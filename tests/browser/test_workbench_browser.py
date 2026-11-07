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

import json
import sys
import time
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

    def rename_box(self, session_id: str, name: str, *, submit: str = "") -> None:
        """在改名框里逐字输入。

        ``fill`` 先选中框内文字，再把新字插入当前焦点。焦点不在框上时，
        空会话框里仍是 ``New session``，回车会把这个占位词提交成空名字。
        """

        row = self.page.locator(f'[data-session-id="{session_id}"]')
        row.hover()
        row.locator("[data-session-rename]").click()
        box = self.page.locator(".session-rename")
        box.press_sequentially(name)
        if submit:
            box.press(submit)

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
        """无界下载出现澄清；End this request 两步确认后失败结束，不执行。"""

        print("\n[TestWorkbenchBrowser] unbounded refill end this request")
        self.send("download A-share daily data to local datasource")
        self.page.wait_for_selector("[data-testid='clarification-form']", timeout=_PLAN_TIMEOUT_MS)
        self.assertTrue(self.page.locator("#btn-clarify-end").is_visible())
        self.page.click("#btn-clarify-end")
        self.page.wait_for_selector("#btn-clarify-end-confirm", timeout=_PLAN_TIMEOUT_MS)
        self.page.click("#btn-clarify-end-confirm")
        self.page.wait_for_selector("text=Clarification skipped. This request ended.", timeout=_PLAN_TIMEOUT_MS)
        body = self.page.locator("#chat-log").inner_text()
        print(" after end:", body[:400])
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

    def test_rename_empty_session_before_first_message(self) -> None:
        """空会话先改名再发首条：自定义名钉死，不被首条全文覆盖。"""

        print("\n[TestWorkbenchBrowser] rename empty session before first message")
        custom = "Pre-named empty"
        query = "list built-in strategies"
        session_id = self.session_id()
        row = self.page.locator(f'[data-session-id="{session_id}"]')
        self.rename_box(session_id, custom, submit="Enter")
        self.page.wait_for_function(
            "() => document.querySelector('#session-title').textContent.includes('Pre-named empty')",
            timeout=10000,
        )
        title_before = self.page.locator("#session-title").inner_text()
        print(" title before send:", title_before)
        self.assertIn(custom, title_before)
        self.send(query)
        self.page.wait_for_selector("#btn-confirm", timeout=_PLAN_TIMEOUT_MS)
        self.page.wait_for_function(
            "() => document.querySelector('#session-title').textContent.includes('Pre-named empty')",
            timeout=10000,
        )
        title = self.page.locator("#session-title").inner_text()
        sid = row.locator(".sid").inner_text()
        print(" title after send:", title, "sid:", sid)
        self.assertIn(custom, title)
        self.assertEqual(sid.strip(), custom)
        self.assertNotEqual(sid.strip(), query)
        self.assertTrue(self.harness.session_file_exists(session_id))

    def test_rename_then_delete_session(self) -> None:
        """改名后删除。session 文件与该会话 run 消失，无关 run 留下。"""

        print("\n[TestWorkbenchBrowser] rename then delete")
        self.send("list built-in strategies")
        self.page.wait_for_selector("#btn-confirm", timeout=_PLAN_TIMEOUT_MS)
        session_id = self.session_id()
        self.assertTrue(self.harness.session_file_exists(session_id))
        runs_before = set(self.harness.run_names())
        print(" session:", session_id, "runs:", sorted(runs_before))
        self.assertTrue(runs_before)
        other = Path(self.harness.store.runs_dir) / "unrelated-keep.json"
        other.write_text(
            '{"plan":{"plan_id":"plan-keep"},"execution":{"status":"dry_run"},'
            '"session":{"session_id":"other-session"}}',
            encoding="utf-8",
        )
        row = self.page.locator(f'[data-session-id="{session_id}"]')
        self.rename_box(session_id, "Browser drill", submit="Enter")
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
        runs_after = set(self.harness.run_names())
        print(" GET:", status, "file:", file_exists, "runs after:", sorted(runs_after))
        self.assertFalse(file_exists)
        for name in runs_before:
            self.assertNotIn(name, runs_after)
        self.assertIn("unrelated-keep.json", runs_after)

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
        send_enabled = self.page.locator("#btn-send").is_enabled()
        print(
            " background:",
            clock,
            "bars:",
            bars,
            "input enabled:",
            self.page.locator("#query-input").is_enabled(),
            "send enabled:",
            send_enabled,
        )
        self.assertIn("Background", clock)
        self.assertGreater(bars, 0)
        self.assertTrue(self.page.locator("#query-input").is_enabled())
        self.assertFalse(send_enabled)

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

    def test_attach_file_chip_and_remove(self) -> None:
        """回形针选文件后芯片出现，× 后芯片清空。"""

        print("\n[TestWorkbenchBrowser] attach file chip and remove")
        send_label = self.page.locator("#btn-send").get_attribute("aria-label")
        attach_label = self.page.locator("#btn-attach").get_attribute("aria-label")
        print(" send aria:", send_label, "attach aria:", attach_label)
        self.assertEqual(send_label, "Send")
        self.assertEqual(attach_label, "Attach")
        sample = Path(self.harness.temp_dir.name) / "browser_note.txt"
        sample.write_text("hello attach\n", encoding="utf-8")
        print(" sample:", sample)
        self.page.set_input_files("#attach-input", str(sample))
        self.page.wait_for_selector(".attach-chip", timeout=10000)
        chip_text = self.page.locator(".attach-chip").inner_text()
        print(" chip:", chip_text)
        self.assertIn("browser_note.txt", chip_text)
        self.page.locator(".attach-chip-remove").click()
        self.page.wait_for_function(
            "() => document.querySelectorAll('.attach-chip').length === 0",
            timeout=10000,
        )
        print(" chips after remove:", self.page.locator(".attach-chip").count())
        self.assertEqual(self.page.locator(".attach-chip").count(), 0)

    def _second_session_then_back(self) -> str:
        """再建一条会话，再点回当前这条。返回新建的 id。"""

        first = self.session_id()
        self.page.click("#btn-new-session")
        self.page.wait_for_function(
            "(prev) => { const id = localStorage.getItem('qteasy-ai.session_id'); return Boolean(id) && id !== prev; }",
            arg=first,
            timeout=10000,
        )
        second = self.session_id()
        print(" second session:", second)
        self.page.locator(f'[data-session-id="{first}"]').click()
        self.page.wait_for_function(
            "(id) => localStorage.getItem('qteasy-ai.session_id') === id",
            arg=first,
            timeout=10000,
        )
        return second

    def _choose_ask(self) -> None:
        """切到 Ask。"""

        self.page.click("#composer-mode")
        self.page.locator('#mode-menu button[data-mode="ask"]').click()
        badge = self.page.locator("#composer-mode").inner_text().strip()
        print(" mode:", badge)
        self.assertTrue(badge.startswith("Ask"))

    def _hold_until(self, held: dict, timeout: float = 10.0) -> None:
        """等到拦截下的请求被页面发出。"""

        deadline = time.monotonic() + timeout
        while held.get("route") is None and time.monotonic() < deadline:
            self.page.wait_for_timeout(50)
        print(" held route:", held.get("route") is not None)
        self.assertIsNotNone(held.get("route"))

    def _fulfill_json(self, held: dict, payload: dict) -> None:
        """放行一条被拦住的请求。"""

        route = held.get("route")
        self.assertIsNotNone(route)
        held["route"] = None
        held["done"] = True
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        )

    def _drop_held(self, held: dict) -> None:
        """用例收尾时丢掉还没放行的假请求。"""

        route = held.get("route")
        if route is None or held.get("done"):
            return
        held["route"] = None
        held["done"] = True
        try:
            route.abort()
        except Exception as exc:
            print(" drop held:", type(exc).__name__, exc)

    def test_reply_dot_appears_while_rename_stays(self) -> None:
        """空闲是气泡。POST 回来时蓝点立刻出现，改名框不被提交。"""

        print("\n[TestWorkbenchBrowser] reply dot while rename stays")
        marker = "REPLY-DOT-7f3a"
        query = "parked ask one"
        first = self.session_id()
        second = self._second_session_then_back()
        print(" first:", first, "second:", second)
        bubbles = self.page.locator(".session-item .session-bubble")
        print(" idle bubbles:", bubbles.count(), "rows:", self.page.locator(".session-item").count())
        self.assertGreaterEqual(self.page.locator(".session-item").count(), 2)
        self.assertEqual(bubbles.count(), self.page.locator(".session-item").count())
        self._choose_ask()
        held = {"route": None, "done": False}
        patches = []
        stamp = {"on": False}

        def hold_ask(route):
            if route.request.method != "POST":
                route.fallback()
                return
            held["route"] = route

        def stamp_busy(route):
            if route.request.method != "GET" or not stamp["on"]:
                route.fallback()
                return
            response = route.fetch()
            data = response.json()
            for row in data.get("sessions") or []:
                if row.get("session_id") == first:
                    row["kernel_busy"] = True
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        def note_patch(request):
            if request.method == "PATCH":
                patches.append(request.url)

        self.page.on("request", note_patch)
        self.page.route("**/v1/sessions", stamp_busy)
        self.page.route("**/v1/ask", hold_ask)
        try:
            self.send(query)
            self.page.wait_for_selector(
                f'[data-session-id="{first}"] .session-busy-ring',
                timeout=10000,
            )
            self._hold_until(held)
            stamp["on"] = True
            self.page.click("#btn-new-session")
            self.page.wait_for_function(
                "(known) => { const id = localStorage.getItem('qteasy-ai.session_id'); return Boolean(id) && id !== known[0] && id !== known[1]; }",
                arg=[first, second],
                timeout=10000,
            )
            ring_after_list = self.page.locator(f'[data-session-id="{first}"] .session-busy-ring').count()
            print(" ring after stale kernel_busy:", ring_after_list, "rows:", self.page.locator(".session-item").count())
            self.assertEqual(ring_after_list, 1)
            self.page.locator(f'[data-session-id="{second}"]').click()
            self.page.wait_for_function(
                "(id) => localStorage.getItem('qteasy-ai.session_id') === id",
                arg=second,
                timeout=10000,
            )
            row = self.page.locator(f'[data-session-id="{second}"]')
            self.rename_box(second, "Half name")
            print(" rename draft:", self.page.locator(".session-rename").input_value())
            self._fulfill_json(held, {
                "ok": True,
                "mode": "ask",
                "session_id": first,
                "transcript": [
                    {"kind": "user_text", "text": query},
                    {"kind": "ask", "text": marker, "payload": {}},
                ],
                "execution": {"status": "", "steps": []},
                "kernel_busy": False,
                "messages": [],
            })
            self.page.wait_for_selector(
                f'[data-session-id="{first}"] .session-unseen-dot',
                timeout=10000,
            )
            draft = self.page.locator(".session-rename").input_value()
            first_row = self.page.locator(f'[data-session-id="{first}"]')
            print(" draft after post:", draft, "patches:", patches)
            print(
                " first mark dot:",
                first_row.locator(".session-unseen-dot").count(),
                "bubble:",
                first_row.locator(".session-bubble").count(),
            )
            self.assertEqual(draft, "Half name")
            self.assertEqual(patches, [])
            self.assertEqual(first_row.locator(".session-unseen-dot").count(), 1)
            self.assertEqual(first_row.locator(".session-bubble").count(), 0)
            self.page.press(".session-rename", "Escape")
            self.page.locator(f'[data-session-id="{first}"]').click()
            self.page.wait_for_selector(f"text={marker}", timeout=10000)
            planning = self.page.locator("[data-testid='planning-wait']").count()
            back_bubble = self.page.locator(f'[data-session-id="{first}"] .session-bubble').count()
            back_dot = self.page.locator(f'[data-session-id="{first}"] .session-unseen-dot').count()
            print(" planning:", planning, "bubble:", back_bubble, "dot:", back_dot)
            self.assertEqual(planning, 0)
            self.assertEqual(back_bubble, 1)
            self.assertEqual(back_dot, 0)
        finally:
            self._drop_held(held)
            self.page.wait_for_function(
                "() => !document.querySelector('.session-busy-ring')",
                timeout=10000,
            )

    def test_hung_ask_keeps_ring_until_session_get(self) -> None:
        """POST 不回来时圆圈保持。点回去先见 Planning，GET 变长后才是回复。"""

        print("\n[TestWorkbenchBrowser] hung ask keeps ring until session get")
        marker = "REPLY-LATE-9c2e"
        query = "parked ask two"
        first = self.session_id()
        second = self._second_session_then_back()
        print(" first:", first, "second:", second)
        self._choose_ask()
        held = {"route": None, "done": False}
        late = {"route": None, "done": False}

        def hold_ask(route):
            if route.request.method != "POST":
                route.fallback()
                return
            held["route"] = route

        def hold_session_get(route):
            path = route.request.url.split("?")[0].rstrip("/")
            if route.request.method != "GET" or not path.endswith(f"/v1/session/{first}"):
                route.fallback()
                return
            late["route"] = route

        self.page.route("**/v1/session/**", hold_session_get)
        self.page.route("**/v1/ask", hold_ask)
        try:
            self.send(query)
            self.page.wait_for_selector(
                f'[data-session-id="{first}"] .session-busy-ring',
                timeout=10000,
            )
            self._hold_until(held)
            self.page.locator(f'[data-session-id="{second}"]').click()
            self.page.wait_for_function(
                "(id) => localStorage.getItem('qteasy-ai.session_id') === id",
                arg=second,
                timeout=10000,
            )
            self.page.wait_for_timeout(2500)
            first_row = self.page.locator(f'[data-session-id="{first}"]')
            second_row = self.page.locator(f'[data-session-id="{second}"]')
            print(
                " after wait ring:",
                first_row.locator(".session-busy-ring").count(),
                "dot:",
                first_row.locator(".session-unseen-dot").count(),
                "second bubble:",
                second_row.locator(".session-bubble").count(),
            )
            self.assertEqual(first_row.locator(".session-busy-ring").count(), 1)
            self.assertEqual(first_row.locator(".session-unseen-dot").count(), 0)
            self.assertEqual(first_row.locator(".session-bubble").count(), 0)
            self.assertEqual(second_row.locator(".session-bubble").count(), 1)
            self.rename_box(second, "Side two", submit="Enter")
            self.page.wait_for_function(
                "() => document.querySelector('#session-title').textContent.includes('Side two')",
                timeout=10000,
            )
            print(
                " renamed ring:",
                self.page.locator(f'[data-session-id="{first}"] .session-busy-ring').count(),
                "second bubble:",
                self.page.locator(f'[data-session-id="{second}"] .session-bubble').count(),
            )
            self.assertEqual(self.page.locator(f'[data-session-id="{first}"] .session-busy-ring').count(), 1)
            self.assertEqual(self.page.locator(f'[data-session-id="{second}"] .session-bubble').count(), 1)
            self.page.locator(f'[data-session-id="{first}"]').click()
            self.page.wait_for_selector("[data-testid='planning-wait']", timeout=10000)
            self._hold_until(late)
            print(" planning before get:", self.page.locator("[data-testid='planning-wait']").count())
            self.assertEqual(self.page.locator("[data-testid='planning-wait']").count(), 1)
            self._fulfill_json(late, {
                "ok": True,
                "mode": "ask",
                "session_id": first,
                "transcript": [
                    {"kind": "user_text", "text": query},
                    {"kind": "ask", "text": marker, "payload": {}},
                ],
                "execution": {"status": "", "steps": []},
                "kernel_busy": False,
                "messages": [],
            })
            self.page.wait_for_selector(f"text={marker}", timeout=10000)
            planning = self.page.locator("[data-testid='planning-wait']").count()
            bubble = self.page.locator(f'[data-session-id="{first}"] .session-bubble').count()
            print(" planning after get:", planning, "bubble:", bubble)
            self.assertEqual(planning, 0)
            self.assertEqual(bubble, 1)
        finally:
            self._drop_held(late)
            self._drop_held(held)
            self.page.wait_for_function(
                "() => !document.querySelector('.session-busy-ring')",
                timeout=10000,
            )
