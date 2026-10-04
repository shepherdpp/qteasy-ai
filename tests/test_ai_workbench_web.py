# coding=utf-8
# ======================================
# File: test_ai_workbench_web.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-07
# Desc:
# Unittest for workbench SPA shell (G.4)
# ======================================

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.workbench.http_app import STATIC_DIR, create_app

_FIXTURE = Path(__file__).resolve().parent / "ai_corpus" / "workbench_ui_states.json"
_TYPES = Path(__file__).resolve().parents[1] / "web" / "src" / "types.ts"


def _extract_js_function(src: str, name: str) -> str:
    """按花括号配对抽出 ``function name`` 源码。"""

    marker = f"function {name}"
    start = src.find(marker)
    if start < 0:
        raise AssertionError(f"missing function {name}")
    brace = src.find("{", start)
    if brace < 0:
        raise AssertionError(f"missing body for {name}")
    depth = 0
    for index in range(brace, len(src)):
        char = src[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return src[start:index + 1]
    raise AssertionError(f"unbalanced braces in {name}")


def _eval_js(fn_src: str, call_expr: str) -> object:
    """用 node 执行已抽出的纯函数并解析 JSON。"""

    script = fn_src + "\nprocess.stdout.write(JSON.stringify(" + call_expr + "));\n"
    out = subprocess.check_output(["node", "-e", script], text=True)
    return json.loads(out)


class TestAiWorkbenchWeb(unittest.TestCase):
    """G.4：SPA 入口、静态资源、DTO 键与 fixture 对齐。"""

    def test_index_and_static_assets(self) -> None:
        """GET / 返回 SPA；/static/app.js 与 css 为 200。"""

        print("\n[TestAiWorkbenchWeb] index and static")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            index = client.get("/")
            js = client.get("/static/app.js")
            css = client.get("/static/app.css")
            print(" index:", index.status_code, index.headers.get("content-type"))
            print(" js:", js.status_code, "css:", css.status_code)
            print(" static dir:", STATIC_DIR, "exists:", STATIC_DIR.exists())
            self.assertEqual(index.status_code, 200)
            self.assertIn("qteasy-ai Workbench", index.text)
            self.assertEqual(js.status_code, 200)
            print(" js has isComposing:", "isComposing" in js.text)
            print(" js has ctrlKey:", "ctrlKey" in js.text)
            print(" js has Workspace:", "Workspace" in js.text)
            print(" js has Mode: prefix:", "Mode:" in js.text)
            self.assertNotIn("Mode:", js.text)
            self.assertIn("mode-ask", js.text)
            self.assertIn("mode-plan", js.text)
            self.assertIn("mode-agent", js.text)
            self.assertIn("plan-card", js.text)
            self.assertIn("clarification-form", js.text)
            self.assertIn("step-list", js.text)
            self.assertIn("isComposing", js.text)
            self.assertIn("ctrlKey", js.text)
            self.assertIn("textarea", js.text)
            self.assertIn("Workspace", js.text)
            self.assertNotIn("btn-toggle-workspace", js.text)
            self.assertIn("btn-collapse-workspace", js.text)
            self.assertNotIn("composer-meta", js.text)
            self.assertIn("composer-provider", js.text)
            self.assertIn("btn-settings", js.text)
            self.assertIn("Ctrl/⌘+Enter to send", js.text)
            self.assertNotIn("Enter new line", js.text)
            print(" topbar has mode-group:", js.text.split("topbar")[1].split("layout")[0].count("mode-group"))
            self.assertNotIn("btn-code-confirm", js.text)
            self.assertNotIn("Confirm running edited strategy", js.text)
            self.assertIn(">View Plan<", js.text)
            self.assertNotIn(">Open plan<", js.text)
            self.assertIn("text/event-stream", js.text)
            self.assertNotIn("btn-retry", js.text)
            self.assertNotIn("function retryLast", js.text)
            self.assertNotIn("Retry failed step", js.text)
            self.assertIn("Edit the blue message (pencil) and send it again.", js.text)
            self.assertIn("next_action", js.text)
            self.assertIn("persistTranscript", js.text)
            self.assertIn("btn-file-back", js.text)
            self.assertIn("applySessionMode", js.text)
            self.assertIn("Plan card dismissed", js.text)
            self.assertNotIn('sendQuery("abandon"', js.text)
            self.assertIn("Confirm is optional", js.text)
            self.assertIn("Show Workspace", js.text)
            self.assertIn("data-edit-user", js.text)
            self.assertIn("/v1/session/", js.text)
            self.assertIn("rewind", js.text)
            self.assertIn("data-art-index", js.text)
            self.assertIn("/v1/provider", js.text)
            self.assertIn("btn-prov-confirm", js.text)
            self.assertIn("applyServerTranscript", js.text)
            self.assertIn("if (!dto || !Array.isArray(dto.transcript)) return;", js.text)
            self.assertIn(
                'return busy && !runWatchActive() && !executeSseOpen && mode !== "agent" && mode !== "run";',
                js.text,
            )
            self.assertIn("function adoptServerResult", js.text)
            print(" js keeps transcript when dto has no transcript:", "Array.isArray(dto.transcript)" in js.text)
            self.assertIn("No artifacts in this session", js.text)
            self.assertIn("This session", js.text)
            self.assertIn("btn-clarify-skip", js.text)
            print(" js has clarify-options:", "clarify-options" in js.text)
            print(" js has data-clarify-option:", "data-clarify-option" in js.text)
            print(" js followUp chip:", "followUp(t.dataset.clarifyOption)" in js.text)
            self.assertIn("data-clarify-option", js.text)
            self.assertIn("clarify-options", js.text)
            self.assertIn("clarify-chip", js.text)
            self.assertIn("payload.options", js.text)
            self.assertIn("Full steps are in the plan Artifact", js.text)
            self.assertIn("sendControlSkip", js.text)
            self.assertIn("sendControlPatches", js.text)
            print(" js has liveClarifyMessage:", "liveClarifyMessage" in js.text)
            print(" js has latestNonUserMessage:", "latestNonUserMessage" in js.text)
            self.assertIn("liveClarifyMessage", js.text)
            self.assertIn("latestNonUserMessage", js.text)
            self.assertIn("latestClarify", js.text)
            print(" js has clarify-history:", "clarify-history" in js.text)
            self.assertIn("clarify-history", js.text)
            self.assertIn("Clarify", js.text)
            self.assertNotIn(
                'transcript.concat(state.messages || []).find((m) => m.kind === "clarification" || m.kind === "clarify")',
                js.text,
            )
            self.assertNotIn(
                'transcript.some((m) => m.kind === "clarification" || m.kind === "clarify")',
                js.text,
            )
            self.assertIn("state.artifacts = workspace.artifacts", js.text)
            self.assertIn("chart-img", js.text)
            self.assertIn("/v1/artifacts/", js.text)
            self.assertIn("busy-msg", js.text)
            self.assertIn("edit-composer", js.text)
            self.assertIn('formatRunClock("Working")', js.text)
            self.assertIn("btn-stop-watch", js.text)
            self.assertIn("AbortController", js.text)
            self.assertIn("heartbeat", js.text)
            self.assertIn("progress-indet", js.text)
            self.assertNotIn("busy-label", js.text)
            self.assertIn("data-now-edit", js.text)
            self.assertIn("Switched to", js.text)
            self.assertNotIn("g7-slot", js.text)
            self.assertNotIn("btn-abandon-trial", js.text)
            self.assertNotIn("btn-abandon-open", js.text)
            print(" js has g7-slot:", "g7-slot" in js.text)
            self.assertEqual(css.status_code, 200)
            self.assertIn("grid-template-columns", css.text)
            print(" css has slot-tag:", "slot-tag" in css.text)
            print(" css has clarify-options:", "clarify-options" in css.text)
            self.assertIn("slot-tag", css.text)
            self.assertIn("clarify-options", css.text)
            self.assertIn("artifact-toolbar", css.text)
            self.assertIn("workspace-col.collapsed", css.text)
            self.assertNotIn("display: none", css.text.split(".workspace-col")[1].split(".col-head")[0] if ".workspace-col" in css.text else "")

    def test_session_mode_dropdown_without_origin_stickers(self) -> None:
        """composer 模式下拉保留；壳层不再用 origin/clarifyUi 贴纸。"""

        print("\n[TestAiWorkbenchWeb] mode dropdown without origin stickers")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            js = client.get("/static/app.js")
            css = client.get("/static/app.css")
            self.assertEqual(js.status_code, 200)
            self.assertEqual(css.status_code, 200)
            src = js.text
            print(" js has clarify_ui:", "clarify_ui" in src)
            print(" js has followUpFromCard:", "followUpFromCard" in src)
            print(" js has mode-menu:", "mode-menu" in src)
            self.assertNotIn("clarify_ui", src)
            self.assertNotIn("followUpFromCard", src)
            self.assertNotIn("clarifyUi", src)
            self.assertNotIn("originMap", src)
            self.assertIn("sendControlSkip", src)
            self.assertIn("sendControlPatches", src)
            self.assertIn("mode-menu", src)
            self.assertIn("mode-dropdown", src)
            self.assertIn("btn-mode-menu", src)
            after_input = src.split('id="query-input"', 1)[1] if 'id="query-input"' in src else ""
            composer_row = after_input.split("btn-send")[0] if after_input else ""
            print(" composer-row has mode-menu:", "mode-menu" in composer_row)
            print(" composer-row has composer-provider:", "composer-provider" in composer_row)
            self.assertIn("mode-menu", composer_row)
            self.assertIn("composer-provider", composer_row)
            self.assertNotIn('<div class="mode-group">', composer_row)
            self.assertNotIn("composer-meta", src)
            self.assertIn("payload.answer", src)
            self.assertIn("Answered:", src)
            self.assertIn("shouldShowLiveClarify", src)
            self.assertIn("clarification-form", src)
            self.assertIn("plan-card", src)
            self.assertIn("liveClarifyMessage", src)
            self.assertIn("Confirm is optional", src)
            self.assertNotIn("design-card", src)
            self.assertNotIn("btn-kb-write", src)
            print(" has followUp fn:", "function followUp" in src)
            print(" has renderDesignCard:", "function renderDesignCard" in src)
            self.assertNotIn("function followUp", src)
            self.assertNotIn("function renderDesignCard", src)
            self.assertNotIn("function renderKbWriteCard", src)
            print(" css has mode-dropdown:", "mode-dropdown" in css.text)
            print(" css has mode-menu:", "mode-menu" in css.text)
            self.assertIn("mode-dropdown", css.text)
            self.assertIn("mode-menu", css.text)

    def test_submit_param_edits_posts_patches_not_followup(self) -> None:
        """submitParamEdits 提交结构化 patches，函数体内不得 followUp / sendQuery。"""

        print("\n[TestAiWorkbenchWeb] submitParamEdits patches control plane")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            fn = src.split("function submitParamEdits")[1].split("async function submitProviderChange")[0]
            print(" fn has followUp:", "followUp" in fn)
            print(" fn has sendQuery:", "sendQuery" in fn)
            print(" fn has patches:", "patches" in fn)
            print(" fn has /v1/plan:", "/v1/plan" in fn)
            self.assertNotIn("followUp", fn)
            self.assertNotIn("sendQuery", fn)
            self.assertIn("patches", fn)
            self.assertIn("/v1/plan", fn)
            self.assertIn("session_id", fn)

    def test_fixture_keys_match_types_ts(self) -> None:
        """fixture 四态 + types.ts WORKBENCH_STATE_KEYS 对齐。"""

        print("\n[TestAiWorkbenchWeb] fixture keys")
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        types_src = _TYPES.read_text(encoding="utf-8")
        match = re.search(r"WORKBENCH_STATE_KEYS = \[([^\]]+)\]", types_src, re.S)
        self.assertIsNotNone(match)
        ts_keys = re.findall(r'"([a-z_]+)"', match.group(1))
        required = list(payload["required_state_keys"])
        print(" ts_keys:", ts_keys)
        print(" fixture required:", required)
        self.assertEqual(ts_keys, required)
        states = payload["states"]
        print(" state names:", sorted(states))
        self.assertEqual(
            set(states),
            {"ask_bubble", "clarification_form", "plan_card_side_effects", "executing_steps"},
        )
        for name, state in states.items():
            print(" state", name, "keys:", sorted(state))
            self.assertEqual(set(state), set(required))
            if name == "ask_bubble":
                self.assertEqual(state["mode"], "ask")
                self.assertIsNone(state["plan_card"])
            if name == "clarification_form":
                kinds = [m["kind"] for m in state["messages"]]
                self.assertIn("clarify", kinds)
            if name == "plan_card_side_effects":
                step = state["plan_card"]["steps"][0]
                self.assertIn("side_effects", step)
                self.assertIn("network", step["side_effects"])
            if name == "executing_steps":
                self.assertEqual(state["execution"]["steps"][0]["status"], "done")
            for art in state.get("artifacts") or []:
                self.assertNotEqual(art.get("type"), "factor_analysis")

    def test_session_list_uses_name_and_last_user_not_job(self) -> None:
        """Sessions 栏主行 name、副行 last_user；含改名/删除确认契约。"""

        print("\n[TestAiWorkbenchWeb] session list name last_user")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            js = client.get("/static/app.js")
            css = client.get("/static/app.css")
            src = js.text
            print(" has last_user:", "last_user" in src)
            print(" has job meta template:", 'row.job' in src and "meta" in src)
            print(" has PATCH:", 'method: "PATCH"' in src)
            print(" has DELETE:", 'method: "DELETE"' in src)
            print(" has confirm:", "window.confirm" in src)
            print(" has New session:", "New session" in src)
            self.assertIn("last_user", src)
            self.assertIn("row.name", src)
            self.assertNotIn('meta">${escapeHtml(row.job', src)
            self.assertIn("data-session-delete", src)
            self.assertIn("window.confirm", src)
            self.assertIn('method: "PATCH"', src)
            self.assertIn('method: "DELETE"', src)
            self.assertIn("stopPropagation", src)
            self.assertIn("New session", src)
            print(" css session-actions:", "session-actions" in css.text)
            self.assertIn("session-actions", css.text)
            self.assertIn(":focus-within", css.text)

    def test_artifact_tabs_open_on_demand_not_auto(self) -> None:
        """中栏 openTabs；Workspace / Open plan 共用 openArtifactTab；ingest 不自动打开。"""

        print("\n[TestAiWorkbenchWeb] artifact open tabs")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            print(" has openArtifactTab:", "function openArtifactTab" in src)
            print(" has openTabs:", "openTabs" in src)
            print(" has data-open-plan:", "data-open-plan" in src)
            print(" has closePlanTabsForRun:", "function closePlanTabsForRun" in src)
            self.assertIn("function openArtifactTab", src)
            self.assertIn("openTabs", src)
            self.assertIn("data-open-plan", src)
            self.assertIn("Open a plan or artifact", src)
            self.assertIn("function closePlanTabsForRun", src)
            self.assertIn('type === "plan"', src)
            ws_fn = src.split("async function onWorkspaceArtifactClick")[1].split("async function createSession")[0]
            print(" workspace calls openArtifactTab:", "openArtifactTab" in ws_fn)
            print(" workspace sets artifactTab idx:", "artifactTab = idx" in ws_fn)
            self.assertIn("openArtifactTab", ws_fn)
            self.assertNotIn("artifactTab = idx", ws_fn)
            ingest = src.split("function ingestDto")[1].split("async function sendQuery")[0]
            print(" ingest calls openArtifactTab:", "openArtifactTab" in ingest)
            self.assertNotIn("openArtifactTab", ingest)
            self.assertIn("data-tab-close", src)
            self.assertIn(">View Plan<", src)
            self.assertNotIn(">Open plan<", src)
            self.assertIn("click View Plan on a Plan ready card", src)
            print(" js has bindTabsWheel:", "function bindTabsWheel" in src)
            self.assertIn("function bindTabsWheel", src)
            self.assertIn("function onTabsWheel", src)

    def test_shell_composer_edit_settings_placeholders(self) -> None:
        """Composer 底栏、用户编辑铅笔、rewind Send、设置 tab 不被 prune。"""

        print("\n[TestAiWorkbenchWeb] shell composer edit settings")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            css = client.get("/static/app.css").text
            print(" placeholder ctrl:", "Ctrl/⌘+Enter to send" in src)
            print(" has composer-provider:", "composer-provider" in src)
            print(" has btn-settings:", "btn-settings" in src)
            print(" has statusbar:", "statusbar" in src)
            self.assertIn("Ctrl/⌘+Enter to send", src)
            self.assertNotIn("Enter new line", src)
            self.assertIn("composer-provider", src)
            self.assertIn("btn-settings", src)
            self.assertIn("statusbar", src)
            self.assertIn('title="Edit">✎</button>', src)
            self.assertIn('id="btn-rewind-submit">${escapeHtml(action.label)}</button>', src)
            self.assertIn('id="btn-rewind-cancel">Cancel</button>', src)
            self.assertIn("Discard and resend", src)
            self.assertNotIn("Resend from here", src)
            self.assertNotIn("Confirm discard and resend", src)
            prune = src.split("function pruneMissingTabs")[1].split("function openPlanFromRunId")[0]
            print(" prune keeps settings:", 'type === "settings"' in prune)
            self.assertIn('type === "settings"', prune)
            self.assertIn('{ type: "settings", run_id: "local" }', src)
            print(" css nowrap:", "flex-wrap: nowrap" in css)
            print(" css statusbar:", ".statusbar" in css)
            print(" css bubble-edit:", ".bubble-edit" in css)
            self.assertIn("flex-wrap: nowrap", css)
            self.assertIn("overflow-x: auto", css)
            self.assertIn(".statusbar", css)
            self.assertIn(".bubble-edit", css)
            self.assertNotIn(".msg-actions", css)
            print(" has theme storage:", "qteasy-ai.theme" in src)
            print(" has light theme:", 'html[data-theme="light"]' in css)
            now_fn = src.split("function renderNow()")[1].split("function renderNowChips")[0]
            print(" now has Environment:", "Environment" in now_fn)
            print(" now has provider block:", "now-provider" in now_fn)
            self.assertIn("qteasy-ai.theme", src)
            self.assertIn("btn-theme-light", src)
            self.assertIn("btn-theme-dark", src)
            self.assertIn("function renderProviderForm", src)
            self.assertIn("id=\"prov-model\"", src)
            self.assertNotIn("Provider and environment configuration will live here", src)
            self.assertNotIn("now-provider", now_fn)
            self.assertNotIn("now-env", now_fn)
            self.assertNotIn("Environment", now_fn)
            self.assertIn("Environment", src.split("function renderStatusbar")[1].split("function openSettingsTab")[0])
            self.assertIn('id="btn-open-settings">Open settings</button>', src)
            self.assertIn('html[data-theme="light"]', css)
            self.assertIn("justify-content: center", css)
            self.assertIn(".fill-pane", css)

    def test_plan_artifact_renders_markdown_with_sanitize(self) -> None:
        """plan Artifact 只读渲染 md/mermaid，保留 json_wins，库缺失可降级 pre。"""

        print("\n[TestAiWorkbenchWeb] plan markdown mermaid")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            index = client.get("/").text
            src = client.get("/static/app.js").text
            print(" index mermaid:", "mermaid" in index.lower())
            print(" index purify:", "purify" in index.lower() or "DOMPurify" in index)
            print(" js renderPlanMarkdown:", "function renderPlanMarkdown" in src)
            print(" js securityLevel:", "securityLevel" in src)
            self.assertTrue("mermaid" in index.lower() or "mermaid" in src)
            self.assertTrue("DOMPurify" in src or "purify" in index.lower())
            self.assertIn("function renderPlanMarkdown", src)
            self.assertIn("securityLevel", src)
            self.assertIn("JSON in runs/ is the executable source", src)
            self.assertIn("renderPlanMarkdown", src.split('current.type === "plan"')[1].split("host.innerHTML")[0])
            self.assertNotIn('<pre class="plan-md">${escapeHtml(markdown', src.split("function renderPlanMarkdown")[0])

    def test_run_liveness_stop_and_switch_session(self) -> None:
        """Stop 停观望；切 Session 不因 busy 早退，先 abort 再 load。"""

        print("\n[TestAiWorkbenchWeb] run liveness stop switch")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            css = client.get("/static/app.css").text
            print(" has dropRunWatch:", "function dropRunWatch" in src)
            print(" has stopWatchingRun:", "function stopWatchingRun" in src)
            print(" has btn-stop-watch:", "btn-stop-watch" in src)
            print(" switch early busy:", "|| busy" in src.split("async function switchSession")[1].split("async function refreshSessions")[0])
            self.assertIn("function dropRunWatch", src)
            self.assertIn("function stopWatchingRun", src)
            self.assertIn("btn-stop-watch", src)
            self.assertIn("function stopWatchingRun", src)
            self.assertIn("cancel-run", src)
            self.assertIn("btn-background-run", src)
            self.assertIn("background-run", src)
            self.assertIn("Stop this run?", src)
            self.assertNotIn("Stopped watching this run. The server may still finish", src)
            switch_fn = src.split("async function switchSession")[1].split("async function refreshSessions")[0]
            self.assertNotIn("|| busy", switch_fn)
            self.assertIn("dropRunWatch", switch_fn)
            self.assertNotIn("cancel-run", switch_fn)
            self.assertNotIn("background-run", switch_fn)
            create_fn = src.split("async function createSession")[1].split("async function switchSession")[0]
            print(" create calls dropRunWatch:", "dropRunWatch" in create_fn)
            self.assertIn("dropRunWatch", create_fn)
            consume = src.split("async function consumeSse")[1].split("function applyLiveStep")[0]
            print(" consume heartbeat:", "heartbeat" in consume)
            self.assertIn("heartbeat", consume)
            print(" css progress-indet:", "progress-indet" in css)
            self.assertIn("progress-indet", css)
            self.assertIn("now-run-status", src)

    def test_background_watch_keeps_clock_and_plan_card(self) -> None:
        """后台监视：计时不被 setBusy 清掉，结束后收起进度条，Confirm 不被轮询关掉。"""

        print("\n[TestAiWorkbenchWeb] background watch clock and plan card")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            set_busy = _extract_js_function(src, "setBusy")
            clock = _extract_js_function(src, "updateBusyElapsedDom")
            watch = _extract_js_function(src, "applyRunningWatch")
            poll = _extract_js_function(src, "startLivePoll")
            stop_fn = _extract_js_function(src, "stopWatchingRun")
            confirm = _extract_js_function(src, "confirmPlan")
            steps = _extract_js_function(src, "renderSteps")
            now = _extract_js_function(src, "renderNow")
            background_fn = _extract_js_function(src, "backgroundThisRun")
            print(" setBusy keeps clock:", "else if (!backgrounded)" in set_busy)
            print(" clock prefix:", 'formatRunClock("Background")' in clock and 'formatRunClock("Working")' in clock)
            print(" watch starts clock after elapsed:", "startElapsedClock();\n  if (!executeSseOpen)" in watch)
            print(" poll clears backgrounded:", "backgrounded = false" in poll)
            print(" poll guards confirmable:", "blocks_composer" in poll and "confirmable: false" in poll)
            print(" poll ignores error dto:", "dto.error" in poll)
            print(" stop ingests:", "ingestDto" in stop_fn)
            print(" confirm guards sse:", "if (!backgrounded)" in confirm and confirm.find("executeSseOpen = true") > confirm.find("if (!backgrounded)"))
            print(" steps hidden when backgrounded:", "if (backgrounded) return" in steps)
            print(" now uses Background:", 'backgrounded ? "Background"' in now)
            print(" background copies plan_card:", "dto.plan_card" in background_fn)
            self.assertIn("else if (!backgrounded)", set_busy)
            self.assertIn('formatRunClock("Background")', clock)
            self.assertIn('formatRunClock("Working")', clock)
            self.assertIn("startElapsedClock();\n  if (!executeSseOpen)", watch)
            self.assertIn("backgrounded = false", poll)
            self.assertIn("blocks_composer", poll)
            self.assertIn("confirmable: false", poll)
            self.assertIn("dto.error", poll)
            self.assertIn("elapsed_s", poll)
            self.assertIn("ingestDto", stop_fn)
            self.assertIn("if (!backgrounded)", confirm)
            self.assertGreater(confirm.find("executeSseOpen = true"), confirm.find("if (!backgrounded)"))
            self.assertIn("if (backgrounded) return", steps)
            self.assertIn('backgrounded ? "Background"', now)
            self.assertIn("dto.plan_card", background_fn)

    def test_live_restore_poll_and_column_splitter(self) -> None:
        """切回 running 不重 POST run-plan；2s GET 轮询；Session|Artifacts 可拖分隔。"""

        print("\n[TestAiWorkbenchWeb] live restore poll splitter")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            css = client.get("/static/app.css").text
            print(" has startLivePoll:", "function startLivePoll" in src)
            print(" has applyRunningWatch:", "function applyRunningWatch" in src)
            print(" has col-splitter:", "col-splitter" in src)
            switch_fn = src.split("async function switchSession")[1].split("async function refreshSessions")[0]
            print(" switch applyRunningWatch:", "applyRunningWatch" in switch_fn)
            print(" switch run-plan:", "/v1/run-plan" in switch_fn)
            self.assertIn("function startLivePoll", src)
            self.assertIn("function applyRunningWatch", src)
            self.assertIn("applyRunningWatch", switch_fn)
            self.assertNotIn("/v1/run-plan", switch_fn)
            self.assertIn("2000", src.split("function startLivePoll")[1].split("function stopLivePoll")[0])
            self.assertIn("/v1/session/", src.split("function startLivePoll")[1].split("function stopLivePoll")[0])
            self.assertIn("row.running", src)
            self.assertIn("col-splitter", src)
            self.assertIn("col-resize", css)
            self.assertIn("260", src)
            self.assertIn("280", src)
            self.assertIn("qteasy-ai.col-session", src)
            self.assertIn("qteasy-ai.col-artifact", src)
            self.assertIn("MIN_SESSION_COL", src)
            self.assertIn("MIN_ARTIFACT_COL", src)

    def test_elapsed_backfill_nm_and_determinate_bar(self) -> None:
        """切回用 elapsed_s 回填 runStartedAt；Now/对话 N/M；progress 画确定条。"""

        print("\n[TestAiWorkbenchWeb] elapsed backfill N/M determinate bar")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            css = client.get("/static/app.css").text
            apply_fn = src.split("function applyRunningWatch")[1].split("function startLivePoll")[0]
            elapsed_pos = apply_fn.find("elapsed_s")
            busy_pos = apply_fn.find("setBusy(true)")
            print(" elapsed_pos:", elapsed_pos, "busy_pos:", busy_pos)
            self.assertGreaterEqual(elapsed_pos, 0)
            self.assertGreater(busy_pos, elapsed_pos)
            self.assertIn("runStartedAt", apply_fn)
            poll_fn = src.split("function startLivePoll")[1].split("function stopLivePoll")[0]
            print(" poll renderChat:", "renderChat" in poll_fn)
            self.assertIn("renderChat", poll_fn)
            consume = src.split("async function consumeSse")[1].split("function applyLiveStep")[0]
            print(" consume progress:", "progress" in consume)
            self.assertIn("progress", consume)
            self.assertIn("function formatRunClock", src)
            self.assertIn("function progressBarHtml", src)
            self.assertIn("step_index", src)
            self.assertIn("progress-det", src)
            self.assertIn("progress-indet", src)
            self.assertIn("progress-det", css)
            self.assertIn("Working", src)
            self.assertIn("${n}/${m}", src)

    def test_plan_artifact_catalog_merge_open_while_busy(self) -> None:
        """catalog 合并 workspace 与 state；Open Plan 不带 busy disabled。"""

        print("\n[TestAiWorkbenchWeb] plan catalog merge open while busy")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            print(" has mergeArtifactLists:", "function mergeArtifactLists" in src)
            print(" has absorbPlanArtifacts:", "function absorbPlanArtifacts" in src)
            self.assertIn("function mergeArtifactLists", src)
            self.assertIn("function absorbPlanArtifacts", src)
            catalog = src.split("function catalogArtifacts")[1].split("function absorbPlanArtifacts")[0]
            print(" catalog merge:", "mergeArtifactLists" in catalog)
            print(" catalog workspace:", "workspace.artifacts" in catalog)
            print(" catalog state:", "state.artifacts" in catalog)
            self.assertIn("mergeArtifactLists", catalog)
            self.assertIn("workspace.artifacts", catalog)
            self.assertIn("state.artifacts", catalog)
            self.assertNotIn("workspace.artifacts || state.artifacts", catalog)
            ingest = src.split("function ingestDto")[1].split("async function sendQuery")[0]
            print(" ingest absorbPlan:", "absorbPlanArtifacts" in ingest)
            self.assertIn("absorbPlanArtifacts", ingest)
            open_plan = [line for line in src.splitlines() if "data-open-plan" in line]
            print(" open-plan lines:", open_plan)
            self.assertTrue(open_plan)
            for line in open_plan:
                self.assertNotIn("disabled", line)
                self.assertNotIn("${lock}", line)

    def test_mode_badge_label_and_tint(self) -> None:
        """#1：徽章只显示 Ask/Plan/Agent，底色为同色系浅透明，Agent 黑底浅字。"""

        print("\n[TestAiWorkbenchWeb] mode badge label and tint")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            css = client.get("/static/app.css").text
            render_mode = _extract_js_function(src, "renderMode")
            print(" renderMode head:", render_mode[:180].replace("\n", " "))
            self.assertNotIn("Mode:", render_mode)
            self.assertIn("Ask", render_mode)
            self.assertIn("Plan", render_mode)
            self.assertIn("Agent", render_mode)
            self.assertIn("mode-ask", render_mode)
            self.assertIn("mode-plan", render_mode)
            self.assertIn("mode-agent", render_mode)
            mount = src.split("function mountShell")[1].split("function readTranscriptMap")[0]
            print(" mount has Mode: PLAN:", "Mode: PLAN" in mount)
            self.assertNotIn("Mode: PLAN", mount)
            self.assertIn("Plan ▾", mount)
            edit = src.split("class=\"msg user editing\"")[1].split("btn-rewind-cancel")[0]
            print(" edit composer has Mode: prefix:", "Mode:" in edit)
            self.assertNotIn("Mode:", edit)
            self.assertIn("id=\"edit-mode\"", edit)
            for selector, color in (
                ("button.mode-badge.mode-ask", "#3ddc6e"),
                ("button.mode-badge.mode-plan", "#e6c34a"),
                ("button.mode-badge.mode-agent", "var(--bg)"),
            ):
                print(" css selector", selector, "present:", selector in css)
                self.assertIn(selector, css)
                block = css.split(selector, 1)[1].split("}", 1)[0]
                print(" ", selector, "block:", block.strip())
                self.assertIn(color, block)
            ask_block = css.split("button.mode-badge.mode-ask", 1)[1].split("}", 1)[0]
            plan_block = css.split("button.mode-badge.mode-plan", 1)[1].split("}", 1)[0]
            agent_block = css.split("button.mode-badge.mode-agent", 1)[1].split("}", 1)[0]
            self.assertIn("rgba(46, 160, 67, 0.22)", ask_block)
            self.assertIn("rgba(201, 162, 39, 0.22)", plan_block)
            self.assertIn("#f2f2f2", agent_block)
            light_ask = css.split('html[data-theme="light"] button.mode-badge.mode-ask', 1)[1].split("}", 1)[0]
            light_plan = css.split('html[data-theme="light"] button.mode-badge.mode-plan', 1)[1].split("}", 1)[0]
            light_agent = css.split('html[data-theme="light"] button.mode-badge.mode-agent', 1)[1].split("}", 1)[0]
            print(" light ask:", light_ask.strip())
            print(" light plan:", light_plan.strip())
            print(" light agent:", light_agent.strip())
            self.assertIn("#0d6b2e", light_ask)
            self.assertIn("#6b4e00", light_plan)
            self.assertIn("#1a1a1a", light_agent)
            check = css.split("#mode-menu button.active::after", 1)[1].split("}", 1)[0]
            print(" mode check:", check.strip())
            self.assertIn('content: "✓"', check)
            self.assertIn("#edit-mode-menu button.active::after", css)

    def test_tab_label_truncates_close_stays_inside(self) -> None:
        """#8：标签截断，关闭钮 flex-shrink 0，条带仍横滚。"""

        print("\n[TestAiWorkbenchWeb] tab label truncates close stays inside")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            css = client.get("/static/app.css").text
            tabs_fn = _extract_js_function(src, "renderArtifacts")
            print(" renderArtifacts has tab-label:", "tab-label" in tabs_fn)
            self.assertIn("tab-label", tabs_fn)
            self.assertIn("tab-close", tabs_fn)
            tab_block = css.split(".tab {", 1)[1].split("}", 1)[0]
            label_block = css.split(".tab-label", 1)[1].split("}", 1)[0]
            close_block = css.split(".tab-close {", 1)[1].split("}", 1)[0]
            tabs_block = css.split(".tabs {", 1)[1].split("}", 1)[0]
            print(" tab block:", tab_block.strip())
            print(" label block:", label_block.strip())
            print(" close block:", close_block.strip())
            self.assertIn("max-width: 220px", tab_block)
            self.assertIn("overflow: hidden", tab_block)
            self.assertIn("text-overflow: ellipsis", label_block)
            self.assertIn("min-width: 0", label_block)
            self.assertIn("flex-shrink: 0", close_block)
            self.assertIn("overflow-x: auto", tabs_block)
            self.assertIn("flex-wrap: nowrap", tabs_block)

    def test_column_tracks_fold_only_paired_column(self) -> None:
        """#18：折叠 rail 只加宽对话栏；折叠 Workspace 只加宽 Artifacts 且贴右缘。"""

        print("\n[TestAiWorkbenchWeb] column tracks fold paired column")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            fn = _extract_js_function(src, "computeColumnTracks")
            apply_fn = _extract_js_function(src, "applyColumnWidths")
            print(" applyColumnWidths calls computeColumnTracks:", "computeColumnTracks" in apply_fn)
            self.assertIn("computeColumnTracks", apply_fn)
            self.assertNotIn("localStorage.setItem", apply_fn)
            client_width = 2984

            def tracks(rail_collapsed: bool, workspace_collapsed: bool, session_w: int, art_w: int) -> dict:
                call = (
                    "computeColumnTracks({"
                    f"clientWidth:{client_width},"
                    f"railCollapsed:{str(rail_collapsed).lower()},"
                    f"workspaceCollapsed:{str(workspace_collapsed).lower()},"
                    f"sessionW:{session_w},artW:{art_w}"
                    "})"
                )
                result = _eval_js(fn, call)
                print(
                    " tracks",
                    "rail" if rail_collapsed else "rail-open",
                    "ws" if workspace_collapsed else "ws-open",
                    "stored", session_w, art_w,
                    "->", result,
                )
                return result

            open_ratio = tracks(False, False, 0, 0)
            self.assertEqual(open_ratio["rail"], 200)
            self.assertEqual(open_ratio["session"], 1100)
            self.assertEqual(open_ratio["artifact"], 1400)
            self.assertEqual(open_ratio["workspace"], 280)
            self.assertEqual(
                open_ratio["rail"] + open_ratio["session"] + open_ratio["splitter"]
                + open_ratio["artifact"] + open_ratio["workspace"],
                client_width,
            )
            fold_rail = tracks(True, False, 0, 0)
            print(" fold rail artifact delta:", fold_rail["artifact"] - open_ratio["artifact"])
            print(" fold rail session delta:", fold_rail["session"] - open_ratio["session"])
            self.assertEqual(fold_rail["artifact"], open_ratio["artifact"])
            self.assertEqual(fold_rail["session"], open_ratio["session"] + 156)
            self.assertEqual(fold_rail["rail"], 44)
            self.assertEqual(fold_rail["workspace"], 280)
            self.assertEqual(
                fold_rail["rail"] + fold_rail["session"] + fold_rail["splitter"]
                + fold_rail["artifact"] + fold_rail["workspace"],
                client_width,
            )
            fold_ws = tracks(False, True, 0, 0)
            print(" fold ws session delta:", fold_ws["session"] - open_ratio["session"])
            print(" fold ws artifact delta:", fold_ws["artifact"] - open_ratio["artifact"])
            self.assertEqual(fold_ws["session"], open_ratio["session"])
            self.assertEqual(fold_ws["artifact"], open_ratio["artifact"] + 236)
            self.assertEqual(fold_ws["workspace"], 44)
            self.assertEqual(
                fold_ws["rail"] + fold_ws["session"] + fold_ws["splitter"]
                + fold_ws["artifact"] + fold_ws["workspace"],
                client_width,
            )
            stored_open = tracks(False, False, 800, 900)
            self.assertEqual(stored_open["session"], 800)
            self.assertEqual(stored_open["artifact"], 900)
            stored_rail = tracks(True, False, 800, 900)
            print(" stored fold rail session/artifact:", stored_rail["session"], stored_rail["artifact"])
            self.assertEqual(stored_rail["artifact"], 900)
            self.assertEqual(stored_rail["session"], 1756)
            self.assertEqual(
                stored_rail["rail"] + stored_rail["session"] + stored_rail["splitter"]
                + stored_rail["artifact"] + stored_rail["workspace"],
                client_width,
            )
            stored_ws = tracks(False, True, 800, 900)
            print(" stored fold ws session/artifact:", stored_ws["session"], stored_ws["artifact"])
            self.assertEqual(stored_ws["session"], 800)
            self.assertEqual(stored_ws["artifact"], 1936)
            self.assertEqual(stored_ws["workspace"], 44)
            self.assertEqual(
                stored_ws["rail"] + stored_ws["session"] + stored_ws["splitter"]
                + stored_ws["artifact"] + stored_ws["workspace"],
                client_width,
            )
            both = tracks(True, True, 800, 900)
            print(" both folded session/artifact:", both["session"], both["artifact"])
            self.assertEqual(both["session"], 956)
            self.assertEqual(both["artifact"], 1936)
            self.assertEqual(both["rail"], 44)
            self.assertEqual(both["workspace"], 44)
            self.assertEqual(
                both["rail"] + both["session"] + both["splitter"]
                + both["artifact"] + both["workspace"],
                client_width,
            )

    def test_splitter_drag_stores_base_widths(self) -> None:
        """拖动写入的是展开基准宽，折叠后再画回同一显示宽；分割线不因悬停或拖动变色。"""

        print("\n[TestAiWorkbenchWeb] splitter drag stores base widths")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            css = client.get("/static/app.css").text
            convert = _extract_js_function(src, "storedColumnsFromDisplayed")
            tracks_fn = _extract_js_function(src, "computeColumnTracks")
            bind_fn = _extract_js_function(src, "bindColumnSplitter")
            print(" bind uses storedColumnsFromDisplayed:", "storedColumnsFromDisplayed" in bind_fn)
            self.assertIn("storedColumnsFromDisplayed", bind_fn)
            self.assertNotIn('classList.add("dragging")', bind_fn)
            client_width = 2984

            def round_trip(
                rail_collapsed: bool,
                workspace_collapsed: bool,
                session_displayed: int,
                artifact_displayed: int,
            ) -> dict:
                stored_call = (
                    "storedColumnsFromDisplayed({"
                    f"clientWidth:{client_width},"
                    f"railCollapsed:{str(rail_collapsed).lower()},"
                    f"workspaceCollapsed:{str(workspace_collapsed).lower()},"
                    f"sessionDisplayed:{session_displayed},"
                    f"artifactDisplayed:{artifact_displayed}"
                    "})"
                )
                stored = _eval_js(convert, stored_call)
                track_call = (
                    "computeColumnTracks({"
                    f"clientWidth:{client_width},"
                    f"railCollapsed:{str(rail_collapsed).lower()},"
                    f"workspaceCollapsed:{str(workspace_collapsed).lower()},"
                    f"sessionW:{stored['sessionW']},artW:{stored['artW']}"
                    "})"
                )
                painted = _eval_js(tracks_fn, track_call)
                print(
                    " displayed", session_displayed, artifact_displayed,
                    "stored", stored,
                    "painted", painted["session"], painted["artifact"],
                )
                return painted

            still = round_trip(False, True, 800, 1936)
            self.assertEqual(still["session"], 800)
            self.assertEqual(still["artifact"], 1936)
            moved = round_trip(False, True, 810, 1926)
            self.assertEqual(moved["session"], 810)
            self.assertEqual(moved["artifact"], 1926)
            opened = round_trip(False, False, 800, 900)
            self.assertEqual(opened["session"], 800)
            self.assertEqual(opened["artifact"], 900)
            rail_only = round_trip(True, False, 1756, 900)
            self.assertEqual(rail_only["session"], 1756)
            self.assertEqual(rail_only["artifact"], 900)
            splitter_block = css.split(".col-splitter {", 1)[1].split("}", 1)[0]
            print(" splitter css:", splitter_block.strip())
            self.assertIn("cursor: col-resize", splitter_block)
            self.assertIn("background: var(--border)", splitter_block)
            self.assertNotIn(".col-splitter:hover", css)
            self.assertNotIn(".col-splitter.dragging", css)

    def test_session_artifact_tree_groups_under_plan(self) -> None:
        """#16：本 Session 为根；plan 下挂同 plan 的后续 run；无 plan 的产物单独成 Run 节点。"""

        print("\n[TestAiWorkbenchWeb] session artifact tree")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            css = client.get("/static/app.css").text
            fn = "\n".join([
                _extract_js_function(src, name)
                for name in (
                    "artifactMtime",
                    "maxArtifactMtime",
                    "orphanRunLabel",
                    "groupSessionArtifacts",
                )
            ])
            render_ws = _extract_js_function(src, "renderWorkspace")
            tree_cls = _extract_js_function(src, "workspaceTreeClass")
            print(" renderWorkspace uses groupSessionArtifacts:", "groupSessionArtifacts" in render_ws)
            print(" tree class:", tree_cls.replace("\n", " "))
            self.assertIn("groupSessionArtifacts", render_ws)
            self.assertIn("data-art-index", render_ws)
            self.assertIn("data-tree-toggle", render_ws)
            self.assertIn("workspaceTreeClass", render_ws)
            self.assertIn("tree-plan", tree_cls)
            self.assertIn("tree-artifact", tree_cls)
            self.assertIn("is-active", tree_cls)
            self.assertIn("is-open", tree_cls)
            self.assertIn("is-closed", tree_cls)
            open_fn = _extract_js_function(src, "openArtifactTab")
            close_fn = _extract_js_function(src, "closeArtifactTab")
            click_fn = _extract_js_function(src, "onArtifactClick")
            print(" open refreshes tree:", "renderWorkspace" in open_fn)
            print(" close refreshes tree:", "renderWorkspace" in close_fn)
            self.assertIn("renderWorkspace", open_fn)
            self.assertIn("renderWorkspace", close_fn)
            self.assertIn("renderWorkspace", click_fn)
            indent = css.split(".tree-node > ul", 1)[1].split("}", 1)[0]
            plan_open = css.split(".file-tree button.file.tree-plan.is-open", 1)[1].split("}", 1)[0]
            plan_active = css.split(".file-tree button.file.tree-plan.is-active", 1)[1].split("}", 1)[0]
            print(" indent:", indent.strip())
            print(" plan open:", plan_open.strip())
            print(" plan active:", plan_active.strip())
            self.assertIn("padding-left: 28px", indent)
            self.assertIn("#f0e6c8", plan_open)
            self.assertIn("rgba(201, 162, 39, 0.22)", plan_active)
            light_plan_open = css.split('html[data-theme="light"] .file-tree button.file.tree-plan.is-open', 1)[1].split("}", 1)[0]
            print(" light plan open:", light_plan_open.strip())
            self.assertIn("#6b4e00", light_plan_open)
            self.assertIn("var(--text-muted)", css.split(".tree-artifact.is-closed", 1)[1].split("}", 1)[0])
            self.assertIn("var(--bg-active)", css.split(".tree-artifact.is-active", 1)[1].split("}", 1)[0])
            payload = {
                "arts": [
                    {"type": "plan", "run_id": "run-plan-aaa", "title": "Read data"},
                    {"type": "data_table", "run_id": "run-plan-aaa", "title": "preview"},
                    {"type": "data_table", "run_id": "run-exec-bbb", "title": "bars"},
                    {"type": "chart", "run_id": "run-agent-ccc", "title": "agent chart"},
                ],
                "messages": [
                    {"kind": "plan_ready", "payload": {"plan_id": "p1", "run_id": "run-plan-aaa"}},
                    {"kind": "result", "payload": {"plan_id": "p1", "run_id": "run-exec-bbb"}},
                    {"kind": "result", "payload": {"plan_id": "p2", "run_id": "run-agent-ccc"}},
                ],
            }
            call = "groupSessionArtifacts(" + json.dumps(payload["arts"]) + "," + json.dumps(payload["messages"]) + ")"
            tree = _eval_js(fn, call)
            print(" tree:", json.dumps(tree, ensure_ascii=False))
            self.assertEqual(tree["label"], "This session")
            self.assertEqual(len(tree["children"]), 2)
            plan_node = tree["children"][0]
            run_node = tree["children"][1]
            print(" plan children indexes:", [row["art_index"] for row in plan_node["children"]])
            print(" run node:", run_node["kind"], run_node["label"], [row["art_index"] for row in run_node["children"]])
            self.assertEqual(plan_node["kind"], "plan")
            self.assertEqual(plan_node["label"], "Read data")
            self.assertEqual(plan_node["art_index"], 0)
            self.assertEqual(plan_node["run_id"], "run-plan-aaa")
            self.assertEqual([row["art_index"] for row in plan_node["children"]], [1, 2])
            self.assertEqual([row["run_id"] for row in plan_node["children"]], ["run-plan-aaa", "run-exec-bbb"])
            self.assertEqual(run_node["kind"], "run")
            self.assertEqual(run_node["label"], "Run · run-agen")
            self.assertEqual(run_node["run_id"], "run-agent-ccc")
            self.assertEqual([row["art_index"] for row in run_node["children"]], [3])

    def test_artifact_tree_orders_by_mtime_and_buckets(self) -> None:
        """R3：新组在前；今天执行的旧 plan 归 Today；Sessions 复用分组且不重排。"""

        print("\n[TestAiWorkbenchWeb] artifact tree mtime buckets")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            css = client.get("/static/app.css").text
            fn = "\n".join([
                _extract_js_function(src, name)
                for name in (
                    "artifactMtime",
                    "maxArtifactMtime",
                    "orphanRunLabel",
                    "groupSessionArtifacts",
                    "timeBucketLabel",
                    "bucketedNodes",
                )
            ])
            session_fn = _extract_js_function(src, "renderSessionList")
            render_ws = _extract_js_function(src, "renderWorkspace")
            head_fn = _extract_js_function(src, "renderTimeGroupHead")
            now_fn = _extract_js_function(src, "renderNow")
            settings_fn = _extract_js_function(src, "renderSettingsBody")
            print(" session uses bucketedNodes:", "bucketedNodes" in session_fn)
            print(" session sorts:", "sessions.sort" in session_fn)
            print(" workspace uses bucketedNodes:", "bucketedNodes" in render_ws)
            self.assertIn("bucketedNodes", session_fn)
            self.assertNotIn("sessions.sort", session_fn)
            self.assertIn("bucketedNodes", render_ws)
            print(" time-group-head:", "time-group-head" in head_fn, 'class="time-bucket"' in head_fn)
            self.assertIn('class="time-bucket"', head_fn)
            self.assertIn("time-group-head", head_fn)
            self.assertIn("data-tree-toggle", head_fn)
            self.assertIn("renderTimeGroupHead", session_fn)
            self.assertIn("renderTimeGroupHead", render_ws)
            self.assertIn("renderTimeGroupHead", now_fn)
            self.assertIn("renderTimeGroupHead", settings_fn)
            group_names = ("NOW", "AUDIT", "THIS SESSION", "SERVER", "APPEARANCE", "PROVIDERS")
            print(" group names:", [name for name in group_names if name in now_fn or name in render_ws or name in settings_fn])
            self.assertIn("NOW", now_fn)
            self.assertIn("AUDIT", now_fn)
            self.assertLess(now_fn.find("NOW"), now_fn.find("AUDIT"))
            self.assertIn("THIS SESSION", render_ws)
            self.assertIn("SERVER", settings_fn)
            self.assertIn("APPEARANCE", settings_fn)
            self.assertIn("PROVIDERS", settings_fn)
            self.assertLess(settings_fn.find("SERVER"), settings_fn.find("APPEARANCE"))
            self.assertLess(settings_fn.find("APPEARANCE"), settings_fn.find("PROVIDERS"))
            self.assertNotIn("Provider manager", settings_fn)
            self.assertIn("data-art-index", render_ws)
            bucket_css = css.split(".time-bucket {", 1)[1].split("}", 1)[0]
            print(" time-bucket css:", bucket_css.strip())
            self.assertIn("font-size: 11px", bucket_css)
            self.assertNotIn("text-transform", bucket_css)
            head_css = css.split(".time-group-head {", 1)[1].split("}", 1)[0]
            print(" time-group-head css:", head_css.strip())
            print(" bg-group-head dark:", "--bg-group-head: #242424" in css)
            print(" bg-group-head light:", "--bg-group-head: #ececec" in css)
            self.assertIn("background: var(--bg-group-head)", head_css)
            self.assertIn("color: var(--text-muted)", head_css)
            self.assertIn("text-transform: uppercase", head_css)
            self.assertIn("--bg-group-head: #242424", css)
            self.assertIn("--bg-group-head: #ececec", css)
            print(" session toggle:", "session:" in session_fn, "renderTimeGroupHead" in session_fn)
            print(" workspace group:", "workspace:" in render_ws, "time-group" in render_ws)
            self.assertIn("session:", session_fn)
            self.assertIn("workspace:", render_ws)
            self.assertIn('class="time-group"', render_ws)
            self.assertIn("workspace-tree", render_ws)
            self.assertNotIn("tree-bucket", render_ws)
            group_css = css.split(".time-group {", 1)[1].split("}", 1)[0]
            body_css = css.split(".time-group > ul.time-group-body {", 1)[1].split("}", 1)[0]
            print(" time-group:", group_css.strip(), "body:", body_css.strip())
            self.assertIn("padding-left: 0", group_css)
            self.assertIn("padding-left: 28px", body_css)
            self.assertNotIn("background", body_css)
            click_fn = _extract_js_function(src, "onSessionListClick")
            toggle_at = click_fn.find("data-tree-toggle")
            switch_at = click_fn.find("switchSession")
            print(" session click toggle before switch:", toggle_at, switch_at)
            self.assertGreater(toggle_at, 0)
            self.assertLess(toggle_at, switch_at)
            call = """
            (function () {
              const now = new Date(2026, 9, 2, 12, 0, 0);
              const nowMs = now.getTime();
              const at = (month, day) => new Date(2026, month, day, 12, 0, 0).getTime() / 1000;
              const newer = groupSessionArtifacts([
                {type: "plan", run_id: "run_oldplan01aaaa", title: "Old plan", mtime: at(9, 1)},
                {type: "data_table", run_id: "run_5632abcd1234", title: "bars", mtime: at(9, 2),
                 run_title: "Read market data (history / reference / static) · 5632abcd"}
              ], [
                {kind: "plan_ready", payload: {plan_id: "p-old", run_id: "run_oldplan01aaaa"}},
                {kind: "result", payload: {run_id: "run_5632abcd1234", executed: true}}
              ]);
              const lifted = groupSessionArtifacts([
                {type: "plan", run_id: "run_aaa11111bbbb", title: "List built-in strategies · aaa11111", mtime: at(8, 1)},
                {type: "data_table", run_id: "run_exec9999eeee", title: "bars", mtime: at(9, 2)},
                {type: "chart", run_id: "run_cccc3333dddd", title: "agent chart", mtime: at(9, 1),
                 run_title: "Export a k-line chart · cccc3333"}
              ], [
                {kind: "plan_ready", payload: {plan_id: "p1", run_id: "run_aaa11111bbbb"}},
                {kind: "result", payload: {plan_id: "p1", run_id: "run_exec9999eeee", executed: true}},
                {kind: "result", payload: {run_id: "run_cccc3333dddd", executed: true}}
              ]);
              const pack = (tree) => ({
                kinds: tree.children.map((node) => node.kind),
                label: tree.children[0].label,
                buckets: bucketedNodes(tree.children, nowMs).map((bucket) => ({
                  label: bucket.label,
                  kinds: bucket.nodes.map((node) => node.kind)
                }))
              });
              return {
                labels: {
                  today: timeBucketLabel(at(9, 2), nowMs),
                  yesterday: timeBucketLabel(at(9, 1), nowMs),
                  week: timeBucketLabel(at(8, 26), nowMs),
                  monthEdge: timeBucketLabel(at(8, 25), nowMs),
                  month: timeBucketLabel(at(8, 3), nowMs),
                  older: timeBucketLabel(at(8, 2), nowMs),
                  missing: timeBucketLabel(0, nowMs)
                },
                newer: pack(newer),
                lifted: pack(lifted)
              };
            })()
            """
            got = _eval_js(fn, call)
            print(" buckets:", json.dumps(got, ensure_ascii=False))
            self.assertEqual(got["labels"]["today"], "TODAY")
            self.assertEqual(got["labels"]["yesterday"], "YESTERDAY")
            self.assertEqual(got["labels"]["week"], "LAST WEEK")
            self.assertEqual(got["labels"]["monthEdge"], "LAST MONTH")
            self.assertEqual(got["labels"]["month"], "LAST MONTH")
            self.assertEqual(got["labels"]["older"], "OLDER")
            self.assertEqual(got["labels"]["missing"], "OLDER")
            self.assertEqual(got["newer"]["kinds"], ["run", "plan"])
            self.assertEqual(
                got["newer"]["label"],
                "Read market data (history / reference / static) · 5632abcd",
            )
            self.assertEqual(
                got["newer"]["buckets"],
                [
                    {"label": "TODAY", "kinds": ["run"]},
                    {"label": "YESTERDAY", "kinds": ["plan"]},
                ],
            )
            self.assertEqual(got["lifted"]["kinds"], ["plan", "run"])
            self.assertEqual(got["lifted"]["label"], "List built-in strategies · aaa11111")
            self.assertEqual(
                got["lifted"]["buckets"],
                [
                    {"label": "TODAY", "kinds": ["plan"]},
                    {"label": "YESTERDAY", "kinds": ["run"]},
                ],
            )

    def test_user_edit_pencil_inside_bubble(self) -> None:
        """#19：铅笔在用户气泡内最右侧，不占用 You 旁空间。"""

        print("\n[TestAiWorkbenchWeb] user edit pencil inside bubble")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            css = client.get("/static/app.css").text
            user_lines = [
                line for line in src.splitlines()
                if "data-edit-user" in line and "msg user" in line and "editing" not in line
            ]
            print(" user bubble lines:", user_lines)
            self.assertEqual(len(user_lines), 1)
            line = user_lines[0]
            self.assertIn('class="msg-role">You</div>', line)
            bubble_at = line.find('class="bubble"')
            edit_at = line.find("data-edit-user")
            print(" bubble_at:", bubble_at, "edit_at:", edit_at)
            self.assertGreater(bubble_at, 0)
            self.assertGreater(edit_at, bubble_at)
            self.assertNotIn("msg-actions", line)
            self.assertIn("bubble-edit", line)
            edit_block = css.split(".bubble-edit {", 1)[1].split("}", 1)[0]
            hover_block = css.split(".msg.user:hover .bubble-edit", 1)[1].split("}", 1)[0]
            print(" bubble-edit:", edit_block.strip())
            print(" hover:", hover_block.strip())
            self.assertIn("position: absolute", edit_block)
            self.assertIn("right: 6px", edit_block)
            self.assertIn("display: none", edit_block)
            self.assertIn("display: inline-block", hover_block)
            self.assertIn(".msg.user:focus-within .bubble-edit", css)
            user_bubble = css.split(".msg.user .bubble {", 1)[1].split("}", 1)[0]
            print(" user bubble:", user_bubble.strip())
            self.assertIn("position: relative", user_bubble)

    def test_turn_fold_and_rewind_confirm(self) -> None:
        """R2：完成后过程可折叠；无 Retry；历史句要确认，最近一条按是否已执行区分。"""

        print("\n[TestAiWorkbenchWeb] turn fold and rewind confirm")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            css = client.get("/static/app.css").text
            chat = _extract_js_function(src, "renderChat")
            turn = _extract_js_function(src, "renderTurn")
            submit = _extract_js_function(src, "submitRewindEdit")
            action_fn = _extract_js_function(src, "userEditRewindAction")
            rewind = _extract_js_function(src, "rewindUserMessage")
            owns = _extract_js_function(src, "latestTurnOwnsSteps")
            edit_at = rewind.find("editingUserIndex = -1")
            slice_at = rewind.find("transcript.slice(0, index + 1)")
            busy_at = rewind.find("setBusy(true)")
            print(" rewind order edit/slice/busy:", edit_at, slice_at, busy_at)
            self.assertGreater(edit_at, 0)
            self.assertGreater(slice_at, edit_at)
            self.assertGreater(busy_at, slice_at)
            self.assertLess(rewind.find("steps: []"), busy_at)
            self.assertIn("state.plan_card = null", rewind)
            self.assertNotIn("if (busy || backgrounded) return true", owns)
            self.assertIn("runWatchActive()", owns)
            self.assertIn("Planning…", chat)
            self.assertIn('data-testid="planning-wait"', chat)
            print(" renderChat calls renderTurn:", "renderTurn(" in chat)
            print(" renderTurn calls renderSteps:", "renderSteps()" in turn)
            print(" submit gates confirm:", "action.confirm && !window.confirm(action.dialog)" in submit)
            self.assertIn("renderTurn(", chat)
            self.assertNotIn("renderSteps()", chat)
            self.assertIn("renderSteps()", turn)
            self.assertIn("Show process", src)
            self.assertIn("process-fold", css)
            self.assertIn("action.confirm && !window.confirm(action.dialog)", submit)
            self.assertNotIn("window.confirm", action_fn)
            http_src = (Path(__file__).resolve().parents[1] / "qteasy_ai" / "workbench" / "http_app.py").read_text()
            self.assertIn(
                '"RUN_FAILED": "Edit the blue message (pencil) and send it again."',
                http_src,
            )
            dialog = (
                "Later turns will be dropped from this session. "
                "Files in ai/runs/ stay on disk; this session will no longer track them."
            )
            wrapped = f"const REWIND_LATER_TURNS = {json.dumps(dialog)};\n{action_fn}"

            def decide(messages: list, index: int) -> dict:
                call = f"userEditRewindAction({json.dumps(messages)}, {index})"
                result = _eval_js(wrapped, call)
                print(" rewind action", index, result)
                return result

            latest_open = decide(
                [{"kind": "user_text", "text": "list strategies"}, {"kind": "clarify", "text": "Which?"}],
                0,
            )
            self.assertEqual(latest_open["confirm"], False)
            self.assertEqual(latest_open["discard"], False)
            self.assertEqual(latest_open["label"], "Send")
            latest_done = decide(
                [
                    {"kind": "user_text", "text": "run it"},
                    {"kind": "result", "text": "Done", "payload": {"run_id": "run-1", "executed": True}},
                ],
                0,
            )
            self.assertEqual(latest_done["confirm"], False)
            self.assertEqual(latest_done["discard"], True)
            self.assertEqual(latest_done["label"], "Discard and resend")
            history_plain = decide(
                [
                    {"kind": "user_text", "text": "first"},
                    {"kind": "ask", "text": "answer"},
                    {"kind": "user_text", "text": "second"},
                ],
                0,
            )
            self.assertEqual(history_plain["confirm"], True)
            self.assertEqual(history_plain["discard"], False)
            self.assertEqual(history_plain["label"], "Send")
            self.assertIn("ai/runs/", history_plain["dialog"])
            history_ran = decide(
                [
                    {"kind": "user_text", "text": "first"},
                    {"kind": "result", "text": "Done", "payload": {"run_id": "run-9", "executed": True}},
                    {"kind": "user_text", "text": "second"},
                ],
                0,
            )
            self.assertEqual(history_ran["confirm"], True)
            self.assertEqual(history_ran["discard"], True)
            self.assertIn("ai/runs/", history_ran["dialog"])

    def test_result_card_opens_artifact_by_title(self) -> None:
        """结果卡按 run_id 列产物按钮；同 run 两张表的页签键含 title。"""

        print("\n[TestAiWorkbenchWeb] result artifact buttons")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            src = client.get("/static/app.js").text
            key_fn = src.split("function artifactKey")[1].split("function openArtifactTab")[0]
            open_fn = src.split("function openArtifactTab")[1].split("function closeArtifactTab")[0]
            buttons = src.split("function resultArtifactButtons")[1].split("function renderVisibleMessage")[0]
            click = src.split("const artBtn = t.closest")[1].split("if (t.dataset.example)")[0]
            print(" key fn:\n", key_fn)
            print(" buttons head:", buttons[:400])
            print(" click uses title:", "data-open-artifact-title" in click)
            self.assertIn('type === "plan" || type === "settings"', key_fn)
            self.assertIn("art.title", key_fn)
            self.assertIn("title: String(art.title", open_fn)
            self.assertIn('!== "plan"', buttons)
            self.assertIn("data-open-artifact-title", buttons)
            self.assertIn("if (!rows.length) return", buttons)
            self.assertNotIn("not ready", buttons.lower())
            self.assertIn("data-open-artifact-title", click)
            self.assertIn("openArtifactTab(art)", click)


if __name__ == "__main__":
    unittest.main()
