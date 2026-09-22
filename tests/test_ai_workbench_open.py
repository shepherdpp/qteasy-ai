# coding=utf-8
# ======================================
# File: test_ai_workbench_open.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-10
# Desc:
# Unittest：G.7 工作台无设计环操作面
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.workbench.http_app import create_app
from qteasy_ai.workbench.mapper import map_assistant_payload


class TestAiWorkbenchOpen(unittest.TestCase):
    """无 active_design、无设计环活卡。"""

    def _client(self, temp_dir: str):
        """同一 MemoryStore 的 TestClient。"""

        from starlette.testclient import TestClient

        store = MemoryStore(base_dir=temp_dir)
        assistant = QteasyAssistant(memory_store=store, registry=build_default_registry())
        return TestClient(create_app(assistant=assistant)), store, assistant

    def test_explore_has_no_design_card(self) -> None:
        """探索句不再投影 design_card。"""

        print("\n[TestAiWorkbenchOpen] no design_card")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, asst = self._client(temp_dir)
            res = client.post(
                "/v1/plan",
                json={
                    "query": "explore a useful momentum factor for hs300",
                    "session_id": "g7-web",
                },
            )
            body = res.json()
            kinds = [item.get("kind") for item in (body.get("messages") or [])]
            state = asst.session_store.load("g7-web")
            print(" status:", res.status_code)
            print(" kinds:", kinds)
            print(" sidebar design:", (body.get("sidebar") or {}).get("design"))
            print(" dumped:", sorted(state.to_dict().keys()))
            self.assertEqual(res.status_code, 200)
            self.assertNotIn("design_card", kinds)
            self.assertIsNone((body.get("sidebar") or {}).get("design"))
            self.assertNotIn("active_design", state.to_dict())

    def test_ask_has_no_confirmable_plan_card(self) -> None:
        """Ask 路径仍不得 plan_card.confirmable。"""

        print("\n[TestAiWorkbenchOpen] ask no confirmable")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, _asst = self._client(temp_dir)
            res = client.post("/v1/ask", json={"query": "什么是 qteasy"})
            body = res.json()
            print(" mode:", body.get("mode"))
            print(" plan_card:", body.get("plan_card"))
            self.assertEqual(body.get("mode"), "ask")
            card = body.get("plan_card")
            self.assertTrue(card is None or card.get("confirmable") is False)

    def test_abandon_routes_do_not_create_design(self) -> None:
        """回退路由不再写设计态。"""

        print("\n[TestAiWorkbenchOpen] abandon routes retired")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, asst = self._client(temp_dir)
            sid = "g7-http-ab"
            client.post(
                "/v1/plan",
                json={"query": "list built-in strategies", "session_id": sid},
            )
            trial = client.post("/v1/open/abandon-trial", json={"session_id": sid})
            state = asst.session_store.load(sid)
            print(" after trial:", trial.status_code)
            self.assertEqual(trial.status_code, 404)
            opened = client.post("/v1/open/abandon-job", json={"session_id": sid})
            print(" after open:", opened.status_code, state.session_id)
            self.assertEqual(opened.status_code, 404)
            self.assertEqual(state.session_id, sid)
            self.assertNotIn("active_design", state.to_dict())

    def test_kb_write_without_confirm_is_4xx(self) -> None:
        """KB write 无确认 4xx。"""

        print("\n[TestAiWorkbenchOpen] kb write 4xx")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store, _asst = self._client(temp_dir)
            sid = "g7-kb-http"
            denied = client.post("/v1/kb/write", json={"session_id": sid})
            print(" denied:", denied.status_code, denied.json())
            self.assertEqual(denied.status_code, 400)
            target = store.user_kb_dir / "raw" / "factors" / "momentum.md"
            print(" exists after deny:", target.exists())
            self.assertFalse(target.exists())

    def test_mapper_ask_payload_has_no_design_card(self) -> None:
        """Ask mapper 不把设计卡混进问答。"""

        print("\n[TestAiWorkbenchOpen] mapper ask")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                registry=build_default_registry(),
            )
            payload = asst.ask("什么是 qteasy", response_style="raw")
            state = map_assistant_payload(payload, query="什么是 qteasy")
            kinds = [item.kind for item in state.messages]
            print(" kinds:", kinds)
            self.assertIn("ask", kinds)
            self.assertNotIn("design_card", kinds)
            self.assertTrue(state.plan_card is None or not state.plan_card.confirmable)


if __name__ == "__main__":
    unittest.main()
