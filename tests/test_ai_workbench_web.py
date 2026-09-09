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
            self.assertIn("btn-code-confirm", js.text)
            self.assertIn("text/event-stream", js.text)
            self.assertIn("btn-retry", js.text)
            self.assertIn("next_action", js.text)
            self.assertIn("persistTranscript", js.text)
            self.assertIn("data-now-edit", js.text)
            self.assertIn("Switched to", js.text)
            self.assertEqual(css.status_code, 200)
            self.assertIn("grid-template-columns", css.text)
            print(" css has slot-tag:", "slot-tag" in css.text)
            self.assertIn("slot-tag", css.text)
            self.assertIn("artifact-toolbar", css.text)

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
                self.assertIn("clarification", kinds)
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
