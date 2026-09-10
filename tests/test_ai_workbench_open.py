# coding=utf-8
# ======================================
# File: test_ai_workbench_open.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-10
# Desc:
# Unittest for G.7 workbench DTO / HTTP open loop
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.workbench.http_app import create_app
from qteasy_ai.workbench.mapper import map_assistant_payload


class TestAiWorkbenchOpen(unittest.TestCase):
    """设计环消息、Ask 无确认卡、试错 run-plan、回退路由、KB write 确认。"""

    def _client(self, temp_dir: str):
        """同一 MemoryStore 的 TestClient。"""

        from starlette.testclient import TestClient

        store = MemoryStore(base_dir=temp_dir)
        assistant = QteasyAssistant(memory_store=store, registry=build_default_registry())
        return TestClient(create_app(assistant=assistant)), store, assistant

    def test_design_message_is_not_ask_text(self) -> None:
        """设计环消息 kind ≠ ask_text。"""

        print("\n[TestAiWorkbenchOpen] design_card kind")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, _asst = self._client(temp_dir)
            res = client.post(
                "/v1/plan",
                json={
                    "query": "explore a useful momentum factor for hs300",
                    "session_id": "g7-web",
                },
            )
            body = res.json()
            kinds = [item.get("kind") for item in (body.get("messages") or [])]
            print(" status:", res.status_code)
            print(" kinds:", kinds)
            print(" plan_card:", body.get("plan_card"))
            print(" sidebar design:", (body.get("sidebar") or {}).get("design"))
            self.assertEqual(res.status_code, 200)
            self.assertIn("design_card", kinds)
            self.assertNotEqual(kinds, ["user_text", "ask_text"])
            card = body.get("plan_card")
            self.assertTrue(card is None or not card.get("confirmable") or not card.get("steps"))

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

    def test_trial_card_can_run_plan(self) -> None:
        """试错卡可 run-plan。"""

        print("\n[TestAiWorkbenchOpen] trial run-plan")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store, _asst = self._client(temp_dir)
            client.post(
                "/v1/plan",
                json={
                    "query": "explore a useful momentum factor for hs300",
                    "session_id": "g7-run",
                },
            )
            trial = client.post(
                "/v1/plan",
                json={"query": "try IC on this factor", "session_id": "g7-run"},
            ).json()
            plan_id = (trial.get("plan_card") or {}).get("plan_id")
            print(" trial plan_id:", plan_id)
            print(" confirmable:", (trial.get("plan_card") or {}).get("confirmable"))
            self.assertTrue(plan_id)
            self.assertTrue((trial.get("plan_card") or {}).get("confirmable"))
            executed = client.post("/v1/run-plan", json={"plan_id": plan_id, "session_id": "g7-run"})
            body = executed.json()
            skills = [item.get("skill_name") for item in ((body.get("execution") or {}).get("steps") or [])]
            print(" execute status:", (body.get("execution") or {}).get("status"))
            print(" execute skills:", skills)
            self.assertEqual(executed.status_code, 200)
            self.assertIn("qt.ai.research.factor_ic_summary", skills)
            self.assertTrue(store.find_run_by_plan_id(plan_id))

    def test_abandon_routes_change_session(self) -> None:
        """回退路由改 session。"""

        print("\n[TestAiWorkbenchOpen] abandon routes")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, asst = self._client(temp_dir)
            sid = "g7-http-ab"
            client.post(
                "/v1/plan",
                json={"query": "explore a useful momentum factor for hs300", "session_id": sid},
            )
            client.post("/v1/plan", json={"query": "try IC on this factor", "session_id": sid})
            trial = client.post("/v1/open/abandon-trial", json={"session_id": sid})
            state = asst.session_store.load(sid)
            print(" after trial:", trial.status_code, state.current_trial_plan_id, bool(state.active_design))
            self.assertEqual(trial.status_code, 200)
            self.assertEqual(state.current_trial_plan_id, "")
            self.assertIsNotNone(state.active_design)
            opened = client.post("/v1/open/abandon-job", json={"session_id": sid})
            state = asst.session_store.load(sid)
            print(" after open:", opened.status_code, state.active_design, state.session_id)
            self.assertEqual(opened.status_code, 200)
            self.assertIsNone(state.active_design)
            self.assertEqual(state.session_id, sid)

    def test_kb_write_without_confirm_is_4xx(self) -> None:
        """KB write 无确认 4xx。"""

        print("\n[TestAiWorkbenchOpen] kb write 4xx")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store, _asst = self._client(temp_dir)
            sid = "g7-kb-http"
            client.post(
                "/v1/plan",
                json={"query": "explore a useful momentum factor for hs300", "session_id": sid},
            )
            client.post("/v1/plan", json={"query": "lock this spec", "session_id": sid})
            denied = client.post("/v1/kb/write", json={"session_id": sid})
            print(" denied:", denied.status_code, denied.json())
            self.assertEqual(denied.status_code, 400)
            target = store.user_kb_dir / "raw" / "factors" / "momentum.md"
            print(" exists after deny:", target.exists())
            self.assertFalse(target.exists())
            ok = client.post("/v1/kb/write", json={"session_id": sid, "confirm": True})
            print(" ok:", ok.status_code, target.exists())
            self.assertEqual(ok.status_code, 200)
            self.assertTrue(target.is_file())

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
            self.assertIn("ask_text", kinds)
            self.assertNotIn("design_card", kinds)
            self.assertTrue(state.plan_card is None or not state.plan_card.confirmable)


if __name__ == "__main__":
    unittest.main()
