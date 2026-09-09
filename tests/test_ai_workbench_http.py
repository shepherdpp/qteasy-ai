# coding=utf-8
# ======================================
# File: test_ai_workbench_http.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-07
# Desc:
# Unittest for Starlette workbench adapter (G.3)
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.workbench.http_app import create_app


class TestAiWorkbenchHttp(unittest.TestCase):
    """G.3：HTTP 只调 Assistant，与 CLI 同 runs/。"""

    def _client(self, temp_dir: str, **profile):
        """同一 MemoryStore 的 TestClient。"""

        from starlette.testclient import TestClient

        store = MemoryStore(base_dir=temp_dir)
        if profile:
            store.save_profile(dict(profile))
        assistant = QteasyAssistant(memory_store=store, registry=build_default_registry())
        app = create_app(assistant=assistant)
        return TestClient(app), store, assistant

    def test_plan_persists_same_runs(self) -> None:
        """POST /v1/plan 的 plan_id 能在 runs/ 找到。"""

        print("\n[TestAiWorkbenchHttp] plan persists")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store, _asst = self._client(temp_dir)
            res = client.post("/v1/plan", json={"query": "list built-in strategies"})
            body = res.json()
            print(" status_code:", res.status_code)
            print(" execution:", body.get("execution"))
            print(" plan_id:", (body.get("plan_card") or {}).get("plan_id"))
            self.assertEqual(res.status_code, 200)
            plan_id = (body.get("plan_card") or {}).get("plan_id")
            self.assertTrue(plan_id)
            found = store.find_run_by_plan_id(plan_id)
            print(" found plan_id:", (found.get("plan") or {}).get("plan_id"))
            self.assertEqual((found.get("plan") or {}).get("plan_id"), plan_id)
            self.assertEqual((found.get("execution") or {}).get("status"), "dry_run")

    def test_run_plan_does_not_rehybrid(self) -> None:
        """先 plan A，再 plan B，run-plan A 仍执行 A 的 skill。"""

        print("\n[TestAiWorkbenchHttp] run-plan no rehybrid")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store, _asst = self._client(temp_dir)
            first = client.post("/v1/plan", json={"query": "list built-in strategies"}).json()
            plan_id = first["plan_card"]["plan_id"]
            client.post("/v1/plan", json={"query": "帮我下载日线"})
            executed = client.post("/v1/run-plan", json={"plan_id": plan_id})
            body = executed.json()
            skills = [s["skill_name"] for s in (body.get("execution") or {}).get("steps") or []]
            print(" plan_id:", plan_id)
            print(" execute skills:", skills)
            print(" status:", (body.get("execution") or {}).get("status"))
            self.assertEqual(executed.status_code, 200)
            self.assertIn("qt.ai.strategy_meta.list", skills)
            self.assertNotIn("qt.ai.data.refill_basic_equity_and_index", skills)

    def test_plan_without_run_plan_not_success(self) -> None:
        """只 plan 不 run-plan → 无 success execute。"""

        print("\n[TestAiWorkbenchHttp] plan only dry_run")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store, _asst = self._client(temp_dir)
            client.post("/v1/plan", json={"query": "list built-in strategies"})
            statuses = []
            for run_id in store.list_runs():
                rec = store.load_run(run_id)
                statuses.append((rec.get("execution") or {}).get("status"))
            print(" statuses:", statuses)
            self.assertTrue(statuses)
            self.assertTrue(all(item == "dry_run" for item in statuses))

    def test_ask_hits_kb_no_skill(self) -> None:
        """POST /v1/ask 命中 what_is_qteasy，无 skill handler 产物。"""

        print("\n[TestAiWorkbenchHttp] ask kb")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, _asst = self._client(temp_dir)
            res = client.post("/v1/ask", json={"query": "什么是 qteasy"})
            body = res.json()
            print(" mode:", body.get("mode"))
            print(" sources:", body.get("sources"))
            print(" artifacts:", body.get("artifacts"))
            self.assertEqual(body.get("mode"), "ask")
            self.assertIn("what_is_qteasy", body.get("sources") or [])
            self.assertEqual(body.get("artifacts") or [], [])
            kinds = [m["kind"] for m in body.get("messages") or []]
            self.assertNotIn("plan_card", kinds)

    def test_agent_auto_refill_blocked(self) -> None:
        """POST /v1/run + agent_auto + allow_refill=false → 门控英文错误。"""

        print("\n[TestAiWorkbenchHttp] allow_refill blocked")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, _asst = self._client(
                temp_dir,
                agent={"allow_refill": False, "allow_backtest": False, "allow_optimize": False},
            )
            res = client.post(
                "/v1/run",
                json={
                    "query": "download daily data from 20180101 to 20231231",
                    "session_id": "auto-refill",
                    "agent_auto": True,
                },
            )
            body = res.json()
            print(" execution:", body.get("execution"))
            print(" error:", body.get("error"))
            self.assertEqual((body.get("execution") or {}).get("status"), "dry_run")
            err = body.get("error") or {}
            self.assertEqual(err.get("code"), "ALLOW_GATE_BLOCKED")
            self.assertRegex(str(err.get("message") or ""), r"[A-Za-z]")

    def test_missing_and_unknown_plan_id(self) -> None:
        """缺 plan_id / 未知 id → 4xx 英文，不改走 query run。"""

        print("\n[TestAiWorkbenchHttp] plan_id errors")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store, _asst = self._client(temp_dir)
            missing = client.post("/v1/run-plan", json={})
            unknown = client.post("/v1/run-plan", json={"plan_id": "plan_does_not_exist"})
            print(" missing:", missing.status_code, missing.json())
            print(" unknown:", unknown.status_code, unknown.json())
            self.assertEqual(missing.status_code, 400)
            self.assertIn("plan_id", str(missing.json().get("error", {}).get("message") or "").lower())
            self.assertEqual(unknown.status_code, 404)
            self.assertRegex(str(unknown.json().get("error", {}).get("message") or ""), r"[A-Za-z]")
            self.assertEqual(store.list_runs(), [])

    def test_session_followup_keeps_intent(self) -> None:
        """同一 session_id 改槽不换 Job。"""

        print("\n[TestAiWorkbenchHttp] session followup")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, asst = self._client(temp_dir)
            first = client.post(
                "/v1/plan",
                json={
                    "query": "帮我写一个基于 20/60 日均线金叉死叉的择时策略，并用 2015–2020 年沪深300做回测",
                    "session_id": "s-web",
                },
            ).json()
            second = client.post(
                "/v1/plan",
                json={"query": "把慢线改成 50", "session_id": "s-web"},
            ).json()
            sess = client.get("/v1/session/s-web").json()
            job1 = (first.get("sidebar") or {}).get("active_intent") or {}
            job2 = (second.get("sidebar") or {}).get("active_intent") or {}
            print(" job1:", job1, "job2:", job2)
            print(" session sidebar:", sess.get("sidebar"))
            self.assertEqual(job1.get("job"), "strategy.builder")
            self.assertEqual(job2.get("job"), "strategy.builder")
            loaded = asst.session_store.load("s-web")
            print(" loaded job:", loaded.active_intent)
            self.assertEqual((loaded.active_intent or {}).get("job"), "strategy.builder")

    def test_sse_has_step_or_fallback_list(self) -> None:
        """execute 后 SSE 至少一条 step_status，或同步 steps 非空。"""

        print("\n[TestAiWorkbenchHttp] sse events")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, _asst = self._client(temp_dir)
            planned = client.post("/v1/plan", json={"query": "list built-in strategies"}).json()
            plan_id = planned["plan_card"]["plan_id"]
            executed = client.post("/v1/run-plan", json={"plan_id": plan_id}).json()
            run_id = executed.get("run_id")
            steps = (executed.get("execution") or {}).get("steps") or []
            print(" run_id:", run_id, "sync steps:", steps)
            self.assertTrue(steps)
            events = client.get(f"/v1/runs/{run_id}/events")
            print(" sse:", events.status_code, events.text[:240])
            self.assertEqual(events.status_code, 200)
            self.assertIn("step_status", events.text)

    def test_list_sessions_and_workspace_tree(self) -> None:
        """GET /v1/sessions 与 /v1/workspace 只读列举 MemoryStore 目录。"""

        print("\n[TestAiWorkbenchHttp] sessions and workspace")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store, asst = self._client(temp_dir)
            client.post("/v1/plan", json={"query": "list built-in strategies", "session_id": "web-demo"})
            listed = client.get("/v1/sessions")
            body = listed.json()
            ids = [row.get("session_id") for row in (body.get("sessions") or [])]
            print(" sessions status:", listed.status_code)
            print(" session ids:", ids)
            self.assertEqual(listed.status_code, 200)
            self.assertTrue(body.get("ok"))
            self.assertIn("web-demo", ids)
            demo = store.strategies_dir / "demo.py"
            demo.write_text("class Demo:\n    pass\n", encoding="utf-8")
            tree = client.get("/v1/workspace")
            payload = tree.json()
            print(" workspace status:", tree.status_code)
            print(" tree names:", [item.get("name") for item in (payload.get("trees") or [])])
            self.assertEqual(tree.status_code, 200)
            names = {item.get("name") for item in (payload.get("trees") or [])}
            self.assertEqual(names, {"runs", "strategies", "user_kb"})
            strat = next(item for item in payload["trees"] if item["name"] == "strategies")
            child_names = [child.get("name") for child in (strat.get("children") or [])]
            print(" strategy files:", child_names)
            self.assertIn("demo.py", child_names)
            preview = client.get("/v1/workspace/file", params={"path": "strategies/demo.py"})
            print(" file status:", preview.status_code, preview.json().get("content", "")[:40])
            self.assertEqual(preview.status_code, 200)
            self.assertIn("class Demo", preview.json().get("content") or "")
            outside = client.get("/v1/workspace/file", params={"path": "../secret.py"})
            print(" outside:", outside.status_code, outside.json())
            self.assertEqual(outside.status_code, 404)
            loaded = asst.session_store.load("web-demo")
            print(" loaded session_id:", loaded.session_id)
            self.assertEqual(loaded.session_id, "web-demo")


if __name__ == "__main__":
    unittest.main()
