# coding=utf-8
# ======================================
# File: harness.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-03
# Desc:
# 工作台浏览器测试的临时服务、hold 技能与页面夹具。
# ======================================

"""为 Playwright 用例起一个只存在于本进程的 workbench。"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

HOLD_QUERY = "hold the workbench run"
HOLD_SKILL = "qt.ai.test.hold"
_HOLD_SECONDS = 8.0
_VIEWPORT = {"width": 1440, "height": 900}


class HoldProbe:
    """记录 hold 技能是被取消还是睡满。"""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.finished = threading.Event()
        self.reason = ""
        self._lock = threading.Lock()

    def reset(self) -> None:
        """清掉上一用例的标志。调用前技能线程必须已经退出。"""

        with self._lock:
            self.reason = ""
        self.started.clear()
        self.finished.clear()

    def mark_started(self) -> None:
        """技能循环已经开始。"""

        self.started.set()

    def mark_finished(self, reason: str) -> None:
        """记下第一次结束原因。"""

        with self._lock:
            if self.finished.is_set():
                return
            self.reason = reason
        self.finished.set()


def _hold_handler(probe: HoldProbe, **kwargs: Any) -> Dict[str, Any]:
    """睡到取消或超时。取消时抛 ``RunCancelled``。"""

    del kwargs
    from qteasy.cancel_check import RunCancelled, should_cancel
    from qteasy_ai.contracts import SkillResult, new_run_id

    probe.mark_started()
    deadline = time.monotonic() + _HOLD_SECONDS
    while time.monotonic() < deadline:
        if should_cancel():
            probe.mark_finished("cancelled")
            raise RunCancelled("hold cancelled")
        time.sleep(0.2)
    probe.mark_finished("timeout")
    return SkillResult(
        ok=True,
        skill_name=HOLD_SKILL,
        run_id=new_run_id(),
        metrics={"held_s": _HOLD_SECONDS},
    ).to_dict()


def _build_hold_plan(
    assistant: Any,
    asked: str,
    *,
    session_id: Optional[str],
    agent_auto: Optional[bool],
) -> Tuple[Any, Optional[Any]]:
    """记下用户句并返回一步 hold 的 dry-run 计划。"""

    from qteasy_ai.contracts import SkillSideEffects, ToolPlan, ToolStep, new_plan_id

    plan = ToolPlan(
        plan_id=new_plan_id(),
        user_query=asked,
        steps=[
            ToolStep(
                step_id="hold-1",
                skill_name=HOLD_SKILL,
                inputs={},
                side_effects=SkillSideEffects(description="test hold"),
                estimated_cost="low",
            )
        ],
        assumptions={"intent_job": "test.hold"},
        planner_trace={"intent_job": "test.hold", "source": "browser_test"},
        execution_mode="dry_run",
        mode="plan",
    )
    sid = str(session_id or "").strip()
    if not sid:
        return plan, None
    state = assistant.session_store.load(sid)
    if agent_auto is not None:
        state.agent_auto = bool(agent_auto)
    state.append_user_text(asked)
    state.start_task(query=asked, job="test.hold")
    assistant._sync_session_from_plan(state, plan, query=asked, skip_classify=False)
    assistant.session_store.save(state)
    return plan, state


def _install_hold(assistant: Any, probe: HoldProbe) -> None:
    """注册 hold 技能，并只拦截那一句的计划装配。"""

    from qteasy_ai.contracts import SkillMetadata, SkillSideEffects

    assistant.registry.register(
        SkillMetadata(
            name=HOLD_SKILL,
            version="0.0.0",
            summary="Browser test hold.",
            inputs_schema={},
            outputs_schema={"held_s": "float"},
            side_effects=SkillSideEffects(description="test hold"),
            required_capabilities=[],
            qteasy_entrypoints=[],
        ),
        lambda **kwargs: _hold_handler(probe, **kwargs),
    )
    original = assistant._assemble_plan

    def assemble(
        query: str,
        *,
        session_id: Optional[str] = None,
        agent_auto: Optional[bool] = None,
        patches: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Any, Optional[Any]]:
        asked = str(query or "").strip()
        if asked == HOLD_QUERY and not patches:
            return _build_hold_plan(
                assistant,
                asked,
                session_id=session_id,
                agent_auto=agent_auto,
            )
        return original(
            query,
            session_id=session_id,
            agent_auto=agent_auto,
            patches=patches,
        )

    assistant._assemble_plan = assemble


class BrowserHarness:
    """临时目录上的 uvicorn 与 Chromium。"""

    def __init__(self) -> None:
        self.temp_dir: Optional[tempfile.TemporaryDirectory[str]] = None
        self.store: Any = None
        self.hold = HoldProbe()
        self.base_url = ""
        self._server: Any = None
        self._thread: Optional[threading.Thread] = None
        self._playwright: Any = None
        self.browser: Any = None

    def start(self) -> None:
        """起服务和浏览器。Playwright 或 Chromium 缺失时跳过整组。"""

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise unittest.SkipTest(
                "playwright is not installed; "
                "pip install playwright && playwright install chromium"
            ) from exc

        import uvicorn

        from qteasy_ai.app import QteasyAssistant, build_default_registry
        from qteasy_ai.memory_store import MemoryStore
        from qteasy_ai.workbench.http_app import create_app

        self.temp_dir = tempfile.TemporaryDirectory(prefix="qteasy-ai-browser-")
        self.store = MemoryStore(base_dir=self.temp_dir.name)
        registry = build_default_registry()
        assistant = QteasyAssistant(memory_store=self.store, registry=registry)
        _install_hold(assistant, self.hold)
        app = create_app(assistant=assistant)
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", access_log=False)
        )
        self._thread = threading.Thread(target=self._server.run, name="wb-browser", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self._server.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("workbench server did not start")
        sockets = self._server.servers[0].sockets
        port = sockets[0].getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"
        print("\n[WorkbenchBrowser] server", self.base_url, "home", self.temp_dir.name)
        self._playwright = sync_playwright().start()
        try:
            self.browser = self._playwright.chromium.launch(headless=True)
        except Exception:
            try:
                print("[WorkbenchBrowser] bundled chromium missing; using installed Google Chrome")
                self.browser = self._playwright.chromium.launch(headless=True, channel="chrome")
            except Exception as exc:
                self.close()
                raise unittest.SkipTest(
                    "chromium is not installed; python -m playwright install chromium"
                ) from exc

    def close(self) -> None:
        """停浏览器、停服务、删临时目录。"""

        if self.browser is not None:
            self.browser.close()
            self.browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        if self.temp_dir is not None:
            self.temp_dir.cleanup()
            self.temp_dir = None

    def session_status(self, session_id: str) -> int:
        """GET 会话，返回 HTTP 状态码。缺文件时现有接口仍是 200 的空会话。"""

        url = f"{self.base_url}/v1/session/{quote(session_id, safe='')}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return int(response.status)
        except urllib.error.HTTPError as exc:
            return int(exc.code)

    def session_file_exists(self, session_id: str) -> bool:
        """会话 JSON 是否已落盘。"""

        from qteasy_ai.session import SessionStore

        return SessionStore(self.store).exists(session_id)

    def run_names(self) -> List[str]:
        """当前 ``runs/`` 文件名。"""

        runs = Path(self.store.runs_dir)
        if not runs.is_dir():
            return []
        return sorted(path.name for path in runs.iterdir() if path.is_file())


class WorkbenchBrowserCase(unittest.TestCase):
    """每个用例一个新的浏览器上下文，测完删掉已落盘的会话。"""

    harness: BrowserHarness

    @classmethod
    def setUpClass(cls) -> None:
        cls.harness = BrowserHarness()
        try:
            cls.harness.start()
        except Exception:
            cls.harness.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        harness = getattr(cls, "harness", None)
        if harness is not None:
            harness.close()

    def setUp(self) -> None:
        self.harness.hold.reset()
        self.dialogs: List[str] = []
        self.dialog_mode = "accept"
        self.context = self.harness.browser.new_context(viewport=_VIEWPORT)
        self.page = self.context.new_page()
        self.page.on("dialog", self._on_dialog)
        base_url = self.harness.base_url

        def _keep_local(route: Any) -> None:
            if route.request.url.startswith(base_url):
                route.continue_()
            else:
                route.abort()

        self.page.route("**/*", _keep_local)
        self.page.goto(base_url, wait_until="domcontentloaded")
        self.page.wait_for_selector("#composer-mode", timeout=15000)
        self.page.evaluate("() => window.dispatchEvent(new Event('resize'))")
        self.page.click("#btn-new-session")
        self.page.wait_for_selector("#query-input")

    def tearDown(self) -> None:
        try:
            self._stop_if_running()
            if self.harness.hold.started.is_set():
                finished = self.harness.hold.finished.wait(timeout=12)
                print(" hold finished:", finished, "reason:", self.harness.hold.reason)
            self._delete_current_session()
        finally:
            self.context.close()

    def _on_dialog(self, dialog: Any) -> None:
        """接受或拒绝 ``window.confirm``。"""

        message = str(dialog.message)
        self.dialogs.append(message)
        print(" dialog:", message[:160])
        if self.dialog_mode == "dismiss":
            dialog.dismiss()
        else:
            dialog.accept()

    def session_id(self) -> str:
        """当前浏览器记下的 session id。"""

        value = self.page.evaluate("() => localStorage.getItem('qteasy-ai.session_id')")
        return str(value or "")

    def send(self, text: str) -> None:
        """在 composer 里输入并发送。"""

        self.page.fill("#query-input", text)
        self.page.click("#btn-send")

    def width_of(self, selector: str) -> float:
        """元素宽度。"""

        box = self.page.locator(selector).bounding_box()
        self.assertIsNotNone(box, msg=selector)
        assert box is not None
        return float(box["width"])

    def right_of(self, selector: str) -> float:
        """元素右缘的 x。"""

        box = self.page.locator(selector).bounding_box()
        self.assertIsNotNone(box, msg=selector)
        assert box is not None
        return float(box["x"]) + float(box["width"])

    def _stop_button_visible(self) -> bool:
        """Stop 还在页面上。重绘拆掉节点时按不在处理。"""

        stop = self.page.locator("#btn-stop-watch")
        try:
            return stop.count() > 0 and stop.is_visible()
        except Exception:
            return False

    def _stop_if_running(self) -> None:
        """忙或后台运行时先 Stop，否则删除会被页面拒绝。

        聊天重绘会拆掉 Stop 再挂上。运行自己结束时按钮消失，这时不再点。
        """

        if not self._stop_button_visible():
            return
        self.dialog_mode = "accept"
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if not self._stop_button_visible():
                print(" teardown stop: already gone")
                return
            try:
                self.page.locator("#btn-stop-watch").click(timeout=1000, force=True)
            except Exception as exc:
                print(" teardown stop retry:", type(exc).__name__)
                continue
            try:
                self.page.locator("#btn-stop-watch").wait_for(state="hidden", timeout=2000)
                print(" teardown stop: hidden")
                return
            except Exception:
                continue
        if not self._stop_button_visible():
            print(" teardown stop: gone after retries")
            return
        self.fail("Stop button stayed visible")

    def _delete_current_session(self) -> None:
        """点删除。已落盘的会话必须变成 404。"""

        session_id = self.session_id()
        existed = bool(session_id) and self.harness.session_file_exists(session_id)
        print(" teardown session:", session_id, "persisted:", existed)
        rail_class = self.page.locator("#session-rail").get_attribute("class") or ""
        if "collapsed" in rail_class:
            self.page.click("#btn-toggle-rail")
        row = self.page.locator(f'[data-session-id="{session_id}"]')
        if row.count():
            row.hover()
            self.dialog_mode = "accept"
            row.locator("[data-session-delete]").click()
            row.wait_for(state="detached", timeout=10000)
        if existed:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and self.harness.session_file_exists(session_id):
                time.sleep(0.05)
        still_there = bool(session_id) and self.harness.session_file_exists(session_id)
        print(" teardown file exists:", still_there)
        self.assertFalse(still_there)
