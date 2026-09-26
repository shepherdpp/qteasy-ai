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
            self.assertIn("btn-code-confirm", js.text)
            self.assertIn("text/event-stream", js.text)
            self.assertIn("btn-retry", js.text)
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
            self.assertIn('id="${sendId}">Send</button>', src)
            self.assertIn('id="btn-rewind-cancel">Cancel</button>', src)
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
            self.assertIn("Stopped watching this run. The server may still finish", src)
            switch_fn = src.split("async function switchSession")[1].split("async function refreshSessions")[0]
            self.assertNotIn("|| busy", switch_fn)
            self.assertIn("dropRunWatch", switch_fn)
            create_fn = src.split("async function createSession")[1].split("async function switchSession")[0]
            print(" create calls dropRunWatch:", "dropRunWatch" in create_fn)
            self.assertIn("dropRunWatch", create_fn)
            consume = src.split("async function consumeSse")[1].split("function applyLiveStep")[0]
            print(" consume heartbeat:", "heartbeat" in consume)
            self.assertIn("heartbeat", consume)
            print(" css progress-indet:", "progress-indet" in css)
            self.assertIn("progress-indet", css)
            self.assertIn("now-run-status", src)

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
            fn = _extract_js_function(src, "groupSessionArtifacts")
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
            self.assertEqual(run_node["label"], "Run run-agen")
            self.assertEqual(run_node["run_id"], "run-agent-ccc")
            self.assertEqual([row["art_index"] for row in run_node["children"]], [3])

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


if __name__ == "__main__":
    unittest.main()
