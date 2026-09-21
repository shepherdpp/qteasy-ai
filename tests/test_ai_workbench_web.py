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
import tempfile
import unittest
from pathlib import Path

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.workbench.http_app import STATIC_DIR, create_app

_FIXTURE = Path(__file__).resolve().parent / "ai_corpus" / "workbench_ui_states.json"
_TYPES = Path(__file__).resolve().parents[1] / "web" / "src" / "types.ts"


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
            self.assertIn("Mode:", js.text)
            self.assertIn("plan-card", js.text)
            self.assertIn("clarification-form", js.text)
            self.assertIn("step-list", js.text)
            self.assertIn("isComposing", js.text)
            self.assertIn("ctrlKey", js.text)
            self.assertIn("textarea", js.text)
            self.assertIn("Workspace", js.text)
            self.assertNotIn("btn-toggle-workspace", js.text)
            self.assertIn("btn-collapse-workspace", js.text)
            self.assertIn("composer-meta", js.text)
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
            self.assertIn('followUp("skip")', js.text)
            self.assertIn("followUp(t.dataset.clarifyOption)", js.text)
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
            self.assertIn("bubble editing", js.text)
            self.assertIn("Working…", js.text)
            self.assertNotIn("busy-label", js.text)
            self.assertIn("data-now-edit", js.text)
            self.assertIn("Switched to", js.text)
            self.assertIn("g7-slot", js.text)
            self.assertIn("btn-abandon-trial", js.text)
            self.assertIn("btn-abandon-open", js.text)
            self.assertIn("btn-kb-write", js.text)
            self.assertIn("/v1/open/abandon-trial", js.text)
            self.assertIn("/v1/open/abandon-job", js.text)
            self.assertIn("/v1/kb/write", js.text)
            self.assertIn("design-card", js.text)
            self.assertIn("trial-queue", js.text)
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
            self.assertIn('followUp("skip")', src)
            self.assertIn("followUp(t.dataset.clarifyOption)", src)
            self.assertIn("mode-menu", src)
            self.assertIn("mode-dropdown", src)
            self.assertIn("btn-mode-menu", src)
            composer_meta = src.split("composer-meta")[1].split("query-input")[0] if "composer-meta" in src else ""
            print(" composer-meta has mode-group:", "mode-group" in composer_meta)
            print(" composer-meta has mode-menu:", "mode-menu" in composer_meta)
            self.assertIn("mode-menu", composer_meta)
            self.assertNotIn('<div class="mode-group">', composer_meta)
            self.assertIn("payload.answer", src)
            self.assertIn("Answered:", src)
            self.assertIn("shouldShowLiveClarify", src)
            self.assertIn("clarification-form", src)
            self.assertIn("plan-card", src)
            self.assertIn("liveClarifyMessage", src)
            self.assertIn("Confirm is optional", src)
            self.assertIn("design-card", src)
            self.assertIn("btn-kb-write", src)
            print(" css has mode-dropdown:", "mode-dropdown" in css.text)
            print(" css has mode-menu:", "mode-menu" in css.text)
            self.assertIn("mode-dropdown", css.text)
            self.assertIn("mode-menu", css.text)

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


if __name__ == "__main__":
    unittest.main()
